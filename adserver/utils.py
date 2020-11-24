"""Ad server utilities."""
import hashlib
import ipaddress
import logging
import os
import re
from collections import namedtuple
from datetime import datetime
from datetime import timedelta

import analytical
import IP2Proxy
from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.geoip2 import GeoIP2Exception
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.encoding import force_text
from django.utils.http import urlencode
from django_countries import countries
from geoip2.errors import AddressNotFoundError
from ratelimit.utils import is_ratelimited
from user_agents import parse

from .constants import PAID_CAMPAIGN


log = logging.getLogger(__name__)  # noqa


GeolocationTuple = namedtuple(
    "GeolocationTuple", ["country_code", "region_code", "metro_code"]
)


# Put this here so we don't reload it on each call
COUNTRY_DICT = dict(countries)


def analytics_event(**kwargs):
    """Send data to analytics with celery."""
    if settings.ADSERVER_ANALYTICS_ID:
        ga = analytical.Provider(
            "googleanalytics", settings.ADSERVER_ANALYTICS_ID, asynchronously=True
        )
        kwargs["an"] = "Ethical Ad Server"
        kwargs["av"] = settings.ADSERVER_VERSION
        kwargs["aip"] = "1"

        if kwargs.get("uip"):
            kwargs["uip"] = anonymize_ip_address(kwargs["uip"])
        if kwargs.get("ua"):
            kwargs["ua"] = anonymize_user_agent(kwargs["ua"])

        ga.event(kwargs)


def get_ad_day():
    """Return a datetime that is the start of the current UTC day."""
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def parse_date_string(date_str):
    if not date_str:
        return None

    try:
        return timezone.make_aware(datetime.strptime(date_str, "%Y-%m-%d"))
    except ValueError:
        # Since this can come from GET params, handle errors
        pass

    return None


def calculate_ecpm(cost, views):
    """Return the effective cost per 1000 impressions given the total cost and views."""
    if views > 0:
        return float(cost) * 1000.0 / views

    return 0.0


def calculate_ctr(clicks, views):
    """Return the click through rate [0.0, 100.0] given the total clicks and views."""
    if views > 0:
        return float(clicks) * 100.0 / views

    return 0.0


def get_client_ip(request):
    """
    Gets the real IP based on a request object.

    Checks if ``request.ip_address`` is present from a Middleware
    (eg. ``RealIPAddressMiddleware``) and returns that.
    If that is not set, return the value from ``REMOTE_ADDR``.
    """
    ip = getattr(request, "ip_address", None)
    if ip:
        return ip

    return request.META.get("REMOTE_ADDR", "")


def get_client_user_agent(request):
    """Gets the users user agent based on the request object."""
    ua = getattr(request, "user_agent", None)
    if ua:
        return ua

    return request.META.get("HTTP_USER_AGENT", "")


def get_client_id(request):
    """Gets the user advertising client ID based on the request."""
    client_id = getattr(request, "advertising_client_id", None)
    if not client_id:
        ua = get_client_user_agent(request)
        ip = get_client_ip(request)
        client_id = generate_client_id(ip, ua)

    return client_id


def get_client_country(request, ip_address=None):
    """Get country data for this request."""
    country = None
    if hasattr(request, "geo"):
        # This is set in all API requests that use the GeoIpMixin
        country = request.geo.country_code
    else:
        geo_data = get_geolocation(ip_address)
        if geo_data:
            country = geo_data["country_code"]

    return country


def get_country_name(country_code):
    return COUNTRY_DICT.get(country_code)


def anonymize_ip_address(ip_address):
    """Anonymizes an IP address by zeroing the last 2 bytes."""
    # Used to anonymize an IP by zero-ing out the last 2 bytes
    ip_mask = int("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000", 16)

    try:
        ip_obj = ipaddress.ip_address(force_text(ip_address))
    except ValueError:
        return None

    anonymized_ip = ipaddress.ip_address(int(ip_obj) & ip_mask)
    return anonymized_ip.compressed


