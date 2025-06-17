"""Tasks for analyzing URLs for topics and keywords."""

import datetime
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.utils import timezone

from config.celery_app import app

from ..constants import PAID
from ..models import Offer
from ..models import Publisher
from ..utils import get_day
from .constants import ANALYZER_MIN_VISITS
from .constants import ANALYZER_REANALYZE_DATE_THRESHOLD
from .models import AnalyzedUrl
from .utils import get_url_analyzer_backends
from .utils import normalize_url


log = logging.getLogger(__name__)  # noqa


@app.task
def analyze_url(url, publisher_slug, force=False):
    """
    Analyze a given URL on a publisher's site.

    - Creates or updates an entry in AnalyzedUrls table
    - Discovers keywords and topics for a URL
    """
    skip_renanalyze_days_threshold = 30
    normalized_url = normalize_url(url)

    publisher = Publisher.objects.filter(slug=publisher_slug).first()
    if not publisher:
        log.warning("Analyzing URL for nonexistent publisher: %s", publisher_slug)
        return

    # Check if we've recently analyzed the URL
    # If we have, skip it
    existing_record = AnalyzedUrl.objects.filter(
        url=normalized_url, publisher=publisher
    ).first()

    if (
        existing_record
        and not force
        and existing_record.last_analyzed_date
        and existing_record.last_analyzed_date
        > (timezone.now() - datetime.timedelta(days=skip_renanalyze_days_threshold))
    ):
        log.warning("URL recently analyzed. Skipping.")
        return

    log.debug("Analyzing url: %s", normalized_url)
    keywords = set()
    response = None

    for backend in get_url_analyzer_backends():
        backend_instance = backend(url)
        # Cache responses across backends
        if not response:
            response = backend_instance.fetch()

        analyzed_keywords = backend_instance.analyze(response)  # Can be None
        if analyzed_keywords:
            log.debug("Keywords from '%s': %s", backend.__name__, analyzed_keywords)

            for kw in analyzed_keywords:
                keywords.add(kw)

    log.debug("Keywords found : %s", keywords)

    keywords = list(keywords)
    url_obj, created = AnalyzedUrl.objects.get_or_create(
        url=normalized_url,
        publisher=publisher,
        defaults={
            "keywords": keywords,
            "last_analyzed_date": timezone.now(),
        },
    )

    if not created:
        url_obj.keywords = keywords
        url_obj.last_analyzed_date = timezone.now()
        url_obj.visits_since_last_analyzed = 0

        url_obj.save()

    # If available, also analyze this URL with embeddings
    if "ethicalads_ext.embedding" in settings.INSTALLED_APPS:
        from ethicalads_ext.embedding.tasks import analyze_publisher_url

        analyze_publisher_url.apply_async(
            args=[url, publisher_slug, True],
            queue="analyzer",
        )


@app.task
def daily_visited_urls_aggregation(day=None):
    """Aggregate URLs and update how many times they were visited in the last day."""
    if day is None:
        # Do the previous day's reports
        day = timezone.now() - datetime.timedelta(days=1)

    start_date, end_date = get_day(day)

    log.debug("Calculating daily visited URLs for %s - %s", start_date, end_date)

    validator = URLValidator(schemes=("http", "https"))

    # Query the offers table for distinct URLs
    for obj in (
        Offer.objects.using(settings.REPLICA_SLUG)
        .filter(
            date__gte=start_date,
            date__lt=end_date,
        )
        .filter(viewed=True)
        .filter(advertisement__flight__campaign__campaign_type=PAID)
        .values("url", "publisher_id")
        .annotate(visits=models.Count("url"))
        .iterator()
    ):
        url = obj["url"]
        publisher_id = obj["publisher_id"]
        visits = obj["visits"]

        if not url:
            # Blank URLs can't be analyzed
            continue

        normalized_url = normalize_url(url)

        try:
            # Ensure the URL is valid
            validator(normalized_url)
        except ValidationError:
            log.warning(
                "Invalid normalized URL. normalized=%s, original=%s",
                normalized_url,
                url,
            )
            continue

        url_obj, created = AnalyzedUrl.objects.get_or_create(
            url=normalized_url,
            publisher_id=publisher_id,
            defaults={
                "last_ad_served_date": timezone.now(),
                "visits_since_last_analyzed": visits,
            },
        )

        if not created:
            # If the object wasn't created, add the visits and set the ad last served date
            AnalyzedUrl.objects.filter(pk=url_obj.pk).update(
                last_ad_served_date=timezone.now(),
                visits_since_last_analyzed=models.F("visits_since_last_analyzed")
                + visits,
            )


@app.task
def daily_analyze_urls(
    days=ANALYZER_REANALYZE_DATE_THRESHOLD, min_visits=ANALYZER_MIN_VISITS
):
    """Analyze URLs that have been visited `min_visits` times but not analyzed since `days` number of days."""
    dt_cutoff = timezone.now() - datetime.timedelta(days=days)

    analyzed_urls = AnalyzedUrl.objects.filter(
        last_analyzed_date__lt=dt_cutoff, visits_since_last_analyzed__gte=min_visits
    ).select_related()

    log.debug("URLs to analyze: %s", analyzed_urls.count())
    for analyzed_url in analyzed_urls:
        analyze_url.apply_async(
            args=[analyzed_url.url, analyzed_url.publisher.slug], queue="analyzer"
        )
