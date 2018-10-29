"""Ad server utilities"""
import hashlib
import ipaddress
import logging
import re
from collections import namedtuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.encoding import force_text
from ratelimit.utils import is_ratelimited
from user_agents import parse

from .constants import CLICKS
from .constants import OFFERS
from .constants import VIEWS


log = logging.getLogger(__name__)  # noqa

# Compile these regular expressions at startup time for performance purposes
BLACKLISTED_UA_REGEXES = [
    re.compile(s) for s in settings.ADSERVER_BLACKLISTED_USER_AGENTS
]


GeolocationTuple = namedtuple(
    "GeolocationTuple", ["country_code", "region_code", "metro_code"]
)


def offer_ad(advertisement):
    """
    Do the book keeping required to track ad offers.

    This generates a nonce as part of the return dict,
    and that must be used throughout the ad pipeline in order to dedupe clicks.
    """
    promo_dict = advertisement.as_dict()
    advertisement.incr(OFFERS)
    # Set validation cache
    for promo_type in [VIEWS, CLICKS]:
        cache.set(
            advertisement.cache_key(
                impression_type=promo_type, nonce=promo_dict["nonce"]
            ),
            0,  # Number of times used. Make this an int so we can detect multiple uses
            60 * 60,  # hour
        )

    return promo_dict


def analytics_event(**kwargs):  # noqa TODO add this
    pass


def get_ad_day():
    """Return a datetime that is the start of the current UTC day"""
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def calculate_ecpm(cost, views):
    """Return the effective cost per 1000 impressions given the total cost and views"""
    if views > 0:
        return float(cost) * 1000.0 / views

    return 0.0


def calculate_ctr(clicks, views):
    """Return the click through rate [0.0, 100.0] given the total clicks and views"""
    if views > 0:
        return float(clicks) * 100.0 / views

    return 0.0


def get_client_ip(request):
    """
    Gets the real IP based on a request object

    Checks if ``request.ip_address`` is present from a Middleware
    (eg. ``RealIPAddressMiddleware``) and returns that.
    If that is not set, return the value from ``REMOTE_ADDR``.
    """
    if hasattr(request, "ip_address"):
        return request.ip_address

    return request.META.get("REMOTE_ADDR", "")


def anonymize_ip_address(ip_address):
    """Anonymizes an IP address by zeroing the last 2 bytes"""
    # Used to anonymize an IP by zero-ing out the last 2 bytes
    ip_mask = int("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000", 16)

    try:
        ip_obj = ipaddress.ip_address(force_text(ip_address))
    except ValueError:
        return None

    anonymized_ip = ipaddress.ip_address(int(ip_obj) & ip_mask)
    return anonymized_ip.compressed


def anonymize_user_agent(user_agent):
    """Anonymizes rare user agents"""
    # If the browser family is not recognized, this is a rare user agent
    parsed_ua = parse(user_agent)
    if parsed_ua.browser.family == "Other" or parsed_ua.os.family == "Other":
        return "Rare user agent"

    return user_agent


def is_click_ratelimited(request, ratelimits=settings.ADSERVER_CLICK_RATELIMITS):
    """Returns ``True`` if this user is rate limited from clicking ads and ``False`` otherwise"""
    for rate in ratelimits:
        if is_ratelimited(
            request, group="ad.click", key="ip", rate=rate, increment=True
        ):
            return True

    return False


def is_blacklisted_user_agent(user_agent, blacklist_regexes=BLACKLISTED_UA_REGEXES):
    """Returns ``True`` if the UA is blacklisted and ``False`` otherwise"""
    for regex in blacklist_regexes:
        if regex.search(user_agent):
            return True

    return False


def generate_client_id(ip_address, user_agent):
    """
    Create an advertising ID

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
