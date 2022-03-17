"""
Django settings for the Ethical Ad Server project.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.2/ref/settings/
"""
import json
import logging
import os

import environ
import stripe
from django.core.exceptions import ImproperlyConfigured

log = logging.getLogger(__name__)  # noqa

env = environ.Env()
try:
    env.read_env(env("ENV_FILE"))
except ImproperlyConfigured:
    log.info("Unable to read env file. Assuming environment is already set.")


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "Overridden in Production"  # noqa

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True
TESTING = False

ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.humanize",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "crispy_forms",
    "rest_framework",
    "rest_framework.authtoken",
    "adserver",
    "adserver.auth",
    "simple_history",
    "django_slack",
    "djstripe",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "enforce_host.EnforceHostMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "adserver.middleware.ServerInfoMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_USER_MODEL = "adserver_auth.User"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.settings_processor",
            ]
        },
    }
]

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"  # This URL has login_required

WSGI_APPLICATION = "config.wsgi.application"

SITE_ID = 1  # Required for allauth


# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases
# --------------------------------------------------------------------------
DB_PATH_SQLITE = os.path.join(BASE_DIR, "db.sqlite3")
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{DB_PATH_SQLITE}",
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

ADSERVER_OFFER_DB_TABLE = env("ADSERVER_OFFER_DB_TABLE", default=None)
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Add support for a read replica, mostly used in reporting.
DATABASE_ROUTERS = env("DATABASE_ROUTER", default=[])
if DATABASE_ROUTERS:
    REPLICA = env.db("REPLICA_DATABASE_URL", default=None)
    if not REPLICA:
        raise ImproperlyConfigured(
            "You have defined a DATABASE_ROUTER, but not a REPLICA_DATABASE_URL. Please use both."
        )
    DATABASES["replica"] = REPLICA
    REPLICA_SLUG = "replica"
else:
    # Allow us to use `Offer.objects.using(settings.REPLICA_SLUG) when we do & don't have a replica
    REPLICA_SLUG = "default"


# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Caching
# Using a local memory cache for development and testing
# and a more hardened cache in production
# See: https://docs.djangoproject.com/en/3.2/topics/cache/
# --------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}


# Sessions
# See: https://docs.djangoproject.com/en/3.2/topics/http/sessions/
# Using signed cookie sessions. No session data is stored server side,
# but sessions are tamper proof as long as the SECRET_KEY is a secret.
# --------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"


# Email
# https://docs.djangoproject.com/en/3.2/topics/email/
# In development, emails are not sent and just logged to the console
# --------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SERVER_EMAIL = "noreply@ethicalads.io"
DEFAULT_FROM_EMAIL = SERVER_EMAIL
EMAIL_TIMEOUT = 5

# For sending Front email. Only used for Payouts.
FRONT_TOKEN = env("FRONT_TOKEN", default=None)
FRONT_CHANNEL = env("FRONT_CHANNEL", default=None)
FRONT_AUTHOR = env("FRONT_AUTHOR", default=None)

# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/
# --------------------------------------------------------------------------
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "assets", "dist")]


# User-uploaded files (ad images)
# https://docs.djangoproject.com/en/3.2/topics/files/
# --------------------------------------------------------------------------
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
# Even for dev, this should be fully qualified
# This allows showing images from the ad server elsewhere more easily
MEDIA_URL = env("MEDIA_URL", default="/media/")

# Logging
# See: https://docs.djangoproject.com/en/3.2/ref/settings/#logging
# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins on every HTTP 500 error when DEBUG=False.
# See: http://docs.djangoproject.com/en/3.2/topics/logging
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "formatters": {
        "succinct": {"format": "%(levelname)-8s %(asctime)s [%(name)s] %(message)s"},
        "verbose": {
            "format": "%(levelname)-8s %(asctime)s [%(name)s] "
            "%(module)s.%(funcName)s():%(lineno)d - %(message)s"
        },
    },
    "handlers": {
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
        },
        "console-adserver": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "succinct",
        },
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        "": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "adserver": {
            "level": "INFO",
            "handlers": ["console-adserver"],
            "propagate": False,
        },
        "django": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "django.request": {
            "handlers": ["mail_admins"],
            "level": "ERROR",
            "propagate": True,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["mail_admins"],
            "propagate": True,
        },
        # Disable azure's super spammy INFO logging
        "azure": {
            "level": "WARNING",
            "handlers": ["console-adserver"],
            "propagate": False,
        },
    },
}

