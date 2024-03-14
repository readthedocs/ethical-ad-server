"""API Urls for the ad server."""
from django.conf import settings
from django.urls import path
from rest_framework import routers

from .views import AdDecisionView
from .views import AdvertiserViewSet
from .views import PublisherViewSet


app_name = "api"

urlpatterns = [path(r"decision/", AdDecisionView.as_view(), name="decision")]

router = routers.SimpleRouter()
router.register(r"advertisers", AdvertiserViewSet, basename="advertisers")
router.register(r"publishers", PublisherViewSet, basename="publishers")

if "ethicalads_ext.embedding" in settings.INSTALLED_APPS:
    from ethicalads_ext.embedding.views import EmbeddingViewSet

    urlpatterns += [path(r"similar/", EmbeddingViewSet.as_view(), name="similar")]


urlpatterns += router.urls
