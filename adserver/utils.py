"""Ad server utilities."""
import hashlib
import ipaddress
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta
from urllib.parse import urlparse

import IP2Proxy
from celery.utils.iso8601 import parse_iso8601
from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.geoip2 import GeoIP2Exception
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.encoding import force_str
from django.utils.http import urlencode
from django.utils.timezone import is_naive
from django.utils.timezone import utc
from django_countries import countries
from geoip2.errors import AddressNotFoundError
from ratelimit.utils import is_ratelimited
from user_agents import parse

from .constants import PAID
from .constants import PAID_CAMPAIGN


log = logging.getLogger(__name__)  # noqa


# Put this here so we don't reload it on each call
COUNTRY_DICT = dict(countries)
COUNTRY_DICT["T1"] = "Tor"


@dataclass
class GeolocationData:

    """Dataclass for (temporarily) storing geolocation information for ad viewers."""

    country: str = (
        None  # Should be a 2 character ISO 3166-1 country code (or T1 for Tor)
    )
    region: str = None
    metro: int = None
    lat: float = None
    lng: float = None


def get_ad_day():
    """Return a datetime that is the start of the current UTC day."""
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def get_day(day=None):
    """
    Get the start and end time for a given day.

    Always return two datetimes with timezone.
    If `day` is `None`, use today.
    If `day` is a datetime or date object, use that day but remove any time data.
    Otherwise, attempt to convert from iso8601.
    """
    start_date = get_ad_day()
    if day:
        if not isinstance(day, (datetime, date)):
            day = parse_iso8601(day)
        start_date = day.replace(hour=0, minute=0, second=0, microsecond=0)
        if is_naive(start_date):
            start_date = utc.localize(start_date)
    end_date = start_date + timedelta(days=1)

    return start_date, end_date


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


def calculate_percent_diff(value, previous):
    """Return the percent difference [0.0, 100.0] of the given value over the previous."""
    if previous > 0:
        return (value / previous - 1) * 100

    return 0.0


def get_client_ip(request):
    """
    Gets the real IP based on a request object.

    Checks if ``request.ip_address`` is present from a Middleware
    (eg. ``CloudflareIpAddressMiddleware``) and returns that.
    If that is not set, return the value from ``REMOTE_ADDR`` and raise a warning.
    """
    if hasattr(request, "ip_address"):
        return request.ip_address

    log.warning(
        "No IP address set by middleware (see CloudflareIpAddressMiddleware). "
        "Consider enabling an IP address middleware so IPs can be used for ad targeting."
    )

    return request.META.get("REMOTE_ADDR", None)


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


def get_client_country(request):
    """Get country data for this request."""
    geo_data = get_geolocation(request)
    return geo_data.country


def get_country_name(country_code):
    return COUNTRY_DICT.get(country_code, country_code)


def get_domain_from_url(url):
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    return parsed.netloc


def anonymize_ip_address(ip_address):
    """Anonymizes an IP address by zeroing the last 2 bytes."""
    # Used to anonymize an IP by zero-ing out the last 2 bytes
    ip_mask = int("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000", 16)

    try:
        ip_obj = ipaddress.ip_address(force_str(ip_address))
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


def get_geolocation(request, force=False):
    """Gets the geolocation for this IP address."""
    if force:
        return get_geoipdb_geolocation(request)
    if hasattr(request, "geo"):
        return request.geo

    log.warning(
        "No geolocation data set by middleware (see CloudflareGeoIpMiddleware). "
        "Consider enabling a GeoIp middleware for ad targeting."
    )
    return GeolocationData()


def get_geoipdb_geolocation(request):
    """Get geolocation using a GeoIP database (such as MaxMind)."""
    geolocation = GeolocationData()
    ip_address = get_client_ip(request)

    try:
        ipaddress.ip_address(force_str(ip_address))
    except ValueError:
        # Invalid IP address - should be safe to log. It's invalid and not identifying
        log.warning("Invalid IP address passed to GeoIP database. IP=%s", ip_address)
        return geolocation

    if geoip:
        try:
            geo = geoip.city(ip_address)
            geolocation.country = geo["country_code"]
            geolocation.region = geo["region"]
            geolocation.metro = geo["dma_code"]
        except AddressNotFoundError:
            # This is probably a local address like 127.0.0.1
            log.debug("Could not get geolocation. IP=%s", ip_address)
        except GeoIP2Exception:
            log.warning("Geolocation configuration error")
    else:
        log.warning("No GeoIP database found.")

    return geolocation


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
        with open(filepath, "r", encoding="utf-8") as fd:
            for line in fd:
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
        hash_id.update(force_bytes(anonymize_ip_address(ip_address)))
    if user_agent:
        hash_id.update(force_bytes(user_agent))

    if not ip_address and not user_agent:
        # Since no IP and no UA were specified,
        # there's no way to distinguish sessions.
        # Instead, just treat every user differently
        hash_id.update(force_bytes(get_random_string(length=12)))

    return hash_id.hexdigest()


def generate_absolute_url(url):
    """
    Generate a fully qualified URL for a path on our site.

    This will look like ``https://server.ethicalads.io/foo/``.
    """
    site = get_current_site(None)
    domain = site.domain
    scheme = "http"
    if settings.ADSERVER_HTTPS:
        scheme = "https"

    url = "{scheme}://{domain}{url}".format(scheme=scheme, domain=domain, url=url)
    return url


def generate_publisher_payout_data(
    publisher, include_current_report=True, include_due_report=True
):
    """
    Generate the amount due at next payout and current month payout data.

    TODO: Break this function up and move it out of utils.
    """
    # pylint: disable=cyclic-import
    # pylint: disable=import-outside-toplevel
    from .reports import PublisherReport

    today = timezone.now()
    end_date = today.replace(day=1) - timedelta(days=1)
    last_payout = publisher.payouts.filter(status=PAID).last()

    if last_payout:
        first = False
        # First of the month of the month the payout was for.
        # TODO: Store this data on the model, instead of hacking it.
        start_date = last_payout.date.replace(day=1)
    else:
        first = True
        # Fake a payout to make the logic work.
        start_date = publisher.created

    report_url = generate_absolute_url(
        reverse("publisher_report", kwargs={"publisher_slug": publisher.slug})
    )

    current_report = None
    current_report_url = None
    due_report = None
    due_report_url = None

    if include_current_report:
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

    # Handle cases where a publisher has just joined this month
    if include_due_report and start_date < today.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ):
        due_queryset = publisher.adimpression_set.filter(
            date__gte=start_date,
            date__lte=end_date,
            advertisement__flight__campaign__campaign_type=PAID_CAMPAIGN,
        )
        due_report = PublisherReport(due_queryset)
        due_report.generate()

        due_report_url = (
            report_url
            + "?"
            + urlencode(
                {
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "campaign_type": PAID_CAMPAIGN,
                }
            )
        )

    payouts_url = generate_absolute_url(
        reverse("publisher_payouts", kwargs={"publisher_slug": publisher.slug})
    )
    settings_url = generate_absolute_url(
        reverse("publisher_settings", kwargs={"publisher_slug": publisher.slug})
    )

    return dict(
        first=first,
        start_date=start_date,
        end_date=end_date,
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
        }
        if current_report
        else None,
        current_report_url=current_report_url,
        payouts_url=payouts_url,
        settings_url=settings_url,
        publisher=publisher,
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
