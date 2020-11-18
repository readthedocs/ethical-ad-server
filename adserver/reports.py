"""Advertising performance reports displayed to advertisers, publishers, and staff."""
import collections
import logging

from .constants import ALL_CAMPAIGN_TYPES
from .models import AdImpression
from .utils import calculate_ctr
from .utils import calculate_ecpm


log = logging.getLogger(__name__)  # noqa


class BaseReport:

    """Base report which other reports are extended from."""

    model = None

    def __init__(self, start_date, end_date=None, **kwargs):
        """Initialize the report using the passed filter parameters."""
        self.start_date = start_date
        self.end_date = end_date

        # Save any other keyword args for use in subclasses
        self.kwargs = kwargs

        # Generated fields available after the report has been processed
        self.total = {}

        if not self.start_date:
            raise RuntimeError("Start date is required")
        if self.end_date and self.start_date > self.end_date:
            log.warning(
                "Start date is after the end date. This report will return nothing."
            )

    def get_queryset(self):
        raise NotImplementedError("Subclasses implement this method")

    def generate(self):
        raise NotImplementedError("Subclasses implement this method")


class PublisherReport(BaseReport):

    """Report for showing daily ad performance for a publisher by day."""

    model = AdImpression

    def __init__(self, publisher, campaign_type=None, **kwargs):
        """
        Initialize the report with the passed filter parameters.

        :param publisher: the publisher for this report (required)
        :param campaign_type: limit to a specific campaign type (optional)
        """
        self.publisher = publisher

        self.campaign_type = campaign_type

        # Generated fields available after the report has been processed
        self.days = []

        if not self.publisher:
            raise RuntimeError("Publisher is required")
        if self.campaign_type and self.campaign_type not in ALL_CAMPAIGN_TYPES:
            self.campaign_type = None
            log.warning(
                "Invalid campaign type %s, not limiting the report by campaign type",
                campaign_type,
            )

        super().__init__(**kwargs)

    def get_queryset(self):
        queryset = self.model.objects.filter(publisher=self.publisher).filter(
            date__gte=self.start_date
        )

        # Limit the report by end date
        if self.end_date:
            queryset = queryset.filter(date__lte=self.end_date)

        # Limit the report to specific campaign types
        if self.campaign_type:
            queryset = queryset.filter(
                advertisement__flight__campaign__campaign_type=self.campaign_type
            )

        return queryset

    def generate(self):
        queryset = self.get_queryset()
        queryset = queryset.select_related("advertisement", "advertisement__flight")

        days = collections.OrderedDict()

        for impression in queryset:
            if impression.date not in days:
                days[impression.date] = collections.defaultdict(int)

            days[impression.date]["date"] = impression.date
            days[impression.date]["index"] = impression.date
            days[impression.date]["decisions"] += impression.decisions
            days[impression.date]["offers"] += impression.offers
            days[impression.date]["views"] += impression.views
            days[impression.date]["clicks"] += impression.clicks

            # Calculate our revenue if the offer resulted in an ad impression
            # There's no revenue for offers with no views/clicks
            if impression.advertisement:
                days[impression.date]["revenue"] += (
                    impression.clicks * float(impression.advertisement.flight.cpc)
                ) + (
                    impression.views
                    * float(impression.advertisement.flight.cpm)
                    / 1000.0
                )
                days[impression.date]["revenue_share"] = days[impression.date][
                    "revenue"
                ] * (self.publisher.revenue_share_percentage / 100.0)
                days[impression.date]["our_revenue"] = (
                    days[impression.date]["revenue"]
                    - days[impression.date]["revenue_share"]
                )

            # These fields must be calculated from the fields above
            days[impression.date]["ctr"] = calculate_ctr(
                days[impression.date]["clicks"], days[impression.date]["views"]
            )
            days[impression.date]["ecpm"] = calculate_ecpm(
                days[impression.date]["revenue"], days[impression.date]["views"]
            )
            days[impression.date]["fill_rate"] = calculate_ctr(
                days[impression.date]["offers"], days[impression.date]["decisions"]
            )
            days[impression.date]["view_rate"] = calculate_ctr(
                days[impression.date]["views"], days[impression.date]["offers"]
            )

        self.days = days.values()

        self.calculate_totals()

    def calculate_totals(self):
        """Calculate the totals across the report data."""
        self.total["decisions"] = sum(day["decisions"] for day in self.days)
        self.total["offers"] = sum(day["offers"] for day in self.days)
        self.total["views"] = sum(day["views"] for day in self.days)
        self.total["clicks"] = sum(day["clicks"] for day in self.days)
        self.total["revenue"] = sum(day["revenue"] for day in self.days)
        self.total["revenue_share"] = sum(day["revenue_share"] for day in self.days)
        self.total["our_revenue"] = self.total["revenue"] - self.total["revenue_share"]
        self.total["ctr"] = calculate_ctr(self.total["clicks"], self.total["views"])
        self.total["ecpm"] = calculate_ecpm(self.total["revenue"], self.total["views"])
        self.total["fill_rate"] = calculate_ctr(
            self.total["offers"], self.total["decisions"]
        )
        self.total["view_rate"] = calculate_ctr(
            self.total["views"], self.total["offers"]
        )
