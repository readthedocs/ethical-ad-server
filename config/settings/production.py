import environ

from .base import *  # noqa


# Any setting without a default will raise ImproperlyConfigured on startup if not in os.environ
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),  # eg. "adserver.yourserver.com,adserver.yourserver.io"
    INTERNAL_IPS=(list, []),
    # Ad server settings
    ADSERVER_HTTPS=(bool, False),
    ADSERVER_ADMIN_URL=(str, ""),
    ADSERVER_DO_NOT_TRACK=(bool, False),
    ADSERVER_PRIVACY_POLICY_URL=(str, None),
)

#
# Django Settings
# https://docs.djangoproject.com/en/1.11/ref/settings/

DEBUG = env("DEBUG")  # False if not in os.environ
TEMPLATE_DEBUG = DEBUG

DATABASES = {
    "default": env.db()  # Raises ImproperlyConfigured exception if DATABASE_URL not set
}

# ALLOWED_HOSTS is required in production
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
SECRET_KEY = env("SECRET_KEY")  # Django won't start unless the SECRET_KEY is non-empty
INTERNAL_IPS = env("INTERNAL_IPS")

#
# Security
# See: https://docs.djangoproject.com/en/1.11/ref/middleware/#django.middleware.security.SecurityMiddleware

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

if env("ADSERVER_HTTPS"):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365 * 10
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

#
# Ad server settings

ADSERVER_ADMIN_URL = env("ADSERVER_ADMIN_URL")
ADSERVER_DO_NOT_TRACK = env("ADSERVER_DO_NOT_TRACK")
ADSERVER_PRIVACY_POLICY_URL = env("ADSERVER_PRIVACY_POLICY_URL")
