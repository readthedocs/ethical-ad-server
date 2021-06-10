"""Urls for the staff interface of the ad server."""
from django.urls import path

from .views import CreateAdvertiserView
from .views import PublisherPayoutView


urlpatterns = [
    path(
        r"create-advertiser/",
        CreateAdvertiserView.as_view(),
        name="create-advertiser",
    ),
    path(
        r"publisher-payouts/",
        PublisherPayoutView.as_view(),
        name="staff-publisher-payouts",
    ),
]