def anonymize_user_agent(user_agent):
    """Anonymizes rare user agents."""
    # If the browser family is not recognized, this is a rare user agent
    parsed_ua = parse(user_agent)
    if parsed_ua.browser.family == "Other" or parsed_ua.os.family == "Other":
        return "Rare user agent"

    return user_agent


def is_view_ratelimited(request, ratelimits=None):
    """Returns ``True`` if this user is rate limited from viewing ads and ``False`` otherwise."""
    if ratelimits is None:
        # Explicitly set the rate limits ONLY if the parameter is `None`
        # If it is an empty list, there's simply no rate limiting
        ratelimits = settings.ADSERVER_VIEW_RATELIMITS

    for rate in ratelimits:
        if is_ratelimited(
            request,
            group="ad.view",
            key=lambda _, req: get_client_ip(req),
            rate=rate,
            increment=True,
        ):
            return True

    return False


def is_click_ratelimited(request, ratelimits=None):
    """Returns ``True`` if this user is rate limited from clicking ads and ``False`` otherwise."""
    if ratelimits is None:
        # Explicitly set the rate limits ONLY if the parameter is `None`
        # If it is an empty list, there's simply no rate limiting
        ratelimits = settings.ADSERVER_CLICK_RATELIMITS

    for rate in ratelimits:
        if is_ratelimited(
            request,
            group="ad.click",
            key=lambda _, req: get_client_ip(req),
            rate=rate,
            increment=True,
        ):
            return True

    return False


def is_blocklisted_user_agent(user_agent, blocklist_regexes=None):
    """Returns ``True`` if the UA is blocklisted and ``False`` otherwise."""
    if blocklist_regexes is None:
        blocklist_regexes = BLOCKLISTED_UA_REGEXES

    if user_agent:
        for regex in blocklist_regexes:
            if regex.search(user_agent):
                return True

    return False


def is_blocklisted_referrer(referrer, blocklist_regexes=None):
    """Returns ``True`` if the Referrer is blocklisted and ``False`` otherwise."""
    if blocklist_regexes is None:
        blocklist_regexes = BLOCKLISTED_REFERRERS_REGEXES

    if referrer:
        for regex in blocklist_regexes:
            if regex.search(referrer):
                return True

    return False


def is_blocklisted_ip(ip, blocked_ips=None):
    """
    Returns ``True`` if the IP is blocklisted and ``False`` otherwise.

    IPs can be blocked because they are anonymous proxies or other reasons.
    """
    if blocked_ips is None:
        blocked_ips = BLOCKLISTED_IPS

    if ip and ip in blocked_ips:
        return True
    if ip and is_proxy_ip(ip):
        return True

    return False


def is_proxy_ip(ip):
    if ipproxy_db and ipproxy_db.is_proxy(ip) > 0:
        return True

    return False


def get_geolocation(ip_address):
    try:
        ipaddress.ip_address(force_text(ip_address))
    except ValueError:
        # Invalid IP address
        return None

    if geoip:
        try:
            return geoip.city(ip_address)
        except AddressNotFoundError:
            log.debug("Could not get geolocation for %s", ip_address)
        except GeoIP2Exception:
            log.warning("Geolocation configuration error")

    return None


def get_ipproxy_db():
    db = None

    filepath = os.path.join(settings.GEOIP_PATH, "IP2Proxy.BIN")
    if os.path.exists(filepath):
        db = IP2Proxy.IP2Proxy(filepath)
    else:
        log.warning("IP Proxy detection is not available.")

    return db


def build_blocked_ip_set():
    """Build a set of blocked IPs for preventing bogus ad impressions."""
    blocked_ips = set()

    filepath = os.path.join(settings.GEOIP_PATH, "torbulkexitlist.txt")
    if os.path.exists(filepath):
        with open(filepath) as fd:
            for line in fd.readlines():
                line = line.strip()
                if line:
                    blocked_ips.add(line)

    return blocked_ips


