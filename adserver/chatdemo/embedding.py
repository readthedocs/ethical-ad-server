"""Embedding utilities for generating ad-targeting embeddings from chat prompts."""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache


log = logging.getLogger(__name__)

# Cache embeddings for 1 hour to avoid redundant API calls
EMBEDDING_CACHE_TIMEOUT = 60 * 60

# The OpenAI embedding model to use - text-embedding-3-small is cheap and fast
EMBEDDING_MODEL = "text-embedding-3-small"


def get_prompt_embedding(prompt_text):
    """
    Generate an embedding vector for the given prompt text using OpenAI.

    Returns a list of floats (the embedding vector) or None on failure.
    """
    if not prompt_text or not prompt_text.strip():
        return None

    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        log.warning("OPENAI_API_KEY not configured, cannot generate prompt embedding")
        return None

    # Check cache first
    cache_key = _embedding_cache_key(prompt_text)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=prompt_text.strip()[:8000],  # Limit input length
        )
        embedding = response.data[0].embedding

        cache.set(cache_key, embedding, EMBEDDING_CACHE_TIMEOUT)
        return embedding

    except Exception:
        log.exception("Failed to generate embedding for prompt")
        return None


def cosine_similarity(vec_a, vec_b):
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = sum(a * a for a in vec_a) ** 0.5
    magnitude_b = sum(b * b for b in vec_b) ** 0.5

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def get_prompt_niche_weights(prompt_text, flights):
    """
    Compute niche targeting weights for flights based on prompt embedding similarity.

    This mirrors the ethicalads_ext.embedding.utils.get_niche_weights interface
    but works directly from prompt text instead of URL content.

    Returns a dict mapping Advertiser -> distance (lower = more similar).
    """
    prompt_embedding = get_prompt_embedding(prompt_text)
    if not prompt_embedding:
        return {}

    weights = {}

    for flight in flights:
        advertiser = flight.campaign.advertiser

        # Skip if we already computed for this advertiser
        if advertiser in weights:
            continue

        # Get the advertiser's embedding if stored, or generate from ad text
        ad_embedding = _get_advertiser_embedding(flight)
        if not ad_embedding:
            continue

        similarity = cosine_similarity(prompt_embedding, ad_embedding)
        # Convert similarity to distance (lower = better match)
        # niche_targeting threshold compares distance < goal
        distance = 1.0 - similarity
        weights[advertiser] = distance

    return weights


def _get_advertiser_embedding(flight):
    """
    Get or generate an embedding for a flight's advertiser content.

    Uses the flight's advertisement text as the content to embed.
    """
    # Build a text representation from the flight's ads
    ad_texts = []
    for ad in flight.advertisements.filter(live=True)[:5]:
        parts = []
        if ad.headline:
            parts.append(ad.headline)
        if ad.content:
            parts.append(ad.content)
        if ad.cta:
            parts.append(ad.cta)
        if not parts and ad.text:
            parts.append(ad.text)
        if parts:
            ad_texts.append(" ".join(parts))

    if not ad_texts:
        return None

    combined_text = " | ".join(ad_texts)
    return get_prompt_embedding(combined_text)


def _embedding_cache_key(text):
    """Generate a cache key for an embedding."""
    text_hash = hashlib.md5(text.strip().lower().encode()).hexdigest()
    return f"prompt-embedding-{text_hash}"
