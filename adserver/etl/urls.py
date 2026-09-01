"""Urls for the ETL and audience estimation interface."""

from django.urls import path

from .views import AudienceEstimatorView


urlpatterns = [
    path(
        r"audience-estimator/",
        AudienceEstimatorView.as_view(),
        name="etl-staff-audience-estimator",
    ),
]
