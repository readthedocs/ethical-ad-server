from django.urls import reverse

from ..constants import CLICKS
from ..constants import VIEWS
from ..models import Click
from ..models import Publisher
from .common import BaseAdModelsTestCase


class AdModelAdminTests(BaseAdModelsTestCase):
    def setUp(self):
        super().setUp()

        self.client.force_login(self.staff_user)

    def test_no_delete(self):
        change_url = reverse("admin:adserver_publisher_changelist")
        data = {
            "action": "delete_selected",
            "_selected_action": [str(self.publisher.pk)],
        }
        response = self.client.post(change_url, data, follow=True)

        self.assertTrue(response.status_code, 200)
        self.assertTrue(Publisher.objects.filter(pk=self.publisher.pk).exists())

    def test_publisher_admin(self):
        list_url = reverse("admin:adserver_publisher_changelist")
        detail_url = reverse(
            "admin:adserver_publisher_change", args=[self.publisher.pk]
        )

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_advertiser_admin(self):
        list_url = reverse("admin:adserver_advertiser_changelist")
        detail_url = reverse(
            "admin:adserver_advertiser_change", args=[self.advertiser.pk]
        )

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_advertisement_admin(self):
        list_url = reverse("admin:adserver_advertisement_changelist")
        detail_url = reverse("admin:adserver_advertisement_change", args=[self.ad1.pk])

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_flight_admin(self):
        list_url = reverse("admin:adserver_flight_changelist")
        detail_url = reverse("admin:adserver_flight_change", args=[self.flight.pk])

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_campaign_admin(self):
        list_url = reverse("admin:adserver_campaign_changelist")
        detail_url = reverse("admin:adserver_campaign_change", args=[self.campaign.pk])

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_adimpression_admin(self):
        self.ad1.incr(VIEWS, self.publisher)
        self.ad1.incr(CLICKS, self.publisher)
        impression = self.ad1.impressions.all().first()

        list_url = reverse("admin:adserver_adimpression_changelist")
        detail_url = reverse("admin:adserver_adimpression_change", args=[impression.pk])

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_click_admin(self):
        request = self.factory.get("/")

        self.ad1.track_click(request, self.publisher, "http://example.com")
        click = Click.objects.all().first()

        list_url = reverse("admin:adserver_click_changelist")
        detail_url = reverse("admin:adserver_click_change", args=[click.pk])

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)
