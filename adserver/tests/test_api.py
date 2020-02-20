import datetime
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.test import override_settings
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django_dynamic_fixture import get
from rest_framework.authtoken.models import Token

from ..api.permissions import AdvertiserPermission
from ..api.permissions import PublisherPermission
from ..constants import CLICKS
from ..constants import COMMUNITY_CAMPAIGN
from ..constants import HOUSE_CAMPAIGN
from ..constants import PAID_CAMPAIGN
from ..constants import VIEWS
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Click
from ..models import Flight
from ..models import Publisher
from ..models import View


class ApiPermissionTest(TestCase):
    def setUp(self):
        self.advertiser = get(Advertiser, slug="test-advertiser")
        self.publisher = get(Publisher, slug="test-publisher")

        self.publisher_permission = PublisherPermission()
        self.advertiser_permission = AdvertiserPermission()

        self.user = get(get_user_model(), email="test1@example.com")
        self.staff_user = get(
            get_user_model(), email="test2@example.com", is_staff=True
        )

        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        self.request.user = AnonymousUser()

    def test_publisher_permission(self):
        # obj is not a publisher
        self.assertFalse(
            self.publisher_permission.has_object_permission(self.request, None, None)
        )
        self.assertFalse(
            self.publisher_permission.has_object_permission(
                self.request, None, self.advertiser
            )
        )

        # User not authed
        self.assertFalse(
            self.publisher_permission.has_object_permission(
                self.request, None, self.publisher
            )
        )

        self.request.user = self.user

        # No access on publisher
        self.assertFalse(
            self.publisher_permission.has_object_permission(
                self.request, None, self.publisher
            )
        )

        self.user.publishers.add(self.publisher)

        self.assertTrue(
            self.publisher_permission.has_object_permission(
                self.request, None, self.publisher
            )
        )

        self.request.user = self.staff_user
        self.assertTrue(
            self.publisher_permission.has_object_permission(
                self.request, None, self.publisher
            )
        )

    def test_advertiser_permission(self):
        # obj is not a advertiser
        self.assertFalse(
            self.advertiser_permission.has_object_permission(self.request, None, None)
        )
        self.assertFalse(
            self.advertiser_permission.has_object_permission(
                self.request, None, self.publisher
            )
        )

        # User not authed
        self.assertFalse(
            self.advertiser_permission.has_object_permission(
                self.request, None, self.advertiser
            )
        )

        self.request.user = self.user

        # No access on publisher
        self.assertFalse(
            self.advertiser_permission.has_object_permission(
                self.request, None, self.advertiser
            )
        )

        self.user.advertisers.add(self.advertiser)

        self.assertTrue(
            self.advertiser_permission.has_object_permission(
                self.request, None, self.advertiser
            )
        )

        self.request.user = self.staff_user
        self.assertTrue(
            self.advertiser_permission.has_object_permission(
                self.request, None, self.advertiser
            )
        )


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

        self.staff_user = get(
            get_user_model(), email="test-staff@example.com", is_staff=True
        )
        self.staff_token = Token.objects.create(user=self.staff_user)

        self.ip_address = "8.8.8.8"
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36"

        self.client = Client(HTTP_AUTHORIZATION="Token {}".format(self.token))
        self.staff_client = Client(
            HTTP_AUTHORIZATION="Token {}".format(self.staff_token)
        )


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

    def test_no_placements(self):
        self.data["placements"] = []
        resp = self.client.post(
            self.url, json.dumps(self.data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

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
        data["campaign_types"] = [PAID_CAMPAIGN, HOUSE_CAMPAIGN, "unknown"]
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)

        # No campaign type -> all campaign types are valid
        data["campaign_types"] = []
        resp = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)

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

        # Empty keywords should be fine too
        data["keywords"] = []
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

        # Staff also has access
        resp = self.staff_client.get(
            self.advertiser_list_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["count"], 2)

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

        # Check with a specified start date
        start_date = (timezone.now() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        resp = self.client.get(
            self.advertiser1_report_url,
            data={"start_date": start_date},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["days"], [])
        self.assertEqual(data["total"]["clicks"], 0)
        self.assertEqual(data["total"]["views"], 0)

        # Staff also has access
        resp = self.staff_client.get(
            self.advertiser1_report_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)


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

        # Staff also has access
        resp = self.staff_client.get(
            self.publisher_list_url, content_type="application/json"
        )
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

        # Check with a specified start date
        start_date = (timezone.now() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        resp = self.client.get(
            self.publisher1_report_url,
            data={"start_date": start_date},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["days"], [])
        self.assertEqual(data["total"]["clicks"], 0)
        self.assertEqual(data["total"]["views"], 0)

        # Staff also has access
        resp = self.staff_client.get(
            self.publisher1_report_url, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)


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
        data = {
            "placements": self.placements,
            "publisher": self.publisher1.slug,
            "user_ip": self.ip_address,
            "user_ua": self.user_agent,
        }
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
