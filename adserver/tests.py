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

from .constants import CLICKS
from .constants import COMMUNITY_CAMPAIGN
from .constants import HOUSE_CAMPAIGN
from .constants import PAID_CAMPAIGN
from .constants import VIEWS
from .decisionengine.backends import AdvertisingDisabledBackend
from .decisionengine.backends import AdvertisingEnabledBackend
from .decisionengine.backends import ProbabilisticClicksNeededBackend
from .forms import FlightForm
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
        form = FlightForm(data=data)
        self.assertFalse(form.is_valid())

        # A flight can't have both a CPC & CPM
        data["cpc"] = 0.0
        form = FlightForm(data=data)
        self.assertTrue(form.is_valid())


class TestValidators(TestCase):
    def setUp(self):
        self.campaign = get(Campaign, max_sale_value=2000.0)
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
        self.campaign = get(Campaign, max_sale_value=2000.0)
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

        ret = self.flight.days_remaining()
        self.assertEqual(ret, 16)
        ret = self.flight.clicks_needed_today()
        self.assertEqual(ret, 62)

        self.flight.start_date = get_ad_day().date()
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.flight.save()

        self.flight.sold_clicks = 1000
        self.assertEqual(self.flight.days_remaining(), 30)
        self.assertEqual(self.flight.clicks_needed_today(), 33)

        self.flight.sold_clicks = 950
        self.assertEqual(self.flight.clicks_needed_today(), 31)

        self.flight.sold_clicks = 0
        self.assertEqual(self.flight.clicks_needed_today(), 0)

        self.flight.sold_impressions = 10000
        self.assertEqual(self.flight.views_needed_today(), 333)

        self.flight.start_date = get_ad_day().date() - datetime.timedelta(days=15)
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.assertEqual(self.flight.views_needed_today(), 666)

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


