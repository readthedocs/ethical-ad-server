"""Tests for the batched database writer."""

import json
import uuid
from datetime import date
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import TestCase
from django.test import override_settings

from ..batch_writer import IMPRESSION_COUNTER_KEY_PREFIX
from ..batch_writer import batch_create_offer
from ..batch_writer import batch_incr_impressions
from ..batch_writer import flush_impression_counters
from ..batch_writer import flush_offer_queue
from ..batch_writer import get_pending_offer
from ..batch_writer import is_impression_batch_enabled
from ..batch_writer import is_offer_batch_enabled
from ..constants import DECISIONS
from ..constants import OFFERS
from ..models import AdImpression
from ..models import Offer
from .common import BaseAdModelsTestCase


class TestIsImpressionBatchEnabled(TestCase):
    """Test the is_impression_batch_enabled function."""

    @override_settings(ADSERVER_BATCH_IMPRESSION_WRITES=False)
    def test_disabled_globally(self):
        publisher = MagicMock()
        publisher.batch_impression_writes = False
        self.assertFalse(is_impression_batch_enabled(publisher))

    @override_settings(ADSERVER_BATCH_IMPRESSION_WRITES=True)
    def test_enabled_globally(self):
        publisher = MagicMock()
        publisher.batch_impression_writes = False
        self.assertTrue(is_impression_batch_enabled(publisher))

    @override_settings(ADSERVER_BATCH_IMPRESSION_WRITES=False)
    def test_enabled_per_publisher(self):
        publisher = MagicMock()
        publisher.batch_impression_writes = True
        self.assertTrue(is_impression_batch_enabled(publisher))

    @override_settings(ADSERVER_BATCH_IMPRESSION_WRITES=False)
    def test_no_publisher(self):
        self.assertFalse(is_impression_batch_enabled(None))


class TestIsOfferBatchEnabled(TestCase):
    """Test the is_offer_batch_enabled function."""

    @override_settings(ADSERVER_BATCH_OFFER_WRITES=False)
    def test_disabled_globally(self):
        publisher = MagicMock()
        publisher.batch_offer_writes = False
        self.assertFalse(is_offer_batch_enabled(publisher))

    @override_settings(ADSERVER_BATCH_OFFER_WRITES=True)
    def test_enabled_globally(self):
        publisher = MagicMock()
        publisher.batch_offer_writes = False
        self.assertTrue(is_offer_batch_enabled(publisher))

    @override_settings(ADSERVER_BATCH_OFFER_WRITES=False)
    def test_enabled_per_publisher(self):
        publisher = MagicMock()
        publisher.batch_offer_writes = True
        self.assertTrue(is_offer_batch_enabled(publisher))

    @override_settings(ADSERVER_BATCH_OFFER_WRITES=False)
    def test_no_publisher(self):
        self.assertFalse(is_offer_batch_enabled(None))


class TestBatchImpressionCounters(BaseAdModelsTestCase):
    """Test batched impression counter increments and flushing."""

    def _make_mock_redis(self):
        """Create a mock Redis client with pipeline support."""
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [1, 1, True]

        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        return mock_redis

    @patch("adserver.batch_writer._get_redis_client")
    def test_batch_incr_impressions_no_redis(self, mock_get_client):
        mock_get_client.return_value = None
        result = batch_incr_impressions(
            self.ad1, self.publisher, (OFFERS, DECISIONS), date.today()
        )
        self.assertFalse(result)

    @patch("adserver.batch_writer._get_redis_client")
    def test_batch_incr_impressions_with_redis(self, mock_get_client):
        mock_redis = self._make_mock_redis()
        mock_get_client.return_value = mock_redis

        result = batch_incr_impressions(
            self.ad1, self.publisher, (OFFERS, DECISIONS), date.today()
        )
        self.assertTrue(result)

        # Verify pipeline calls
        pipe = mock_redis.pipeline.return_value
        self.assertEqual(pipe.hincrby.call_count, 2)
        pipe.expire.assert_called_once()
        pipe.execute.assert_called_once()

        # Verify the key was added to active set
        mock_redis.sadd.assert_called_once()

    @patch("adserver.batch_writer._get_redis_client")
    def test_batch_incr_null_advertisement(self, mock_get_client):
        mock_redis = self._make_mock_redis()
        mock_get_client.return_value = mock_redis

        result = batch_incr_impressions(
            None, self.publisher, (DECISIONS,), date.today()
        )
        self.assertTrue(result)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_counters_empty(self, mock_get_client):
        mock_redis = MagicMock()
        mock_redis.smembers.return_value = set()
        mock_get_client.return_value = mock_redis

        count = flush_impression_counters()
        self.assertEqual(count, 0)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_counters(self, mock_get_client):
        mock_redis = MagicMock()
        day = date.today()
        key = f"{IMPRESSION_COUNTER_KEY_PREFIX}{self.ad1.pk}:{self.publisher.pk}:{day.isoformat()}"

        mock_redis.smembers.return_value = {key.encode()}

        pipe = MagicMock()
        pipe.execute.return_value = [
            {b"offers": b"5", b"decisions": b"5"},
            1,
        ]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_impression_counters()
        self.assertEqual(count, 1)

        # Verify AdImpression was created
        impression = AdImpression.objects.get(
            advertisement=self.ad1,
            publisher=self.publisher,
            date=day,
        )
        self.assertEqual(impression.offers, 5)
        self.assertEqual(impression.decisions, 5)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_counters_existing_record(self, mock_get_client):
        """Test flushing counters when an AdImpression record already exists."""
        day = date.today()

        # Create an existing impression
        impression = AdImpression.objects.create(
            advertisement=self.ad1,
            publisher=self.publisher,
            date=day,
            offers=10,
            decisions=10,
            views=3,
        )

        mock_redis = MagicMock()
        key = f"{IMPRESSION_COUNTER_KEY_PREFIX}{self.ad1.pk}:{self.publisher.pk}:{day.isoformat()}"
        mock_redis.smembers.return_value = {key.encode()}

        pipe = MagicMock()
        pipe.execute.return_value = [
            {b"offers": b"5", b"views": b"2"},
            1,
        ]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_impression_counters()
        self.assertEqual(count, 1)

        # Verify the impression was updated (incremented, not replaced)
        impression.refresh_from_db()
        self.assertEqual(impression.offers, 15)
        self.assertEqual(impression.views, 5)
        self.assertEqual(impression.decisions, 10)  # Unchanged


