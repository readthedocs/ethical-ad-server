from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_dynamic_fixture import get
from rest_framework.authtoken.models import Token


class TestApiTokenMangementViews(TestCase):

    """Test the API token management (list, create, delete) views."""

    def setUp(self):
        self.user = get(
            get_user_model(), email="test1@example.com", username="test-user"
        )

        self.list_view = reverse("api_token_list")
        self.create_view = reverse("api_token_create")
        self.delete_view = reverse("api_token_delete")

        self.client.force_login(self.user)

    def test_logged_out(self):
        self.client.logout()

        resp = self.client.get(self.list_view)

        # Redirected to login
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["location"].startswith("/accounts/login/"))

    def test_list_view(self):
        resp = self.client.get(self.list_view)
        self.assertContains(resp, "Generate API Token")

        token = Token.objects.create(user=self.user)

        resp = self.client.get(self.list_view)
        self.assertContains(resp, "Revoke token")
        self.assertContains(resp, token.key)

    def test_create_view(self):
        resp = self.client.post(self.create_view, data={}, follow=True)
        self.assertContains(resp, "API token created successfully")

        self.assertTrue(Token.objects.filter(user=self.user).exists())

    def test_delete_view(self):
        # Token doesn't exist yet
        resp = self.client.post(self.delete_view, data={})
        self.assertEqual(resp.status_code, 404)

        Token.objects.create(user=self.user)

        resp = self.client.post(self.delete_view, data={}, follow=True)
        self.assertContains(resp, "API token revoked")

        self.assertFalse(Token.objects.filter(user=self.user).exists())
