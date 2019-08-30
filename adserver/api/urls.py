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
router.register(r"advertisers", AdvertiserViewSet, base_name="advertisers")
router.register(r"publishers", PublisherViewSet, base_name="publishers")
urlpatterns += router.urls