class TestBatchOfferCreation(BaseAdModelsTestCase):
    """Test batched Offer creation and flushing."""

    def _make_offer_data(self, advertisement=None, publisher=None):
        publisher = publisher or self.publisher
        return {
            "id": str(uuid.uuid4()),
            "date": "2025-01-15T10:30:00+00:00",
            "publisher_id": publisher.pk,
            "ip": "1.2.3.0",
            "user_agent": "Mozilla/5.0",
            "client_id": "test-client-123",
            "country": "US",
            "url": "https://example.com/page",
            "domain": "example.com",
            "paid_eligible": True,
            "rotations": 1,
            "browser_family": "Chrome",
            "os_family": "Windows",
            "is_bot": False,
            "is_mobile": False,
            "is_proxy": False,
            "keywords": ["python", "django"],
            "div_id": "ad-div",
            "ad_type_slug": "text-slug",
            "advertisement_id": advertisement.pk if advertisement else None,
            "viewed": False,
            "clicked": False,
            "uplifted": None,
            "view_time": None,
            "is_refunded": False,
        }

    @patch("adserver.batch_writer._get_redis_client")
    def test_batch_create_offer_no_redis(self, mock_get_client):
        mock_get_client.return_value = None
        result = batch_create_offer(self._make_offer_data(self.ad1))
        self.assertFalse(result)

    @patch("adserver.batch_writer._get_redis_client")
    def test_batch_create_offer_with_redis(self, mock_get_client):
        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [True, 1]
        mock_redis.pipeline.return_value = pipe
        mock_redis.llen.return_value = 1  # Below batch size
        mock_get_client.return_value = mock_redis

        data = self._make_offer_data(self.ad1)
        result = batch_create_offer(data)
        self.assertTrue(result)

        # Verify the offer data was stored
        pipe.setex.assert_called_once()
        pipe.rpush.assert_called_once()

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_offer_queue_empty(self, mock_get_client):
        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [[], 0]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_offer_queue()
        self.assertEqual(count, 0)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_offer_queue(self, mock_get_client):
        data = self._make_offer_data(self.ad1)
        serialized = json.dumps(data, default=str)

        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [[serialized.encode()], 1]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_offer_queue()
        self.assertEqual(count, 1)

        # Verify the offer was created in the database
        offer = Offer.objects.get(id=data["id"])
        self.assertEqual(offer.publisher_id, self.publisher.pk)
        self.assertEqual(offer.advertisement_id, self.ad1.pk)
        self.assertEqual(offer.country, "US")

    @patch("adserver.batch_writer._get_redis_client")
    def test_get_pending_offer_not_found(self, mock_get_client):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_get_client.return_value = mock_redis

        result = get_pending_offer(str(uuid.uuid4()))
        self.assertIsNone(result)

    @patch("adserver.batch_writer._get_redis_client")
    def test_get_pending_offer_found(self, mock_get_client):
        data = self._make_offer_data(self.ad1)
        serialized = json.dumps(data, default=str)

        mock_redis = MagicMock()
        mock_redis.get.return_value = serialized.encode()
        mock_get_client.return_value = mock_redis

        offer = get_pending_offer(data["id"])
        self.assertIsNotNone(offer)
        self.assertEqual(str(offer.pk), data["id"])
        self.assertEqual(offer.publisher_id, self.publisher.pk)

        # Verify the pending key was cleaned up
        mock_redis.delete.assert_called_once()
        mock_redis.lrem.assert_called_once()

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_offer_queue_null_advertisement(self, mock_get_client):
        data = self._make_offer_data()  # No advertisement
        serialized = json.dumps(data, default=str)

        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [[serialized.encode()], 1]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_offer_queue()
        self.assertEqual(count, 1)

        offer = Offer.objects.get(id=data["id"])
        self.assertIsNone(offer.advertisement_id)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_offer_queue_deduplication(self, mock_get_client):
        """Duplicate offers in the queue should only be created once."""
        data = self._make_offer_data(self.ad1)
        serialized = json.dumps(data, default=str)

        mock_redis = MagicMock()
        pipe = MagicMock()
        # Same offer data twice in the queue
        pipe.execute.return_value = [[serialized.encode(), serialized.encode()], 1]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_offer_queue()
        self.assertEqual(count, 1)

        # Only one offer should exist
        self.assertEqual(Offer.objects.filter(id=data["id"]).count(), 1)


