"""Celery tasks for the ad server."""
import datetime
import json
import logging

from celery.utils.iso8601 import parse_iso8601
from django.db.models import Count

from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import VIEWS
from .models import AdImpression
from .models import Advertisement
from .models import GeoImpression
from .models import KeywordImpression
from .models import Offer
from .models import PlacementImpression
from .utils import get_ad_day
from config.celery_app import app

log = logging.getLogger(__name__)  # noqa


def _get_day(day):
    """Get the start and end time with support for celery-encoded strings, dates, and datetimes."""
    start_date = get_ad_day()
    if day:
        log.info("Got day: %s", day)
        if not isinstance(day, (datetime.datetime, datetime.date)):
            log.info("Converting day from string")
            day = parse_iso8601(day)
        start_date = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + datetime.timedelta(days=1)

    return (start_date, end_date)


def _default_filters(impression_type, start_date, end_date):
    """Filter the queryset by date and impression type."""
    queryset = Offer.objects.filter(
        date__gte=start_date,
        date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
        is_refunded=False,
    )

    if impression_type == CLICKS:
        queryset = queryset.filter(clicked=True)
    elif impression_type == VIEWS:
        queryset = queryset.filter(viewed=True)
    elif impression_type == OFFERS:
        queryset = queryset.filter(advertisement__isnull=False)

    return queryset


@app.task()
def daily_update_geos(day=None):
    """
    Update the Geo index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating GeoImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)
        for values in (
            queryset.values("publisher", "advertisement", "country")
            .annotate(total=Count("country"))
            .filter(total__gt=0)
            .order_by("-total")
        ):
            impression, _ = GeoImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                country=values["country"],
                date=start_date,
            )
            GeoImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
            )


@app.task()
def daily_update_placements(day=None):
    """
    Update the Placement index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating PlacementImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)
        for values in (
            queryset.values("publisher", "advertisement", "div_id", "ad_type_slug")
            .annotate(total=Count("div_id"))
            .filter(total__gt=0)
            .filter(publisher__record_placements=True)
            .exclude(div_id__regex=r"(rtd-\w{4}|ad_\w{4}).*")
            .order_by("-total")
        ):

            impression, _ = PlacementImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                div_id=values["div_id"],
                ad_type_slug=values["ad_type_slug"],
                date=start_date,
            )
            PlacementImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
            )


@app.task()
def daily_update_impressions(day=None):
    """
    Update the AdImpression index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating AdImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)

        for values in (
            queryset.values("publisher", "advertisement")
            # This needs to be publisher and not advertisement to gets decisions properly
            .annotate(total=Count("publisher"))
            .filter(total__gt=0)
            .order_by("-total")
        ):

            impression, _ = AdImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                date=start_date,
            )
            AdImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["total"]}
            )


@app.task()
def daily_update_keywords(day=None):
    """
    Update the KeywordImpression index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date, end_date = _get_day(day)

    log.info("Updating KeywordImpression for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = _default_filters(impression_type, start_date, end_date)

        for values in (
            queryset.values("publisher", "advertisement", "keywords")
            .annotate(total=Count("keywords"))
            .filter(total__gt=0)
            .order_by("-total")
            .values(
                "publisher",
                "advertisement",
                "keywords",
                "advertisement__flight__targeting_parameters",
                "total",
            )
        ):
            if not (
                values["keywords"]
                and values["advertisement__flight__targeting_parameters"]
            ):
                continue

            keywords = json.loads(values["keywords"])
            publisher_keywords = set(keywords)

            flight_targeting = json.loads(
                values["advertisement__flight__targeting_parameters"]
            )
            flight_keywords = set(flight_targeting.get("include_keywords", {}))

            matched_keywords = publisher_keywords & flight_keywords
            for keyword in matched_keywords:
                impression, _ = KeywordImpression.objects.get_or_create(
                    date=start_date,
                    publisher_id=values["publisher"],
                    advertisement_id=values["advertisement"],
                    keyword=keyword,
                )
                KeywordImpression.objects.filter(pk=impression.pk).update(
                    **{impression_type: values["total"]}
                )
