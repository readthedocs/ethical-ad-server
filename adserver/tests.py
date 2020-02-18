import datetime
import hashlib
import io
import json
import os
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import management
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.db import models
from django.test import Client
from django.test import override_settings
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django_dynamic_fixture import get
from rest_framework.authtoken.models import Token

from .constants import AFFILIATE_CAMPAIGN
from .constants import CLICKS
from .constants import COMMUNITY_CAMPAIGN
from .constants import HOUSE_CAMPAIGN
from .constants import PAID_CAMPAIGN
from .constants import VIEWS
from .decisionengine.backends import AdvertisingDisabledBackend
from .decisionengine.backends import AdvertisingEnabledBackend
from .decisionengine.backends import ProbabilisticFlightBackend
from .forms import AdvertisementCreateForm
from .forms import AdvertisementUpdateForm
from .forms import FlightAdminForm
from .models import AdImpression
from .models import AdType
from .models import Advertisement
from .models import Advertiser
from .models import Campaign
from .models import Click
from .models import Flight
from .models import Publisher
from .models import View
from .utils import anonymize_ip_address
from .utils import anonymize_user_agent
from .utils import calculate_ctr
from .utils import calculate_ecpm
from .utils import GeolocationTuple
from .utils import get_ad_day
from .utils import is_blacklisted_user_agent
from .utils import is_click_ratelimited
from .validators import AdvertisementValidator
from .validators import TargetingParametersValidator


class DoNotTrackTest(TestCase):
    def setUp(self):
        self.dnt_status_url = reverse("dnt-status")
        self.dnt_policy_url = reverse("dnt-policy")

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
    def test_get_ad_day(self):
        day = get_ad_day()
        self.assertTrue(timezone.is_aware(day))
        self.assertIsInstance(day, datetime.datetime)

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


class FormTests(TestCase):
    def setUp(self):
        self.campaign = get(Campaign, name="Test Campaign")
        self.flight = get(Flight, name="Test Flight", campaign=self.campaign)
        self.ad = get(Advertisement, name="Test Ad", flight=self.flight)

    def test_flight_form(self):
        data = {
            "name": "Test Flight",
            "slug": "test-flight",
            "cpc": 1.0,
            "cpm": 1.0,
            "sold_clicks": 100,
            "sold_impressions": 100_000,
            "campaign": self.campaign.pk,
            "live": True,
            "priority_multiplier": 1,
            "start_date": get_ad_day().date(),
            "end_date": get_ad_day().date() + datetime.timedelta(days=2),
        }
        form = FlightAdminForm(data=data)
        self.assertFalse(form.is_valid())

        # A flight can't have both a CPC & CPM
        data["cpc"] = 0.0
        form = FlightAdminForm(data=data)
        self.assertTrue(form.is_valid())

    def test_ad_update_form(self):
        data = {
            "name": "Test Ad",
            "link": "http://example.com",
            "image": None,
            "live": True,
            "text": "This is a test",
        }
        form = AdvertisementUpdateForm(data=data, instance=self.ad)
        self.assertTrue(form.is_valid())
        ad = form.save()

        self.assertEqual(ad.text, "<a>This is a test</a>")

    def test_ad_create_form(self):
        data = {
            "name": "Test Ad",
            "link": "http://example.com",
            "image": None,
            "live": True,
            "text": "This is a test",
        }
        form = AdvertisementCreateForm(data=data, flight=self.flight)
        self.assertFalse(form.is_valid())  # Name exists

        data["name"] = "Another test"
        form = AdvertisementCreateForm(data=data, flight=self.flight)
        self.assertTrue(form.is_valid())


class TestValidators(TestCase):
    def setUp(self):
        self.campaign = get(Campaign)
        self.flight = get(Flight, campaign=self.campaign)
        self.ad = get(
            Advertisement,
            image=None,
            ad_type=None,
            text="<b>Test</b>",
            flight=self.flight,
        )

        one_pixel_png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02\x00\x00\x00\x0bIDATx"
            b"\x9cc\xfa\xcf\x00\x00\x02\x07\x01\x02\x9a\x1c1q\x00\x00\x00"
            b"\x00IEND\xaeB`\x82"
        )
        self.image = SimpleUploadedFile(
            name="test.png", content=one_pixel_png_bytes, content_type="image/png"
        )

    def test_targeting_validator(self):
        validator = TargetingParametersValidator()

        # Ok
        validator({})
        validator({"include_countries": ["US", "CA"]})
        validator({"exclude_countries": ["US", "CA"]})
        validator({"include_keywords": ["django", "vuejs"]})
        validator({"include_state_provinces": ["CA", "ID", "OR"]})
        validator({"include_metro_codes": [1, 2]})

        # Unknown (old) parameters - these raise an error
        self.assertRaises(
            ValidationError, validator, {"include_programming_languages": ["py", "js"]}
        )
        self.assertRaises(
            ValidationError,
            validator,
            {"exclude_programming_languages": ["py", "words"]},
        )
        self.assertRaises(ValidationError, validator, {"include_projects": [1, 2]})
        self.assertRaises(
            ValidationError, validator, {"include_themes": ["alabaster", "rtd"]}
        )
        self.assertRaises(
            ValidationError, validator, {"include_builders": ["sphinx", "mkdocs"]}
        )

        # Invalid
        self.assertRaises(ValidationError, validator, {"include_countries": "ZZ"})
        self.assertRaises(ValidationError, validator, {"include_keywords": [1]})
        self.assertRaises(
            ValidationError, validator, {"include_state_provinces": ["USA"]}
        )

    def test_ad_validator(self):
        text_ad_type = get(AdType, has_text=True, max_text_length=10, has_image=False)
        image_ad_type = get(
            AdType, has_text=False, has_image=True, image_height=None, image_width=None
        )
        validator = AdvertisementValidator()

        # Ok
        validator(self.ad)

        # Text ad
        self.ad.ad_type = text_ad_type
        validator(self.ad)

        # Text too long
        self.ad.text = "*" * 100
        self.assertRaises(ValidationError, validator, self.ad)

        # Invalid tags
        self.ad.text = "<script /><b>Hi</b>"
        validator(self.ad)
        self.assertEqual(self.ad.text, "<b>Hi</b>")

        # Image ad - missing image
        self.ad.text = ""
        self.ad.ad_type = image_ad_type
        self.assertRaises(ValidationError, validator, self.ad)
        self.ad.image = self.image

        # Ok
        validator(self.ad)
        image_ad_type.image_height = 1
        image_ad_type.image_width = 1
        validator(self.ad)

        # Image incorrect dimensions
        image_ad_type.image_height = 3
        image_ad_type.image_width = 3
        self.assertRaises(ValidationError, validator, self.ad)


