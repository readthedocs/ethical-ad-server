from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_dynamic_fixture import get

from ..models import Advertiser
from ..models import Campaign
from ..models import Flight
from ..models import Offer
from ..models import Publisher
from ..models import PublisherGroup
from ..models import PublisherPayout
from ..staff.forms import CreateAdvertiserForm
from ..staff.forms import CreatePublisherForm
from ..tasks import daily_update_impressions
from ..tasks import daily_update_publishers


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
        perm = Permission.objects.get(
            codename="add_advertiser",
            content_type=ContentType.objects.get_for_model(Advertiser),
        )
        self.staff_user.user_permissions.add(perm)

        self.pub_group_rtd = get(
            PublisherGroup,
            slug="readthedocs",
            default_enabled=True,
        )
        self.pub_group_ea = get(
            PublisherGroup,
            slug="ethicalads-network",
            default_enabled=True,
        )
        self.pub_group_other = get(
            PublisherGroup,
            slug="other",
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

        # Advertiser and user exists now
        form = CreateAdvertiserForm(data=data)
        self.assertFalse(form.is_valid())

        # Create another advertiser with the same user
        advertiser_name = "Test Advertiser 2"
        data = {
            "advertiser_name": advertiser_name,
            "user_email": user_email,
        }
        form = CreateAdvertiserForm(data=data)
        self.assertTrue(form.is_valid())
        form.save()

        self.assertTrue(Advertiser.objects.filter(name=advertiser_name).exists())
        user = User.objects.filter(email=user_email).first()
        self.assertEqual(user.advertisers.count(), 2)

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

        # Check that an advertiser was created
        advertiser = Advertiser.objects.filter(name=advertiser_name).first()
        self.assertIsNotNone(advertiser)

        # Check that a campaign was created for the advertiser
        campaign = Campaign.objects.filter(advertiser=advertiser).first()
        self.assertIsNotNone(campaign)

        # Check that the campaign targets the two pub groups (readthedocs and ethicalads-network)
        for slug in ("readthedocs", "ethicalads-network"):
            self.assertTrue(campaign.publisher_groups.filter(slug=slug).exists())
        self.assertFalse(
            campaign.publisher_groups.filter(pk=self.pub_group_other.pk).exists()
        )


class CreatePublisherTest(TestCase):
    def setUp(self):
        CreateAdvertiserTest.setUp(self)

        self.site = "foo.com"
        self.user_name = "User Name"
        self.user_email = "user@example.com"
        self.keywords = "frontend,bar"
        self.data = {
            "site": self.site,
            "user_name": self.user_name,
            "user_email": self.user_email,
            "keywords": self.keywords,
        }

        perm = Permission.objects.get(
            codename="add_publisher",
            content_type=ContentType.objects.get_for_model(Publisher),
        )
        self.staff_user.user_permissions.add(perm)

    def test_form(self):
        form = CreatePublisherForm(data=self.data)
        self.assertTrue(form.is_valid())
        form.save()

        self.assertTrue(Publisher.objects.filter(name=self.site).exists())
        publisher = Publisher.objects.filter(name=self.site).first()
        self.assertEqual(publisher.keywords, self.keywords.split(","))
        self.assertEqual(
            publisher.publisher_groups.first().slug, CreatePublisherForm.DEFAULT_GROUP
        )

        user = User.objects.filter(email=self.user_email).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.publishers.count(), 1)

        # Publisher now exists
        form = CreatePublisherForm(data=self.data)
        self.assertFalse(form.is_valid())

    def test_form_existing_user(self):
        data = {
            "site": self.site,
            "user_name": self.user_name,
            "user_email": self.user.email,  # User exists
            "keywords": self.keywords,
        }

        form = CreatePublisherForm(data=data)
        self.assertTrue(form.is_valid())
        form.save()

        self.assertTrue(Publisher.objects.filter(name=self.site).exists())

        self.assertEqual(User.objects.filter(email=self.user.email).count(), 1)
        user = User.objects.filter(email=self.user.email).first()
        self.assertEqual(user.publishers.count(), 1)

    def test_view(self):
        url = reverse("create-publisher")

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

        response = self.client.post(url, data=self.data)
        self.assertEqual(response.status_code, 302)

        self.assertTrue(Publisher.objects.filter(name=self.site).exists())


