"""
Batched database writer for ad impressions and offers.

Instead of writing to the database on every ad decision,
this module accumulates writes in Redis and flushes them
in bulk periodically. This reduces per-request database load significantly.

Enable impression batching via ``ADSERVER_BATCH_IMPRESSION_WRITES = True``
or per-publisher via ``Publisher.batch_impression_writes = True``.

Enable offer batching via ``ADSERVER_BATCH_OFFER_WRITES = True``
or per-publisher via ``Publisher.batch_offer_writes = True``.
"""

import json
import logging
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import models

from .constants import CLICKS
from .constants import DECISIONS
from .constants import OFFERS
from .constants import VIEWS


log = logging.getLogger(__name__)

# Redis key prefixes for batched data
IMPRESSION_COUNTER_KEY_PREFIX = "batch:impression:"
OFFER_QUEUE_KEY = "batch:offers"
OFFER_PENDING_KEY_PREFIX = "batch:offer:"

# All impression counter fields we track
IMPRESSION_FIELDS = (OFFERS, DECISIONS, VIEWS, CLICKS)


def is_impression_batch_enabled(publisher=None):
    """Check if batched AdImpression writes are enabled."""
    global_enabled = getattr(settings, "ADSERVER_BATCH_IMPRESSION_WRITES", False)
    if publisher and hasattr(publisher, "batch_impression_writes"):
        return publisher.batch_impression_writes or global_enabled
    return global_enabled


def is_offer_batch_enabled(publisher=None):
    """Check if batched Offer writes are enabled."""
    global_enabled = getattr(settings, "ADSERVER_BATCH_OFFER_WRITES", False)
    if publisher and hasattr(publisher, "batch_offer_writes"):
        return publisher.batch_offer_writes or global_enabled
    return global_enabled


def get_batch_size():
    """Return the configured batch size before flushing."""
    return getattr(settings, "ADSERVER_BATCH_SIZE", 100)


def _get_redis_client():
    """
    Get the raw Redis client from django-redis cache backend.

    Returns None if the cache backend doesn't support Redis
    (e.g. LocMemCache in development).
    """
    try:
        return cache.client.get_client()
    except (AttributeError, Exception):
        return None


def _impression_counter_key(advertisement_id, publisher_id, date_str):
    """Build the Redis hash key for an AdImpression counter."""
    ad_key = advertisement_id if advertisement_id else "null"
    return f"{IMPRESSION_COUNTER_KEY_PREFIX}{ad_key}:{publisher_id}:{date_str}"


def batch_incr_impressions(advertisement, publisher, impression_types, day):
    """
    Increment impression counters in Redis instead of the database.

    Counters are stored in Redis as simple key-value pairs
    and flushed to the database periodically.

    Returns True if the increment was batched, False if it should fall
    through to the normal DB write path.
    """
    redis_client = _get_redis_client()
    if redis_client is None:
        return False

    ad_id = advertisement.pk if advertisement else None
    date_str = day.isoformat()
    key = _impression_counter_key(ad_id, publisher.pk, date_str)

    pipe = redis_client.pipeline()
    for imp_type in impression_types:
        pipe.hincrby(key, imp_type, 1)
    # Set a TTL of 24 hours so keys don't accumulate forever if flush fails
    pipe.expire(key, 86400)
    pipe.execute()

    # Track all active counter keys in a set so we can find them during flush
    redis_client.sadd(f"{IMPRESSION_COUNTER_KEY_PREFIX}active_keys", key)

    return True


def batch_create_offer(offer_data):
    """
    Queue an offer for batched creation instead of immediate DB insert.

    The offer_data dict contains all fields needed to create the Offer.
    The UUID primary key is pre-generated so we can return it as the nonce.

    Stores the offer data in Redis so it can be looked up if a view/click
    arrives before the batch is flushed.

    Returns True if the offer was batched, False if it should fall
    through to the normal DB write path.
    """
    redis_client = _get_redis_client()
    if redis_client is None:
        return False

    offer_id = str(offer_data["id"])

    # Store the full offer data so get_offer can find it before flush
    serialized = json.dumps(offer_data, default=str)
    pipe = redis_client.pipeline()
    # Store in the pending offers hash for quick lookup by UUID
    pipe.setex(f"{OFFER_PENDING_KEY_PREFIX}{offer_id}", 3600, serialized)
    # Also push to the queue for bulk creation
    pipe.rpush(OFFER_QUEUE_KEY, serialized)
    pipe.execute()

    # Auto-flush if queue has grown large enough
    queue_len = redis_client.llen(OFFER_QUEUE_KEY)
    if queue_len >= get_batch_size():
        # Trigger async flush if celery is available, otherwise flush inline
        try:
            from .tasks import flush_batched_db_writes

            flush_batched_db_writes.delay()
        except Exception:
            flush_offer_queue()
            flush_impression_counters()

    return True


def get_pending_offer(nonce):
    """
    Look up an offer that may still be in the Redis batch queue.

    If found, immediately flush it to the database and return
    the saved Offer instance. This handles the case where a
    view/click arrives before the batch has been flushed.

    Returns None if the offer is not in the pending queue.
    """
    redis_client = _get_redis_client()
    if redis_client is None:
        return None

    offer_key = f"{OFFER_PENDING_KEY_PREFIX}{nonce}"
    data = redis_client.get(offer_key)
    if data is None:
        return None

    # Found in Redis - flush this single offer to the DB immediately

    offer_data = json.loads(data)
    # Remove from pending
    redis_client.delete(offer_key)
    # Remove from queue (best-effort, flush will skip duplicates)
    redis_client.lrem(OFFER_QUEUE_KEY, 1, data)

    offer = _create_offer_from_data(offer_data)
    try:
        offer.save()
    except Exception:
        log.exception("Failed to save pending offer %s", nonce)
        return None
    return offer


