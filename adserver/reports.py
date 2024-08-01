"""Advertising performance reports displayed to advertisers, publishers, and staff."""

import collections
import datetime
import logging
import operator

from .constants import PAID_CAMPAIGN
from .models import AdImpression
from .models import AdvertiserImpression
from .models import GeoImpression
from .models import KeywordImpression
from .models import PlacementImpression
from .models import PublisherPaidImpression
from .models import RegionImpression
from .models import RegionTopicImpression
from .models import UpliftImpression
from .utils import calculate_ctr
from .utils import calculate_ecpm
from .utils import get_country_name


log = logging.getLogger(__name__)  # noqa


class BaseReport:
    """Base report which other reports are extended from."""

    # Model of the aggregated impression class
    # This is used to validate that the expected queryset class matches the passed one
    model = None

    # This is a "getter" (potentially dotted) used to get the field that the data is indexed by
    # For example, to get a report broken down by day, use ``date`` which will get ``adimpression.date``
    index = None

    # The "getter" to order the results by (``-views`` to order by views descending)
    order = None

    DEFAULT_MAX_RESULTS = 65535

    # Fields to apply select_related on the queryset
    select_related_fields = ("advertisement", "advertisement__flight")

    def __init__(
        self, queryset, index=None, order=None, max_results=None, export=False, **kwargs
    ):
        """
        Initialize the report using filtered, ordered queryset.

        :param queryset: A filtered queryset to use with the report.
        :param index: Override the report result index.
            This is sometimes necessary for example when filtering a geo report to a specific country,
            you probably want to index by date.
        :param order: Override the report result order.
        :param export: Tell the report if it's being exported, so it can adjust display for processing
        :param max_results: Override the maximum results to return
        """
        self.queryset = queryset

        if index:
            self.index = index
        if order:
            self.order = order
        if max_results:
            self.max_results = max_results
        else:
            self.max_results = self.DEFAULT_MAX_RESULTS

        self.export = export

        # Save any other keyword args for use in subclasses
        self.kwargs = kwargs

        # Processed fields available after the report has been generated
        self.total = {}
        self.results = []

        if self.queryset.model is not self.model:
            raise RuntimeError(
                f"Report queryset (type {self.queryset.model}) is not type {self.model}"
            )

    def get_index_display(self, index):
        """Used to add display logic the index field."""
        return index

    def generate(self):
        raise NotImplementedError("Subclasses implement this method")


class AdvertiserReport(BaseReport):
    """Report for showing daily ad performance for an advertiser."""

    model = AdImpression
    index = "date"
    order = "-date"

    def generate(self):
        """Generate/calculate the report from the queryset by the index."""
        queryset = self.queryset.select_related(*self.select_related_fields)

        # This allows us to use `.` in the report_index to span relations
        getter = operator.attrgetter(self.index)

        results = {}

        for impression in queryset:
            index = getter(impression)

            if index not in results:
                results[index] = collections.defaultdict(int)

            results[index]["index"] = self.get_index_display(index)
            results[index][self.index] = self.get_index_display(index)
            results[index]["views"] += impression.views
            results[index]["clicks"] += impression.clicks

            # Calculate advertiser cost if the offer resulted in an ad impression
            # There's no revenue for offers with no views/clicks
            if hasattr(impression, "advertisement"):
                results[index]["cost"] += (
                    impression.clicks * float(impression.advertisement.flight.cpc)
                ) + (
                    impression.views
                    * float(impression.advertisement.flight.cpm)
                    / 1000.0
                )
            elif hasattr(impression, "spend"):
                results[index]["cost"] += float(impression.spend)

            # These fields must be calculated from the fields above
            results[index]["ctr"] = calculate_ctr(
                results[index]["clicks"], results[index]["views"]
            )
            results[index]["ecpm"] = calculate_ecpm(
                results[index]["cost"], results[index]["views"]
            )

        # Store, order, and aggregate on the report results
        self.results = sorted(
            results.values(),
            key=lambda obj: obj[self.order.lstrip("-")],
            reverse=self.order.startswith("-"),
        )[: self.max_results]
        self.calculate_totals()

    def calculate_totals(self):
        """Calculate the totals across the report results."""
        self.total["index"] = "Total"
        self.total["views"] = sum(result["views"] for result in self.results)
        self.total["clicks"] = sum(result["clicks"] for result in self.results)
        self.total["cost"] = sum(result["cost"] for result in self.results)
        self.total["ctr"] = calculate_ctr(self.total["clicks"], self.total["views"])
        self.total["ecpm"] = calculate_ecpm(self.total["cost"], self.total["views"])


