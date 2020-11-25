"""Ad server views."""
import collections
import csv
import logging
import string
import urllib
from datetime import datetime
from datetime import timedelta

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import ugettext_lazy as _
from django.views import View
from django.views.generic import CreateView
from django.views.generic import DeleteView
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView
from django.views.generic import UpdateView
from django.views.generic.base import RedirectView
from django_countries import countries
from rest_framework.authtoken.models import Token
from user_agents import parse as parse_user_agent

from .constants import ALL_CAMPAIGN_TYPES
from .constants import CAMPAIGN_TYPES
from .constants import CLICKS
from .constants import VIEWS
from .forms import AdvertisementForm
from .forms import PublisherSettingsForm
from .mixins import AdvertiserAccessMixin
from .mixins import PublisherAccessMixin
from .models import AdImpression
from .models import AdType
from .models import Advertisement
from .models import Advertiser
from .models import Flight
from .models import GeoImpression
from .models import KeywordImpression
from .models import Offer
from .models import PlacementImpression
from .models import Publisher
from .models import PublisherPayout
from .models import UpliftImpression
from .reports import AdvertiserReport
from .reports import PublisherAdvertiserReport
from .reports import PublisherGeoReport
from .reports import PublisherKeywordReport
from .reports import PublisherPlacementReport
from .reports import PublisherReport
from .reports import PublisherUpliftReport
from .utils import analytics_event
from .utils import calculate_ctr
from .utils import calculate_ecpm
from .utils import generate_publisher_payout_data
from .utils import get_ad_day
from .utils import get_client_ip
from .utils import get_client_user_agent
from .utils import get_geolocation
from .utils import is_blocklisted_ip
from .utils import is_blocklisted_referrer
from .utils import is_blocklisted_user_agent
from .utils import is_click_ratelimited
from .utils import is_view_ratelimited


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
        publishers = list(request.user.publishers.all())
        advertisers = list(request.user.advertisers.all())

        if not publishers and len(advertisers) == 1:
            # This user has access to a single advertiser - redirect to it
            return redirect(reverse("advertiser_main", args=[advertisers[0].slug]))
        if not advertisers and len(publishers) == 1:
            # This user has access to a single publisher - redirect to it
            return redirect(reverse("publisher_main", args=[publishers[0].slug]))

    return render(
        request,
        "adserver/dashboard.html",
        {"advertisers": advertisers, "publishers": publishers},
    )


class AdvertiserMainView(AdvertiserAccessMixin, UserPassesTestMixin, RedirectView):

    """Should be (or redirect to) the main view for an advertiser that they see when first logging in."""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse("flight_list", kwargs=kwargs)


class FlightListView(AdvertiserAccessMixin, UserPassesTestMixin, ListView):

    """List view for advertiser flights."""

    model = Flight
    template_name = "adserver/advertiser/flight-list.html"

    def get_context_data(self, **kwargs):  # pylint: disable=arguments-differ
        context = super().get_context_data(**kwargs)

        context.update({"advertiser": self.advertiser, "flights": self.get_queryset()})

        return context

    def get_queryset(self):
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        return Flight.objects.filter(campaign__advertiser=self.advertiser).order_by(
            "-live", "-end_date", "name"
        )


class FlightDetailView(AdvertiserAccessMixin, UserPassesTestMixin, DetailView):

    """Detail view for flights."""

    model = Flight
    template_name = "adserver/advertiser/flight-detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        advertisement_list = self.object.advertisements.order_by("-live", "name")
        context.update(
            {"advertiser": self.advertiser, "advertisement_list": advertisement_list}
        )
        return context

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        return get_object_or_404(
            Flight,
            campaign__advertiser=self.advertiser,
            slug=self.kwargs["flight_slug"],
        )


class AdvertisementDetailView(AdvertiserAccessMixin, UserPassesTestMixin, DetailView):

    """Detail view for advertisements."""

    model = Advertisement
    template_name = "adserver/advertiser/advertisement-detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"advertiser": self.advertiser})
        return context

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        return get_object_or_404(
            Advertisement,
            flight__campaign__advertiser=self.advertiser,
            slug=self.kwargs["advertisement_slug"],
        )


