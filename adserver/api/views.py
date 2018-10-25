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
    Decide on a `Advertisement` based on inputs, the user, and attributes of the request

    Input parameters

    * `placements` - where the ad can go
    * `[keywords]` - keywords about the ad
    * `[force_sf]` - force showing a specific advertisement
    * `[force_campaign]` - force showing an ad from a specific campaign

    When called via GET the placements array is passed as `|` separated strings of its components:

    * `div_ids`
    * `priorities`

    The decision is based on

    * the input parameters
    * minimal user agent details (browser, mobile, operating system)
    * geo, keywords, and other targeting parameters
    """

    permission_classes = (permissions.AllowAny,)
    renderer_classes = (JSONRenderer, JSONPRenderer)

    def _prepare_response(self, ad, placement):
        """Wrap `offer_ad` with the placement"""
        if not ad or not placement:
            return {}

        data = offer_ad(ad)
        data.update({"div_id": placement["div_id"]})
        return data

    def get(self, request):
        """
        Decision API is called via GET

        When called via GET the placements array is passed
        as individual fields rather than a JSON dict
        """
        data = request.query_params.dict()

        placements = []
        div_ids = data.get("div_ids", "").split("|")
        ad_types = data.get("ad_types", "").split("|")
        priorities = data.get("priorities", "").split("|")

        for i, (div_id, display_type) in enumerate(zip(div_ids, ad_types)):
            placement = {"div_id": div_id, "ad_type": display_type}
            if i < len(priorities) and priorities[i]:
                placement["priority"] = priorities[i]

            placements.append(placement)

        data["placements"] = placements
        return self.decision(request, data)

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
        serializer = AdDecisionSerializer(data=data)

        if serializer.is_valid():
            placements = serializer.validated_data["placements"]

            ad_slug = serializer.validated_data.get("force_ad")
            campaign_slug = serializer.validated_data.get("force_campaign")

            backend = get_ad_decision_backend()(
                request=request,
                placements=placements,
                ad_slug=ad_slug,
                campaign_slug=campaign_slug,
            )
            ad, placement = backend.get_ad_and_placement()

            return Response(self._prepare_response(ad, placement))

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
