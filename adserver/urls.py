"""Ad server URLs."""
from django.conf.urls import include
from django.conf.urls import url

from .views import AdClickProxyView
from .views import AdvertiserReportView
from .views import AdViewProxyView
from .views import AllAdvertiserReportView
from .views import AllPublisherReportView
from .views import dashboard
from .views import do_not_track
from .views import do_not_track_policy
from .views import PublisherReportView


urlpatterns = [
    url("^$", dashboard, name="dashboard-home"),
    # Do not Track
    url(r"^\.well-known/dnt/$", do_not_track, name="dnt-status"),
    url(r"^\.well-known/dnt-policy.txt$", do_not_track_policy, name="dnt-policy"),
    # Ad API
    url(r"^api/v1/", include("adserver.api.urls", namespace="api")),
    # View & Click proxies
    url(
        r"^proxy/view/(?P<advertisement_id>\d+)/(?P<nonce>\w+)/$",
        AdViewProxyView.as_view(),
        name="view-proxy",
    ),
    url(
        r"^proxy/click/(?P<advertisement_id>\d+)/(?P<nonce>\w+)/$",
        AdClickProxyView.as_view(),
        name="click-proxy",
    ),
    # Advertiser and publisher reports
    url(
        r"^advertiser/all/report/$",
        AllAdvertiserReportView.as_view(),
        name="all_advertisers_report",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/report/$",
        AdvertiserReportView.as_view(),
        name="advertiser_report",
    ),
    url(
        r"^publisher/all/report/$",
        AllPublisherReportView.as_view(),
        name="all_publishers_report",
    ),
    url(
        r"^publisher/(?P<publisher_slug>[-a-zA-Z0-9_]+)/report/$",
        PublisherReportView.as_view(),
        name="publisher_report",
    ),
]
