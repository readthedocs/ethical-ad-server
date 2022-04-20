"""Tasks for analyzing URLs for topics and keywords."""
import datetime
import logging

from django.utils import timezone

from ..models import Offer
from ..models import Publisher
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
def daily_visited_urls(days=2):
    """Analyze URLs that were visited recently but have never been analyzed."""
    dt_cutoff = timezone.now() - datetime.timedelta(days=days)

    # Loop over each publisher and query the offers table for distinct URLs
    for publisher in Publisher.objects.all():
        for obj in (
            Offer.objects.filter(publisher=publisher, date__gt=dt_cutoff)
            .values("url")
            .distinct()
        ):
            url = obj["url"]
            if not url:
                # Blank URLs can't be analyzed
                continue

            normalized_url = normalize_url(url)
            if not AnalyzedUrl.objects.filter(
                url=normalized_url, publisher_id=publisher.id
            ).exists():
                analyze_url.apply_async(args=[normalized_url, publisher.slug])


@app.task
def weekly_analyze_urls(days=7):
    """Analyze URLs that have been visited but not analyzed since DAYS number of days."""
    dt_cutoff = timezone.now() - datetime.timedelta(days=days)

    analyzed_urls = AnalyzedUrl.objects.filter(
        last_analyzed_date__lt=dt_cutoff, visits_since_last_analyzed__gt=0
    ).select_related()
    for analyzed_url in analyzed_urls:
        analyze_url.apply_async(args=[analyzed_url.url, analyzed_url.publisher.slug])
