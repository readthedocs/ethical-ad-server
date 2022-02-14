"""Mixins for API views and viewsets."""
from django.conf import settings

from ..utils import generate_client_id
from ..utils import get_client_ip
from ..utils import get_client_user_agent
from ..utils import get_geolocation


class GeoIpMixin:

    """
    A mixin that attaches updated IP, User Agent, and Geolocation data to the request.

    These need to be updated because the person seeing the ad may not be
    the person requesting the ad.

    In debug mode and for staff users, this data is also set as HTTP
    headers in the response. This is useful for debugging geolocation issues.
    """

    ip_field = "user_ip"
    ua_field = "user_ua"

    def initial(self, request, *args, **kwargs):
        """Set data onto the request."""
        super().initial(request, *args, **kwargs)

        request.ip_address = get_client_ip(request)
        request.user_agent = get_client_user_agent(request)

        # Get the actual client IP address and UA (the user who will view the ad)
        if self.ip_field in request.data and request.data[self.ip_field]:
            request.ip_address = request.data[self.ip_field]
        if self.ua_field in request.data and request.data[self.ua_field]:
            request.user_agent = request.data[self.ua_field]

        request.advertising_client_id = generate_client_id(
            request.ip_address, request.user_agent
        )

        # Geolocate the actual IP address (not the requestor's IP)
        # This is needed for the case of a server requesting ads on a user's behalf
        request.geo = get_geolocation(request)

    def finalize_response(self, request, response, *args, **kwargs):
        """Log data set on the request to HTTP headers in DEBUG or for staff."""
        response = super().finalize_response(request, response, *args, **kwargs)

        if settings.DEBUG or request.user.is_staff:
            # Show the real IP and geo for staff users in production
            # This allows debugging issues with ad targeting
            response["X-Adserver-RealIP"] = str(getattr(request, "ip_address", ""))
            response["X-Adserver-ClientID"] = str(
                getattr(request, "advertising_client_id", "")
            )
            response["X-Adserver-Country"] = str(request.geo.country)
            response["X-Adserver-Region"] = str(request.geo.region)
            response["X-Adserver-Metro"] = str(request.geo.metro)

        return response