class PublisherPayoutTests(TestCase):
    def setUp(self):
        from .test_publisher_dashboard import TestPublisherDashboardViews  # noqa

        TestPublisherDashboardViews.setUp(self)

        # Create offers to pay out last month
        last_month = timezone.now().replace(day=1) - timedelta(days=1)
        self.publisher1.created = last_month
        self.publisher1.save()

        # 50 clicks * 2 CPC = $100 ($70 shared)
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
        daily_update_publishers(day=last_month)

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
        self.assertContains(list_response, f"<span>{self.publisher1.name}</span>")

    def test_list_view_filters(self):
        url = reverse("staff-publisher-payouts")
        self.client.force_login(self.staff_user)

        # Filter paid
        list_response = self.client.get(url + "?paid=True")
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, "<td>$70.00</td>")
        self.assertNotContains(list_response, f"<span>{self.publisher1.name}</span>")

        list_response = self.client.get(url + "?paid=False")
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "<td>$70.00</td>")
        self.assertContains(list_response, f"<span>{self.publisher1.name}</span>")

        # Filter first
        list_response = self.client.get(url + "?first=True")
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "<td>$70.00</td>")
        self.assertContains(list_response, f"<span>{self.publisher1.name}</span>")

        list_response = self.client.get(url + "?first=False")
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, "<td>$70.00</td>")
        self.assertNotContains(list_response, f"<span>{self.publisher1.name}</span>")

        # Filter publisher
        list_response = self.client.get(url + "?publisher=foo")
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, "<td>$70.00</td>")
        self.assertNotContains(list_response, f"<span>{self.publisher1.name}</span>")

        list_response = self.client.get(url + "?publisher=test")
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "<td>$70.00</td>")
        self.assertContains(list_response, f"<span>{self.publisher1.name}</span>")

    @override_settings(
        # Use the memory email backend instead of front for testing
        FRONT_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        FRONT_ENABLED=True,
    )
    def test_create_view(self):
        self.client.force_login(self.staff_user)

        # Need a user otherwise the email isn't sent because there's no recipients
        self.user.publishers.add(self.publisher1)

        # Start payout
        start_url = reverse(
            "staff-start-publisher-payout",
            kwargs=dict(publisher_slug=self.publisher1.slug),
        )
        start_response = self.client.get(start_url)
        self.assertEqual(start_response.status_code, 200)
        self.assertContains(start_response, 'value="EthicalAds"')
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

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Test subject")

    def test_finish_view(self):
        self.client.force_login(self.staff_user)

        self.payout = get(
            PublisherPayout,
            status="emailed",
            publisher=self.publisher1,
            amount=55,
            date=timezone.now() - timedelta(days=3),
        )
        self.payout2 = get(
            PublisherPayout,
            status="emailed",
            publisher=self.publisher1,
            amount=77,
            date=timezone.now() - timedelta(days=2),
        )
        self.payout3 = get(
            PublisherPayout,
            status="emailed",
            publisher=self.publisher1,
            amount=99,
            date=timezone.now() - timedelta(days=1),
        )

        self.assertEqual(self.payout.status, "emailed")

        # Start payout
        finish_url = reverse(
            "staff-finish-publisher-payout",
            kwargs=dict(publisher_slug=self.publisher1.slug),
        )
        finish_response = self.client.get(finish_url)
        self.assertEqual(finish_response.status_code, 200)
        self.assertContains(finish_response, self.payout3.get_status_display())
        self.assertContains(finish_response, "$99")

        post_response = self.client.post(finish_url)
        self.assertEqual(post_response.status_code, 302)
        # requery to get new object
        self.assertEqual(PublisherPayout.objects.get(pk=self.payout3.pk).status, "paid")
