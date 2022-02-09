import datetime

from django.contrib.auth.models import AnonymousUser
from django_dynamic_fixture import get
from django_slack.utils import get_backend

from ..models import AdImpression
from ..models import KeywordImpression
from ..models import Offer
from ..tasks import calculate_publisher_ctrs
from ..tasks import daily_update_impressions
from ..tasks import daily_update_keywords
from ..tasks import notify_of_completed_flights
from ..tasks import notify_of_publisher_changes
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

    def test_daily_update_keywords(self):
        # Keyword Aggregation requires some targeting
        self.flight.targeting_parameters = {
            "include_keywords": ["django"],
        }
        self.flight.save()

        # Add some views and clicks
        # Ad1 - offered/decision=4, views=3, clicks=1
        # Ad2 - offered/decisions=2, views=2, clicks=0
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=False,
            keywords=["django", "python"],
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=True,
            keywords=["django", "python"],
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=True,
            keywords=["django", "python"],
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher,
            viewed=True,
            keywords=["django", "python"],
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher,
            viewed=True,
            keywords=["django", "python"],
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=True,
            clicked=True,
            keywords=["django", "python"],
        )

        daily_update_keywords()

        # Verify that the aggregation task worked correctly
        ki_ad1 = KeywordImpression.objects.filter(
            keyword="django", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(ki_ad1)
        self.assertEqual(ki_ad1.offers, 4)
        self.assertEqual(ki_ad1.views, 3)
        self.assertEqual(ki_ad1.clicks, 1)

        ki_ad2 = KeywordImpression.objects.filter(
            keyword="django", publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(ki_ad2)
        self.assertEqual(ki_ad2.offers, 2)
        self.assertEqual(ki_ad2.views, 2)
        self.assertEqual(ki_ad2.clicks, 0)

    def test_notify_completed_flights(self):
        backend = get_backend()
        backend.reset_messages()

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

    def test_notify_of_publisher_changes(self):
        # Publisher changes only apply to paid campaigns
        self.publisher.allow_paid_campaigns = True
        self.publisher.save()

        backend = get_backend()
        messages = backend.retrieve_messages()
        notify_of_publisher_changes()

        # Shouldn't be any publisher changes yet
        self.assertEqual(len(messages), 0)

        # Add some views and clicks
        for _ in range(50):
            get(Offer, advertisement=self.ad1, publisher=self.publisher, viewed=True)
        for _ in range(5):
            offer = get(
                Offer,
                advertisement=self.ad1,
                publisher=self.publisher,
                viewed=True,
                clicked=True,
            )

        # Add some impressions from a week ago
        eight_days_ago = offer.date - datetime.timedelta(days=8)
        for _ in range(100):
            get(
                Offer,
                advertisement=self.ad1,
                publisher=self.publisher,
                date=eight_days_ago,
                viewed=True,
            )
        for _ in range(11):
            get(
                Offer,
                advertisement=self.ad1,
                publisher=self.publisher,
                date=eight_days_ago,
                viewed=True,
                clicked=True,
            )

        daily_update_impressions()
        daily_update_impressions(eight_days_ago)

        # Ensure the ad impressions (used in the reports) are generated
        self.assertTrue(AdImpression.objects.filter(publisher=self.publisher).exists())

        backend.reset_messages()
        notify_of_publisher_changes(min_views=100)

        # Should be 1 message: one for views with CTR being within the threshold
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 1, messages)
        self.assertTrue(
            '"views" was 55 last week and 111 the previous week (-50.45%)'
            in messages[0]["text"]
        )

        backend.reset_messages()

        # No messages because it's below the minimum views
        notify_of_publisher_changes(min_views=1000)
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 0)
