from unittest import mock

import stripe
from django.test import override_settings
from django.urls import reverse
from django_dynamic_fixture import get
from djstripe.models import Invoice

from ..constants import CLICKS
from ..constants import VIEWS
from ..models import Advertiser
from ..models import Campaign
from ..models import Click
from ..models import Flight
from ..models import Offer
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

        # Ensure the Stripe customer link is present
        self.advertiser.djstripe_customer = self.stripe_customer
        self.advertiser.save()

        response = self.client.get(list_url)
        self.assertTrue(response.status_code, 200)
        self.assertContains(response, self.advertiser.djstripe_customer.id)
        self.assertContains(response, self.advertiser.djstripe_customer.name)

    def test_advertiser_invoice_create(self):
        url = reverse("admin:adserver_advertiser_changelist")
        data = {
            "action": "action_create_draft_invoice",
            "_selected_action": [str(self.advertiser.pk)],
        }
        resp = self.client.post(url, data, follow=True)
        self.assertContains(resp, "Stripe is not configured")

        with override_settings(
            STRIPE_LIVE_SECRET_KEY="test-12345", STRIPE_ENABLED=True
        ):
            with mock.patch("stripe.InvoiceItem.create") as _, mock.patch(
                "stripe.Invoice.create"
            ) as invoice_create, mock.patch(
                "adserver.admin.Invoice.sync_from_stripe_data"
            ) as _2:
                # No Stripe ID for this advertiser
                resp = self.client.post(url, data, follow=True)
                self.assertContains(resp, "No Stripe customer ID")

                self.advertiser.djstripe_customer = self.stripe_customer
                self.advertiser.save()

                invoice_create.return_value = stripe.Invoice(id="inv_98765")

                resp = self.client.post(url, data, follow=True)
                self.assertContains(resp, "New Stripe invoice")

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

    def test_flight_invoice_create(self):
        advertiser2 = get(Advertiser)
        campaign2 = get(Campaign, advertiser=advertiser2)
        flight2 = get(
            Flight,
            live=True,
            campaign=campaign2,
            sold_impressions=10000,
            cpm=2.2,
            start_date=self.flight.start_date,
            end_date=self.flight.end_date,
            targeting_parameters={},
        )
        flight3 = get(
            Flight,
            live=True,
            campaign=campaign2,
            sold_impressions=0,
            cpm=0,
            start_date=self.flight.start_date,
            end_date=self.flight.end_date,
            targeting_parameters={},
        )

        url = reverse("admin:adserver_flight_changelist")
        data = {
            "action": "action_create_draft_invoice",
            "_selected_action": [self.flight.pk, flight2.pk, flight3.pk],
        }
        resp = self.client.post(url, data, follow=True)
        self.assertContains(resp, "Stripe is not configured")

        with override_settings(
            STRIPE_LIVE_SECRET_KEY="test-12345", STRIPE_ENABLED=True
        ):
            with mock.patch("stripe.InvoiceItem.create") as _, mock.patch(
                "stripe.Invoice.create"
            ) as invoice_create, mock.patch(
                "adserver.admin.Invoice.sync_from_stripe_data"
            ) as invoice_object:
                resp = self.client.post(url, data, follow=True)
                self.assertContains(
                    resp,
                    "All selected flights must be from a single advertiser",
                )

                campaign2.advertiser = self.advertiser
                campaign2.save()

                # No Stripe ID for this advertiser
                resp = self.client.post(url, data, follow=True)
                self.assertContains(resp, "No Stripe customer ID")

                self.advertiser.djstripe_customer = self.stripe_customer
                self.advertiser.save()

                invoice_create.return_value = stripe.Invoice(id="inv_98765")
                invoice_object.return_value = Invoice(customer=self.stripe_customer)

                resp = self.client.post(url, data, follow=True)
                self.assertContains(resp, "New Stripe invoice")

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

        offer = get(Offer, publisher=self.publisher)

        self.ad1.track_click(request, self.publisher, offer=offer)
        click = Click.objects.all().first()

        list_url = reverse("admin:adserver_click_changelist")
        detail_url = reverse("admin:adserver_click_change", args=[click.pk])

        for url in (list_url, detail_url):
            response = self.client.get(url)
            self.assertTrue(response.status_code, 200)

    def test_offer_refund_action(self):
        request = self.factory.get("/")

        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        offer1 = Offer.objects.get(pk=output["nonce"])
        output = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type,
            div_id="foo",
            keywords=None,
        )
        offer2 = Offer.objects.get(pk=output["nonce"])

        view1 = self.ad1.track_view(request, self.publisher, offer=offer1)
        view2 = self.ad1.track_view(request, self.publisher, offer=offer2)
        self.ad1.invalidate_nonce(VIEWS, offer1.pk)
        self.ad1.invalidate_nonce(VIEWS, offer2.pk)

        self.assertTrue(view1)
        self.assertTrue(view2)

        url = reverse("admin:adserver_offer_changelist")
        data = {
            "action": "refund_impressions",
            "_selected_action": [offer1.pk, offer2.pk],
        }

        # Verify confirmation page
        resp = self.client.post(url, data)
        self.assertContains(resp, "Are you sure you want to refund")

        # Bypass the confirmation page
        data["confirm"] = "yes"
        resp = self.client.post(url, data, follow=True)
        self.assertContains(resp, "2 offers refunded")

        offer1.refresh_from_db()
        offer2.refresh_from_db()
        self.assertTrue(offer1.is_refunded)
        self.assertTrue(offer2.is_refunded)
