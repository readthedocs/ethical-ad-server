import datetime

from django.contrib.auth.models import AnonymousUser
from django_dynamic_fixture import get
from django_slack.utils import get_backend

from ..models import Offer
from ..tasks import calculate_publisher_ctrs
from ..tasks import daily_update_impressions
from ..tasks import notify_of_completed_flights
from ..tasks import remove_old_client_ids
from .common import BaseAdModelsTestCase


class TasksTest(BaseAdModelsTestCase):
    def test_remove_client_ids(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        offer_dict = self.ad1.offer_ad(
            request=request,
            publisher=self.publisher,
            ad_type_slug=self.text_ad_type.slug,
            div_id="foo",
            keywords=None,
        )
        offer = Offer.objects.filter(pk=offer_dict["nonce"]).first()
        self.assertIsNotNone(offer)
        self.assertIsNotNone(offer.client_id)

        remove_old_client_ids()

        # Shouldn't remove the offer's client_id since it is "recent"
        offer.refresh_from_db()
        self.assertIsNotNone(offer.client_id)

        # Set the time back on the offer and the client_id should be blanked out
        offer.date = offer.date - datetime.timedelta(days=100)
        offer.save()
        remove_old_client_ids()

        # Offer's client_id is nulled out
        offer.refresh_from_db()
        self.assertIsNone(offer.client_id)

    def test_calculate_publisher_ctrs(self):
        calculate_publisher_ctrs()

        self.publisher.refresh_from_db()
        self.assertEqual(self.publisher.sampled_ctr, 0.0)

        # Add some views and clicks
        get(Offer, advertisement=self.ad1, publisher=self.publisher, viewed=True)
        get(Offer, advertisement=self.ad1, publisher=self.publisher, viewed=True)
        get(Offer, advertisement=self.ad1, publisher=self.publisher, viewed=True)
        get(Offer, advertisement=self.ad1, publisher=self.publisher, viewed=True)
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=True,
            clicked=True,
        )

        daily_update_impressions()
        calculate_publisher_ctrs()

        self.publisher.refresh_from_db()
        self.assertEqual(self.publisher.sampled_ctr, 20)

    def test_notify_completed_flights(self):
        backend = get_backend()

        notify_of_completed_flights()
        messages = backend.retrieve_messages()

        # Shouldn't be any completed flight messages
        self.assertEqual(len(messages), 0)

        # "Complete" the flight
        self.flight.sold_clicks = 1
        self.flight.total_views = 1
        self.flight.total_clicks = 1
        self.flight.save()
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=True,
            clicked=True,
        )
        daily_update_impressions()

        backend.reset_messages()
        notify_of_completed_flights()

        # Should be one message for the completed flight now
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 1)
