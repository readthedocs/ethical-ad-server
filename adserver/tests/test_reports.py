import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import COMMUNITY_CAMPAIGN
from ..constants import HOUSE_CAMPAIGN
from ..constants import PAID_CAMPAIGN
from ..constants import VIEWS
from ..models import AdImpression
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import AdvertiserImpression
from ..models import Campaign
from ..models import Flight
from ..models import Offer
from ..models import Publisher
from ..models import PublisherPaidImpression
from ..reports import AdvertiserReport
from ..reports import OptimizedAdvertiserReport
from ..reports import OptimizedPublisherPaidReport
from ..reports import PublisherGeoReport
from ..reports import PublisherReport
from ..tasks import daily_update_advertisers
from ..tasks import daily_update_geos
from ..tasks import daily_update_impressions
from ..tasks import daily_update_keywords
from ..tasks import daily_update_placements
from ..tasks import daily_update_publishers
from ..tasks import daily_update_regiontopic
from ..tasks import daily_update_uplift
from ..tasks import update_previous_day_reports
from ..utils import calculate_ecpm
from ..utils import get_ad_day


class TestReportsBase(TestCase):
    def setUp(self):
        self.advertiser1 = get(
            Advertiser, name="Test Advertiser", slug="test-advertiser"
        )
        self.advertiser2 = get(
            Advertiser, name="Another Advertiser", slug="another-advertiser"
        )
        self.publisher1 = get(
            Publisher,
            slug="test-publisher",
            allow_paid_campaigns=True,
            record_placements=True,
        )
        self.publisher2 = get(
            Publisher, slug="another-publisher", allow_paid_campaigns=True
        )

        self.campaign = get(
            Campaign,
            name="Test Campaign",
            slug="test-campaign",
            advertiser=self.advertiser1,
            campaign_type=PAID_CAMPAIGN,
        )
        self.community_campaign = get(
            Campaign,
            name="Community Campaign",
            slug="community-campaign",
            advertiser=self.advertiser2,
            campaign_type=COMMUNITY_CAMPAIGN,
        )
        self.house_campaign = get(
            Campaign,
            name="House Campaign",
            slug="house-campaign",
            advertiser=self.advertiser2,
            campaign_type=HOUSE_CAMPAIGN,
        )

        self.flight1 = get(
            Flight,
            name="Test Flight",
            slug="test-flight",
            campaign=self.campaign,
            live=True,
            cpc=2.0,
            sold_clicks=2000,
            targeting_parameters={
                "include_countries": ["US", "CA"],
                "exclude_countries": ["DE"],
                "include_keywords": ["python", "test", "awesome"],
                "include_metro_codes": [205],
                "include_state_provinces": ["CA", "NY"],
            },
        )

        self.flight2 = get(
            Flight,
            name="Test Flight 2",
            slug="test-flight-2",
            campaign=self.community_campaign,
            live=False,
            cpm=0,
            sold_impressions=1000,
        )
        self.flight3 = get(
            Flight,
            name="Test Flight 3",
            slug="test-flight-3",
            campaign=self.house_campaign,
            live=False,
        )

        self.ad_type1 = get(AdType, name="Ad Type", has_image=False)
        self.ad1 = get(
            Advertisement,
            name="Test Ad 1",
            slug="test-ad-1",
            flight=self.flight1,
            ad_type=self.ad_type1,
            image=None,
        )

        # Trigger some impressions so flights will be shown in the date range
        self.ad1.incr(VIEWS, self.publisher1)
        self.ad1.incr(VIEWS, self.publisher1)
        self.ad1.incr(VIEWS, self.publisher1)
        self.ad1.incr(VIEWS, self.publisher1)
        self.ad1.incr(CLICKS, self.publisher1)

        self.password = "(@*#$&ASDFKJ"
        self.user = get(get_user_model(), email="test1@example.com")
        self.user.set_password(self.password)
        self.user.save()

        self.staff_user = get(get_user_model(), is_staff=True)