class TestProtectedModels(TestCase):

    """Test that models extending IndestructibleModel can't be deleted"""

    def setUp(self):
        self.campaign = get(Campaign, name="Test Campaign")

        self.flight = get(Flight, name="Test Flight", campaign=self.campaign)

        self.ad = get(
            Advertisement,
            slug="ad-slug",
            link="http://example.com",
            text="<a>test</a>",
            image=None,
            ad_type=None,
            live=True,
            flight=self.flight,
        )

    def test_delete_model(self):
        self.assertRaises(IntegrityError, self.ad.delete)
        self.assertRaises(IntegrityError, self.campaign.delete)
        self.assertRaises(IntegrityError, self.flight.delete)

    def test_queryset(self):
        self.assertRaises(IntegrityError, Advertisement.objects.all().delete)
        self.assertRaises(IntegrityError, Flight.objects.all().delete)
        self.assertRaises(IntegrityError, Campaign.objects.all().delete)


class TestAdModels(TestCase):
    def setUp(self):
        self.publisher = get(Publisher)
        self.campaign = get(Campaign, publishers=[self.publisher])
        self.flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1000,
            cpc=2.0,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            targeting_parameters={},
        )
        self.ad = get(
            Advertisement,
            name="promo slug",
            slug="ad-slug",
            link="http://example.com",
            live=True,
            image=None,
            ad_type=None,
            text="<b>Test</b>",
            flight=self.flight,
        )

    def test_geo_include(self):
        # Show to countries if no targeting/excludes
        self.assertTrue(self.flight.show_to_geo("US"))
        self.assertTrue(self.flight.show_to_geo("UK"))
        self.assertTrue(self.flight.show_to_geo("CA"))

        self.flight.targeting_parameters = {"include_countries": ["US", "UK"]}
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo("US"))
        self.assertTrue(self.flight.show_to_geo("UK"))
        self.assertFalse(self.flight.show_to_geo("CA"))

        # Unknown geo
        self.assertFalse(self.flight.show_to_geo(None))

    def test_geo_exclude(self):
        self.assertTrue(self.flight.show_to_geo("AZ"))

        self.flight.targeting_parameters = {"exclude_countries": ["US", "AZ"]}
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo("UK"))
        self.assertFalse(self.flight.show_to_geo("AZ"))
        self.assertFalse(self.flight.show_to_geo("US"))

    def test_geo_state_metro_include(self):
        self.assertTrue(self.flight.show_to_geo("US", "CA", 825))

        self.flight.targeting_parameters = {
            "include_countries": ["US"],
            "include_state_provinces": ["CA", "OR"],
        }
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo("US", "CA", 825))
        self.assertFalse(self.flight.show_to_geo("US", "WA", 819))

        self.flight.targeting_parameters = {
            "include_countries": ["US"],
            "include_metro_codes": [819],
        }
        self.flight.save()

        self.assertFalse(self.flight.show_to_geo("US", "CA", 825))
        self.assertTrue(self.flight.show_to_geo("US", "WA", 819))

    def test_keyword_targeting(self):
        self.assertTrue(self.flight.show_to_keywords(["django"]))

        self.flight.targeting_parameters["include_keywords"] = ["django"]
        self.flight.save()

        self.assertFalse(self.flight.show_to_keywords([]))
        self.assertFalse(self.flight.show_to_keywords(["rails"]))
        self.assertTrue(self.flight.show_to_keywords(["django", "rails"]))

    def test_start_date_math(self):
        self.flight.start_date = get_ad_day().date() - datetime.timedelta(days=14)
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.flight.save()

        self.assertEqual(self.flight.days_remaining(), 16)
        # 15/31% through the flight, 0% through the clicks
        self.assertEqual(self.flight.clicks_needed_today(), 484)

        self.flight.start_date = get_ad_day().date()
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.flight.save()

        self.flight.sold_clicks = 1000
        self.assertEqual(self.flight.days_remaining(), 30)
        self.assertEqual(self.flight.clicks_remaining(), 1000)
        self.assertEqual(self.flight.clicks_needed_today(), 33)

        self.flight.sold_clicks = 950
        self.assertEqual(self.flight.clicks_needed_today(), 31)

        self.flight.sold_clicks = 0
        self.assertEqual(self.flight.clicks_needed_today(), 0)

        self.flight.sold_impressions = 10000
        # 0% through the views, 31 days
        self.assertEqual(self.flight.views_needed_today(), 323)

        self.flight.start_date = get_ad_day().date() - datetime.timedelta(days=15)
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        # 16/31% through the flight, 0% through the views
        self.assertEqual(self.flight.views_needed_today(), 5162)

    def test_ad_broken_html(self):
        # Ensures the ad validator is called from the save method
        text = "<a>noendtag"
        self.ad.text = text
        self.ad.save()
        self.assertEqual(self.ad.text, text + "</a>")

    def test_ad_malicious_html(self):
        self.ad.text = '<script>alert("foo")</script>'
        self.ad.save()
        self.assertEqual(self.ad.text, 'alert("foo")')

    def test_ad_remove_inline_style(self):
        self.ad.text = '<b style="color: red">text</b>'
        self.ad.save()
        self.assertEqual(self.ad.text, "<b>text</b>")

    def test_render_ad(self):
        self.assertIn("Test", self.ad.render_ad())

        ad_type = get(
            AdType, template="Nothing here", has_image=False, max_text_length=100
        )
        self.ad.ad_type = ad_type
        self.ad.save()

        self.assertIn("Nothing here", self.ad.render_ad())
        self.assertNotIn("Test", self.ad.render_ad())

    def test_click_view_links_in_render(self):
        self.ad.text = "<a>Call to Action!</a>"
        self.ad.save()

        self.assertIn(self.ad.link, self.ad.render_ad())

        view_url = "http://view.link"
        click_url = "http://view.link"
        output = self.ad.render_ad(click_url=click_url, view_url=view_url)
        self.assertIn(view_url, output)
        self.assertIn(click_url, output)

    def test_campaign_totals(self):
        self.assertAlmostEqual(self.campaign.total_value(), 0.0)

        # Each click is $2
        self.ad.incr(CLICKS, self.publisher)
        self.ad.incr(CLICKS, self.publisher)

        self.assertAlmostEqual(self.campaign.total_value(), 4.0)

        cpm_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_impressions=10,
            cpm=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            targeting_parameters={},
        )
        ad2 = get(
            Advertisement,
            name="promo slug",
            slug="ad-slug2",
            link="http://example.com",
            live=True,
            image=None,
            ad_type=None,
            text="<b>Test</b>",
            flight=cpm_flight,
        )

        # Each view is $0.1
        ad2.incr(VIEWS, self.publisher)
        ad2.incr(VIEWS, self.publisher)
        ad2.incr(VIEWS, self.publisher)

        self.assertAlmostEqual(self.campaign.total_value(), 4.3)

    def test_flight_value_remaining(self):
        self.assertAlmostEqual(self.flight.value_remaining(), 1000 * 2)

        self.flight.sold_clicks = 100
        self.flight.save()
        self.assertAlmostEqual(self.flight.value_remaining(), 100 * 2)

        # Each click is worth $2
        self.ad.incr(CLICKS, self.publisher)
        self.ad.incr(CLICKS, self.publisher)
        self.ad.incr(CLICKS, self.publisher)

        self.flight.refresh_from_db()
        self.assertAlmostEqual(self.flight.value_remaining(), 97 * 2)

        self.flight.cpm = 50.0
        self.flight.cpc = 0
        self.flight.sold_clicks = 0
        self.flight.sold_impressions = 100
        self.flight.save()

        self.assertAlmostEqual(self.flight.value_remaining(), 5.0)

        # Each view is $0.05
        for _ in range(25):
            self.ad.incr(VIEWS, self.publisher)

        self.flight.refresh_from_db()
        self.assertAlmostEqual(self.flight.value_remaining(), 5.0 - (25 * 0.05))

    def test_projected_total_value(self):
        self.assertAlmostEqual(self.flight.projected_total_value(), 1000 * 2)

        # Clicks don't affect the projected total value
        self.ad.incr(CLICKS, self.publisher)
        self.ad.incr(CLICKS, self.publisher)
        self.ad.incr(CLICKS, self.publisher)

        self.flight.refresh_from_db()
        self.assertAlmostEqual(self.flight.projected_total_value(), 1000 * 2)

        self.flight.cpm = 50.0
        self.flight.cpc = 0
        self.flight.sold_clicks = 0
        self.flight.sold_impressions = 100
        self.flight.save()

        self.assertAlmostEqual(self.flight.projected_total_value(), 5.0)


