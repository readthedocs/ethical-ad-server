"""Celery tasks for the ad server."""
import datetime
import logging

from celery.utils.iso8601 import parse_iso8601
from django.db.models import Count

from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import OFFERS
from .constants import VIEWS
from .models import GeoImpression
from .models import Offer
from .models import PlacementImpression
from .utils import get_ad_day
from config.celery_app import app

log = logging.getLogger(__name__)  # noqa


@app.task()
def daily_update_geos(day=None):
    """
    Update the Geo index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date = get_ad_day()
    if day:
        start_date = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + datetime.timedelta(days=1)

    log.info("Updating GeoImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = Offer.objects.filter(
            date__gte=start_date,
            date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
        )

        if impression_type == CLICKS:
            queryset = queryset.filter(clicked=True)
        elif impression_type == VIEWS:
            queryset = queryset.filter(viewed=True)
        elif impression_type == OFFERS:
            queryset = queryset.filter(advertisement__isnull=False)

        for values in (
            queryset.values("publisher", "advertisement", "country")
            .annotate(Count("country"))
            .filter(country__count__gt=0)
            .order_by("-country__count")
        ):
            impression, _ = GeoImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                country=values["country"],
                date=start_date,
            )
            GeoImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["country__count"]}
            )


@app.task()
def daily_update_placements(day=None):
    """
    Update the Placement index each day.

    :arg day: An optional datetime object representing a day
    """
    start_date = get_ad_day()
    if day:
        log.info("Got day: %s", day)
        if not isinstance(day, (datetime.datetime, datetime.date)):
            log.info("Converting day from string")
            day = parse_iso8601(day)
        start_date = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + datetime.timedelta(days=1)

    log.info("Updating PlacementImpressions for %s-%s", start_date, end_date)

    for impression_type in IMPRESSION_TYPES:
        queryset = Offer.objects.filter(
            date__gte=start_date,
            date__lt=end_date,  # Things at UTC midnight should count towards tomorrow
        )

        if impression_type == CLICKS:
            queryset = queryset.filter(clicked=True)
        elif impression_type == VIEWS:
            queryset = queryset.filter(viewed=True)
        elif impression_type == OFFERS:
            queryset = queryset.filter(advertisement__isnull=False)

        for values in (
            queryset.values("publisher", "advertisement", "div_id", "ad_type_slug")
            .annotate(Count("div_id"))
            .filter(div_id__count__gt=0)
            .filter(publisher__record_placements=True)
            .exclude(div_id__regex=r"(rtd-\w{4}|ad_\w{4}).*")
            .order_by("-div_id")
        ):

            impression, _ = PlacementImpression.objects.get_or_create(
                publisher_id=values["publisher"],
                advertisement_id=values["advertisement"],
                div_id=values["div_id"],
                ad_type_slug=values["ad_type_slug"],
                date=start_date,
            )
            PlacementImpression.objects.filter(pk=impression.pk).update(
                **{impression_type: values["div_id__count"]}
            )
