"""Core models for the ad server."""
import datetime
import logging
import math
from collections import Counter
from collections import defaultdict
from collections import OrderedDict

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import IntegrityError
from django.db import models
from django.template import engines
from django.template.loader import get_template
from django.utils.crypto import get_random_string
from django.utils.html import mark_safe
from django.utils.translation import ugettext_lazy as _
from django_countries import countries
from django_countries.fields import CountryField
from jsonfield import JSONField
from user_agents import parse

from .constants import CAMPAIGN_TYPES
from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import PAID_CAMPAIGN
from .constants import VIEWS
from .utils import anonymize_ip_address
from .utils import calculate_ctr
from .utils import calculate_ecpm
from .utils import get_ad_day
from .utils import get_client_id
from .utils import get_client_ip
from .utils import get_client_user_agent
from .utils import get_geolocation
from .validators import AdvertisementValidator
from .validators import TargetingParametersValidator


log = logging.getLogger(__name__)  # noqa


def default_flight_end_date():
    return datetime.date.today() + datetime.timedelta(days=30)


class IndestructibleQuerySet(models.QuerySet):

    """A queryset object without the delete option."""

    def delete(self):
        """Always raises ``IntegrityError``."""
        raise IntegrityError


class IndestructibleManager(models.Manager):

    """A model manager that generates ``IndestructibleQuerySets``."""

    def get_queryset(self):
        return IndestructibleQuerySet(self.model, using=self._db)


class IndestructibleModel(models.Model):

    """A model that disallows the delete method or deleting at the queryset level."""

    objects = IndestructibleManager()

    def delete(self, using=None, keep_parents=False):
        """Always raises ``IntegrityError``."""
        raise IntegrityError

    class Meta:
        abstract = True


class Publisher(IndestructibleModel):

    """
    A publisher that displays advertising from the ad server.

    A publisher represents a site or collection of sites that displays advertising.
    Advertisers can opt-in to displaying ads on different publishers.

    An example of a publisher would be Read the Docs, our first publisher.
    """

    pub_date = models.DateTimeField(_("Publication date"), auto_now_add=True)
    modified_date = models.DateTimeField(_("Modified date"), auto_now=True)

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Publisher Slug"), max_length=200)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name


class Advertiser(IndestructibleModel):

    """An advertiser who buys advertising from the ad server."""

    pub_date = models.DateTimeField(_("Publication date"), auto_now_add=True)
    modified_date = models.DateTimeField(_("Modified date"), auto_now=True)

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Publisher Slug"), max_length=200)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name