class AdvertisementUpdateView(AdvertiserAccessMixin, UserPassesTestMixin, UpdateView):

    """Update view for advertisements."""

    form_class = AdvertisementForm
    model = Advertisement
    template_name = "adserver/advertiser/advertisement-update.html"

    def form_valid(self, form):
        result = super().form_valid(form)
        ad_name = form.cleaned_data["name"]
        messages.success(self.request, _("Successfully saved %(ad)s") % {"ad": ad_name})
        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"advertiser": self.advertiser})
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        ad = self.get_object()
        kwargs["flight"] = ad.flight
        return kwargs

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        return get_object_or_404(
            Advertisement,
            flight__campaign__advertiser=self.advertiser,
            slug=self.kwargs["advertisement_slug"],
        )

    def get_success_url(self):
        return reverse(
            "advertisement_detail",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.object.flight.slug,
                "advertisement_slug": self.object.slug,
            },
        )


class AdvertisementCreateView(AdvertiserAccessMixin, UserPassesTestMixin, CreateView):

    """Create view for advertisements."""

    form_class = AdvertisementForm
    model = Advertisement
    template_name = "adserver/advertiser/advertisement-create.html"

    def dispatch(self, request, *args, **kwargs):
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        self.flight = get_object_or_404(Flight, slug=self.kwargs["flight_slug"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        result = super().form_valid(form)
        ad_name = form.cleaned_data["name"]
        messages.success(self.request, _("Successfully saved %(ad)s") % {"ad": ad_name})
        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "advertiser": self.advertiser,
                "flight": self.flight,
                "ad_types": AdType.objects.exclude(deprecated=True).exclude(
                    description=""
                )[:5],
            }
        )
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["flight"] = get_object_or_404(Flight, slug=self.kwargs["flight_slug"])
        kwargs["initial"] = {
            "live": True,
            "ad_types": AdType.objects.filter(default_enabled=True),
        }
        return kwargs

    def get_success_url(self):
        return reverse(
            "advertisement_update",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.object.slug,
            },
        )


class BaseProxyView(View):

    """A base view for proxying ad views and clicks and collecting relevant metrics on clicks and views."""

    log_level = logging.DEBUG
    log_security_level = logging.WARNING
    impression_type = VIEWS
    success_message = "Billed impression"

    def ignore_tracking_reason(self, request, advertisement, offer):
        """Returns a reason this impression should not be tracked or `None` if this *should* be tracked."""
        reason = None

        ip_address = get_client_ip(request)
        user_agent = get_client_user_agent(request)
        parsed_ua = parse_user_agent(user_agent)
        referrer = request.META.get("HTTP_REFERER")

        country_code = None
        region_code = None
        metro_code = None
        geo_data = get_geolocation(ip_address)
        if geo_data:
            # One or more of these may be None which is OK
            # Ads targeting countries/regions/metros won't be counted
            country_code = geo_data["country_code"]
            region_code = geo_data["region"]
            metro_code = geo_data["dma_code"]

        if not offer:
            log.log(self.log_level, "Ad impression for unknown offer")
            reason = "Unknown offer"
        elif not advertisement.is_valid_offer(self.impression_type, offer):
            log.log(self.log_level, "Old or nonexistent impression nonce")
            reason = "Old/Invalid nonce"
        elif parsed_ua.is_bot:
            log.log(self.log_level, "Bot impression. User Agent: [%s]", user_agent)
            reason = "Bot impression"
        elif not settings.DEBUG and ip_address in settings.INTERNAL_IPS:
            # Ignore internal IPs except in DEBUG where all IPs are probably internal
            log.log(
                self.log_level, "Internal IP impression. User Agent: [%s]", user_agent
            )
            reason = "Internal IP"
        elif parsed_ua.os.family == "Other" and parsed_ua.browser.family == "Other":
            # This is probably a bot/proxy server/prefetcher/etc.
            log.log(self.log_level, "Unknown user agent impression [%s]", user_agent)
            reason = "Unrecognized user agent"
        elif not request.user.is_anonymous:
            log.log(self.log_level, "Ignored known user ad impression")
            reason = "Known user impression"
        elif is_blocklisted_user_agent(user_agent):
            log.log(self.log_level, "Blocked user agent impression [%s]", user_agent)
            reason = "Blocked UA impression"
        elif is_blocklisted_referrer(referrer):
            log.log(
                self.log_level,
                "Blocklisted referrer [%s], Publisher: [%s], UA: [%s]",
                referrer,
                offer.publisher,
                user_agent,
            )
            reason = "Blocked referrer impression"
        elif is_blocklisted_ip(ip_address):
            log.log(
                self.log_level,
                "Blocked IP impression, Publisher: [%s]",
                offer.publisher,
            )
            reason = "Blocked IP impression"
        elif not offer.publisher:
            log.log(self.log_level, "Ad impression for unknown publisher")
            reason = "Unknown publisher"
        elif not advertisement.flight.show_to_geo(
            country_code, region_code, metro_code
        ):
            # This is very rare but it is visible in ad reports
            # I believe the most common cause for this is somebody uses a VPN and is served an ad
            # Then they turn off their VPN and click on the ad
            log.log(
                self.log_security_level,
                "Invalid geo targeting for ad [%s]. Country: [%s], Region: [%s], Metro: [%s]",
                advertisement,
                country_code,
                region_code,
                metro_code,
            )
            reason = "Invalid targeting impression"
        elif self.impression_type == CLICKS and is_click_ratelimited(request):
            log.log(
                self.log_level,
                "User has clicked too many ads recently, Publisher: [%s], UA: [%s]",
                offer.publisher,
                user_agent,
            )
            reason = "Ratelimited click impression"
        elif self.impression_type == VIEWS and is_view_ratelimited(request):
            log.log(
                self.log_level,
                "User has viewed too many ads recently, Publisher: [%s], UA: [%s]",
                offer.publisher,
                user_agent,
            )
            reason = "Ratelimited view impression"

        return reason

    def send_to_analytics(self, request, advertisement, message):
        """A no-op by default, sublcasses may override it to send view/clicks to analytics."""

    def get(self, request, advertisement_id, nonce):
        """Handles proxying ad views and clicks and collecting metrics on them."""
        advertisement = get_object_or_404(Advertisement, pk=advertisement_id)
        try:
            offer = Offer.objects.get(id=nonce)
            publisher = offer.publisher
        except (ValidationError, Offer.DoesNotExist) as exception:
            log.debug("Invalid Offer. exception=%s", exception)
            offer = None
            publisher = None

        ignore_reason = self.ignore_tracking_reason(request, advertisement, offer)

        if not ignore_reason:
            log.log(self.log_level, self.success_message)
            advertisement.invalidate_nonce(self.impression_type, nonce)
            advertisement.track_impression(
                request,
                self.impression_type,
                publisher=publisher,
                offer=offer,
            )

        message = ignore_reason or self.success_message
        response = self.get_response(request, advertisement, publisher)

        self.send_to_analytics(request, advertisement, message)

        # Add the reason for accepting or rejecting the impression to the headers
        # but only for staff or in DEBUG/TESTING
        if settings.DEBUG or settings.TESTING or request.user.is_staff:
            response["X-Adserver-Reason"] = message

        return response

    def get_response(self, request, advertisement, publisher):
        """Subclasses *must* override this method."""
        raise NotImplementedError


