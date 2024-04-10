import datetime

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from django_dynamic_fixture import get
from django_slack.utils import get_backend

from ..constants import HOUSE_CAMPAIGN
from ..models import AdImpression
from ..models import AdvertiserImpression
from ..models import GeoImpression
from ..models import KeywordImpression
from ..models import Offer
from ..models import PlacementImpression
from ..models import PublisherImpression
from ..models import PublisherPaidImpression
from ..models import RegionImpression
from ..models import RegionTopicImpression
from ..models import UpliftImpression
from ..tasks import calculate_ad_ctrs
from ..tasks import calculate_publisher_ctrs
from ..tasks import daily_update_advertisers
from ..tasks import daily_update_geos
from ..tasks import daily_update_impressions
from ..tasks import daily_update_keywords
from ..tasks import daily_update_placements
from ..tasks import daily_update_publishers
from ..tasks import daily_update_regiontopic
from ..tasks import daily_update_uplift
from ..tasks import disable_inactive_publishers
from ..tasks import notify_of_completed_flights
from ..tasks import notify_of_publisher_changes
from ..tasks import remove_old_client_ids
from ..tasks import remove_old_report_data
from ..tasks import update_previous_day_reports
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
        self.publisher.allow_paid_campaigns = True
        self.publisher.save()

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

    def test_calculate_ad_ctrs(self):
        calculate_ad_ctrs(min_views=0)

        self.ad1.refresh_from_db()
        self.assertAlmostEqual(self.ad1.sampled_ctr, 0.0)

        # Ad1: 9+1 views, 1 click
        for _ in range(9):
            get(Offer, advertisement=self.ad1, publisher=self.publisher, viewed=True)
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            viewed=True,
            clicked=True,
        )

        # Ad2: 5+2 views, 2 clicks
        for _ in range(5):
            get(Offer, advertisement=self.ad2, publisher=self.publisher, viewed=True)
        for _ in range(2):
            get(
                Offer,
                advertisement=self.ad2,
                publisher=self.publisher,
                viewed=True,
                clicked=True,
            )

        daily_update_impressions()
        calculate_ad_ctrs(min_views=0)

        self.ad1.refresh_from_db()
        self.ad2.refresh_from_db()

        self.assertAlmostEqual(self.ad1.sampled_ctr, 100 * (1 / 10))
        self.assertAlmostEqual(self.ad2.sampled_ctr, 100 * (2 / 7))

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

    @override_settings(
        # Use the memory email backend instead of front for testing
        FRONT_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        FRONT_ENABLED=True,
    )
    def test_notify_completed_flights_hard_stop(self):
        # Ensure there's a recipient for a wrapup email
        self.staff_user.advertisers.add(self.advertiser)

        backend = get_backend()
        backend.reset_messages()

        notify_of_completed_flights()
        messages = backend.retrieve_messages()

        # Shouldn't be any completed flight messages
        self.assertEqual(len(messages), 0)
        self.assertEqual(len(mail.outbox), 0)

        # Set this flight to hard stop
        self.flight.sold_clicks = 100
        self.flight.total_views = 1_000
        self.flight.total_clicks = 50
        self.flight.hard_stop = True
        self.flight.start_date = timezone.now() - datetime.timedelta(days=31)
        self.flight.end_date = timezone.now() - datetime.timedelta(days=1)
        self.flight.save()

        # This should hard stop the flight
        notify_of_completed_flights()
        self.flight.refresh_from_db()

        # Flight should no longer be live
        self.assertFalse(self.flight.live)

        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 1)
        self.assertTrue(
            "was hard stopped. There was $100.00 value remaining" in messages[0]["text"]
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].subject.startswith("Advertising flight wrapup"))

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

        # Should be 1 message: one for revenue with CTR being within the threshold
        # Ads are $2 CPC
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 1, messages)
        self.assertTrue(
            '"revenue" was 10 last week and 22 the previous week (-54.55%)'
            in messages[0]["text"],
            messages[0]["text"],
        )

        backend.reset_messages()

        # No messages because it's below the minimum views
        notify_of_publisher_changes(min_views=1000)
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 0)

    @override_settings(
        # Use the memory email backend instead of front for testing
        FRONT_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        FRONT_ENABLED=True,
    )
    def test_disable_inactive_publishers(self):
        # Ensure there's a recipient for the email
        self.staff_user.publishers.add(self.publisher)

        backend = get_backend()
        backend.reset_messages()

        disable_inactive_publishers()
        messages = backend.retrieve_messages()

        # The publisher has not hit the threshold
        self.assertEqual(len(messages), 0)
        self.assertEqual(len(mail.outbox), 0)

        # Set this publisher up to be inactive
        self.publisher.allow_paid_campaigns = True
        self.publisher.created = timezone.now() - datetime.timedelta(days=100)
        self.publisher.save()

        disable_inactive_publishers(dry_run=True)
        self.publisher.refresh_from_db()
        self.assertTrue(self.publisher.allow_paid_campaigns)

        # Still nothing due to dry-run
        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 0)
        self.assertEqual(len(mail.outbox), 0)

        # Actually disable the publishers
        disable_inactive_publishers()
        self.publisher.refresh_from_db()
        self.assertFalse(self.publisher.allow_paid_campaigns)

        messages = backend.retrieve_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(len(mail.outbox), 1)


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
            view_time=6,
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
            view_time=6,
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
            country="MX",
            viewed=True,
            view_time=4,
            keywords=["backend"],
            div_id="id_2",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher,
            country="MX",
            viewed=True,
            view_time=4,
            uplifted=True,
            keywords=["security"],
            div_id="id_2",
            ad_type_slug=self.text_ad_type.slug,
        )
        get(
            Offer,
            advertisement=self.ad2,
            publisher=self.publisher,
            country="MX",
            viewed=True,
            view_time=4,
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
        self.assertEqual(ai1.view_time, 16)

        ai2 = AdImpression.objects.filter(
            publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(ai2)
        self.assertEqual(ai2.offers, 2)
        self.assertEqual(ai2.views, 2)
        self.assertEqual(ai2.clicks, 0)
        self.assertEqual(ai2.view_time, 8)

    def test_daily_update_advertiser_impressions(self):
        # Advertiser1 - offered/decision=6, views=5, clicks=1, spend=$2
        daily_update_impressions()
        daily_update_advertisers()

        # Verify that the aggregation task worked correctly
        ai = AdvertiserImpression.objects.filter(advertiser=self.advertiser).first()
        self.assertIsNotNone(ai)
        self.assertEqual(ai.decisions, 6)
        self.assertEqual(ai.offers, 6)
        self.assertEqual(ai.views, 5)
        self.assertEqual(ai.clicks, 1)
        self.assertAlmostEqual(float(ai.spend), 2.0)

    def test_daily_update_publisher_impressions(self):
        # Add a null offer (a decision that didn't result in an ad) in there
        get(
            Offer,
            advertisement=None,
            publisher=self.publisher,
            country="MX",
            viewed=False,
            view_time=None,
            keywords=["backend"],
            div_id="id_2",
            ad_type_slug=self.text_ad_type.slug,
        )

        # Publisher - offers=6, decisions=7, views=5, clicks=1, revenue=$2
        daily_update_impressions()
        daily_update_publishers()

        # Verify that the aggregation task worked correctly
        pi = PublisherImpression.objects.filter(publisher=self.publisher).first()
        self.assertIsNotNone(pi)
        self.assertEqual(pi.decisions, 7)
        self.assertEqual(pi.offers, 6)
        self.assertEqual(pi.views, 5)
        self.assertEqual(pi.clicks, 1)
        self.assertAlmostEqual(float(pi.revenue), 2.0)

        pi = PublisherPaidImpression.objects.filter(publisher=self.publisher).first()
        self.assertIsNotNone(pi)
        # The null offer isn't "paid" since there's no ad associated
        self.assertEqual(pi.decisions, 6)
        self.assertEqual(pi.offers, 6)
        self.assertEqual(pi.views, 5)
        self.assertEqual(pi.clicks, 1)
        self.assertAlmostEqual(float(pi.revenue), 2.0)

    def test_daily_update_no_paid_impressions(self):
        # Switch this to unpaid
        self.flight.cpc = 0
        self.flight.save()
        self.campaign.campaign_type = HOUSE_CAMPAIGN
        self.campaign.save()

        daily_update_impressions()
        daily_update_publishers()

        pi = PublisherImpression.objects.filter(publisher=self.publisher).first()
        self.assertIsNotNone(pi)

        pi = PublisherPaidImpression.objects.filter(publisher=self.publisher).first()
        self.assertIsNone(pi)

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

        # Check with topics instead of keyword targeting
        self.flight.targeting_parameters = {
            # Should give same results for ad1, nothing for ad2
            "include_topics": ["backend-web"],
        }
        self.flight.save()

        # Ad1 - offered/decision=4, views=3, clicks=1
        # Ad2 - offered/decisions=2, views=2, clicks=0
        daily_update_keywords()

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
        self.assertIsNone(ki_ad2)

    def test_daily_update_geos(self):
        # Ad1/CA - offered/decision=3, views=2, clicks=1
        # Ad1/MX - offered/decision=1, views=1, clicks=0
        # Ad2/MX - offered/decisions=2, views=2, clicks=0
        daily_update_geos()

        # Verify that the aggregation task worked correctly
        geo_ad1_ca = GeoImpression.objects.filter(
            country="CA", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(geo_ad1_ca)
        self.assertEqual(geo_ad1_ca.offers, 3)
        self.assertEqual(geo_ad1_ca.views, 2)
        self.assertEqual(geo_ad1_ca.clicks, 1)

        geo_ad1_mx = GeoImpression.objects.filter(
            country="MX", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(geo_ad1_mx)
        self.assertEqual(geo_ad1_mx.offers, 1)
        self.assertEqual(geo_ad1_mx.views, 1)
        self.assertEqual(geo_ad1_mx.clicks, 0)

        geo_ad2_mx = GeoImpression.objects.filter(
            country="MX", publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(geo_ad2_mx)
        self.assertEqual(geo_ad2_mx.offers, 2)
        self.assertEqual(geo_ad2_mx.views, 2)
        self.assertEqual(geo_ad2_mx.clicks, 0)

        reg_na_ad1 = RegionImpression.objects.filter(
            region="us-ca", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(reg_na_ad1)
        self.assertEqual(reg_na_ad1.offers, 3)
        self.assertEqual(reg_na_ad1.views, 2)
        self.assertEqual(reg_na_ad1.clicks, 1)

        reg_latam_ad1 = RegionImpression.objects.filter(
            region="latin-america", publisher=self.publisher, advertisement=self.ad1
        ).first()
        self.assertIsNotNone(reg_latam_ad1)
        self.assertEqual(reg_latam_ad1.offers, 1)
        self.assertEqual(reg_latam_ad1.views, 1)
        self.assertEqual(reg_latam_ad1.clicks, 0)

        reg_latam_ad2 = RegionImpression.objects.filter(
            region="latin-america", publisher=self.publisher, advertisement=self.ad2
        ).first()
        self.assertIsNotNone(reg_latam_ad2)
        self.assertEqual(reg_latam_ad2.offers, 2)
        self.assertEqual(reg_latam_ad2.views, 2)
        self.assertEqual(reg_latam_ad2.clicks, 0)

    def test_daily_update_regiontopic(self):
        # Ad1/backend/CA - offered/decision=3, views=2, clicks=1
        # Ad1/backend/MX - offered/decision=1, views=1, clicks=0
        # Ad2/security/MX - offered/decisions=2, views=2, clicks=0
        daily_update_regiontopic()

        na_backend_ad1 = RegionTopicImpression.objects.filter(
            region="us-ca", topic="backend-web", advertisement=self.ad1
        ).first()
        self.assertIsNotNone(na_backend_ad1)
        self.assertEqual(na_backend_ad1.offers, 3)
        self.assertEqual(na_backend_ad1.views, 2)
        self.assertEqual(na_backend_ad1.clicks, 1)

        latam_backend_ad1 = RegionTopicImpression.objects.filter(
            region="latin-america", topic="backend-web", advertisement=self.ad1
        ).first()
        self.assertIsNotNone(latam_backend_ad1)
        self.assertEqual(latam_backend_ad1.offers, 1)
        self.assertEqual(latam_backend_ad1.views, 1)
        self.assertEqual(latam_backend_ad1.clicks, 0)

        latam_security_ad2 = RegionTopicImpression.objects.filter(
            region="latin-america", topic="security-privacy", advertisement=self.ad2
        ).first()
        self.assertIsNotNone(latam_security_ad2)
        self.assertEqual(latam_security_ad2.offers, 2)
        self.assertEqual(latam_security_ad2.views, 2)
        self.assertEqual(latam_security_ad2.clicks, 0)

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

    def test_remove_old_report_data(self):
        # Add a very old offer
        old_date = timezone.now() - datetime.timedelta(days=370)
        get(
            Offer,
            advertisement=self.ad1,
            publisher=self.publisher,
            country="CA",
            viewed=True,
            view_time=6,
            clicked=True,
            keywords=["backend"],
            div_id="id_1",
            ad_type_slug=self.text_ad_type.slug,
            date=old_date,
        )

        # Run aggregations both for today and the very old day
        update_previous_day_reports(timezone.now())
        update_previous_day_reports(old_date)

        # Check that the aggregations match
        impression_old = RegionTopicImpression.objects.filter(
            region="us-ca",
            topic="backend-web",
            advertisement=self.ad1,
            date=old_date.date(),
        ).first()
        self.assertIsNotNone(impression_old)
        self.assertEqual(impression_old.offers, 1)
        self.assertEqual(impression_old.views, 1)
        self.assertEqual(impression_old.clicks, 1)

        # Remove old aggregation data and verify they are gone
        remove_old_report_data()
        self.assertFalse(
            RegionTopicImpression.objects.filter(
                region="us-ca",
                topic="backend-web",
                advertisement=self.ad1,
                date=old_date.date(),
            ).exists()
        )

        # Newer aggregation data are still there
        impression_new = RegionTopicImpression.objects.filter(
            region="us-ca",
            topic="backend-web",
            advertisement=self.ad1,
            date=timezone.now(),
        ).first()
        self.assertIsNotNone(impression_new)
        self.assertEqual(impression_new.offers, 3)
        self.assertEqual(impression_new.views, 2)
        self.assertEqual(impression_new.clicks, 1)

    def test_traffic_fill(self):
        # Ad1/CA - offered/decision=3, views=2, clicks=1
        # Ad1/MX - offered/decision=1, views=1, clicks=0
        # Ad2/MX - offered/decisions=2, views=2, clicks=0
        # All views/clicks on publisher1
        self.flight.total_views = 5
        self.flight.save()
        update_previous_day_reports(timezone.now())

        self.flight.refresh_from_db()

        self.assertIsNotNone(self.flight.traffic_fill)
        self.assertTrue("regions" in self.flight.traffic_fill)
        self.assertTrue("countries" in self.flight.traffic_fill)
        self.assertTrue("publishers" in self.flight.traffic_fill)
        self.assertDictEqual(
            self.flight.traffic_fill["countries"], {"CA": 0.4, "MX": 0.6}
        )
        self.assertDictEqual(
            self.flight.traffic_fill["publishers"], {self.publisher.slug: 1.0}
        )