class DecisionEngineTests(TestCase):
    def setUp(self):
        self.publisher = get(Publisher, slug="test-publisher")
        self.ad_type = get(AdType, has_image=False, slug="z")
        self.campaign = get(Campaign, publishers=[self.publisher])
        self.include_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1000,
            cpc=2.0,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            # Only show in US,CA,MX
            targeting_parameters={"include_countries": ["US", "CA", "MX"]},
        )

        self.cpm_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=0,
            sold_impressions=10000,
            cpm=3.50,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            targeting_parameters={"include_countries": ["US", "CA", "MX"]},
        )

        self.advertisement1 = get(
            Advertisement,
            name="ad-slug",
            slug="ad-slug",
            link="http://example.com",
            live=True,
            image=None,
            ad_type=self.ad_type,
            flight=self.include_flight,
        )

        self.exclude_flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=100,
            cpc=5.0,
            # Don't show in AZ
            targeting_parameters={"exclude_countries": ["US", "AZ"]},
        )

        # Don't show in AZ and only for JS projects
        self.advertisement2 = get(
            Advertisement,
            name="promo2-slug",
            link="http://example.com",
            live=True,
            image=None,
            ad_type=self.ad_type,
            flight=self.exclude_flight,
        )

        # No filters
        self.basic_flight = get(
            Flight, live=True, campaign=self.campaign, sold_clicks=100, cpc=0.0
        )
        self.advertisement3 = get(
            Advertisement,
            name="promo3-slug",
            link="http://example.com",
            live=True,
            image=None,
            ad_type=self.ad_type,
            flight=self.basic_flight,
        )

        self.possible_ads = [
            self.advertisement1,
            self.advertisement2,
            self.advertisement3,
        ]

        self.placements = [{"div_id": "a", "ad_type": "z"}]

        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        self.request.geo = GeolocationTuple("US", "CA", None)

        self.backend = AdvertisingEnabledBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

        self.probabilistic_backend = ProbabilisticFlightBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

    def test_ads_disabled(self):
        backend = AdvertisingDisabledBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        ad, _ = backend.get_ad_and_placement()
        self.assertIsNone(ad)

    def test_before_start_date(self):
        flights = self.backend.get_candidate_flights()
        self.assertTrue(flights.exists())

        # Change flight start dates to the future
        for flight in (self.include_flight, self.exclude_flight, self.basic_flight):
            flight.start_date = get_ad_day().date() + datetime.timedelta(days=1)
            flight.save()

        # Now none of the flights are selected (they start in the future)
        flights = self.backend.get_candidate_flights()
        self.assertFalse(flights.exists())

    def test_nonlive_flight(self):
        flights = self.backend.get_candidate_flights()
        self.assertTrue(flights.exists())

        for flight in (self.include_flight, self.exclude_flight, self.basic_flight):
            flight.live = False
            flight.save()

        flights = self.backend.get_candidate_flights()
        self.assertFalse(flights.exists())

    def test_no_clicks_needed(self):
        self.assertTrue(self.backend.filter_flight(self.include_flight))

        self.include_flight.sold_clicks = 0
        self.include_flight.save()
        self.assertFalse(self.backend.filter_flight(self.include_flight))
        self.assertEqual(self.include_flight.clicks_remaining(), 0)

    def test_no_views_needed(self):
        # Switch promo to a CPM flight
        self.advertisement1.flight = self.cpm_flight
        self.advertisement1.save()

        self.assertTrue(self.backend.filter_flight(self.cpm_flight))

        self.cpm_flight.sold_impressions = 32
        self.cpm_flight.save()
        self.assertTrue(self.backend.filter_flight(self.cpm_flight))
        self.assertEqual(self.cpm_flight.views_remaining(), 32)

        self.cpm_flight.sold_impressions = 0
        self.cpm_flight.save()
        self.assertFalse(self.backend.filter_flight(self.cpm_flight))

    def test_flight_clicks(self):
        # Tests the flight_clicks_today, flight_total_clicks optimizations
        backend = AdvertisingEnabledBackend(
            request=self.request,
            placements=self.placements,
            publisher=self.publisher,
            ad_slug=self.advertisement1.slug,
        )

        self.assertEqual(self.include_flight.clicks_remaining(), 1000)
        self.assertEqual(self.include_flight.total_clicks, 0)
        self.assertEqual(self.include_flight.clicks_today(), 0)
        flights = backend.get_candidate_flights()
        self.assertEqual(len(flights), 1)

        # Add 2 clicks
        self.advertisement1.incr(CLICKS, self.publisher)
        self.advertisement1.incr(CLICKS, self.publisher)

        # Refresh the data on the include_flight - gets the denormalized views
        self.include_flight.refresh_from_db()

        self.assertEqual(self.include_flight.clicks_remaining(), 998)
        self.assertEqual(self.include_flight.total_clicks, 2)
        self.assertEqual(self.include_flight.clicks_today(), 2)

        # Change those 2 clicks to yesterday
        impression = self.advertisement1.impressions.all()[0]
        impression.date = (get_ad_day() - datetime.timedelta(days=1)).date()
        impression.save()

        # Add 1 click for today
        self.advertisement1.incr(CLICKS, self.publisher)

        # Refresh the data on the include_flight - gets the denormalized views
        self.include_flight.refresh_from_db()

        self.assertEqual(self.include_flight.clicks_remaining(), 997)
        self.assertEqual(self.include_flight.clicks_today(), 1)

    def test_flight_geo_targeting(self):
        # Remove the flight without targeting for this test
        self.basic_flight.live = False
        self.basic_flight.save()

        ad, _ = self.backend.get_ad_and_placement()
        self.assertTrue(ad in (self.advertisement1, self.advertisement2))

        self.backend.country_code = "US"
        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement1)

        self.backend.country_code = "MX"
        ad, _ = self.backend.get_ad_and_placement()
        self.assertTrue(ad in (self.advertisement1, self.advertisement2))

        self.backend.country_code = "FO"
        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement2)

        self.backend.country_code = "AZ"
        ad, _ = self.backend.get_ad_and_placement()
        self.assertIsNone(ad)

        self.backend.country_code = "RANDOM"
        ad, _ = self.backend.get_ad_and_placement()
        self.assertEqual(ad, self.advertisement2)

    def test_clicks_needed(self):
        self.assertEqual(self.include_flight.clicks_needed_today(), 33)

        clicks_to_simulate = 10
        for _ in range(clicks_to_simulate):
            self.advertisement1.incr(CLICKS, self.publisher)

        # Refresh the data on the include_flight - gets the denormalized views
        self.include_flight.refresh_from_db()

        self.assertEqual(self.include_flight.clicks_needed_today(), 23)

        # Set to a date in the past
        self.include_flight.end_date = get_ad_day().date() - datetime.timedelta(days=2)
        self.assertEqual(
            self.include_flight.clicks_needed_today(),
            self.include_flight.sold_clicks - clicks_to_simulate,
        )

    def test_views_needed(self):
        # Switch promo to a CPM flight
        self.advertisement1.flight = self.cpm_flight
        self.advertisement1.save()

        self.assertEqual(self.cpm_flight.clicks_needed_today(), 0)
        # 0% through the flight, 31 days
        self.assertEqual(self.cpm_flight.views_needed_today(), 323)

        views_to_simulate = 10
        for _ in range(views_to_simulate):
            self.advertisement1.incr(VIEWS, self.publisher)

        # Refresh the data on the include_flight - gets the denormalized views
        self.cpm_flight.refresh_from_db()

        self.assertEqual(self.cpm_flight.views_needed_today(), 313)

        # Set to a date in the past
        self.cpm_flight.end_date = get_ad_day().date() - datetime.timedelta(days=2)
        self.assertEqual(
            self.cpm_flight.views_needed_today(),
            self.cpm_flight.sold_impressions - views_to_simulate,
        )

    def test_database_queries_made(self):
        with self.assertNumQueries(1):
            flights = list(self.probabilistic_backend.get_candidate_flights())
            self.assertEqual(len(flights), 3)

        with self.assertNumQueries(1):
            # This should just be the same query from `get_candidate_flights` above
            flight = self.probabilistic_backend.select_flight()

        with self.assertNumQueries(1):
            # One query to get the specific ad for the chosen flight
            ad = self.probabilistic_backend.select_ad_for_flight(flight)
            self.assertTrue(ad in self.possible_ads, ad)

        with self.assertNumQueries(2):
            # Two total queries to get an ad placement
            ad, _ = self.probabilistic_backend.get_ad_and_placement()
            self.assertTrue(ad in self.possible_ads, ad)

    def test_click_probability(self):
        # Remove existing flights
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        priority_range = [1, 2, 10, 50, 100, 10000]

        flight1 = get(Flight, campaign=self.campaign, live=True, sold_clicks=100)
        flight2 = get(Flight, campaign=self.campaign, live=True, sold_clicks=100)

        self.advertisement1.flight = flight1
        self.advertisement2.flight = flight2
        self.advertisement1.save()
        self.advertisement2.save()

        for flight1_priority in priority_range:
            for flight2_priority in priority_range:
                # Adjust priorities
                flight1.priority_multiplier = flight1_priority
                flight2.priority_multiplier = flight2_priority
                flight1.save()
                flight2.save()

                flight1_prob = flight1.weighted_clicks_needed_today()
                flight2_prob = flight2.weighted_clicks_needed_today()
                total = flight1_prob + flight2_prob

                with mock.patch("random.randint") as randint:

                    randint.return_value = -1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, None)

                    randint.return_value = 0
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement1)

                    randint.return_value = flight1_prob - 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement1)

                    randint.return_value = flight1_prob
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement1)

                    randint.return_value = flight1_prob + 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement2)

                    randint.return_value = total - 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement2)

                    randint.return_value = total
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, self.advertisement2)

                    randint.return_value = total + 1
                    ad, _ = self.probabilistic_backend.get_ad_and_placement()
                    self.assertEqual(ad, None)

    def test_campaign_type_priority(self):
        # First disable all the flights from the test case constructor
        for flight in Flight.objects.all():
            flight.live = False
            flight.save()

        flights = self.probabilistic_backend.get_candidate_flights()
        self.assertFalse(flights.exists())

        # Paid
        paid_campaign = get(
            Campaign, campaign_type=PAID_CAMPAIGN, publishers=[self.publisher]
        )
        paid_flight = get(
            Flight,
            campaign=paid_campaign,
            live=True,
            cpc=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        paid_ad = get(
            Advertisement,
            name="paid",
            slug="test-paid-ad",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=paid_flight,
        )

        # Affiliate
        affiliate_campaign = get(
            Campaign, campaign_type=AFFILIATE_CAMPAIGN, publishers=[self.publisher]
        )
        affiliate_flight = get(
            Flight,
            campaign=affiliate_campaign,
            live=True,
            cpc=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        affiliate_ad = get(
            Advertisement,
            name="affiliate",
            slug="test-affiliate-ad",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=affiliate_flight,
        )

        # Community
        community_campaign = get(
            Campaign, campaign_type=COMMUNITY_CAMPAIGN, publishers=[self.publisher]
        )
        community_flight = get(
            Flight,
            campaign=community_campaign,
            live=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        community_ad = get(
            Advertisement,
            name="community",
            slug="test-community-ad",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=community_flight,
        )

        # House
        house_campaign = get(
            Campaign, campaign_type=HOUSE_CAMPAIGN, publishers=[self.publisher]
        )
        house_campaign.campaign_type = HOUSE_CAMPAIGN
        house_campaign.save()
        house_flight = get(
            Flight,
            campaign=house_campaign,
            live=True,
            sold_clicks=100,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
        )
        house_ad = get(
            Advertisement,
            name="house",
            slug="test-house-ad",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=house_flight,
        )

        # Paid before affiliate or community
        ad, _ = self.probabilistic_backend.get_ad_and_placement()
        self.assertEqual(ad, paid_ad)

        paid_flight.live = False
        paid_flight.save()

        # Affiliate before house or community
        ad, _ = self.probabilistic_backend.get_ad_and_placement()
        self.assertEqual(ad, affiliate_ad)

        affiliate_flight.live = False
        affiliate_flight.save()

        # Community before house
        ad, _ = self.probabilistic_backend.get_ad_and_placement()
        self.assertEqual(ad, community_ad)


class BaseApiTest(TestCase):
    def setUp(self):
        self.publisher = self.publisher1 = get(Publisher, slug="test-publisher")
        self.publisher2 = get(Publisher, slug="another-publisher")
        self.campaign = get(Campaign, slug="campaign-slug", publishers=[self.publisher])
        self.flight = get(
            Flight, live=True, campaign=self.campaign, sold_clicks=1000, cpc=1.0
        )
        self.ad_type = get(AdType, has_image=False, slug="z")
        self.ad = get(
            Advertisement,
            slug="ad-slug",
            name="ad",
            link="http://example.com",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=self.flight,
        )

        self.placements = [{"div_id": "a", "ad_type": self.ad_type.slug}]
        self.data = {"placements": self.placements, "publisher": self.publisher.slug}

        self.user = get(get_user_model(), username="test-user")
        self.user.publishers.add(self.publisher)
        self.token = Token.objects.create(user=self.user)
        self.url = reverse("api:decision")

        self.ip_address = "8.8.8.8"
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36"

        self.client = Client(HTTP_AUTHORIZATION="Token {}".format(self.token))


class AdDecisionApiTests(BaseApiTest):
    def test_get_request(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_post_request(self):
        resp = self.client.post(self.url)
        self.assertTrue(400 <= resp.status_code <= 499)

        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

    def test_invalid_auth(self):
        client = Client()
        resp = client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 401)

        client = Client(HTTP_AUTHORIZATION="invalid")
        resp = client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 401)

    def test_not_live(self):
        self.ad.live = False
        self.ad.save()

        # Not live - shouldn't be displayed
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json, {})

    def test_force_ad(self):
        self.data["force_ad"] = "unknown-slug"
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json, {})

        # Mark a live ad to non-live
        self.ad.live = False
        self.ad.save()

        # Forcing the ad ignores "live"
        self.data["force_ad"] = "ad-slug"
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertTrue("id" in resp_json)
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

    def test_force_campaign(self):
        self.data["force_campaign"] = "unknown-campaign"
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json, {})

        # Force the ad campaign
        self.data["force_campaign"] = self.campaign.slug
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertTrue("id" in resp_json)
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

    def test_unknown_ad_type(self):
        data = {
            "placements": [{"div_id": "a", "ad_type": "unknown"}],
            "publisher": self.publisher.slug,
        }
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json, {}, resp_json)

    def test_invalid_publisher(self):
        # Missing publisher
        data = {"placements": [{"div_id": "a", "ad_type": "unknown"}]}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)

        # Unknown publisher
        data["publisher"] = "does-not-exist"
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_publishers(self):
        # the user has no permissions on this publisher
        data = {"placements": self.placements, "publisher": self.publisher2.slug}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 403, resp.content)

        self.user.publishers.add(self.publisher2)
        data = {"placements": self.placements, "publisher": self.publisher2.slug}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {})

        # Allow this publisher on the campaign
        self.campaign.publishers.add(self.publisher2)
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

    def test_campaign_types(self):
        community_campaign = get(
            Campaign, publishers=[self.publisher], campaign_type=COMMUNITY_CAMPAIGN
        )
        house_campaign = get(
            Campaign, publishers=[self.publisher], campaign_type=HOUSE_CAMPAIGN
        )

        data = {
            "placements": self.placements,
            "publisher": self.publisher.slug,
            "campaign_types": [PAID_CAMPAIGN],
        }
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

        # Try community only
        data["campaign_types"] = [COMMUNITY_CAMPAIGN]
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {}, resp_json)

        # Set the flight to a community campaign and verify that it is returned
        self.flight.campaign = community_campaign
        self.flight.save()
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

        # Try multiple campaign types
        data["campaign_types"] = [PAID_CAMPAIGN, HOUSE_CAMPAIGN]
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {}, resp_json)

        # Set the flight to a house campaign and verify that it is returned
        self.flight.campaign = house_campaign
        self.flight.save()
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

        # try an invalid campaign type
        data["campaign_types"] = ["unknown"]
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_keywords(self):
        data = {
            "placements": self.placements,
            "publisher": self.publisher.slug,
            "campaign_types": [PAID_CAMPAIGN],
            "keywords": [""],  # Blank keyword - should be ok
        }
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

        # Lots of keywords but not too many
        data["keywords"] = [f"a-{i}" for i in range(100)]
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp_json["id"], "ad-slug", resp_json)

        # Too many keywords - reject it!
        data["keywords"] = [f"a-{i}" for i in range(101)]
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)