class TestBatchAutoFlush(BaseAdModelsTestCase):
    """Test auto-flush when batch size is reached."""

    @override_settings(ADSERVER_BATCH_SIZE=2)
    @patch("adserver.batch_writer._get_redis_client")
    def test_auto_flush_triggers_celery_task(self, mock_get_client):
        """When queue reaches batch size, celery task should be triggered."""
        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [True, 1]
        mock_redis.pipeline.return_value = pipe
        mock_redis.llen.return_value = 2  # Equals batch size

        mock_get_client.return_value = mock_redis

        data = {
            "id": str(uuid.uuid4()),
            "date": "2025-01-15T10:30:00+00:00",
            "publisher_id": self.publisher.pk,
        }
        with patch("adserver.batch_writer.flush_offer_queue") as mock_flush_offers:
            with patch(
                "adserver.batch_writer.flush_impression_counters"
            ) as mock_flush_impressions:
                batch_create_offer(data)
                # Celery import will fail in test, so it falls back to inline flush
                mock_flush_offers.assert_called_once()
                mock_flush_impressions.assert_called_once()

    @patch("adserver.batch_writer._get_redis_client")
    def test_no_redis_for_pending_offer(self, mock_get_client):
        mock_get_client.return_value = None
        result = get_pending_offer(str(uuid.uuid4()))
        self.assertIsNone(result)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_counters_no_redis(self, mock_get_client):
        mock_get_client.return_value = None
        count = flush_impression_counters()
        self.assertEqual(count, 0)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_offer_queue_no_redis(self, mock_get_client):
        mock_get_client.return_value = None
        count = flush_offer_queue()
        self.assertEqual(count, 0)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_offer_queue_bad_json(self, mock_get_client):
        """Bad JSON in queue should be skipped gracefully."""
        mock_redis = MagicMock()
        pipe = MagicMock()
        pipe.execute.return_value = [[b"not-valid-json"], 1]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_offer_queue()
        self.assertEqual(count, 0)

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_counters_invalid_key(self, mock_get_client):
        """Invalid counter keys should be removed from the active set."""
        mock_redis = MagicMock()
        # Key with wrong format (not enough parts)
        mock_redis.smembers.return_value = {b"batch:impression:badkey"}
        pipe = MagicMock()
        pipe.execute.return_value = [{b"offers": b"5"}, 1]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_impression_counters()
        self.assertEqual(count, 0)
        # Should still clean up the bad key
        mock_redis.srem.assert_called_once()

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_counters_empty_hash(self, mock_get_client):
        """Empty counter hashes should be cleaned up."""
        mock_redis = MagicMock()
        key = f"batch:impression:{self.ad1.pk}:{self.publisher.pk}:{date.today().isoformat()}"
        mock_redis.smembers.return_value = {key.encode()}
        pipe = MagicMock()
        pipe.execute.return_value = [{}, 1]  # Empty hash
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_impression_counters()
        self.assertEqual(count, 0)
        mock_redis.srem.assert_called_once()

    @patch("adserver.batch_writer._get_redis_client")
    def test_flush_impression_null_ad_key(self, mock_get_client):
        """Test flushing counters for null advertisement (null offers)."""
        mock_redis = MagicMock()
        day = date.today()
        key = f"batch:impression:null:{self.publisher.pk}:{day.isoformat()}"

        mock_redis.smembers.return_value = {key.encode()}
        pipe = MagicMock()
        pipe.execute.return_value = [{b"decisions": b"3"}, 1]
        mock_redis.pipeline.return_value = pipe
        mock_get_client.return_value = mock_redis

        count = flush_impression_counters()
        self.assertEqual(count, 1)

        impression = AdImpression.objects.get(
            advertisement=None,
            publisher=self.publisher,
            date=day,
        )
        self.assertEqual(impression.decisions, 3)


class TestFlushBatchedDBWritesTask(BaseAdModelsTestCase):
    """Test the Celery task for flushing batched writes."""

    @patch("adserver.batch_writer.flush_impression_counters")
    @patch("adserver.batch_writer.flush_offer_queue")
    def test_flush_task(self, mock_flush_offers, mock_flush_impressions):
        from ..tasks import flush_batched_db_writes

        mock_flush_offers.return_value = 5
        mock_flush_impressions.return_value = 3

        result = flush_batched_db_writes()
        self.assertEqual(result, {"offers": 5, "impressions": 3})
        mock_flush_offers.assert_called_once()
        mock_flush_impressions.assert_called_once()
