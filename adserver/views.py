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
from rest_framework.authtoken.models import Token
from user_agents import parse as parse_user_agent

from .constants import CAMPAIGN_TYPES
from .constants import CLICKS
from .constants import VIEWS
from .forms import AdvertisementForm
from .forms import PublisherSettingsForm
from .mixins import AdvertiserAccessMixin
from .mixins import GeoReportMixin
from .mixins import PublisherAccessMixin
from .mixins import ReportQuerysetMixin
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
from .reports import AdvertiserGeoReport
from .reports import AdvertiserPublisherReport
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


class AdvertiserMainView(
    AdvertiserAccessMixin, UserPassesTestMixin, ReportQuerysetMixin, DetailView
):

    """Should be (or redirect to) the main view for an advertiser that they see when first logging in."""

    advertiser = None
    impression_model = AdImpression
    model = Advertiser
    template_name = "adserver/advertiser/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get the beginning of the month so we can show month-to-date stats
        start_date = timezone.now().replace(day=1, hour=0, minute=0, second=0)

        queryset = self.get_queryset(
            advertiser=self.advertiser,
            start_date=start_date,
        )
        report = AdvertiserReport(queryset)
        report.generate()

        flights = (
            Flight.objects.filter(campaign__advertiser=self.advertiser)
            .filter(live=True)
            .order_by("-live", "-end_date", "name")
        )

        context.update(
            {
                "advertiser": self.advertiser,
                "report": report,
                "flights": flights,
                "start_date": start_date,
            }
        )
        return context

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        return self.advertiser


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


class AdvertisementCopyView(AdvertiserAccessMixin, UserPassesTestMixin, TemplateView):

    """Create a copy of an existing ad."""

    template_name = "adserver/advertiser/advertisement-copy.html"

    def dispatch(self, request, *args, **kwargs):
        self.advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs["advertiser_slug"]
        )
        self.flight = get_object_or_404(
            Flight,
            slug=self.kwargs["flight_slug"],
            campaign__advertiser=self.advertiser,
        )
        self.source_advertisement = source_ad_id = None

        if (
            "source_advertisement" in request.GET
            and request.GET["source_advertisement"].isdigit()
        ):
            source_ad_id = request.GET["source_advertisement"]
        elif (
            "source_advertisement" in request.POST
            and request.POST["source_advertisement"].isdigit()
        ):
            source_ad_id = request.POST["source_advertisement"]

        if source_ad_id:
            self.source_advertisement = (
                Advertisement.objects.filter(
                    flight__campaign__advertiser=self.advertiser
                )
                .filter(pk=source_ad_id)
                .first()
            )
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.flight and self.source_advertisement:
            new_ad = self.copy_instance()
            messages.success(
                self.request,
                _("Successfully created %(ad)s from a copy.") % {"ad": new_ad},
            )
            return redirect(
                reverse(
                    "advertisement_update",
                    kwargs={
                        "advertiser_slug": self.advertiser.slug,
                        "flight_slug": self.flight.slug,
                        "advertisement_slug": new_ad.slug,
                    },
                )
            )

        # This should basically never be taken
        return redirect(
            reverse(
                "flight_detail",
                kwargs={
                    "advertiser_slug": self.advertiser.slug,
                    "flight_slug": self.flight.slug,
                },
            )
        )

    def copy_instance(self):
        instance = self.source_advertisement.__copy__()
        instance.flight = self.flight
        instance.save()  # Automatically gets a new slug
        return instance

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "advertiser": self.advertiser,
                "flight": self.flight,
                "advertisements": Advertisement.objects.filter(
                    flight__campaign__advertiser=self.advertiser
                ).select_related(),
                "source_advertisement": self.source_advertisement,
            }
        )
        return context


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

        # Append a query string param ?ea-publisher=${publisher}
        url_parts = list(urllib.parse.urlparse(url))
        query_params = dict(urllib.parse.parse_qsl(url_parts[4]))
        query_params.update({"ea-publisher": publisher_slug})
        url_parts[4] = urllib.parse.urlencode(query_params)
        url = urllib.parse.urlunparse(url_parts)

        return HttpResponseRedirect(url)


