"""Mixins for API views and viewsets."""
from django.conf import settings

from ..utils import generate_client_id
from ..utils import GeolocationTuple
from ..utils import get_client_ip
from ..utils import get_client_user_agent
from ..utils import get_geolocation


class GeoIpMixin:

    """
    A mixin that attaches IP, User Agent, and Geolocation data to the request.

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

        # Geolocate the actual IP address
        country_code = region_code = metro_code = None
        geo_data = get_geolocation(request.ip_address)
        if geo_data:
            country_code = geo_data["country_code"]
            region_code = geo_data["region"]
            metro_code = geo_data["dma_code"]

        request.geo = GeolocationTuple(country_code, region_code, metro_code)

    def finalize_response(self, request, response, *args, **kwargs):
        """Log data set on the request to HTTP headers in DEBUG or for staff."""
        response = super().finalize_response(request, response, *args, **kwargs)

        if settings.DEBUG or request.user.is_staff:
            # Show the real IP and geo for staff users in production
            # This allows debugging issues with ad targeting
            response["X-Adserver-RealIP"] = str(request.ip_address)
            response["X-Adserver-ClientID"] = str(request.advertising_client_id)
            response["X-Adserver-Country"] = str(request.geo.country_code)
            response["X-Adserver-Region"] = str(request.geo.region_code)
            response["X-Adserver-Metro"] = str(request.geo.metro_code)

        return response
