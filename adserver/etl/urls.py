"""Urls for the ETL and audience estimation interface."""

from django.urls import path

from .views import AudienceEstimatorView
from .views import DailyOffersDumpHealthView
from .views import MonthlyOffersDumpHealthView


urlpatterns = [
    path(
        r"audience-estimator/",
        AudienceEstimatorView.as_view(),
        name="etl-staff-audience-estimator",
    ),
    path(
        r"health/daily-offers-dump/",
        DailyOffersDumpHealthView.as_view(),
        name="health-daily-offers-dump",
    ),
    path(
        r"health/monthly-offers-dump/",
        MonthlyOffersDumpHealthView.as_view(),
        name="health-monthly-offers-dump",
    ),
]
