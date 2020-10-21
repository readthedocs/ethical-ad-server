"""Celery tasks for the ad server."""
import datetime
import logging

from django.db.models import Count

from .constants import CLICKS
from .constants import IMPRESSION_TYPES
from .constants import VIEWS
from .models import GeoImpression
from .models import Offer
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
