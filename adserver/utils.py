"""Ad server utilities"""

import ipaddress
import logging
import re

from django.conf import settings
from django.utils.encoding import force_text

from user_agents import parse
from ratelimit.utils import is_ratelimited


log = logging.getLogger(__name__)  # noqa

# Compile these regular expressions at startup time for performance purposes
BLACKLISTED_UA_REGEXES = [
    re.compile(s) for s in settings.ADSERVER_BLACKLISTED_USER_AGENTS
]


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
    """Gets the real IP based on a request object"""
    ip_address = request.META.get("REMOTE_ADDR")

    # Get the original IP address (eg. "X-Forwarded-For: client, proxy1, proxy2")
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
    if x_forwarded_for:
        ip_address = x_forwarded_for.rsplit(":")[0]

    return ip_address


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