class OptimizedAdvertiserReport(AdvertiserReport):
    """A report using the optimized AdvertiserImpression index showing daily ad performance for an advertiser."""

    model = AdvertiserImpression
    index = "date"
    order = "-date"
    select_related_fields = ()


class AdvertiserGeoReport(AdvertiserReport):
    """Report to breakdown advertiser performance by country."""

    model = GeoImpression
    index = "country"
    order = "-views"

    def get_index_display(self, index):
        if self.index == "country":
            return get_country_name(index)

        return super().get_index_display(index)


class AdvertiserPublisherReport(AdvertiserReport):
    """Report to breakdown advertiser performance by publisher."""

    model = AdImpression
    index = "publisher"
    order = "-views"
    select_related_fields = ("advertisement", "advertisement__flight", "publisher")


class PublisherReport(BaseReport):
    """Report for showing daily ad performance for a publisher."""

    model = AdImpression
    index = "date"
    order = "-date"
    select_related_fields = (
        "publisher",
        "advertisement",
        "advertisement__flight",
        "advertisement__flight__campaign",
    )

    def generate(self):
        """Generate/calculate the report from the queryset by the index."""
        # Allow more custom getter functions for multi-dimensional indexes
        if not hasattr(self, "getter"):
            # This allows us to use `.` in the report_index to span relations
            self.getter = operator.attrgetter(self.index)

        queryset = self.queryset.select_related(*self.select_related_fields)

        results = {}

        for impression in queryset:
            index = self.getter(impression)

            if index not in results:
                results[index] = collections.defaultdict(int)

            # Count offers for all paid campaigns
            # This is required to get an accurate fill rate when house ads are on
            if (
                getattr(impression, "advertisement", None)
                and impression.advertisement.flight.campaign.campaign_type
                == PAID_CAMPAIGN
            ):
                results[index]["paid_offers"] += impression.offers
            elif self.model == PublisherPaidImpression:
                # This is the publisher paid model
                # All offers are paid
                results[index]["paid_offers"] += impression.offers

            results[index]["index"] = self.get_index_display(index)
            results[index][self.index] = index
            results[index]["decisions"] += impression.decisions
            results[index]["offers"] += impression.offers
            results[index]["views"] += impression.views
            results[index]["clicks"] += impression.clicks

            # Calculate our revenue if the offer resulted in an ad impression
            # There's no revenue for offers with no views/clicks
            if getattr(impression, "advertisement", None):
                results[index]["revenue"] += (
                    impression.clicks * float(impression.advertisement.flight.cpc)
                ) + (
                    impression.views
                    * float(impression.advertisement.flight.cpm)
                    / 1000.0
                )
            elif hasattr(impression, "revenue"):
                # For the optimized indexes, the revenue is already calculated
                results[index]["revenue"] += float(impression.revenue)

            # Support arbitrary revshare numbers on reporting
            applied_rev_share = float(
                self.kwargs.get("force_revshare")
                or impression.publisher.revenue_share_percentage
            )
            results[index]["revenue_share"] = results[index]["revenue"] * (
                applied_rev_share / 100.0
            )
            results[index]["revenue_share_ecpm"] = calculate_ecpm(
                results[index]["revenue_share"], results[index]["views"]
            )
            results[index]["our_revenue"] = (
                results[index]["revenue"] - results[index]["revenue_share"]
            )

            # These fields must be calculated from the fields above
            results[index]["ctr"] = calculate_ctr(
                results[index]["clicks"], results[index]["views"]
            )
            results[index]["ecpm"] = calculate_ecpm(
                results[index]["revenue"], results[index]["views"]
            )
            results[index]["fill_rate"] = calculate_ctr(
                results[index]["paid_offers"], results[index]["decisions"]
            )
            results[index]["view_rate"] = calculate_ctr(
                results[index]["views"], results[index]["offers"]
            )

        # Store, order, and aggregate on the report results
        self.results = sorted(
            results.values(),
            key=lambda obj: obj[self.order.lstrip("-")],
            reverse=self.order.startswith("-"),
        )[: self.max_results]
        self.calculate_totals()

    def calculate_totals(self):
        """Calculate the totals across the report results."""
        self.total["index"] = "Total"
        self.total["decisions"] = sum(result["decisions"] for result in self.results)
        self.total["offers"] = sum(result["offers"] for result in self.results)
        self.total["paid_offers"] = sum(
            result["paid_offers"] for result in self.results
        )
        self.total["views"] = sum(result["views"] for result in self.results)
        self.total["clicks"] = sum(result["clicks"] for result in self.results)
        self.total["revenue"] = sum(result["revenue"] for result in self.results)
        self.total["revenue_share"] = sum(
            result["revenue_share"] for result in self.results
        )
        self.total["revenue_share_ecpm"] = calculate_ecpm(
            self.total["revenue_share"], self.total["views"]
        )
        self.total["our_revenue"] = self.total["revenue"] - self.total["revenue_share"]
        self.total["ctr"] = calculate_ctr(self.total["clicks"], self.total["views"])
        self.total["ecpm"] = calculate_ecpm(self.total["revenue"], self.total["views"])
        self.total["fill_rate"] = calculate_ctr(
            self.total["paid_offers"], self.total["decisions"]
        )
        self.total["view_rate"] = calculate_ctr(
            self.total["views"], self.total["offers"]
        )

    def get_index_display(self, index):
        """Handle making sure dates use the same 3 letter syntax as Django."""
        if isinstance(index, datetime.date):
            # %a is the day of week, so you know which are weekends
            value = index.strftime("%b %d, %Y")
            # Make it so these parse as dates in a CSV
            if not self.export:
                value += index.strftime(" (%a)")
            return value

        return super().get_index_display(index)


