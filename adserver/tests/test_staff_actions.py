from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_dynamic_fixture import get

from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Offer
from ..models import Publisher
from ..staff.forms import CreateAdvertiserForm
from ..staff.forms import StartPublisherPayoutForm
from ..tasks import daily_update_impressions
from .test_publisher_dashboard import TestPublisherDashboardViews

User = get_user_model()


class CreateAdvertiserTest(TestCase):
    def setUp(self):
        self.user = get(
            get_user_model(),
            name="test user",
            email="test@example.com",
        )
        self.staff_user = get(
            get_user_model(),
            is_staff=True,
            name="Staff User",
            email="staff@example.com",
        )

    def test_form(self):
        advertiser_name = "Test Advertiser"
        user_name = "User Name"
        user_email = "user@example.com"
        data = {
            "advertiser_name": advertiser_name,
            "user_name": user_name,
            "user_email": user_email,
        }
        form = CreateAdvertiserForm(data=data)
        self.assertTrue(form.is_valid())
        form.save()

        self.assertTrue(Advertiser.objects.filter(name=advertiser_name).exists())
        self.assertTrue(Campaign.objects.filter(name=advertiser_name).exists())
        advertiser = Advertiser.objects.filter(name=advertiser_name).first()
        self.assertTrue(Flight.objects.filter(campaign__advertiser=advertiser).exists())

        user = User.objects.filter(email=user_email).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.advertisers.count(), 1)

    def test_view(self):
        url = reverse("create-advertiser")

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Non-staff - Forbidden
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Staff user
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        advertiser_name = "Test Advertiser"
        user_name = "User Name"
        user_email = "user@example.com"
        data = {
            "advertiser_name": advertiser_name,
            "user_name": user_name,
            "user_email": user_email,
        }
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302)

        self.assertTrue(Advertiser.objects.filter(name=advertiser_name).exists())


class PublisherPayoutTests(TestCase):
    def setUp(self):
        TestPublisherDashboardViews.setUp(self)

        # Create offers to pay out last month
        last_month = timezone.now().replace(day=1) - timedelta(days=1)
        self.publisher1.created = last_month
        self.publisher1.save()
        for x in range(50):
            get(
                Offer,
                advertisement=self.ad1,
                publisher=self.publisher1,
                viewed=True,
                clicked=True,
                date=last_month,
            )

        # Index data into proper table
        daily_update_impressions(day=last_month)

    def test_list_view(self):
        url = reverse("staff-publisher-payouts")

        # Anonymous - no access
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["location"].startswith("/accounts/login/"))

        # Non-staff - Forbidden
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Publisher payout ready
        self.client.force_login(self.staff_user)
        list_response = self.client.get(url)
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "<td>$70.00</td>")
        self.assertContains(list_response, "test-publisher</a></td>")

    @override_settings(FRONT_TOKEN="test", FRONT_CHANNEL="test", FRONT_AUTHOR="test")
    @patch("adserver.staff.forms.requests.request")
    def test_create_view(self, mock_request):
        self.client.force_login(self.staff_user)

        # Start payout
        start_url = reverse(
            "staff-start-publisher-payout",
            kwargs=dict(publisher_slug=self.publisher1.slug),
        )
        start_response = self.client.get(start_url)
        self.assertEqual(start_response.status_code, 200)
        self.assertContains(start_response, 'value="EthicalAds by Read the Docs"')
        self.assertContains(
            start_response, f"EthicalAds Payout - {self.publisher1.name}"
        )

        # Send email
        data = {
            "sender": "Test",
            "subject": "Test subject",
            "body": "cool email",
            "amount": "40534",
            "archive": True,
        }
        post_response = self.client.post(start_url, data=data)
        self.assertEqual(post_response.status_code, 302)

        self.assertEqual(
            mock_request.call_args[0],
            ("POST", "https://api2.frontapp.com/channels/test/messages"),
        )
