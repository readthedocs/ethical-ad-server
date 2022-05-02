"""Tasks for analyzing URLs for topics and keywords."""
import datetime
import logging

from django.conf import settings
from django.db import models
from django.utils import timezone

from ..constants import PAID
from ..models import Offer
from ..models import Publisher
from ..utils import get_day
from .models import AnalyzedUrl
from .utils import get_url_analyzer_backend
from .utils import normalize_url
from config.celery_app import app


log = logging.getLogger(__name__)  # noqa


@app.task
def analyze_url(url, publisher_slug):
    """
    Analyze a given URL on a publisher's site.

    - Creates or updates an entry in AnalyzedUrls table
    - Discovers keywords and topics for a URL
    """
    normalized_url = normalize_url(url)

    publisher = Publisher.objects.filter(slug=publisher_slug).first()
    if not publisher:
        log.warning("Analyzing URL for nonexistent publisher: %s", publisher_slug)
        return

    log.debug("Analyzing url: %s", normalized_url)

    backend = get_url_analyzer_backend()(url)
    keywords = backend.analyze()  # Can be None

    url_obj, created = AnalyzedUrl.objects.get_or_create(
        url=normalized_url,
        publisher=publisher,
        defaults={"keywords": keywords, "last_analyzed_date": timezone.now()},
    )

    if not created:
        url_obj.keywords = keywords
        url_obj.last_analyzed_date = timezone.now()
        url_obj.visits_since_last_analyzed = 0
        url_obj.save()


@app.task
def daily_visited_urls_aggregation(day=None):
    """Aggregate URLs and update how many times they were visited in the last day."""
    if day is None:
        # Do the previous day's reports
        day = timezone.now() - datetime.timedelta(days=1)

    start_date, end_date = get_day(day)

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
            url_obj.update(
                last_ad_served_date=timezone.now(),
                visits_since_last_analyzed=models.F("visits_since_last_analyzed")
                + visits,
            )


@app.task
def daily_analyze_urls(days=7, min_visits=50):
    """Analyze URLs that have been visited `min_visits` times but not analyzed since `days` number of days."""
    dt_cutoff = timezone.now() - datetime.timedelta(days=days)

    analyzed_urls = AnalyzedUrl.objects.filter(
        last_analyzed_date__lt=dt_cutoff, visits_since_last_analyzed__gte=min_visits
    ).select_related()

    log.debug("URLs to analyze: %s", analyzed_urls.count())
    for analyzed_url in analyzed_urls:
        analyze_url.apply_async(args=[analyzed_url.url, analyzed_url.publisher.slug])
