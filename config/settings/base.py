"""
Django settings for the Ethical Ad Server project.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""

import os
import json

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "Overridden in Production"

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
    "crispy_forms",
    "adserver",
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
]

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
SERVER_EMAIL = "info@example.com"
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
        "": {"level": "INFO", "handlers": ["console-adserver"], "propagate": False},
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

# Django Crispy Forms
# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs

CRISPY_TEMPLATE_PACK = "bootstrap4"

############################################################################
# Ad server specific settings
############################################################################

ADSERVER_ADMIN_URL = "admin"

with open(os.path.join(BASE_DIR, "package.json")) as fd:
    ADSERVER_VERSION = json.load(fd)["version"]
