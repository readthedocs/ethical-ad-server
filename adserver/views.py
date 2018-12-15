"""Ad server views"""
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from user_agents import parse

from .constants import CLICKS
from .constants import VIEWS
from .models import Advertisement
from .utils import analytics_event
from .utils import get_client_ip
from .utils import is_blacklisted_user_agent
from .utils import is_click_ratelimited


log = logging.getLogger(__name__)  # noqa


def do_not_track(request):
    """
    Returns the Do Not Track status for the user

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
    Returns the Do Not Track policy

    https://github.com/EFForg/dnt-guide#12-how-to-assert-dnt-compliance

    :raises: Http404 if ``settings.ADSERVER_DO_NOT_TRACK`` is ``False``
    """
    if not settings.ADSERVER_DO_NOT_TRACK:
        raise Http404

    return render(request, "adserver/dnt-policy.txt", content_type="text/plain")


def proxy_ad_click(request, ad_id, nonce):
    """Track a click on an ad and redirect to the link."""
    ip = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    parsed_ua = parse(user_agent)

    ad = get_object_or_404(Advertisement, pk=ad_id)
    count = cache.get(ad.cache_key(impression_type=CLICKS, nonce=nonce), None)

    event_category = "Advertisement"
    event_action = "Billed Click"
    event_label = ad.slug

    # The event_value is in US cents (eg. for $2 CPC, the value is 200)
    # CPMs are too small to register
    event_value = int(ad.flight.cpc * 100)  # GA doesn't support floats for event value

    if parsed_ua.is_bot:
        log.warning("Bot click. User Agent: [%s]", user_agent)
        event_action = "Bot Click"
    elif parsed_ua.os.family == "Other" and parsed_ua.browser.family == "Other":
        # This is probably a bot/proxy server/prefetcher/etc.
        log.warning("Unknown user agent click [%s]", user_agent)
        event_action = "Invalid UA Click"
    elif request.user.is_staff:
        log.warning("Ignored staff user ad click")
        event_action = "Staff Click"
    elif count is None:
        log.warning("Old or nonexistent hash tried on Click.")
        event_action = "Old/Nonexistent Click"
    elif is_blacklisted_user_agent(user_agent):
        log.warning("Blacklisted user agent click [%s]", user_agent)
        event_action = "Blacklisted Click"
    elif is_click_ratelimited(request):
        # Note: Normally logging IPs is frowned upon but this is a security/billing violation
        log.warning("User (%s) has clicked too many ads recently [%s]", ip, user_agent)
        event_action = "RateLimited Click"
    elif count == 0:
        log.debug("Billed ad click")
        ad.incr(CLICKS)
        cache.incr(ad.cache_key(impression_type=CLICKS, nonce=nonce))
        ad.record_click(request=request, advertisement=ad)
    else:
        log.warning(
            "Duplicate click logged. %s total clicks tried. User Agent: [%s]",
            count,
            user_agent,
        )
        cache.incr(ad.cache_key(impression_type=CLICKS, nonce=nonce))
        event_action = "Duplicate Click"

    analytics_event(
        ec=event_category,
        ea=event_action,
        el=event_label,
        ev=event_value,
        ua=user_agent,
        uip=ip,
    )
    return redirect(ad.link)


def proxy_ad_view(request, ad_id, nonce):
    """Track a view of an ad and redirect to the image."""
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    parsed_ua = parse(user_agent)

    ad = get_object_or_404(Advertisement, pk=ad_id)
    count = cache.get(ad.cache_key(impression_type=VIEWS, nonce=nonce), None)

    if parsed_ua.is_bot:
        log.debug("Bot view. User Agent: [%s]", user_agent)
    elif parsed_ua.os.family == "Other" and parsed_ua.browser.family == "Other":
        # This is probably a bot/proxy server/prefetcher/etc.
        log.debug("Unknown user agent view [%s]", user_agent)
    elif request.user.is_staff:
        log.debug("Ignored staff user ad view")
    elif count is None:
        log.debug("Old or nonexistent hash tried on View.")
    elif is_blacklisted_user_agent(user_agent):
        log.debug("Blacklisted user agent view [%s]", user_agent)
    elif count == 0:
        log.debug("Billed ad view")
        ad.incr(VIEWS)
        cache.incr(ad.cache_key(impression_type=VIEWS, nonce=nonce))
        ad.record_view(request=request, advertisement=ad)
    else:
        log.debug(
            "Duplicate view logged. %s total views tried. User Agent: [%s]",
            count,
            user_agent,
        )
        cache.incr(ad.cache_key(impression_type=VIEWS, nonce=nonce))
    if ad.image:
        return redirect(ad.image.url)

    return HttpResponse("View Proxy")


@login_required
def dashboard(request):
    return render(
        request, "adserver/dashboard.html", {"version": settings.ADSERVER_VERSION}
    )
