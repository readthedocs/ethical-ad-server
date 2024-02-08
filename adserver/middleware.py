"""Ad server middleware."""
import ipaddress
import logging
import socket

from django.conf import settings

from .utils import GeolocationData
from .utils import get_geoipdb_geolocation


log = logging.getLogger(__name__)  # noqa


class ServerInfoMiddleware:

    """Sets informational headers for staff users or in DEBUG mode."""

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets headers for staff users or in debug mode."""
        response = self.get_response(request)

        response["X-Server"] = socket.gethostname()

        if settings.DEBUG or request.user.is_staff:
            response["X-Adserver-Version"] = settings.ADSERVER_VERSION
        return response


class IpAddressMiddleware:

    """
    Sets the IP address of the user onto the request object.

    In production, you probably want to use the CloudflareIpAddressMiddleware
    or the XForwardedForMiddleware depending on your setup.
    """

    PROVIDER_NAME = "REMOTE_ADDR header"

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets the IP address of the user onto the request object."""
        request.ip_address = self.get_ip_address(request)
        response = self.get_response(request)

        if settings.DEBUG or request.user.is_staff:
            response["X-Adserver-IpAddress-Provider"] = self.PROVIDER_NAME
        return response

    def get_ip_address(self, request):
        return request.META.get("REMOTE_ADDR", None)


class XForwardedForMiddleware(IpAddressMiddleware):

    """
    Sets request.ip_address with the client's IP from x-forwarded-for.

    On Heroku, x-forwarded-for contains the client's IP address:
    https://devcenter.heroku.com/articles/http-routing#heroku-headers

    SECURITY NOTE: This middleware *SHOULD BE DISABLED* if the x-forwarded-for
        header is not guaranteed from the load balancer as a user could fake it.
    """

    PROVIDER_NAME = "X-Forwarded-For"
    HEADER_NAME = "X-Forwarded-For"

    def get_ip_address(self, request):
        ip = super().get_ip_address(request)
        x_forwarded_for = request.headers.get(self.HEADER_NAME, None)
        if x_forwarded_for:
            # HTTP_X_FORWARDED_FOR can be a comma-separated list of IPs.
            # The client's IP will be the first one.
            # (eg. "X-Forwarded-For: client, proxy1, proxy2")
            client_ip = x_forwarded_for.split(",")[0].strip()

            # Removing the port number (if present)
            # But be careful about IPv6 addresses
            if client_ip.count(":") == 1:
                client_ip = client_ip.rsplit(":", maxsplit=1)[0]

            try:
                ipaddress.ip_address(client_ip)
                ip = client_ip
            except ValueError:
                # This should be OK to log since this is a spoofed address
                log.warning(
                    "Invalid IP from X-Forwarded-For. "
                    "This header is probably untrustworthy so the XForwardedForMiddleware should be disabled. "
                    "x-forwarded-for=%s",
                    x_forwarded_for,
                )

        return ip


class CloudflareIpAddressMiddleware(IpAddressMiddleware):

    """
    Sets request.ip_address from Cloudflare headers.

    See: https://developers.cloudflare.com/fundamentals/get-started/http-request-headers

    SECURITY NOTE: This middleware *SHOULD BE DISABLED* if not running on Cloudflare.
        Otherwise these headers are spoofable and could result in invalid traffic.
    """

    PROVIDER_NAME = "Cloudflare"
    IP_HEADER = "CF-Connecting-IP"

    def get_ip_address(self, request):
        ip = super().get_ip_address(request)
        cf_ip = request.headers.get(self.IP_HEADER, None)

        if cf_ip:
            try:
                ipaddress.ip_address(cf_ip)
                ip = cf_ip
            except ValueError:
                # This should be OK to log since this is a spoofed address
                log.warning(
                    "Invalid IP in Cloudflare headers. "
                    "This header is probably untrustworthy so the CloudflareIpAddressMiddleware should be disabled. "
                    "%s=%s",
                    self.IP_HEADER,
                    cf_ip,
                )

        return ip


class GeoIpMiddleware:

    """
    Sets a request.geo dictionary onto the request object.

    This middleware doesn't have any provider and just sets null
    for all the geolocation data. It isn't useful except in development/testing.

    In production, you probably want to use the CloudflareGeoIpMiddleware
    or the GeoIpDbMiddleware depending on your setup.
    """

    PROVIDER_NAME = "None"

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets the geolocation data of the user onto the request object."""
        request.geo = self.get_geoip(request)
        response = self.get_response(request)

        if settings.DEBUG or request.user.is_staff:
            response["X-Adserver-GeoIp-Provider"] = self.PROVIDER_NAME
        return response

    def get_geoip(self, request):
        return GeolocationData()


class CloudflareGeoIpMiddleware(GeoIpMiddleware):

    """
    Sets request.geo from Cloudflare headers.

    See: https://support.cloudflare.com/hc/en-us/articles/200168236-Configuring-Cloudflare-IP-Geolocation

    SECURITY NOTE: This middleware *SHOULD BE DISABLED* if not running on Cloudflare.
        Otherwise these headers are spoofable and could result in invalid traffic.
        Also, Cloudflare IP Geolocation must be enabled.
    """

    PROVIDER_NAME = "Cloudflare"
    COUNTRY_HEADER = "CF-IPCountry"

    # These fields will require a custom transform rule
    # https://developers.cloudflare.com/rules/transform/
    REGION_HEADER = "X-Cloudflare-Geo-Region"  # ip.src.region_code
    METRO_HEADER = "X-Cloudflare-Geo-Metro"  # ip.src.metro_code

    def get_geoip(self, request):
        geo = super().get_geoip(request)

        country_code = request.headers.get(self.COUNTRY_HEADER, None)
        if country_code == "XX":
            # CF always adds the header and sets "XX" if it can't geolocate
            # CF uses "T1" for Tor traffic which should be handled by our system
            country_code = None

        geo.country = country_code
        geo.region = request.headers.get(self.REGION_HEADER, None)
        geo.metro = request.headers.get(self.METRO_HEADER, None)

        return geo


class GeoIpDatabaseMiddleware(GeoIpMiddleware):

    """Sets request.geo using a GeoIP database."""

    PROVIDER_NAME = "GeoIP DB"

    def get_geoip(self, request):
        return get_geoipdb_geolocation(request)
