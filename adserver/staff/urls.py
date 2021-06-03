"""Urls for the staff interface of the ad server."""
from django.urls import path

from .views import CreateAdvertiserView


urlpatterns = [
    path(
        r"create-advertiser/", CreateAdvertiserView.as_view(), name="create-advertiser"
    ),
]
