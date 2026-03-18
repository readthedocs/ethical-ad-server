"""Custom context processors that inject certain settings values into all templates."""

import datetime

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def settings_processor(request):
    return {
        "adserver_ethicalads_branding": settings.ADSERVER_ETHICALADS_BRANDING,
        "adserver_privacy_policy": settings.ADSERVER_PRIVACY_POLICY_URL,
        "adserver_publisher_policy": settings.ADSERVER_PUBLISHER_POLICY_URL,
        "adserver_version": settings.ADSERVER_VERSION,
        "adserver_etl": "ethicalads_ext.etl" in settings.INSTALLED_APPS,
        "metabase_enabled": settings.METABASE_ENABLED,
        "plausible_domain": settings.PLAUSIBLE_DOMAIN,
    }


def maintenance_message_processor(request):
    """
    Adds a maintenance message to the context if one is set and it hasn't expired.
    """
    if not settings.ADSERVER_MAINTENANCE_MESSAGE:
        return {}

    expiry = settings.ADSERVER_MAINTENANCE_MESSAGE_EXPIRY
    if isinstance(expiry, str):
        expiry = parse_datetime(expiry)
    elif not isinstance(expiry, datetime.datetime):
        expiry = None

    if expiry and timezone.is_naive(expiry):
        expiry = timezone.make_aware(expiry)

    # Check if the maintenance message has expired
    if expiry and timezone.now() > expiry:
        return {}

    return {
        "maintenance_message": settings.ADSERVER_MAINTENANCE_MESSAGE,
    }
