"""Core models for the ad server."""
import datetime
import html
import logging
import math
import uuid
from collections import Counter
from collections import defaultdict
from collections import OrderedDict

import bleach
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.core.cache import cache
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import IntegrityError
from django.db import models
from django.db import transaction
from django.template import engines
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.html import mark_safe
from django.utils.text import slugify
from django.utils.translation import ugettext_lazy as _
from django_countries import countries
from django_countries.fields import CountryField
from django_extensions.db.models import TimeStampedModel
from jsonfield import JSONField
from user_agents import parse

from .constants import ALL_CAMPAIGN_TYPES
from .constants import CAMPAIGN_TYPES
from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import PAID_CAMPAIGN
from .constants import PUBLISHER_PAYOUT_METHODS
from .constants import VIEWS
from .utils import anonymize_ip_address
from .utils import calculate_ctr
from .utils import calculate_ecpm
from .utils import get_ad_day
from .utils import get_client_id
from .utils import get_client_ip
from .utils import get_client_user_agent
from .utils import get_geolocation
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


class Publisher(TimeStampedModel, IndestructibleModel):

    """
    A publisher that displays advertising from the ad server.

    A publisher represents a site or collection of sites that displays advertising.
    Advertisers can opt-in to displaying ads on different publishers.

    An example of a publisher would be Read the Docs, our first publisher.
    """

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Publisher Slug"), max_length=200)

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

    unauthed_ad_decisions = models.BooleanField(
        default=True,
        help_text=_(
            "Whether this publisher allows unauthenticated ad decision API requests (eg. JSONP)"
        ),
    )

    # Default to False so that we can use this as an "approved" flag for publishers
    allow_paid_campaigns = models.BooleanField(_("Allow paid campaigns"), default=False)
    allow_affiliate_campaigns = models.BooleanField(
        _("Allow affiliate campaigns"), default=False
    )
    allow_community_campaigns = models.BooleanField(
        _("Allow community campaigns"), default=True
    )
    allow_house_campaigns = models.BooleanField(
        _("Allow house campaigns"), default=True
    )

    # Payout information
    payout_method = models.CharField(
        max_length=100,
        choices=PUBLISHER_PAYOUT_METHODS,
        blank=True,
        null=True,
        default=None,
    )
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

    # DEPRECATED - this has no effect and will be removed in a future update
    paid_campaigns_only = models.BooleanField(
        default=True, help_text=_("Only show paid campaigns for this publisher")
    )

    # This overrides settings.ADSERVER_RECORD_VIEWS for a specific publisher
    # Details of each ad view are written to the database.
    # Setting this can result in some performance degradation and a bloated database.
    record_views = models.BooleanField(
        default=True,
        help_text=_("Record each ad view from this publisher to the database"),
    )

    class Meta:
        ordering = ("name",)

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

    def daily_reports(self, start_date=None, end_date=None, campaign_type=None):
        """
        Generates a report of clicks, views, & cost for a given time period for the Publisher.

        :param start_date: the start date to generate the report (or all time)
        :param end_date: the end date for the report (ignored if no `start_date`)
        :param campaign_type: only return campaigns of a specific type (eg. house, paid)
        :return: A dictionary containing a list of days for the report
            and an aggregated total
        """
        report = {"days": [], "total": {}}
        impressions = AdImpression.objects.filter(publisher=self)
        if start_date:
            impressions = impressions.filter(date__gte=start_date)
            if end_date:
                impressions = impressions.filter(date__lte=end_date)
        if campaign_type and campaign_type in ALL_CAMPAIGN_TYPES:
            impressions = impressions.filter(
                advertisement__flight__campaign__campaign_type=campaign_type
            )

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
            days[impression.date]["revenue"] += (
                impression.clicks * float(impression.advertisement.flight.cpc)
            ) + (impression.views * float(impression.advertisement.flight.cpm) / 1000.0)
            days[impression.date]["revenue_share"] = days[impression.date][
                "revenue"
            ] * (self.revenue_share_percentage / 100.0)
            days[impression.date]["our_revenue"] = (
                days[impression.date]["revenue"]
                - days[impression.date]["revenue_share"]
            )
            days[impression.date]["ctr"] = calculate_ctr(
                days[impression.date]["clicks"], days[impression.date]["views"]
            )
            days[impression.date]["ecpm"] = calculate_ecpm(
                days[impression.date]["revenue"], days[impression.date]["views"]
            )

        report["days"] = days.values()

        report["total"]["views"] = sum(day["views"] for day in report["days"])
        report["total"]["clicks"] = sum(day["clicks"] for day in report["days"])
        report["total"]["revenue"] = sum(day["revenue"] for day in report["days"])
        report["total"]["revenue_share"] = sum(
            day["revenue_share"] for day in report["days"]
        )
        report["total"]["our_revenue"] = (
            report["total"]["revenue"] - report["total"]["revenue_share"]
        )
        report["total"]["ctr"] = calculate_ctr(
            report["total"]["clicks"], report["total"]["views"]
        )
        report["total"]["ecpm"] = calculate_ecpm(
            report["total"]["revenue"], report["total"]["views"]
        )

        return report

    def total_payout_sum(self):
        """
        The total amount ever paid out to this publisher
        """

        total = self.payouts.all().aggregate(
            total=models.Sum("amount", output_field=models.DecimalField())
        )["total"]
        if total:
            return total
        return 0

    def total_revshare_sum(self, start_date=None, end_date=None):
        """
        Total revshare of all ads the publisher has ever shown
        """

        total = 0

        impressions = AdImpression.objects.filter(publisher=self)
        if start_date:
            impressions = impressions.filter(date__gte=start_date)
        if end_date:
            impressions = impressions.filter(date__lte=end_date)
        impressions = impressions.select_related(
            "advertisement", "advertisement__flight"
        )
        for impression in impressions:
            revenue = (
                impression.clicks * float(impression.advertisement.flight.cpc)
            ) + (impression.views * float(impression.advertisement.flight.cpm) / 1000.0)
            total += revenue * (self.revenue_share_percentage / 100.0)

        return total