class BaseReportView(UserPassesTestMixin, ReportQuerysetMixin, TemplateView):

    """
    A base report that other reports can extend.

    By default, it restricts access to staff and sets up date context variables.
    """

    DEFAULT_REPORT_DAYS = 30
    LIMIT = 20
    SESSION_KEY_START_DATE = "report_start_date"
    SESSION_KEY_END_DATE = "report_end_date"
    export = False
    export_filename = "readthedocs-report.csv"
    export_view = None
    fieldnames = ["index", "views", "clicks", "cost", "ctr", "ecpm"]
    impression_model = AdImpression
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

    def get_export_url(self, **kwargs):
        if not self.export_view:
            return None

        return "{url}?{params}".format(
            url=reverse(self.export_view, kwargs=kwargs),
            params=urllib.parse.urlencode(self.request.GET),
        )

    def _parse_date_string(self, date_str):
        try:
            return timezone.make_aware(datetime.strptime(date_str, "%Y-%m-%d"))
        except ValueError:
            # Since this can come from GET params, handle errors
            pass

        return None

    def get_start_date(self):
        start_date = None
        if "start_date" in self.request.GET:
            start_date = self._parse_date_string(self.request.GET["start_date"])
        if not start_date and self.SESSION_KEY_START_DATE in self.request.session:
            start_date = self._parse_date_string(
                self.request.session[self.SESSION_KEY_START_DATE]
            )

        if not start_date:
            start_date = get_ad_day() - timedelta(days=self.DEFAULT_REPORT_DAYS)

        # Store date in the session
        self.request.session[self.SESSION_KEY_START_DATE] = start_date.strftime(
            "%Y-%m-%d"
        )

        return start_date

    def get_end_date(self):
        end_date = None
        if "end_date" in self.request.GET:
            end_date = self._parse_date_string(self.request.GET["end_date"])
        if not end_date and self.SESSION_KEY_END_DATE in self.request.session:
            end_date = self._parse_date_string(
                self.request.session[self.SESSION_KEY_END_DATE]
            )

        if end_date:
            # Store date in the session
            self.request.session[self.SESSION_KEY_END_DATE] = end_date.strftime(
                "%Y-%m-%d"
            )

        return end_date


class AdvertiserReportView(AdvertiserAccessMixin, BaseReportView):

    """A report for one advertiser."""

    export_view = "advertiser_report_export"
    template_name = "adserver/reports/advertiser.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        advertiser_slug = kwargs.get("advertiser_slug", "")

        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)

        queryset = self.get_queryset(
            advertiser=advertiser,
            start_date=context["start_date"],
            end_date=context["end_date"],
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
                "export_url": self.get_export_url(advertiser_slug=advertiser.slug),
            }
        )

        return context


class AdvertiserFlightReportView(AdvertiserAccessMixin, BaseReportView):

    """A report for one flight for an advertiser."""

    export_view = "flight_report_export"
    template_name = "adserver/reports/advertiser-flight.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        advertiser_slug = kwargs.get("advertiser_slug", "")
        flight_slug = kwargs.get("flight_slug", "")

        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)
        flight = get_object_or_404(
            Flight, slug=flight_slug, campaign__advertiser=advertiser
        )

        queryset = self.get_queryset(
            advertiser=advertiser,
            flight=flight,
            start_date=context["start_date"],
            end_date=context["end_date"],
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
                "export_url": self.get_export_url(
                    advertiser_slug=advertiser.slug, flight_slug=flight.slug
                ),
            }
        )

        return context


