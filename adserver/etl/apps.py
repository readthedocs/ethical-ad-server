"""App config for ad server ETL."""

from django.apps import AppConfig


class AdServerETLConfig(AppConfig):
    """App config for ad server ETL."""

    name = "adserver.etl"
    label = "adserver_etl"
    verbose_name = "Ad Server ETL"