class AdViewProxyView(BaseProxyView):

    """Track an ad view."""

    impression_type = VIEWS
    success_message = "Billed view"

    def get_response(self, request, advertisement, publisher):
        return HttpResponse(
            "<svg><!-- View Proxy --></svg>", content_type="image/svg+xml"
        )


class AdClickProxyView(BaseProxyView):

    """Track an ad click and redirect to the ad destination link."""

    impression_type = CLICKS
    success_message = "Billed click"

    def send_to_analytics(self, request, advertisement, message):
        ip_address = get_client_ip(request)
        user_agent = get_client_user_agent(request)

        event_category = "Advertisement"
        event_label = advertisement.slug
        event_action = message

        # The event_value is in US cents (eg. for $2 CPC, the value is 200)
        # CPMs are too small to register
        event_value = int(advertisement.flight.cpc * 100)

        analytics_event(
            ec=event_category,
            ea=event_action,
            el=event_label,
            ev=event_value,
            ua=user_agent,
            uip=ip_address,  # will be anonymized
        )

    def get_response(self, request, advertisement, publisher):
        # Allows using variables in links such as `?utm_source=${publisher}`
        template = string.Template(advertisement.link)

        publisher_slug = "unknown"
        if publisher:
            publisher_slug = publisher.slug

        url = template.safe_substitute(
            publisher=publisher_slug, advertisement=advertisement.slug
        )
        return HttpResponseRedirect(url)


