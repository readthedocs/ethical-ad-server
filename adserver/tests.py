import hashlib
import json
import re

from django.test import TestCase, override_settings
from django.urls import reverse
from django.test.client import RequestFactory

from .utils import (
    anonymize_ip_address,
    anonymize_user_agent,
    calculate_ecpm,
    calculate_ctr,
    is_click_ratelimited,
    is_blacklisted_user_agent,
)


class DoNotTrackTest(TestCase):
    def setUp(self):
        self.dnt_status_url = reverse("adserver:dnt-status")
        self.dnt_policy_url = reverse("adserver:dnt-policy")

    @override_settings(ADSERVER_DO_NOT_TRACK=False)
    def test_dnt_disabled(self):
        for url in (self.dnt_status_url, self.dnt_policy_url):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 404)

    @override_settings(ADSERVER_DO_NOT_TRACK=True)
    def test_dnt_status(self):
        resp = self.client.get(self.dnt_status_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/tracking-status+json")

        # Can't use response.json() because the content-type is non-standard
        data = json.loads(resp.content)
        self.assertEqual(data["tracking"], "T")
        self.assertFalse("policy" in data)

        resp = self.client.get(self.dnt_status_url, HTTP_DNT="1")
        data = json.loads(resp.content)
        self.assertEqual(data["tracking"], "N")

        privacy_policy_url = "http://example.com/policy.txt"
        with override_settings(ADSERVER_PRIVACY_POLICY_URL=privacy_policy_url):
            resp = self.client.get(self.dnt_status_url, HTTP_DNT="1")
            data = json.loads(resp.content)
            self.assertEqual(data["policy"], privacy_policy_url)

    @override_settings(ADSERVER_DO_NOT_TRACK=True)
    def test_dnt_policy(self):
        resp = self.client.get(self.dnt_policy_url)
        self.assertEqual(resp.status_code, 200)

        # Verify the hashes match
        # https://github.com/EFForg/dnt-guide#12-how-to-assert-dnt-compliance
        # https://github.com/EFForg/dnt-policy/blob/master/dnt-policies.json
        shasum = hashlib.new("sha1")
        shasum.update(resp.content)
        self.assertEqual(shasum.hexdigest(), "a18e8dba6848d3fc241b03b88291cb75a3cfec3b")


class UtilsTest(TestCase):
    def test_anonymize_ip(self):
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

    def test_calculate_ctr(self):
        self.assertAlmostEqual(calculate_ctr(100, 0), 0)
        self.assertAlmostEqual(calculate_ctr(1, 1), 100)
        self.assertAlmostEqual(calculate_ctr(1, 10), 10)
        self.assertAlmostEqual(calculate_ctr(5, 25), 20)

    def test_blacklisted_user_agent(self):
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/69.0.3497.100 Safari/537.36"
        )
        self.assertFalse(is_blacklisted_user_agent(ua))
        regexes = [re.compile("Chrome")]
        self.assertTrue(is_blacklisted_user_agent(ua, regexes))

    def test_ratelimited(self):
        factory = RequestFactory()
        request = factory.get("/")

        self.assertFalse(is_click_ratelimited(request))

        # The first request is "not" ratelimited; the second is
        ratelimits = ["1/s", "1/m"]
        self.assertFalse(is_click_ratelimited(request, ratelimits))
        self.assertTrue(is_click_ratelimited(request, ratelimits))
