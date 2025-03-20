"""Ethical Ad Server URL Configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import RedirectView


urlpatterns = []

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    from allauth.core.ratelimit import _handler429 as handle_429  # noqa

    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("429/", handle_429),
        path("500/", default_views.server_error),
    ]

    # We can't use `settings.MEDIA_URL` as the pattern since MEDIA_URL may be fully qualified
    urlpatterns += static("/media/", document_root=settings.MEDIA_ROOT)

    # Enable Django Debug Toolbar in development
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path(r"__debug__/", include(debug_toolbar.urls))] + urlpatterns

if settings.ADSERVER_ADMIN_URL:
    # In development, the Django admin is available at /admin
    # In production, a custom URL path can be specified
    # If no ADSERVER_ADMIN_URL is specified, the Django admin is disabled
    urlpatterns += [path(f"{settings.ADSERVER_ADMIN_URL}/", admin.site.urls)]

if "ethicalads_ext.support" in settings.INSTALLED_APPS:
    urlpatterns += [
        path(r"support/", include("ethicalads_ext.support.urls")),
    ]

if "ethicalads_ext.etl" in settings.INSTALLED_APPS:
    urlpatterns += [
        path(r"etl/", include("ethicalads_ext.etl.urls")),
    ]

urlpatterns += [
    # Allauth overrides
    # Disable managing emails for now
    path(
        r"accounts/email/",
        RedirectView.as_view(pattern_name="dashboard-home", permanent=False),
    ),
    path(r"accounts/", include("allauth.urls")),
    path(r"stripe/", include("djstripe.urls", namespace="djstripe")),
    path(r"", include("adserver.urls")),
]
