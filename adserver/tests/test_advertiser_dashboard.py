import datetime

import bs4
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django_dynamic_fixture import get
from django_slack.utils import get_backend
from django.conf import settings

from ..constants import PAID_CAMPAIGN
from ..constants import PUBLISHER_HOUSE_CAMPAIGN
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..models import Region
from ..models import Topic
from ..tasks import daily_update_advertisers
from ..utils import get_ad_day
from .common import ONE_PIXEL_PNG_BYTES
from ..auth.models import UserAdvertiserMember


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

        self.factory = RequestFactory()

    def test_advertiser_overview(self):
        url = reverse(
            "advertiser_main", kwargs={"advertiser_slug": self.advertiser.slug}
        )

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Flight is "over"
        self.flight.live = False
        self.flight.start_date = get_ad_day().date() - datetime.timedelta(days=35)
        self.flight.end_date = get_ad_day().date() - datetime.timedelta(days=5)
        self.flight.save()

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no active or upcoming flights")

        # Flight is live and ongoing
        self.flight.end_date = get_ad_day().date() + datetime.timedelta(days=5)
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
        daily_update_advertisers()

        response = self.client.get(url)
        self.assertNotContains(
            response,
            "There are a few steps to getting started with your first ad campaign with us",
        )
        self.assertContains(response, f"Month to date overview for {self.advertiser.name}")

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

        # Make it a reporter who can't request a new flight
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Request a new flight")

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

        # Make it a reporter who can't edit
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Create advertisement")

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
            "days": ["saturday", "sunday"],
        }
        self.flight.save()

        resp = self.client.get(url)
        self.assertContains(resp, "Exclude regions")
        self.assertContains(resp, "Exclude publishers")
        self.assertContains(resp, "Exclude domains")
        self.assertContains(resp, "Mobile traffic: exclude")
        self.assertContains(resp, "Days: Saturday, Sunday")

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
            "niche_distance": 0.5,
            "niche_urls": "\n".join([
                # Make sure comments are stripped properly
                "https://example.com/niche1/ ",
                "https://example.com/niche2/",
            ]),
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
        self.assertEqual(self.flight.niche_targeting, 0.5)

        # Analyzer is always running in testing - no need to check installed apps here
        # However, we are going to import it in the function just in case
        from adserver.analyzer.models import AnalyzedAdvertiserUrl  # noqa
        self.assertEqual(
            AnalyzedAdvertiserUrl.objects.filter(advertiser=self.advertiser, flights=self.flight).count(),
            2,
        )

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

    def test_flight_update_invalid(self):
        url = reverse(
            "flight_update",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        self.client.force_login(self.staff_user)
        self.staff_user.user_permissions.add(
            Permission.objects.get(
                codename="change_flight",
                content_type=ContentType.objects.get_for_model(Flight),
            )
        )

        self.flight.targeting_parameters = {
            "niche_targeting": 0.35,
        }
        self.flight.save()

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Niche: Similarity 0.35 to")

        data = {
            "name": "New Name",
            "cpc": 2.5,
            "cpm": 0,
            "sold_clicks": 250,
            "sold_impressions": 0,
            "live": False,
            "start_date": get_ad_day().date(),
            "end_date": get_ad_day().date() + datetime.timedelta(days=2),
            "priority_multiplier": 1,
            "include_countries": "ABC",
            "exclude_countries": "",
            "include_keywords": "python, django",
            "niche_distance": 0.25,
            "niche_urls": "\n".join([
                "https://example.com/niche1/",
                "invalid-url",
            ]),
        }
        resp = self.client.post(url, data=data)
        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, "&#x27;invalid-url&#x27; is an invalid URL")
        self.assertContains(resp, "ABC is not a valid country code")

    def test_flight_autorenew_view(self):
        """Check that automatic renewals are working."""
        url = reverse(
            "flight_auto_renew",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
                "flight_slug": self.flight.slug,
            },
        )

        self.assertFalse(self.flight.auto_renew)

        # Anonymous - no access
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        user_no_advertisers = get(
            get_user_model(),
            name="test user2",
            email="test2@example.com",
        )

        # Regular user - no access
        self.client.force_login(user_no_advertisers)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        # Regular user - access to this advertiser
        self.client.force_login(self.user)

        # Make it a reporter who can't access
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Flight auto-renewal")

        resp = self.client.post(
            url,
            data={
                "auto_renew": True,
            },
            follow=True,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "Your flight will automatically renew when complete.",
        )
        self.flight.refresh_from_db()
        self.assertTrue(self.flight.auto_renew)

        resp = self.client.post(
            url,
            data={
                "auto_renew": False,
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "Your flight will not automatically renew when complete. "
            "Your account manager will contact you about renewing.",
        )
        self.flight.refresh_from_db()
        self.assertFalse(self.flight.auto_renew)

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

    @override_settings(
        # Use the memory email backend instead of front for testing
        FRONT_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        FRONT_ENABLED=True,
    )
    def test_flight_request_view(self):
        url = reverse(
            "flight_request",
            kwargs={
                "advertiser_slug": self.advertiser.slug,
            },
        )

        # Anonymous - no access
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        # Regular user - access to this advertiser
        self.client.force_login(self.user)

        # Make it a reporter who can't access
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

        self.client.force_login(self.user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Request a new flight")

        # Not modeled on an old flight
        resp = self.client.get(url + "?old_flight=&next=step-2")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "Your account manager will be notified to review your ads and targeting.",
        )

        backend = get_backend()
        backend.reset_messages()

        # Set regions and topics that are available to be chosen
        Region.objects.filter(slug__in=Region.NON_OVERLAPPING_REGIONS).update(
            selectable=True
        )
        Topic.objects.filter(
            slug__in=(
                "devops",
                "backend-web",
                "frontend-web",
                "data-science",
                "security-privacy",
            )
        ).update(selectable=True)

        new_name = "My New Flight"
        today = get_ad_day().date()
        budget = "3599"
        note = "This is a note that should appear in the email"
        data = {
            "name": new_name,
            "start_date": today,
            "end_date": today + datetime.timedelta(days=20),
            "advertisements": [],
            "budget": budget,
            "regions": ["us-ca"],
            "topics": ["devops"],
            "note": note,
        }

        resp = self.client.post(
            url + "?old_flight=&next=step-2", data=data, follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"Successfully setup a new")
        self.assertContains(resp, f"notified your account manager")

        # Email to account manager was sent with budget and note
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith("New Flight Request"))
        html_body = mail.outbox[0].body
        self.assertTrue(note in html_body)
        self.assertTrue(budget in html_body)

        # Verify the slack message was sent
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0]["text"].startswith("New flight request: User="))
        self.assertTrue(budget in messages[0]["text"])
        self.assertTrue(note in messages[0]["text"])

        new_flight = Flight.objects.filter(name=new_name).first()
        self.assertIsNotNone(new_flight)
        self.assertFalse(new_flight.live)
        self.assertEqual(new_flight.targeting_parameters["include_regions"], ["us-ca"])
        self.assertEqual(new_flight.targeting_parameters["include_topics"], ["devops"])

        backend.reset_messages()

        # Modeled on a past flight
        resp = self.client.get(url + "?old_flight=" + self.flight.slug + "&next=step-2")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "Your account manager will be notified to review your ads and targeting.",
        )

        resp = self.client.post(url, data=data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"Successfully setup a new")

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

        # Make it a reporter who can't access
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Edit advertisement")

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

        # Make it a reporter who can't access
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

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

        # Make it a reporter who can't access
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

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

    def test_ad_bulk_create_view(self):
        url = reverse(
            "advertisement_bulk_create",
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
        self.assertContains(response, "Bulk create ads")

        with open(settings.BASE_DIR + "/adserver/tests/data/bulk_ad_upload_invalid.csv") as fd:
            resp = self.client.post(url, data={
                "advertisements": fd,
            })

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Total text for &#x27;Invalid Ad1&#x27; must be 100 or less")

        with open(settings.BASE_DIR + "/adserver/tests/data/bulk_ad_upload.csv") as fd:
            resp = self.client.post(url, data={
                "advertisements": fd,
            })

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Preview and save your ads")

            soup = bs4.BeautifulSoup(resp.content, features="html.parser")
            elem = soup.find("input", attrs={"name": "signed_advertisements"})
            self.assertIsNotNone(elem)

            signed_ads = elem.attrs["value"]

        resp = self.client.post(url, follow=True, data={
            "signed_advertisements": signed_ads,
        })

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Successfully uploaded")

        signed_ads = "invalid"
        resp = self.client.post(url, follow=True, data={
            "signed_advertisements": signed_ads,
        })

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Upload expired or invalid")

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

        # Make it a reporter who can't access
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_REPORTER
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

        response = self.client.get(url)
        self.assertContains(response, "Re-use your previous ads")
        self.assertContains(response, self.ad1.name)

        # Perform the copy
        count_ads = Advertisement.objects.all().count()
        response = self.client.post(url, data={"advertisements": [self.ad1.pk]})
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

        # Make it a manager who can't invite users
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.name)
        self.assertContains(response, self.user.email)
        self.assertNotContains(response, "Invite user")

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

        # Make it a manager who can't invite users
        member = UserAdvertiserMember.objects.get(user=self.user, advertiser=self.advertiser)
        member.role = UserAdvertiserMember.ROLE_MANAGER
        member.save()

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        member.role = UserAdvertiserMember.ROLE_ADMIN
        member.save()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invite user to")

        response = self.client.post(
            url,
            data={"name": "Another User", "email": "another@example.com", "role": UserAdvertiserMember.ROLE_MANAGER},
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
            data={"name": name, "email": email, "role": UserAdvertiserMember.ROLE_MANAGER},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Successfully invited")
        self.assertEqual(User.objects.filter(email=email).count(), 1)

        # Invite the same user again to check that the user isn't created again
        response = self.client.post(
            url,
            data={"name": "Yet Another User", "email": email, "role": UserAdvertiserMember.ROLE_MANAGER},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Successfully invited")
        self.assertEqual(User.objects.filter(email=email).count(), 1)
        self.assertEqual(User.objects.filter(name=name).count(), 1)

        # The 2nd request didn't create a user or update the user's name
        self.assertEqual(User.objects.filter(name="Yet Another User").count(), 0)
