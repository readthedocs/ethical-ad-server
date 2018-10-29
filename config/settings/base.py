"""
Django settings for the Ethical Ad Server project.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""
import json
import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "Overridden in Production"  # noqa

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "crispy_forms",
    "rest_framework",
    "adserver",
    "adserver.auth",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "adserver.middleware.RealIPAddressMiddleware",
    "adserver.middleware.GeolocationMiddleware",
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
            ]
        },
    }
]

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"  # This URL has login_required

WSGI_APPLICATION = "config.wsgi.application"

SITE_ID = 1  # Required for allauth

# Database
# https://docs.djangoproject.com/en/1.11/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

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
# See: https://docs.djangoproject.com/en/1.11/topics/cache/

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}

# Sessions
# See: https://docs.djangoproject.com/en/1.11/topics/http/sessions/
# Using signed cookie sessions. No session data is stored server side,
# but sessions are tamper proof as long as the SECRET_KEY is a secret.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

# Email
# https://docs.djangoproject.com/en/1.11/topics/email/
# In development, emails are not sent and just logged to the console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SERVER_EMAIL = "noreply@ethicalads.io"
DEFAULT_FROM_EMAIL = SERVER_EMAIL
EMAIL_TIMEOUT = 5

# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATIC_URL = "/static/"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "assets", "dist")]

# Logging
# See: https://docs.djangoproject.com/en/1.11/ref/settings/#logging
# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins on every HTTP 500 error when DEBUG=False.
# See: http://docs.djangoproject.com/en/1.11/topics/logging
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
    },
}

GEOIP_PATH = os.path.join(BASE_DIR, "geoip")

# Django Crispy Forms
# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs

CRISPY_TEMPLATE_PACK = "bootstrap4"

# Django allauth
# https://django-allauth.readthedocs.io

ACCOUNT_ADAPTER = "adserver.auth.adapters.AdServerAccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"

############################################################################
# Ad server specific settings
############################################################################

# The URL where the Django admin is served
ADSERVER_ADMIN_URL = "admin"

# The backend to be used by the ad server
# Set to `None` to disable all advertising
# This can be useful to set temporarily during migrations
ADSERVER_DECISION_BACKEND = (
    "adserver.decisionengine.backends.ProbabilisticClicksNeededBackend"
)  # noqa

# Whether Do Not Track is enabled for the ad server
ADSERVER_DO_NOT_TRACK = False

ADSERVER_PRIVACY_POLICY_URL = None
ADSERVER_CLICK_RATELIMITS = []
ADSERVER_BLACKLISTED_USER_AGENTS = []
ADSERVER_RECORD_VIEWS = True  # False in prod by default

with open(os.path.join(BASE_DIR, "package.json")) as fd:
    ADSERVER_VERSION = json.load(fd)["version"]
