"""App config for ad server auth."""

from django.apps import AppConfig


class AdServerAuthConfig(AppConfig):
    name = "adserver.auth"
    label = "adserver_auth"
    verbose_name = "Ad Server Auth"