class Campaign(IndestructibleModel):

    """
    A collection of advertisements (:py:class:`~Advertisement`) from the same advertiser.

    A campaign is typically made up of one or more :py:class:`~Flight` which are themselves
    groups of advertisements including details common among the ads.

    Campaigns have a campaign type which distinguishes paid, house and community ads.

    Since campaigns contain important historical data around tracking how we bill
    and report to customers, they cannot be deleted once created.
    """

    pub_date = models.DateTimeField(_("Publication date"), auto_now_add=True)
    modified_date = models.DateTimeField(_("Modified date"), auto_now=True)

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Campaign Slug"), max_length=200)

    advertiser = models.ForeignKey(
        Advertiser,
        blank=True,
        null=True,
        default=None,
        related_name="campaigns",
        on_delete=models.PROTECT,
        help_text=_(
            "The advertiser for this campaign. "
            "A campaign without an advertiser is run by the ad network."
        ),
    )
    publishers = models.ManyToManyField(
        Publisher,
        related_name="flights",
        blank=True,
        help_text=_(
            "Ads for this campaign are eligible for display on these publishers"
        ),
    )

    campaign_type = models.CharField(
        _("Campaign Type"), max_length=20, choices=CAMPAIGN_TYPES, default=PAID_CAMPAIGN
    )

    max_sale_value = models.DecimalField(
        _("Max Sale Value"),
        max_digits=8,
        decimal_places=2,
        default=None,
        blank=True,
        null=True,
        help_text=_(
            "If set, ads will not be displayed if (cpc * total_clicks) "
            "+ (cpm * total_views / 1000) for all ads exceeds this"
        ),
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name

    def get_absolute_url(self):
        # TODO: ad report link
        return "#"

    def ad_count(self):
        return Advertisement.objects.filter(flight__campaign=self).count()

    def total_value(self):
        """Calculate total cost/revenue for all ads/flights in this campaign."""
        # Check for a cached value that would come from an annotated queryset
        if hasattr(self, "campaign_total_value"):
            return self.campaign_total_value or 0.0

        ads = Advertisement.objects.filter(flight__campaign=self)
        aggregation = AdImpression.objects.filter(advertisement__in=ads).aggregate(
            total_value=models.Sum(
                (models.F("clicks") * models.F("advertisement__flight__cpc"))
                + (models.F("views") * models.F("advertisement__flight__cpm") / 1000.0),
                output_field=models.FloatField(),
            )
        )["total_value"]

        return aggregation or 0.0

    def daily_reports(
        self, start_date=None, end_date=None, name_filter=None, inactive=True
    ):
        """
        Generates a report of clicks, views, & cost for a given time period for the Campaign.

        :param start_date: the start date to generate the report (or all time)
        :param end_date: the end date for the report (ignored if no `start_date`)
        :param name_filter: ignore ads that don't match the specified string
        :param inactive: if True, show inactive ads in addition to live ones
        :return: A dictionary containing a list of days for the report
            and an aggregated total
        """
        report = {"days": [], "total": {}}

        impressions = AdImpression.objects.filter(advertisement__flight__campaign=self)
        if name_filter:
            impressions = impressions.filter(advertisement__name__icontains=name_filter)
        if not inactive:
            impressions = impressions.filter(advertisement__live=True)
        if start_date:
            impressions = impressions.filter(date__gte=start_date)
            if end_date:
                impressions = impressions.filter(date__lte=end_date)
        impressions = impressions.select_related(
            "advertisement", "advertisement__flight"
        )

        days = OrderedDict()
        for impression in impressions:
            if impression.date not in days:
                days[impression.date] = defaultdict(int)

            days[impression.date]["date"] = impression.date
            days[impression.date]["views"] += impression.views
            days[impression.date]["clicks"] += impression.clicks
            days[impression.date]["cost"] += (
                impression.clicks * float(impression.advertisement.flight.cpc)
            ) + (impression.views * float(impression.advertisement.flight.cpm) / 1000.0)
            days[impression.date]["ctr"] = calculate_ctr(
                days[impression.date]["clicks"], days[impression.date]["views"]
            )
            days[impression.date]["ecpm"] = calculate_ecpm(
                days[impression.date]["cost"], days[impression.date]["views"]
            )

        report["days"] = days.values()

        report["total"]["views"] = sum(day["views"] for day in report["days"])
        report["total"]["clicks"] = sum(day["clicks"] for day in report["days"])
        report["total"]["cost"] = sum(day["cost"] for day in report["days"])
        report["total"]["ctr"] = calculate_ctr(
            report["total"]["clicks"], report["total"]["views"]
        )
        report["total"]["ecpm"] = calculate_ecpm(
            report["total"]["cost"], report["total"]["views"]
        )

        return report


class Flight(IndestructibleModel):

    """
    A flight is a collection of :py:class:`~Advertisement` objects.

    Effectively a flight is a single "ad buy". So if an advertiser wants to
    buy $2000 worth of ads at $2 CPC and run 5 variations, they would have 5
    :py:class:`~Advertisement` objects in a single :py:class:`~Flight`.
    Flights are associated with a :py:class:`~Campaign` and so they have a
    single advertiser.

    At this level, we control:

    * Sold clicks (maximum clicks across all ads in this flight)
    * CPC/CPM which could be 0
    * Targeting parameters (programming language, geo, etc)
    * Start and end date (the end date is a soft target)
    * Whether the flight is live or not

    Since flights contain important historical data around tracking how we bill
    and report to customers, they cannot be deleted once created.
    """

    HIGHEST_PRIORITY_MULTIPLIER = 100
    LOWEST_PRIORITY_MULTIPLIER = 1

    pub_date = models.DateTimeField(_("Publication date"), auto_now_add=True)
    modified_date = models.DateTimeField(_("Modified date"), auto_now=True)

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Flight Slug"), max_length=200)
    start_date = models.DateField(
        _("Start Date"),
        default=datetime.date.today,
        help_text=_("This ad will not be shown before this date"),
    )
    end_date = models.DateField(
        _("End Date"),
        default=default_flight_end_date,
        help_text=_("The target end date for the ad (it may go after this date)"),
    )
    live = models.BooleanField(_("Live"), default=False)
    priority_multiplier = models.IntegerField(
        _("Priority Multiplier"),
        default=LOWEST_PRIORITY_MULTIPLIER,
        validators=[
            MinValueValidator(LOWEST_PRIORITY_MULTIPLIER),
            MaxValueValidator(HIGHEST_PRIORITY_MULTIPLIER),
        ],
        help_text="Multiplies chance of showing this flight's ads [{},{}]".format(
            LOWEST_PRIORITY_MULTIPLIER, HIGHEST_PRIORITY_MULTIPLIER
        ),
    )

    # CPC
    cpc = models.DecimalField(
        _("Cost Per Click"), max_digits=5, decimal_places=2, default=0
    )
    sold_clicks = models.IntegerField(_("Sold Clicks"), default=0)

    # CPM
    cpm = models.DecimalField(
        _("Cost Per 1k Impressions"), max_digits=5, decimal_places=2, default=0
    )
    sold_impressions = models.IntegerField(_("Sold Impressions"), default=0)

    campaign = models.ForeignKey(
        Campaign, related_name="flights", on_delete=models.PROTECT
    )

    targeting_parameters = JSONField(
        _("Targeting parameters"),
        blank=True,
        null=True,
        validators=[TargetingParametersValidator()],
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name

    @property
    def included_countries(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_countries", [])

    @property
    def included_state_provinces(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_state_provinces", [])

    @property
    def included_metro_codes(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_metro_codes", [])

    @property
    def excluded_countries(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("exclude_countries", [])

    @property
    def included_programming_languages(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_programming_languages", [])

    @property
    def excluded_programming_languages(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("exclude_programming_languages", [])

    @property
    def included_projects(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_projects", [])

    @property
    def included_keywords(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_keywords", [])

    @property
    def included_themes(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_themes", [])

    @property
    def included_builders(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_builders", [])

    def get_include_countries_display(self):
        included_country_codes = self.included_countries
        countries_dict = dict(countries)
        return [countries_dict.get(cc, "Unknown") for cc in included_country_codes]

    def get_exclude_countries_display(self):
        excluded_country_codes = self.excluded_countries
        countries_dict = dict(countries)
        return [countries_dict.get(cc, "Unknown") for cc in excluded_country_codes]

    def show_to_geo(self, country_code, state_province_code=None, metro_code=None):
        """
        Check if a flight is valid for a given country code.

        A ``country_code`` of ``None`` (meaning the user's country is unknown)
        will not match a flight with any ``include_countries`` but wont be
        excluded from any ``exclude_countries``
        """
        if self.included_countries and country_code not in self.included_countries:
            return False
        if (
            self.included_state_provinces
            and state_province_code not in self.included_state_provinces
        ):
            return False
        if self.included_metro_codes and metro_code not in self.included_metro_codes:
            return False
        if country_code in self.excluded_countries:
            return False

        return True

    def show_to_keywords(self, keywords):
        """
        Check if a flight is valid for a given keywords.

        If *any* keywords match, it is considered valid
        """
        keyword_set = set(keywords)
        if self.included_keywords and not keyword_set.intersection(
            self.included_keywords
        ):
            return False

        return True

    def sold_days(self):
        return (self.end_date - self.start_date).days

    def days_remaining(self):
        """Number of days left in a flight."""
        days_since_start = (get_ad_day().date() - self.start_date).days
        return max(0, int(self.sold_days()) - int(days_since_start))

    def views_per_day(self):
        if not self.live:
            return 0

        days_left = self.days_remaining()
        views_remaining = self.views_remaining()
        if days_left <= 0:
            return views_remaining

        return views_remaining // days_left

    def clicks_per_day(self):
        if not self.live:
            return 0

        days_left = self.days_remaining()
        clicks_remaining = self.clicks_remaining()
        if days_left <= 0:
            return clicks_remaining

        return clicks_remaining // days_left

    def views_today(self):
        # Check for a cached value that would come from an annotated queryset
        if hasattr(self, "flight_views_today"):
            return self.flight_views_today or 0

        aggregation = AdImpression.objects.filter(
            advertisement__in=self.advertisements.all(), date=get_ad_day().date()
        ).aggregate(total_views=models.Sum("views"))["total_views"]

        # The aggregation can be `None` if there are no impressions
        return aggregation or 0

    def clicks_today(self):
        # Check for a cached value that would come from an annotated queryset
        if hasattr(self, "flight_clicks_today"):
            return self.flight_clicks_today or 0

        aggregation = AdImpression.objects.filter(
            advertisement__in=self.advertisements.all(), date=get_ad_day().date()
        ).aggregate(total_clicks=models.Sum("clicks"))["total_clicks"]

        # The aggregation can be `None` if there are no impressions
        return aggregation or 0

    def views_needed_today(self):
        if not self.live or self.sold_impressions <= 0:
            return 0

        if self.days_remaining() > 0:
            return self.views_per_day() - self.views_today()

        return self.views_remaining()

    def clicks_needed_today(self):
        """Calculates clicks needed based on the impressions this flight's ads have."""
        if not self.live or self.sold_clicks <= 0:
            return 0

        if self.days_remaining() > 0:
            return self.clicks_per_day() - self.clicks_today()

        return self.clicks_remaining()

    def weighted_clicks_needed_today(self):
        """
        Calculates clicks needed taking into account a flight's priority.

        For the purpose of clicks needed, 1000 impressions = 1 click (for CPM ads)
        """
        impressions_needed = 0

        # This is naive but we are counting a click as being worth 1,000 views
        impressions_needed += math.ceil(self.views_needed_today() / 1000.0)
        impressions_needed += self.clicks_needed_today()

        return impressions_needed * self.priority_multiplier

    def total_clicks(self):
        # Check for a cached value that would come from an annotated queryset
        if hasattr(self, "flight_total_clicks"):
            return self.flight_total_clicks or 0

        aggregation = AdImpression.objects.filter(
            advertisement__in=self.advertisements.all()
        ).aggregate(total_clicks=models.Sum("clicks"))["total_clicks"]

        # The aggregation can be `None` if there are no impressions
        return aggregation or 0

    def total_views(self):
        # Check for a cached value that would come from an annotated queryset
        if hasattr(self, "flight_total_views"):
            return self.flight_total_views or 0

        aggregation = AdImpression.objects.filter(
            advertisement__in=self.advertisements.all()
        ).aggregate(total_views=models.Sum("views"))["total_views"]

        # The aggregation can be `None` if there are no impressions
        return aggregation or 0

    def clicks_remaining(self):
        return max(0, self.sold_clicks - self.total_clicks())

    def views_remaining(self):
        return max(0, self.sold_impressions - self.total_views())


class AdType(models.Model):

    """
    A type of advertisement including such parameters as the amount of text and images size.

    Many ad types are industry standards from the Interactive Advertising Bureau (IAB).
    Some publishers prefer native ads that are custom sized for their needs.

    See https://www.iab.com/newadportfolio/
    """

    pub_date = models.DateTimeField(_("Publication date"), auto_now_add=True)
    modified_date = models.DateTimeField(_("Modified date"), auto_now=True)

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Slug"), max_length=200)

    # image specifications
    # image_height/width of null means it accepts any value (not recommended)
    has_image = models.BooleanField(_("Has image?"), default=True)
    image_width = models.PositiveIntegerField(blank=True, null=True)
    image_height = models.PositiveIntegerField(blank=True, null=True)

    # text specifications
    has_text = models.BooleanField(_("Has text?"), default=True)
    max_text_length = models.PositiveIntegerField(
        blank=True, null=True, help_text=_("Max length does not include HTML tags")
    )
    allowed_html_tags = models.CharField(
        _("Allowed HTML tags"),
        blank=True,
        max_length=255,
        default="a b strong i em code",
        help_text=_("Space separated list of allowed HTML tag names"),
    )

    publisher = models.ForeignKey(
        Publisher, blank=True, null=True, help_text=_("For publisher-specific ad types")
    )

    template = models.TextField(
        _("Ad template"),
        blank=True,
        null=True,
        help_text=_("Override the template for rendering this ad type"),
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name


class Advertisement(IndestructibleModel):

    """
    A single advertisement creative.

    Multiple ads are organized into a :py:class:`~Flight` which has details
    common across the ad such as targeting and desired number of clicks.

    At this level, we store:

    * The HTML for the ad
    * An optional image to go with the ad
    * The display type of the ad (footer, sidebar, etc.)
    * Whether the ad is "live"
    * The link to the advertisers landing page

    Since ads contain important historical data around tracking how we bill
    and report to customers, they cannot be deleted once created.
    """

    pub_date = models.DateTimeField(_("Publication date"), auto_now_add=True)
    modified_date = models.DateTimeField(_("Modified date"), auto_now=True)

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Slug"), max_length=200)
    text = models.TextField(
        _("Text"),
        blank=True,
        help_text=_("Different ad types have different text requirements"),
    )
    link = models.URLField(_("Link URL"), max_length=255)
    image = models.ImageField(
        _("Image"),
        max_length=255,
        upload_to="images/%Y/%m/",
        blank=True,
        null=True,
        help_text=_("Sized according to the ad type"),
    )
    live = models.BooleanField(_("Live"), default=False)
    flight = models.ForeignKey(
        Flight, related_name="advertisements", on_delete=models.PROTECT
    )

    # If this is null, no validation on the image or text is done
    # And the ad has primitive styling
    ad_type = models.ForeignKey(
        AdType, blank=True, null=True, default=None, on_delete=models.PROTECT
    )

    class Meta:
        ordering = ("slug", "-live")

    def __str__(self):
        """Simple override."""
        return self.name

    def save(self, *args, **kwargs):  # pylint: disable=arguments-differ
        # Ensure that the model is fully validated before saving
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        AdvertisementValidator()(self)

    def get_absolute_url(self):
        # TODO: ad report link
        return "#"

    def as_dict(self):
        """A dict respresentation of this for JSON encoding."""
        nonce = get_random_string()  # 12 chars alphanumeric

        return {
            "id": self.slug,
            "text": self.text,
            "html": self.render_ad(),
            "image": self.image.url if self.image else None,
            "link": self.link,
            "nonce": nonce,
        }

    def cache_key(self, impression_type, nonce):
        assert impression_type in IMPRESSION_TYPES + ("publisher",)
        return "advertisement:{id}:{nonce}:{type}".format(
            id=self.slug, nonce=nonce, type=impression_type
        )

    def incr(self, impression_type, publisher):
        """Add to the number of times this action has been performed, stored in the DB."""
        assert impression_type in IMPRESSION_TYPES
        day = get_ad_day().date()
        impression, _ = self.impressions.get_or_create(publisher=publisher, date=day)

        setattr(impression, impression_type, models.F(impression_type) + 1)
        impression.save()

    def _record_base(self, request, model, publisher, url):
        ip_address = get_client_ip(request)
        user_agent = get_client_user_agent(request)
        client_id = get_client_id(request)
        parsed_ua = parse(user_agent)

        if model != Click and settings.ADSERVER_DO_NOT_TRACK:
            # For compliance with DNT,
            # we can't store UAs indefinitely from a user merely browsing
            user_agent = None

        # Get country data for this request
        country = None
        if hasattr(request, "geo"):
            # This is set in all API requests that use the GeoIpMixin
            country = request.geo.country_code
        else:
            geo_data = get_geolocation(ip_address)
            if geo_data:
                country = geo_data["country_code"]

        obj = model.objects.create(
            publisher=publisher,
            ip=anonymize_ip_address(ip_address),
            user_agent=user_agent,
            client_id=client_id,
            country=country,
            url=url,
            # Derived user agent data
            browser_family=parsed_ua.browser.family,
            os_family=parsed_ua.os.family,
            is_bot=parsed_ua.is_bot,
            is_mobile=parsed_ua.is_mobile,
            # Page info
            advertisement=self,
        )
        return obj

    def track_click(self, request, publisher, url):
        """Store click data in the DB."""
        self.incr(CLICKS, publisher)
        self._record_base(request, Click, publisher, url)

    def track_view(self, request, publisher, url):
        """
        Store view data in the DB.

        Views are only stored if ``settings.ADSERVER_RECORD_VIEWS=True``
        For a large scale ad server, writing a database record per ad view
        is not feasible
        """
        self.incr(VIEWS, publisher)

        if settings.ADSERVER_RECORD_VIEWS:
            self._record_base(request, View, publisher, url)
        else:
            log.debug("Not recording ad view (settings.ADSERVER_RECORD_VIEWS=False)")

    def offer_ad(self, publisher):
        """
        Offer to display this ad on a specific publisher.

        Tracks an offer in the database and sets various cache variables
        """
        # The time after an ad has been offered where impressions (clicks) won't count
        offer_time_limit = 60 * 60 * 4  # 4 hours

        data = self.as_dict()
        nonce = data["nonce"]
        self.incr(OFFERS, publisher)
        # Set validation cache
        for impression_type in [VIEWS, CLICKS]:
            cache.set(
                self.cache_key(impression_type=impression_type, nonce=nonce),
                0,  # Number of times used. Make this an int so we can detect multiple uses
                offer_time_limit,
            )

        # Cache the publisher slug for this nonce
        # This is needed so we can later retrieve the publisher if this ad/nonce is viewed/clicked
        cache.set(
            self.cache_key(impression_type="publisher", nonce=nonce),
            publisher.slug,
            offer_time_limit,
        )

        return data

    def get_publisher(self, nonce):
        publisher = None
        publisher_slug = cache.get(
            self.cache_key(impression_type="publisher", nonce=nonce), None
        )

        if publisher_slug:
            publisher = Publisher.objects.filter(slug=publisher_slug).first()

        return publisher

    def is_valid_nonce(self, impression_type, nonce):
        """
        Returns true if this nonce (from ``offer_ad``) is valid for a given impression type (click, view).

        A nonce is valid if it was generated recently (hasn't timed out)
        and hasn't already been used
        """
        return (
            cache.get(
                self.cache_key(impression_type=impression_type, nonce=nonce), None
            )
            == 0
        )

    def invalidate_nonce(self, impression_type, nonce):
        cache.delete(self.cache_key(impression_type=impression_type, nonce=nonce))

    def view_ratio(self, day=None):
        if not day:
            day = get_ad_day()
        impression = self.impressions.get_or_create(date=day)[0]
        return impression.view_ratio

    def click_ratio(self, day=None):
        if not day:
            day = get_ad_day()
        impression = self.impressions.get_or_create(date=day)[0]
        return impression.click_ratio

    def clicks_today(self, day=None):
        return self.clicks_shown_today(day)

    def clicks_shown_today(self, day=None):
        if not day:
            day = get_ad_day()
        impression = self.impressions.get_or_create(date=day)[0]
        return float(impression.clicks)

    def views_shown_today(self, day=None):
        if not day:
            day = get_ad_day()
        impression = self.impressions.get_or_create(date=day)[0]
        return float(impression.views)

    def total_views(self):
        aggregate = self.impressions.aggregate(models.Sum("views"))["views__sum"]
        if aggregate:
            return aggregate
        return 0

    def total_clicks(self):
        aggregate = self.impressions.aggregate(models.Sum("clicks"))["clicks__sum"]
        if aggregate:
            return aggregate
        return 0

    def total_click_ratio(self):
        return calculate_ctr(self.total_clicks(), self.total_views())

    def daily_reports(self, start_date=None, end_date=None):
        """
        Generates a report of clicks, views, & cost for a given time period for this ad.

        :param start_date: the start date to generate the report (or all time)
        :param end_date: the end date for the report (ignored if no `start_date`)
        :return: A dictionary containing a list of days for the report
            and an aggregated total
        """
        report = {"days": [], "total": {}}

        impressions = self.impressions

        if start_date:
            impressions = impressions.filter(date__gte=start_date)
            if end_date:
                impressions = impressions.filter(date__lte=end_date)
        else:
            impressions = impressions.all()

        for impression in impressions:
            report["days"].append(
                {
                    "date": impression.date,
                    "views": impression.views,
                    "clicks": impression.clicks,
                    "cost": (
                        (impression.clicks * float(self.flight.cpc))
                        + (impression.views * float(self.flight.cpm) / 1000.0)
                    ),
                    "ctr": impression.click_ratio,
                }
            )

        report["total"]["views"] = sum(day["views"] for day in report["days"])
        report["total"]["clicks"] = sum(day["clicks"] for day in report["days"])
        report["total"]["cost"] = sum(day["cost"] for day in report["days"])
        report["total"]["ctr"] = calculate_ctr(
            report["total"]["clicks"], report["total"]["views"]
        )

        return report

    def detail_report(self, start_date, end_date=None):
        report = {
            "country_breakdown": Counter(Unknown=0),
            "language_breakdown": Counter(Unknown=0),
        }

        clicks = self.clicks.filter(date__gte=start_date)
        if end_date:
            clicks = clicks.filter(date__lte=end_date)

        for click in clicks:
            language = country = "Unknown"

            if click.country:
                country = str(click.country.name)
            report["country_breakdown"][country] += 1
            report["language_breakdown"][language] += 1

        return report

    def render_links(self, link=None):
        """
        Include the link in the html text.

        Does not include any callouts such as "ads served ethically"
        """
        url = link or self.link
        return mark_safe(
            self.text.replace(
                "<a>", '<a href="%s" rel="nofollow" target="_blank">' % url
            )
        )

    def render_ad(self):
        template = get_template("adserver/advertisement.html")
        if self.ad_type and self.ad_type.template:
            template = engines["django"].from_string(self.ad_type.template)

        return template.render(
            {
                "ad": self,
                "image_url": self.image,
                "link_url": self.link,
                "text_as_html": self.render_links(),
            }
        ).strip()


class BaseImpression(models.Model):

    """Statistics for tracking."""

    date = models.DateField(_("Date"))

    # Offers include cases where the server returned an ad
    # but the client didn't load it
    # or the client didn't qualify as a view (staff, blacklisted, etc.)
    offers = models.IntegerField(
        _("Offers"),
        default=0,
        help_text=_(
            "The number of times an ad was proposed by the ad server. "
            "The client may not load the ad (a view) for a variety of reasons "
        ),
    )

    # Views & Clicks don't count actions that are blacklisted, done by staff, bots, etc.
    views = models.IntegerField(
        _("Views"),
        default=0,
        help_text=_("Number of times the ad was legitimately viewed"),
    )
    clicks = models.IntegerField(
        _("Clicks"),
        default=0,
        help_text=_("Number of times the ad was legitimately clicked"),
    )

    class Meta:
        abstract = True

    @property
    def view_ratio(self):
        if self.offers == 0:
            return 0  # Don't divide by 0
        return float(float(self.views) / float(self.offers) * 100)

    @property
    def click_ratio(self):
        if self.views == 0:
            return 0  # Don't divide by 0
        return "%.3f" % float(float(self.clicks) / float(self.views) * 100)


class AdImpression(BaseImpression):

    """
    Track stats around how successful this ad has been.

    Indexed one per ad per day per publisher.
    """

    publisher = models.ForeignKey(
        Publisher, null=True, blank=True, on_delete=models.PROTECT
    )
    advertisement = models.ForeignKey(
        Advertisement, related_name="impressions", on_delete=models.PROTECT
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date")
        verbose_name_plural = _("Ad impressions")

    def __str__(self):
        """Simple override."""
        return "%s on %s" % (self.advertisement, self.date)


class AdBase(IndestructibleModel):

    """A base class for data on ad views and clicks."""

    date = models.DateTimeField(_("Created date"), auto_now_add=True)

    publisher = models.ForeignKey(
        Publisher, null=True, blank=True, on_delete=models.PROTECT
    )

    # Click Data
    ip = models.GenericIPAddressField(_("Ip Address"))  # should be anonymized
    user_agent = models.CharField(
        _("User Agent"), max_length=1000, blank=True, null=True
    )
    client_id = models.CharField(_("Client ID"), max_length=1000, blank=True, null=True)
    country = CountryField(null=True)
    url = models.CharField(_("Page URL"), max_length=10000, blank=True, null=True)

    # Fields derived from the user agent - these should not be user identifiable
    browser_family = models.CharField(
        _("Browser Family"), max_length=1000, blank=True, null=True, default=None
    )
    os_family = models.CharField(
        _("Operating System Family"),
        max_length=1000,
        blank=True,
        null=True,
        default=None,
    )
    is_bot = models.BooleanField(default=False)
    is_mobile = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def __str__(self):
        """Simple override."""
        return "%s on %s (%s)" % (self._meta.object_name, self.advertisement, self.url)

    def get_absolute_url(self):
        return self.url


class Click(AdBase):

    """Contains data on ad clicks."""

    advertisement = models.ForeignKey(
        Advertisement, max_length=255, related_name="clicks", on_delete=models.PROTECT
    )


class View(AdBase):

    """Contains data on ad views."""

    advertisement = models.ForeignKey(
        Advertisement, max_length=255, related_name="views", on_delete=models.PROTECT
    )
