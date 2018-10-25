"""Ad server URLs"""
from django.conf.urls import include
from django.conf.urls import url

from .views import dashboard
from .views import do_not_track
from .views import do_not_track_policy
from .views import proxy_ad_click
from .views import proxy_ad_view


urlpatterns = [
    url("^$", dashboard, name="dashboard-home"),
    # Do not Track
    url(r"^\.well-known/dnt/$", do_not_track, name="dnt-status"),
    url(r"^\.well-known/dnt-policy.txt$", do_not_track_policy, name="dnt-policy"),
    # Ad endpoints
    url(
        r"^proxy/view/(?P<ad_id>\d+)/(?P<nonce>[a-zA-Z0-9]+)/$",
        proxy_ad_view,
        name="proxy-ad-view",
    ),
    url(
        r"^proxy/click/(?P<ad_id>\d+)/(?P<nonce>[a-zA-Z0-9]+)/$",
        proxy_ad_click,
        name="proxy-ad-click",
    ),
    # Ad API
    url(r"^api/v1/", include("adserver.api.urls", namespace="api")),
]