# Security settings
# https://docs.djangoproject.com/en/3.2/topics/security/
# https://docs.djangoproject.com/en/3.2/ref/middleware/#django.middleware.security.SecurityMiddleware
# https://docs.djangoproject.com/en/3.2/ref/clickjacking/
# These are only the settings that don't matter whether the request is HTTPS or not
# See settings/production.py for additional settings
# --------------------------------------------------------------------------
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
CSRF_COOKIE_SAMESITE = "Strict"

GEOIP_PATH = os.path.join(BASE_DIR, "geoip")


# Django Crispy Forms
# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
# --------------------------------------------------------------------------
CRISPY_TEMPLATE_PACK = "bootstrap4"


# Django allauth
# https://django-allauth.readthedocs.io
# --------------------------------------------------------------------------
ACCOUNT_ADAPTER = "adserver.auth.adapters.AdServerAccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True

# Celery settings for asynchronous tasks
# http://docs.celeryproject.org/en/latest/userguide/configuration.html
# --------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True
CELERY_DEFAULT_QUEUE = "celery"
CELERY_APP_NAME = "ethicalads"
CELERYD_TASK_TIME_LIMIT = 60 * 60  # 60 minutes
CELERY_SEND_TASK_ERROR_EMAILS = False
CELERYD_HIJACK_ROOT_LOGGER = False
CELERYD_PREFETCH_MULTIPLIER = 1
CELERY_CREATE_MISSING_QUEUES = True
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"


# Django Rest Framework (API)
# https://www.django-rest-framework.org
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "COERCE_DECIMAL_TO_STRING": False,
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "DEFAULT_PARSER_CLASSES": ("rest_framework.parsers.JSONParser",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "PAGE_SIZE": 100,
}


# Stripe
# Handle payments and invoice creation with Stripe
# https://stripe.com/docs
# https://dj-stripe.readthedocs.io/
# --------------------------------------------------------------------------
STRIPE_KEY_DEFAULT = "sk_live_x"
STRIPE_LIVE_SECRET_KEY = env("STRIPE_SECRET_KEY", default=STRIPE_KEY_DEFAULT)
STRIPE_TEST_SECRET_KEY = env("STRIPE_TEST_SECRET_KEY", default="sk_test_x")
STRIPE_CONNECT_CLIENT_ID = env("STRIPE_CONNECT_CLIENT_ID", default=None)
STRIPE_LIVE_MODE = False  # Set to True in production
DJSTRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default=None)
DJSTRIPE_FOREIGN_KEY_TO_FIELD = "id"
DJSTRIPE_USE_NATIVE_JSONFIELD = False
if not DJSTRIPE_WEBHOOK_SECRET:
    # This is less optimal than setting the webhook secret
    # However, the app won't start without the secret
    # with this setting set to the default
    DJSTRIPE_WEBHOOK_VALIDATION = "retrieve_event"

# This is a bit convoluted but basically django-stripe raises a critical
# if the key isn't set to anything. This prevents migrations from being created
# among other things.
# https://github.com/dj-stripe/dj-stripe/issues/1360
STRIPE_ENABLED = STRIPE_LIVE_SECRET_KEY != STRIPE_KEY_DEFAULT
if STRIPE_ENABLED:
    stripe.api_key = STRIPE_LIVE_SECRET_KEY
else:
    stripe.api_key = None
stripe.api_version = "2020-08-27"


# Slack
# Sending slack notifications
# By default, Slack notifications are only sent when DEBUG=False
# and when SLACK_TOKEN is set
# https://django-slack.readthedocs.io/
# --------------------------------------------------------------------------
SLACK_TOKEN = env("SLACK_TOKEN", default=None)
SLACK_CHANNEL = env("SLACK_CHANNEL", default="#ads-notifications")
SLACK_USERNAME = env("SLACK_USERNAME", default="Ethical Ad Server")
SLACK_FAIL_SILENTLY = env.bool("SLACK_FAIL_SILENTLY", default=True)