class AdvertiserApiTests(BaseApiTest):
    def setUp(self):
        super().setUp()

        self.advertiser1 = get(
            Advertiser, name="Test Advertiser", slug="test-advertiser"
        )
        self.advertiser2 = get(
            Advertiser, name="Another Advertiser", slug="another-advertiser"
        )

        self.user.advertisers.add(self.advertiser1)
        self.campaign.advertiser = self.advertiser1
        self.campaign.save()

        # Urls
        self.advertiser_list_url = reverse("api:advertisers-list")
        self.advertiser1_detail_url = reverse(
            "api:advertisers-detail", args=[self.advertiser1.slug]
        )
        self.advertiser2_detail_url = reverse(
            "api:advertisers-detail", args=[self.advertiser2.slug]
        )
        self.advertiser1_report_url = reverse(
            "api:advertisers-report", args=[self.advertiser1.slug]
        )
        self.advertiser2_report_url = reverse(
            "api:advertisers-report", args=[self.advertiser2.slug]
        )

    def test_advertiser_access(self):
        # User has access to advertiser1 but not advertiser2
        resp = self.client.get(
            self.advertiser_list_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["slug"], self.advertiser1.slug)

        for url in (self.advertiser1_detail_url, self.advertiser1_report_url):
            resp = self.client.get(url, content_type="application/json")
            self.assertEqual(resp.status_code, 200, resp.content)

        for url in (self.advertiser2_detail_url, self.advertiser2_report_url):
            resp = self.client.get(url, content_type="application/json")
            self.assertEqual(resp.status_code, 404, resp.content)

        # With access to advertiser2, the APIs succeed
        self.user.advertisers.add(self.advertiser2)
        for url in (self.advertiser2_detail_url, self.advertiser2_report_url):
            resp = self.client.get(url, content_type="application/json")
            self.assertEqual(resp.status_code, 200, resp.content)

    def test_advertiser_report(self):
        resp = self.client.get(
            self.advertiser1_report_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["days"], [])
        self.assertEqual(data["total"]["clicks"], 0)
        self.assertEqual(data["total"]["views"], 0)

        self.ad.incr(VIEWS, self.publisher1)
        self.ad.incr(VIEWS, self.publisher1)
        self.ad.incr(CLICKS, self.publisher1)

        # These still count even though they're on a different publisher
        self.ad.incr(VIEWS, self.publisher2)
        self.ad.incr(CLICKS, self.publisher2)

        resp = self.client.get(
            self.advertiser1_report_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["total"]["clicks"], 2)
        self.assertEqual(data["total"]["views"], 3)

        # Test flight and advertisement details
        self.assertEqual(len(data["flights"]), 1)
        self.assertEqual(data["flights"][0]["slug"], self.flight.slug)
        self.assertEqual(data["flights"][0]["report"]["total"]["clicks"], 2)
        self.assertEqual(data["flights"][0]["report"]["total"]["views"], 3)
        self.assertEqual(len(data["flights"][0]["report"]["days"]), 1)

        self.assertEqual(len(data["flights"][0]["advertisements"]), 1)
        self.assertEqual(data["flights"][0]["advertisements"][0]["slug"], self.ad.slug)
        self.assertEqual(
            data["flights"][0]["advertisements"][0]["report"]["total"]["clicks"], 2
        )
        self.assertEqual(
            data["flights"][0]["advertisements"][0]["report"]["total"]["views"], 3
        )
        self.assertEqual(
            len(data["flights"][0]["advertisements"][0]["report"]["days"]), 1
        )