class TestReportViews(TestReportsBase):
    """These are the HTML reports that logged-in advertisers and publishers see."""

    def test_login(self):
        url = reverse("account_login")
        response = self.client.post(
            url, {"login": self.user.email, "password": "invalid-password"}
        )
        self.assertContains(
            response, "The email address and/or password you specified are not correct"
        )

    def test_home(self):
        url = reverse("dashboard-home")
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertContains(response, "You do not have access to anything")

        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertContains(response, self.advertiser1.name)
        self.assertContains(response, self.publisher1.name)

    def test_advertiser_redirect(self):
        url = reverse("dashboard-home")
        self.client.force_login(self.user)
        self.user.advertisers.add(self.advertiser1)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)

        # If a user has access to 2 advertisers (or a publisher and an advertiser) don't redirect
        self.user.advertisers.add(self.advertiser2)
        response = self.client.get(url)
        self.assertContains(response, self.advertiser1.name)
        self.assertContains(response, self.advertiser2.name)

        self.user.advertisers.remove(self.advertiser2)
        self.user.publishers.add(self.publisher1)
        response = self.client.get(url)
        self.assertContains(response, self.advertiser1.name)
        self.assertContains(response, self.publisher1.name)

    def test_publisher_redirect(self):
        url = reverse("dashboard-home")
        self.client.force_login(self.user)
        self.user.publishers.add(self.publisher1)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)

        self.user.publishers.add(self.publisher2)
        response = self.client.get(url)
        self.assertContains(response, self.publisher1.name)
        self.assertContains(response, self.publisher2.name)

    def test_staff_advertiser_report_access(self):
        url = reverse("staff_advertisers_report")

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Staff only has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_staff_publishers_report_access(self):
        daily_update_publishers()

        url = reverse("staff_publishers_report")

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url + "?sort=ctr")
        self.assertEqual(response.status_code, 403)

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
        self.assertEqual(response.status_code, 403)

        # Grant that user access
        self.user.advertisers.add(self.advertiser1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # No access to advertiser2
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 403)

        # Staff has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 200)

    def test_advertiser_report_contents(self):
        url = reverse("advertiser_report", args=[self.advertiser1.slug])

        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertContains(response, self.advertiser1.name)

        ad2 = get(
            Advertisement,
            name="Test Ad 2",
            slug="test-ad-2",
            flight=self.flight2,
            ad_type=self.ad_type1,
            image=None,
        )
        ad3 = get(
            Advertisement,
            name="Test Ad 3",
            slug="test-ad-3",
            flight=self.flight3,
            ad_type=self.ad_type1,
            image=None,
        )

        ad2.incr(VIEWS, self.publisher2)
        ad2.incr(VIEWS, self.publisher2)
        ad2.incr(CLICKS, self.publisher2)
        ad3.incr(VIEWS, self.publisher2)
        ad3.incr(VIEWS, self.publisher2)
        ad3.incr(CLICKS, self.publisher2)

        url = reverse("advertiser_report", args=[self.advertiser2.slug])
        response = self.client.get(url)
        self.assertContains(response, self.advertiser2.name)

        # Check staff fields not present since the permission wasn't configured
        self.assertNotContains(response, "eCPM")

        # Add the permission
        self.staff_user.user_permissions.add(
            Permission.objects.get(
                codename="staff_advertiser_fields",
                content_type=ContentType.objects.get_for_model(Advertiser),
            )
        )
        response = self.client.get(url)
        self.assertContains(response, "eCPM")

    def test_advertiser_report_export(self):
        self.client.force_login(self.staff_user)

        url = reverse("advertiser_report_export", args=[self.advertiser1.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Disposition"].startswith("attachment; filename=")
        )

    def test_flight_report_access(self):
        url = reverse("flight_report", args=[self.advertiser1.slug, self.flight1.slug])

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # No access
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Grant that user access
        self.user.advertisers.add(self.advertiser1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Staff has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_flight_report_contents(self):
        self.client.force_login(self.staff_user)

        url = reverse("flight_report", args=[self.advertiser1.slug, self.flight1.slug])
        response = self.client.get(url)
        self.assertContains(response, self.advertiser1.name)
        self.assertContains(response, self.flight1.name)

        url2 = reverse("flight_report", args=[self.advertiser2.slug, self.flight2.slug])
        response = self.client.get(url2)
        self.assertContains(response, self.advertiser2.name)
        self.assertContains(response, self.flight2.name)

        url3 = reverse("flight_report", args=[self.advertiser2.slug, self.flight3.slug])
        response = self.client.get(url3)
        self.assertContains(response, self.advertiser2.name)
        self.assertContains(response, self.flight3.name)

    def test_flight_report_export(self):
        self.client.force_login(self.staff_user)

        url = reverse(
            "flight_report_export", args=[self.advertiser1.slug, self.flight1.slug]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Disposition"].startswith("attachment; filename=")
        )

    def test_advertiser_geo_report_contents(self):
        url = reverse("advertiser_geo_report", args=[self.advertiser1.slug])

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)

        # The data now just comes from metabase
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_advertiser_publisher_report_contents(self):
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher2,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher2,
            viewed=True,
        )

        # Update reporting
        daily_update_impressions()

        url = reverse("advertiser_publisher_report", args=[self.advertiser1.slug])

        # Anonymous
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>3</strong></td>')
        self.assertContains(response, self.publisher1.name)
        self.assertContains(response, self.publisher2.name)
        self.assertNotContains(response, "Belgium")

        # Filter reports
        response = self.client.get(url, {"publisher": self.publisher1.slug})
        self.assertContains(response, '<td class="text-right"><strong>1</strong></td>')
        response = self.client.get(url, {"publisher": self.publisher2.slug})
        self.assertContains(response, '<td class="text-right"><strong>2</strong></td>')

        # Verify the export URL is configured
        self.assertContains(response, "CSV Export")

        export_url = reverse(
            "advertiser_publisher_report_export", args=[self.advertiser1.slug]
        )
        response = self.client.get(export_url)
        self.assertContains(response, "Total,3")

    def test_advertiser_keyword_report(self):
        url = reverse("advertiser_keyword_report", args=[self.advertiser1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)

        resp = self.client.get(url)
        self.assertContains(resp, "Advertiser Keyword Report")

    def test_advertiser_topic_report(self):
        url = reverse("advertiser_topic_report", args=[self.advertiser1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)

        resp = self.client.get(url)
        self.assertContains(resp, "Advertiser Topic Report")

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
        self.assertEqual(response.status_code, 403)

        # Grant that user access
        self.user.publishers.add(self.publisher1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # No access to publisher2
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 403)

        # Staff has has access
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(url2)
        self.assertEqual(response.status_code, 200)

    def test_publisher_report_export(self):
        self.client.force_login(self.staff_user)

        url = reverse("publisher_report_export", args=[self.publisher1.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Disposition"].startswith("attachment; filename=")
        )

    def test_publisher_report_contents(self):
        self.client.force_login(self.staff_user)
        url = reverse("publisher_report", args=[self.publisher1.slug])

        self.ad2 = get(
            Advertisement,
            name="Test Ad 2",
            slug="test-ad-2",
            flight=self.flight2,
            ad_type=self.ad_type1,
            image=None,
        )

        # Paid
        get(Offer, advertisement=self.ad1, publisher=self.publisher1, viewed=True)
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
            clicked=True,
        )

        # Not paid
        get(Offer, advertisement=self.ad2, publisher=self.publisher1, viewed=True)
        get(Offer, advertisement=self.ad2, publisher=self.publisher1, viewed=True)
        get(Offer, advertisement=self.ad2, publisher=self.publisher1, viewed=True)

        # Null offer
        get(Offer, advertisement=None, publisher=self.publisher1)

        # Update reporting
        daily_update_impressions()

        # Generate the report (used to check data)
        report = PublisherReport(AdImpression.objects.filter(publisher=self.publisher1))
        report.generate()

        # Check the actual data
        self.assertEqual(len(report.results), 1)
        self.assertAlmostEqual(report.total["views"], 5)
        self.assertAlmostEqual(report.total["clicks"], 1)
        self.assertAlmostEqual(report.total["decisions"], 6)
        self.assertAlmostEqual(report.total["offers"], 5)
        self.assertAlmostEqual(report.total["paid_offers"], 2)
        self.assertAlmostEqual(report.total["fill_rate"], 100 * 2 / 6)
        self.assertAlmostEqual(report.total["revenue"], 2.0)

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>5</strong></td>')

        # Filter reports
        response = self.client.get(url, {"campaign_type": "paid"})
        self.assertContains(response, '<td class="text-right"><strong>2</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>3</strong></td>'
        )

        # Verify the export URL is configured
        self.assertContains(response, "CSV Export")

        # Check staff fields not present since the permission wasn't configured
        self.assertNotContains(response, "Fill Rate")

        # Add the permission
        self.staff_user.user_permissions.add(
            Permission.objects.get(
                codename="staff_publisher_fields",
                content_type=ContentType.objects.get_for_model(Publisher),
            )
        )
        response = self.client.get(url)
        self.assertContains(response, "Fill Rate")

    def test_publisher_placement_report_contents(self):
        self.client.force_login(self.staff_user)
        url = reverse("publisher_placement_report", args=[self.publisher1.slug])

        get(Offer, publisher=self.publisher1, div_id="p1", viewed=True)
        get(Offer, publisher=self.publisher1, div_id="p2", viewed=True)
        get(Offer, publisher=self.publisher1, div_id="p2", viewed=True)
        get(Offer, publisher=self.publisher1, div_id="ad_23453464", viewed=True)

        # Update reporting
        daily_update_placements(day=datetime.datetime.utcnow().isoformat())

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>3</strong></td>')
        self.assertNotContains(response, "ad_23453464")

        # Filter reports
        response = self.client.get(url, {"div_id": "p1"})
        self.assertContains(response, '<td class="text-right"><strong>1</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>2</strong></td>'
        )
        response = self.client.get(url, {"div_id": "p2"})
        self.assertContains(response, '<td class="text-right"><strong>2</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>1</strong></td>'
        )

        # Filter old default slugs
        response = self.client.get(url, {"div_id": "ad_23453464"})
        self.assertContains(response, '<td class="text-right"><strong>0</strong></td>')

        # Verify the export URL is configured
        self.assertContains(response, "CSV Export")

        export_url = reverse(
            "publisher_placement_report_export", args=[self.publisher1.slug]
        )
        response = self.client.get(export_url, {"div_id": "p2"})
        self.assertContains(response, "Total,2")

    def test_publisher_geo_report_contents(self):
        # Update reporting
        daily_update_geos()

        url = reverse("publisher_geo_report", args=[self.publisher1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        # No data directly on page - handled by metabase
        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Geo Report for ")

    def test_publisher_advertiser_report_contents(self):
        self.client.force_login(self.staff_user)
        url = reverse("publisher_advertiser_report", args=[self.publisher1.slug])

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        self.assertContains(response, self.advertiser1.name)
        self.assertNotContains(response, self.advertiser2.name)

        # Filter reports
        response = self.client.get(url, {"advertiser": self.advertiser1.slug})
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        # Date breakdown, not advertiser breakdown
        self.assertNotContains(response, f"<td>{self.advertiser1.name}</td>")

        response = self.client.get(url, {"advertiser": self.advertiser2.slug})
        self.assertContains(response, '<td class="text-right"><strong>0</strong></td>')

        # Verify the export URL is configured
        self.assertContains(response, "CSV Export")

        export_url = reverse(
            "publisher_advertiser_report_export", args=[self.publisher1.slug]
        )
        response = self.client.get(export_url, {"advertiser": self.advertiser1.slug})
        self.assertContains(response, "Total,4")

    def test_publisher_keyword_report_contents(self):
        # Update reporting
        daily_update_keywords()

        url = reverse("publisher_keyword_report", args=[self.publisher1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        # No data directly on page - handled by metabase
        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Keyword Report")

    def test_publisher_uplift_report_contents(self):
        self.client.force_login(self.staff_user)
        url = reverse("publisher_uplift_report")

        self.ad2 = get(
            Advertisement,
            name="Test Ad 2",
            slug="test-ad-2",
            flight=self.flight2,
            ad_type=self.ad_type1,
            image=None,
        )

        # Paid
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
            uplifted=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
            uplifted=True,
        )

        # Not paid
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher1,
            viewed=True,
            uplifted=True,
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher1,
            viewed=True,
            uplifted=True,
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher1,
            viewed=True,
            uplifted=True,
        )

        # Update reporting
        daily_update_uplift()

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>5</strong></td>')

        # Filter reports
        response = self.client.get(url, {"campaign_type": "paid"})
        self.assertContains(response, '<td class="text-right"><strong>2</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>3</strong></td>'
        )

    def test_staff_advertiser_report_contents(self):
        url = reverse("staff_advertisers_report")

        # Create a house ad
        ad2 = get(
            Advertisement,
            name="Test Ad 2",
            slug="test-ad-2",
            flight=self.flight3,
            ad_type=self.ad_type1,
            image=None,
        )

        # House ad traffic
        get(
            Offer,
            advertisement=ad2,
            publisher=self.publisher1,
            viewed=True,
        )
        get(
            Offer,
            advertisement=ad2,
            publisher=self.publisher1,
            viewed=True,
            clicked=True,
        )

        # Paid traffic
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            viewed=True,
            clicked=True,
        )

        daily_update_impressions()
        daily_update_advertisers()

        # Staff only has has access
        self.client.force_login(self.staff_user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<td class="text-right"><strong>6</strong></td>')

        response = self.client.get(url + "?campaign_type=paid")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>6</strong></td>'
        )

    def test_global_keyword_report_contents(self):
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["test"],
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["test"],
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["test"],
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["awesome"],
            viewed=True,
            clicked=True,
        )

        # Update reporting
        daily_update_keywords()

        self.client.force_login(self.staff_user)
        url = reverse("staff_keyword_report")

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        self.assertContains(response, "test")

        # Filter reports
        response = self.client.get(url, {"keyword": "test"})
        self.assertContains(response, '<td class="text-right"><strong>3</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>2</strong></td>'
        )
        response = self.client.get(url, {"keyword": "awesome"})
        self.assertContains(response, '<td class="text-right"><strong>1</strong></td>')

        # Invalid country
        response = self.client.get(url, {"keyword": "foobar"})
        self.assertContains(response, '<td class="text-right"><strong>0</strong></td>')

        # Disabled for now
        self.assertNotContains(response, "CSV Export")

    def test_global_geo_report_contents(self):
        get(
            Offer,
            publisher=self.publisher1,
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            publisher=self.publisher1,
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            publisher=self.publisher1,
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            publisher=self.publisher1,
            country="FR",
            paid_eligible=True,
            viewed=True,
            clicked=True,
        )

        # Update reporting
        daily_update_geos()

        self.client.force_login(self.staff_user)
        url = reverse("staff_geo_report")

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        self.assertContains(response, "France")
        self.assertNotContains(response, "Belgium")

        # Filter reports
        response = self.client.get(url, {"country": "US"})
        self.assertContains(response, '<td class="text-right"><strong>3</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>2</strong></td>'
        )
        response = self.client.get(url, {"country": "FR"})
        self.assertContains(response, '<td class="text-right"><strong>1</strong></td>')

        # Invalid country
        response = self.client.get(url, {"country": "foobar"})
        self.assertContains(response, '<td class="text-right"><strong>0</strong></td>')

        # Disabled for now
        self.assertNotContains(response, "CSV Export")

    def test_global_region_report_contents(self):
        get(
            Offer,
            publisher=self.publisher1,
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            publisher=self.publisher1,
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            publisher=self.publisher1,
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            publisher=self.publisher1,
            country="MX",
            paid_eligible=True,
            viewed=True,
            clicked=True,
        )

        # Update reporting
        daily_update_geos()

        self.client.force_login(self.staff_user)
        url = reverse("staff_region_report")

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        self.assertContains(response, "<td>us-ca</td>")
        self.assertNotContains(response, "<td>wider-apac</td>")

        # Filter reports
        response = self.client.get(url, {"region": "us-ca"})
        self.assertContains(response, '<td class="text-right"><strong>3</strong></td>')
        self.assertNotContains(
            response, '<td class="text-right"><strong>2</strong></td>'
        )
        response = self.client.get(url, {"region": "latin-america"})
        self.assertContains(response, '<td class="text-right"><strong>1</strong></td>')

        # Invalid country
        response = self.client.get(url, {"region": "foobar"})
        self.assertContains(response, '<td class="text-right"><strong>0</strong></td>')

        # Check CSV export is enabled
        self.assertContains(response, "CSV Export")

    def test_staff_regiontopic_report_contents(self):
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["javascript"],
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["javascript"],
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["javascript"],
            country="US",
            paid_eligible=True,
            viewed=True,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher1,
            keywords=["python"],
            country="MX",
            paid_eligible=True,
            viewed=True,
            clicked=True,
        )

        # Update reporting
        daily_update_regiontopic()

        self.client.force_login(self.staff_user)
        url = reverse("staff_regiontopic_report")

        # All reports
        response = self.client.get(url)
        self.assertContains(response, '<td class="text-right"><strong>4</strong></td>')
        self.assertContains(response, "us-ca:frontend")
        self.assertContains(response, "latin-america:python")
        self.assertNotContains(response, "us-ca:python")

        # Filter reports
        response = self.client.get(url, {"region": "us-ca"})
        self.assertContains(response, "<td>us-ca:frontend")
        self.assertNotContains(response, "<td>eu-aus-nz")

        response = self.client.get(url, {"region": "latin-america"})
        self.assertContains(response, "<td>latin-america:python")
        self.assertNotContains(response, "<td>us-ca:python")

        response = self.client.get(url, {"topic": "python"})
        self.assertContains(response, "<td>latin-america:python")
        self.assertNotContains(response, "<td>us-ca:backend-web")

        response = self.client.get(url, {"topic": "python"})
        self.assertContains(response, "<td>latin-america:python")
        self.assertNotContains(response, "<td>us-ca:frontend-web")

        # 2 filters lead to a date-based view
        response = self.client.get(url, {"topic": "frontend-web", "region": "us-ca"})
        self.assertContains(
            response, "<td>%s" % datetime.datetime.utcnow().strftime("%b")
        )
        self.assertNotContains(response, "<td>us-ca:frontend-web")

        # Invalid country
        response = self.client.get(url, {"region": "foobar"})
        self.assertContains(response, '<td class="text-right"><strong>0</strong></td>')

        # Disabled for now
        self.assertNotContains(response, "CSV Export")


class TestReportClasses(TestReportsBase):
    def setUp(self):
        super().setUp()

    def test_invalid_report_queryset(self):
        with self.assertRaises(RuntimeError):
            PublisherGeoReport(AdImpression.objects.filter(advertisement=self.ad1))

    def test_publisher_report(self):
        # Record a null offer (decisions that don't return an ad)
        factory = RequestFactory()
        request = factory.get("/")
        Advertisement.record_null_offer(
            request=request,
            publisher=self.publisher1,
            ad_type_slug=self.ad_type1.slug,
            div_id="ad-id",
            keywords=[],
            url=None,
        )

        report = PublisherReport(AdImpression.objects.filter(publisher=self.publisher1))
        report.generate()

        self.assertEqual(len(report.results), 1)
        self.assertAlmostEqual(report.total["views"], 4)
        self.assertAlmostEqual(report.total["clicks"], 1)
        # The other views didn't result in an offer/decision
        # Since they didn't go through the "offer_ad" workflow
        self.assertAlmostEqual(report.total["decisions"], 1)

    def test_optimized_publisher_report(self):
        daily_update_publishers()

        queryset = PublisherPaidImpression.objects.filter(publisher=self.publisher1)
        report = OptimizedPublisherPaidReport(queryset)
        report.generate()

        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.total["views"], 4)
        self.assertEqual(report.total["clicks"], 1)
        self.assertAlmostEqual(report.total["revenue"], 2.0)
        self.assertAlmostEqual(report.total["revenue_share"], 1.40)

    def test_optimized_publisher_report_noresults(self):
        # Switch over to unpaid ads
        self.flight1.cpc = 0
        self.flight1.campaign = self.house_campaign
        self.flight1.save()

        daily_update_impressions()
        daily_update_publishers()

        queryset = PublisherPaidImpression.objects.filter(publisher=self.publisher1)
        report = OptimizedPublisherPaidReport(queryset)
        report.generate()

        self.assertEqual(len(report.results), 0)
        self.assertEqual(report.total["views"], 0)
        self.assertEqual(report.total["clicks"], 0)

    def test_optimized_advertiser_report(self):
        daily_update_advertisers()

        queryset = AdvertiserImpression.objects.filter(advertiser=self.advertiser1)
        report = OptimizedAdvertiserReport(queryset)
        report.generate()

        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.total["views"], 4)
        self.assertEqual(report.total["clicks"], 1)
        self.assertAlmostEqual(report.total["cost"], 2.0)

    def test_advertiser_flight_report(self):
        ad2 = get(
            Advertisement,
            name="Test Ad 2",
            slug="test-ad-2",
            flight=self.flight2,
            ad_type=self.ad_type1,
            image=None,
        )

        report = AdvertiserReport(
            AdImpression.objects.filter(advertisement__flight=ad2.flight)
        )
        report.generate()

        self.assertEqual(report.results, [])
        self.assertDictEqual(
            report.total,
            {
                "views": 0,
                "clicks": 0,
                "cost": 0.0,
                "ctr": 0.0,
                "ecpm": 0.0,
                "index": "Total",
            },
        )

        # From the base class setup, ad1 has 4 views and 1 click
        # Generate the report with some views/clicks
        queryset = AdImpression.objects.filter(advertisement__flight=self.ad1.flight)
        report = AdvertiserReport(queryset)
        report.generate()

        self.assertEqual(len(report.results), 1)
        self.assertAlmostEqual(report.total["views"], 4)
        self.assertAlmostEqual(report.total["clicks"], 1)
        self.assertAlmostEqual(report.total["cost"], 2.0)
        self.assertAlmostEqual(report.total["ctr"], 100 * 1 / 4)
        self.assertAlmostEqual(report.total["ecpm"], calculate_ecpm(2.0, 4))


class TestReportTasks(TestReportsBase):
    def test_index_all_reports(self):
        with (
            patch("adserver.tasks.daily_update_geos") as patched_geos,
            patch("adserver.tasks.daily_update_keywords") as patched_keywords,
            patch("adserver.tasks.daily_update_placements") as patched_placements,
            patch("adserver.tasks.daily_update_uplift") as patched_uplift,
        ):
            update_previous_day_reports()

            yesterday = get_ad_day() - datetime.timedelta(days=1)
            patched_geos.assert_called_with(yesterday)

            self.assertTrue(patched_geos.called)
            self.assertTrue(patched_keywords.called)
            self.assertTrue(patched_placements.called)
            self.assertTrue(patched_uplift.called)
