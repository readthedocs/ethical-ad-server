"""Core models for the ad server."""
import datetime
import html
import logging
import math
import re
import uuid
from collections import Counter

import bleach
import djstripe.models as djstripe_models
import pytz
from django.conf import settings
from django.core.cache import cache
from django.core.cache import caches
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import IntegrityError
from django.db import models
from django.db import transaction
from django.db.models.constraints import UniqueConstraint
from django.template import engines
from django.template.loader import get_template
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.html import mark_safe
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from django_extensions.db.models import TimeStampedModel
from djstripe.enums import InvoiceStatus
from jsonfield import JSONField
from simple_history.models import HistoricalRecords
from user_agents import parse

from .constants import CAMPAIGN_TYPES
from .constants import CLICKS
from .constants import DECISIONS
from .constants import FLIGHT_STATE_CURRENT
from .constants import FLIGHT_STATE_PAST
from .constants import FLIGHT_STATE_UPCOMING
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import PAID
from .constants import PAID_CAMPAIGN
from .constants import PAYOUT_OPENCOLLECTIVE
from .constants import PAYOUT_PAYPAL
from .constants import PAYOUT_STATUS
from .constants import PAYOUT_STRIPE
from .constants import PENDING
from .constants import PUBLISHER_PAYOUT_METHODS
from .constants import VIEWS
from .utils import anonymize_ip_address
from .utils import calculate_ctr
from .utils import COUNTRY_DICT
from .utils import generate_absolute_url
from .utils import get_ad_day
from .utils import get_client_country
from .utils import get_client_id
from .utils import get_client_ip
from .utils import get_client_user_agent
from .utils import get_domain_from_url
from .utils import is_proxy_ip
from .validators import TargetingParametersValidator
from .validators import TopicPricingValidator
from .validators import TrafficFillValidator

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


class Topic(TimeStampedModel, models.Model):

    """Topics able to be targeted by the ad server."""

    # Topics are cached for 30m
    # We don't want to repeatedly hit the database for data that rarely changes
    CACHE_KEY = "keyword-topic-mapping"
    CACHE_TIMEOUT = 60 * 30

    name = models.CharField(max_length=255)
    slug = models.SlugField(_("Slug"), max_length=200, unique=True)

    selectable = models.BooleanField(
        default=False,
        help_text=_("Whether advertisers can select this region for new flights"),
    )

    def __str__(self):
        """String representation."""
        return self.name

    @classmethod
    def load_from_cache(cls):
        """Load keyword and topic mappings from the cache or database."""
        topics = caches[settings.CACHE_LOCAL_ALIAS].get(cls.CACHE_KEY)
        if not topics:
            topics = cls._load_db()
        return topics

    @classmethod
    def _load_db(cls):
        """Load keyword and topic mappings from database and cache it."""
        # topic -> list of keyword slugs
        topics = {}

        for topic in Topic.objects.all().prefetch_related():
            topics[topic.slug] = [kw.slug for kw in topic.keywords.all()]

        caches[settings.CACHE_LOCAL_ALIAS].set(
            cls.CACHE_KEY, value=topics, timeout=cls.CACHE_TIMEOUT
        )

        return topics


class Keyword(TimeStampedModel, models.Model):

    """A keyword for a topic on the ad server."""

    slug = models.SlugField(_("Slug"), max_length=200, unique=True)

    topics = models.ManyToManyField(
        Topic,
        blank=True,
        related_name="keywords",
    )

    def __str__(self):
        """String representation."""
        return self.slug


class Region(TimeStampedModel, models.Model):

    """A region able to be targeted by the ad server."""

    # Regions are cached for 30m
    # We don't want to repeatedly hit the database for data that rarely changes
    CACHE_KEY = "country-region-mapping"
    CACHE_TIMEOUT = 60 * 30

    NON_OVERLAPPING_REGIONS = (
        "us-ca",
        "western-europe",
        "eastern-europe",
        "aus-nz",
        "wider-apac",
        "latin-america",
        "africa",
        "south-asia",
        "exclude",
        "global",  # This does overlap but is only used when none of the others apply
    )

    name = models.CharField(max_length=255)
    slug = models.SlugField(_("Slug"), max_length=200, unique=True)

    selectable = models.BooleanField(
        default=False,
        help_text=_("Whether advertisers can select this region for new flights"),
    )

    prices = JSONField(
        _("Topic prices"),
        blank=True,
        null=True,
        validators=[TopicPricingValidator()],
        help_text=_("Topic pricing matrix for this region"),
    )

    # Lower order takes precedence
    # When mapping country to a single region, the lowest order region is returned
    order = models.PositiveSmallIntegerField(
        _("Order"),
        default=0,
        help_text=_(
            "When mapping country to a single region, the lowest order region is returned."
        ),
    )

    def __str__(self):
        """String representation."""
        return self.name

    @classmethod
    def load_from_cache(cls):
        """Load country to region mappings from the cache or database."""
        regions = caches[settings.CACHE_LOCAL_ALIAS].get(cls.CACHE_KEY)
        if not regions:
            regions = cls._load_db()
        return regions

    @classmethod
    def _load_db(cls):
        """Load country to region mapping from the DB and cache it."""
        # Maps region (in order) -> list of countries
        regions = {}

        for region in (
            Region.objects.all().order_by("order").prefetch_related("countryregion_set")
        ):
            countries = [cr.country.code for cr in region.countryregion_set.all()]
            regions[region.slug] = countries

        caches[settings.CACHE_LOCAL_ALIAS].set(
            cls.CACHE_KEY, value=regions, timeout=cls.CACHE_TIMEOUT
        )

        return regions

    @classmethod
    def get_region_from_country_code(cls, country):
        """Get the *nonoverlapping* region slug from the country code. Returns "other" if no others apply."""
        regions = cls.load_from_cache()

        for slug in regions:
            if slug not in cls.NON_OVERLAPPING_REGIONS:
                continue

            if country in regions[slug]:
                return slug

        return "global"

    @staticmethod
    def get_pricing():
        pricing = {}
        for region in Region.objects.filter(selectable=True):
            if region.prices:
                pricing[region.slug] = region.prices

        return pricing


class CountryRegion(TimeStampedModel, models.Model):

    """Countries in targeted regions."""

    country = CountryField()
    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        """String representation."""
        return f"{self.country.name}"