class AdvertiserGeoReportView(AdvertiserAccessMixin, GeoReportMixin, BaseReportView):

    """A report for an advertiser broken down by geo."""

    export_view = "advertiser_geo_report_export"
    impression_model = GeoImpression
    template_name = "adserver/reports/advertiser-geo.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        country = self.request.GET.get("country", "")

        advertiser_slug = kwargs.get("advertiser_slug", "")
        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)

        flight_slug = self.request.GET.get("flight", "")
        flight = Flight.objects.filter(
            campaign__advertiser=advertiser, slug=flight_slug
        ).first()

        queryset = self.get_queryset(
            advertiser=advertiser,
            start_date=context["start_date"],
            end_date=context["end_date"],
            country=country,
            flight=flight,
        )

        report = AdvertiserGeoReport(
            queryset,
            # Index by date if filtering report to a single country
            index="date" if country else None,
            order="-date" if country else None,
            max_results=None if country else self.LIMIT,
        )
        report.generate()

        country_options = self.get_country_options(
            # Don't pass the country so we get all countries
            self.get_queryset(
                advertiser=advertiser,
                start_date=context["start_date"],
                end_date=context["end_date"],
            )
        )

        context.update(
            {
                "advertiser": advertiser,
                "report": report,
                "country": country,
                "country_options": country_options,
                "country_name": self.get_country_name(country),
                "flights": Flight.objects.filter(
                    campaign__advertiser=advertiser
                ).order_by("-start_date"),
                "export_url": self.get_export_url(advertiser_slug=advertiser.slug),
            }
        )

        return context


class AdvertiserPublisherReportView(AdvertiserAccessMixin, BaseReportView):

    """A report for an advertiser broken down by publishers where the advertisers ads are shown."""

    export_view = "advertiser_publisher_report_export"
    template_name = "adserver/reports/advertiser-publisher.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        advertiser_slug = kwargs.get("advertiser_slug", "")
        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)
        report_publisher = Publisher.objects.filter(
            slug=self.request.GET.get("publisher", "")
        ).first()

        flight_slug = self.request.GET.get("flight", "")
        flight = Flight.objects.filter(
            campaign__advertiser=advertiser, slug=flight_slug
        ).first()

        queryset = self.get_queryset(
            advertiser=advertiser,
            publisher=report_publisher,
            flight=flight,
            start_date=context["start_date"],
            end_date=context["end_date"],
        )

        report = AdvertiserPublisherReport(
            queryset,
            # Index by date if filtering report to a single publisher
            index="date" if report_publisher else None,
            order="-date" if report_publisher else None,
            max_results=None if report_publisher else self.LIMIT,
        )
        report.generate()

        # Get the list of publishers for the filter dropdown
        publisher_list = (
            self.get_queryset(
                advertiser=advertiser,
                start_date=context["start_date"],
                end_date=context["end_date"],
            )
            .values_list("publisher")
            .annotate(total_views=Sum("views"))
            .order_by("-total_views")
            .values_list(
                "publisher__slug",
                "publisher__name",
            )
            .distinct()[: self.LIMIT]
        )

        context.update(
            {
                "advertiser": advertiser,
                "report": report,
                "report_publisher": report_publisher,
                "publisher_list": publisher_list,
                "flights": Flight.objects.filter(
                    campaign__advertiser=advertiser
                ).order_by("-start_date"),
                "export_url": self.get_export_url(advertiser_slug=advertiser.slug),
            }
        )

        return context


class AllAdvertiserReportView(BaseReportView):

    """A report aggregating all advertisers."""

    template_name = "adserver/reports/all-advertisers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

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
                start_date=context["start_date"],
                end_date=context["end_date"],
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

    export_view = "publisher_report_export"
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
                "export_url": self.get_export_url(publisher_slug=publisher.slug),
            }
        )

        return context


class PublisherPlacementReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher broken down by placement (Div/ad type)."""

    export_view = "publisher_placement_report_export"
    impression_model = PlacementImpression
    template_name = "adserver/reports/publisher-placement.html"
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
                "export_url": self.get_export_url(publisher_slug=publisher.slug),
            }
        )

        return context

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "div_id" in kwargs and kwargs["div_id"]:
            queryset = queryset.filter(div_id=kwargs["div_id"])

        return queryset


class PublisherGeoReportView(PublisherAccessMixin, GeoReportMixin, BaseReportView):

    """A report for a single publisher."""

    export_view = "publisher_geo_report_export"
    impression_model = GeoImpression
    template_name = "adserver/reports/publisher-geo.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        country = self.request.GET.get("country", "")
        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        country_options = list(
            self.get_country_options(
                # Don't pass the country so we get all countries
                self.get_queryset(
                    publisher=publisher,
                    campaign_type=context["campaign_type"],
                    start_date=context["start_date"],
                    end_date=context["end_date"],
                )
            )
        )

        queryset = self.get_queryset(
            publisher=publisher,
            campaign_type=context["campaign_type"],
            start_date=context["start_date"],
            end_date=context["end_date"],
            country=country,
            # Don't iterate over countries that aren't in the output
            countries=set(indx[0] for indx in country_options),
        )

        report = PublisherGeoReport(
            queryset,
            # Index by date if filtering report to a single country
            index="date" if country else None,
            order="-date" if country else None,
            max_results=None if country else self.LIMIT,
        )
        report.generate()

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "country": country,
                "country_options": country_options,
                "country_name": self.get_country_name(country),
                "export_url": self.get_export_url(publisher_slug=publisher.slug),
            }
        )

        return context


class PublisherAdvertiserReportView(PublisherAccessMixin, BaseReportView):

    """Show top advertisers for a publisher."""

    export_view = "publisher_advertiser_report_export"
    template_name = "adserver/reports/publisher-advertiser.html"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # This needs to be something other than `advertiser`
        # to not conflict with template context on advertising reports.
        report_advertiser = Advertiser.objects.filter(
            slug=self.request.GET.get("advertiser", "")
        ).first()

        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        queryset = self.get_queryset(
            publisher=publisher,
            advertiser=report_advertiser,
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
                "export_url": self.get_export_url(publisher_slug=publisher.slug),
            }
        )

        return context


class PublisherKeywordReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher."""

    export_view = "publisher_keyword_report_export"
    impression_model = KeywordImpression
    template_name = "adserver/reports/publisher-keyword.html"
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
                "export_url": self.get_export_url(publisher_slug=publisher.slug),
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
            # "suggested_capabilities[]": "transfers",
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
        report = None
        sort_options = None
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
        if publishers_and_reports and report:
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


class UpliftReportView(BaseReportView):

    """An uplift report for all publishers."""

    export_view = "publisher_uplift_report_export"
    fieldnames = ["index", "views", "clicks", "ctr", "ecpm", "revenue", "our_revenue"]
    impression_model = UpliftImpression
    force_revshare = 70.0
    report = PublisherUpliftReport
    template_name = "adserver/reports/all-publishers-uplift.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        sort = self.request.GET.get("sort", "")
        force_revshare = self.request.GET.get("force_revshare", self.force_revshare)

        publishers = Publisher.objects.all()

        # Get all publishers where an ad has a view or click in the specified date range
        revenue_share_percentage = self.request.GET.get("revenue_share_percentage", "")
        if revenue_share_percentage:
            try:
                publishers = publishers.filter(
                    revenue_share_percentage=float(revenue_share_percentage)
                )
            except ValueError:
                pass

        queryset = self.get_queryset(
            publishers=publishers,
            start_date=context["start_date"],
            end_date=context["end_date"],
            campaign_type=context["campaign_type"],
        )

        report = self.report(
            queryset,
            max_results=None,
            force_revshare=force_revshare,
            order=sort if sort else None,
        )
        report.generate()
        sort_options = report.total.keys()

        context.update(
            {
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                # Make these strings to easily compare with GET args
                "revshare_options": set(
                    str(pub.revenue_share_percentage) for pub in Publisher.objects.all()
                ),
                "revenue_share_percentage": revenue_share_percentage,
                "sort": sort,
                "sort_options": sort_options,
                "export_url": self.get_export_url(),
            }
        )

        return context


class PublisherMainView(
    PublisherAccessMixin, UserPassesTestMixin, ReportQuerysetMixin, DetailView
):

    """Should be (or redirect to) the main view for a publisher that they see when first logging in."""

    publisher = None
    impression_model = AdImpression
    model = Publisher
    template_name = "adserver/publisher/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get the beginning of the month so we can show month-to-date stats
        start_date = timezone.now().replace(day=1, hour=0, minute=0, second=0)

        queryset = self.get_queryset(
            publisher=self.publisher,
            start_date=start_date,
        )
        report = PublisherReport(queryset)
        report.generate()

        context.update(
            {
                "publisher": self.publisher,
                "report": report,
                "start_date": start_date,
            }
        )
        return context

    def get_object(self, queryset=None):  # pylint: disable=unused-argument
        self.publisher = get_object_or_404(
            Publisher, slug=self.kwargs["publisher_slug"]
        )
        return self.publisher


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
