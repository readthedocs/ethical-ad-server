import datetime
from unittest import mock

from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import FLIGHT_STATE_CURRENT
from ..constants import FLIGHT_STATE_PAST
from ..constants import FLIGHT_STATE_UPCOMING
from ..constants import VIEWS
from ..models import AdImpression
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..models import Offer
from ..models import Publisher
from ..reports import AdvertiserReport
from ..utils import GeolocationData
from ..utils import get_ad_day
from .common import BaseAdModelsTestCase


class TestProtectedModels(BaseAdModelsTestCase):

    """Test that models extending IndestructibleModel can't be deleted"""

    def test_delete_model(self):
        self.assertRaises(IntegrityError, self.ad1.delete)
        self.assertRaises(IntegrityError, self.campaign.delete)
        self.assertRaises(IntegrityError, self.flight.delete)

    def test_queryset(self):
        self.assertRaises(IntegrityError, Advertisement.objects.all().delete)
        self.assertRaises(IntegrityError, Flight.objects.all().delete)
        self.assertRaises(IntegrityError, Campaign.objects.all().delete)


class TestAdModels(BaseAdModelsTestCase):
    def test_geo_include(self):
        # Show to countries if no targeting/excludes
        self.assertTrue(self.flight.show_to_geo(GeolocationData("US")))
        self.assertTrue(self.flight.show_to_geo(GeolocationData("UK")))
        self.assertTrue(self.flight.show_to_geo(GeolocationData("CA")))

        self.flight.targeting_parameters = {"include_countries": ["US", "UK"]}
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo(GeolocationData("US")))
        self.assertTrue(self.flight.show_to_geo(GeolocationData("UK")))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("CA")))

        # Unknown geo
        self.assertFalse(self.flight.show_to_geo(GeolocationData()))

        # Test regions
        self.flight.targeting_parameters = {"include_regions": ["us-ca", "eu"]}
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo(GeolocationData("US")))
        self.assertTrue(self.flight.show_to_geo(GeolocationData("FR")))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("AU")))

    def test_geo_exclude(self):
        self.assertTrue(self.flight.show_to_geo(GeolocationData("AZ")))

        self.flight.targeting_parameters = {"exclude_countries": ["US", "AZ"]}
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo(GeolocationData("UK")))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("AZ")))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("US")))

        # Test regions
        self.flight.targeting_parameters = {
            "exclude_regions": ["exclude", "south-asia"]
        }
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo(GeolocationData("US")))
        self.assertTrue(self.flight.show_to_geo(GeolocationData("FR")))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("CN")))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("IN")))

    def test_geo_state_metro_include(self):
        self.assertTrue(self.flight.show_to_geo(GeolocationData("US", "CA", 825)))

        self.flight.targeting_parameters = {
            "include_countries": ["US"],
            "include_state_provinces": ["CA", "OR"],
        }
        self.flight.save()

        self.assertTrue(self.flight.show_to_geo(GeolocationData("US", "CA", 825)))
        self.assertFalse(self.flight.show_to_geo(GeolocationData("US", "WA", 819)))

        self.flight.targeting_parameters = {
            "include_countries": ["US"],
            "include_metro_codes": [819],
        }
        self.flight.save()

        self.assertFalse(self.flight.show_to_geo(GeolocationData("US", "CA", 825)))
        self.assertTrue(self.flight.show_to_geo(GeolocationData("US", "WA", 819)))

    def test_keyword_targeting(self):
        self.assertTrue(self.flight.show_to_keywords(["django"]))

        self.flight.targeting_parameters["include_keywords"] = ["django"]
        self.flight.save()

        self.assertFalse(self.flight.show_to_keywords([]))
        self.assertFalse(self.flight.show_to_keywords(["rails"]))
        self.assertTrue(self.flight.show_to_keywords(["django", "rails"]))

        self.flight.targeting_parameters["exclude_keywords"] = ["rails"]
        self.flight.save()

        self.assertFalse(self.flight.show_to_keywords([]))
        self.assertTrue(self.flight.show_to_keywords(["django"]))
        self.assertFalse(self.flight.show_to_keywords(["django", "rails"]))

        self.flight.targeting_parameters = {
            "include_topics": ["backend-web", "frontend-web"]
        }
        self.flight.save()

        self.assertFalse(self.flight.show_to_keywords([]))
        self.assertTrue(self.flight.show_to_keywords(["django"]))
        self.assertTrue(self.flight.show_to_keywords(["javascript"]))
        self.assertFalse(self.flight.show_to_keywords(["devops"]))

    def test_publisher_targeting(self):
        self.flight.targeting_parameters["include_publishers"] = [self.publisher.slug]
        self.flight.save()
        self.assertTrue(self.flight.show_on_publisher(self.publisher))

        self.flight.targeting_parameters["include_publishers"] = [
            "another-publisher-slug"
        ]
        self.flight.save()
        self.assertFalse(self.flight.show_on_publisher(self.publisher))

        self.flight.targeting_parameters = {"exclude_publishers": [self.publisher.slug]}
        self.flight.save()
        self.assertFalse(self.flight.show_on_publisher(self.publisher))

        self.flight.targeting_parameters["exclude_publishers"] = [
            "another-publisher-slug"
        ]
        self.flight.save()
        self.assertTrue(self.flight.show_on_publisher(self.publisher))

    def test_domain_targeting(self):
        self.flight.targeting_parameters["include_domains"] = ["example.com"]
        self.flight.save()
        self.assertTrue(
            self.flight.show_on_domain("https://example.com/path/to/resource")
        )

        self.flight.targeting_parameters["include_domains"] = ["another-example.com"]
        self.flight.save()
        self.assertFalse(
            self.flight.show_on_domain("https://example.com/path/to/resource")
        )

        self.flight.targeting_parameters = {
            "exclude_domains": ["bad-domain.com", "example.com"]
        }
        self.flight.save()
        self.assertFalse(
            self.flight.show_on_domain("https://example.com/path/to/resource")
        )

        # If only using exclude, show on blank/unknown URLs
        self.assertTrue(self.flight.show_on_domain(None))
        self.assertTrue(self.flight.show_on_domain(""))

        self.flight.targeting_parameters["exclude_domains"] = ["bad-domain.com"]
        self.flight.save()
        self.assertTrue(
            self.flight.show_on_domain("https://example.com/path/to/resource")
        )

    def test_start_date_math(self):
        self.flight.pacing_interval = 60 * 60 * 24
        self.flight.start_date = get_ad_day().date() - datetime.timedelta(days=14)
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.flight.save()

        self.assertEqual(self.flight.days_remaining(), 16)
        # 15/31% through the flight, 0% through the clicks
        self.assertEqual(self.flight.clicks_needed_this_interval(), 484)

        self.flight.start_date = get_ad_day().date()
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.flight.save()

        self.flight.sold_clicks = 1000
        self.assertEqual(self.flight.days_remaining(), 30)
        self.assertEqual(self.flight.clicks_remaining(), 1000)
        self.assertEqual(self.flight.clicks_needed_this_interval(), 33)

        self.flight.sold_clicks = 950
        self.assertEqual(self.flight.clicks_needed_this_interval(), 31)

        self.flight.sold_clicks = 0
        self.assertEqual(self.flight.clicks_needed_this_interval(), 0)

        self.flight.sold_impressions = 10000
        # 0% through the views, 31 days
        self.assertEqual(self.flight.views_needed_this_interval(), 323)

        self.flight.start_date = get_ad_day().date() - datetime.timedelta(days=15)
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        # 16/31% through the flight, 0% through the views
        self.assertEqual(self.flight.views_needed_this_interval(), 5162)

    def test_custom_interval(self):
        now = get_ad_day()

        # eg. campaign starts on the 1st, today is the 15th, ends on the 31st
        # Completed intervals (through first 14 days) = 14 * 24
        # 1 hour intervals instead of the normal 1 day
        self.flight.pacing_interval = 60 * 60
        self.flight.sold_clicks = 10_050
        self.flight.start_date = now.date() - datetime.timedelta(days=14)
        self.flight.end_date = self.flight.start_date + datetime.timedelta(days=30)
        self.flight.save()

        self.assertEqual(self.flight.sold_days(), 31 * 24)

        with mock.patch("adserver.models.timezone") as tz:
            # Make this deterministic so we don't run into edge cases
            # Set to the start date
            tz.now.return_value = now - datetime.timedelta(days=14)

            percent_remaining = (31 * 24 - 1) / (31 * 24)
            pace = int(self.flight.sold_clicks * percent_remaining)

            self.assertEqual(self.flight.days_remaining(), 31 * 24 - 1)
            self.assertEqual(
                self.flight.clicks_needed_this_interval(),
                self.flight.sold_clicks - pace,
            )

        with mock.patch("adserver.models.timezone") as tz:
            tz.now.return_value = now

            # 17 full days remaining (16 days + 23 hours + current interval)
            self.assertEqual(self.flight.days_remaining(), 17 * 24 - 1)

            percent_remaining = (17 * 24 - 1) / (31 * 24)
            pace = int(self.flight.sold_clicks * percent_remaining)

            # We are 14 full days through the flight and 0% through the clicks
            # So we need all the clicks from the previous 14 days
            # plus whatever is expected in the current interval
            self.assertEqual(
                self.flight.clicks_needed_this_interval(),
                self.flight.sold_clicks - pace,
            )

            # Make the flight overfulfilled
            self.flight.total_clicks = int(self.flight.sold_clicks * 0.80)
            self.assertEqual(self.flight.clicks_needed_this_interval(), 0)

    def test_render_ad(self):
        ad_type1 = get(
            AdType,
            template=None,
            has_image=True,
            max_text_length=100,
            image_height=None,
            image_width=None,
        )

        self.ad1.ad_types.add(ad_type1.pk)
        self.assertIn("<b>Test</b>", self.ad1.render_ad(ad_type1))

        self.ad2.ad_types.add(ad_type1.pk)
        self.assertIn("ethical-ad", self.ad2.render_ad(ad_type1))
        self.assertIn("<img", self.ad2.render_ad(ad_type1))
        self.assertIn("<b>Test</b>", self.ad2.render_ad(ad_type1))

        ad_type2 = get(
            AdType, template="Nothing here", has_image=False, max_text_length=100
        )
        self.ad1.ad_types.remove(ad_type1.pk)
        self.ad1.ad_types.add(ad_type2.pk)
        self.ad1.image = None
        self.ad1.save()

        self.assertIn("Nothing here", self.ad1.render_ad(ad_type2))
        self.assertNotIn("Test", self.ad1.render_ad(ad_type2))

    def test_render_ad_no_pixel(self):
        ad_type1 = get(
            AdType,
            template=None,
            has_image=True,
            max_text_length=100,
            image_height=None,
            image_width=None,
        )

        publisher = get(Publisher, render_pixel=True)

        self.ad1.ad_types.add(ad_type1.pk)
        self.assertIn(
            "<b>Test</b>",
            self.ad1.render_ad(ad_type1, publisher=publisher, view_url="test.com"),
        )
        self.assertIn(
            "ethical-pixel",
            self.ad1.render_ad(ad_type1, publisher=publisher, view_url="test.com"),
        )

        publisher.render_pixel = False

        self.assertIn(
            "<b>Test</b>",
            self.ad1.render_ad(ad_type1, publisher=publisher, view_url="test.com"),
        )
        self.assertNotIn(
            "ethical-pixel",
            self.ad1.render_ad(ad_type1, publisher=publisher, view_url="test.com"),
        )

    def test_click_view_links_in_render(self):
        self.ad1.text = "<a>Call to Action!</a>"
        self.ad1.save()
        self.ad1.ad_types.add(self.text_ad_type)

        self.assertIn(self.ad1.link, self.ad1.render_ad(self.text_ad_type))

        view_url = "http://view.link"
        click_url = "http://view.link"
        output = self.ad1.render_ad(
            self.text_ad_type, click_url=click_url, view_url=view_url
        )
        self.assertIn(view_url, output)
        self.assertIn(click_url, output)

    def test_body_escaping_ad(self):
        self.ad1.text = "<a>Call to Action & such!</a>"
        self.ad1.save()
        self.ad1.ad_types.add(self.text_ad_type)

        request = self.factory.get("/")

        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        self.assertTrue("copy" in output)
        self.assertDictEqual(
            output["copy"],
            {
                "headline": "",
                "content": "Call to Action & such!",
                "cta": "",
            },
        )

    def test_ad_fields_breakout(self):
        self.ad1.text = ""
        self.ad1.headline = "Sample Advertiser"
        self.ad1.content = "Compelling body copy..."
        self.ad1.cta = "Buy Stuff Today!"
        self.ad1.save()
        self.ad1.ad_types.add(self.text_ad_type)

        request = self.factory.get("/")

        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        self.assertTrue("copy" in output)
        self.assertDictEqual(
            output["copy"],
            {
                "headline": self.ad1.headline,
                "content": self.ad1.content,
                "cta": self.ad1.cta,
            },
        )

    def test_ad_country_click_breakdown(self):
        dt = timezone.now() - datetime.timedelta(days=30)
        report = self.ad1.country_click_breakdown(dt, timezone.now())
        self.assertDictEqual(report, {})

        request = self.factory.get("/")

        request.ip_address = "127.0.0.1"
        request.user_agent = "test user agent"

        offer = get(Offer, publisher=self.publisher)

        self.ad1.track_click(request, self.publisher, offer=offer)
        self.ad1.track_click(request, self.publisher, offer=offer)
        self.ad1.track_impression(request, CLICKS, self.publisher, offer=offer)
        self.ad1.track_impression(
            request, VIEWS, self.publisher, offer=offer
        )  # Doesn't count

        report = self.ad1.country_click_breakdown(dt, timezone.now())
        self.assertDictEqual(report, {"Unknown": 3})

    def test_ad_copy(self):
        count_ads = Advertisement.objects.all().count()

        self.ad1.ad_types.set([self.text_ad_type])
        ad1_copy = self.ad1.__copy__()

        # Should be one more ad than before
        self.assertEqual(Advertisement.objects.all().count(), count_ads + 1)

        self.assertNotEqual(ad1_copy, self.ad1)
        self.assertTrue(self.text_ad_type in list(ad1_copy.ad_types.all()))

    def test_campaign_totals(self):
        self.assertAlmostEqual(self.campaign.total_value(), 0.0)

        # Each click is $2
        self.ad1.incr(CLICKS, self.publisher)
        self.ad1.incr(CLICKS, self.publisher)

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

    def test_flight_state(self):
        self.assertEqual(self.flight.state, FLIGHT_STATE_CURRENT)

        self.flight.live = False
        self.assertEqual(self.flight.state, FLIGHT_STATE_UPCOMING)

        self.flight.live = True
        self.flight.start_date = timezone.now().date() - datetime.timedelta(days=50)
        self.flight.end_date = timezone.now().date() - datetime.timedelta(days=20)

        # Still current because it's still live
        self.assertEqual(self.flight.state, FLIGHT_STATE_CURRENT)

        self.flight.live = False
        self.assertEqual(self.flight.state, FLIGHT_STATE_PAST)

    def test_flight_value_remaining(self):
        self.assertAlmostEqual(self.flight.value_remaining(), 1000 * 2)

        self.flight.sold_clicks = 100
        self.flight.save()
        self.assertAlmostEqual(self.flight.value_remaining(), 100 * 2)

        # Each click is worth $2
        self.ad1.incr(CLICKS, self.publisher)
        self.ad1.incr(CLICKS, self.publisher)
        self.ad1.incr(CLICKS, self.publisher)

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
            self.ad1.incr(VIEWS, self.publisher)

        self.flight.refresh_from_db()
        self.assertAlmostEqual(self.flight.value_remaining(), 5.0 - (25 * 0.05))

    def test_projected_total_value(self):
        self.assertAlmostEqual(self.flight.projected_total_value(), 1000 * 2)

        # Clicks don't affect the projected total value
        self.ad1.incr(CLICKS, self.publisher)
        self.ad1.incr(CLICKS, self.publisher)
        self.ad1.incr(CLICKS, self.publisher)

        self.flight.refresh_from_db()
        self.assertAlmostEqual(self.flight.projected_total_value(), 1000 * 2)

        self.flight.cpm = 50.0
        self.flight.cpc = 0
        self.flight.sold_clicks = 0
        self.flight.sold_impressions = 100
        self.flight.save()

        self.assertAlmostEqual(self.flight.projected_total_value(), 5.0)

    @override_settings(ADSERVER_DO_NOT_TRACK=True)
    def test_offer_ad(self):
        request = self.factory.get("/")
        request.ip_address = "1.1.1.1"
        request.user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/90.0.4430.72 Safari/537.36"
        )

        div_id = "foo"
        url = "http://example.com/path.html"
        keywords = ["python", "ruby"]

        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id=div_id,
            keywords=keywords,
            url=url,
        )
        offer = Offer.objects.get(pk=output["nonce"])

        self.assertEqual(offer.publisher, self.publisher)
        self.assertEqual(offer.advertisement, self.ad1)
        self.assertEqual(offer.div_id, div_id)
        self.assertEqual(offer.url, url)
        self.assertEqual(offer.ip, "1.1.0.0")  # anonymized
        self.assertEqual(offer.os_family, "Linux")
        self.assertEqual(offer.browser_family, "Chrome")
        self.assertFalse(offer.viewed)
        self.assertFalse(offer.clicked)
        self.assertFalse(offer.uplifted)
        self.assertIsNone(offer.user_agent)
        self.assertTrue("python" in offer.keywords)
        self.assertTrue("ruby" in offer.keywords)

        # Test the publisher after setting record_offer_details
        self.publisher.record_offer_details = True
        self.publisher.save()

        # Offer the ad again
        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id=div_id,
            keywords=keywords,
            url=url,
        )
        offer = Offer.objects.get(pk=output["nonce"])
        self.assertIsNotNone(offer.user_agent)

    def test_refund(self):
        request = self.factory.get("/")

        request.ip_address = "127.0.0.1"
        request.user_agent = "test user agent"

        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        offer1 = Offer.objects.get(pk=output["nonce"])
        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        offer2 = Offer.objects.get(pk=output["nonce"])
        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        offer3 = Offer.objects.get(pk=output["nonce"])

        view1 = self.ad1.track_view(request, self.publisher, offer=offer1)
        view2 = self.ad1.track_view(request, self.publisher, offer=offer2)
        view3 = self.ad1.track_view(request, self.publisher, offer=offer3)
        self.ad1.invalidate_nonce(VIEWS, offer1.pk)
        self.ad1.invalidate_nonce(VIEWS, offer2.pk)
        self.ad1.invalidate_nonce(VIEWS, offer3.pk)

        # Each click is $2.00 (cpc)
        click1 = self.ad1.track_click(request, self.publisher, offer=offer1)
        click2 = self.ad1.track_click(request, self.publisher, offer=offer2)
        click3 = self.ad1.track_click(request, self.publisher, offer=offer3)
        self.ad1.invalidate_nonce(CLICKS, offer1.pk)
        self.ad1.invalidate_nonce(CLICKS, offer2.pk)
        self.ad1.invalidate_nonce(CLICKS, offer3.pk)

        for offer in (offer1, offer2, offer3):
            offer.refresh_from_db()
            self.assertTrue(offer.viewed)
            self.assertTrue(offer.clicked)
            self.assertFalse(offer.is_refunded)

        for click in (click1, click2, click3):
            self.assertIsNotNone(click)

        self.flight.refresh_from_db()

        self.assertEqual(self.flight.total_clicks, 3)

        impression = self.ad1.impressions.get(
            publisher=self.publisher, date=click1.date.date()
        )
        self.assertEqual(impression.clicks, 3)

        report = AdvertiserReport(
            AdImpression.objects.filter(advertisement__flight=self.flight)
        )
        report.generate()
        self.assertAlmostEqual(report.total["clicks"], 3)
        self.assertAlmostEqual(report.total["cost"], 6.0)

        # Refund 2 of the 3 offers (including the clicks/views)
        self.assertTrue(offer1.refund())
        self.assertTrue(offer2.refund())

        # Ensure you can't double refund
        self.assertFalse(offer1.refund())

        self.assertTrue(offer1.is_refunded)
        self.assertTrue(offer2.is_refunded)
        self.assertFalse(offer3.is_refunded)

        # Ensure the refunded offers still count as clicked/viewed (although those are refunded as well)
        for offer in (offer1, offer2):
            self.assertTrue(offer.viewed)
            self.assertTrue(offer.clicked)

        # Reload data from the DB
        self.flight.refresh_from_db()
        impression.refresh_from_db()

        self.assertEqual(self.flight.total_clicks, 1)
        self.assertEqual(impression.clicks, 1)
        self.assertEqual(self.flight.total_views, 1)
        self.assertEqual(impression.views, 1)

        report = AdvertiserReport(
            AdImpression.objects.filter(advertisement__flight=self.flight)
        )
        report.generate()
        self.assertAlmostEqual(report.total["views"], 1)
        self.assertAlmostEqual(report.total["clicks"], 1)
        self.assertAlmostEqual(report.total["cost"], 2.0)