class PublisherApiTests(BaseApiTest):
    def setUp(self):
        super().setUp()

        # Urls
        self.publisher_list_url = reverse("api:publishers-list")
        self.publisher1_detail_url = reverse(
            "api:publishers-detail", args=[self.publisher1.slug]
        )
        self.publisher2_detail_url = reverse(
            "api:publishers-detail", args=[self.publisher2.slug]
        )
        self.publisher1_report_url = reverse(
            "api:publishers-report", args=[self.publisher1.slug]
        )
        self.publisher2_report_url = reverse(
            "api:publishers-report", args=[self.publisher2.slug]
        )

    def test_publisher_access(self):
        # User has access to publisher1 but not publisher2
        resp = self.client.get(self.publisher_list_url, content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["slug"], self.publisher1.slug)

        for url in (self.publisher1_detail_url, self.publisher1_report_url):
            resp = self.client.get(url, content_type="application/json")
            self.assertEqual(resp.status_code, 200, resp.content)

        for url in (self.publisher2_detail_url, self.publisher2_report_url):
            resp = self.client.get(url, content_type="application/json")
            self.assertEqual(resp.status_code, 404, resp.content)

        # With access to publisher2, the APIs succeed
        self.user.publishers.add(self.publisher2)
        for url in (self.publisher2_detail_url, self.publisher2_report_url):
            resp = self.client.get(url, content_type="application/json")
            self.assertEqual(resp.status_code, 200, resp.content)

    def test_publisher_report(self):
        resp = self.client.get(
            self.publisher1_report_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["days"], [])
        self.assertEqual(data["total"]["clicks"], 0)
        self.assertEqual(data["total"]["views"], 0)

        self.ad.incr(VIEWS, self.publisher1)
        self.ad.incr(VIEWS, self.publisher1)
        self.ad.incr(CLICKS, self.publisher1)

        # For publisher 2, these shouldn't count
        self.ad.incr(VIEWS, self.publisher2)
        self.ad.incr(CLICKS, self.publisher2)

        resp = self.client.get(
            self.publisher1_report_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["total"]["clicks"], 1)
        self.assertEqual(data["total"]["views"], 2)


