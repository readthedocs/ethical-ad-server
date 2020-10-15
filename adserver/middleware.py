"""Ad server middleware."""
import socket


class XForwardedForMiddleware:

    """
    Sets request.ip_address with the client's IP from x-forwarded-for.

    On Heroku, x-forwarded-for contains the client's IP address:
    https://devcenter.heroku.com/articles/http-routing#heroku-headers

    SECURITY NOTE: This middleware *SHOULD BE DISABLED* if the x-forwarded-for
        header is not guaranteed from the load balancer as a user could fake it.
    """

    def __init__(self, get_response):
        """One-time configuration and initialization."""
        self.get_response = get_response

    def __call__(self, request):
        """Sets request.ip_address based on x-forwarded-for."""
        request.ip_address = self._get_ip_address(request)
        response = self.get_response(request)
        response["X-Server"] = socket.gethostname()
        return response

    def _get_ip_address(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", None)
        if x_forwarded_for:
            # HTTP_X_FORWARDED_FOR can be a comma-separated list of IPs.
            # The client's IP will be the first one.
            # (eg. "X-Forwarded-For: client, proxy1, proxy2")
            client_ip = x_forwarded_for.split(",")[0].strip()

            # Removing the port number (if present)
            # But be careful about IPv6 addresses
            if client_ip.count(":") == 1:
                client_ip = client_ip.rsplit(":", maxsplit=1)[0]
        else:
            client_ip = request.META.get("REMOTE_ADDR", "")

        return client_ip
