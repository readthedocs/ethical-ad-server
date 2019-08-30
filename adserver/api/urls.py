"""API Urls for the ad server."""
from django.conf.urls import url
from rest_framework import routers

from .views import AdDecisionView
from .views import AdvertiserViewSet
from .views import ClickTrackingView
from .views import PublisherViewSet
from .views import ViewTrackingView


urlpatterns = [
    url(r"^decision/$", AdDecisionView.as_view(), name="decision"),
    url(r"^track/view/$", ViewTrackingView.as_view(), name="view-tracking"),
    url(r"^track/click/$", ClickTrackingView.as_view(), name="click-tracking"),
]

router = routers.SimpleRouter()
router.register(r"advertiser", AdvertiserViewSet, base_name="advertiser")
router.register(r"publisher", PublisherViewSet, base_name="publisher")
urlpatterns += router.urls
