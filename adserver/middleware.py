"""Middleware for the ad server"""

from collections import namedtuple
import logging

from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2, GeoIP2Exception
from geoip2.errors import AddressNotFoundError

from .utils import get_client_ip


log = logging.getLogger(__name__)  # noqa


class GeolocationMiddleware:

    """Handles IP geolocation so ads can be targeted by geolocation"""

    GeolocationTuple = namedtuple("GeolocationTuple", ["country_code", "region", "dma"])

    def __init__(self, get_response):
        """
        Initialize the geolocation with one-time setup

        :param get_response: typically the view for the middleware
        """
        self.get_response = get_response
        self.geoip = None

        try:
            self.geoip = GeoIP2()
        except GeoIP2Exception:
            log.exception("IP Geolocation is unavailable")

    def __call__(self, request):
        """
        Sets geolocation data on the request object

        If ``settings.DEBUG``, sets HTTP headers with geolocation on the response

        :param request: the request object
        :return: an HTTP response
        """
        geo_data = self._get_geolocation(request)
        if geo_data:
            country_code = geo_data["country_code"]
            region = geo_data["region"]
            dma = geo_data["dma_code"]
            request.geo = self.GeolocationTuple(country_code, region, dma)
        else:
            request.geo = self.GeolocationTuple(None, None, None)

        response = self.get_response(request)

        if settings.DEBUG or request.user.is_staff:
            # Show the GeoIP results for staff users in production
            # This allows debugging issues with ad targeting
            response["X-Adserver-Country"] = str(request.geo.country_code)
            response["X-Adserver-Region"] = str(request.geo.region)
            response["X-Adserver-DMA"] = str(request.geo.dma)

        return response

    def _get_geolocation(self, request):
        if self.geoip:
            ip = get_client_ip(request)
            try:
                return self.geoip.city(ip)
            except AddressNotFoundError:
                log.debug("Could not get geolocation for %s", ip)

        return None
