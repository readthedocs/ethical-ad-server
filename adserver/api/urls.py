"""API Urls for the ad server."""
from django.conf.urls import url
from rest_framework import routers

from .views import AdDecisionView
from .views import AdvertiserViewSet
from .views import PublisherViewSet


urlpatterns = [url(r"^decision/$", AdDecisionView.as_view(), name="decision")]

router = routers.SimpleRouter()
router.register(r"advertisers", AdvertiserViewSet, base_name="advertisers")
router.register(r"publishers", PublisherViewSet, base_name="publishers")
urlpatterns += router.urls
