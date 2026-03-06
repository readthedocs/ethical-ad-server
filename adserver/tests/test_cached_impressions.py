"""Tests for cached impression writes."""

import datetime

from django.core.cache import cache
from django.test import TestCase
from django.test import override_settings
from django_dynamic_fixture import get

from ..constants import CLICKS
from ..constants import DECISIONS
from ..constants import OFFERS
from ..constants import VIEWS
from ..impression_cache import CachedImpressionWriter
from ..models import AdImpression
from ..models import AdType
from ..models import Advertisement
from ..models import Campaign
from ..models import Flight
from ..models import Publisher
from ..models import PublisherGroup
from ..utils import get_ad_day


class CachedImpressionWriterTests(TestCase):
    """Tests for the CachedImpressionWriter utility."""

    def setUp(self):
        self.publisher = get(
            Publisher, slug="test-publisher", allow_paid_campaigns=True
        )
        self.publisher_group = get(PublisherGroup)
        self.publisher_group.publishers.add(self.publisher)

        self.ad_type = get(AdType, has_image=False, slug="z")
        self.campaign = get(Campaign, publisher_groups=[self.publisher_group])
        self.flight = get(
            Flight,
            live=True,
            campaign=self.campaign,
            sold_clicks=1000,
            cpc=2.0,
            start_date=get_ad_day().date(),
            end_date=get_ad_day().date() + datetime.timedelta(days=30),
            targeting_parameters={},
            pacing_interval=24 * 60 * 60,
        )

        self.ad = get(
            Advertisement,
            name="ad-slug",
            slug="ad-slug",
            link="http://example.com",
            live=True,
            image=None,
            flight=self.flight,
        )
        self.ad.ad_types.add(self.ad_type)

        self.writer = CachedImpressionWriter()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_cache_key_generation(self):
        """Cache keys should be deterministic based on ad, publisher, date, and type."""
        day = get_ad_day().date()
        key = self.writer._cache_key(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.assertIn(str(self.ad.pk), key)
        self.assertIn(str(self.publisher.pk), key)
        self.assertIn(VIEWS, key)

    def test_increment_creates_cache_entry(self):
        """Incrementing should create a cached counter."""
        day = get_ad_day().date()
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)

        key = self.writer._cache_key(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.assertEqual(cache.get(key), 1)

    def test_increment_accumulates(self):
        """Multiple increments should accumulate in cache."""
        day = get_ad_day().date()
        for _ in range(5):
            self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)

        key = self.writer._cache_key(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.assertEqual(cache.get(key), 5)

    def test_increment_tracks_dirty_keys(self):
        """Incremented keys should be tracked for flushing."""
        day = get_ad_day().date()
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, CLICKS)

        dirty_keys = self.writer.get_dirty_keys()
        self.assertEqual(len(dirty_keys), 2)

    def test_flush_writes_to_database(self):
        """Flushing should write accumulated counts to AdImpression."""
        day = get_ad_day().date()

        # Accumulate some impressions
        for _ in range(3):
            self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        for _ in range(2):
            self.writer.increment(self.ad.pk, self.publisher.pk, day, CLICKS)

        # No DB writes yet
        self.assertFalse(
            AdImpression.objects.filter(
                advertisement=self.ad, publisher=self.publisher, date=day
            ).exists()
        )

        # Flush to DB
        flushed = self.writer.flush()
        self.assertGreater(flushed, 0)

        # Verify DB state
        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 3)
        self.assertEqual(impression.clicks, 2)

    def test_flush_clears_dirty_keys(self):
        """After flushing, dirty keys should be cleared."""
        day = get_ad_day().date()
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)

        self.assertEqual(len(self.writer.get_dirty_keys()), 1)

        self.writer.flush()

        self.assertEqual(len(self.writer.get_dirty_keys()), 0)

    def test_flush_clears_cache_values(self):
        """After flushing, cache values should be reset."""
        day = get_ad_day().date()
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)

        key = self.writer._cache_key(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.assertEqual(cache.get(key), 1)

        self.writer.flush()

        self.assertIsNone(cache.get(key))

    def test_flush_accumulates_with_existing_db_records(self):
        """Flushing should add to existing AdImpression records, not replace them."""
        day = get_ad_day().date()

        # Create an existing impression
        AdImpression.objects.create(
            advertisement=self.ad,
            publisher=self.publisher,
            date=day,
            views=10,
            clicks=5,
        )

        # Accumulate more
        for _ in range(3):
            self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, CLICKS)

        self.writer.flush()

        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 13)  # 10 + 3
        self.assertEqual(impression.clicks, 6)  # 5 + 1

    def test_flush_handles_multiple_ads(self):
        """Flushing should handle impressions for different ads."""
        day = get_ad_day().date()

        ad2 = get(
            Advertisement,
            name="ad2",
            slug="ad2-slug",
            link="http://example.com",
            live=True,
            image=None,
            flight=self.flight,
        )

        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(ad2.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(ad2.pk, self.publisher.pk, day, VIEWS)

        self.writer.flush()

        imp1 = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        imp2 = AdImpression.objects.get(
            advertisement=ad2, publisher=self.publisher, date=day
        )
        self.assertEqual(imp1.views, 1)
        self.assertEqual(imp2.views, 2)

    def test_flush_handles_multiple_impression_types(self):
        """Flushing should correctly handle all impression types."""
        day = get_ad_day().date()

        self.writer.increment(self.ad.pk, self.publisher.pk, day, DECISIONS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, OFFERS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, CLICKS)

        self.writer.flush()

        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.decisions, 1)
        self.assertEqual(impression.offers, 1)
        self.assertEqual(impression.views, 1)
        self.assertEqual(impression.clicks, 1)

    def test_flush_with_no_data(self):
        """Flushing with no cached data should be a no-op."""
        flushed = self.writer.flush()
        self.assertEqual(flushed, 0)

    def test_flush_handles_null_advertisement(self):
        """Flushing should handle null advertisement (null offers/decisions)."""
        day = get_ad_day().date()

        # None ad_id represents a null offer (decision with no ad)
        self.writer.increment(None, self.publisher.pk, day, DECISIONS)

        self.writer.flush()

        impression = AdImpression.objects.get(
            advertisement=None, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.decisions, 1)

    def test_multiple_flushes(self):
        """Multiple flush cycles should work correctly."""
        day = get_ad_day().date()

        # First cycle
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.flush()

        # Second cycle
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.flush()

        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 5)  # 2 + 3

    def test_incr_uses_cache_when_enabled(self):
        """Advertisement.incr should use cached writes when setting is enabled."""
        day = get_ad_day().date()

        with override_settings(ADSERVER_IMPRESSION_CACHE_ENABLED=True):
            self.ad.incr(VIEWS, self.publisher)

        # Should NOT be in DB yet
        self.assertFalse(
            AdImpression.objects.filter(
                advertisement=self.ad,
                publisher=self.publisher,
                date=day,
                views__gt=0,
            ).exists()
        )

        # Flush and verify
        writer = CachedImpressionWriter()
        writer.flush()

        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 1)

    def test_incr_uses_db_when_disabled(self):
        """Advertisement.incr should write directly when cache is disabled."""
        day = get_ad_day().date()

        with override_settings(ADSERVER_IMPRESSION_CACHE_ENABLED=False):
            self.ad.incr(VIEWS, self.publisher)

        # Should be in DB immediately
        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 1)

    def test_concurrent_flush_safety(self):
        """Flush should use atomic decr to avoid double-counting."""
        day = get_ad_day().date()

        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)

        # Flush once
        self.writer.flush()

        # Flushing again should be a no-op (no double counting)
        flushed = self.writer.flush()
        self.assertEqual(flushed, 0)

        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 2)

    def test_increments_during_flush_are_preserved(self):
        """Increments that arrive between the snapshot read and the decr are not lost."""
        day = get_ad_day().date()
        key = self.writer._cache_key(self.ad.pk, self.publisher.pk, day, VIEWS)

        # Seed the counter with 3 views
        for _ in range(3):
            self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.assertEqual(cache.get(key), 3)

        # Simulate what flush does internally: snapshot, then write, then decr.
        # Between snapshot and decr, a new increment arrives.
        dirty_keys = self.writer.get_dirty_keys()
        snapshots = {k: cache.get(k) for k in dirty_keys}

        # --- concurrent increment arrives here ---
        self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)
        self.assertEqual(cache.get(key), 4)  # 3 original + 1 new

        # Now finish the flush by writing snapshot to DB and decrementing
        self.writer.flush()

        # The first flush saw 3 + wrote 3 to DB. But the counter was 4 at
        # decr time so 4 - 3 = 1 remains.  That remaining 1 should survive
        # for the next flush cycle.
        #
        # Actually, the full flush re-reads dirty keys and snapshots, so
        # let's just verify end-to-end: after two full flushes, total = 4.
        # Reset and do it properly.

        # --- end-to-end test ---
        cache.clear()
        AdImpression.objects.all().delete()

        for _ in range(3):
            self.writer.increment(self.ad.pk, self.publisher.pk, day, VIEWS)

        # Manually bump the counter to simulate a concurrent increment after
        # the flush snapshots but before it decrements.
        # We'll use a patching approach: patch cache.decr to inject an increment.
        from unittest.mock import patch

        original_decr = cache.decr

        def decr_with_concurrent_increment(k, amount):
            # Before decrementing, simulate a concurrent increment
            cache.incr(k)
            self.writer._add_dirty_key(k)
            return original_decr(k, amount)

        with patch.object(cache, "decr", side_effect=decr_with_concurrent_increment):
            self.writer.flush()

        # After flush: 3 were snapshot and written to DB.
        # During decr, counter went from 3 → 4 (concurrent incr) → 1 (decr by 3).
        # So 1 remains in cache.
        self.assertEqual(cache.get(key), 1)
        self.assertIn(key, self.writer.get_dirty_keys())

        # Second flush picks up the remaining 1
        self.writer.flush()

        impression = AdImpression.objects.get(
            advertisement=self.ad, publisher=self.publisher, date=day
        )
        self.assertEqual(impression.views, 4)  # 3 + 1 concurrent
