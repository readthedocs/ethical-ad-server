import datetime

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.test import override_settings
from django_dynamic_fixture import get
from django_slack.utils import get_backend

from ..models import AdImpression
from ..models import GeoImpression
from ..models import KeywordImpression
from ..models import Offer
from ..models import PlacementImpression
from ..models import RegionImpression
from ..models import RegionTopicImpression
from ..models import UpliftImpression
from ..tasks import calculate_publisher_ctrs
from ..tasks import daily_update_geos
from ..tasks import daily_update_impressions
from ..tasks import daily_update_keywords
from ..tasks import daily_update_placements
from ..tasks import daily_update_regiontopic
from ..tasks import daily_update_uplift
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

    @override_settings(
        # Use the memory email backend instead of front for testing
        FRONT_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        FRONT_ENABLED=True,
    )
    def test_notify_completed_flights(self):
        # Ensure there's a recipient for a wrapup email
        self.staff_user.advertisers.add(self.advertiser)

        backend = get_backend()
        backend.reset_messages()

        notify_of_completed_flights()
        messages = backend.retrieve_messages()

        # Shouldn't be any completed flight messages
        self.assertEqual(len(messages), 0)
        self.assertEqual(len(mail.outbox), 0)

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
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith("Advertising flight wrapup"))

        # Flight should no longer be live
        self.flight.refresh_from_db()
        self.assertFalse(self.flight.live)

    def test_notify_of_publisher_changes(self):
        # Publisher changes only apply to paid campaigns
        self.publisher.allow_paid_campaigns = True
        self.publisher.save()

        backend = get_backend()
        backend.reset_messages()

        notify_of_publisher_changes()
        messages = backend.retrieve_messages()

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


