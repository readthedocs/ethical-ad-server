"""Mixins for advertiser and publisher views."""
from django.conf import settings
from django.core.paginator import Paginator
from django.db import connection
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django_countries import countries

from .models import Advertiser
from .models import Publisher


class AdvertiserAccessMixin:

    """Mixin for checking advertiser access that works with the ``UserPassesTestMixin``."""

    advertiser_slug_parameter = "advertiser_slug"

    def test_func(self):
        """The user must have access on the advertiser or be staff."""
        if self.request.user.is_anonymous:
            return False

        advertiser = get_object_or_404(
            Advertiser, slug=self.kwargs[self.advertiser_slug_parameter]
        )
        return (
            self.request.user.is_staff
            or advertiser in self.request.user.advertisers.all()
        )


class PublisherAccessMixin:

    """Mixin for checking publisher access that works with the ``UserPassesTestMixin``."""

    publisher_slug_parameter = "publisher_slug"

    def test_func(self):
        """The user must have access on the publisher or be staff."""
        if self.request.user.is_anonymous:
            return False

        publisher = get_object_or_404(
            Publisher, slug=self.kwargs[self.publisher_slug_parameter]
        )
        return (
            self.request.user.is_staff
            or publisher in self.request.user.publishers.all()
        )


class GeoReportMixin:

    """Provide geo report functionality. MUST be used with BaseReportView."""

    def get_queryset(self, **kwargs):
        queryset = super().get_queryset(**kwargs)

        if "country" in kwargs and kwargs["country"]:
            queryset = queryset.filter(country=kwargs["country"])

        if "countries" in kwargs and kwargs["countries"]:
            queryset = queryset.filter(country__in=kwargs["countries"])

        return queryset

    def get_country_options(self, queryset):
        countries_dict = dict(countries)

        # The order_by here is to enable distinct to work
        # https://docs.djangoproject.com/en/dev/ref/models/querysets/#distinct
        country_list = (
            queryset.values_list("country", flat=True)
            .annotate(total_views=models.Sum("views"))
            .order_by("-total_views")
            .distinct()[: self.LIMIT]
        )

        return ((cc, countries_dict.get(cc, "Unknown")) for cc in country_list)

    def get_country_name(self, country):
        countries_dict = dict(countries)
        return countries_dict.get(country)


class EstimatedCountPaginator(Paginator):

    """
    Paginator that gives only an estimated count based on DB statistics..

    This only works for PostgreSQL. Other database engines always return the full count.
    """

    @cached_property
    def count(self):
        if (
            settings.DEBUG
            or "postgresql" not in settings.DATABASES["default"]["ENGINE"]
        ):
            return super().count

        query = self.object_list.query

        # We set the timeout in a db transaction to prevent it from
        # affecting other transactions.
        with connection.cursor() as cursor:
            # This is postgres specific
            cursor.execute(
                "SELECT reltuples FROM pg_class WHERE relname = %s",
                [query.model._meta.db_table],
            )
            return int(cursor.fetchone()[0])