class AdvertisingIntegrationTests(BaseApiTest):
    def setUp(self):
        super().setUp()

        self.user.publishers.add(self.publisher2)
        self.campaign.publishers.add(self.publisher2)

        self.page_url = "http://example.com"

        # To be counted, the UA and IP must be valid, non-blacklisted/non-bots
        self.proxy_client = Client(
            HTTP_USER_AGENT=self.user_agent, REMOTE_ADDR=self.ip_address
        )

    def test_ad_view_and_tracking(self):
        data = {"placements": self.placements, "publisher": self.publisher1.slug}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        nonce = data["nonce"]

        # At this point, the ad has been "offered" but not "viewed"
        impression = self.ad.impressions.filter(publisher=self.publisher1).first()
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.views, 0)

        # Simulate an ad view and verify it was viewed
        view_url = reverse(
            "view-proxy", kwargs={"advertisement_id": self.ad.pk, "nonce": nonce}
        )

        resp = self.proxy_client.get(view_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Billed view")

        # Verify an impression was written
        impression = self.ad.impressions.filter(publisher=self.publisher1).first()
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.views, 1)

        # Ensure also that a view object is written
        self.assertEqual(
            View.objects.filter(
                advertisement=self.ad, publisher=self.publisher1
            ).count(),
            1,
        )

        # Simulate for a different publisher
        data = {"placements": self.placements, "publisher": self.publisher2.slug}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        impression = self.ad.impressions.filter(publisher=self.publisher2).first()
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.views, 0)

    def test_ad_click_and_tracking(self):
        data = {"placements": self.placements, "publisher": self.publisher1.slug}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        nonce = data["nonce"]

        # At this point, the ad has been "offered" but not "clicked"
        impression = self.ad.impressions.filter(publisher=self.publisher1).first()
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.clicks, 0)

        # Simulate an ad click
        click_url = reverse(
            "click-proxy", kwargs={"advertisement_id": self.ad.pk, "nonce": nonce}
        )
        resp = self.proxy_client.get(click_url, HTTP_REFERER=self.page_url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["X-Adserver-Reason"], "Billed click")

        # Verify an impression was written
        impression = self.ad.impressions.filter(publisher=self.publisher1).first()
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.clicks, 1)

        # Ensure also that a click object is written
        clicks = Click.objects.filter(advertisement=self.ad, publisher=self.publisher1)
        self.assertEqual(clicks.count(), 1)
        click = clicks.first()

        # Ip is anonymized
        self.assertEqual(click.ip, "8.8.0.0")
        self.assertEqual(click.publisher, self.publisher1)
        self.assertEqual(click.advertisement, self.ad)
        self.assertEqual(click.os_family, "Mac OS X")
        self.assertEqual(click.url, self.page_url)

    @override_settings(ADSERVER_RECORD_VIEWS=False)
    def test_record_views_false(self):
        data = {"placements": self.placements, "publisher": self.publisher1.slug}
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        nonce = resp.json()["nonce"]

        # Simulate an ad view and verify it was viewed
        view_url = reverse(
            "view-proxy", kwargs={"advertisement_id": self.ad.pk, "nonce": nonce}
        )

        resp = self.proxy_client.get(view_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Billed view")

        # Verify an impression was written
        impression = self.ad.impressions.filter(publisher=self.publisher1).first()
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.views, 1)

        # Ensure also that a view object was NOT written due to ADSERVER_RECORD_VIEWS=False
        self.assertFalse(
            View.objects.filter(
                advertisement=self.ad, publisher=self.publisher1
            ).exists()
        )


