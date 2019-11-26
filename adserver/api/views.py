"""APIs for the ad server."""
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from ..decisionengine import get_ad_decision_backend
from ..models import Advertisement
from ..models import Advertiser
from ..models import Publisher
from ..utils import parse_date_string
from .mixins import GeoIpMixin
from .permissions import PublisherPermission
from .serializers import AdDecisionSerializer
from .serializers import AdvertiserSerializer
from .serializers import PublisherSerializer


log = logging.getLogger(__name__)  # noqa


class AdDecisionView(GeoIpMixin, APIView):

    """
    Make a decision on an `Advertisement` to show.

    The ad decision is based on

    * the publisher (ad campaigns may be publisher specific)
    * the available placements (ad types and priorities)
    * minimal user agent details (browser, mobile, operating system)
    * geography (based on IP)
    * keywords

    .. http:post:: /api/v1/decision/

        :param string publisher: **Required**. The slug of the publisher
        :param array placements: **Required**. Various possible ad placements where an ad could go
        :param array keywords: Case-insensitive strings that describe the page where the ad will go for targeting
        :param array campaign_types: Limit the ad results to certain campaign types
        :param string user_ip: User's IP address used for targeting
            (the requestor's IP will be used if not present)
        :param string user_ua: User's user agent used for targeting
            (the requestor's UA will be used if not present)
        :param string force_ad: Limit results to a specific ad
        :param string force_campaign: Limit results to ads from a specific campaign
    """

    permission_classes = (PublisherPermission,)

    def _prepare_response(self, ad, placement, publisher):
        """Wrap `offer_ad` with the placement for the publisher."""
        if not ad or not placement:
            return {}

        data = ad.offer_ad(publisher)
        data.update({"div_id": placement["div_id"]})
        return data

    def post(self, request):
        """
        Decision API called via POST.

        Used for server to server ad requests.

        Depending on the configuration of authentication classes and middleware,
        CSRF protection on POST requests may be enabled.
        See: http://www.django-rest-framework.org/topics/ajax-csrf-cors/#csrf-protection
        """
        return self.decision(request, request.data)

    def decision(self, request, data):
        """
        Makes a decision on what add to display based on info.

        :param request: the HTTP request
        :param data: data needed for the decision (query params, post data, etc.)
        :return: An add decision (JSON) or an empty JSON dict
        """
        serializer = AdDecisionSerializer(data=data)

        if serializer.is_valid():
            publisher = serializer.validated_data["publisher"]
            self.check_object_permissions(request, publisher)
            backend = get_ad_decision_backend()(
                # Required parameters
                request=request,
                placements=serializer.validated_data["placements"],
                publisher=publisher,
                # Optional parameters
                keywords=serializer.validated_data.get("keywords"),
                campaign_types=serializer.validated_data.get("campaign_types"),
                # Debugging parameters
                ad_slug=serializer.validated_data.get("force_ad"),
                campaign_slug=serializer.validated_data.get("force_campaign"),
            )
            ad, placement = backend.get_ad_and_placement()

            return Response(self._prepare_response(ad, placement, publisher))

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdvertiserViewSet(viewsets.ReadOnlyModelViewSet):

    """
    Advertiser API calls.

    .. http:get:: /api/v1/advertisers/

        Return a list of advertisers the user has access to

    .. http:get:: /api/v1/advertisers/(str:slug)/

        Return a specific advertiser

    .. http:get:: /api/v1/advertisers/(str:slug)/report/

        Return a report of ad performance for this advertiser

        :query date start_date: Start the report on a given day inclusive.
            If not specified, defaults to 30 days ago
        :query date end_date: End the report on a given day inclusive.
            If not specified, no end time is used (up to current)
    """

    serializer_class = AdvertiserSerializer
    lookup_field = "slug"

    def get_queryset(self):
        """Returns Advertisers the user has access to."""
        if self.request.user.is_staff:
            return Advertiser.objects.all()

        return self.request.user.advertisers.all()

    @action(detail=True, methods=["get"])
    def report(self, request, slug=None):
        """Return a report of ad performance for this advertiser."""
        # This will raise a 404 if the user doesn't have access to the advertiser
        advertiser = self.get_object()
        start_date = parse_date_string(request.query_params.get("start_date"))
        end_date = parse_date_string(request.query_params.get("end_date"))

        if not start_date:
            start_date = timezone.now() - timedelta(days=30)

        data = advertiser.daily_reports(start_date=start_date, end_date=end_date)

        # Add the daily performance of all ads within the timeframe
        data["advertisements"] = []
        for ad in Advertisement.objects.filter(flight__campaign__advertiser=advertiser):
            report = ad.daily_reports(start_date=start_date, end_date=end_date)
            if report["total"]["views"]:
                ad_data = AdvertisementSerializer(ad).data
                ad_data["report"] = report
                data["advertisements"].append(ad_data)

        return Response(data)


class PublisherViewSet(viewsets.ReadOnlyModelViewSet):

    """
    Publisher API calls.

    .. http:get:: /api/v1/publishers/

        Return a list of publishers the user has access to

    .. http:get:: /api/v1/publishers/(str:slug)/

        Return a specific publisher

    .. http:get:: /api/v1/publishers/(str:slug)/report/

        Return a report of ad performance for this publisher

        :query date start_date: Start the report on a given day inclusive.
            If not specified, defaults to 30 days ago
        :query date end_date: End the report on a given day inclusive.
            If not specified, no end time is used (up to current)
    """

    serializer_class = PublisherSerializer
    lookup_field = "slug"

    def get_queryset(self):
        """Returns Publishers the user has access to."""
        if self.request.user.is_staff:
            return Publisher.objects.all()

        return self.request.user.publishers.all()

    @action(detail=True, methods=["get"])
    def report(self, request, slug=None):
        """Return a report of ad performance for this publisher."""
        # This will raise a 404 if the user doesn't have access to the publisher
        publisher = self.get_object()
        start_date = parse_date_string(request.query_params.get("start_date"))
        end_date = parse_date_string(request.query_params.get("end_date"))

        if not start_date:
            start_date = timezone.now() - timedelta(days=30)

        return Response(
            publisher.daily_reports(start_date=start_date, end_date=end_date)
        )
