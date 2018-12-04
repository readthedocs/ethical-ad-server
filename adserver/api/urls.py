"""API Urls for the ad server"""
from django.conf.urls import url

from .views import AdDecisionView
from .views import ClickTrackingView
from .views import ViewTrackingView


urlpatterns = [
    url(r"^decision/$", AdDecisionView.as_view(), name="decision"),
    url(r"^track/view/$", ViewTrackingView.as_view(), name="view-tracking"),
    url(r"^track/click/$", ClickTrackingView.as_view(), name="click-tracking"),
]
