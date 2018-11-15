"""APIs for the ad server"""
from rest_framework import permissions
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_jsonp.renderers import JSONPRenderer

from ..decisionengine import get_ad_decision_backend
from ..utils import offer_ad
from .serializers import AdDecisionSerializer


class AdDecisionView(APIView):

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
        :param string force_ad: Limit results to a specific ad
        :param string force_campaign: Limit results to ads from a specific campaign
    """

    permission_classes = (permissions.AllowAny,)
    renderer_classes = (JSONRenderer, JSONPRenderer)

    def _prepare_response(self, ad, placement, publisher):
        """Wrap `offer_ad` with the placement for the publisher"""
        if not ad or not placement:
            return {}

        data = offer_ad(ad, publisher)
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
