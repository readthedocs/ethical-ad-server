"""
Ad decision backends for the ad server.

Different sites may want different backends based on how different
ads should be prioritized. For example, you may want to prioritize
ads which one makes the most money or by which one is the most relevant.
"""
from django.conf import settings
from django.utils.module_loading import import_string

from .backends import AdvertisingDisabledBackend


def get_ad_decision_backend():
    if not settings.ADSERVER_DECISION_BACKEND:
        return AdvertisingDisabledBackend

    return import_string(settings.ADSERVER_DECISION_BACKEND)
