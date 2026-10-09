"""Nightly DuckDB aggregations using offers parquet files and Ibis."""

import ibis
from django_countries import countries

from ..models import Region
from .utils import day_to_offers_parquet_url
from .utils import set_duckdb_memory_limit
from .utils import setup_duckdb_aws_connection
from .utils import setup_duckdb_pg_connection


class BaseAggregation:
    """Base class for DuckDB/Ibis aggregations."""

    table = None

    def __init__(self, start_date, end_date, parquet_url=None, con=None):
        self.start_date = start_date
        self.end_date = end_date
        self.con = con

        if not parquet_url:
            self.parquet_url = day_to_offers_parquet_url(start_date)
        else:
            self.parquet_url = parquet_url

        self.backend = self.con if self.con is not None else ibis.duckdb.connect()

        setup_duckdb_pg_connection(con=self.backend)
        if str(self.parquet_url).startswith("s3://"):
            setup_duckdb_aws_connection(con=self.backend)
        set_duckdb_memory_limit(con=self.backend)

    def get_expression(self, backend=None):
        if not self.table:
            raise RuntimeError("Subclasses need to define 'table'.")
        raise NotImplementedError("Subclasses need to implement 'get_expression'.")

    def aggregate(self):
        if not self.table:
            raise RuntimeError("Subclasses need to define 'table'.")

        expr = self.get_expression(self.backend)
        self.backend.insert(self.table, expr, database="ethicaladsdb_primary")


class DomainAggregation(BaseAggregation):
    """Aggregate domain impressions by day."""

    table = "adserver_domainimpression"

    def get_expression(self, backend=None):
        backend = backend if backend is not None else self.backend
        pf = backend.read_parquet(self.parquet_url)
        filtered = pf.filter(
            (pf.date >= self.start_date)
            & (pf.date < self.end_date)
            & pf.domain.notnull()
        )
        return (
            filtered.group_by(
                date=filtered.date.truncate("D"),
                advertisement_id=filtered.advertisement_id,
                domain=filtered.domain,
            )
            .aggregate(
                decisions=filtered.domain.count(),
                offers=filtered.domain.count(where=filtered.advertisement_id.notnull()),
                views=filtered.domain.count(where=filtered.viewed),
                clicks=filtered.domain.count(where=filtered.clicked),
            )
            .filter(lambda t: t.views > 0)
            .mutate(created=ibis.now(), modified=ibis.now())
            .order_by([ibis.desc("decisions"), "domain", "advertisement_id"])
        )


class UpliftAggregation(BaseAggregation):
    """Aggregate uplift impressions by day."""

    table = "adserver_upliftimpression"

    def get_expression(self, backend=None):
        backend = backend if backend is not None else self.backend
        pf = backend.read_parquet(self.parquet_url)
        filtered = pf.filter((pf.date >= self.start_date) & (pf.date < self.end_date))
        return (
            filtered.group_by(
                date=filtered.date.truncate("D"),
                advertisement_id=filtered.advertisement_id,
                publisher_id=filtered.publisher_id,
            )
            .aggregate(
                decisions=filtered.uplifted.count(),
                offers=filtered.uplifted.count(
                    where=filtered.advertisement_id.notnull()
                ),
                views=filtered.uplifted.count(where=filtered.viewed),
                clicks=filtered.uplifted.count(where=filtered.clicked),
            )
            .filter(lambda t: t.decisions > 0)
            .mutate(created=ibis.now(), modified=ibis.now())
            .order_by([ibis.desc("decisions"), "publisher_id", "advertisement_id"])
        )


class RotationAggregation(BaseAggregation):
    """Aggregate rotated ad impressions by day."""

    table = "adserver_rotationimpression"

    def get_expression(self, backend=None):
        backend = backend if backend is not None else self.backend
        pf = backend.read_parquet(self.parquet_url)
        filtered = pf.filter(
            (pf.date >= self.start_date)
            & (pf.date < self.end_date)
            & (pf.rotations > 1)
        )
        return (
            filtered.group_by(
                date=filtered.date.truncate("D"),
                advertisement_id=filtered.advertisement_id,
                publisher_id=filtered.publisher_id,
            )
            .aggregate(
                decisions=filtered.publisher_id.count(),
                offers=filtered.publisher_id.count(
                    where=filtered.advertisement_id.notnull()
                ),
                views=filtered.publisher_id.count(where=filtered.viewed),
                clicks=filtered.publisher_id.count(where=filtered.clicked),
            )
            .filter(lambda t: t.decisions > 0)
            .mutate(created=ibis.now(), modified=ibis.now())
            .order_by([ibis.desc("decisions"), "publisher_id", "advertisement_id"])
        )


class GeoAggregation(BaseAggregation):
    """Aggregate country geo impressions by day."""

    table = "adserver_geoimpression"

    def get_expression(self, backend=None):
        backend = backend if backend is not None else self.backend
        pf = backend.read_parquet(self.parquet_url)
        pub = backend.table("adserver_publisher", database="ethicaladsdb")
        joined = pf.left_join(pub, pf.publisher_id == pub.id)
        filtered = joined.filter(
            (pf.date >= self.start_date)
            & (pf.date < self.end_date)
            & (pf.paid_eligible | ~pub.allow_paid_campaigns.cast("bool"))
        )
        return (
            filtered.group_by(
                date=pf.date.truncate("D"),
                advertisement_id=pf.advertisement_id,
                publisher_id=pf.publisher_id,
                country=pf.country,
            )
            .aggregate(
                decisions=pf.country.count(),
                offers=pf.country.count(where=pf.advertisement_id.notnull()),
                views=pf.country.count(where=pf.viewed),
                clicks=pf.country.count(where=pf.clicked),
            )
            .filter(lambda t: t.decisions > 0)
            .mutate(created=ibis.now(), modified=ibis.now())
            .order_by(
                [ibis.desc("decisions"), "advertisement_id", "publisher_id", "country"]
            )
        )


class RegionAggregation(BaseAggregation):
    """Aggregate region impressions by day."""

    table = "adserver_regionimpression"

    def get_expression(self, backend=None):
        backend = backend if backend is not None else self.backend
        pf = backend.read_parquet(self.parquet_url)
        pub = backend.table("adserver_publisher", database="ethicaladsdb")

        country_region = [
            {"country": cc, "region": Region.get_region_from_country_code(cc)}
            for cc, _ in countries
        ]
        cr = ibis.memtable(country_region)

        joined = pf.left_join(pub, pf.publisher_id == pub.id).inner_join(
            cr, cr.country == pf.country
        )
        filtered = joined.filter(
            (pf.date >= self.start_date)
            & (pf.date < self.end_date)
            & (pf.paid_eligible | ~pub.allow_paid_campaigns.cast("bool"))
        )
        return (
            filtered.group_by(
                date=pf.date.truncate("D"),
                advertisement_id=pf.advertisement_id,
                publisher_id=pf.publisher_id,
                region=cr.region,
            )
            .aggregate(
                decisions=cr.region.count(),
                offers=cr.region.count(where=pf.advertisement_id.notnull()),
                views=cr.region.count(where=pf.viewed),
                clicks=cr.region.count(where=pf.clicked),
            )
            .filter(lambda t: t.decisions > 0)
            .mutate(created=ibis.now(), modified=ibis.now())
            .order_by(
                [ibis.desc("decisions"), "advertisement_id", "publisher_id", "region"]
            )
        )
