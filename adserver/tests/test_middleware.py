from django.contrib.auth import get_user_model
from django.test import TestCase
from django_dynamic_fixture import get


class TestMiddleware(TestCase):
    def test_server_middleware(self):
        response = self.client.get("/")
        self.assertTrue("X-Server" in response)
        self.assertFalse("X-Adserver-Version" in response)

        # Login as staff
        staff_user = get(get_user_model(), is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get("/")
        self.assertTrue("X-Server" in response)
        self.assertTrue("X-Adserver-Version" in response)

    def test_cloudflare_ip_middleware(self):
        with self.modify_settings(
            MIDDLEWARE={
                "append": "adserver.middleware.CloudflareIpAddressMiddleware",
                "remove": "adserver.middleware.IpAddressMiddleware",
            }
        ):
            response = self.client.get("/")
            request = response.wsgi_request
            self.assertTrue(hasattr(request, "ip_address"))
            self.assertEqual(request.ip_address, "127.0.0.1")

            ip = "10.10.10.10"
            response = self.client.get("/", HTTP_CF_CONNECTING_IP=ip)
            request = response.wsgi_request
            self.assertEqual(request.ip_address, ip)
            self.assertFalse("X-Adserver-IpAddress-Provider" in response)

            ip = "invalid"
            response = self.client.get("/", HTTP_CF_CONNECTING_IP=ip)
            request = response.wsgi_request
            self.assertEqual(request.ip_address, "127.0.0.1")

            # Login as staff
            staff_user = get(get_user_model(), is_staff=True)
            self.client.force_login(staff_user)

            # The provider header should be present for staff
            ip = "10.10.10.10"
            response = self.client.get("/", HTTP_CF_CONNECTING_IP=ip)
            request = response.wsgi_request
            self.assertEqual(request.ip_address, ip)
            self.assertTrue("X-Adserver-IpAddress-Provider" in response)
            self.assertEqual(response["X-Adserver-IpAddress-Provider"], "Cloudflare")

    def test_xforwarded_for_middleware(self):
        with self.modify_settings(
            MIDDLEWARE={
                "append": "adserver.middleware.XForwardedForMiddleware",
                "remove": "adserver.middleware.IpAddressMiddleware",
            }
        ):
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

            # Invalid client IP
            ip = "invalid"
            response = self.client.get("/", HTTP_X_FORWARDED_FOR=ip)
            request = response.wsgi_request
            self.assertEqual(request.ip_address, "127.0.0.1")

            # Login as staff
            staff_user = get(get_user_model(), is_staff=True)
            self.client.force_login(staff_user)

            # The provider header should be present for staff
            ip = "10.10.10.10"
            response = self.client.get("/", HTTP_X_FORWARDED_FOR=ip)
            request = response.wsgi_request
            self.assertEqual(request.ip_address, ip)
            self.assertTrue("X-Adserver-IpAddress-Provider" in response)
            self.assertEqual(
                response["X-Adserver-IpAddress-Provider"], "X-Forwarded-For"
            )

    def test_cloudflare_geoip_middleware(self):
        with self.modify_settings(
            MIDDLEWARE={
                "append": "adserver.middleware.CloudflareGeoIpMiddleware",
                "remove": "adserver.middleware.GeoIpMiddleware",
            }
        ):
            country = "CA"
            response = self.client.get("/", HTTP_CF_IPCOUNTRY=country)
            request = response.wsgi_request
            self.assertEqual(request.geo.country, country)
            self.assertFalse("X-Adserver-GeoIP-Provider" in response)

            country = "XX"
            response = self.client.get("/", HTTP_CF_IPCOUNTRY=country)
            request = response.wsgi_request
            self.assertEqual(request.geo.country, None)

            # Login as staff
            staff_user = get(get_user_model(), is_staff=True)
            self.client.force_login(staff_user)

            country = "US"
            response = self.client.get("/", HTTP_CF_IPCOUNTRY=country)
            request = response.wsgi_request
            self.assertEqual(request.geo.country, country)
            self.assertTrue("X-Adserver-GeoIP-Provider" in response)
            self.assertEqual(response["X-Adserver-GeoIP-Provider"], "Cloudflare")

    def test_geoipdb_middleware(self):
        with self.modify_settings(
            MIDDLEWARE={
                "append": "adserver.middleware.GeoIpDatabaseMiddleware",
                "remove": "adserver.middleware.GeoIpMiddleware",
            }
        ):
            # Note: Because we can't ship the GeoIP database,
            # this test is mostly a fake test...
            response = self.client.get("/")
            request = response.wsgi_request
            self.assertIsNone(request.geo.country)
            self.assertFalse("X-Adserver-GeoIP-Provider" in response)

            # Login as staff
            staff_user = get(get_user_model(), is_staff=True)
            self.client.force_login(staff_user)

            response = self.client.get("/")
            request = response.wsgi_request
            self.assertIsNone(request.geo.country)
            self.assertTrue("X-Adserver-GeoIP-Provider" in response)
            self.assertEqual(response["X-Adserver-GeoIP-Provider"], "GeoIP DB")
