"""API Urls for the ad server."""

from django.conf import settings
from django.urls import path
from rest_framework import routers

from .views import AdDecisionView
from .views import AdvertisementViewSet
from .views import AdvertiserViewSet
from .views import FlightViewSet
from .views import PublisherViewSet


app_name = "api"

urlpatterns = [
    path(r"decision/", AdDecisionView.as_view(), name="decision"),
    # The flight/advertisement API paths match the URL structure of the advertiser dashboard.
    # These viewsets are wired manually because they're nested under the advertiser
    # which the router can't do: any extra @actions on them must also be added here.
    path(
        r"advertisers/<slug:advertiser_slug>/flights/",
        FlightViewSet.as_view({"get": "list"}),
        name="flights-list",
    ),
    path(
        r"advertisers/<slug:advertiser_slug>/flights/<slug:flight_slug>/",
        FlightViewSet.as_view({"get": "retrieve"}),
        name="flights-detail",
    ),
    path(
        r"advertisers/<slug:advertiser_slug>/flights/<slug:flight_slug>/advertisements/",
        AdvertisementViewSet.as_view({"get": "list"}),
        name="advertisements-list",
    ),
    path(
        r"advertisers/<slug:advertiser_slug>/flights/<slug:flight_slug>/advertisements/<slug:advertisement_slug>/",
        AdvertisementViewSet.as_view({"get": "retrieve"}),
        name="advertisements-detail",
    ),
]

router = routers.SimpleRouter()
router.register(r"advertisers", AdvertiserViewSet, basename="advertisers")
router.register(r"publishers", PublisherViewSet, basename="publishers")

if "ethicalads_ext.embedding" in settings.INSTALLED_APPS:
    from ethicalads_ext.embedding import urls as embedding_urls  # noqa

    urlpatterns += embedding_urls.urlpatterns


urlpatterns += router.urls
