"""Ad server URLs."""
from django.urls import include
from django.urls import path
from django.views.generic import TemplateView

from .views import AdClickProxyView
from .views import AdvertisementCreateView
from .views import AdvertisementDetailView
from .views import AdvertisementUpdateView
from .views import AdvertiserFlightReportView
from .views import AdvertiserGeoReportView
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
from .views import publisher_stripe_oauth_return
from .views import PublisherAdvertiserReportView
from .views import PublisherEmbedView
from .views import PublisherGeoReportView
from .views import PublisherKeywordReportView
from .views import PublisherMainView
from .views import PublisherPayoutDetailView
from .views import PublisherPayoutListView
from .views import PublisherPlacementReportView
from .views import PublisherReportView
from .views import PublisherSettingsView
from .views import PublisherStripeOauthConnectView


urlpatterns = [
    path("", dashboard, name="dashboard-home"),
    # Robots.txt
    path(
        r"robots.txt",
        TemplateView.as_view(
            template_name="adserver/robots.txt", content_type="text/plain"
        ),
        name="robots_text",
    ),
    # Do not Track
    path(r".well-known/dnt/", do_not_track, name="dnt-status"),
    path(r".well-known/dnt-policy.txt", do_not_track_policy, name="dnt-policy"),
    # Ad API
    path(r"api/v1/", include("adserver.api.urls")),
    # View & Click proxies
    path(
        r"proxy/view/<int:advertisement_id>/<str:nonce>/",
        AdViewProxyView.as_view(),
        name="view-proxy",
    ),
    path(
        r"proxy/click/<int:advertisement_id>/<str:nonce>/",
        AdClickProxyView.as_view(),
        name="click-proxy",
    ),
    # Advertiser management and reporting
    path(
        r"advertiser/all/report/",
        AllAdvertiserReportView.as_view(),
        name="all_advertisers_report",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/",
        AdvertiserMainView.as_view(),
        name="advertiser_main",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/report/",
        AdvertiserReportView.as_view(),
        name="advertiser_report",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/report.csv",
        AdvertiserReportView.as_view(export=True),
        name="advertiser_report_export",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/report/geos/",
        AdvertiserGeoReportView.as_view(),
        name="advertiser_geo_report",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/report/geos.csv",
        AdvertiserGeoReportView.as_view(export=True),
        name="advertiser_geo_report_export",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/",
        FlightListView.as_view(),
        name="flight_list",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/<slug:flight_slug>/",
        FlightDetailView.as_view(),
        name="flight_detail",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/<slug:flight_slug>/report/",
        AdvertiserFlightReportView.as_view(),
        name="flight_report",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/<slug:flight_slug>/report.csv",
        AdvertiserFlightReportView.as_view(export=True),
        name="flight_report_export",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/<slug:flight_slug>/advertisements/create/",
        AdvertisementCreateView.as_view(),
        name="advertisement_create",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/<slug:flight_slug>/advertisements/<slug:advertisement_slug>/",
        AdvertisementDetailView.as_view(),
        name="advertisement_detail",
    ),
    path(
        r"advertiser/<slug:advertiser_slug>/flights/<slug:flight_slug>/advertisements/<slug:advertisement_slug>/update/",
        AdvertisementUpdateView.as_view(),
        name="advertisement_update",
    ),
    # Publisher management and reporting
    path(
        r"publisher/all/report/",
        AllPublisherReportView.as_view(),
        name="all_publishers_report",
    ),
    path(
        r"publisher/<slug:publisher_slug>/",
        PublisherMainView.as_view(),
        name="publisher_main",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/",
        PublisherReportView.as_view(),
        name="publisher_report",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report.csv",
        PublisherReportView.as_view(export=True),
        name="publisher_report_export",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/placements/",
        PublisherPlacementReportView.as_view(),
        name="publisher_placement_report",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/placements.csv",
        PublisherPlacementReportView.as_view(export=True),
        name="publisher_placement_report_export",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/geos/",
        PublisherGeoReportView.as_view(),
        name="publisher_geo_report",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/geos.csv",
        PublisherGeoReportView.as_view(export=True),
        name="publisher_geo_report_export",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/advertisers/",
        PublisherAdvertiserReportView.as_view(),
        name="publisher_advertiser_report",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/advertisers.csv",
        PublisherAdvertiserReportView.as_view(export=True),
        name="publisher_advertiser_report_export",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/keywords/",
        PublisherKeywordReportView.as_view(),
        name="publisher_keyword_report",
    ),
    path(
        r"publisher/<slug:publisher_slug>/report/keywords.csv",
        PublisherKeywordReportView.as_view(export=True),
        name="publisher_keyword_report_export",
    ),
    path(
        r"publisher/<slug:publisher_slug>/embed/",
        PublisherEmbedView.as_view(),
        name="publisher_embed",
    ),
    path(
        r"publisher/<slug:publisher_slug>/oauth/stripe/connect/",
        PublisherStripeOauthConnectView.as_view(),
        name="publisher_stripe_oauth_connect",
    ),
    path(
        r"publisher/oauth/stripe/return/",
        publisher_stripe_oauth_return,
        name="publisher_stripe_oauth_return",
    ),
    path(
        r"publisher/<slug:publisher_slug>/settings/",
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
    # User account management
    path(r"accounts/api-token/", ApiTokenListView.as_view(), name="api_token_list"),
    path(
        r"accounts/api-token/create/",
        ApiTokenCreateView.as_view(),
        name="api_token_create",
    ),
    path(
        r"accounts/api-token/delete/",
        ApiTokenDeleteView.as_view(),
        name="api_token_delete",
    ),
]
