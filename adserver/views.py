"""Ad server views."""
import collections
import logging
from datetime import datetime
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import TemplateView

from .constants import CAMPAIGN_TYPES
from .models import AdImpression
from .models import Advertisement
from .models import Advertiser
from .models import Publisher
from .utils import calculate_ctr
from .utils import calculate_ecpm
from .utils import get_ad_day


log = logging.getLogger(__name__)  # noqa


def do_not_track(request):
    """
    Returns the Do Not Track status for the user.

    https://w3c.github.io/dnt/drafts/tracking-dnt.html#status-representation

    :raises: Http404 if ``settings.ADSERVER_DO_NOT_TRACK`` is ``False``
    """
    if not settings.ADSERVER_DO_NOT_TRACK:
        raise Http404

    dnt_header = request.META.get("HTTP_DNT")

    data = {"tracking": "N" if dnt_header == "1" else "T"}
    if settings.ADSERVER_PRIVACY_POLICY_URL:
        data["policy"] = settings.ADSERVER_PRIVACY_POLICY_URL

    # pylint: disable=redundant-content-type-for-json-response
    return JsonResponse(data, content_type="application/tracking-status+json")


def do_not_track_policy(request):
    """
    Returns the Do Not Track policy.

    https://github.com/EFForg/dnt-guide#12-how-to-assert-dnt-compliance

    :raises: Http404 if ``settings.ADSERVER_DO_NOT_TRACK`` is ``False``
    """
    if not settings.ADSERVER_DO_NOT_TRACK:
        raise Http404

    return render(request, "adserver/dnt-policy.txt", content_type="text/plain")


@login_required
def dashboard(request):
    """The initial dashboard view."""
    if request.user.is_staff:
        publishers = Publisher.objects.all()
        advertisers = Advertiser.objects.all()
    else:
        publishers = request.user.publishers.all()
        advertisers = request.user.advertisers.all()

    return render(
        request,
        "adserver/dashboard.html",
        {"advertisers": advertisers, "publishers": publishers},
    )


class BaseReportView(UserPassesTestMixin, TemplateView):

    """
    A base report that other reports can extend.

    By default, it restricts access to staff and sets up date context variables.
    """

    DEFAULT_REPORT_DAYS = 30

    def test_func(self):
        """By default, reports are locked down to staff."""
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        start_date = self.get_start_date()
        end_date = self.get_end_date()
        campaign_type = self.request.GET.get("campaign_type", "")

        if end_date and end_date < start_date:
            end_date = None

        return {
            "start_date": start_date,
            "end_date": end_date,
            "campaign_type": campaign_type,
        }

    def _parse_date_string(self, date_str):
        try:
            return timezone.make_aware(datetime.strptime(date_str, "%Y-%m-%d"))
        except ValueError:
            # Since this can come from GET params, handle errors
            pass

        return None

    def get_start_date(self):
        if "start_date" in self.request.GET:
            start_date = self._parse_date_string(self.request.GET["start_date"])
            if start_date:
                return start_date

        return get_ad_day() - timedelta(days=self.DEFAULT_REPORT_DAYS)

    def get_end_date(self):
        if "end_date" in self.request.GET:
            end_date = self._parse_date_string(self.request.GET["end_date"])
            if end_date:
                return end_date

        return None


class AdvertiserReportView(BaseReportView):

    """A report for one advertiser."""

    template_name = "adserver/reports/advertiser.html"

    def test_func(self):
        """The user must have access on the advertiser or be staff."""
        if self.request.user.is_anonymous:
            return False

        advertiser = get_object_or_404(Advertiser, slug=self.kwargs["advertiser_slug"])
        return (
            self.request.user.is_staff
            or advertiser in self.request.user.advertisers.all()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data()

        advertiser_slug = kwargs.get("advertiser_slug", "")

        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)
        advertisements = Advertisement.objects.filter(
            flight__campaign__advertiser=advertiser
        )
        advertisements = advertisements.select_related(
            "flight", "flight__campaign", "flight__campaign"
        )

        ads_and_reports = []
        for ad in advertisements:
            report = ad.daily_reports(
                start_date=context["start_date"], end_date=context["end_date"]
            )
            if report["total"]["views"]:
                ads_and_reports.append((ad, report))

        advertiser_report = advertiser.daily_reports(
            start_date=context["start_date"], end_date=context["end_date"]
        )

        context.update(
            {
                "advertiser": advertiser,
                "advertiser_report": advertiser_report,
                "ads_and_reports": ads_and_reports,
                "total_clicks": advertiser_report["total"]["clicks"],
                "total_cost": advertiser_report["total"]["cost"],
                "total_views": advertiser_report["total"]["views"],
                "total_ctr": advertiser_report["total"]["ctr"],
            }
        )

        return context


