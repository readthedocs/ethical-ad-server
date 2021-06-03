from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get

from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..staff.forms import CreateAdvertiserForm


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