class TestProxyViews(BaseApiTest):
    def setUp(self):
        # Even though this test doesn't use the API,
        # I want the base setup of the API tests
        super().setUp()

        self.staff_user = get(get_user_model(), is_staff=True, username="staff-user")

        self.offer = self.ad.offer_ad(self.publisher)
        self.nonce = self.offer["nonce"]

        self.client = Client(
            HTTP_USER_AGENT=self.user_agent, REMOTE_ADDR=self.ip_address
        )
        self.url = reverse(
            "view-proxy", kwargs={"advertisement_id": self.ad.pk, "nonce": self.nonce}
        )
        self.click_url = reverse(
            "click-proxy", kwargs={"advertisement_id": self.ad.pk, "nonce": self.nonce}
        )

    def test_view_tracking_valid(self):
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Billed view")

    def test_view_tracking_invalid_nonce(self):
        url = reverse(
            "view-proxy",
            kwargs={"advertisement_id": self.ad.pk, "nonce": "invalidnonce"},
        )
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Old/Nonexistent nonce")

    def test_view_tracking_internal_ip(self):
        client = Client(HTTP_USER_AGENT=self.user_agent, REMOTE_ADDR="127.0.0.1")
        resp = client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Internal IP")

    def test_view_tracking_staff(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Staff impression")

    def test_view_tracking_bot(self):
        bot_ua = (
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        )

        resp = self.client.get(self.url, HTTP_USER_AGENT=bot_ua)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Bot impression")

    def test_view_tracking_unknown_ua(self):
        unknown_ua = "Unrecognized UA"
        resp = self.client.get(self.url, HTTP_USER_AGENT=unknown_ua)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Adserver-Reason"], "Unrecognized user agent")

    def test_view_tracking_invalid_ad(self):
        url = reverse(
            "view-proxy", kwargs={"advertisement_id": 99999, "nonce": "invalidnonce"}
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_click_tracking_valid(self):
        resp = self.client.get(self.click_url)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], self.ad.link)
        self.assertEqual(resp["X-Adserver-Reason"], "Billed click")

        # Don't track dupes
        resp = self.client.get(self.click_url)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], self.ad.link)
        self.assertEqual(resp["X-Adserver-Reason"], "Old/Nonexistent nonce")

    @override_settings(ADSERVER_CLICK_RATELIMITS=["1/s", "1/m"])
    def test_click_tracking_ratelimit(self):
        resp = self.client.get(self.click_url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["X-Adserver-Reason"], "Billed click")

        # Click the ad again with a new nonce
        offer = self.ad.offer_ad(self.publisher)
        nonce = offer["nonce"]
        click_url = reverse(
            "click-proxy", kwargs={"advertisement_id": self.ad.pk, "nonce": nonce}
        )
        resp = self.client.get(click_url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["X-Adserver-Reason"], "Ratelimited impression")

    def test_click_tracking_invalid_targeting(self):
        self.ad.flight.targeting_parameters = {"include_countries": ["CA"]}
        self.ad.flight.save()

        with mock.patch("adserver.views.get_geolocation") as get_geo:
            get_geo.return_value = {
                "country_code": "FR",
                "region": None,
                "dma_code": None,
            }
            resp = self.client.get(self.click_url)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["X-Adserver-Reason"], "Invalid targeting impression")


