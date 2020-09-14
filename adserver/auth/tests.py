from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_dynamic_fixture import get


User = get_user_model()


class UserAdminTest(TestCase):
    def setUp(self):
        self.staff_user = get(
            User, is_staff=True, is_superuser=True, email="test2@example.com"
        )
        self.user = get(User, email="test1@example.com")

        self.client.force_login(self.staff_user)
        self.change_url = reverse("admin:adserver_auth_user_changelist")
        self.data = {
            "action": "invite_user_action",
            "_selected_action": [str(self.user.pk)],
        }

    def test_admin_invite_user_success(self):
        self.user.last_login = None
        self.user.save()

        response = self.client.post(self.change_url, self.data, follow=True)
        self.assertContains(response, "Sent invite to")
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith("You've been invited"))

    def test_admin_invite_user_rejected(self):
        # Users who have logged in before can't be invited
        self.user.last_login = timezone.now()
        self.user.save()

        response = self.client.post(self.change_url, self.data, follow=True)
        self.assertContains(response, "No invite sent")
        self.assertEqual(len(mail.outbox), 0)


class UserModelAndManagerTest(TestCase):
    def test_model_manager(self):
        email1 = "test1@example.com"
        password = "*(FSD&sadflk"

        with self.assertRaises(ValueError, msg="Email must be set"):
            User.objects.create_user(email="", password=password)

        user = User.objects.create_user(email=email1, password=password)
        self.assertEqual(user.email, email1)
        self.assertFalse(user.is_staff)

        email2 = "test2@example.com"

        with self.assertRaises(ValueError, msg="Superuser must have is_staff=True."):
            User.objects.create_superuser(
                email=email2, password=password, is_staff=False
            )
        with self.assertRaises(
            ValueError, msg="Superuser must have is_superuser=True."
        ):
            User.objects.create_superuser(
                email=email2, password=password, is_superuser=False
            )

        user = User.objects.create_superuser(email=email2, password=password)
        self.assertEqual(user.email, email2)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
