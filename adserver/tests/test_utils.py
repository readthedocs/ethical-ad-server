import datetime
import re
from unittest import mock

import pytz
from django.contrib.gis.geoip2 import GeoIP2Exception
from django.test import TestCase
from django.test.client import RequestFactory
from django.utils import timezone
from geoip2.errors import AddressNotFoundError

from ..utils import anonymize_ip_address
from ..utils import anonymize_user_agent
from ..utils import calculate_ctr
from ..utils import calculate_ecpm
from ..utils import generate_client_id
from ..utils import get_ad_day
from ..utils import get_client_id
from ..utils import get_client_user_agent
from ..utils import get_geoipdb_geolocation
from ..utils import get_geolocation
from ..utils import is_blocklisted_ip
from ..utils import is_blocklisted_referrer
from ..utils import is_blocklisted_user_agent
from ..utils import is_click_ratelimited
from ..utils import is_valid_user_agent
from ..utils import is_view_ratelimited
from ..utils import parse_date_string


class UtilsTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")

    def test_get_ad_day(self):
        day = get_ad_day()
        self.assertTrue(timezone.is_aware(day))
        self.assertIsInstance(day, datetime.datetime)

    def test_anonymize_ip(self):
        self.assertIsNone(anonymize_ip_address("invalid-ip"))

        self.assertEqual(anonymize_ip_address("127.0.0.1"), "127.0.0.0")
        self.assertEqual(anonymize_ip_address("127.127.127.127"), "127.127.0.0")
        self.assertEqual(
            anonymize_ip_address("3ffe:1900:4545:3:200:f8ff:fe21:67cf"),
            "3ffe:1900:4545:3:200:f8ff:fe21:0",
        )
        self.assertEqual(
            anonymize_ip_address("fe80::200:f8ff:fe21:67cf"), "fe80::200:f8ff:fe21:0"
        )

    def test_anonymize_ua(self):
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36"
        self.assertEqual(anonymize_user_agent(ua), ua)

        self.assertEqual(
            anonymize_user_agent("Some rare user agent"), "Rare user agent"
        )

    def test_calculate_ecpm(self):
        self.assertAlmostEqual(calculate_ecpm(100, 0), 0)
        self.assertAlmostEqual(calculate_ecpm(100, 1), 100_000)
        self.assertAlmostEqual(calculate_ecpm(1, 1000), 1)
        self.assertAlmostEqual(calculate_ecpm(5, 100), 50)

    def test_calculate_ctr(self):
        self.assertAlmostEqual(calculate_ctr(100, 0), 0)
        self.assertAlmostEqual(calculate_ctr(1, 1), 100)
        self.assertAlmostEqual(calculate_ctr(1, 10), 10)
        self.assertAlmostEqual(calculate_ctr(5, 25), 20)

    def test_is_valid_user_agent(self):
        unsupported_uas = (
            "python-requests/2.27.1",
            "Links (2.1pre15; Linux 2.4.26 i686; 158x61)",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:5.0) Gecko/20100101 Firefox/5.0",
            "Mozilla/5.0 (Windows; U; Win98; en-US; rv:1.4) Gecko Netscape/7.1",
            "Mozilla/5.0 (Linux; Android 4.4.2; SM-T230NU Build/KOT49H) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.81 Safari/537.36",
        )
        for ua in unsupported_uas:
            self.assertFalse(is_valid_user_agent(ua))

        supported_ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
            "Chrome/103.0.5060.134 Safari/537.36"
        )
        self.assertTrue(is_valid_user_agent(supported_ua))

    def test_blocklisted_user_agent(self):
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/69.0.3497.100 Safari/537.36"
        )
        self.assertFalse(is_blocklisted_user_agent(ua))
        regexes = [re.compile("Chrome")]
        self.assertTrue(is_blocklisted_user_agent(ua, regexes))

        regexes = [re.compile("this isn't found"), re.compile("neither is this")]
        self.assertFalse(is_blocklisted_user_agent(ua, regexes))

    def test_blocklisted_referrer(self):
        referrer = "http://google.com"
        self.assertFalse(is_blocklisted_referrer(referrer))
        regexes = [re.compile("google.com")]
        self.assertTrue(is_blocklisted_referrer(referrer, regexes))

        regexes = [re.compile("this isn't found"), re.compile("neither is this")]
        self.assertFalse(is_blocklisted_referrer(referrer, regexes))

    def test_blocklisted_ip(self):
        ip = "1.1.1.1"
        self.assertFalse(is_blocklisted_ip(ip))

        self.assertTrue(is_blocklisted_ip(ip, ["1.1.1.1", "2.2.2.2"]))
        self.assertFalse(is_blocklisted_ip(ip, ["2.2.2.2"]))

    def test_click_ratelimited(self):
        factory = RequestFactory()
        request = factory.get("/")

        self.assertFalse(is_click_ratelimited(request))

        # The first request is "not" ratelimited; the second is
        ratelimits = ["1/s", "1/m"]
        self.assertFalse(is_click_ratelimited(request, ratelimits))
        self.assertTrue(is_click_ratelimited(request, ratelimits))

    def test_view_ratelimited(self):
        factory = RequestFactory()
        request = factory.get("/")

        self.assertFalse(is_view_ratelimited(request))

        # The first 3 requests are "not" ratelimited; the 4th is
        ratelimits = ["3/5m"]
        self.assertFalse(is_view_ratelimited(request, ratelimits))
        self.assertFalse(is_view_ratelimited(request, ratelimits))
        self.assertFalse(is_view_ratelimited(request, ratelimits))
        self.assertTrue(is_view_ratelimited(request, ratelimits))

    def test_generate_client_id(self):
        hexdigest1 = generate_client_id("8.8.8.8", "Mac OS, Safari, 10.x.x")
        hexdigest2 = generate_client_id("8.8.8.8", "Mac OS, Safari, 11.x.x")
        self.assertNotEqual(hexdigest1, hexdigest2)

        hexdigest3 = generate_client_id("", "")
        hexdigest4 = generate_client_id("", "")
        self.assertNotEqual(hexdigest3, hexdigest4)

    def test_get_client_id(self):
        factory = RequestFactory()
        request = factory.get("/")

        self.assertIsNotNone(get_client_id(request))

        client_id = "a-test-id"
        request.advertising_client_id = client_id
        self.assertEqual(get_client_id(request), client_id)

    def test_get_client_ua(self):
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_4) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36"
        )

        factory = RequestFactory(HTTP_USER_AGENT=ua)
        request = factory.get("/")

        self.assertEqual(get_client_user_agent(request), ua)

        # Force the ua
        forced_ua = "Test-UA"
        request.user_agent = forced_ua
        self.assertEqual(get_client_user_agent(request), forced_ua)

    def test_geolocation(self):
        """The GeoIP database is not available in CI."""
        self.request.ip_address = "invalid-ip"
        geolocation = get_geolocation(self.request)
        self.assertIsNone(geolocation.country)

        with mock.patch("adserver.utils.geoip") as geoip:
            geoip.city.return_value = {
                "country_code": "FR",
                "region": None,
                "dma_code": None,
            }
            self.request.ip_address = "8.8.8.8"
            geolocation = get_geoipdb_geolocation(self.request)
            self.assertIsNotNone(geolocation)
            self.assertEqual(geolocation.country, "FR")

        with mock.patch("adserver.utils.geoip") as geoip:
            geoip.city.side_effect = AddressNotFoundError()
            geolocation = get_geoipdb_geolocation(self.request)
            self.assertIsNone(geolocation.country)

        with mock.patch("adserver.utils.geoip") as geoip:
            geoip.city.side_effect = GeoIP2Exception()
            geolocation = get_geoipdb_geolocation(self.request)
            self.assertIsNone(geolocation.country)

    def test_parse_date_string(self):
        self.assertIsNone(parse_date_string("not-a-date"))
        self.assertIsNone(parse_date_string(""))
        self.assertIsNone(parse_date_string(None))

        self.assertEqual(
            parse_date_string("2020-01-01"),
            datetime.datetime(year=2020, month=1, day=1, tzinfo=pytz.utc),
        )
