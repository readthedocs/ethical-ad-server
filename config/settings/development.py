from .base import *  # noqa


INTERNAL_IPS = ("127.0.0.1", "10.0.2.2")

# django-debug-toolbar
# https://django-debug-toolbar.readthedocs.io
# --------------------------------------------------------------------------
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
INSTALLED_APPS += ["debug_toolbar"]
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": ["debug_toolbar.panels.redirects.RedirectsPanel"],
    "SHOW_TEMPLATE_CONTEXT": True,
}

LOGGING["loggers"]["adserver"]["level"] = "DEBUG"