def generate_client_id(ip_address, user_agent):
    """
    Create an advertising ID.

    This simplifies things but essentially if a user has the same IP and same UA,
    this will treat them as the same user for analytics purposes
    """
    salt = b"advertising-client-id"

    hash_id = hashlib.sha256()
    hash_id.update(force_bytes(settings.SECRET_KEY))
    hash_id.update(salt)
    if ip_address:
        hash_id.update(force_bytes(ip_address))
    if user_agent:
        hash_id.update(force_bytes(user_agent))

    if not ip_address and not user_agent:
        # Since no IP and no UA were specified,
        # there's no way to distinguish sessions.
        # Instead, just treat every user differently
        hash_id.update(force_bytes(get_random_string()))

    return hash_id.hexdigest()


def generate_absolute_url(view, kwargs):
    """
    Generate a fully qualified URL for a view on our site.

    This will look like ``https://server.ethicalads.io/foo/``.
    """
    site = get_current_site(None)
    domain = site.domain
    scheme = "http"
    if settings.ADSERVER_HTTPS:
        scheme = "https"

    url = "{scheme}://{domain}{url}".format(
        scheme=scheme, domain=domain, url=reverse(view, kwargs=kwargs)
    )
    return url


def generate_publisher_payout_data(publisher):
    """
    Generate the amount due at next payout and current month payout data.

    TODO: Break this function up and move it out of utils.
    """
    from .reports import PublisherReport  # pylint: disable=cyclic-import

    today = timezone.now()
    last_day_last_month = today.replace(day=1) - timedelta(days=1)
    last_payout = publisher.payouts.last()

    if last_payout:
        first = False
        # First of the month of the month the payout was for.
        # TODO: Store this data on the model, instead of hacking it.
        last_payout_date = last_payout.date.replace(day=1)
    else:
        first = True
        # Fake a payout to make the logic work.
        last_payout_date = publisher.created

    report_url = generate_absolute_url(
        "publisher_report", kwargs={"publisher_slug": publisher.slug}
    )

    current_queryset = publisher.adimpression_set.filter(
        date__gte=today.replace(day=1),
        date__lte=today,
        advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
    )
    current_report = PublisherReport(current_queryset)
    current_report.generate()

    current_report_url = (
        report_url
        + "?"
        + urlencode(
            {
                "start_date": today.strftime("%Y-%m-01"),
                "end_date": today.strftime("%Y-%m-%d"),
                "campaign_type": PAID_CAMPAIGN,
            }
        )
    )

    due_report = None
    due_report_url = None

    # Handle cases where a publisher has just joined this month
    if last_payout_date.month != today.month:
        due_queryset = publisher.adimpression_set.filter(
            date__gte=last_payout_date,
            date__lte=last_day_last_month,
            advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
        )
        due_report = PublisherReport(due_queryset)
        due_report.generate()

        due_report_url = (
            report_url
            + "?"
            + urlencode(
                {
                    "start_date": last_payout_date.strftime("%Y-%m-%d"),
                    "end_date": last_day_last_month.strftime("%Y-%m-%d"),
                    "campaign_type": PAID_CAMPAIGN,
                }
            )
        )

    return dict(
        first=first,
        last_payout_date=last_payout_date,
        last_day_last_month=last_day_last_month,
        today=today,
        due_report={
            "total": due_report.total,
            "results": due_report.results,
        }
        if due_report
        else None,
        due_report_url=due_report_url,
        current_report={
            "total": current_report.total,
            "results": current_report.results,
        },
        current_report_url=current_report_url,
    )


# Compile these regular expressions at startup time for performance purposes
BLOCKLISTED_UA_REGEXES = [
    re.compile(s) for s in settings.ADSERVER_BLOCKLISTED_USER_AGENTS
]
BLOCKLISTED_REFERRERS_REGEXES = [
    re.compile(s) for s in settings.ADSERVER_BLOCKLISTED_REFERRERS
]
BLOCKLISTED_IPS = build_blocked_ip_set()

try:
    geoip = GeoIP2()
except GeoIP2Exception:
    log.exception("IP Geolocation is unavailable")
    geoip = None

ipproxy_db = get_ipproxy_db()