class TestAdvertiserCrudViews(TestCase):

    """Test the advertiser CRUD interface for creating and updating ads."""

    def setUp(self):
        self.advertiser = get(
            Advertiser, name="Test Advertiser", slug="test-advertiser"
        )
        self.campaign = get(
            Campaign,
            name="Test Campaign",
            slug="test-campaign",
            advertiser=self.advertiser,
        )
        self.flight = get(
            Flight, name="Test Flight", slug="test-flight", campaign=self.campaign
        )
        self.ad_type = get(AdType, name="Ad Type", has_image=False)
        self.ad = get(Advertisement, name="Test Ad", slug="test-ad", flight=self.flight)

        self.user = get(
            get_user_model(), username="test-user", advertisers=[self.advertiser]
        )

    def test_flight_list_view(self):
        url = reverse("flight_list", kwargs={"advertiser_slug": self.advertiser.slug})

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.flight.name)

    def test_flight_detail_view(self):
        url = reverse(
            "flight_detail",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad.name)

    def test_ad_detail_view(self):
        url = reverse(
            "advertisement_detail",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.ad.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad.name)

    def test_ad_update_view(self):
        url = reverse(
            "advertisement_update",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.ad.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad.name)

        data = {
            "name": "New Name",
            "live": True,
            "link": "http://example.com",
            "text": "Sample text",
            "image": None,
        }
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302)

        # Verify the DB was updated
        self.ad.refresh_from_db()
        self.assertEqual(self.ad.name, data["name"])

    def test_ad_create_view(self):
        url = reverse(
            "advertisement_create",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create advertisement")

        data = {
            "name": "New Name",
            "live": True,
            "link": "http://example.com",
            "text": "Sample text",
            "image": None,
            "ad_type": self.ad_type.pk,
        }
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Advertisement.objects.filter(flight=self.flight, name="New Name").exists()
        )


class TestReportViews(TestCase):

    """These are the HTML reports that logged-in advertisers and publishers see."""

    def setUp(self):
        self.advertiser1 = get(
            Advertiser, name="Test Advertiser", slug="test-advertiser"
        )
        self.advertiser2 = get(
            Advertiser, name="Another Advertiser", slug="another-advertiser"
        )
        self.publisher1 = get(Publisher, slug="test-publisher")
        self.publisher2 = get(Publisher, slug="another-publisher")

        self.user = get(get_user_model(), username="test-user")
        self.staff_user = get(get_user_model(), is_staff=True, username="staff-user")

    def test_all_advertiser_report_access(self):
        url = reverse("all_advertisers_report")

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Staff only has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_all_publishers_report_access(self):
        url = reverse("all_publishers_report")

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Staff only has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_advertiser_report_access(self):
        url = reverse("advertiser_report", args=[self.advertiser1.slug])
        url2 = reverse("advertiser_report", args=[self.advertiser2.slug])

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Grant that user access
        self.user.advertisers.add(self.advertiser1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # No access to advertiser2
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Staff has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 200)

    def test_publisher_report_access(self):
        url = reverse("publisher_report", args=[self.publisher1.slug])
        url2 = reverse("publisher_report", args=[self.publisher2.slug])

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Grant that user access
        self.user.publishers.add(self.publisher1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # No access to publisher2
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Staff has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 200)


class TestImporterManagementCommand(TestCase):
    def setUp(self):
        base_path = os.path.abspath(os.path.dirname(__file__))
        dumpfile = os.path.join(base_path, "test_fixtures/import_dumpfile.json")
        out = io.StringIO()
        management.call_command("rtdimport", dumpfile, stdout=out)

    def test_import_counts(self):
        self.assertEqual(Publisher.objects.count(), 2)
        self.assertEqual(Advertisement.objects.count(), 2)
        self.assertEqual(Flight.objects.count(), 1)
        self.assertEqual(Campaign.objects.count(), 2)

        # House/Community ads create a single advertiser
        self.assertEqual(Advertiser.objects.count(), 1)

        self.assertEqual(Click.objects.count(), 2)

        # The 2 project impressions collapse into 1
        # since they are the same "publisher" and ad
        self.assertEqual(AdImpression.objects.count(), 3)

    def test_impression_values(self):
        readthedocs_publisher = Publisher.objects.get(slug="readthedocs")
        other_publisher = Publisher.objects.get(slug="readthedocs-pallets")

        # take the total and subtract the impressions from other publishers (150 - 40 - 30)
        self.assertEqual(
            AdImpression.objects.filter(
                advertisement_id=1, publisher=readthedocs_publisher
            ).aggregate(sum_views=models.Sum("views"))["sum_views"],
            80,
        )

        # 40 + 30
        self.assertEqual(
            AdImpression.objects.filter(
                advertisement_id=1, publisher=other_publisher
            ).aggregate(sum_views=models.Sum("views"))["sum_views"],
            70,
        )

        self.assertEqual(
            AdImpression.objects.filter(advertisement_id=1).aggregate(
                sum_views=models.Sum("views")
            )["sum_views"],
            150,
        )


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
