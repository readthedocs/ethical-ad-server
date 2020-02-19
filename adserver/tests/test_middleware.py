from django.test import TestCase


class TestMiddleware(TestCase):
    def test_xforwarded_for_middleware(self):
        response = self.client.get("/")
        request = response.wsgi_request
        self.assertTrue(hasattr(request, "ip_address"))
        self.assertEqual(request.ip_address, "127.0.0.1")

        response = self.client.get("/", HTTP_X_FORWARDED_FOR="10.10.10.10")
        request = response.wsgi_request
        self.assertEqual(request.ip_address, "10.10.10.10")

        # Multiple proxies in the chain
        ip = "10.10.10.10"
        x_forwarded_for = f"{ip}, 11.11.11.11, 12.12.12.12"
        response = self.client.get("/", HTTP_X_FORWARDED_FOR=x_forwarded_for)
        request = response.wsgi_request
        self.assertEqual(request.ip_address, ip)

        # client ip (ipv4), other clients with port
        ip = "10.10.10.10"
        x_forwarded_for = f"{ip}:1234, 11.11.11.11, 12.12.12.12"
        response = self.client.get("/", HTTP_X_FORWARDED_FOR=x_forwarded_for)
        request = response.wsgi_request
        self.assertEqual(request.ip_address, ip)

        # client ip (ipv6), other clients with port
        ip = "2001:abc:def:012:345:6789:abcd:ef12"
        x_forwarded_for = f"{ip}, 11.11.11.11:2345, 12.12.12.12:3456"
        response = self.client.get("/", HTTP_X_FORWARDED_FOR=x_forwarded_for)
        request = response.wsgi_request
        self.assertEqual(request.ip_address, ip)
