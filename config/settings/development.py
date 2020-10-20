"""Development settings."""
from celery.schedules import crontab

from .base import *  # noqa
from .base import env

# Allow to use weak passwords for development
AUTH_PASSWORD_VALIDATORS = []

# Set the local IPs which are needed for Django Debug Toolbar
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
if env.bool("USE_DOCKER", default=False):
    import socket

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS += [ip[:-1] + "1" for ip in ips]


# django-debug-toolbar
# https://django-debug-toolbar.readthedocs.io
# --------------------------------------------------------------------------
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
INSTALLED_APPS += ["debug_toolbar", "django_extensions"]
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": ["debug_toolbar.panels.redirects.RedirectsPanel"],
    "SHOW_TEMPLATE_CONTEXT": True,
}

LOGGING["loggers"]["adserver"]["level"] = "DEBUG"


# Celery settings for asynchronous tasks
# http://docs.celeryproject.org
# --------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=env("REDIS_URL", default=None))
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

CELERYBEAT_SCHEDULE = {
    "every-day-generate-geo-index": {
        "task": "adserver.tasks.daily_update_geos",
        "schedule": crontab(minute="*/5"),
    },
}
