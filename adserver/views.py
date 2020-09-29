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
from .mixins import PublisherAccessMixin
from .models import AdImpression
from .models import AdType
from .models import Advertisement
from .models import Advertiser
from .models import Flight
from .models import Publisher
from .models import PublisherPayout
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

    def get_object(self, queryset=None):
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

    def get_object(self, queryset=None):
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

    def get_object(self, queryset=None):
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
                "ad_types": AdType.objects.exclude(description="")[:5],
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

    def ignore_tracking_reason(self, request, advertisement, nonce, publisher):
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

        if not advertisement.is_valid_nonce(self.impression_type, nonce):
            log.log(self.log_level, "Old or nonexistent impression nonce")
            reason = "Old/Nonexistent nonce"
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
                publisher,
                user_agent,
            )
            reason = "Blocked referrer impression"
        elif is_blocklisted_ip(ip_address):
            log.log(self.log_level, "Blocked IP impression, Publisher: [%s]", publisher)
            reason = "Blocked IP impression"
        elif not publisher:
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
                publisher,
                user_agent,
            )
            reason = "Ratelimited click impression"
        elif self.impression_type == VIEWS and is_view_ratelimited(request):
            log.log(
                self.log_level,
                "User has viewed too many ads recently, Publisher: [%s], UA: [%s]",
                publisher,
                user_agent,
            )
            reason = "Ratelimited view impression"

        return reason

    def send_to_analytics(self, request, advertisement, message):
        """A no-op by default, sublcasses may override it to send view/clicks to analytics."""

    def get(self, request, advertisement_id, nonce):
        """Handles proxying ad views and clicks and collecting metrics on them."""
        advertisement = get_object_or_404(Advertisement, pk=advertisement_id)
        publisher = advertisement.get_publisher(nonce)
        referrer = request.META.get("HTTP_REFERER")

        ignore_reason = self.ignore_tracking_reason(
            request, advertisement, nonce, publisher
        )

        if not ignore_reason:
            log.log(self.log_level, self.success_message)
            advertisement.invalidate_nonce(self.impression_type, nonce)
            advertisement.track_impression(
                request, self.impression_type, publisher, referrer
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
    export = False
    export_filename = "readthedocs-report.csv"
    fieldnames = ["date", "views", "clicks", "cost", "ctr", "ecpm"]

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
            writer.writerows(report["days"])

            # Update the Total field for display purposes only
            report["total"]["date"] = "Total"
            writer.writerow(report["total"])

            return response

        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        start_date = self.get_start_date()
        end_date = self.get_end_date()
        campaign_type = self.request.GET.get("campaign_type", "")
        revenue_share_percentage = self.request.GET.get("revenue_share_percentage", "")
        # This needs to be something other than `advertiser` to not conflict with template context on advertising reports.
        report_advertiser = self.request.GET.get("report_advertiser", "")

        if end_date and end_date < start_date:
            end_date = None

        return {
            "start_date": start_date,
            "end_date": end_date,
            "campaign_type": campaign_type,
            "revenue_share_percentage": revenue_share_percentage,
            "report_advertiser": report_advertiser,
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


class AdvertiserReportView(AdvertiserAccessMixin, BaseReportView):

    """A report for one advertiser."""

    template_name = "adserver/reports/advertiser.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        start_date = context["start_date"]
        end_date = context["end_date"]

        advertiser_slug = kwargs.get("advertiser_slug", "")

        advertiser = get_object_or_404(Advertiser, slug=advertiser_slug)
        advertiser_report = advertiser.daily_reports(
            start_date=start_date, end_date=end_date
        )

        flights = (
            Flight.objects.filter(campaign__advertiser=advertiser)
            .order_by("-live", "-end_date", "name")
            .select_related("campaign")
        )

        context.update(
            {
                "advertiser": advertiser,
                "advertiser_report": advertiser_report,
                "report": advertiser_report,
                "flights": flights,
                "total_clicks": advertiser_report["total"]["clicks"],
                "total_cost": advertiser_report["total"]["cost"],
                "total_views": advertiser_report["total"]["views"],
                "total_ctr": advertiser_report["total"]["ctr"],
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

        flight_report = flight.daily_reports(start_date=start_date, end_date=end_date)

        advertisements = []
        for ad, ad_report in flight.ad_reports(
            start_date=start_date, end_date=end_date
        ):
            ad.report = ad_report
            advertisements.append(ad)

        context.update(
            {
                "advertiser": advertiser,
                "flight": flight,
                "flight_report": flight_report,
                "report": flight_report,
                "advertisements": advertisements,
                "total_clicks": flight_report["total"]["clicks"],
                "total_cost": flight_report["total"]["cost"],
                "total_views": flight_report["total"]["views"],
                "total_ctr": flight_report["total"]["ctr"],
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


class PublisherReportView(PublisherAccessMixin, BaseReportView):

    """A report for a single publisher."""

    template_name = "adserver/reports/publisher.html"

    fieldnames = ["date", "views", "clicks", "ctr", "ecpm", "revenue", "revenue_share"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        publisher_slug = kwargs.get("publisher_slug", "")
        publisher = get_object_or_404(Publisher, slug=publisher_slug)

        advertiser_list = (
            publisher.adimpression_set.order_by(
                "advertisement__flight__campaign__advertiser__slug"
            )
            .values_list(
                "advertisement__flight__campaign__advertiser__slug",
                "advertisement__flight__campaign__advertiser__name",
            )
            .distinct()
        )

        report = publisher.daily_reports(
            start_date=context["start_date"],
            end_date=context["end_date"],
            campaign_type=context["campaign_type"],
            advertiser=context["report_advertiser"],
        )

        context.update(
            {
                "publisher": publisher,
                "report": report,
                "campaign_types": CAMPAIGN_TYPES,
                "advertiser_list": advertiser_list,
            }
        )

        return context


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

    def get_object(self, queryset=None):
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

    def get_object(self, queryset=None):  # noqa
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

    template_name = "adserver/reports/all-publishers.html"

    def get_context_data(self, **kwargs):  # pylint: disable=too-many-locals
        context = super().get_context_data(**kwargs)
        sort = self.request.GET.get("sort", "")

        # Get all publishers where an ad has a view or click in the specified date range
        impressions = AdImpression.objects.filter(date__gte=context["start_date"])
        if context["end_date"]:
            impressions = impressions.filter(date__lte=context["end_date"])

        publishers = Publisher.objects.filter(id__in=impressions.values("publisher"))

        if context["revenue_share_percentage"]:
            try:
                publishers = publishers.filter(
                    revenue_share_percentage=float(context["revenue_share_percentage"])
                )
            except ValueError:
                pass

        publishers_and_reports = []
        for publisher in publishers:
            report = publisher.daily_reports(
                start_date=context["start_date"],
                end_date=context["end_date"],
                campaign_type=context["campaign_type"],
            )
            if report["total"]["views"] > 0:
                publishers_and_reports.append((publisher, report))

        # Sort reports by revenue
        if sort == "revenue":
            publishers_and_reports = sorted(
                publishers_and_reports,
                key=lambda obj: obj[1]["total"]["revenue"],
                reverse=True,
            )

        total_clicks = sum(
            report["total"]["clicks"] for _, report in publishers_and_reports
        )
        total_views = sum(
            report["total"]["views"] for _, report in publishers_and_reports
        )
        total_revenue = sum(
            report["total"]["revenue"] for _, report in publishers_and_reports
        )
        our_total_revenue = total_revenue - sum(
            report["total"]["revenue_share"] for _, report in publishers_and_reports
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
                days[day["date"]]["revenue"] += float(day["revenue"])
                days[day["date"]]["our_revenue"] += float(day["our_revenue"])
                days[day["date"]]["ctr"] = calculate_ctr(
                    days[day["date"]]["clicks"], days[day["date"]]["views"]
                )

        context.update(
            {
                "publishers": [p for p, _ in publishers_and_reports],
                "publishers_and_reports": publishers_and_reports,
                "total_clicks": total_clicks,
                "total_revenue": total_revenue,
                "our_total_revenue": our_total_revenue,
                "total_views": total_views,
                "total_ctr": calculate_ctr(total_clicks, total_views),
                "total_ecpm": calculate_ecpm(total_revenue, total_views),
                "campaign_types": CAMPAIGN_TYPES,
                # Make these strings to easily compare with GET args
                "revshare_options": set(
                    str(pub.revenue_share_percentage) for pub in Publisher.objects.all()
                ),
                "sort": sort,
            }
        )

        return context


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

    def get_object(self, queryset=None):  # noqa
        token = Token.objects.filter(user=self.request.user).first()
        if not token:
            raise Http404
        return token