# Metabase
# Graphing and BI tool
# --------------------------------------------------------------------------
METABASE_SITE_URL = env("METABASE_SITE_URL", default="http://metabase:3000")
METABASE_SECRET_KEY = env("METABASE_SECRET_KEY", default=None)
# Maps metabase questions by name to the ID
METABASE_QUESTIONS = {
    "PUBLISHER_PERFORMANCE": 1,
    "ADVERTISER_PERFORMANCE": 2,
    "REGION_BREAKDOWN": 3,
    "ALL_ADVERTISERS_BREAKDOWN": 5,
    "TOTAL_REVENUE": 6,
}


# Plausible Analytics
# --------------------------------------------------------------------------
PLAUSIBLE_DOMAIN = env("PLAUSIBLE_DOMAIN", default="server.ethicalads.io")


# Ad server specific settings
# https://ethical-ad-server.readthedocs.io/en/latest/install/configuration.html
# --------------------------------------------------------------------------

# Anyone may use the ad server under the terms of the license.
# However, permission to use the EthicalAds brand, logo, and trademarks,
# are not conferred with the permission to use the code.
ADSERVER_ETHICALADS_BRANDING = env.bool("ADSERVER_ETHICALADS_BRANDING", default=False)

# The URL where the Django admin is served
ADSERVER_ADMIN_URL = "admin"

# The backend to be used by the ad server
# Set to `None` to disable all advertising
# This can be useful to set temporarily during migrations
ADSERVER_DECISION_BACKEND = env(
    "ADSERVER_DECISION_BACKEND",
    default="adserver.decisionengine.backends.ProbabilisticFlightBackend",
)

# Whether Do Not Track is enabled for the ad server
ADSERVER_DO_NOT_TRACK = False

ADSERVER_ANALYTICS_ID = env("ADSERVER_ANALYTICS_ID", default=None)
ADSERVER_PRIVACY_POLICY_URL = env("ADSERVER_PRIVACY_POLICY_URL", default=None)
ADSERVER_PUBLISHER_POLICY_URL = env("ADSERVER_PUBLISHER_POLICY_URL", default=None)
ADSERVER_CLICK_RATELIMITS = []
ADSERVER_VIEW_RATELIMITS = []
ADSERVER_BLOCKLISTED_USER_AGENTS = env.list(
    "ADSERVER_BLOCKLISTED_USER_AGENTS", default=[]
)
ADSERVER_BLOCKLISTED_REFERRERS = env.list("ADSERVER_BLOCKLISTED_REFERRERS", default=[])
ADSERVER_MINIMUM_PAYOUT = env.int("ADSERVER_MINIMUM_PAYOUT", default=50)
# Recording views is highly discouraged in production but useful in development
ADSERVER_RECORD_VIEWS = True
ADSERVER_HTTPS = False  # Should be True in most production setups
ADSERVER_STICKY_DECISION_DURATION = 0

# For customer support emails
ADSERVER_SUPPORT_TO_EMAIL = env("ADSERVER_SUPPORT_TO_EMAIL", default=None)
ADSERVER_SUPPORT_FORM_ACTION = env("ADSERVER_SUPPORT_FORM_ACTION", default=None)

with open(os.path.join(BASE_DIR, "package.json"), encoding="utf-8") as fd:
    ADSERVER_VERSION = json.load(fd)["version"]

# Additional middleware for setting the user's real IP
# and translating the IP into a geo for ad targeting.
ADSERVER_IPADDRESS_MIDDLEWARE = env(
    "ADSERVER_IPADDRESS_MIDDLEWARE", default="adserver.middleware.IpAddressMiddleware"
)
ADSERVER_GEOIP_MIDDLEWARE = env(
    "ADSERVER_GEOIP_MIDDLEWARE", default="adserver.middleware.GeoIpMiddleware"
)

# Add the optional middlewares if they are set
# The IP address middleware should come BEFORE the GeoIP middleware
# That way the GeoIP middleware will have access to the correct IP
if ADSERVER_IPADDRESS_MIDDLEWARE:
    MIDDLEWARE.append(ADSERVER_IPADDRESS_MIDDLEWARE)
if ADSERVER_GEOIP_MIDDLEWARE:
    MIDDLEWARE.append(ADSERVER_GEOIP_MIDDLEWARE)
