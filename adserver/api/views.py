"""APIs for the ad server"""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from user_agents import parse

from ..constants import CLICKS
from ..constants import VIEWS
from ..decisionengine import get_ad_decision_backend
from ..utils import analytics_event
from ..utils import get_client_ip
from ..utils import get_client_user_agent
from ..utils import is_blacklisted_user_agent
from .mixins import GeoIpMixin
from .permissions import PublisherPermission
from .serializers import AdDecisionSerializer
from .serializers import AdTrackingSerializer


log = logging.getLogger(__name__)  # noqa


class AdDecisionView(GeoIpMixin, APIView):

    """
    Make a decision on an `Advertisement` to show

    The ad decision is based on

    * the publisher (ad campaigns may be publisher specific)
    * the available placements (ad types and priorities)
    * minimal user agent details (browser, mobile, operating system)
    * geography (based on IP)
    * keywords

    .. http:post:: /api/v1/decision/

        :param string publisher: **Required**. The slug of the publisher
        :param array placements: **Required**. Various possible ad placements where an ad could go
        :param array keywords: Keywords that identify the page where the ad will go
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
        """Wrap `offer_ad` with the placement for the publisher"""
        if not ad or not placement:
            return {}

        data = ad.offer_ad(publisher)
        data.update({"div_id": placement["div_id"]})
        return data

    def post(self, request):
        """
        Decision API called via POST

        Used for server to server ad requests.

        Depending on the configuration of authentication classes and middleware,
        CSRF protection on POST requests may be enabled.
        See: http://www.django-rest-framework.org/topics/ajax-csrf-cors/#csrf-protection
        """
        return self.decision(request, request.data)

    def decision(self, request, data):
        """
        Makes a decision on what add to display based on info

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


class BaseTrackingView(GeoIpMixin, APIView):

    """A base API class for tracking ad impressions"""

    permission_classes = (PublisherPermission,)

    log_level = logging.DEBUG
    impression_type = VIEWS

    def _get_response_data(self, message):
        data = None

        if settings.DEBUG or settings.TESTING:
            # Only return the reason an impression was tracked or not in DEBUG mode
            # Otherwise users may attempt to brute force ad impressions
            data = {"message": message}

        return data

    def _ignore_tracking_reason(self, request, advertisement, nonce, publisher):
        """Returns a reason this impression should not be tracked or `None` if this *should* be tracked"""
        reason = None

        ip_address = get_client_ip(request)
        user_agent = get_client_user_agent(request)
        parsed_ua = parse(user_agent)

        valid_nonce = advertisement.is_valid_nonce(self.impression_type, nonce)

        if not valid_nonce:
            log.log(self.log_level, "Old or nonexistent impression nonce")
            reason = "Old/Nonexistent nonce"
        elif parsed_ua.is_bot:
            log.log(self.log_level, "Bot impression. User Agent: [%s]", user_agent)
            reason = "Bot impression"
        elif ip_address in settings.INTERNAL_IPS:
            log.log(
                self.log_level, "Internal IP impression. User Agent: [%s]", user_agent
            )
            reason = "Internal IP"
        elif parsed_ua.os.family == "Other" and parsed_ua.browser.family == "Other":
            # This is probably a bot/proxy server/prefetcher/etc.
            log.log(self.log_level, "Unknown user agent impression [%s]", user_agent)
            reason = "Unrecognized user agent"
        elif request.user.is_staff:
            log.log(self.log_level, "Ignored staff user ad impression")
            reason = "Staff impression"
        elif is_blacklisted_user_agent(user_agent):
            log.log(
                self.log_level, "Blacklisted user agent impression [%s]", user_agent
            )
            reason = "Blacklisted impression"
        elif not publisher:
            log.log(self.log_level, "Ad impression for unknown publisher")
            reason = "Unknown publisher"

        return reason


class ViewTrackingView(BaseTrackingView):

    """
    Track an ad view

    .. http:post:: /api/v1/track/view/

        :param string advertisement: **Required** the slug of the ad
        :param string nonce: **Required** the nonce returned from the decision API
        :param string url: **Required** the referrer for the ad view
        :param string user_ip: User's IP address used for targeting
            (the requestor's IP will be used if not present)
        :param string user_ua: User's user agent used for targeting
            (the requestor's UA will be used if not present)
    """

    def post(self, request):
        """Handle tracking an ad view"""
        serializer = AdTrackingSerializer(data=request.data)
        if serializer.is_valid():
            advertisement = serializer.validated_data["advertisement"]
            nonce = serializer.validated_data["nonce"]
            url = serializer.validated_data["url"]
            publisher = advertisement.get_publisher(nonce)

            self.check_object_permissions(request, publisher)

            ignore_reason = self._ignore_tracking_reason(
                request, advertisement, nonce, publisher
            )
            if not ignore_reason:
                log.debug("Billed ad view")
                advertisement.invalidate_nonce(self.impression_type, nonce)
                advertisement.track_view(request, publisher, url)

            message = ignore_reason or "Billed view"
            return Response(
                self._get_response_data(message), status=status.HTTP_202_ACCEPTED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ClickTrackingView(BaseTrackingView):

    """
    Track an ad click

    .. http:post:: /api/v1/track/click/

        :param string advertisement: **Required** the slug of the ad
        :param string nonce: **Required** the nonce returned from the decision API
        :param string url: **Required** the referrer for the ad view
        :param string user_ip: User's IP address used for targeting
            (the requestor's IP will be used if not present)
        :param string user_ua: User's user agent used for targeting
            (the requestor's UA will be used if not present)
    """

    log_level = logging.WARNING
    impression_type = CLICKS

    def send_click_to_analytics(self, request, advertisement, event_action):
        """Send click data to analytics"""
        ip_address = get_client_ip(request)
        user_agent = get_client_user_agent(request)

        event_category = "Advertisement"
        event_label = advertisement.slug

        # The event_value is in US cents (eg. for $2 CPC, the value is 200)
        # CPMs are too small to register
        event_value = int(advertisement.flight.cpc * 100)

        analytics_event(
            event_category=event_category,
            event_action=event_action,
            event_label=event_label,
            event_value=event_value,
            ua=user_agent,
            uip=ip_address,  # will be anonymized
        )

    def post(self, request):
        """Handle tracking an ad click"""
        serializer = AdTrackingSerializer(data=request.data)
        if serializer.is_valid():
            advertisement = serializer.validated_data["advertisement"]
            nonce = serializer.validated_data["nonce"]
            url = serializer.validated_data["url"]
            publisher = advertisement.get_publisher(nonce)

            self.check_object_permissions(request, publisher)

            ignore_reason = self._ignore_tracking_reason(
                request, advertisement, nonce, publisher
            )
            if not ignore_reason:
                log.info("Billed ad click")
                advertisement.invalidate_nonce(self.impression_type, nonce)
                advertisement.track_click(request, publisher, url)

            message = ignore_reason or "Billed click"
            self.send_click_to_analytics(request, advertisement, message)

            return Response(
                self._get_response_data(message), status=status.HTTP_202_ACCEPTED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
