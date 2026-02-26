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
from ..utils import build_blocked_ip_set
from ..utils import cached_method
from ..utils import calculate_ctr
from ..utils import calculate_ecpm
from ..utils import calculate_percent_diff
from ..utils import generate_absolute_url
from ..utils import generate_client_id
from ..utils import get_ad_day
from ..utils import get_client_id
from ..utils import get_client_user_agent
from ..utils import get_day
from ..utils import get_domain_from_url
from ..utils import get_geoipdb_geolocation
from ..utils import get_geolocation
from ..utils import get_ipproxy_db
from ..utils import is_allowed_domain
from ..utils import is_blocklisted_ip
from ..utils import is_blocklisted_referrer
from ..utils import is_blocklisted_user_agent
from ..utils import is_click_ratelimited
from ..utils import is_proxy_ip
from ..utils import is_view_ratelimited
from ..utils import offers_dump_exists
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

    def test_calculate_percent_diff(self):
        self.assertAlmostEqual(calculate_percent_diff(10, 5), 100.0)
        self.assertAlmostEqual(calculate_percent_diff(10, 0), 0.0)
        self.assertAlmostEqual(calculate_percent_diff(10, -5), 0.0)

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

        with mock.patch("adserver.utils.is_proxy_ip") as is_proxy_ip:
            is_proxy_ip.return_value = True
            self.assertTrue(is_blocklisted_ip("3.3.3.3"))

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
            geoip.city.side_effect = AddressNotFoundError(
                "IP Address Not Found somehow"
            )
            geolocation = get_geoipdb_geolocation(self.request)
            self.assertIsNone(geolocation.country)

        with mock.patch("adserver.utils.geoip") as geoip:
            geoip.city.side_effect = GeoIP2Exception()
            geolocation = get_geoipdb_geolocation(self.request)
            self.assertIsNone(geolocation.country)

        # Invalid IP
        self.request.ip_address = "not-an-ip"
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

    def test_get_domain_from_url(self):
        self.assertEqual(get_domain_from_url("http://example.com/foo"), "example.com")
        self.assertIsNone(get_domain_from_url(None))
        # urlparse doesn't easily raise ValueError, but we can mock it or provide weird input
        with mock.patch("adserver.utils.urlparse") as urlparse:
            urlparse.side_effect = ValueError
            self.assertIsNone(get_domain_from_url("http://example.com"))

    def test_generate_absolute_url(self):
        with self.settings(ADSERVER_HTTPS=True):
            url = generate_absolute_url("/foo/")
            self.assertTrue(url.startswith("https://"))

        with self.settings(ADSERVER_HTTPS=False):
            url = generate_absolute_url("/foo/")
            self.assertTrue(url.startswith("http://"))

    def test_get_day(self):
        # Default today
        start, end = get_day()
        self.assertEqual(end - start, datetime.timedelta(days=1))

        # ISO string
        start, end = get_day("2020-01-01")
        self.assertEqual(
            start, datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        )

        # Naive datetime
        naive = datetime.datetime(2020, 1, 1)
        start, end = get_day(naive)
        self.assertEqual(start.tzinfo, datetime.timezone.utc)

    def test_is_blocklisted_ua_no_ua(self):
        self.assertFalse(is_blocklisted_user_agent(None))
        self.assertFalse(is_blocklisted_user_agent(""))

    def test_is_blocklisted_referrer_no_referrer(self):
        self.assertFalse(is_blocklisted_referrer(None))
        self.assertFalse(is_blocklisted_referrer(""))

    def test_is_blocklisted_ip_none(self):
        self.assertFalse(is_blocklisted_ip(None))
        self.assertFalse(is_blocklisted_ip(""))

    def test_is_proxy_ip_no_db(self):
        with mock.patch("adserver.utils.ipproxy_db", None):
            self.assertFalse(is_proxy_ip("8.8.8.8"))

    def test_is_allowed_domain_no_restrictions(self):
        self.assertTrue(is_allowed_domain("http://example.com", []))
        self.assertTrue(is_allowed_domain("http://example.com", None))
        self.assertTrue(is_allowed_domain(None, ["example.com"]))

        self.assertTrue(
            is_allowed_domain("http://example.com", ("not-example.com", "example.com"))
        )
        self.assertTrue(
            is_allowed_domain(
                "https://example.com/path.html", ("not-example.com", "example.com")
            )
        )

        self.assertFalse(is_allowed_domain("http://example.com", ("not-example.com",)))
        self.assertFalse(
            is_allowed_domain("https://example.com/path.html", ("not-example.com",))
        )

        # Subdomains aren't included by default
        self.assertFalse(is_allowed_domain("http://www.example.com", ("example.com",)))

    def test_generate_client_id_no_ua_ip(self):
        id1 = generate_client_id(None, None)
        id2 = generate_client_id(None, None)
        self.assertNotEqual(id1, id2)

    def test_build_blocked_ip_set_with_file(self):
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch(
                "builtins.open", mock.mock_open(read_data="1.2.3.4\n5.6.7.8\n")
            ):
                blocked = build_blocked_ip_set()
                self.assertIn("1.2.3.4", blocked)
                self.assertIn("5.6.7.8", blocked)

    def test_get_ipproxy_db_success(self):
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("adserver.utils.IP2Proxy.IP2Proxy"):
                db = get_ipproxy_db()
                self.assertIsNotNone(db)

    def test_is_proxy_ip_true(self):
        with mock.patch("adserver.utils.ipproxy_db") as mock_db:
            mock_db.is_proxy.return_value = 1
            self.assertTrue(is_proxy_ip("1.2.3.4"))

    def test_offers_dump_exists_placeholder(self):
        self.assertFalse(offers_dump_exists(datetime.date.today()))


class CachedMethodTest(TestCase):
    """Tests for the cached_method decorator."""

    def test_cached_method_caches_result(self):
        """Second call should return cached value without calling the function."""
        call_count_ref = [0]

        class FakeModel:
            pk = 1001

            @cached_method("my_attr")
            def my_method(self):
                call_count_ref[0] += 1
                return 42

        obj = FakeModel()
        result1 = obj.my_method()
        result2 = obj.my_method()

        self.assertEqual(result1, 42)
        self.assertEqual(result2, 42)
        self.assertEqual(call_count_ref[0], 1)

    def test_cached_method_bypass_cache(self):
        """bypass_cache=True should force re-evaluation."""
        call_count_ref = [0]

        class FakeModel:
            pk = 1002

            @cached_method("my_attr")
            def my_method(self):
                call_count_ref[0] += 1
                return 42

        obj = FakeModel()
        obj.my_method()
        obj.my_method(bypass_cache=True)

        self.assertEqual(call_count_ref[0], 2)

    def test_cached_method_uses_annotated_attr(self):
        """An annotated queryset attribute is returned without calling the function."""
        call_count_ref = [0]

        class FakeModel:
            pk = 1003
            my_attr = 99

            @cached_method("my_attr")
            def my_method(self):
                call_count_ref[0] += 1
                return 42

        obj = FakeModel()
        result = obj.my_method()

        self.assertEqual(result, 99)
        self.assertEqual(call_count_ref[0], 0)

    def test_cached_method_annotated_attr_none_returns_zero(self):
        """An annotated None value (e.g. no DB rows) is treated as 0."""
        call_count_ref = [0]

        class FakeModel:
            pk = 1004
            my_attr = None

            @cached_method("my_attr")
            def my_method(self):
                call_count_ref[0] += 1
                return 42

        obj = FakeModel()
        result = obj.my_method()

        self.assertEqual(result, 0)
        self.assertEqual(call_count_ref[0], 0)