class BaseReportView(UserPassesTestMixin, TemplateView):

    """
    A base report that other reports can extend.

    By default, it restricts access to staff and sets up date context variables.
    """

    DEFAULT_REPORT_DAYS = 30
    LIMIT = 20
    export = False
    export_filename = "readthedocs-report.csv"
    fieldnames = ["index", "views", "clicks", "cost", "ctr", "ecpm"]
    model = AdImpression
    report = PublisherReport

    def test_func(self):
        """By default, reports are locked down to staff."""
        return self.request.user.is_staff

    def render_to_response(self, context, **response_kwargs):
        """Handle exporting all reports to a CSV."""
        if self.export:
            report = context["report"]
            filename = self.export_filename
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

            writer = csv.DictWriter(
                response, fieldnames=self.fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(report.results)
            writer.writerow(report.total)

            return response

        return super().render_to_response(context, **response_kwargs)

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
            "limit": self.LIMIT,
        }

    def get_queryset(self, **kwargs):
        """Get the queryset (from ``model``) used to generate the report."""
        queryset = self.model.objects.all()

        if "start_date" in kwargs and kwargs["start_date"]:
            queryset = queryset.filter(date__gte=kwargs["start_date"])
        if "end_date" in kwargs and kwargs["end_date"]:
            queryset = queryset.filter(date__lte=kwargs["end_date"])

        # Advertiser filters
        if "advertiser" in kwargs and kwargs["advertiser"]:
            queryset = queryset.filter(
                advertisement__flight__campaign__advertiser=kwargs["advertiser"]
            )
        if "flight" in kwargs and kwargs["flight"]:
            queryset = queryset.filter(advertisement__flight=kwargs["flight"])

        # Publisher filters
        if "publisher" in kwargs and kwargs["publisher"]:
            queryset = queryset.filter(publisher=kwargs["publisher"])
        if "campaign_type" in kwargs and kwargs["campaign_type"] in ALL_CAMPAIGN_TYPES:
            queryset = queryset.filter(
                advertisement__flight__campaign__campaign_type=kwargs["campaign_type"]
            )

        return queryset

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


class AdvertiserReportView(AdvertiserAccessMixin, BaseReportView):

    """A report for one advertiser."""

    template_name = "adserver/reports/advertiser.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        start_date = context["start_date"]
        end_date = context["end_date"]

        advertiser_slug = kwargs.get("advertiser_slug", "")

        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)

        queryset = self.get_queryset(
            advertiser=advertiser,
            start_date=start_date,
            end_date=end_date,
        )
        report = AdvertiserReport(queryset)
        report.generate()

        flights = (
            Flight.objects.filter(campaign__advertiser=advertiser)
            .order_by("-live", "-end_date", "name")
            .select_related("campaign")
        )

        context.update(
            {
                "advertiser": advertiser,
                "report": report,
                "flights": flights,
                "export_url": "{url}?{params}".format(
                    url=reverse("advertiser_report_export", args=[advertiser.slug]),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                        }
                    ),
                ),
            }
        )

        return context


class AdvertiserFlightReportView(AdvertiserAccessMixin, BaseReportView):

    """A report for one flight for an advertiser."""

    template_name = "adserver/reports/advertiser-flight.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        start_date = context["start_date"]
        end_date = context["end_date"]

        advertiser_slug = kwargs.get("advertiser_slug", "")
        flight_slug = kwargs.get("flight_slug", "")

        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)
        flight = get_object_or_404(
            Flight, slug=flight_slug, campaign__advertiser=advertiser
        )

        queryset = self.get_queryset(
            advertiser=advertiser,
            flight=flight,
            start_date=start_date,
            end_date=end_date,
        )

        report = AdvertiserReport(queryset)
        report.generate()

        # Get the breakdown of performance per ad
        advertisements = []
        for ad in flight.advertisements.prefetch_related("ad_types"):
            ad_queryset = queryset.filter(advertisement=ad)
            ad_report = AdvertiserReport(ad_queryset)
            ad_report.generate()
            ad.report = ad_report
            if ad_report.total["views"]:
                advertisements.append(ad)

        context.update(
            {
                "advertiser": advertiser,
                "flight": flight,
                "report": report,
                "advertisements": advertisements,
                "export_url": "{url}?{params}".format(
                    url=reverse(
                        "flight_report_export", args=[advertiser.slug, flight.slug]
                    ),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                        }
                    ),
                ),
            }
        )

        return context


class AllAdvertiserReportView(BaseReportView):

    """A report aggregating all advertisers."""

    template_name = "adserver/reports/all-advertisers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        start_date = context["start_date"]
        end_date = context["end_date"]

        # Get all advertisers where an ad for that advertiser has a view or click
        # in the specified date range
        impressions = self.get_queryset(
            start_date=context["start_date"],
            end_date=context["end_date"],
        )
        advertisers = Advertiser.objects.filter(
            id__in=Advertisement.objects.filter(
                id__in=impressions.values("advertisement")
            ).values("flight__campaign__advertiser")
        )

        advertisers_and_reports = []
        for advertiser in advertisers:
            queryset = self.get_queryset(
                advertiser=advertiser,
                start_date=start_date,
                end_date=end_date,
            )
            report = AdvertiserReport(queryset)
            report.generate()

            if report.total["views"] > 0:
                advertisers_and_reports.append((advertiser, report))

        total_clicks = sum(
            report.total["clicks"] for _, report in advertisers_and_reports
        )
        total_views = sum(
            report.total["views"] for _, report in advertisers_and_reports
        )
        total_cost = sum(report.total["cost"] for _, report in advertisers_and_reports)

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


class PublisherReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher."""

    template_name = "adserver/reports/publisher.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        queryset = self.get_queryset(
            publisher=publisher,
            campaign_type=context["campaign_type"],
            start_date=context["start_date"],
            end_date=context["end_date"],
        )

        report = PublisherReport(queryset)
        report.generate()

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "export_url": "{url}?{params}".format(
                    url=reverse("publisher_report_export", args=[publisher.slug]),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                            "campaign_type": context["campaign_type"] or "",
                        }
                    ),
                ),
            }
        )

        return context


class PublisherPlacementReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher broken down by placement (Div/ad type)."""

    model = PlacementImpression
    template_name = "adserver/reports/publisher_placement.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        div_id = self.request.GET.get("div_id", "")
        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        queryset = self.get_queryset(
            publisher=publisher,
            campaign_type=context["campaign_type"],
            start_date=context["start_date"],
            end_date=context["end_date"],
            div_id=div_id,
        )

        report = PublisherPlacementReport(
            queryset,
            # Index by date if filtering report to a single placement
            index="date" if div_id else None,
            order="-date" if div_id else None,
            max_results=None if div_id else self.LIMIT,
        )
        report.generate()

        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        div_id_options = (
            self.get_queryset(
                publisher=publisher,
                start_date=context["start_date"],
                end_date=context["end_date"],
            )
            .values_list("div_id", flat=True)
            .annotate(total_views=Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "div_id": div_id,
                "div_id_options": div_id_options,
                "export_url": "{url}?{params}".format(
                    url=reverse(
                        "publisher_placement_report_export", args=[publisher.slug]
                    ),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                            "campaign_type": context["campaign_type"] or "",
                            "div_id": div_id or "",
                        }
                    ),
                ),
            }
        )

        return context

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "div_id" in kwargs and kwargs["div_id"]:
            queryset = queryset.filter(div_id=kwargs["div_id"])

        return queryset


class PublisherGeoReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher."""

    model = GeoImpression
    template_name = "adserver/reports/publisher_geo.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        country = self.request.GET.get("country", "")
        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        queryset = self.get_queryset(
            publisher=publisher,
            campaign_type=context["campaign_type"],
            start_date=context["start_date"],
            end_date=context["end_date"],
            country=country,
        )

        report = PublisherGeoReport(
            queryset,
            # Index by date if filtering report to a single country
            index="date" if country else None,
            order="-date" if country else None,
            max_results=None if country else self.LIMIT,
        )
        report.generate()

        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        country_list = (
            self.get_queryset(
                publisher=publisher,
                start_date=context["start_date"],
                end_date=context["end_date"],
            )
            .values_list("country", flat=True)
            .annotate(total_views=Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        countries_dict = dict(countries)
        country_options = (
            (cc, countries_dict.get(cc, "Unknown")) for cc in country_list
        )

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "country": country,
                "country_options": country_options,
                "country_name": countries_dict.get(country),
                "export_url": "{url}?{params}".format(
                    url=reverse("publisher_geo_report_export", args=[publisher.slug]),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                            "campaign_type": context["campaign_type"] or "",
                            "country": country or "",
                        }
                    ),
                ),
            }
        )

        return context

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "country" in kwargs and kwargs["country"]:
            queryset = queryset.filter(country=kwargs["country"])

        return queryset


class PublisherAdvertiserReportView(PublisherAccessMixin, BaseReportView):

    """Show top advertisers for a publisher."""

    template_name = "adserver/reports/publisher_advertiser.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # This needs to be something other than `advertiser`
        # to not conflict with template context on advertising reports.
        report_advertiser = self.request.GET.get("report_advertiser", "")

        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        queryset = self.get_queryset(
            publisher=publisher,
            advertiser=Advertiser.objects.filter(slug=report_advertiser).first(),
            campaign_type=context["campaign_type"],
            start_date=context["start_date"],
            end_date=context["end_date"],
        ).filter(advertisement__isnull=False)

        report = PublisherAdvertiserReport(
            queryset,
            # Index by date if filtering report to a single country
            index="date" if report_advertiser else None,
            order="-date" if report_advertiser else None,
            max_results=None if report_advertiser else self.LIMIT,
        )
        report.generate()

        # Get the list of advertisers for the filter dropdown
        advertiser_list = (
            self.get_queryset(
                publisher=publisher,
                start_date=context["start_date"],
                end_date=context["end_date"],
            )
            .filter(advertisement__isnull=False)
            .values_list("advertisement__flight__campaign__advertiser")
            .annotate(total_views=Sum("views"))
            .order_by("-total_views")
            .values_list(
                "advertisement__flight__campaign__advertiser__slug",
                "advertisement__flight__campaign__advertiser__name",
            )
            .distinct()[: self.LIMIT]
        )

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "advertiser_list": advertiser_list,
                "report_advertiser": report_advertiser,
                "limit": self.LIMIT,
                "export_url": "{url}?{params}".format(
                    url=reverse(
                        "publisher_advertiser_report_export", args=[publisher.slug]
                    ),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                            "campaign_type": context["campaign_type"] or "",
                            "report_advertiser": report_advertiser,
                        }
                    ),
                ),
            }
        )

        # Remove report_advertiser if there's invalid data passed in
        if report_advertiser not in (slug for slug, name in advertiser_list):
            context["report_advertiser"] = None

        if report_advertiser:
            advertiser_name = Advertiser.objects.get(slug=report_advertiser).name
            context["advertiser_name"] = advertiser_name

        return context


class PublisherKeywordReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher."""

    model = KeywordImpression
    template_name = "adserver/reports/publisher_keyword.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        keyword = self.request.GET.get("keyword", "")
        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        queryset = self.get_queryset(
            publisher=publisher,
            keyword=keyword,
            campaign_type=context["campaign_type"],
            start_date=context["start_date"],
            end_date=context["end_date"],
        )

        report = PublisherKeywordReport(
            queryset,
            # Index by date if filtering report to a single country
            index="date" if keyword else None,
            order="-date" if keyword else None,
            max_results=None if keyword else self.LIMIT,
        )
        report.generate()

        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        keyword_list = (
            self.get_queryset(
                publisher=publisher,
                start_date=context["start_date"],
                end_date=context["end_date"],
            )
            .values_list("keyword", flat=True)
            .annotate(total_views=Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "keyword": keyword,
                "keyword_list": keyword_list,
                "export_url": "{url}?{params}".format(
                    url=reverse(
                        "publisher_keyword_report_export", args=[publisher.slug]
                    ),
                    params=urllib.parse.urlencode(
                        {
                            "start_date": context["start_date"].date(),
                            "end_date": context["end_date"].date()
                            if context["end_date"]
                            else "",
                            "campaign_type": context["campaign_type"] or "",
                            "keyword": keyword,
                        }
                    ),
                ),
            }
        )

        return context

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "keyword" in kwargs and kwargs["keyword"]:
            queryset = queryset.filter(keyword=kwargs["keyword"])

        return queryset


class PublisherEmbedView(PublisherAccessMixin, UserPassesTestMixin, TemplateView):

    """Advertising embed code for a publisher."""

    template_name = "adserver/publisher/embed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(
            Publisher, slug=publisher_slug, unauthed_ad_decisions=True
        )

        context.update({"publisher": publisher})

        return context


class PublisherSettingsView(PublisherAccessMixin, UserPassesTestMixin, UpdateView):

    """Settings configuration for a publisher."""

    form_class = PublisherSettingsForm
    model = Publisher
    template_name = "adserver/publisher/settings.html"

    def form_valid(self, form):
        result = super().form_valid(form)
        messages.success(
            self.request,
            _("Successfully saved %(publisher)s settings")
            % {"publisher": self.object.name},
        )
        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"publisher": self.object})
        return context

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        return get_object_or_404(Publisher, slug=self.kwargs["publisher_slug"])

    def get_success_url(self):
        return reverse(
            "publisher_settings", kwargs={"publisher_slug": self.object.slug}
        )


class PublisherStripeOauthConnectView(
    PublisherAccessMixin, UserPassesTestMixin, RedirectView
):

    """Redirect the user to the correct Stripe connect URL for the publisher."""

    model = Publisher
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if not settings.STRIPE_CONNECT_CLIENT_ID:
            messages.error(self.request, _("Stripe is not configured"))
            return reverse("dashboard-home")

        publisher = self.get_object()

        # Save a state nonce to verify that the Stripe oauth flow can't be replayed or forged
        stripe_state = get_random_string(30)
        self.request.session["stripe_state"] = stripe_state
        self.request.session["stripe_connect_publisher"] = publisher.slug

        params = {
            "client_id": settings.STRIPE_CONNECT_CLIENT_ID,
            "suggested_capabilities[]": "transfers",
            "stripe_user[email]": self.request.user.email,
            "state": stripe_state,
            "redirect_uri": self.request.build_absolute_uri(
                reverse("publisher_stripe_oauth_return")
            ),
        }
        return f"https://connect.stripe.com/express/oauth/authorize?{urllib.parse.urlencode(params)}"

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        return get_object_or_404(Publisher, slug=self.kwargs["publisher_slug"])


