"""API Urls for the ad server"""
from django.conf.urls import url

from .views import AdDecisionView


urlpatterns = [url(r"^decision/$", AdDecisionView.as_view(), name="decision")]
