"""
Production Django settings for the Ethical Ad Server project.

This is meant to be customized by setting environment variables.
"""
import environ

from .base import *  # noqa


# Any setting without a default will raise ImproperlyConfigured on startup if not in os.environ
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),  # eg. "adserver.yourserver.com,adserver.yourserver.io"
    INTERNAL_IPS=(list, []),
    REDIS_PORT=(int, 6379),
    # User-uploaded media
    DEFAULT_FILE_STORAGE=(str, "storages.backends.azure_storage.AzureStorage"),
    MEDIA_URL=(str, ""),
    MEDIA_ROOT=(str, ""),
    # Ad server settings
    ADSERVER_HTTPS=(bool, False),
    ADSERVER_ADMIN_URL=(str, ""),
    ADSERVER_DECISION_BACKEND=(str, ADSERVER_DECISION_BACKEND),
    ADSERVER_DO_NOT_TRACK=(bool, False),
    ADSERVER_PRIVACY_POLICY_URL=(str, None),
    ADSERVER_CLICK_RATELIMITS=(list, ["1/m", "3/10m", "10/h", "25/d"]),
    ADSERVER_BLACKLISTED_USER_AGENTS=(list, []),
    ADSERVER_RECORD_VIEWS=(bool, False),
)

#
# Django Settings
# https://docs.djangoproject.com/en/1.11/ref/settings/

DEBUG = env("DEBUG")  # False if not in os.environ
TEMPLATE_DEBUG = DEBUG

DATABASES = {
    "default": env.db()  # Raises ImproperlyConfigured exception if DATABASE_URL not set
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=600)

# ALLOWED_HOSTS is required in production
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
SECRET_KEY = env("SECRET_KEY")  # Django won't start unless the SECRET_KEY is non-empty
INTERNAL_IPS = env("INTERNAL_IPS")

#
# Cache
# https://docs.djangoproject.com/en/1.11/topics/cache/
# https://niwinz.github.io/django-redis/

# Can't use REDIS_URL due to https://github.com/joke2k/django-environ/issues/200
# And requirement of rediss for SSL connections
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "{protocol}://{host}:{port}/0".format(
            protocol="rediss" if int(env("REDIS_PORT")) == 6380 else "redis",
            host=env("REDIS_HOST"),
            port=env("REDIS_PORT"),
        ),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": env("REDIS_PASSWORD"),
            "IGNORE_EXCEPTIONS": True,
            "SOCKET_CONNECT_TIMEOUT": 5,  # in seconds
            "SOCKET_TIMEOUT": 5,  # in seconds
        },
    }
}

#
# Security
# See: https://docs.djangoproject.com/en/1.11/topics/security/
# See: https://docs.djangoproject.com/en/1.11/ref/middleware/#django.middleware.security.SecurityMiddleware
# See: https://docs.djangoproject.com/en/1.11/ref/clickjacking/

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if env("ADSERVER_HTTPS"):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365 * 10
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

#
# Email settings
# See: https://anymail.readthedocs.io

INSTALLED_APPS += ["anymail"]
EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
ANYMAIL = {"MAILGUN_API_KEY": env("MAILGUN_API_KEY")}

#
# User upload storage
# https://docs.djangoproject.com/en/1.11/topics/files/
# https://django-storages.readthedocs.io/en/latest/backends/azure.html
DEFAULT_FILE_STORAGE = env("DEFAULT_FILE_STORAGE")
MEDIA_ROOT = env("MEDIA_ROOT")
MEDIA_URL = env("MEDIA_URL")
AZURE_ACCOUNT_NAME = env("AZURE_ACCOUNT_NAME", default="")
AZURE_ACCOUNT_KEY = env("AZURE_ACCOUNT_KEY", default="")
AZURE_CONTAINER = env("AZURE_CONTAINER", default="")

#
# Ad server settings

ADSERVER_ADMIN_URL = env("ADSERVER_ADMIN_URL")
ADSERVER_DO_NOT_TRACK = env("ADSERVER_DO_NOT_TRACK")
ADSERVER_PRIVACY_POLICY_URL = env("ADSERVER_PRIVACY_POLICY_URL")
ADSERVER_DECISION_BACKEND = env("ADSERVER_DECISION_BACKEND")
ADSERVER_RECORD_VIEWS = env("ADSERVER_RECORD_VIEWS")
