"""Ad server middleware."""
import ipaddress
import logging
import socket

from django.conf import settings


log = logging.getLogger(__name__)  # noqa


class ServerInfoMiddleware:

    """Sets informational headers for staff users or in DEBUG mode."""

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets headers for staff users or in debug mode."""
        response = self.get_response(request)

        if settings.DEBUG or request.user.is_staff:
            response["X-Server"] = socket.gethostname()
            response["X-Adserver-Version"] = settings.ADSERVER_VERSION
        return response


class CloudflareMiddleware:

    """
    Sets request.ip_address and request.country from Cloudflare headers.

    See: https://developers.cloudflare.com/fundamentals/get-started/http-request-headers

    SECURITY NOTE: This middleware *SHOULD BE DISABLED* if not running on Cloudflare.
        Otherwise these headers are spoofable and could result in invalid traffic.
        Also, Cloudflare IP Geolocation must be enabled.
    """

    COUNTRY_HEADER = "CF-IPCountry"
    IP_HEADER = "CF-Connecting-IP"

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets request.ip_address and request.country based on Cloudflare headers."""
        request.ip_address = self._get_ip_address(request)
        request.user_country = self._get_country(request)
        response = self.get_response(request)

        if request.user_country and (settings.DEBUG or request.user.is_staff):
            response["X-Adserver-GeoIPProvider"] = "Cloudflare"

        return response

    def _get_ip_address(self, request):
        ip = request.headers.get(self.IP_HEADER, None)

        if ip:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                # This should be OK to log since this is a spoofed address
                log.warning(
                    "Invalid IP in Cloudflare headers. "
                    "This header is probably untrustworthy so the CloudflareMiddleware should be disabled. "
                    "%s=%s",
                    self.IP_HEADER,
                    ip,
                )
                ip = None
        if not ip:
            ip = request.META.get("REMOTE_ADDR", "")

        return ip

    def _get_country(self, request):
        country_code = request.headers.get(self.COUNTRY_HEADER, None)
        if country_code == "XX":
            # CF always adds the header and sets "XX" if it can't geolocate
            country_code = None

        return country_code


class XForwardedForMiddleware:

    """
    Sets request.ip_address with the client's IP from x-forwarded-for.

    On Heroku, x-forwarded-for contains the client's IP address:
    https://devcenter.heroku.com/articles/http-routing#heroku-headers

    SECURITY NOTE: This middleware *SHOULD BE DISABLED* if the x-forwarded-for
        header is not guaranteed from the load balancer as a user could fake it.
    """

    HEADER_NAME = "X-Forwarded-For"

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets request.ip_address based on x-forwarded-for."""
        request.ip_address = self._get_ip_address(request)
        response = self.get_response(request)
        return response

    def _get_ip_address(self, request):
        client_ip = None
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
            except ValueError:
                # This should be OK to log since this is a spoofed address
                log.warning(
                    "Invalid IP from X-Forwarded-For. "
                    "This header is probably untrustworthy so the XForwardedForMiddleware should be disabled. "
                    "x-forwarded-for=%s",
                    x_forwarded_for,
                )
                client_ip = None
        if not client_ip:
            client_ip = request.META.get("REMOTE_ADDR", "")

        return client_ip