def _create_offer_from_data(offer_data):
    """Create an Offer instance from serialized data dict and save it to the database."""
    from datetime import datetime

    from django.utils import timezone as tz

    from .models import Offer

    offer_data = offer_data.copy()
    offer_data["id"] = uuid.UUID(offer_data["id"])

    # Convert ISO date string back to datetime
    if isinstance(offer_data.get("date"), str):
        dt = datetime.fromisoformat(offer_data["date"])
        if dt.tzinfo is None:
            dt = tz.make_aware(dt)
        offer_data["date"] = dt

    # Convert advertisement_id and publisher_id (may be stored as strings)
    if offer_data.get("advertisement_id"):
        offer_data["advertisement_id"] = int(offer_data["advertisement_id"])
    if offer_data.get("publisher_id"):
        offer_data["publisher_id"] = int(offer_data["publisher_id"])

    return Offer(**offer_data)


def flush_offer_queue():
    """
    Flush all pending offers from the Redis queue to the database via bulk_create.

    Returns the number of offers flushed.
    """
    from .models import Offer

    redis_client = _get_redis_client()
    if redis_client is None:
        return 0

    # Atomically grab all items from the queue
    pipe = redis_client.pipeline()
    pipe.lrange(OFFER_QUEUE_KEY, 0, -1)
    pipe.delete(OFFER_QUEUE_KEY)
    results = pipe.execute()
    items = results[0]

    if not items:
        return 0

    offers = []
    offer_ids_seen = set()
    for item in items:
        try:
            data = json.loads(item)
            offer_id = data["id"]
            if offer_id in offer_ids_seen:
                # Skip duplicates (may have been flushed individually by get_pending_offer)
                continue
            offer_ids_seen.add(offer_id)
            offer = _create_offer_from_data(data)
            offers.append(offer)
        except (json.JSONDecodeError, KeyError, ValueError):
            log.exception("Failed to deserialize batched offer")
            continue

    if not offers:
        return 0

    # Use ignore_conflicts=True to skip any offers already flushed individually
    try:
        created = Offer.objects.bulk_create(offers, ignore_conflicts=True)
        count = len(created)
    except Exception:
        log.exception("Failed to bulk_create %d offers", len(offers))
        count = 0

    # Clean up pending keys for successfully created offers
    if count > 0:
        pipe = redis_client.pipeline()
        for offer_id in offer_ids_seen:
            pipe.delete(f"{OFFER_PENDING_KEY_PREFIX}{offer_id}")
        pipe.execute()

    log.info("Flushed %d batched offers to database", count)
    return count


def flush_impression_counters():
    """
    Flush all batched impression counters from Redis to the database.

    Reads accumulated counters from Redis hashes and applies them
    to AdImpression records using get_or_create + F() updates.

    Returns the number of impression records updated.
    """
    from .models import AdImpression

    redis_client = _get_redis_client()
    if redis_client is None:
        return 0

    # Get all active counter keys
    active_keys_set = f"{IMPRESSION_COUNTER_KEY_PREFIX}active_keys"
    keys = redis_client.smembers(active_keys_set)
    if not keys:
        return 0

    count = 0
    keys_to_remove = []

    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key

        # Atomically read and delete the hash
        pipe = redis_client.pipeline()
        pipe.hgetall(key_str)
        pipe.delete(key_str)
        results = pipe.execute()
        counters = results[0]

        if not counters:
            keys_to_remove.append(key)
            continue

        # Parse the key to get advertisement_id, publisher_id, date
        # Format: batch:impression:{ad_id}:{pub_id}:{date}
        parts = key_str.replace(IMPRESSION_COUNTER_KEY_PREFIX, "").split(":")
        if len(parts) != 3:
            log.warning("Invalid impression counter key: %s", key_str)
            keys_to_remove.append(key)
            continue

        ad_key, pub_id_str, date_str = parts

        try:
            from datetime import date as date_type

            advertisement_id = None if ad_key == "null" else int(ad_key)
            publisher_id = int(pub_id_str)
            day = date_type.fromisoformat(date_str)
        except (ValueError, TypeError):
            log.warning("Failed to parse impression counter key: %s", key_str)
            keys_to_remove.append(key)
            continue

        # Decode counters
        decoded_counters = {}
        for field, value in counters.items():
            field_name = field.decode() if isinstance(field, bytes) else field
            field_value = int(value.decode() if isinstance(value, bytes) else value)
            if field_name in IMPRESSION_FIELDS and field_value > 0:
                decoded_counters[field_name] = field_value

        if not decoded_counters:
            keys_to_remove.append(key)
            continue

        # Apply to database
        try:
            impression, created = AdImpression.objects.using("default").get_or_create(
                advertisement_id=advertisement_id,
                publisher_id=publisher_id,
                date=day,
                defaults=decoded_counters,
            )

            if not created:
                AdImpression.objects.using("default").filter(pk=impression.pk).update(
                    **{
                        field: models.F(field) + value
                        for field, value in decoded_counters.items()
                    }
                )

            count += 1
        except Exception:
            log.exception("Failed to flush impression counters for key: %s", key_str)
            # Don't remove key so it can be retried
            continue

        keys_to_remove.append(key)

    # Clean up processed keys from the active set
    if keys_to_remove:
        redis_client.srem(active_keys_set, *keys_to_remove)

    log.info("Flushed %d batched impression counter groups to database", count)
    return count
