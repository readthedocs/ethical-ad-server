"""Ad server URLs."""
from django.conf.urls import include
from django.conf.urls import url

from .views import AdClickProxyView
from .views import AdvertisementCreateView
from .views import AdvertisementDetailView
from .views import AdvertisementUpdateView
from .views import AdvertiserReportView
from .views import AdViewProxyView
from .views import AllAdvertiserReportView
from .views import AllPublisherReportView
from .views import dashboard
from .views import do_not_track
from .views import do_not_track_policy
from .views import FlightDetailView
from .views import FlightListView
from .views import PublisherReportView


urlpatterns = [
    url("^$", dashboard, name="dashboard-home"),
    # Do not Track
    url(r"^\.well-known/dnt/$", do_not_track, name="dnt-status"),
    url(r"^\.well-known/dnt-policy.txt$", do_not_track_policy, name="dnt-policy"),
    # Ad API
    url(r"^api/v1/", include("adserver.api.urls")),
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
    # Advertiser management and reporting
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
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/$",
        FlightListView.as_view(),
        name="flight_list",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/(?P<flight_slug>[-a-zA-Z0-9_]+)/$",
        FlightDetailView.as_view(),
        name="flight_detail",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/(?P<flight_slug>[-a-zA-Z0-9_]+)/advertisements/create/$",
        AdvertisementCreateView.as_view(),
        name="advertisement_create",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/(?P<flight_slug>[-a-zA-Z0-9_]+)/advertisements/(?P<advertisement_slug>[-a-zA-Z0-9_]+)/$",
        AdvertisementDetailView.as_view(),
        name="advertisement_detail",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/(?P<flight_slug>[-a-zA-Z0-9_]+)/advertisements/(?P<advertisement_slug>[-a-zA-Z0-9_]+)/update/$",
        AdvertisementUpdateView.as_view(),
        name="advertisement_update",
    ),
    # Publisher management and reporting
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
