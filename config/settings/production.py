"""
Production Django settings for the Ethical Ad Server project.

This is meant to be customized by setting environment variables.

Only a few environment variables are required:

- SECRET_KEY
- ALLOWED_HOSTS
- REDIS_URL
- DATABASE_URL
- SENDGRID_API_KEY
"""
import logging
import ssl

from celery.schedules import crontab

from .base import *  # noqa
from .base import env


# Django Settings
# https://docs.djangoproject.com/en/2.2/ref/settings/
# --------------------------------------------------------------------------
DEBUG = False
TEMPLATE_DEBUG = DEBUG

# ALLOWED_HOSTS is required in production
# eg. "adserver.yourserver.com,adserver.yourserver.io"
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
SECRET_KEY = env("SECRET_KEY")  # Django won't start unless the SECRET_KEY is non-empty
INTERNAL_IPS = env.list("INTERNAL_IPS", default=[])


# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases
# --------------------------------------------------------------------------
DATABASES = {
    "default": env.db()  # Raises ImproperlyConfigured exception if DATABASE_URL not set
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=3600)


# Cache
# https://docs.djangoproject.com/en/2.2/topics/cache/
# https://niwinz.github.io/django-redis/
# --------------------------------------------------------------------------
CACHES = {"default": env.cache("REDIS_URL")}

# Secure connection workaround
# https://github.com/joke2k/django-environ/pull/211
if env.bool("REDIS_SSL", default=False):
    CACHES["default"]["LOCATION"] = CACHES["default"]["LOCATION"].replace(
        "redis://", "rediss://"
    )


# Security
# https://docs.djangoproject.com/en/2.2/topics/security/
# https://docs.djangoproject.com/en/2.2/ref/middleware/#django.middleware.security.SecurityMiddleware
# https://docs.djangoproject.com/en/2.2/ref/clickjacking/
# --------------------------------------------------------------------------
if env.bool("ADSERVER_HTTPS", default=False):
    ADSERVER_HTTPS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year is recommended: 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Redirect HTTP -> HTTPS
    # https://devcenter.heroku.com/articles/http-routing#heroku-headers
    # Optionally enforce a specific host. Other hosts will redirect
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    ENFORCE_HOST = env("ENFORCE_HOST", default=None)


# Email settings
# See: https://anymail.readthedocs.io
# --------------------------------------------------------------------------
INSTALLED_APPS += ["anymail"]
EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
ANYMAIL = {"SENDGRID_API_KEY": env("SENDGRID_API_KEY")}


# User upload storage
# https://docs.djangoproject.com/en/2.2/topics/files/
# https://django-storages.readthedocs.io/en/latest/backends/azure.html
DEFAULT_FILE_STORAGE = env(
    "DEFAULT_FILE_STORAGE", default="storages.backends.azure_storage.AzureStorage"
)
MEDIA_URL = env("MEDIA_URL", default="")
MEDIA_ROOT = env("MEDIA_ROOT", default="")
DEFAULT_FILE_STORAGE_HOSTNAME = env("DEFAULT_FILE_STORAGE_HOSTNAME", default=None)
AZURE_ACCOUNT_NAME = env("AZURE_ACCOUNT_NAME", default="")
AZURE_ACCOUNT_KEY = env("AZURE_ACCOUNT_KEY", default="")
AZURE_CONTAINER = env("AZURE_CONTAINER", default="")


# Celery settings for asynchronous tasks
# http://docs.celeryproject.org
# --------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=env("REDIS_URL"))
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

if env.bool("REDIS_SSL", default=False):
    CELERY_BROKER_URL = CELERY_BROKER_URL.replace("redis://", "rediss://")
    CELERY_RESULT_BACKEND = CELERY_BROKER_URL
    CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_REQUIRED}

CELERY_BEAT_SCHEDULE = {
    "every-hour-generate-geo-index": {
        "task": "adserver.tasks.daily_update_geos",
        "schedule": crontab(minute="15"),
    },
    "every-hour-generate-placement-index": {
        "task": "adserver.tasks.daily_update_placements",
        "schedule": crontab(minute="45"),
    },
    # TODO: Make this run nightly on the previous days data
    "every-hour-generate-keyword-index": {
        "task": "adserver.tasks.daily_update_keywords",
        "schedule": crontab(hour="23", minute="58"),
    },
}


# Sentry settings for error monitoring
# https://docs.sentry.io/platforms/python/django/
# --------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default=None)
if SENTRY_DSN:
    # pylint: disable=import-error
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_logging = LoggingIntegration(
        event_level=logging.WARNING  # Send warnings as events
    )

    sentry_sdk.init(dsn=SENTRY_DSN, integrations=[sentry_logging, DjangoIntegration()])


# Production ad server specific settings
# https://ethical-ad-server.readthedocs.io/en/latest/install/configuration.html
# --------------------------------------------------------------------------
ADSERVER_ADMIN_URL = env("ADSERVER_ADMIN_URL", default="admin")
ADSERVER_DO_NOT_TRACK = env.bool("ADSERVER_DO_NOT_TRACK", default=False)
ADSERVER_RECORD_VIEWS = env.bool("ADSERVER_RECORD_VIEWS", default=False)
ADSERVER_CLICK_RATELIMITS = env.list(
    "ADSERVER_CLICK_RATELIMITS", default=["1/m", "3/10m", "10/h", "25/d"]
)
ADSERVER_VIEW_RATELIMITS = env.list("ADSERVER_VIEW_RATELIMITS", default=["5/5m"])

# GeoIP settings
# This directory should be the path to GeoLite2-City.mmdb and GeoLite2-Country.mmdb
GEOIP_PATH = env("GEOIP_GEOLITE2_PATH", default=GEOIP_PATH)
GEOIP_CITY = env("GEOIP_GEOLITE2_CITY_FILENAME", default="GeoLite2-City.mmdb")
GEOIP_COUNTRY = env("GEOIP_GEOLITE2_COUNTRY_FILENAME", default="GeoLite2-Country.mmdb")
