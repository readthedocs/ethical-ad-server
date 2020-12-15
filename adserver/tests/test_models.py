import datetime

from django.db import IntegrityError
from django.utils import timezone
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import VIEWS
from ..models import AdImpression
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..models import Offer
from ..models import Publisher
from ..reports import AdvertiserReport
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

        self.flight.targeting_parameters["exclude_keywords"] = ["rails"]
        self.flight.save()

        self.assertFalse(self.flight.show_to_keywords([]))
        self.assertTrue(self.flight.show_to_keywords(["django"]))
        self.assertFalse(self.flight.show_to_keywords(["django", "rails"]))

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

    def test_view_refund(self):
        request = self.factory.get("/")

        request.ip_address = "127.0.0.1"
        request.user_agent = "test user agent"

        self.flight.cpm = 50.0
        self.flight.cpc = 0
        self.flight.sold_clicks = 0
        self.flight.sold_impressions = 100
        self.flight.save()

        offer = get(Offer, publisher=self.publisher)

        # Each view is $0.05
        view1 = self.ad1.track_view(request, self.publisher, offer=offer)
        view2 = self.ad1.track_view(request, self.publisher, offer=offer)
        view3 = self.ad1.track_view(request, self.publisher, offer=offer)

        for view in (view1, view2, view3):
            self.assertIsNotNone(view)

        self.flight.refresh_from_db()

        self.assertEqual(self.flight.total_views, 3)

        impression = self.ad1.impressions.get(
            publisher=self.publisher, date=view1.date.date()
        )
        self.assertEqual(impression.views, 3)

        report = AdvertiserReport(
            AdImpression.objects.filter(advertisement__flight=self.flight)
        )
        report.generate()
        self.assertAlmostEqual(report.total["views"], 3)
        self.assertAlmostEqual(report.total["cost"], 0.15)

        # Refund 2 of the 3 views
        self.assertTrue(view1.refund())
        self.assertTrue(view2.refund())

        # Ensure you can't double refund
        self.assertFalse(view1.refund())

        self.assertTrue(view1.is_refunded)
        self.assertTrue(view2.is_refunded)
        self.assertFalse(view3.is_refunded)

        # Reload data from the DB
        self.flight.refresh_from_db()
        impression.refresh_from_db()

        self.assertEqual(self.flight.total_views, 1)
        self.assertEqual(impression.views, 1)

        report = AdvertiserReport(
            AdImpression.objects.filter(advertisement__flight=self.flight)
        )
        report.generate()
        self.assertAlmostEqual(report.total["views"], 1)
        self.assertAlmostEqual(report.total["cost"], 0.05)

    def test_click_refund(self):
        request = self.factory.get("/")

        request.ip_address = "127.0.0.1"
        request.user_agent = "test user agent"

        offer = get(Offer, publisher=self.publisher)

        # Each click is $2.00 (cpc)
        click1 = self.ad1.track_click(request, self.publisher, offer=offer)
        click2 = self.ad1.track_click(request, self.publisher, offer=offer)
        click3 = self.ad1.track_click(request, self.publisher, offer=offer)

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

        # Refund 2 of the 3 clicks
        self.assertTrue(click1.refund())
        self.assertTrue(click2.refund())

        # Ensure you can't double refund
        self.assertFalse(click1.refund())

        self.assertTrue(click1.is_refunded)
        self.assertTrue(click2.is_refunded)
        self.assertFalse(click3.is_refunded)

        # Reload data from the DB
        self.flight.refresh_from_db()
        impression.refresh_from_db()

        self.assertEqual(self.flight.total_clicks, 1)
        self.assertEqual(impression.clicks, 1)

        report = AdvertiserReport(
            AdImpression.objects.filter(advertisement__flight=self.flight)
        )
        report.generate()
        self.assertAlmostEqual(report.total["clicks"], 1)
        self.assertAlmostEqual(report.total["cost"], 2.0)
