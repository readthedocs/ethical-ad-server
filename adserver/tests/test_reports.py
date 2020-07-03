from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import COMMUNITY_CAMPAIGN
from ..constants import HOUSE_CAMPAIGN
from ..constants import PAID_CAMPAIGN
from ..constants import VIEWS
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher


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
                "include_keywords": ["python"],
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
            cpm=1.0,
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
        self.ad1.incr(CLICKS, self.publisher1)

        self.password = "(@*#$&ASDFKJ"
        self.user = get(
            get_user_model(), email="test1@example.com", username="test-user"
        )
        self.user.set_password(self.password)
        self.user.save()

        self.staff_user = get(get_user_model(), is_staff=True, username="staff-user")

    def test_login(self):
        url = reverse("account_login")
        response = self.client.post(
            url, {"login": self.user.email, "password": "invalid-password"}
        )
        self.assertContains(
            response, "The e-mail address and/or password you specified are not correct"
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

    def test_all_advertiser_report_access(self):
        url = reverse("all_advertisers_report")

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

    def test_all_publishers_report_access(self):
        url = reverse("all_publishers_report")

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
        self.client.force_login(self.staff_user)

        url = reverse("advertiser_report", args=[self.advertiser1.slug])
        response = self.client.get(url)
        self.assertContains(response, self.advertiser1.name)
        self.assertContains(response, self.flight1.name)

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
        self.assertContains(response, self.flight2.name)
        self.assertContains(response, self.flight3.name)

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

    def test_publisher_embed_code(self):
        self.client.force_login(self.staff_user)

        url = reverse("publisher_embed", args=[self.publisher1.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.publisher1.unauthed_ad_decisions = False
        self.publisher1.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