class OptimizedPublisherPaidReport(PublisherReport):
    """
    A report using the optimized PublisherPaidImpression index showing daily ad performance for a publisher.

    Note: only shows PAID impressions
    """

    model = PublisherPaidImpression
    index = "date"
    order = "-date"
    select_related_fields = ("publisher",)


class PublisherGeoReport(PublisherReport):
    """Report to breakdown publisher performance by country."""

    model = GeoImpression
    index = "country"
    order = "-views"

    def get_index_display(self, index):
        if self.index == "country":
            return get_country_name(index)

        return super().get_index_display(index)


class PublisherRegionReport(PublisherReport):
    """Report to breakdown publisher performance by country."""

    model = RegionImpression
    index = "region"
    order = "-views"
    select_related_fields = (
        "advertisement",
        "advertisement__flight",
        "advertisement__flight__campaign",
    )


class PublisherPlacementReport(PublisherReport):
    """Report to breakdown publisher performance by placement (<div>'s, ad type)."""

    model = PlacementImpression
    index = "div_id"
    order = "-views"


class PublisherAdvertiserReport(PublisherReport):
    """Report to breakdown publisher performance by advertiser."""

    model = AdImpression
    index = "advertisement.flight.campaign.advertiser"
    order = "-views"
    select_related_fields = (
        "publisher",
        "advertisement",
        "advertisement__flight",
        "advertisement__flight__campaign",
        "advertisement__flight__campaign__advertiser",
    )


class PublisherKeywordReport(PublisherReport):
    """Report to breakdown publisher performance by keyword."""

    model = KeywordImpression
    index = "keyword"
    order = "-views"


class PublisherUpliftReport(PublisherReport):
    """Report to breakdown publisher performance by keyword."""

    model = UpliftImpression
    index = "publisher.name"
    order = "-views"


class PublisherRegionTopicReport(PublisherReport):
    """Report to breakdown publisher performance by region & topic."""

    model = RegionTopicImpression
    index = "topic"
    order = "-views"
    select_related_fields = (
        "advertisement",
        "advertisement__flight",
        "advertisement__flight__campaign",
        "advertisement__flight__campaign__advertiser",
    )

    def getter(self, data):  # pylint: disable=method-hidden
        """Show both region & topic in the index."""
        if self.index != "date":
            return f"{data.region}:{data.topic}"
        # Fallback if not used
        return operator.attrgetter(self.index)(data)