class AggregationTaskTests(BaseAdModelsTestCase):
    def setUp(self):
        super().setUp()

        # Keyword Aggregation requires some targeting
        self.flight.targeting_parameters = {
            "include_keywords": ["backend", "security"],
        }
        self.flight.save()

        # Required for placement impression aggregation
        self.publisher.record_placements = True
        self.publisher.save()

        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            country="CA",
            viewed=False,
            keywords=["backend"],
            div_id="id_1",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            country="CA",
            viewed=True,
            keywords=["backend"],
            div_id="id_1",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            country="CA",
            viewed=True,
            clicked=True,
            uplifted=True,
            keywords=["backend"],
            div_id="id_1",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            country="DE",
            viewed=True,
            keywords=["backend"],
            div_id="id_2",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher,
            country="DE",
            viewed=True,
            uplifted=True,
            keywords=["security"],
            div_id="id_2",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher,
            country="DE",
            viewed=True,
            uplifted=True,
            keywords=["security"],
            div_id="id_2",
            ad_type_slug=self.text_ad_type.slug,
        )

    def test_daily_update_impressions(self):
        # Ad1 - offered/decision=4, views=3, clicks=1
        # Ad2 - offered/decisions=2, views=2, clicks=0
        daily_update_impressions()

        # Verify that the aggregation task worked correctly
        ai1 = AdImpression.objects.filter(
            publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(ai1)
        self.assertEqual(ai1.offers, 4)
        self.assertEqual(ai1.views, 3)
        self.assertEqual(ai1.clicks, 1)

        ai2 = AdImpression.objects.filter(
            publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(ai2)
        self.assertEqual(ai2.offers, 2)
        self.assertEqual(ai2.views, 2)
        self.assertEqual(ai2.clicks, 0)

    def test_daily_update_keywords(self):
        # Ad1 - offered/decision=4, views=3, clicks=1
        # Ad2 - offered/decisions=2, views=2, clicks=0
        daily_update_keywords()

        # Verify that the aggregation task worked correctly
        ki_ad1 = KeywordImpression.objects.filter(
            keyword="backend", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(ki_ad1)
        self.assertEqual(ki_ad1.offers, 4)
        self.assertEqual(ki_ad1.views, 3)
        self.assertEqual(ki_ad1.clicks, 1)

        ki_ad2 = KeywordImpression.objects.filter(
            keyword="security", publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(ki_ad2)
        self.assertEqual(ki_ad2.offers, 2)
        self.assertEqual(ki_ad2.views, 2)
        self.assertEqual(ki_ad2.clicks, 0)

    def test_daily_update_geos(self):
        # Ad1/CA - offered/decision=3, views=2, clicks=1
        # Ad1/DE - offered/decision=1, views=1, clicks=0
        # Ad2/DE - offered/decisions=2, views=2, clicks=0
        daily_update_geos()

        # Verify that the aggregation task worked correctly
        geo_ad1_ca = GeoImpression.objects.filter(
            country="CA", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(geo_ad1_ca)
        self.assertEqual(geo_ad1_ca.offers, 3)
        self.assertEqual(geo_ad1_ca.views, 2)
        self.assertEqual(geo_ad1_ca.clicks, 1)

        geo_ad1_de = GeoImpression.objects.filter(
            country="DE", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(geo_ad1_de)
        self.assertEqual(geo_ad1_de.offers, 1)
        self.assertEqual(geo_ad1_de.views, 1)
        self.assertEqual(geo_ad1_de.clicks, 0)

        geo_ad2_de = GeoImpression.objects.filter(
            country="DE", publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(geo_ad2_de)
        self.assertEqual(geo_ad2_de.offers, 2)
        self.assertEqual(geo_ad2_de.views, 2)
        self.assertEqual(geo_ad2_de.clicks, 0)

        reg_na_ad1 = RegionImpression.objects.filter(
            region="us-ca", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(reg_na_ad1)
        self.assertEqual(reg_na_ad1.offers, 3)
        self.assertEqual(reg_na_ad1.views, 2)
        self.assertEqual(reg_na_ad1.clicks, 1)

        reg_eu_ad1 = RegionImpression.objects.filter(
            region="eu-aus-nz", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(reg_eu_ad1)
        self.assertEqual(reg_eu_ad1.offers, 1)
        self.assertEqual(reg_eu_ad1.views, 1)
        self.assertEqual(reg_eu_ad1.clicks, 0)

        reg_eu_ad2 = RegionImpression.objects.filter(
            region="eu-aus-nz", publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(reg_eu_ad2)
        self.assertEqual(reg_eu_ad2.offers, 2)
        self.assertEqual(reg_eu_ad2.views, 2)
        self.assertEqual(reg_eu_ad2.clicks, 0)

    def test_daily_update_regiontopic(self):
        # Ad1/backend/CA - offered/decision=3, views=2, clicks=1
        # Ad1/backend/DE - offered/decision=1, views=1, clicks=0
        # Ad2/security/DE - offered/decisions=2, views=2, clicks=0
        daily_update_regiontopic()

        na_backend_ad1 = RegionTopicImpression.objects.filter(
            region="us-ca", topic="backend-web", advertisement=self.ad1
        ).first()
        self.assertIsNotNone(na_backend_ad1)
        self.assertEqual(na_backend_ad1.offers, 3)
        self.assertEqual(na_backend_ad1.views, 2)
        self.assertEqual(na_backend_ad1.clicks, 1)

        eu_backend_ad1 = RegionTopicImpression.objects.filter(
            region="eu-aus-nz", topic="backend-web", advertisement=self.ad1
        ).first()
        self.assertIsNotNone(eu_backend_ad1)
        self.assertEqual(eu_backend_ad1.offers, 1)
        self.assertEqual(eu_backend_ad1.views, 1)
        self.assertEqual(eu_backend_ad1.clicks, 0)

        eu_security_ad2 = RegionTopicImpression.objects.filter(
            region="eu-aus-nz", topic="security-privacy", advertisement=self.ad2
        ).first()
        self.assertIsNotNone(eu_security_ad2)
        self.assertEqual(eu_security_ad2.offers, 2)
        self.assertEqual(eu_security_ad2.views, 2)
        self.assertEqual(eu_security_ad2.clicks, 0)

    def test_daily_update_uplift(self):
        # Ad1 - offered/decision=1, views=1, clicks=1
        # Ad2 - offered/decisions=2, views=2, clicks=0
        daily_update_uplift()

        uplift1 = UpliftImpression.objects.filter(advertisement=self.ad1).first()
        self.assertIsNotNone(uplift1)
        self.assertEqual(uplift1.offers, 1)
        self.assertEqual(uplift1.views, 1)
        self.assertEqual(uplift1.clicks, 1)

        uplift2 = UpliftImpression.objects.filter(advertisement=self.ad2).first()
        self.assertIsNotNone(uplift2)
        self.assertEqual(uplift2.offers, 2)
        self.assertEqual(uplift2.views, 2)
        self.assertEqual(uplift2.clicks, 0)

    def test_daily_update_placements(self):
        # Ad1/id_1 - offered/decision=3, views=2, clicks=1
        # Ad1/id_2 - offered/decisions=1, views=1, clicks=0
        # Ad2/id_2 - offered/decisions=2, views=2, clicks=0
        daily_update_placements()

        pi1_ad1 = PlacementImpression.objects.filter(
            advertisement=self.ad1, div_id="id_1"
        ).first()
        self.assertIsNotNone(pi1_ad1)
        self.assertEqual(pi1_ad1.offers, 3)
        self.assertEqual(pi1_ad1.views, 2)
        self.assertEqual(pi1_ad1.clicks, 1)

        pi2_ad1 = PlacementImpression.objects.filter(
            advertisement=self.ad1, div_id="id_2"
        ).first()
        self.assertIsNotNone(pi2_ad1)
        self.assertEqual(pi2_ad1.offers, 1)
        self.assertEqual(pi2_ad1.views, 1)
        self.assertEqual(pi2_ad1.clicks, 0)

        pi2_ad2 = PlacementImpression.objects.filter(
            advertisement=self.ad2, div_id="id_2"
        ).first()
        self.assertIsNotNone(pi2_ad2)
        self.assertEqual(pi2_ad2.offers, 2)
        self.assertEqual(pi2_ad2.views, 2)
        self.assertEqual(pi2_ad2.clicks, 0)
