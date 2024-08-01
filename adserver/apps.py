"""Ad server Django app settings."""

from django.apps import AppConfig


class AdserverConfig(AppConfig):
    name = "adserver"
    verbose_name = "Ad Server Core"

    def ready(self):
        import adserver.tasks  # noqa
        import adserver.hooks  # noqa