class PublisherGroup(TimeStampedModel):

    """Group of publishers that can be targeted by advertiser's campaigns."""

    name = models.CharField(
        _("Name"), max_length=200, help_text=_("Visible to advertisers")
    )
    slug = models.SlugField(_("Publisher group slug"), max_length=200)

    publishers = models.ManyToManyField(
        Publisher,
        related_name="publisher_groups",
        blank=True,
        help_text=_("A group of publishers that can be targeted by advertisers"),
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name


class Advertiser(TimeStampedModel, IndestructibleModel):

    """An advertiser who buys advertising from the ad server."""

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Advertiser Slug"), max_length=200)

    stripe_customer_id = models.CharField(
        _("Stripe Customer ID"), max_length=200, blank=True, null=True, default=None
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name

    def get_absolute_url(self):
        return reverse("advertiser_report", kwargs={"advertiser_slug": self.slug})

    def daily_reports(self, start_date=None, end_date=None):
        """
        Generates a report of clicks, views, & cost for a given time period for the Advertiser.

        :param start_date: the start date to generate the report (or all time)
        :param end_date: the end date for the report (ignored if no `start_date`)
        :return: A dictionary containing a list of days for the report
            and an aggregated total
        """
        report = {"days": [], "total": {}}
        impressions = AdImpression.objects.filter(
            advertisement__flight__campaign__advertiser=self
        )
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
    slug = models.SlugField(_("Campaign Slug"), max_length=200)

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

    # Deprecated and scheduled for removal
    publishers = models.ManyToManyField(
        Publisher,
        related_name="campaigns",
        blank=True,
        help_text=_(
            "Ads for this campaign are eligible for display on these publishers"
        ),
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        """Simple override."""
        return self.name

    def ad_count(self):
        return Advertisement.objects.filter(flight__campaign=self).count()

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

        report["days"] = list(days.values())

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

    name = models.CharField(_("Name"), max_length=200)
    slug = models.SlugField(_("Flight Slug"), max_length=200)
    start_date = models.DateField(
        _("Start Date"),
        default=datetime.date.today,
        db_index=True,
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

    # Denormalized fields
    total_views = models.PositiveIntegerField(
        default=0, help_text=_("Views across all ads in this flight")
    )
    total_clicks = models.PositiveIntegerField(
        default=0, help_text=_("Clicks across all ads in this flight")
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
    def state(self):
        today = get_ad_day().date()
        if self.live and self.start_date <= today:
            return _("Current")
        if self.end_date > today:
            return _("Upcoming")
        return _("Past")

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
        if self.excluded_countries and country_code in self.excluded_countries:
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

    def sold_days(self):
        # Add one to count both the start and end day
        return max(0, (self.end_date - self.start_date).days) + 1

    def days_remaining(self):
        """Number of days left in a flight."""
        return max(0, (self.end_date - get_ad_day().date()).days)

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
        if (
            not self.live
            or self.views_remaining() <= 0
            or self.start_date > get_ad_day().date()
        ):
            return 0

        if self.days_remaining() > 0:
            flight_remaining_percentage = self.days_remaining() / self.sold_days()

            # This is how many views should be remaining this far in the flight
            flight_views_pace = int(self.sold_impressions * flight_remaining_percentage)

            return max(0, self.views_remaining() - flight_views_pace)

        return self.views_remaining()

    def clicks_needed_today(self):
        """Calculates clicks needed based on the impressions this flight's ads have."""
        if (
            not self.live
            or self.clicks_remaining() <= 0
            or self.start_date > get_ad_day().date()
        ):
            return 0

        if self.days_remaining() > 0:
            flight_remaining_percentage = self.days_remaining() / self.sold_days()

            # This is how many clicks we should have remaining this far in the flight
            flight_clicks_pace = int(self.sold_clicks * flight_remaining_percentage)

            return max(0, self.clicks_remaining() - flight_clicks_pace)

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

    def daily_reports(
        self, start_date=None, end_date=None, name_filter=None, inactive=True
    ):
        """
        Generates a report of clicks, views, & cost for a given time period for the Flight.

        :param start_date: the start date to generate the report (or all time)
        :param end_date: the end date for the report (ignored if no `start_date`)
        :param name_filter: ignore ads that don't match the specified string
        :param inactive: if True, show inactive ads in addition to live ones
        :return: A dictionary containing a list of days for the report and an aggregated total
        """
        report = {"days": [], "total": {}}

        impressions = AdImpression.objects.filter(advertisement__flight=self)
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

    def ad_reports(self, start_date=None, end_date=None):
        """
        Generates a report broken down by advertisement in the given time period.

        :param start_date: the start date to generate the report (or all time)
        :param end_date: the end date for the report (ignored if no `start_date`)
        :return: A list of ads and their daily report for all ads in the time period.
        """
        ad_reports = []

        for ad in self.advertisements.prefetch_related("ad_types"):
            report = ad.daily_reports(start_date=start_date, end_date=end_date)
            if report["total"]["views"]:
                ad_reports.append((ad, report))

        return ad_reports


class AdType(TimeStampedModel, models.Model):

    """
    A type of advertisement including such parameters as the amount of text and images size.

    Many ad types are industry standards from the Interactive Advertising Bureau (IAB).
    Some publishers prefer native ads that are custom sized for their needs.

    See https://www.iab.com/newadportfolio/
    """

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
    slug = models.SlugField(_("Slug"), max_length=200)
    text = models.TextField(
        _("Text"),
        blank=True,
        help_text=_("Different ad types have different text requirements"),
    )
    # Supports simple variables like ${publisher} and ${advertisement}
    # using string.Template syntax
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

    class Meta:
        ordering = ("slug", "-live")

    def __str__(self):
        """Simple override."""
        return self.name

    def cache_key(self, impression_type, nonce):
        assert impression_type in IMPRESSION_TYPES + ("publisher",)
        return "advertisement:{id}:{nonce}:{type}".format(
            id=self.slug, nonce=nonce, type=impression_type
        )

    def incr(self, impression_type, publisher):
        """Add to the number of times this action has been performed, stored in the DB."""
        assert impression_type in IMPRESSION_TYPES
        day = get_ad_day().date()

        # Ensure that an impression object exists for today
        impression, _ = self.impressions.get_or_create(publisher=publisher, date=day)

        AdImpression.objects.filter(pk=impression.pk).update(
            **{impression_type: models.F(impression_type) + 1}
        )

        # Update the denormalized fields on the Flight
        if impression_type == VIEWS:
            Flight.objects.filter(pk=self.flight_id).update(
                total_views=models.F("total_views") + 1
            )
        elif impression_type == CLICKS:
            Flight.objects.filter(pk=self.flight_id).update(
                total_clicks=models.F("total_clicks") + 1
            )

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
            date=timezone.now(),
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

    def track_impression(self, request, impression_type, publisher, url):
        if impression_type not in (CLICKS, VIEWS):
            raise RuntimeError("Impression must be either a click or a view")

        if impression_type == CLICKS:
            self.track_click(request, publisher, url)
        elif impression_type == VIEWS:
            self.track_view(request, publisher, url)

    def track_click(self, request, publisher, url):
        """Store click data in the DB."""
        self.incr(CLICKS, publisher)
        return self._record_base(request, Click, publisher, url)

    def track_view(self, request, publisher, url):
        """
        Store view data in the DB.

        Views are only stored if ``settings.ADSERVER_RECORD_VIEWS=True``
        Or if a publisher has the ``Publisher.record_views`` flag set.
        For a large scale ad server, writing a database record per ad view
        is not feasible
        """
        self.incr(VIEWS, publisher)

        if settings.ADSERVER_RECORD_VIEWS or publisher.record_views:
            return self._record_base(request, View, publisher, url)

        log.debug("Not recording ad view.")
        return None

    def offer_ad(self, publisher, ad_type_slug):
        """
        Offer to display this ad on a specific publisher and a specific display (ad type).

        Tracks an offer in the database and sets various cache variables
        """
        ad_type = AdType.objects.filter(slug=ad_type_slug).first()

        # The time after an ad has been offered where impressions (clicks) won't count
        offer_time_limit = 60 * 60 * 4  # 4 hours

        nonce = get_random_string(16)

        site = get_current_site(None)
        domain = site.domain
        scheme = "http"
        if settings.ADSERVER_HTTPS:
            scheme = "https"

        view_url = "{scheme}://{domain}{url}".format(
            scheme=scheme,
            domain=domain,
            url=reverse(
                "view-proxy", kwargs={"advertisement_id": self.pk, "nonce": nonce}
            ),
        )

        click_url = "{scheme}://{domain}{url}".format(
            scheme=scheme,
            domain=domain,
            url=reverse(
                "click-proxy", kwargs={"advertisement_id": self.pk, "nonce": nonce}
            ),
        )

        # This required unescaping HTML entities that bleach escapes,
        # allowing it to be used outside of HTML contexts.
        # https://github.com/mozilla/bleach/issues/192
        body = html.unescape(bleach.clean(self.text, tags=[], strip=True))

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

        return {
            "id": self.slug,
            "text": self.text,
            "body": body,
            "html": self.render_ad(ad_type, click_url=click_url, view_url=view_url),
            "image": self.image.url if self.image else None,
            "link": click_url,
            "view_url": view_url,
            "nonce": nonce,
            "display_type": ad_type_slug,
            "campaign_type": self.flight.campaign.campaign_type,
        }

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

        return report

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

    def render_ad(self, ad_type, click_url=None, view_url=None):
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

        return template.render(
            {
                "ad": self,
                "image_url": self.image.url if self.image else None,
                "link_url": click_url or self.link,
                "view_url": view_url,
                "text_as_html": self.render_links(link=click_url),
            }
        ).strip()


class BaseImpression(TimeStampedModel, models.Model):

    """Statistics for tracking."""

    date = models.DateField(_("Date"))

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
        Advertisement, related_name="impressions", on_delete=models.PROTECT
    )

    class Meta:
        ordering = ("-date",)
        unique_together = ("publisher", "advertisement", "date")
        verbose_name_plural = _("Ad impressions")

    def __str__(self):
        """Simple override."""
        return "%s on %s" % (self.advertisement, self.date)


class AdBase(TimeStampedModel, IndestructibleModel):

    """A base class for data on ad views and clicks."""

    date = models.DateTimeField(_("Impression date"))

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
    is_refunded = models.BooleanField(default=False)

    impression_type = None

    class Meta:
        abstract = True

    def __str__(self):
        """Simple override."""
        return "%s on %s (%s)" % (self._meta.object_name, self.advertisement, self.url)

    def get_absolute_url(self):
        return self.url

    @transaction.atomic
    def refund(self):
        """Refund this view or click."""
        if self.is_refunded:
            # Prevent double refunding
            return False

        # Update the denormalized aggregate impression object
        impression = self.advertisement.impressions.get(
            publisher=self.publisher, date=self.date.date()
        )
        AdImpression.objects.filter(pk=impression.pk).update(
            **{self.impression_type: models.F(self.impression_type) - 1}
        )

        # Update the denormalized impressions on the Flight
        if self.impression_type == VIEWS:
            Flight.objects.filter(pk=self.advertisement.flight_id).update(
                total_views=models.F("total_views") - 1
            )
        elif self.impression_type == CLICKS:
            Flight.objects.filter(pk=self.advertisement.flight_id).update(
                total_clicks=models.F("total_clicks") - 1
            )

        self.is_refunded = True
        self.save()

        return True


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

    @property
    def last_paid_month(self):
        """
        The month that this payout was up until.

        This could include payments from multiple months,
        if we had to wait for a publisher to get to the minimum.
        """
        # TODO: Make this a proper model method,
        # so that we don't have to guess what month the payout is from
        return self.date.replace(day=1) - datetime.timedelta(days=1)

    def get_absolute_url(self):
        return reverse(
            "publisher_payout",
            kwargs={"publisher_slug": self.publisher.slug, "pk": self.pk},
        )
