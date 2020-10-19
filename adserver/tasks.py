from django.db import Count

from ..config.celery_app import app
from .models import GeoImpression
from .models import Offer
from .utils import get_ad_day


@app.task()
def daily_update_geos(day=None):
    """
    Update the Geo index each day
    """

    beginning_of_today = get_ad_day()
    for values in (
        Offer.objects.filter(date__gte=beginning_of_today, viewed=True)
        .values("publisher", "advertisement", "country")
        .annotate(Count("country"))
        .filter(country__count__gt=0)
        .order_by("-country__count")
    ):
        impression, _ = GeoImpression.objects.get_or_create(
            publisher_id=values["publisher"],
            advertisement_id=values["advertisement"],
            country=values["country"],
            date=beginning_of_today,
        )
        GeoImpression.objects.filter(pk=impression.pk).update(
            views=values["country__count"]
        )

    for values in (
        Offer.objects.filter(date__gte=beginning_of_today, clicked=True)
        .values("publisher", "advertisement", "country")
        .annotate(Count("country"))
        .filter(country__count__gt=0)
        .order_by("-country__count")
    ):
        impression, _ = GeoImpression.objects.get_or_create(
            publisher_id=values["publisher"],
            advertisement_id=values["advertisement"],
            country=values["country"],
            date=beginning_of_today,
        )
        GeoImpression.objects.filter(pk=impression.pk).update(
            clicks=values["country__count"]
        )
