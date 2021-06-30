"""Urls for the staff interface of the ad server."""
from django.urls import path

from .views import CreateAdvertiserView
from .views import CreatePublisherView
from .views import PublisherFinishPayoutView
from .views import PublisherPayoutView
from .views import PublisherStartPayoutView


urlpatterns = [
    path(
        r"create-advertiser/",
        CreateAdvertiserView.as_view(),
        name="create-advertiser",
    ),
    path(
        r"create-publisher/",
        CreatePublisherView.as_view(),
        name="create-publisher",
    ),
    path(
        r"publisher-payouts/",
        PublisherPayoutView.as_view(),
        name="staff-publisher-payouts",
    ),
    path(
        r"publisher-start-payout/<slug:publisher_slug>/",
        PublisherStartPayoutView.as_view(),
        name="staff-start-publisher-payout",
    ),
    path(
        r"publisher-finish-payout/<slug:publisher_slug>/",
        PublisherFinishPayoutView.as_view(),
        name="staff-finish-publisher-payout",
    ),
]
