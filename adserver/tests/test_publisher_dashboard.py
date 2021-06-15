from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import PAID_CAMPAIGN
from ..constants import VIEWS
from ..models import AdType
from ..models import Advertisement
from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..models import PublisherPayout


class TestPublisherDashboardViews(TestCase):

    """Test the publisher dashboard interface for configuring publishers and payouts."""

    def setUp(self):
        self.advertiser1 = get(
            Advertiser, name="Test Advertiser", slug="test-advertiser"
        )
        self.publisher1 = get(
            Publisher, slug="test-publisher", allow_paid_campaigns=True
        )
        self.publisher2 = get(
            Publisher, slug="another-publisher", allow_paid_campaigns=True
        )

        self.password = "(@*#$&ASDFKJ"
        self.user = get(
            get_user_model(), email="test1@example.com", username="test-user"
        )
        self.user.set_password(self.password)
        self.user.save()

        self.staff_user = get(get_user_model(), is_staff=True, username="staff-user")

        # Copied from test_reports.py
        # TODO: Extract into a base class?

        self.campaign = get(
            Campaign,
            name="Test Campaign",
            slug="test-campaign",
            advertiser=self.advertiser1,
            campaign_type=PAID_CAMPAIGN,
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

        self.ad_type1 = get(AdType, name="Ad Type", has_image=False)
        self.ad1 = get(
            Advertisement,
            name="Test Ad 1",
            slug="test-ad-1",
            flight=self.flight1,
            ad_type=self.ad_type1,
            image=None,
        )

    def test_publisher_overview(self):
        url = reverse("publisher_main", args=[self.publisher1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertContains(resp, "too small to draw conclusions")

    def test_publisher_embed_code(self):
        url = reverse("publisher_embed", args=[self.publisher1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.publisher1.unauthed_ad_decisions = False
        self.publisher1.save()

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_publisher_settings(self):
        url = reverse("publisher_settings", args=[self.publisher1.slug])

        # Anonymous
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.staff_user)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Save the settings and verify them
        resp = self.client.post(
            url,
            {"allow_affiliate_campaigns": "on", "allow_community_campaigns": "on"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Successfully saved")

        self.publisher1.refresh_from_db()

        self.assertTrue(self.publisher1.allow_affiliate_campaigns)
        self.assertTrue(self.publisher1.allow_community_campaigns)
        self.assertFalse(self.publisher1.allow_house_campaigns)

    def test_publisher_settings_stripe_block(self):
        url = reverse("publisher_settings", args=[self.publisher1.slug])
        self.client.force_login(self.staff_user)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Stripe is not configured")

        # Test that the "connect" link shows if the publisher isn't already connected
        with override_settings(STRIPE_CONNECT_CLIENT_ID="ca_XXXXXXXXXXX"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Connect via Stripe")

        self.publisher1.payout_method = "stripe"
        self.publisher1.stripe_connected_account_id = "acct_XXXXXXX"
        self.publisher1.save()

        # Test the "manage" link if the account is already connected
        with mock.patch("stripe.Account.create_login_link") as create_login_link:
            stripe_url = "http://manage.stripe.com/"
            create_login_link.return_value = mock.MagicMock()
            create_login_link.return_value.url = stripe_url

            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Manage Stripe account")
            self.assertContains(resp, stripe_url)

    def test_publisher_nopaid_notice(self):
        self.client.force_login(self.staff_user)

        url = reverse("publisher_settings", args=[self.publisher1.slug])

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(
            resp, "Your publisher account is not approved for paid campaigns"
        )

        self.publisher1.allow_paid_campaigns = False
        self.publisher1.save()

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, "Your publisher account is not approved for paid campaigns"
        )

    def test_publisher_payouts_list(self):
        url = reverse("publisher_payouts", args=[self.publisher1.slug])

        # Anonymous - redirect to login
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)

        # No access to publisher
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        self.user.publishers.add(self.publisher1)

        # No payments or views
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Balance for this month")

        # Only this months balance
        self.ad1.incr(VIEWS, self.publisher1)
        self.ad1.incr(CLICKS, self.publisher1)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Balance for this month")
        self.assertContains(resp, "1.40")

        get(PublisherPayout, amount=2.5, publisher=self.publisher1, status="paid")
        get(PublisherPayout, amount=2.0, publisher=self.publisher1, status="paid")

        # separate publisher
        get(PublisherPayout, amount=5.2, publisher=self.publisher2, status="paid")

        # Test payout display
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "$2.50")
        self.assertContains(resp, "$2.0")
        self.assertContains(resp, "1.40")  # This month
        self.assertContains(resp, "$5.90")  # total
        self.assertNotContains(resp, "5.20")  # other publisher

    def test_publisher_payout_detail(self):
        payout = get(
            PublisherPayout,
            amount=2.5,
            publisher=self.publisher1,
            note="this is a test",
            method="paypal",
            status="paid",
        )

        url = payout.get_absolute_url()

        # Anonymous - redirect to login
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.client.force_login(self.user)

        # No access to publisher
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        self.user.publishers.add(self.publisher1)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "this is a test")
        self.assertContains(resp, "$2.50")

    def test_publisher_stripe_connect(self):
        url = reverse("publisher_stripe_oauth_connect", args=[self.publisher1.slug])

        # Anonymous - redirect to login
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

        self.user.publishers.add(self.publisher1)
        self.client.force_login(self.user)

        resp = self.client.get(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Stripe is not configured")

        with override_settings(STRIPE_CONNECT_CLIENT_ID="ca_XXXXXXXXXXX"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(
                resp["location"].startswith(
                    "https://connect.stripe.com/express/oauth/authorize"
                )
            )

            self.assertTrue("stripe_state" in self.client.session)
            self.assertTrue("stripe_connect_publisher" in self.client.session)
            self.assertEqual(
                self.client.session["stripe_connect_publisher"], self.publisher1.slug
            )

    def test_publisher_stripe_return(self):
        connect_url = reverse(
            "publisher_stripe_oauth_connect", args=[self.publisher1.slug]
        )
        url = reverse("publisher_stripe_oauth_return")

        self.user.publishers.add(self.publisher1)
        self.client.force_login(self.user)

        # Didn't setup state beforehand
        resp = self.client.get(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "There was a problem connecting your Stripe account")

        # Do Stripe connect - which sets up session state
        with override_settings(STRIPE_CONNECT_CLIENT_ID="ca_XXXXXXXXXXX"):
            self.client.get(connect_url)

            self.assertTrue("stripe_state" in self.client.session)
            self.assertTrue("stripe_connect_publisher" in self.client.session)
            self.assertEqual(
                self.client.session["stripe_connect_publisher"], self.publisher1.slug
            )

        with mock.patch("stripe.OAuth.token") as oauth_token_create:
            account_id = "uid_XXXXX"
            oauth_token_create.return_value = {"stripe_user_id": account_id}

            url += "?code=XXXXX&state={}".format(self.client.session["stripe_state"])

            resp = self.client.get(url, follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Successfully connected your Stripe account")

            # These get deleted
            self.assertFalse("stripe_state" in self.client.session)
            self.assertFalse("stripe_connect_publisher" in self.client.session)

            self.publisher1.refresh_from_db()
            self.assertEqual(self.publisher1.stripe_connected_account_id, account_id)
