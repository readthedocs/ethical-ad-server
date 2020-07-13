import datetime

from django.db import IntegrityError
from django.utils import timezone
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import VIEWS
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..utils import calculate_ecpm
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

        view_url = "http://view.link"
        click_url = "http://click.link"
        output = self.ad1.offer_ad(self.publisher, self.text_ad_type)
        self.assertEqual(output["body"], "Call to Action & such!")

    def test_ad_country_click_breakdown(self):
        dt = timezone.now() - datetime.timedelta(days=30)
        report = self.ad1.country_click_breakdown(dt, timezone.now())
        self.assertDictEqual(report, {})

        request = self.factory.get("/")

        request.ip_address = "127.0.0.1"
        request.user_agent = "test user agent"

        self.ad1.track_click(request, self.publisher, None)
        self.ad1.track_click(request, self.publisher, None)
        self.ad1.track_impression(request, CLICKS, self.publisher, None)
        self.ad1.track_impression(request, VIEWS, self.publisher, None)  # Doesn't count

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

    def test_campaign_daily_report(self):
        report = self.campaign.daily_reports()
        self.assertEqual(report["days"], [])
        self.assertDictEqual(
            report["total"],
            {"views": 0, "clicks": 0, "cost": 0.0, "ctr": 0.0, "ecpm": 0.0},
        )

        self.ad1.incr(CLICKS, self.publisher)  # $2
        self.ad1.incr(CLICKS, self.publisher)  # $2
        self.ad1.incr(VIEWS, self.publisher)  # $0
        self.ad1.incr(VIEWS, self.publisher)
        self.ad1.incr(VIEWS, self.publisher)

        report = self.campaign.daily_reports()
        self.assertEqual(len(report["days"]), 1)
        self.assertAlmostEqual(report["total"]["views"], 3)
        self.assertAlmostEqual(report["total"]["clicks"], 2)
        self.assertAlmostEqual(report["total"]["cost"], 4.0)
        self.assertAlmostEqual(report["total"]["ctr"], 100 * 2 / 3)
        self.assertAlmostEqual(report["total"]["ecpm"], calculate_ecpm(4.0, 3))

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
