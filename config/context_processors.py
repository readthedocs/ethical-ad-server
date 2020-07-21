"""Custom context processors that inject certain settings values into all templates."""
from django.conf import settings


def settings_processor(request):
    return {
        "adserver_version": settings.ADSERVER_VERSION,
        "adserver_privacy_policy": settings.ADSERVER_PRIVACY_POLICY_URL,
    }