@login_required
def publisher_stripe_oauth_return(request):
    """Handle the oauth return flow from Stripe - save the account on the publisher."""
    # A stripe token we passed when setup started - needs to be double checked
    state = request.GET.get("state", "")
    oauth_code = request.GET.get("code", "")

    if request.user.is_staff:
        publishers = Publisher.objects.all()
    else:
        publishers = request.user.publishers.all()

    publisher = publishers.filter(
        slug=request.session.get("stripe_connect_publisher", "")
    ).first()

    if state == request.session.get("stripe_state") and publisher:
        response = None
        log.debug(
            "Using stripe auth code to connect publisher account. Publisher = [%s]",
            publisher,
        )
        try:
            response = stripe.OAuth.token(
                grant_type="authorization_code", code=oauth_code
            )
        except stripe.oauth_error.OAuthError:
            log.error("Invalid Stripe authorization code: %s", oauth_code)
        except Exception:
            log.error("An unknown Stripe error occurred.")

        if response:
            connected_account_id = response["stripe_user_id"]
            publisher.stripe_connected_account_id = connected_account_id
            publisher.save()
            messages.success(request, _("Successfully connected your Stripe account"))

            # Delete saved stripe state
            del request.session["stripe_state"]
            del request.session["stripe_connect_publisher"]

            return redirect(reverse("publisher_main", args=[publisher.slug]))
    else:
        log.warning(
            "Stripe state or publisher do not check out. State = [%s], Publisher = [%s]",
            state,
            publisher,
        )

    messages.error(request, _("There was a problem connecting your Stripe account"))
    log.error("There was a problem connecting a Stripe account.")
    return redirect(reverse("dashboard-home"))


class PublisherPayoutListView(PublisherAccessMixin, UserPassesTestMixin, ListView):

    """List of publisher payouts."""

    model = PublisherPayout
    template_name = "adserver/publisher/payout-list.html"

    def get_context_data(self, **kwargs):  # pylint: disable=arguments-differ
        """Get the past payouts, along with the current balance and future balance."""
        context = super().get_context_data(**kwargs)

        payouts = self.get_queryset()
        data = generate_publisher_payout_data(self.publisher)

        total_balance = (
            float(self.publisher.total_payout_sum())
            + data["current_report"]["total"]["revenue_share"]
        )

        if data.get("due_report"):
            total_balance += data["due_report"]["total"]["revenue_share"]

        context.update(data)
        context.update(
            {
                "publisher": self.publisher,
                "payouts": payouts,
                "total_balance": total_balance,
            }
        )

        return context

    def get_queryset(self):
        self.publisher = get_object_or_404(
            Publisher, slug=self.kwargs["publisher_slug"]
        )
        return self.publisher.payouts.order_by("-date")


class PublisherPayoutDetailView(PublisherAccessMixin, UserPassesTestMixin, DetailView):

    """Details of a specific publisher payout."""

    template_name = "adserver/publisher/payout.html"

    def get_object(self, queryset=None):
        self.publisher = get_object_or_404(
            Publisher, slug=self.kwargs["publisher_slug"]
        )
        return get_object_or_404(
            PublisherPayout, publisher=self.publisher, pk=self.kwargs["pk"]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"publisher": self.publisher, "payout": self.get_object()})

        return context