class Publisher(TimeStampedModel, IndestructibleModel):

    """
    A publisher that displays advertising from the ad server.

    A publisher represents a site or collection of sites that displays advertising.
    Advertisers can opt-in to displaying ads on different publishers.

    An example of a publisher would be Read the Docs, our first publisher.
    """

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Publisher Slug"), max_length=200, unique=True)

    revenue_share_percentage = models.FloatField(
        default=70.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_("Percentage of advertising revenue shared with this publisher"),
    )

    default_keywords = models.CharField(
        _("Default keywords"),
        max_length=250,
        help_text=_("A CSV of default keywords for this property. Used for targeting."),
        default="",
        blank=True,
    )
    allow_api_keywords = models.BooleanField(
        default=True,
        help_text=_(
            "Whether to allow the ad API/client to send its own keywords for targeting."
        ),
    )

    # If this is blank, all domains are allowed
    allowed_domains = models.CharField(
        _("Allowed domains"),
        max_length=1024,
        help_text=_(
            "A space separated list of domains where the publisher's ads can appear"
        ),
        default="",
        blank=True,
    )

    unauthed_ad_decisions = models.BooleanField(
        default=True,
        help_text=_(
            "Whether this publisher allows unauthenticated ad decision API requests (eg. JSONP)"
        ),
    )
    disabled = models.BooleanField(
        default=False,
        help_text=_("Completely disable this publisher"),
    )

    saas = models.BooleanField(
        default=False,
        help_text=_(
            "This published is configured as a SaaS customer. They will be billed by usage instead of paid out."
        ),
    )

    # Default to False so that we can use this as an "approved" flag for publishers
    allow_paid_campaigns = models.BooleanField(_("Allow paid campaigns"), default=False)
    allow_affiliate_campaigns = models.BooleanField(
        _("Allow affiliate campaigns"), default=False
    )
    allow_community_campaigns = models.BooleanField(
        _("Allow community campaigns"),
        default=True,
        help_text="These are unpaid campaigns that support non-profit projects in our community. Shown only when no paid ads are available",
    )
    allow_house_campaigns = models.BooleanField(
        _("Allow house campaigns"),
        default=True,
        help_text="These are ads for EthicalAds itself. Shown only when no paid ads are available.",
    )
    daily_cap = models.DecimalField(
        _("Daily maximum earn cap"),
        max_digits=8,
        decimal_places=2,
        default=None,
        blank=True,
        null=True,
        help_text=_(
            "A daily maximum this publisher can earn after which only unpaid ads are shown."
        ),
    )

    allow_multiple_placements = models.BooleanField(
        default=False,
        help_text=_("Can this publisher have multiple placements on the same pageview"),
    )

    # Payout information
    skip_payouts = models.BooleanField(
        _("Skip payouts"),
        default=False,
        help_text=_(
            "Enable this to temporarily disable payouts. They will be processed again once you uncheck this."
        ),
    )
    payout_method = models.CharField(
        max_length=100,
        choices=PUBLISHER_PAYOUT_METHODS,
        blank=True,
        null=True,
        default=None,
    )
    djstripe_account = models.ForeignKey(
        djstripe_models.Account,
        verbose_name=_("Stripe connected account"),
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        default=None,
    )

    # Deprecated - migrate to `stripe_account`
    stripe_connected_account_id = models.CharField(
        _("Stripe connected account ID"),
        max_length=200,
        blank=True,
        null=True,
        default=None,
    )
    open_collective_name = models.CharField(
        _("Open Collective name"), max_length=200, blank=True, null=True, default=None
    )
    paypal_email = models.EmailField(
        _("PayPal email address"), blank=True, null=True, default=None
    )

    # Record additional details to the offer for this publisher
    # This can be used for publishers where their traffic needs more scrutiny
    record_offer_details = models.BooleanField(
        default=False,
        help_text=_("Record additional offer details for this publisher"),
    )

    # This overrides settings.ADSERVER_RECORD_VIEWS for a specific publisher
    # Details of each ad view are written to the database.
    record_views = models.BooleanField(
        default=False,
        help_text=_("Record each ad view from this publisher to the database"),
    )
    record_placements = models.BooleanField(
        default=False, help_text=_("Record placement impressions for this publisher")
    )
    # This defaults to False, so publishers have to ask for it.
    render_pixel = models.BooleanField(
        default=False,
        help_text=_(
            "Render ethical-pixel in ad templates. This is needed for users not using the ad client."
        ),
    )
    cache_ads = models.BooleanField(
        default=True,
        help_text=_(
            "Cache this publishers ad requests. Disable for special cases (eg. SaaS users)"
        ),
    )
    cache_ads_duration = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "If cache_ads is True and duration > 0, "
            "use a custom duration instead of settings.ADSERVER_STICKY_DECISION_DURATION."
        ),
    )

    # Denormalized fields
    sampled_ctr = models.FloatField(
        default=0.0,
        help_text=_(
            "A periodically calculated CTR from a sample of ads on this publisher."
        ),
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("name",)

        permissions = [
            ("staff_publisher_fields", "Can view staff publisher fields in reports"),
        ]

    def __str__(self):
        """Simple override."""
        return self.name

    def get_absolute_url(self):
        return reverse("publisher_report", kwargs={"publisher_slug": self.slug})

    @property
    def keywords(self):
        """
        Parses database keywords and ensures consistency.

        - Lowercases all tags
        - Converts underscores to hyphens
        - Slugifies tags
        - Removes empty tags

        Similar logic to RTD ``readthedocs.projects.tag_utils.rtd_parse_tags``.
        """
        if self.default_keywords:
            return_keywords = []
            keyword_list = self.default_keywords.split(",")
            for keyword in keyword_list:
                keyword = keyword.lower().replace("_", "-")
                keyword = slugify(keyword)
                if keyword:
                    return_keywords.append(keyword)
            return return_keywords
        return []

    @property
    def daily_earn_cache_key(self):
        today = get_ad_day().date()
        return f"daily-earn::{self.slug}::{today:%Y-%m-%d}"

    def allowed_domains_as_list(self):
        return self.allowed_domains.split()

    def total_payout_sum(self):
        """The total amount ever paid out to this publisher."""
        total = self.payouts.filter(status=PAID).aggregate(
            total=models.Sum("amount", output_field=models.DecimalField())
        )["total"]
        if total:
            return total
        return 0

    def payout_url(self):
        if self.payout_method == PAYOUT_STRIPE and self.djstripe_account.id:
            return f"https://dashboard.stripe.com/connect/accounts/{self.djstripe_account.id}"
        if self.payout_method == PAYOUT_OPENCOLLECTIVE and self.open_collective_name:
            return f"https://opencollective.com/{self.open_collective_name}"
        if self.payout_method == PAYOUT_PAYPAL and self.paypal_email:
            return "https://www.paypal.com/myaccount/transfer/homepage/pay"
        return ""

    def get_daily_earn(self):
        """Get how much this publisher has earned today."""
        cache_key = self.daily_earn_cache_key
        return cache.get(cache_key, default=0.0)

    def increment_daily_earn(self, delta):
        """Increment how much this publisher has earned today."""
        cache_key = self.daily_earn_cache_key
        try:
            cache.incr(cache_key, delta=delta)
        except ValueError:
            # Cache key doesn't exist for today
            cache.set(cache_key, value=delta, timeout=60 * 60 * 24)


class PublisherGroup(TimeStampedModel):

    """Group of publishers that can be targeted by advertiser's campaigns."""

    name = models.CharField(
        _("Name"), max_length=200, help_text=_("Visible to advertisers")
    )
    slug = models.SlugField(_("Publisher group slug"), max_length=200, unique=True)

    publishers = models.ManyToManyField(
        Publisher,
        related_name="publisher_groups",
        blank=True,
        help_text=_("A group of publishers that can be targeted by advertisers"),
    )

    default_enabled = models.BooleanField(
        default=False,
        help_text=_(
            "Whether this publisher group is enabled on new campaigns by default"
        ),
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name


class Advertiser(TimeStampedModel, IndestructibleModel):

    """An advertiser who buys advertising from the ad server."""

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Advertiser Slug"), max_length=200, unique=True)

    # Publisher specific advertiser account
    publisher = models.OneToOneField(
        Publisher,
        null=True,
        blank=True,
        default=None,
        on_delete=models.PROTECT,
        help_text=_("Used for advertiser accounts associated with a publisher"),
    )

    djstripe_customer = models.ForeignKey(
        djstripe_models.Customer,
        verbose_name=_("Stripe Customer"),
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        default=None,
    )

    # Deprecated - will migration to `customer`
    stripe_customer_id = models.CharField(
        _("Stripe Customer ID"), max_length=200, blank=True, null=True, default=None
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("name",)

        permissions = [
            ("staff_advertiser_fields", "Can view staff advertiser fields in reports"),
        ]

    def __str__(self):
        """Simple override."""
        return self.name

    def get_absolute_url(self):
        return reverse("advertiser_main", kwargs={"advertiser_slug": self.slug})


class Campaign(TimeStampedModel, IndestructibleModel):

    """
    A collection of advertisements (:py:class:`~Advertisement`) from the same advertiser.

    A campaign is typically made up of one or more :py:class:`~Flight` which are themselves
    groups of advertisements including details common among the ads.

    Campaigns have a campaign type which distinguishes paid, house and community ads.

    Since campaigns contain important historical data around tracking how we bill
    and report to customers, they cannot be deleted once created.
    """

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Campaign Slug"), max_length=200, unique=True)

    advertiser = models.ForeignKey(
        Advertiser,
        related_name="campaigns",
        on_delete=models.PROTECT,
        help_text=_("The advertiser for this campaign."),
    )

    publisher_groups = models.ManyToManyField(
        PublisherGroup,
        blank=True,
        help_text=_(
            "Ads for this campaign are eligible for display on publishers in any of these groups"
        ),
    )

    campaign_type = models.CharField(
        _("Campaign Type"),
        max_length=20,
        choices=CAMPAIGN_TYPES,
        default=PAID_CAMPAIGN,
        help_text=_(
            "Most campaigns are paid but ad server admins can configure other lower priority campaign types."
        ),
    )

    exclude_publishers = models.ManyToManyField(
        Publisher,
        blank=True,
        help_text=_("Ads for this campaign will not be shown on these publishers"),
    )

    # Deprecated and no longer used. Will be removed in future releases
    publishers = models.ManyToManyField(
        Publisher,
        related_name="campaigns",
        blank=True,
        help_text=_(
            "Ads for this campaign are eligible for display on these publishers"
        ),
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name

    def ad_count(self):
        return Advertisement.objects.filter(flight__campaign=self).count()

    def allowed_ad_types(self, exclude_deprecated=False):
        """Get the valid ad types for this campaign."""
        queryset = AdType.objects.filter(
            models.Q(publisher_groups=None)
            | models.Q(  # Global ad types across all publishers
                publisher_groups__id__in=self.publisher_groups.all().values("pk")
            )
        )
        if exclude_deprecated:
            queryset = queryset.exclude(deprecated=True)
        return queryset.distinct()

    def total_value(self):
        """Calculate total cost/revenue for all ads/flights in this campaign."""
        # Check for a cached value that would come from an annotated queryset
        if hasattr(self, "campaign_total_value"):
            return self.campaign_total_value or 0.0

        aggregation = Flight.objects.filter(campaign=self).aggregate(
            total_value=models.Sum(
                (models.F("total_clicks") * models.F("cpc"))
                + (models.F("total_views") * models.F("cpm") / 1000.0),
                output_field=models.FloatField(),
            )
        )["total_value"]

        return aggregation or 0.0

    def publisher_group_display(self):
        """Helper function to display publisher groups if the selected set isn't the default."""
        default_pub_groups = [
            pg.name
            for pg in PublisherGroup.objects.filter(default_enabled=True).order_by(
                "name"
            )
        ]
        campaign_pub_groups = [pg.name for pg in self.publisher_groups.order_by("name")]

        if default_pub_groups != campaign_pub_groups:
            return campaign_pub_groups

        return None


class Flight(TimeStampedModel, IndestructibleModel):

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

    HIGHEST_PRIORITY_MULTIPLIER = 1000000
    LOWEST_PRIORITY_MULTIPLIER = 1

    # The pacing interval in seconds used to pace flights evenly.
    # For example, with a 1000 click flight over 10 days,
    # there will be 10 intervals (each 1 day) and we'll aim for 100 clicks per day
    # Shorter intervals (eg. an hour) spread flights more evenly across geographies
    DEFAULT_PACING_INTERVAL = 60 * 60  # 1 hour

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Flight Slug"), max_length=200, unique=True)
    start_date = models.DateField(
        _("Start Date"),
        default=datetime.date.today,
        db_index=True,
        help_text=_("This flight will not be shown before this date"),
    )
    end_date = models.DateField(
        _("End Date"),
        default=default_flight_end_date,
        help_text=_("The estimated end date for the flight"),
    )
    hard_stop = models.BooleanField(
        _("Hard stop"),
        default=False,
        help_text=_(
            "The flight will be stopped on the end date even if not completely fulfilled"
        ),
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
    sold_clicks = models.PositiveIntegerField(_("Sold Clicks"), default=0)

    # CPM
    cpm = models.DecimalField(
        _("Cost Per 1k Impressions"), max_digits=5, decimal_places=2, default=0
    )
    sold_impressions = models.PositiveIntegerField(_("Sold Impressions"), default=0)

    campaign = models.ForeignKey(
        Campaign, related_name="flights", on_delete=models.PROTECT
    )

    targeting_parameters = JSONField(
        _("Targeting parameters"),
        blank=True,
        null=True,
        validators=[TargetingParametersValidator()],
    )

    pacing_interval = models.PositiveIntegerField(
        default=DEFAULT_PACING_INTERVAL,
    )
    prioritize_ads_ctr = models.BooleanField(
        _("Prioritize ads by CTR"),
        default=True,
        help_text=_(
            "If true, the ad server will automatically show ads with higher CTRs "
            "at a higher rate than ads with lower CTRs."
        ),
    )

    # Denormalized fields
    total_views = models.PositiveIntegerField(
        default=0, help_text=_("Views across all ads in this flight")
    )
    total_clicks = models.PositiveIntegerField(
        default=0, help_text=_("Clicks across all ads in this flight")
    )

    # We store nightly the top 20 publishers/countries/regions for each flight
    # and the percentage they have filled this flight
    # eg.
    # {
    #    "publishers": {"publisher1": 0.1, "publisher2": 0.05},
    #    "countries": {"US": 0.1, "CA": 0.05, "DE": 0.05},
    #    "regions": {"us-ca": 0.25, "eu": 0.5},
    #  }
    traffic_fill = JSONField(
        _("Traffic fill"),
        blank=True,
        null=True,
        default=None,
        validators=[TrafficFillValidator()],
    )

    # If set, any publisher, country, or region whose `traffic_fill` exceeds the cap
    # will not be eligible to show on this campaign until they're below the cap.
    # Format is the same as `traffic_fill` but this is set manually
    traffic_cap = JSONField(
        _("Traffic cap"),
        blank=True,
        null=True,
        default=None,
        validators=[TrafficFillValidator()],
    )

    # Connect to Stripe invoice data
    # There can be multiple invoices for a flight
    # (say a 3 month flight billed monthly)
    # and an invoice can cover multiple flights
    invoices = models.ManyToManyField(
        djstripe_models.Invoice,
        verbose_name=_("Stripe invoices"),
        blank=True,
    )
    discount = models.ForeignKey(
        djstripe_models.Coupon,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        default=None,
    )

    history = HistoricalRecords()

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
    def included_regions(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_regions", [])

    @property
    def excluded_regions(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("exclude_regions", [])

    @property
    def included_topics(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_topics", [])

    @property
    def included_keywords(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_keywords", [])

    @property
    def excluded_keywords(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("exclude_keywords", [])

    @property
    def included_publishers(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_publishers", [])

    @property
    def excluded_publishers(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("exclude_publishers", [])

    @property
    def included_domains(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("include_domains", [])

    @property
    def excluded_domains(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("exclude_domains", [])

    @property
    def days(self):
        if not self.targeting_parameters:
            return []
        return self.targeting_parameters.get("days", [])

    @property
    def state(self):
        today = get_ad_day().date()
        if self.live and self.start_date <= today:
            return FLIGHT_STATE_CURRENT
        if self.end_date > today:
            return FLIGHT_STATE_UPCOMING
        return FLIGHT_STATE_PAST

    @classmethod
    def order_flights(cls, flights):
        """
        Orders flights by our normal ordering of state, then date, then name.

        Previously, we were using database ordering, but that cannot deterministically
        order flights by state. Flights can be upcoming if they start after today
        or if they start before today (but end after today) but aren't live.
        """
        state_order = {
            FLIGHT_STATE_CURRENT: 0,
            FLIGHT_STATE_UPCOMING: 1,
            FLIGHT_STATE_PAST: 2,
        }
        return sorted(
            flights,
            key=lambda f: (state_order[f.state], -1 * f.start_date.toordinal(), f.name),
        )

    def get_absolute_url(self):
        return reverse(
            "flight_detail",
            kwargs={
                "advertiser_slug": self.campaign.advertiser.slug,
                "flight_slug": self.slug,
            },
        )

    def get_include_regions(self):
        return Region.objects.filter(slug__in=self.included_regions)

    def get_exclude_regions(self):
        return Region.objects.filter(slug__in=self.excluded_regions)

    def get_include_topics(self):
        return Topic.objects.filter(slug__in=self.included_topics)

    def get_include_countries_display(self):
        included_country_codes = self.included_countries
        return [COUNTRY_DICT.get(cc, "Unknown") for cc in included_country_codes]

    def get_exclude_countries_display(self):
        excluded_country_codes = self.excluded_countries
        return [COUNTRY_DICT.get(cc, "Unknown") for cc in excluded_country_codes]

    def get_days_display(self):
        return [day.capitalize() for day in self.days]

    def show_to_geo(self, geo_data):
        """
        Check if a flight is valid for a given country code.

        A ``country_code`` of ``None`` (meaning the user's country is unknown)
        will not match a flight with any ``include_countries`` but wont be
        excluded from any ``exclude_countries``
        """
        if self.included_countries and geo_data.country not in self.included_countries:
            return False
        if (
            self.included_state_provinces
            and geo_data.region not in self.included_state_provinces
        ):
            return False
        if (
            self.included_metro_codes
            and geo_data.metro not in self.included_metro_codes
        ):
            return False
        if self.excluded_countries and geo_data.country in self.excluded_countries:
            return False

        regions = Region.load_from_cache()

        # Check region groupings as well
        if self.included_regions or self.excluded_regions:
            if self.included_regions and not any(
                geo_data.country in regions[reg]
                for reg in self.included_regions
                if reg in regions
            ):
                return False

            if self.excluded_regions and any(
                geo_data.country in regions[reg]
                for reg in self.excluded_regions
                if reg in regions
            ):
                return False

        # Check if the country traffic cap exceeds the current fill for that country
        if self.traffic_cap and self.traffic_fill and "countries" in self.traffic_cap:
            # pylint: disable=invalid-sequence-index
            limited_countries = self.traffic_cap["countries"]
            country_traffic_fill = self.traffic_fill.get("countries", {})
            if country_traffic_fill.get(geo_data.country, 0.0) > limited_countries.get(
                geo_data.country, 100.0
            ):
                return False

        # Check if the region traffic cap exceeds the current fill for that region
        if self.traffic_cap and self.traffic_fill and "regions" in self.traffic_cap:
            # pylint: disable=invalid-sequence-index
            limited_regions = self.traffic_cap["regions"]
            region_traffic_fill = self.traffic_fill.get("regions", {})
            for region_slug in regions:
                if geo_data.country not in regions[region_slug]:
                    continue
                if region_traffic_fill.get(region_slug, 0.0) > limited_regions.get(
                    region_slug, 100.0
                ):
                    return False

        return True

    def show_to_keywords(self, keywords):
        """
        Check if a flight is valid for a given keywords.

        If *any* keywords match the included list, it should be shown.
        If *any* keywords are in the excluded list, it should not be shown.
        """
        keyword_set = set(keywords)
        if self.included_keywords:
            # If no keywords from the page in the include list, don't show this flight
            if not keyword_set.intersection(self.included_keywords):
                return False

        if self.excluded_keywords:
            # If any keyworks from the page in the exclude list, don't show this flight
            if keyword_set.intersection(self.excluded_keywords):
                return False

        # Check topics (groupings of keywords)
        if self.included_topics:
            topics = Topic.load_from_cache()
            topic_keyword_set = set()
            for topic_slug in self.included_topics:
                # Be defensive in case the topic isn't in the cache
                if topic_slug not in topics:
                    log.warning(
                        "Unknown topic being targeted. Topic=%s, Flight=%s",
                        topic_slug,
                        self,
                    )
                    continue

                for kw in topics[topic_slug]:
                    topic_keyword_set.add(kw)

            if not keyword_set.intersection(topic_keyword_set):
                return False

        return True

    def show_to_mobile(self, is_mobile):
        """Check if a flight is valid for this traffic based on mobile/non-mobile."""
        if not self.targeting_parameters:
            return True

        mobile_traffic_targeting = self.targeting_parameters.get("mobile_traffic")
        if mobile_traffic_targeting == "exclude" and is_mobile:
            return False
        if mobile_traffic_targeting == "only" and not is_mobile:
            return False

        return True

    def show_to_day(self, day):
        """Check if a flight is valid for this traffic based on the day."""
        if not self.targeting_parameters:
            return True

        days_targeting = self.targeting_parameters.get("days")
        if days_targeting and day not in days_targeting:
            return False

        return True

    def show_on_publisher(self, publisher):
        if self.included_publishers:
            return publisher.slug in self.included_publishers

        if self.excluded_publishers:
            return publisher.slug not in self.excluded_publishers

        # Check if the publisher traffic cap exceeds the current fill for that publisher
        if self.traffic_cap and self.traffic_fill and "publishers" in self.traffic_cap:
            # pylint: disable=invalid-sequence-index
            limited_publishers = self.traffic_cap["publishers"]
            publisher_traffic_fill = self.traffic_fill.get("publishers", {})
            if publisher_traffic_fill.get(publisher.slug, 0.0) > limited_publishers.get(
                publisher.slug, 100.0
            ):
                return False

        return True

    def show_on_domain(self, url):
        domain = get_domain_from_url(url)

        if self.included_domains:
            return domain in self.included_domains

        if self.excluded_domains:
            return domain not in self.excluded_domains

        return True

    def sold_days(self):
        # The flight is considered to end at the end of the day on the `end_date`
        # and start at the beginning of the day on the `start_date`
        start_datetime = pytz.utc.localize(
            datetime.datetime.combine(self.start_date, datetime.datetime.min.time())
        )
        end_datetime = pytz.utc.localize(
            datetime.datetime.combine(self.end_date, datetime.datetime.max.time())
        )

        remaining_seconds = (end_datetime - start_datetime).total_seconds()

        # Add one because the final interval will be a partial
        # (eg. 23 hours, 59 minutes, 59 seconds, 999ms)
        return max(0, int(remaining_seconds / self.pacing_interval)) + 1

    def days_overdue(self):
        """Number of days (NOT intervals) past the end date on the flight."""
        # A negative number means the flight is not overdue
        days_overdue = (self.end_date - timezone.now().date()).days * -1
        return max(0, days_overdue)

    def days_remaining(self):
        """Number of intervals (default = days) left in a flight."""
        # The flight is considered to end at the end of the day on the `end_date`
        end_datetime = pytz.utc.localize(
            datetime.datetime.combine(self.end_date, datetime.datetime.max.time())
        )

        remaining_seconds = (end_datetime - timezone.now()).total_seconds()
        return max(0, int(remaining_seconds / self.pacing_interval))

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

    def views_needed_this_interval(self):
        today = get_ad_day().date()
        if (
            not self.live
            or self.views_remaining() <= 0
            or self.start_date > today
            or (self.hard_stop and self.end_date < today)
        ):
            return 0

        if self.days_remaining() > 0:
            flight_remaining_percentage = self.days_remaining() / self.sold_days()

            # This is how many views should be remaining this far in the flight
            flight_views_pace = int(self.sold_impressions * flight_remaining_percentage)

            return max(0, self.views_remaining() - flight_views_pace)

        return self.views_remaining()

    def clicks_needed_this_interval(self):
        """Calculates clicks needed based on the impressions this flight's ads have."""
        today = get_ad_day().date()
        if (
            not self.live
            or self.clicks_remaining() <= 0
            or self.start_date > today
            or (self.hard_stop and self.end_date < today)
        ):
            return 0

        if self.days_remaining() > 0:
            flight_remaining_percentage = self.days_remaining() / self.sold_days()

            # This is how many clicks we should have remaining this far in the flight
            flight_clicks_pace = int(self.sold_clicks * flight_remaining_percentage)

            return max(0, self.clicks_remaining() - flight_clicks_pace)

        return self.clicks_remaining()

    def weighted_clicks_needed_this_interval(self, publisher=None):
        """
        Calculates clicks needed taking into account a flight's priority.

        For the purpose of clicks needed, 1000 impressions = 1 click (for CPM ads)
        Takes into account value of the flight,
        which causes higher paid and better CTR ads to be prioritized.
        Uses the passed publisher for a better CTR estimate if passed.
        """
        impressions_needed = 0

        # This is naive but we are counting a click as being worth 1,000 views
        impressions_needed += math.ceil(self.views_needed_this_interval() / 1000.0)
        impressions_needed += self.clicks_needed_this_interval()

        if self.cpc:
            # Use the publisher CTR if available
            # Otherwise, use this flight's average CTR
            estimated_ctr = float(self.ctr())
            if publisher and publisher.sampled_ctr > 0.01:
                estimated_ctr = publisher.sampled_ctr

            # Note: CTR is in percent (eg. 0.1 means 0.1% not 0.001)
            estimated_ecpm = float(self.cpc) * estimated_ctr * 10
        else:
            # CPM ads
            estimated_ecpm = float(self.cpm)

        # This prioritizes an ad with estimated eCPM=$1 at the normal rate
        # An ad with estimated eCPM=$2 at 2x the normal rate, eCPM=$3 => 3x normal
        price_priority_value = estimated_ecpm

        # Keep values between 1-10 so we don't penalize the value for lower performance
        # but add value for higher performance without overweighting
        price_priority_value = max(float(price_priority_value), 1.0)
        price_priority_value = min(price_priority_value, 10.0)

        prioritized_impressions_needed = int(
            impressions_needed * self.priority_multiplier * price_priority_value
        )

        # Prioritize flights the more overdue they are
        overdue_factor = int(max(1, self.days_overdue()) ** 1.5)

        return int(prioritized_impressions_needed * overdue_factor)

    def clicks_remaining(self):
        return max(0, self.sold_clicks - self.total_clicks)

    def views_remaining(self):
        return max(0, self.sold_impressions - self.total_views)

    def value_remaining(self):
        """Value ($) remaining on this ad flight."""
        value_clicks_remaining = float(self.clicks_remaining() * self.cpc)
        value_views_remaining = float(self.views_remaining() * self.cpm) / 1000.0
        return value_clicks_remaining + value_views_remaining

    def projected_total_value(self):
        """Total value ($) assuming all sold impressions and clicks are delivered."""
        projected_value_clicks = float(self.sold_clicks * self.cpc)
        projected_value_views = float(self.sold_impressions * self.cpm) / 1000.0
        return projected_value_clicks + projected_value_views

    def total_value(self):
        """Total value ($) so far based on what's been delivered."""
        value_clicks = float(self.total_clicks * self.cpc)
        value_views = float(self.total_views * self.cpm) / 1000.0
        return value_clicks + value_views

    def percent_complete(self):
        projected_total = self.projected_total_value()
        if projected_total > 0:
            return self.total_value() / projected_total * 100
        return 0

    def ctr(self):
        clicks = self.total_clicks
        views = self.total_views
        return calculate_ctr(clicks, views)

    @cached_property
    def active_invoices(self):
        """Get invoices excluding drafts, void, and uncollectable ones."""
        return self.invoices.filter(status__in=(InvoiceStatus.open, InvoiceStatus.paid))


class AdType(TimeStampedModel, models.Model):

    """
    A type of advertisement including such parameters as the amount of text and images size.

    Many ad types are industry standards from the Interactive Advertising Bureau (IAB).
    Some publishers prefer native ads that are custom sized for their needs.

    See https://www.iab.com/newadportfolio/
    """

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Slug"), max_length=200, unique=True)

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

    # Deprecated - new ads don't allow any HTML
    # They are instead broken into a headline, body, and call to action
    allowed_html_tags = models.CharField(
        _("Allowed HTML tags"),
        blank=True,
        max_length=255,
        default="a b strong i em code",
        help_text=_("Space separated list of allowed HTML tag names"),
    )

    default_enabled = models.BooleanField(
        default=False,
        help_text=_(
            "Whether this ad type should default to checked when advertisers are creating ads"
        ),
    )

    template = models.TextField(
        _("Ad template"),
        blank=True,
        null=True,
        help_text=_("Override the template for rendering this ad type"),
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("A short description of the ad type to guide advertisers."),
    )
    order = models.PositiveSmallIntegerField(default=0)

    deprecated = models.BooleanField(
        default=False,
        help_text=_(
            "Users cannot select deprecated ad types unless an ad is already that type."
        ),
    )

    publisher_groups = models.ManyToManyField(
        PublisherGroup,
        related_name="adtypes",
        blank=True,
        help_text=_(
            "This is used for ad types specific to certain publishers. "
            "By default, an ad type is global for all publishers.",
        ),
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("order", "name")

    def __str__(self):
        """Simple override."""
        return self.name


class Advertisement(TimeStampedModel, IndestructibleModel):

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

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Slug"), max_length=200, unique=True)

    # ad.text used to be a standalone field with certain HTML supported
    # Now it is constructed from the headline, content, and call to action
    # Headline, content, and CTA do not allow any HTML
    text = models.TextField(
        _("Text"),
        blank=True,
        help_text=_("For most ad types, the text should be less than 100 characters."),
    )
    headline = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text=_(
            "An optional headline at the beginning of the ad usually displayed in bold"
        ),
    )
    content = models.TextField(
        blank=True,
        null=True,
        help_text=_(
            "For most ad types, the combined length of the headline, body, and call to action "
            "should be less than 100 characters."
        ),
    )
    cta = models.CharField(
        _("Call to action"),
        max_length=200,
        blank=True,
        null=True,
        help_text=_(
            "An optional call to action displayed at the end of the ad usually in bold"
        ),
    )

    # Supports simple variables like ${publisher} and ${advertisement}
    # using string.Template syntax
    link = models.URLField(
        _("Link URL"),
        max_length=255,
        help_text=_(
            "URL of your landing page. "
            "This may contain UTM parameters so you know the traffic came from us. "
            "The publisher will be added in the 'ea-publisher' query parameter."
        ),
    )
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

    # Deprecated - this will be removed
    ad_type = models.ForeignKey(
        AdType, blank=True, null=True, default=None, on_delete=models.PROTECT
    )

    ad_types = models.ManyToManyField(
        AdType,
        related_name="advertisements",
        blank=True,
        help_text=_("Possible ways this ad will be displayed"),
    )

    # This is used exclusively in optimizations and NOT in any reporting
    sampled_ctr = models.FloatField(
        default=0.0,
        help_text=_("A periodically calculated CTR for this ad."),
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("slug", "-live")

    def __copy__(self):
        """Duplicate an ad."""
        # https://docs.djangoproject.com/en/4.2/topics/db/queries/#copying-model-instances
        # Get a fresh reference so that "self" doesn't become the new copy
        ad = Advertisement.objects.get(pk=self.pk)

        new_name = ad.name
        new_slug = ad.slug

        # Fix up names/slugs of ads that have been copied before
        # Remove dates and (" Copy") from the end of the name/slug
        new_name = re.sub(" \d{4}-\d{2}-\d{2}$", "", new_name)
        while new_name.endswith(" Copy"):
            new_name = new_name[:-5]
        new_slug = re.sub("-copy\d*$", "", new_slug)
        new_slug = re.sub("-\d{8}(-\d+)?$", "", new_slug)

        # Get a slug that doesn't already exist
        # This tries -20230501, then -20230501-1, etc.
        new_slug += "-{}".format(timezone.now().strftime("%Y%m%d"))
        digit = 0
        while Advertisement.objects.filter(slug=new_slug).exists():
            ending = f"-{digit}"
            if new_slug.endswith(ending):
                new_slug = new_slug[: -len(ending)]
            digit += 1
            new_slug += f"-{digit}"

        ad_types = ad.ad_types.all()

        ad.pk = None
        ad.name = new_name + " {}".format(timezone.now().strftime("%Y-%m-%d"))
        ad.slug = new_slug
        ad.live = False  # The new ad should always be non-live
        ad.save()

        ad.ad_types.set(ad_types)
        return ad

    def __str__(self):
        """Simple override."""
        return self.name

    def get_absolute_url(self):
        return reverse(
            "advertisement_detail",
            kwargs={
                "advertiser_slug": self.flight.campaign.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.slug,
            },
        )

    def incr(self, impression_type, publisher):
        """
        Add to the number of times this action has been performed, stored in the DB.

        TODO: Refactor this method, moving it off the Advertisement class since it can be called
              without an advertisement when we have a Decision and no Offer.
        """
        day = get_ad_day().date()

        if isinstance(impression_type, str):
            impression_types = (impression_type,)
        else:
            impression_types = impression_type

        for imp_type in impression_types:
            assert imp_type in IMPRESSION_TYPES

            # Update the denormalized fields on the Flight
            if imp_type == VIEWS:
                Flight.objects.filter(pk=self.flight_id).update(
                    total_views=models.F("total_views") + 1
                )
            elif imp_type == CLICKS:
                Flight.objects.filter(pk=self.flight_id).update(
                    total_clicks=models.F("total_clicks") + 1
                )

        # Ensure that an impression object exists for today
        # and make sure to query the writable DB for this
        impression, created = AdImpression.objects.using("default").get_or_create(
            advertisement=self,
            publisher=publisher,
            date=day,
            defaults={imp_type: 1 for imp_type in impression_types},
        )

        if not created:
            # If the object was created above, we don't need to update
            # since the defaults will have already done the update for us.
            AdImpression.objects.using("default").filter(pk=impression.pk).update(
                **{imp_type: models.F(imp_type) + 1 for imp_type in impression_types}
            )

    def _record_base(
        self,
        request,
        model,
        publisher,
        keywords,
        url,
        div_id,
        ad_type_slug,
        paid_eligible=False,
        rotations=1,
    ):
        """
        Save the actual AdBase model to the database.

        This is used for all subclasses,
        so we need to keep all the data passed in generic.
        """
        ip_address = get_client_ip(request)
        user_agent = get_client_user_agent(request)
        client_id = get_client_id(request)
        parsed_ua = parse(user_agent)
        country = get_client_country(request)
        url = url or request.headers.get("referer")

        if (
            model != Click
            and settings.ADSERVER_DO_NOT_TRACK
            and not publisher.record_offer_details
        ):
            # For compliance with DNT,
            # we can't store UAs indefinitely from a user merely browsing
            user_agent = None

        if div_id:
            # Even though the publisher could have a div of any length
            # and we want to echo back the same div to them,
            # we only store the first 100 characters of it.
            div_id = div_id[: Offer.DIV_MAXLENGTH]

        obj = model.objects.create(
            date=timezone.now(),
            publisher=publisher,
            ip=anonymize_ip_address(ip_address),
            user_agent=user_agent,
            client_id=client_id,
            country=country,
            url=url,
            paid_eligible=paid_eligible,
            rotations=rotations,
            # Derived user agent data
            browser_family=parsed_ua.browser.family,
            os_family=parsed_ua.os.family,
            is_bot=parsed_ua.is_bot,
            is_mobile=parsed_ua.is_mobile,
            is_proxy=is_proxy_ip(ip_address),
            # Client Data
            keywords=keywords if keywords else None,  # Don't save empty lists
            div_id=div_id,
            ad_type_slug=ad_type_slug,
            # Page info
            advertisement=self,
        )
        return obj

    def track_impression(self, request, impression_type, publisher, offer):
        if impression_type not in (CLICKS, VIEWS):
            raise RuntimeError("Impression must be either a click or a view")

        if impression_type == CLICKS:
            self.track_click(request, publisher, offer)
        elif impression_type == VIEWS:
            self.track_view(request, publisher, offer)

    def track_click(self, request, publisher, offer):
        """Store click data in the DB."""
        self.incr(impression_type=CLICKS, publisher=publisher)
        return self._record_base(
            request=request,
            model=Click,
            publisher=publisher,
            keywords=offer.keywords,
            url=offer.url,
            div_id=offer.div_id,
            ad_type_slug=offer.ad_type_slug,
            paid_eligible=offer.paid_eligible,
            rotations=offer.rotations,
        )

    def track_view(self, request, publisher, offer):
        """
        Store view data in the DB.

        Views are only stored if ``settings.ADSERVER_RECORD_VIEWS=True``
        or a publisher has the ``Publisher.record_views`` flag set.
        For a large scale ad server, writing a database record per ad view
        is not feasible
        """
        self.incr(impression_type=VIEWS, publisher=publisher)

        if request.GET.get("uplift"):
            # Don't overwrite Offer object here, since it might have changed prior to our writing
            Offer.objects.filter(pk=offer.pk).update(uplifted=True)

        if settings.ADSERVER_RECORD_VIEWS or publisher.record_views:
            return self._record_base(
                request=request,
                model=View,
                publisher=publisher,
                keywords=offer.keywords,
                url=offer.url,
                div_id=offer.div_id,
                ad_type_slug=offer.ad_type_slug,
                paid_eligible=offer.paid_eligible,
                rotations=offer.rotations,
            )

        log.debug("Not recording ad view.")
        return None

    def track_view_time(self, offer, view_time):
        """Store the time the ad was in view."""
        # Don't overwrite the Offer object here, it might have changed prior to our writing
        if view_time > Offer.MAX_VIEW_TIME:
            # Set a maximum allowed view time so averages aren't thrown off
            view_time = Offer.MAX_VIEW_TIME
            log.warning("View time exceeded maximum view time: view_time=%s", view_time)
        if (
            not offer.is_old()
            and offer.viewed
            and not offer.view_time
            and view_time > 0
        ):
            Offer.objects.filter(pk=offer.pk).update(view_time=view_time)
            return True

        log.info("View time was for an invalid view")
        return False

    def offer_ad(
        self,
        request,
        publisher,
        ad_type_slug,
        div_id,
        keywords,
        url=None,
        forced=False,
        paid_eligible=False,
        rotations=1,
    ):
        """
        Offer to display this ad on a specific publisher and a specific display (ad type).

        Tracks an offer in the database to save data about it and compare against view.
        """
        ad_type = AdType.objects.filter(slug=ad_type_slug).first()

        self.incr(impression_type=(OFFERS, DECISIONS), publisher=publisher)
        offer = self._record_base(
            request=request,
            model=Offer,
            publisher=publisher,
            keywords=keywords,
            url=url,
            div_id=div_id,
            ad_type_slug=ad_type_slug,
            paid_eligible=paid_eligible,
            rotations=rotations,
        )

        if forced and self.flight.campaign.campaign_type == PAID_CAMPAIGN:
            # Ad offers forced to a specific ad or campaign should never be billed.
            # By discarding the nonce, the ad view/click will never count.
            # We will still record data for unpaid campaign in reporting though.
            nonce = "forced"
        else:
            nonce = offer.pk

        view_url = generate_absolute_url(
            reverse("view-proxy", kwargs={"advertisement_id": self.pk, "nonce": nonce})
        )

        view_time_url = generate_absolute_url(
            reverse(
                "view-time-proxy", kwargs={"advertisement_id": self.pk, "nonce": nonce}
            )
        )

        click_url = generate_absolute_url(
            reverse("click-proxy", kwargs={"advertisement_id": self.pk, "nonce": nonce})
        )

        text = self.render_links(click_url)
        body = html.unescape(bleach.clean(text, tags=[], strip=True))

        # Match keywords to topics, only when there are keywords to match
        topic_set = set()
        if keywords:
            topics = Topic.load_from_cache()
            for topic, topic_keywords in topics.items():
                for topic_keyword in topic_keywords:
                    if topic_keyword in keywords:
                        topic_set.add(topic)

        return {
            "id": self.slug,
            "text": text,
            "body": body,
            "html": self.render_ad(
                ad_type,
                click_url=click_url,
                view_url=view_url,
                publisher=publisher,
                keywords=keywords,
                topics=topic_set,
            ),
            # Breakdown of the ad text into its component parts
            "copy": {
                "headline": self.headline or "",
                "cta": self.cta or "",
                "content": self.content or body,
            },
            "image": self.image.url if self.image else None,
            "link": click_url,
            "view_url": view_url,
            "view_time_url": view_time_url,
            "nonce": nonce,
            "display_type": ad_type_slug,
            "campaign_type": self.flight.campaign.campaign_type,
        }

    @classmethod
    def record_null_offer(
        cls,
        request,
        publisher,
        ad_type_slug,
        div_id,
        keywords,
        url,
        paid_eligible=False,
    ):
        """
        Store null offers, so that we can keep track of our fill rate.

        Without this, when we don't offer an ad and a user doesn't have house ads on,
        we don't have any way to track how many requests for an ad there have been.
        """
        cls.incr(self=None, impression_type=DECISIONS, publisher=publisher)
        cls._record_base(
            self=None,
            request=request,
            model=Offer,
            publisher=publisher,
            keywords=keywords,
            url=url,
            div_id=div_id,
            ad_type_slug=ad_type_slug,
            paid_eligible=paid_eligible,
        )

    def is_valid_offer(self, impression_type, offer):
        """
        Returns true if this nonce (from ``offer_ad``) is valid for a given impression type.

        A nonce is valid if it was generated recently (hasn't timed out)
        and hasn't already been used.
        """
        if offer.is_old():
            return False

        if impression_type == VIEWS:
            return offer.viewed is False
        if impression_type == CLICKS:
            return offer.viewed is True and offer.clicked is False

        return False

    def invalidate_nonce(self, impression_type, nonce):
        if impression_type == VIEWS:
            Offer.objects.filter(id=nonce).update(viewed=True)
        if impression_type == CLICKS:
            Offer.objects.filter(id=nonce).update(clicked=True)

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

    def ctr(self):
        return calculate_ctr(self.total_clicks(), self.total_views())

    def country_click_breakdown(self, start_date, end_date=None):
        report = Counter()

        clicks = self.clicks.filter(date__gte=start_date)
        if end_date:
            clicks = clicks.filter(date__lte=end_date)

        for click in clicks:
            country = "Unknown"

            if click.country:
                country = str(click.country.name)
            report[country] += 1

        return report

    def render_links(self, link=None, preview=False):
        """
        Include the link in the html text.

        Does not include any callouts such as "ads served ethically"
        """
        url = link or self.link
        if not self.text:
            template = get_template("adserver/advertisement-body.html")
            return mark_safe(
                template.render(
                    {
                        "url": url,
                        "ad": self,
                        "preview": preview,
                    }
                ).strip()
            )

        # Old style ads where the text was fully customizable
        ad_html = self.text
        a_tag = format_html(
            '<a href="{}" rel="nofollow noopener sponsored" target="_blank">', url
        )

        return mark_safe(ad_html.replace("<a>", a_tag))

    def render_ad(
        self,
        ad_type,
        click_url=None,
        view_url=None,
        publisher=None,
        keywords=None,
        topics=None,
        preview=False,
    ):
        """Render the ad as HTML including any proxy links for collecting view/click metrics."""
        if not ad_type:
            # Render by the first ad type for this ad
            # This is only used to preview the ad
            ad_type = self.ad_types.all().first()

        if ad_type and ad_type.template:
            # Check if the ad type has a specific template
            template = engines["django"].from_string(ad_type.template)
        else:
            # Otherwise get the default template
            # Don't do this by default as searching for a template is expensive
            template = get_template("adserver/advertisement.html")

        image_preview_url = None
        if preview:
            # When previewing an ad (typically in the advertiser dashboard)
            # we want to display a simple placeholder image.
            image_preview_url = static("image-placeholder.png")

        return template.render(
            {
                "ad": self,
                "publisher": publisher,
                "image_url": self.image.url if self.image else image_preview_url,
                "link_url": click_url or self.link,
                "view_url": view_url,
                "text_as_html": self.render_links(link=click_url, preview=preview),
                # Pass keywords and topics so we can be smart with what landing page
                # to link the `Ads by EthicalAds` to.
                "keywords": keywords,
                "topics": topics,
            }
        ).strip()


class BaseImpression(TimeStampedModel, models.Model):

    """Statistics for tracking."""

    date = models.DateField(_("Date"), db_index=True)

    # Decisions are a superset of all Offers.
    # Every API request that comes in results in a Decision,
    # and an Offer is only created when we actually offer an ad.
    decisions = models.PositiveIntegerField(
        _("Decisions"),
        default=0,
        help_text=_(
            "The number of times the Ad Decision API was called. "
            "The server might not respond with an ad if there isn't inventory."
        ),
    )

    # Offers include cases where the server returned an ad
    # but the client didn't load it
    # or the client didn't qualify as a view (staff, blocklisted, etc.)
    offers = models.PositiveIntegerField(
        _("Offers"),
        default=0,
        help_text=_(
            "The number of times an ad was proposed by the ad server. "
            "The client may not load the ad (a view) for a variety of reasons "
        ),
    )

    # Views & Clicks don't count actions that are blocklisted, done by staff, bots, etc.
    views = models.PositiveIntegerField(
        _("Views"),
        default=0,
        help_text=_("Number of times the ad was legitimately viewed"),
    )
    clicks = models.PositiveIntegerField(
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
        Advertisement, related_name="impressions", on_delete=models.PROTECT, null=True
    )
    # This field is the sum of all the view time for each ad for this publisher each day
    view_time = models.PositiveIntegerField(
        _("Seconds that the ad was in view"),
        null=True,
    )

    class Meta:
        # We must also constrain when the `advertisement` is null
        constraints = (
            UniqueConstraint(
                fields=("publisher", "date"),
                condition=models.Q(advertisement=None),
                name="null_offer_unique",
            ),
        )
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date")
        verbose_name_plural = _("Ad impressions")

    def __str__(self):
        """Simple override."""
        return "%s on %s" % (self.advertisement, self.date)


class AdvertiserImpression(BaseImpression):

    """
    Create a daily index by advertiser (and nothing else).

    Indexed one per advertiser per day.
    """

    advertiser = models.ForeignKey(
        Advertiser,
        related_name="advertiser_impressions",
        on_delete=models.PROTECT,
        null=True,
    )
    spend = models.DecimalField(
        _("Daily spend"), max_digits=10, decimal_places=4, default=0
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("advertiser", "date")
        verbose_name_plural = _("Advertiser impressions")

    def __str__(self):
        """Simple override."""
        return "%s on %s" % (self.advertiser, self.date)


class BasePublisherImpression(BaseImpression):
    revenue = models.DecimalField(
        _("Daily revenue"),
        max_digits=10,
        decimal_places=4,
        default=0,
        help_text=_(
            "This value has not been multiplied by the revenue share percentage"
        ),
    )

    class Meta:
        abstract = True

    def __str__(self):
        """Simple override."""
        return "%s on %s" % (self.publisher, self.date)


class PublisherImpression(BasePublisherImpression):

    """
    Create a daily index by publisher (and nothing else).

    Indexed one per publisher per day.
    """

    publisher = models.ForeignKey(
        Publisher,
        related_name="publisher_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "date")
        verbose_name_plural = _("Publisher impressions")


class PublisherPaidImpression(BasePublisherImpression):

    """
    Create a daily index by publisher (and nothing else) for paid impressions ONLY.

    Indexed one per publisher per day.
    """

    publisher = models.ForeignKey(
        Publisher,
        related_name="publisher_paid_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "date")
        verbose_name_plural = _("Publisher paid impressions")


class PlacementImpression(BaseImpression):

    """
    Create an index of placements for ads.

    Indexed one per ad/publisher/placement per day.
    """

    div_id = models.CharField(max_length=255, null=True, blank=True)
    ad_type_slug = models.CharField(_("Ad type"), blank=True, null=True, max_length=100)
    publisher = models.ForeignKey(
        Publisher, related_name="placement_impressions", on_delete=models.PROTECT
    )
    advertisement = models.ForeignKey(
        Advertisement,
        related_name="placement_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = (
            "publisher",
            "advertisement",
            "date",
            "div_id",
            "ad_type_slug",
        )
        verbose_name_plural = _("Placement impressions")

    def __str__(self):
        """Simple override."""
        return "Placement %s of %s on %s" % (self.div_id, self.advertisement, self.date)


class GeoImpression(BaseImpression):

    """
    Create an index of geo targeting for ads.

    Indexed one per ad/publisher/geo per day.
    """

    country = CountryField()
    publisher = models.ForeignKey(
        Publisher, related_name="geo_impressions", on_delete=models.PROTECT
    )
    advertisement = models.ForeignKey(
        Advertisement,
        related_name="geo_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date", "country")

    def __str__(self):
        """Simple override."""
        return "Geo %s of %s on %s" % (self.country, self.advertisement, self.date)


class RegionImpression(BaseImpression):

    """
    Create an index of region geo targeting for ads.

    Indexed one per ad/publisher/region per day.
    """

    region = models.CharField(_("Region"), max_length=100)
    publisher = models.ForeignKey(
        Publisher, related_name="region_impressions", on_delete=models.PROTECT
    )
    advertisement = models.ForeignKey(
        Advertisement,
        related_name="region_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date", "region")

    def __str__(self):
        """Simple override."""
        return "Region %s of %s for %s on %s" % (
            self.region,
            self.advertisement,
            self.publisher,
            self.date,
        )


class KeywordImpression(BaseImpression):

    """
    Create an index of keyword targeting for ads.

    Indexed one per ad/publisher/keyword per day.
    """

    keyword = models.CharField(_("Keyword"), max_length=1000)
    publisher = models.ForeignKey(
        Publisher, related_name="keyword_impressions", on_delete=models.PROTECT
    )
    advertisement = models.ForeignKey(
        Advertisement,
        related_name="keyword_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date", "keyword")

    def __str__(self):
        """Simple override."""
        return "Keyword %s of %s on %s" % (self.keyword, self.advertisement, self.date)


class UpliftImpression(BaseImpression):

    """
    Create an index of uplift for ads.

    Indexed one per ad/publisher per day.
    This is a subset of AdImpressions created by uplift from the Acceptable Ads program.
    """

    publisher = models.ForeignKey(
        Publisher, related_name="uplift_impressions", on_delete=models.PROTECT
    )
    advertisement = models.ForeignKey(
        Advertisement,
        related_name="uplift_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date")

    def __str__(self):
        """Simple override."""
        return "Uplift of %s on %s" % (self.advertisement, self.date)


class RegionTopicImpression(BaseImpression):

    """
    Create an index combining aggregated keywords & geos.

    Indexed one per region/topic/ad/publisher per day.
    """

    region = models.CharField(_("Region"), max_length=100)
    topic = models.CharField(_("Topic"), max_length=100)
    advertisement = models.ForeignKey(
        Advertisement,
        related_name="regiontopic_impressions",
        on_delete=models.PROTECT,
        null=True,
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("date", "region", "topic", "advertisement")

    def __str__(self):
        """Simple override."""
        return f"RegionTopic Impression ({self.region}:{self.topic}) on {self.date}"


class AdBase(TimeStampedModel, IndestructibleModel):

    """A base class for data on ad views and clicks."""

    DIV_MAXLENGTH = 100

    date = models.DateTimeField(_("Impression date"), db_index=True)

    publisher = models.ForeignKey(
        Publisher, null=True, blank=True, on_delete=models.PROTECT
    )

    # This field is overridden in subclasses
    advertisement = models.ForeignKey(
        Advertisement,
        max_length=255,
        related_name="clicks_or_views",
        on_delete=models.PROTECT,
    )

    paid_eligible = models.BooleanField(
        help_text=_("Whether the impression was eligible for a paid ad"),
        default=None,
        null=True,
    )

    # Whether this ad was rotated by the client (rotations > 1).
    # This is needed to measure CTR of rotated ads independently
    rotations = models.PositiveSmallIntegerField(
        _("Number of ad rotations"), default=None, null=True
    )

    # User Data
    ip = models.GenericIPAddressField(_("Ip Address"))  # anonymized
    user_agent = models.CharField(
        _("User Agent"), max_length=1000, blank=True, null=True
    )
    # Client IDs are used primarily for fraud and short term (sub-day) frequency capping
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

    # Client data
    keywords = JSONField(_("Keyword targeting for this view"), blank=True, null=True)
    div_id = models.CharField(
        _("Div id"), blank=True, null=True, max_length=DIV_MAXLENGTH
    )
    # This locked up the DB for a long time trying to write to our huge View table,
    # so we made it a Text field instead of a FK.
    ad_type_slug = models.CharField(_("Ad type"), blank=True, null=True, max_length=100)

    is_bot = models.BooleanField(default=False)
    is_mobile = models.BooleanField(default=False)
    is_proxy = models.BooleanField(default=None, blank=True, null=True)
    is_refunded = models.BooleanField(default=False)

    impression_type = None

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
    impression_type = CLICKS


class View(AdBase):

    """Contains data on ad views."""

    advertisement = models.ForeignKey(
        Advertisement, max_length=255, related_name="views", on_delete=models.PROTECT
    )
    impression_type = VIEWS


class Offer(AdBase):

    """Contains data on ad views."""

    MAX_VIEW_TIME = 5 * 60  # seconds

    # Use an ok user-facing pk value
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    advertisement = models.ForeignKey(
        Advertisement,
        max_length=255,
        related_name="offers",
        on_delete=models.PROTECT,
        null=True,
    )
    impression_type = OFFERS

    # Invalidation logic
    viewed = models.BooleanField(_("Offer was viewed"), default=False)
    clicked = models.BooleanField(_("Offer was clicked"), default=False)

    # The Acceptable Ads program requires us to track how many impressions are attributed to them,
    # so that we can report that data back to them.
    # This uplifted boolean is where we track that on Offers.
    uplifted = models.BooleanField(
        _("Attribute Offer to uplift"), default=None, null=True
    )

    view_time = models.PositiveIntegerField(
        _("Seconds that the ad was in view"),
        default=None,
        null=True,
    )

    @transaction.atomic
    def refund(self):
        """
        Refund this offer and any clicks/views derived from it.

        This does not modify any denormalized index records (eg. GeoImpression, PlacementImpression)
        except for AdImpression itself.
        """
        if self.is_refunded:
            # Prevent double refunding
            return False

        if self.advertisement:
            # Update the denormalized aggregate impression object
            impression = self.advertisement.impressions.get(
                publisher=self.publisher, date=self.date.date()
            )
            AdImpression.objects.filter(pk=impression.pk).update(
                **{self.impression_type: models.F(self.impression_type) - 1}
            )

            # Update the denormalized impressions on the Flight
            # And the denormalized aggregate AdImpressions
            if self.viewed:
                Flight.objects.filter(pk=self.advertisement.flight_id).update(
                    total_views=models.F("total_views") - 1
                )
                AdImpression.objects.filter(pk=impression.pk).update(
                    **{VIEWS: models.F(VIEWS) - 1}
                )
            if self.clicked:
                Flight.objects.filter(pk=self.advertisement.flight_id).update(
                    total_clicks=models.F("total_clicks") - 1
                )
                AdImpression.objects.filter(pk=impression.pk).update(
                    **{CLICKS: models.F(CLICKS) - 1}
                )

        self.is_refunded = True
        self.save()

        return True

    def is_old(self):
        """Checks if this offer is "old" meaning not for a currently running ad."""
        four_hours_ago = timezone.now() - datetime.timedelta(hours=4)
        if four_hours_ago > self.date:
            return True
        return False

    class Meta:
        # This is needed because we can't sort on pk to get the created ordering
        ordering = ("-date",)
        if settings.ADSERVER_OFFER_DB_TABLE:
            db_table = settings.ADSERVER_OFFER_DB_TABLE


class PublisherPayout(TimeStampedModel):

    """Details on historical publisher payouts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publisher = models.ForeignKey(
        Publisher, related_name="payouts", on_delete=models.PROTECT
    )
    amount = models.DecimalField(_("Amount"), max_digits=8, decimal_places=2, default=0)
    date = models.DateTimeField(_("Payout date"))
    method = models.CharField(
        max_length=100,
        choices=PUBLISHER_PAYOUT_METHODS,
        blank=True,
        null=True,
        default=None,
    )
    note = models.TextField(
        _("Note"),
        blank=True,
        null=True,
        help_text=_("A publisher-visible note about the payout"),
    )
    attachment = models.FileField(
        _("Attachment"),
        max_length=255,
        upload_to="payouts/%Y/%m/",
        blank=True,
        null=True,
        help_text=_("A publisher-visible attachment such as a receipt"),
    )
    start_date = models.DateField(
        _("Start Date"),
        help_text=_("First day of paid period"),
        null=True,
    )
    end_date = models.DateField(
        _("End Date"),
        help_text=_("Last day of paid period"),
        null=True,
    )
    status = models.CharField(
        max_length=50,
        choices=PAYOUT_STATUS,
        default=PENDING,
        help_text=_("Status of this payout"),
    )

    history = HistoricalRecords()

    class Meta:
        # This is 'date' instead of '-date' to make `first()` and `last()` work properly
        ordering = ("date",)

    def __str__(self):
        """Simple override."""
        return "%s to %s" % (self.amount, self.publisher)

    @property
    def attachment_filename(self):
        if self.attachment and self.attachment.name:
            return self.attachment.name.split("/")[-1]

        return None

    def get_absolute_url(self):
        return reverse(
            "publisher_payout",
            kwargs={"publisher_slug": self.publisher.slug, "pk": self.pk},
        )