class AllAdvertiserReportView(BaseReportView):

    """A report aggregating all advertisers."""

    template_name = "adserver/reports/all-advertisers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()

        # Get all advertisers where an ad for that advertiser has a view or click
        # in the specified date range
        impressions = AdImpression.objects.filter(date__gte=context["start_date"])
        if context["end_date"]:
            impressions = impressions.filter(date__lte=context["end_date"])
        advertisers = Advertiser.objects.filter(
            id__in=Advertisement.objects.filter(
                id__in=impressions.values("advertisement")
            ).values("flight__campaign__advertiser")
        )

        advertisers_and_reports = []
        for advertiser in advertisers:
            report = advertiser.daily_reports(
                start_date=context["start_date"], end_date=context["end_date"]
            )
            if report["total"]["views"] > 0:
                advertisers_and_reports.append((advertiser, report))

        total_clicks = sum(
            report["total"]["clicks"] for _, report in advertisers_and_reports
        )
        total_views = sum(
            report["total"]["views"] for _, report in advertisers_and_reports
        )
        total_cost = sum(
            report["total"]["cost"] for _, report in advertisers_and_reports
        )

        # Aggregate the different advertiser reports by day
        days = {}
        for advertiser, report in advertisers_and_reports:
            for day in report["days"]:
                if day["date"] not in days:
                    days[day["date"]] = collections.defaultdict(int)
                    days[day["date"]]["views_by_advertiser"] = {}
                    days[day["date"]]["clicks_by_advertiser"] = {}

                days[day["date"]]["date"] = day["date"].strftime("%Y-%m-%d")
                days[day["date"]]["views"] += day["views"]
                days[day["date"]]["clicks"] += day["clicks"]
                days[day["date"]]["views_by_advertiser"][advertiser.name] = day["views"]
                days[day["date"]]["clicks_by_advertiser"][advertiser.name] = day[
                    "clicks"
                ]
                days[day["date"]]["cost"] += float(day["cost"])
                days[day["date"]]["ctr"] = calculate_ctr(
                    days[day["date"]]["clicks"], days[day["date"]]["views"]
                )

        context.update(
            {
                "advertisers": [a for a, _ in advertisers_and_reports],
                "advertisers_and_reports": advertisers_and_reports,
                "total_clicks": total_clicks,
                "total_cost": total_cost,
                "total_views": total_views,
                "total_ctr": calculate_ctr(total_clicks, total_views),
                "total_ecpm": calculate_ecpm(total_cost, total_views),
            }
        )

        return context


class PublisherReportView(BaseReportView):

    """A report for a single publisher."""

    template_name = "adserver/reports/publisher.html"

    def test_func(self):
        """The user must have access on the publisher or be staff."""
        if self.request.user.is_anonymous:
            return False

        publisher = get_object_or_404(Publisher, slug=self.kwargs["publisher_slug"])
        return (
            self.request.user.is_staff
            or publisher in self.request.user.publishers.all()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data()

        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        report = publisher.daily_reports(
            start_date=context["start_date"], end_date=context["end_date"]
        )

        context.update({"publisher": publisher, "report": report})

        return context


class AllPublisherReportView(BaseReportView):

    """A report for all publishers."""

    template_name = "adserver/reports/all-publishers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()

        # Get all publishers where an ad has a view or click in the specified date range
        impressions = AdImpression.objects.filter(date__gte=context["start_date"])
        if context["end_date"]:
            impressions = impressions.filter(date__lte=context["end_date"])
        if context["campaign_type"] and context["campaign_type"] in CAMPAIGN_TYPES:
            impressions = impressions.filter(
                advertisement__flight__campaign__campaign_type=context["campaign_type"]
            )
        publishers = Publisher.objects.filter(id__in=impressions.values("publisher"))

        publishers_and_reports = []
        for publisher in publishers:
            report = publisher.daily_reports(
                start_date=context["start_date"], end_date=context["end_date"]
            )
            if report["total"]["views"] > 0:
                publishers_and_reports.append((publisher, report))

        total_clicks = sum(
            report["total"]["clicks"] for _, report in publishers_and_reports
        )
        total_views = sum(
            report["total"]["views"] for _, report in publishers_and_reports
        )
        total_cost = sum(
            report["total"]["cost"] for _, report in publishers_and_reports
        )

        # Aggregate the different publisher reports by day
        days = {}
        for publisher, report in publishers_and_reports:
            for day in report["days"]:
                if day["date"] not in days:
                    days[day["date"]] = collections.defaultdict(int)
                    days[day["date"]]["views_by_publisher"] = {}
                    days[day["date"]]["clicks_by_publisher"] = {}

                days[day["date"]]["date"] = day["date"].strftime("%Y-%m-%d")
                days[day["date"]]["views"] += day["views"]
                days[day["date"]]["clicks"] += day["clicks"]
                days[day["date"]]["views_by_publisher"][publisher.name] = day["views"]
                days[day["date"]]["clicks_by_publisher"][publisher.name] = day["clicks"]
                days[day["date"]]["cost"] += float(day["cost"])
                days[day["date"]]["ctr"] = calculate_ctr(
                    days[day["date"]]["clicks"], days[day["date"]]["views"]
                )

        context.update(
            {
                "publishers": [p for p, _ in publishers_and_reports],
                "publishers_and_reports": publishers_and_reports,
                "total_clicks": total_clicks,
                "total_cost": total_cost,
                "total_views": total_views,
                "total_ctr": calculate_ctr(total_clicks, total_views),
                "total_ecpm": calculate_ecpm(total_cost, total_views),
                "campaign_types": CAMPAIGN_TYPES,
            }
        )

        return context
