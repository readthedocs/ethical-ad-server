import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get

from ..constants import PAID_CAMPAIGN
from ..constants import PUBLISHER_HOUSE_CAMPAIGN
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..utils import get_ad_day
from .common import ONE_PIXEL_PNG_BYTES


User = get_user_model()


class TestAdvertiserDashboardViews(TestCase):

    """Test the advertiser dashboard interface for creating and updating ads."""

    def setUp(self):
        self.publisher = get(
            Publisher, slug="test-publisher", allow_paid_campaigns=True
        )

        self.advertiser = get(
            Advertiser, name="Test Advertiser", slug="test-advertiser"
        )
        self.campaign = get(
            Campaign,
            name="Test Campaign",
            slug="test-campaign",
            advertiser=self.advertiser,
            campaign_type=PAID_CAMPAIGN,
        )
        self.flight = get(
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

        self.ad1 = get(
            Advertisement,
            name="Test Ad 1",
            slug="test-ad-1",
            flight=self.flight,
            image=None,
            content="ad text",
        )
        self.ad2 = get(
            Advertisement,
            name="Test Ad 2",
            slug="test-ad-2",
            flight=self.flight,
            image=SimpleUploadedFile(
                name="test.png", content=ONE_PIXEL_PNG_BYTES, content_type="image/png"
            ),
        )
        self.ad3 = get(
            Advertisement,
            name="Test Ad 3",
            slug="test-ad-3",
            flight=self.flight,
            image=None,
        )

        self.ad_type1 = get(
            AdType,
            name="Ad Type",
            has_image=False,
            max_text_length=100,
            description="test",
        )
        self.ad_type2 = get(
            AdType,
            name="Ad Type 2",
            has_image=True,
            image_height=None,
            image_width=None,
            max_text_length=1000,
            allowed_html_tags="",
        )
        self.ad_type3 = get(
            AdType,
            name="Ad Type 3",
            has_image=False,
            image_height=None,
            image_width=None,
            max_text_length=100,
            allowed_html_tags="",
        )

        self.ad1.ad_types.add(self.ad_type1)
        self.ad2.ad_types.add(self.ad_type2)
        self.ad3.ad_types.add(self.ad_type3)

        self.user = get(
            get_user_model(),
            name="test user",
            email="test@example.com",
            advertisers=[self.advertiser],
        )
        self.staff_user = get(
            get_user_model(),
            is_staff=True,
            name="Staff User",
            email="staff@example.com",
        )

    def advertiser_overview(self):
        url = reverse(
            "advertiser_main", kwargs={"advertiser_slug": self.advertiser.slug}
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.flight.live = False
        self.flight.save()

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no active flights")

        self.flight.live = True
        self.flight.save()

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.flight.name)

        # New advertiser - gets the first time experience
        self.assertContains(
            response,
            "There are a few steps to getting started with your first ad campaign with us",
        )

        # Offer an ad
        request = self.factory.get("/")
        self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.ad_type1,
            div_id="foo",
            keywords=None,
        )

        response = self.client.get(url)
        self.assertNotContains(
            response,
            "There are a few steps to getting started with your first ad campaign with us",
        )
        self.assertContains(response, "Welcome back")

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
        self.assertContains(response, self.ad1.name)

        # Set to a CPM flight
        self.flight.cpm = 2.0
        self.flight.cpc = 0
        self.flight.sold_clicks = 0
        self.flight.sold_impressions = 10000
        self.flight.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad1.name)

    def test_flight_detail_metadata(self):
        url = reverse(
            "flight_detail",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        self.client.force_login(self.user)

        self.flight.prioritize_ads_ctr = False
        self.flight.save()

        resp = self.client.get(url)
        self.assertContains(resp, "Ads are chosen round-robin")

        self.campaign.campaign_type = PUBLISHER_HOUSE_CAMPAIGN
        self.campaign.save()

        resp = self.client.get(url)
        self.assertContains(resp, "House ads controlled by the publisher")

        # Test some includes
        self.flight.targeting_parameters = {
            "include_regions": ["us-ca"],
            "include_topics": ["security-privacy"],
            "include_publishers": ["readthedocs"],
            "include_domains": ["example.com"],
        }
        self.flight.prioritize_ads_ctr = True
        self.flight.save()

        resp = self.client.get(url)
        # self.fail(resp.content)
        self.assertContains(resp, "Ads with higher CTR are prioritized")
        self.assertContains(resp, "Topics:")
        self.assertContains(resp, "Security &amp; privacy")
        self.assertContains(resp, "Include regions:")
        self.assertContains(resp, "US &amp; Canada")
        self.assertContains(resp, "Include publishers")
        self.assertContains(resp, "Include domains")

        # Test some excludes
        self.flight.targeting_parameters = {
            "exclude_regions": ["us-ca"],
            "exclude_publishers": ["readthedocs"],
            "exclude_domains": ["example.com"],
            "mobile_traffic": "exclude",
        }
        self.flight.save()

        resp = self.client.get(url)
        self.assertContains(resp, "Exclude regions")
        self.assertContains(resp, "Exclude publishers")
        self.assertContains(resp, "Exclude domains")
        self.assertContains(resp, "Mobile traffic: exclude")

    def test_flight_create_view(self):
        url = reverse(
            "flight_create",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
            },
        )

        # Anonymous - no access
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        # Regular user - no access
        self.client.force_login(self.user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        # Staff user still requires permission
        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        self.staff_user.user_permissions.add(
            Permission.objects.get(
                codename="add_flight",
                content_type=ContentType.objects.get_for_model(Flight),
            )
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.advertiser.name)

        name = "My new test flight"
        data = {
            "name": name,
            "campaign": self.campaign.pk,
        }
        resp = self.client.post(url, data=data)
        self.assertEqual(resp.status_code, 302)

        self.assertTrue(self.campaign.flights.filter(name=name).exists())

    def test_flight_update_view(self):
        url = reverse(
            "flight_update",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        # Anonymous - no access
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        # Regular user - no access
        self.client.force_login(self.user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        # Staff user still requires permission
        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        self.staff_user.user_permissions.add(
            Permission.objects.get(
                codename="change_flight",
                content_type=ContentType.objects.get_for_model(Flight),
            )
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.flight.name)

        new_name = "New Name"

        data = {
            "name": new_name,
            "cpc": 2.5,
            "cpm": 0,
            "sold_clicks": 250,
            "sold_impressions": 0,
            "live": False,
            "start_date": get_ad_day().date(),
            "end_date": get_ad_day().date() + datetime.timedelta(days=2),
            "priority_multiplier": 1,
            "include_countries": "US  ,  CN",
            "exclude_countries": "",
            "include_keywords": "python, django",
        }
        resp = self.client.post(url, data=data)
        self.assertEqual(resp.status_code, 302)

        # Verify the DB was updated
        self.flight.refresh_from_db()
        self.assertEqual(self.flight.name, new_name)
        self.assertFalse(self.flight.live)
        self.assertAlmostEqual(self.flight.cpc, 2.5)
        self.assertEqual(self.flight.sold_clicks, 250)
        self.assertEqual(self.flight.included_countries, ["US", "CN"])
        self.assertEqual(self.flight.excluded_countries, [])
        self.assertEqual(self.flight.included_keywords, ["python", "django"])

        # Ensure we didn't overwrite the metro and state/province targeting
        self.assertEqual(self.flight.included_state_provinces, ["CA", "NY"])
        self.assertEqual(self.flight.included_metro_codes, [205])

        # Test the no existing targeting case
        self.flight.targeting_parameters = None
        self.flight.save()
        data["include_countries"] = "US,CA"
        resp = self.client.post(url, data=data)
        self.assertEqual(resp.status_code, 302)
        self.flight.refresh_from_db()
        self.assertEqual(self.flight.included_countries, ["US", "CA"])

    def test_flight_renew_view(self):
        url = reverse(
            "flight_renew",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        # Anonymous - no access
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        # Regular user - no access
        self.client.force_login(self.user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        # Staff user still requires permission
        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        self.staff_user.user_permissions.add(
            Permission.objects.get(
                codename="change_flight",
                content_type=ContentType.objects.get_for_model(Flight),
            )
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.flight.name)

        # Save a small update to the flight we're copying
        # We will verify this was copied
        self.flight.priority_multiplier = 10
        self.flight.save()

        new_name = "Renewed Flight"
        today = get_ad_day().date()

        data = {
            "name": new_name,
            "campaign": self.flight.campaign.pk,
            "cpc": 2.5,
            "cpm": 0,
            "sold_clicks": 250,
            "sold_impressions": 0,
            "live": False,
            "start_date": today,
            "end_date": today + datetime.timedelta(days=20),
            "advertisements": [self.ad1.pk, self.ad2.pk],
        }
        resp = self.client.post(url, data=data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"Successfully created new flight")
        self.assertContains(resp, f"via renewal")

        # Verify the new flight was created in the DB
        new_flight = Flight.objects.filter(name=new_name).first()
        self.assertIsNotNone(new_flight)
        self.assertFalse(new_flight.live)
        self.assertAlmostEqual(new_flight.cpc, 2.5)
        self.assertEqual(new_flight.sold_clicks, 250)

        # Fields not on the form
        self.assertEqual(new_flight.included_countries, ["US", "CA"])
        self.assertEqual(new_flight.included_keywords, ["python"])
        self.assertEqual(
            new_flight.priority_multiplier, self.flight.priority_multiplier
        )

        # Ensure the ads were copied and live
        self.assertEqual(new_flight.advertisements.all().count(), 2)
        for ad in new_flight.advertisements.all():
            self.assertTrue(ad.live)

    def test_ad_detail_view(self):
        url = reverse(
            "advertisement_detail",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.ad1.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad1.name)

    def test_ad_update_view(self):
        url = reverse(
            "advertisement_update",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.ad1.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad1.name)

        data = {
            "name": "New Name",
            "live": True,
            "link": "http://example.com",
            "headline": "Some Company: ",
            "content": "Sample text",
            "image": "",
            "ad_types": [self.ad_type1.pk],
        }
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302, response.content)

        # Verify the DB was updated
        self.ad1.refresh_from_db()
        self.assertEqual(self.ad1.name, data["name"])

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
            "headline": "Some Company: ",
            "content": "Sample text",
            "image": "",
            "ad_types": [self.ad_type1.pk],
        }
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Advertisement.objects.filter(flight=self.flight, name="New Name").exists()
        )

    def test_ad_copy_view(self):
        url = reverse(
            "advertisement_copy",
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
        self.assertContains(response, "Copy advertisement")
        self.assertContains(response, self.ad1.name)

        # Goes to the confirm screen
        response = self.client.get(url, data={"source_advertisement": self.ad1.pk})
        self.assertContains(response, "Copy advertisement")
        self.assertContains(response, "Source advertisement")

        # Perform the copy
        count_ads = Advertisement.objects.all().count()
        response = self.client.post(url, data={"source_advertisement": self.ad1.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Advertisement.objects.all().count(), count_ads + 1)

    def test_deprecated_ad_type(self):
        url = reverse(
            "advertisement_create",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad_type3.name)

        # Deprecate the ad type
        self.ad_type3.name += " (Deprecated)"
        self.ad_type3.deprecated = True
        self.ad_type3.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.ad_type3.name)

        # Ad3 has ad type 3
        url = reverse(
            "advertisement_update",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
                "advertisement_slug": self.ad3.slug,
            },
        )

        # Since ad3 has ad type 3, that option is shown
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ad_type3.name)

    def test_authorized_users(self):
        url = reverse(
            "advertiser_users",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.name)
        self.assertContains(response, self.user.email)

        self.user.advertisers.remove(self.advertiser)

        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.user.name)
        self.assertContains(response, "There are no authorized users")

    def test_authorized_users_remove(self):
        url = reverse(
            "advertiser_users_remove",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "user_id": self.user.id,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.name)
        self.assertContains(response, self.user.email)

        # Remove the user from the advertiser
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.advertisers.count(), 0)

        # This user is no longer part of this advertiser
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_authorized_users_invite(self):
        url = reverse(
            "advertiser_users_invite",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
            },
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invite user to")

        response = self.client.post(
            url,
            data={"name": "Another User", "email": "another@example.com"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Successfully invited")

    def test_authorized_users_invite_existing(self):
        url = reverse(
            "advertiser_users_invite",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
            },
        )

        self.client.force_login(self.user)

        name = "Another User"
        email = "another@example.com"

        response = self.client.post(
            url,
            data={"name": name, "email": email},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Successfully invited")
        self.assertEqual(User.objects.filter(email=email).count(), 1)

        # Invite the same user again to check that the user isn't created again
        response = self.client.post(
            url,
            data={"name": "Yet Another User", "email": email},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Successfully invited")
        self.assertEqual(User.objects.filter(email=email).count(), 1)
        self.assertEqual(User.objects.filter(name=name).count(), 1)

        # The 2nd request didn't create a user or update the user's name
        self.assertEqual(User.objects.filter(name="Yet Another User").count(), 0)
