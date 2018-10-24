"""
Ad decision backends for the ad server

Different sites may want different backends based on how different
ads should be prioritized. For example, you may want to prioritize
ads by which one makes the most money or by which one is the most relevant.
"""
from django.conf import settings

from .backends import AdvertisingDisabledBackend
from .backends import ProbabilisticClicksNeededBackend


def get_ad_decision_backend():
    if not getattr(settings, "ADSERVER_DISABLE_ADS", True):
        return AdvertisingDisabledBackend

    return ProbabilisticClicksNeededBackend
