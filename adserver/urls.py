"""Ad server URLs."""
from django.conf.urls import include
from django.conf.urls import url
from django.urls import path

from .views import AdClickProxyView
from .views import AdvertisementCreateView
from .views import AdvertisementDetailView
from .views import AdvertisementUpdateView
from .views import AdvertiserFlightReportView
from .views import AdvertiserMainView
from .views import AdvertiserReportView
from .views import AdViewProxyView
from .views import AllAdvertiserReportView
from .views import AllPublisherReportView
from .views import ApiTokenCreateView
from .views import ApiTokenDeleteView
from .views import ApiTokenListView
from .views import dashboard
from .views import do_not_track
from .views import do_not_track_policy
from .views import FlightDetailView
from .views import FlightListView
from .views import PublisherEmbedView
from .views import PublisherMainView
from .views import PublisherPayoutDetailView
from .views import PublisherPayoutListView
from .views import PublisherReportView
from .views import PublisherSettingsView


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
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/$",
        AdvertiserMainView.as_view(),
        name="advertiser_main",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/report/$",
        AdvertiserReportView.as_view(),
        name="advertiser_report",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/report\.csv$",
        AdvertiserReportView.as_view(export=True),
        name="advertiser_report_export",
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
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/(?P<flight_slug>[-a-zA-Z0-9_]+)/report/$",
        AdvertiserFlightReportView.as_view(),
        name="flight_report",
    ),
    url(
        r"^advertiser/(?P<advertiser_slug>[-a-zA-Z0-9_]+)/flights/(?P<flight_slug>[-a-zA-Z0-9_]+)/report\.csv$",
        AdvertiserFlightReportView.as_view(export=True),
        name="flight_report_export",
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
        r"^publisher/(?P<publisher_slug>[-a-zA-Z0-9_]+)/$",
        PublisherMainView.as_view(),
        name="publisher_main",
    ),
    url(
        r"^publisher/(?P<publisher_slug>[-a-zA-Z0-9_]+)/report/$",
        PublisherReportView.as_view(),
        name="publisher_report",
    ),
    url(
        r"^publisher/(?P<publisher_slug>[-a-zA-Z0-9_]+)/embed/$",
        PublisherEmbedView.as_view(),
        name="publisher_embed",
    ),
    url(
        r"^publisher/(?P<publisher_slug>[-a-zA-Z0-9_]+)/settings/$",
        PublisherSettingsView.as_view(),
        name="publisher_settings",
    ),
    path(
        r"publisher/<slug:publisher_slug>/payouts/",
        PublisherPayoutListView.as_view(),
        name="publisher_payouts",
    ),
    path(
        r"publisher/<slug:publisher_slug>/payouts/<uuid:pk>/",
        PublisherPayoutDetailView.as_view(),
        name="publisher_payout",
    ),
    url(
        r"^publisher/(?P<publisher_slug>[-a-zA-Z0-9_]+)/report\.csv$",
        PublisherReportView.as_view(export=True),
        name="publisher_report_export",
    ),
    # User account management
    url(r"^accounts/api-token/$", ApiTokenListView.as_view(), name="api_token_list"),
    url(
        r"^accounts/api-token/create/$",
        ApiTokenCreateView.as_view(),
        name="api_token_create",
    ),
    url(
        r"^accounts/api-token/delete/$",
        ApiTokenDeleteView.as_view(),
        name="api_token_delete",
    ),
]