class DecisionEngineTests(TestCase):
    def setUp(self):
        self.publisher = get(Publisher, slug="test-publisher")
        self.ad_type = get(AdType, has_image=False, slug="z")
        self.campaign = get(
            Campaign, publishers=[self.publisher], max_sale_value=2000.0
        )
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
            targeting_parameters={"exclude_countries": ["AZ"]},
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

        self.probabilistic_backend = ProbabilisticClicksNeededBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )

    def test_ads_disabled(self):
        backend = AdvertisingDisabledBackend(
            request=self.request, placements=self.placements, publisher=self.publisher
        )
        ad, _ = backend.get_ad_and_placement()
        self.assertIsNone(ad)

    def test_before_start_date(self):
        ads = self.backend.get_ads_queryset()
        self.assertTrue(ads.exists())

        # Change flight start dates to the future
        for flight in (self.include_flight, self.exclude_flight, self.basic_flight):
            flight.start_date = get_ad_day().date() + datetime.timedelta(days=1)
            flight.save()

        # Now none of the ads are selected (they start in the future)
        ads = self.backend.get_ads_queryset()
        self.assertFalse(ads.exists())

    def test_nonlive_flight(self):
        for flight in (self.include_flight, self.exclude_flight, self.basic_flight):
            flight.live = False
            flight.save()

        ads = self.backend.get_ads_queryset()
        self.assertFalse(ads.exists())

    def test_campaign_max_sale_value(self):
        self.campaign.max_sale_value = 2.0
        self.campaign.save()

        self.include_flight.cpc = 2.0
        self.include_flight.save()

        # First choice should get the promo
        self.assertEqual(self.campaign.total_value(), 0)
        self.assertEqual(
            self.backend.filter_ads([self.advertisement1]), [self.advertisement1]
        )
        self.advertisement1.incr(CLICKS, self.publisher)

        # Second time the promo is filtered out - the promo has met its max_sale_value
        self.assertEqual(self.campaign.total_value(), 2.0)
        self.assertEqual(self.backend.filter_ads([self.advertisement1]), [])

    def test_no_clicks_needed(self):
        ret = self.backend.filter_ads([self.advertisement1])
        self.assertEqual(len(ret), 1)

        self.include_flight.sold_clicks = 0
        self.include_flight.save()
        ret = self.backend.filter_ads([self.advertisement1])
        self.assertEqual(len(ret), 0)
        self.assertEqual(self.include_flight.clicks_remaining(), 0)

    def test_no_views_needed(self):
        # Switch promo to a CPM flight
        self.advertisement1.flight = self.cpm_flight
        self.advertisement1.save()

        ret = self.backend.filter_ads([self.advertisement1])
        self.assertEqual(len(ret), 1)

        self.cpm_flight.sold_impressions = 32
        self.cpm_flight.save()
        ret = self.backend.filter_ads([self.advertisement1])
        self.assertEqual(len(ret), 1)
        self.assertEqual(self.cpm_flight.views_remaining(), 32)

        self.cpm_flight.sold_impressions = 0
        self.cpm_flight.save()
        ret = self.backend.filter_ads([self.advertisement1])
        self.assertEqual(len(ret), 0)

    def test_campaign_total_value(self):
        # Tests the campaign_total_value optimization
        ads = self.backend.get_ads_queryset()
        ads = self.backend.annotate_queryset(ads)

        self.assertEqual(self.campaign.total_value(), 0)
        self.assertEqual(ads[0].flight.campaign.campaign_total_value, 0)

        self.advertisement1.incr(CLICKS, self.publisher)  # +2
        self.advertisement1.incr(CLICKS, self.publisher)  # +2
        self.advertisement2.incr(CLICKS, self.publisher)  # +5

        ads = self.backend.get_ads_queryset()
        ads = self.backend.annotate_queryset(ads)

        self.assertAlmostEqual(self.campaign.total_value(), 9.0)
        self.assertAlmostEqual(ads[0].flight.campaign.campaign_total_value, 9.0)

    def test_flight_clicks(self):
        # Tests the flight_clicks_today, flight_total_clicks optimizations
        backend = AdvertisingEnabledBackend(
            request=self.request,
            placements=self.placements,
            publisher=self.publisher,
            ad_slug=self.advertisement1.slug,
        )

        self.assertEqual(self.include_flight.clicks_remaining(), 1000)
        self.assertEqual(self.include_flight.total_clicks(), 0)
        self.assertEqual(self.include_flight.clicks_today(), 0)
        ads = backend.get_ads_queryset()
        self.assertEqual(len(ads), 1)
        ads = backend.annotate_queryset(ads)
        self.assertEqual(len(ads), 1)
        # Fields added by `annotate_queryset`
        self.assertEqual(ads[0].flight.flight_total_clicks, 0)
        self.assertEqual(ads[0].flight.flight_clicks_today, 0)

        # Add 2 clicks
        self.advertisement1.incr(CLICKS, self.publisher)
        self.advertisement1.incr(CLICKS, self.publisher)

        self.assertEqual(self.include_flight.clicks_remaining(), 998)
        self.assertEqual(self.include_flight.total_clicks(), 2)
        self.assertEqual(self.include_flight.clicks_today(), 2)
        ads = backend.get_ads_queryset()
        ads = backend.annotate_queryset(ads)
        self.assertEqual(ads[0].flight.flight_total_clicks, 2)
        self.assertEqual(ads[0].flight.flight_clicks_today, 2)
        self.assertEqual(self.include_flight.clicks_remaining(), 998)

        # Change those 2 clicks to yesterday
        impression = self.advertisement1.impressions.all()[0]
        impression.date = (get_ad_day() - datetime.timedelta(days=1)).date()
        impression.save()

        # Add 1 click for today
        self.advertisement1.incr(CLICKS, self.publisher)

        self.assertEqual(self.include_flight.clicks_remaining(), 997)
        self.assertEqual(self.include_flight.clicks_today(), 1)
        ads = backend.get_ads_queryset()
        ads = backend.annotate_queryset(ads)
        self.assertEqual(self.include_flight.total_clicks(), 3)
        self.assertEqual(ads[0].flight.flight_total_clicks, 3)
        self.assertEqual(ads[0].flight.flight_clicks_today, 1)

    def test_get_ad(self):
        # Remove the ad without targeting for this test
        self.advertisement3.live = False
        self.advertisement3.save()

        ad, _ = self.backend.get_ad_and_placement()
        self.assertTrue(ad in (self.advertisement1, self.advertisement2))

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
        # Tests an optimization method `annotate_queryset`
        ads = self.backend.get_ads_queryset()
        ads = self.backend.annotate_queryset(ads)
        self.assertEqual(len(ads), 3)

        self.assertEqual(self.include_flight.clicks_needed_today(), 33)
        annotated_flight = [p.flight for p in ads if p.flight == self.include_flight][0]
        self.assertEqual(annotated_flight.clicks_needed_today(), 33)

        clicks_to_simulate = 10
        for _ in range(clicks_to_simulate):
            self.advertisement1.incr(CLICKS, self.publisher)

        self.assertEqual(self.include_flight.clicks_needed_today(), 23)
        ads = self.backend.get_ads_queryset()
        ads = self.backend.annotate_queryset(ads)
        annotated_flight = [p.flight for p in ads if p.flight == self.include_flight][0]
        self.assertEqual(annotated_flight.clicks_needed_today(), 23)

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
        self.assertEqual(self.cpm_flight.views_needed_today(), 333)

        views_to_simulate = 10
        for _ in range(views_to_simulate):
            self.advertisement1.incr(VIEWS, self.publisher)

        self.assertEqual(self.cpm_flight.views_needed_today(), 323)

        # Set to a date in the past
        self.cpm_flight.end_date = get_ad_day().date() - datetime.timedelta(days=2)
        self.assertEqual(
            self.cpm_flight.views_needed_today(),
            self.cpm_flight.sold_impressions - views_to_simulate,
        )

    def test_database_queries_made(self):
        with self.assertNumQueries(1):
            # 1 for promos/campaigns - no queries in a loop
            ads = list(self.backend.get_ads_queryset())
            self.assertEqual(len(ads), 3)

        with self.assertNumQueries(3):
            # One query for campaign max value, one for flight total clicks
            #  and one for flight clicks today
            # For all campaigns/flights
            ads = self.backend.annotate_queryset(ads)
            self.assertEqual(len(ads), 3)

        with self.assertNumQueries(0):
            # Everything should be prefetched at this point
            ads = self.backend.filter_ads(ads)
            self.assertEqual(len(ads), 3)
            ad = self.backend.choose_ad(ads)
            self.assertTrue(ad in self.possible_ads)

    def test_click_probability(self):
        priority_range = range(
            Flight.LOWEST_PRIORITY_MULTIPLIER, Flight.HIGHEST_PRIORITY_MULTIPLIER, 15
        )

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
                possible_ads = [self.advertisement1, self.advertisement2]

                with mock.patch("random.randint") as randint:

                    randint.return_value = -1
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, None)

                    randint.return_value = 0
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, self.advertisement1)

                    randint.return_value = flight1_prob - 1
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, self.advertisement1)

                    randint.return_value = flight1_prob
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, self.advertisement1)

                    randint.return_value = flight1_prob + 1
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, self.advertisement2)

                    randint.return_value = total - 1
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, self.advertisement2)

                    randint.return_value = total
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, self.advertisement2)

                    randint.return_value = total + 1
                    ret = self.probabilistic_backend.choose_ad(possible_ads)
                    self.assertEqual(ret, None)

    def test_ad_type_priority(self):
        paid_campaign = get(Campaign, campaign_type=PAID_CAMPAIGN)
        paid_flight = get(Flight, campaign=paid_campaign, live=True, sold_clicks=100)
        paid_ad = get(
            Advertisement,
            name="paid",
            slug="test-paid-ad",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=paid_flight,
        )

        community_campaign = get(Campaign, campaign_type=COMMUNITY_CAMPAIGN)
        community_flight = get(
            Flight, campaign=community_campaign, live=True, sold_clicks=100
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

        house_campaign = get(Campaign, campaign_type=HOUSE_CAMPAIGN)
        house_flight = get(Flight, campaign=house_campaign, live=True, sold_clicks=100)
        house_ad = get(
            Advertisement,
            name="house",
            slug="test-house-ad",
            ad_type=self.ad_type,
            image=None,
            live=True,
            flight=house_flight,
        )

        # Paid before community
        ret = self.probabilistic_backend.choose_ad([house_ad, community_ad, paid_ad])
        self.assertEqual(ret, paid_ad)

        # Community before house
        ret = self.probabilistic_backend.choose_ad([house_ad, community_ad])
        self.assertEqual(ret, community_ad)


class BaseApiTest(TestCase):
    def setUp(self):
        self.publisher = self.publisher1 = get(Publisher, slug="test-publisher")
        self.publisher2 = get(Publisher, slug="another-publisher")
        self.campaign = get(
            Campaign, publishers=[self.publisher], max_sale_value=2000.0
        )
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

        # Forcing the ad ignores "live"
        self.data["force_ad"] = "ad-slug"
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp_json = resp.json()
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


class TestReportViews(TestCase):
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
        self.assertEqual(Campaign.objects.count(), 1)

        # House ads don't generate an advertiser
        self.assertEqual(Advertiser.objects.count(), 0)

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
