"""APIs for the ad server."""
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_jsonp.renderers import JSONPRenderer

from ..constants import DECISIONS
from ..decisionengine import get_ad_decision_backend
from ..models import AdImpression
from ..models import Advertisement
from ..models import Advertiser
from ..models import Flight
from ..models import Publisher
from ..reports import AdvertiserReport
from ..reports import PublisherReport
from ..utils import parse_date_string
from .mixins import GeoIpMixin
from .permissions import AdDecisionPermission
from .serializers import AdDecisionSerializer
from .serializers import AdvertisementSerializer
from .serializers import AdvertiserSerializer
from .serializers import FlightSerializer
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

    .. http:get:: /api/v1/decision/

        Request an advertisement for a specific publisher.

        The publisher must be explicitly permitted to allow unauthenticated requests.
        This is typically used as a JSONP call.

        :<json string publisher: **Required**. The slug of the publisher.
            If using the ethical-ad-client, this comes from ``data-ea-publisher``.
        :<json string div_ids: A ``|`` delimited string of on-page ids.
            The number and order must correspond to the ``ad_types``
        :<json string ad_types: A ``|`` delimited string of ad types.
            The number and order must correspond to the ``div_ids``.
        :<json string priorities: An optional ``|`` delimited string of priorities for different ad types.
            The number and order matter, applying to ``div_ids`` and ``ad_types``.
        :<json array keywords: An optional ``|`` delimited string of case-insensitive keywords
            that describe content on the page where the ad is requested (eg. ``python|docker|kubernetes``).
            Used for ad targeting and is additive with any publisher settings.
        :<json array campaign_types: An optional ``|`` delimited string of campaign types (eg. ``paid|community|house``)
            which can be used to limit to just certain types of ads.
            Can only further reduce campaign types, not allow ones prohibited for the publisher.
        :<json string format: Format can optionally be specified as ``jsonp`` to allow a callback.
        :<json string callback: The name of the callback for a JSONP request (default is ``callback``)
        :<json string force_ad: Limit results to a specific ad
        :<json string force_campaign: Limit results to ads from a specific campaign

        :>json string id: The advertisement slug of the chosen ad
        :>json string text: The HTML text of only the ad without any images (see ``html`` for full HTML)
        :>json string body: The text of the ad, stripped of any HTML.
        :>json string html: An HTML rendering of the ad
        :>json string link: A click URL for the ad
        :>json string view_url: A view URL to count an ad view
        :>json string nonce: A one-time nonce used in the URLs so the ad is never double counted
        :>json string display_type: The slug of type of ad (eg. sidebar)
        :>json string div_id: The <div> ID where the ad will be inserted
        :>json string campaign_type: The type of campaign this as is from (eg. house, community, paid)

        An example::

            # Multiple type options
            {
                "ad_types": "readthedocs-fixed-footer|readthedocs-sidebar",
                "div_ids": "text-div|image-div"
                "priorities": "3|5"
            }

            # Simplest case
            {
                "ad_types": "readthedocs-sidebar",
                "div_ids": "sample-div"
            }

    .. http:post:: /api/v1/decision/

        Authentication is required for this endpoint.
        The POST version of the API is similar to the GET version with only a few changes:

        :<json string publisher: **Required**. The slug of the publisher.
        :<json array placements: **Required**. Various possible ad placements where an ad could go.
            This is a combination of ``div_ids``, ``ad_types``, and ``priorities`` in the GET API.
            Only one ad will be returned but you can prioritize one type of ad over another.
        :<json array keywords: Case-insensitive strings that describe the page where the ad will go for targeting
        :<json array campaign_types: Limit the ad results to certain campaign types.
        :<json string user_ip: User's IP address used for targeting
            (the requestor's IP will be used if not present)
        :<json string user_ua: User's user agent used for targeting
            (the requestor's UA will be used if not present)

        The response is the same as the GET request above.

        An example::

            {
                "publisher": "your-publisher",
                "placements": [
                    {
                        "div_id": "ad-div-1",
                        "ad_type": "image-v1",
                        "priority": 10,
                    }
                ],
                "campaign_types": ["paid"],  # request PAID ads only
                "keywords": [
                    "python",
                    "docker",
                    "kubernetes",
                ],
            }
    """

    permission_classes = (AdDecisionPermission,)
    renderer_classes = (JSONRenderer, JSONPRenderer)

    def _prepare_response(self, ad, placement, publisher, keywords):
        """
        Wrap `offer_ad` with the placement for the publisher.

        Data passed to `offer_ad` is cached for use on the View & Click tracking.
        """
        # Record a decision for every call to the API

        ad_type_slug = placement.get("ad_type")
        div_id = placement.get("div_id")

        if not ad:
            Advertisement.record_null_offer(
                request=self.request,
                publisher=publisher,
                ad_type_slug=ad_type_slug,
                div_id=div_id,
                keywords=keywords,
            )
            return {}

        ad.incr(impression_type=DECISIONS, publisher=publisher)

        data = ad.offer_ad(
            request=self.request,
            publisher=publisher,
            ad_type_slug=ad_type_slug,
            div_id=div_id,
            keywords=keywords,
        )
        log.debug(
            "Offering ad. publisher=%s ad_type=%s div_id=%s keywords=%s",
            publisher,
            ad_type_slug,
            div_id,
            keywords,
        )

        # The div where the ad is chosen to go is echoed back to the client
        data.update({"div_id": div_id})
        return data

    def get(self, request):
        """
        Decision API is called via GET.

        When called via GET the placements array is passed
        as individual fields rather than a JSON dict.

        List fields are passed as pipe (|) separated.
        """
        data = request.query_params.dict()

        placements = []
        div_ids = data.get("div_ids", "").split("|")
        ad_types = data.get("ad_types", "").split("|")
        priorities = data.get("priorities", "").split("|")

        data["keywords"] = [k for k in data.get("keywords", "").split("|") if k]
        data["campaign_types"] = [
            ct for ct in data.get("campaign_types", "").split("|") if ct
        ]

        for i, (div_id, ad_type) in enumerate(zip(div_ids, ad_types)):
            placement = {"div_id": div_id, "ad_type": ad_type}
            if i < len(priorities) and priorities[i]:
                placement["priority"] = priorities[i]

            placements.append(placement)

        data["placements"] = placements
        return self.decision(request, data)

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
            keywords = serializer.validated_data.get("keywords")
            backend = get_ad_decision_backend()(
                # Required parameters
                request=request,
                placements=serializer.validated_data["placements"],
                publisher=publisher,
                # Optional parameters
                keywords=keywords,
                campaign_types=serializer.validated_data.get("campaign_types"),
                # Debugging parameters
                ad_slug=serializer.validated_data.get("force_ad"),
                campaign_slug=serializer.validated_data.get("force_campaign"),
            )
            ad, placement = backend.get_ad_and_placement()

            return Response(
                self._prepare_response(
                    ad=ad,
                    placement=placement,
                    publisher=publisher,
                    # We need backend.keywords here to get the combined publisher/user keywords
                    keywords=backend.keywords,
                )
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdvertiserViewSet(viewsets.ReadOnlyModelViewSet):

    """
    Advertiser API calls.

    .. http:get:: /api/v1/advertisers/

        Return a list of advertisers the user has access to

        :>json int count: The number of advertisers returned
        :>json string next: A URL to the next page of advertisers (if needed)
        :>json string previous: A URL to the previous page of advertisers (if needed)
        :>json array results: An array of advertiser results (see advertiser details call)

    .. http:get:: /api/v1/advertisers/(str:slug)/

        Return a specific advertiser

        :>json string url: The URL to this report
        :>json string name: The name of the advertiser
        :>json string slug: A slug for the advertiser
        :>json date created: An array of advertiser results
        :>json date modified: The date the advertiser was last modified

    .. http:get:: /api/v1/advertisers/(str:slug)/report/

        Return a report of ad performance for this advertiser

        :query date start_date: Start the report on a given day inclusive.
            If not specified, defaults to 30 days ago
        :query date end_date: End the report on a given day inclusive.
            If not specified, no end time is used (up to current)

        :>json array days: An array of advertiser results per day
        :>json object total: An object of aggregated totals for the advertiser
        :>json array flights: An array of flights for this advertiser in the time period
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

        queryset = AdImpression.objects.filter(
            advertisement__flight__campaign__advertiser=advertiser
        ).filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        advertiser_report = AdvertiserReport(queryset)
        advertiser_report.generate()

        # Add the daily performance of all flights and ads within the timeframe
        flights = []
        for flight in Flight.objects.filter(campaign__advertiser=advertiser):
            flight_queryset = queryset.filter(advertisement__flight=flight)
            report = AdvertiserReport(flight_queryset)
            report.generate()

            if report.total["views"]:
                flight_data = FlightSerializer(flight).data
                flight_data["report"] = {
                    "total": report.total,
                    # Use "days" instead of "results" for backwards compatibility
                    "days": report.results,
                }
                flight_data["advertisements"] = []

                for ad, ad_report in flight.ad_reports(
                    start_date=start_date, end_date=end_date
                ):
                    ad_data = AdvertisementSerializer(ad).data
                    ad_data["report"] = ad_report
                    flight_data["advertisements"].append(ad_data)

                flights.append(flight_data)

        return Response(
            {
                "total": advertiser_report.total,
                # Use "days" instead of "results" for backwards compatibility
                "days": advertiser_report.results,
                "flights": flights,
            }
        )


class PublisherViewSet(viewsets.ReadOnlyModelViewSet):

    """
    Publisher API calls.

    .. http:get:: /api/v1/publishers/

        Return a list of publishers the user has access to

        :>json int count: The number of publisher returned
        :>json string next: A URL to the next page of publisher (if needed)
        :>json string previous: A URL to the previous page of publisher (if needed)
        :>json array results: An array of publisher results (see publisher details call)

    .. http:get:: /api/v1/publishers/(str:slug)/

        Return a specific publisher

        :>json string url: The URL to this report
        :>json string name: The name of the publisher
        :>json string slug: A slug for the publisher
        :>json date created: An array of publisher results
        :>json date modified: The date the publisher was last modified

    .. http:get:: /api/v1/publishers/(str:slug)/report/

        Return a report of ad performance for this publisher

        :query date start_date: Start the report on a given day inclusive.
            If not specified, defaults to 30 days ago
        :query date end_date: End the report on a given day inclusive.
            If not specified, no end time is used (up to current)

        :>json array days: An array of publisher results per day
        :>json object total: An object of aggregated totals for the publisher
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

        queryset = AdImpression.objects.filter(
            publisher=publisher, date__gte=start_date
        )
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        report = PublisherReport(queryset)
        report.generate()

        return Response(
            {
                "total": report.total,
                # Use "days" instead of "results" for backwards compatibility
                "days": report.results,
            }
        )
