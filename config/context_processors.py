"""Custom context processors that inject certain settings values into all templates."""

from django.conf import settings


def settings_processor(request):
    return {
        "adserver_ethicalads_branding": settings.ADSERVER_ETHICALADS_BRANDING,
        "adserver_privacy_policy": settings.ADSERVER_PRIVACY_POLICY_URL,
        "adserver_publisher_policy": settings.ADSERVER_PUBLISHER_POLICY_URL,
        "adserver_version": settings.ADSERVER_VERSION,
        "plausible_domain": settings.PLAUSIBLE_DOMAIN,
    }
