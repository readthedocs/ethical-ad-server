"""Middleware for the ad server"""
import logging

from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.geoip2 import GeoIP2Exception
from geoip2.errors import AddressNotFoundError

from .utils import GeolocationTuple
from .utils import get_client_ip


log = logging.getLogger(__name__)  # noqa


class RealIPAddressMiddleware:

    """
    Attaches the real IP address of a request to ``request.ip_address``

    Sets the real IP based on the X-Forwarded-For header.
    This cannot be done reliably for all configurations.
    You may need to customize this middleware depending on your load balancer
    or disable it completely if you are not using a load balancer.
    Only use this when you can absolutely trust the value of HTTP_X_FORWARDED_FOR.

    See https://docs.djangoproject.com/en/dev/releases/1.1/#removed-setremoteaddrfromforwardedfor-middleware
    """

    def __init__(self, get_response):
        """One-time setup"""
        self.get_response = get_response

    def __call__(self, request):
        request.ip_address = self._get_real_ip(request)
        response = self.get_response(request)

        if settings.DEBUG or request.user.is_staff:
            # Show the real IP for staff users in production
            # This allows debugging issues with ad targeting
            response["X-Adserver-RealIP"] = str(request.ip_address)

        return response

    def _get_real_ip(self, request):
        ip_address = request.META.get("REMOTE_ADDR", "")

        # Get the original IP address from a header set by the load balancer
        # (eg. "X-Forwarded-For: client, proxy1, proxy2")
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
        if x_forwarded_for:
            # Some load balancers include the port number
            ip_address = x_forwarded_for.rsplit(":")[0]

        return ip_address


class GeolocationMiddleware:

    """Handles IP geolocation so ads can be targeted by geolocation"""

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
            region_code = geo_data["region"]
            metro_code = geo_data["dma_code"]
            request.geo = GeolocationTuple(country_code, region_code, metro_code)
        else:
            request.geo = GeolocationTuple(None, None, None)

        response = self.get_response(request)

        if settings.DEBUG or request.user.is_staff:
            # Show the GeoIP results for staff users in production
            # This allows debugging issues with ad targeting
            response["X-Adserver-Country"] = str(request.geo.country_code)
            response["X-Adserver-Region"] = str(request.geo.region_code)
            response["X-Adserver-Metro"] = str(request.geo.metro_code)

        return response

    def _get_geolocation(self, request):
        if self.geoip:
            ip = get_client_ip(request)
            try:
                return self.geoip.city(ip)
            except AddressNotFoundError:
                log.debug("Could not get geolocation for %s", ip)
            except GeoIP2Exception:
                log.warning("Geolocation configuration error")

        return None
