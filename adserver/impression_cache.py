"""Cached impression writer for batching AdImpression database writes."""

import logging

from django.core.cache import cache
from django.db import models

from .constants import IMPRESSION_TYPES


log = logging.getLogger(__name__)

# Cache key prefix for impression counters
IMPRESSION_CACHE_PREFIX = "impression_cache"

# Cache key for tracking which keys have pending data
DIRTY_KEYS_CACHE_KEY = f"{IMPRESSION_CACHE_PREFIX}:dirty_keys"

# Cache timeout for impression data (2 hours - generous buffer for flush intervals)
IMPRESSION_CACHE_TIMEOUT = 2 * 60 * 60


class CachedImpressionWriter:
    """
    Buffer AdImpression increments in Django's cache and flush to the DB in batch.

    Instead of hitting the database on every ad impression (offer, view, click),
    this writer accumulates counts in the cache and periodically flushes them
    to the AdImpression table.

    Usage::

        writer = CachedImpressionWriter()
        writer.increment(ad_id, publisher_id, date, "views")
        # ... later ...
        writer.flush()  # writes all pending counts to DB
    """

    def _cache_key(self, ad_id, publisher_id, date, impression_type):
        """Build a deterministic cache key for an impression counter."""
        return (
            f"{IMPRESSION_CACHE_PREFIX}"
            f":{ad_id}:{publisher_id}:{date}:{impression_type}"
        )

    def _parse_cache_key(self, key):
        """Parse a cache key back into its component parts."""
        parts = key.split(":")
        # prefix:ad_id:publisher_id:date:impression_type
        ad_id = None if parts[1] == "None" else int(parts[1])
        publisher_id = int(parts[2])
        date_str = parts[3]
        impression_type = parts[4]
        return ad_id, publisher_id, date_str, impression_type

    def increment(self, ad_id, publisher_id, date, impression_type):
        """
        Increment a cached impression counter.

        :param ad_id: Advertisement PK (or None for null offers)
        :param publisher_id: Publisher PK
        :param date: The date for this impression
        :param impression_type: One of IMPRESSION_TYPES (decisions, offers, views, clicks)
        """
        assert impression_type in IMPRESSION_TYPES

        key = self._cache_key(ad_id, publisher_id, date, impression_type)

        # Try to increment; if the key doesn't exist, set it to 1
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=IMPRESSION_CACHE_TIMEOUT)

        # Track this key as dirty (needing flush)
        self._add_dirty_key(key)

    def _add_dirty_key(self, key):
        """Add a key to the set of dirty keys that need flushing."""
        dirty_keys = cache.get(DIRTY_KEYS_CACHE_KEY) or set()
        dirty_keys.add(key)
        cache.set(DIRTY_KEYS_CACHE_KEY, dirty_keys, timeout=IMPRESSION_CACHE_TIMEOUT)

    def get_dirty_keys(self):
        """Return the set of cache keys with pending data."""
        return cache.get(DIRTY_KEYS_CACHE_KEY) or set()

    def flush(self):
        """
        Flush all cached impression data to the database.

        Returns the number of impression records written/updated.
        """
        from .models import AdImpression

        dirty_keys = self.get_dirty_keys()
        if not dirty_keys:
            return 0

        # Collect all pending data, grouped by (ad_id, publisher_id, date)
        # so we can batch updates per impression record
        pending = {}
        for key in dirty_keys:
            count = cache.get(key)
            if count is None or count == 0:
                continue

            ad_id, publisher_id, date_str, impression_type = self._parse_cache_key(key)
            group_key = (ad_id, publisher_id, date_str)

            if group_key not in pending:
                pending[group_key] = {}
            pending[group_key][impression_type] = count

        flushed = 0
        for (ad_id, publisher_id, date_str), type_counts in pending.items():
            try:
                # Get or create the impression record
                impression, created = AdImpression.objects.using(
                    "default"
                ).get_or_create(
                    advertisement_id=ad_id,
                    publisher_id=publisher_id,
                    date=date_str,
                    defaults=type_counts,
                )

                if not created:
                    # Update existing record with F() expressions for atomicity
                    AdImpression.objects.using("default").filter(
                        pk=impression.pk
                    ).update(
                        **{
                            imp_type: models.F(imp_type) + count
                            for imp_type, count in type_counts.items()
                        }
                    )

                flushed += 1
            except Exception:
                log.exception(
                    "Failed to flush impression cache: ad=%s publisher=%s date=%s",
                    ad_id,
                    publisher_id,
                    date_str,
                )
                continue

        # Clear all flushed keys from cache
        for key in dirty_keys:
            cache.delete(key)
        cache.delete(DIRTY_KEYS_CACHE_KEY)

        if flushed:
            log.info("Flushed %d cached impression records to database", flushed)

        return flushed