class AllPublisherReportView(BaseReportView):

    """A report for all publishers."""

    force_revshare = None
    template_name = "adserver/reports/all-publishers.html"

    def get_context_data(self, **kwargs):  # pylint: disable=too-many-locals
        context = super().get_context_data(**kwargs)
        sort = self.request.GET.get("sort", "")
        force_revshare = self.request.GET.get("force_revshare", self.force_revshare)

        # Get all publishers where an ad has a view or click in the specified date range
        impressions = self.get_queryset(
            start_date=context["start_date"],
            end_date=context["end_date"],
        )
        publishers = Publisher.objects.filter(id__in=impressions.values("publisher"))

        revenue_share_percentage = self.request.GET.get("revenue_share_percentage", "")
        if revenue_share_percentage:
            try:
                publishers = publishers.filter(
                    revenue_share_percentage=float(revenue_share_percentage)
                )
            except ValueError:
                pass

        publishers_and_reports = []
        for publisher in publishers:
            queryset = self.get_queryset(
                publisher=publisher,
                start_date=context["start_date"],
                end_date=context["end_date"],
                campaign_type=context["campaign_type"],
            )
            report = self.report(queryset, force_revshare=force_revshare)
            report.generate()
            if report.total["views"] > 0:
                publishers_and_reports.append((publisher, report))

        # Sort reports by revenue
        sort_options = report.total.keys()
        if sort and sort in sort_options:
            publishers_and_reports = sorted(
                publishers_and_reports,
                key=lambda obj: obj[1].total[sort],
                reverse=True,
            )

        total_clicks = sum(
            report.total["clicks"] for _, report in publishers_and_reports
        )
        total_views = sum(report.total["views"] for _, report in publishers_and_reports)
        total_revenue = sum(
            report.total["revenue"] for _, report in publishers_and_reports
        )
        our_total_revenue = total_revenue - sum(
            report.total["revenue_share"] for _, report in publishers_and_reports
        )

        # Aggregate the different publisher reports by day
        days = {}
        for publisher, report in publishers_and_reports:
            for day in report.results:
                if day["date"] not in days:
                    days[day["date"]] = collections.defaultdict(int)
                    days[day["date"]]["views_by_publisher"] = {}
                    days[day["date"]]["clicks_by_publisher"] = {}

                days[day["date"]]["index"] = day["index"]
                days[day["date"]]["date"] = day["date"]
                days[day["date"]]["views"] += day["views"]
                days[day["date"]]["clicks"] += day["clicks"]
                days[day["date"]]["views_by_publisher"][publisher.name] = day["views"]
                days[day["date"]]["clicks_by_publisher"][publisher.name] = day["clicks"]
                days[day["date"]]["revenue"] += float(day["revenue"])
                days[day["date"]]["our_revenue"] += float(day["our_revenue"])
                days[day["date"]]["ctr"] = calculate_ctr(
                    days[day["date"]]["clicks"], days[day["date"]]["views"]
                )
                days[day["date"]]["ecpm"] = calculate_ecpm(
                    days[day["date"]]["revenue"], days[day["date"]]["views"]
                )

        # Ensure the aggregated total is sorted
        days = sorted(
            days.values(),
            key=lambda obj: obj["date"],
            reverse=True,
        )

        context.update(
            {
                "publishers": [p for p, _ in publishers_and_reports],
                "publishers_and_reports": publishers_and_reports,
                "total_clicks": total_clicks,
                "total_revenue": total_revenue,
                "our_total_revenue": our_total_revenue,
                "days": days,
                "total_views": total_views,
                "total_ctr": calculate_ctr(total_clicks, total_views),
                "total_ecpm": calculate_ecpm(total_revenue, total_views),
                "campaign_types": CAMPAIGN_TYPES,
                # Make these strings to easily compare with GET args
                "revshare_options": set(
                    str(pub.revenue_share_percentage) for pub in Publisher.objects.all()
                ),
                "revenue_share_percentage": revenue_share_percentage,
                "sort": sort,
                "sort_options": sort_options,
            }
        )

        return context


class UpliftReportView(AllPublisherReportView):

    """An uplift report for all publishers."""

    model = UpliftImpression
    force_revshare = 70.0
    report = PublisherUpliftReport
    template_name = "adserver/reports/all-publishers_uplift.html"


class PublisherMainView(PublisherAccessMixin, UserPassesTestMixin, RedirectView):

    """Should be (or redirect to) the main view for a publisher that they see when first logging in."""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse("publisher_report", kwargs=kwargs)


class ApiTokenMixin(LoginRequiredMixin):

    """User token to access the ad server API."""

    model = Token
    lookup_url_kwarg = "token_pk"
    template_name = "adserver/accounts/api-token.html"
    success_url = reverse_lazy("api_token_list")

    def get_queryset(self):
        # NOTE: we are currently showing just one token since the DRF model has
        # a OneToOneField relation with User.
        return Token.objects.filter(user__in=[self.request.user])


class ApiTokenListView(ApiTokenMixin, ListView):
    pass


class ApiTokenCreateView(ApiTokenMixin, CreateView):

    """View to generate a Token object for the logged in User."""

    http_method_names = ["post"]
    object = None

    def post(self, request, *args, **kwargs):
        token, created = Token.objects.get_or_create(user=self.request.user)
        self.object = token
        if created:
            messages.success(request, _("API token created successfully"))
        return HttpResponseRedirect(self.get_success_url())


class ApiTokenDeleteView(ApiTokenMixin, DeleteView):

    """View to delete/revoke the current Token of the logged in User."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        result = super().post(request, *args, **kwargs)
        messages.info(request, _("API token revoked"))
        return result

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        token = Token.objects.filter(user=self.request.user).first()
        if not token:
            raise Http404
        return token
