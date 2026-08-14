"""Nightly DuckDB aggregations using offers parquet files."""

import duckdb
from django_countries import countries

from ..models import Region
from .utils import day_to_offers_parquet_url
from .utils import setup_duckdb_aws_connection
from .utils import setup_duckdb_pg_connection


class BaseAggregation:
    """Base class for DuckDB aggregations."""

    table = None
    query = None

    def __init__(self, start_date, end_date, parquet_url=None):
        self.start_date = start_date
        self.end_date = end_date

        # This parquet URL should not come from an untrusted source
        # It is injected directly into the SQL query
        if not parquet_url:
            self.parquet_url = day_to_offers_parquet_url(start_date)
        else:
            self.parquet_url = parquet_url

        setup_duckdb_pg_connection()
        if str(self.parquet_url).startswith("s3://"):
            setup_duckdb_aws_connection()

    def get_select_query(self):
        if not self.table or not self.query:
            raise RuntimeError("Subclasses need to define 'query' and 'table'.")

        return self.query.format(parquet_url=self.parquet_url)

    def get_insert_query(self):
        if not self.table or not self.query:
            raise RuntimeError("Subclasses need to define 'query' and 'table'.")

        select_query = self.get_select_query()

        # Must insert into the primary
        # Inserting "BY NAME" means that the columns in the select statement
        # Must match the columns in the database table.
        # https://duckdb.org/docs/stable/sql/statements/insert.html#insert-into--by-name
        insert_query = f"""
            INSERT INTO ethicaladsdb_primary.{self.table} BY NAME (
                {select_query}
            )
        """
        return insert_query

    def aggregate(self):
        duckdb.execute(self.get_insert_query(), [self.start_date, self.end_date])


class DomainAggregation(BaseAggregation):
    """Aggregate domain impressions by day."""

    table = "adserver_domainimpression"
    query = """
        SELECT
            DATE_TRUNC('day', "date") AS "date",
            advertisement_id,
            "domain",
            COUNT("domain") AS "decisions",
            COUNT("domain") FILTER (WHERE advertisement_id IS NOT NULL) AS "offers",
            COUNT("domain") FILTER (WHERE viewed) AS "views",
            COUNT("domain") FILTER (WHERE clicked) AS "clicks",
            NOW() AS "created",
            NOW() AS "modified"
        FROM read_parquet('{parquet_url}')
        WHERE
            date >= ?
            AND date < ?
            AND "domain" IS NOT NULL
        GROUP BY
            DATE_TRUNC('day', "date"),
            advertisement_id,
            "domain"
        HAVING COUNT("domain") FILTER (WHERE (viewed)) > 0
        ORDER BY
            decisions DESC,
            "domain",
            advertisement_id
    """


class UpliftAggregation(BaseAggregation):
    """Aggregate uplift impressions by day."""

    table = "adserver_upliftimpression"
    query = """
        SELECT
            DATE_TRUNC('day', "date") AS "date",
            advertisement_id,
            publisher_id,
            COUNT("uplifted") AS "decisions",
            COUNT("uplifted") FILTER (WHERE advertisement_id IS NOT NULL) AS "offers",
            COUNT("uplifted") FILTER (WHERE viewed) AS "views",
            COUNT("uplifted") FILTER (WHERE clicked) AS "clicks",
            NOW() AS "created",
            NOW() AS "modified"
        FROM read_parquet('{parquet_url}')
        WHERE
            date >= ?
            AND date < ?
        GROUP BY
            DATE_TRUNC('day', "date"),
            advertisement_id,
            publisher_id
        HAVING COUNT("uplifted") > 0
        ORDER BY
            decisions DESC,
            publisher_id,
            advertisement_id
    """


class RotationAggregation(BaseAggregation):
    """Aggregate rotated ad impressions by day."""

    table = "adserver_rotationimpression"
    query = """
        SELECT
            DATE_TRUNC('day', "date") AS "date",
            advertisement_id,
            publisher_id,
            COUNT("publisher_id") AS "decisions",
            COUNT("publisher_id") FILTER (WHERE advertisement_id IS NOT NULL) AS "offers",
            COUNT("publisher_id") FILTER (WHERE viewed) AS "views",
            COUNT("publisher_id") FILTER (WHERE clicked) AS "clicks",
            NOW() AS "created",
            NOW() AS "modified"
        FROM read_parquet('{parquet_url}')
        WHERE
            date >= ?
            AND date < ?
            AND rotations > 1
        GROUP BY
            DATE_TRUNC('day', "date"),
            advertisement_id,
            publisher_id
        HAVING COUNT("publisher_id") > 0
        ORDER BY
            decisions DESC,
            publisher_id,
            advertisement_id
    """


class GeoAggregation(BaseAggregation):
    """Aggregate country geo impressions by day."""

    table = "adserver_geoimpression"

    # This joins the offer dump back against the publisher table
    # It is a little slower but still returned aggregated results within a few seconds
    query = """
        SELECT
            DATE_TRUNC('day', "date") AS "date",
            advertisement_id,
            publisher_id,
            country,
            COUNT("country") AS "decisions",
            COUNT("country") FILTER (WHERE advertisement_id IS NOT NULL) AS "offers",
            COUNT("country") FILTER (WHERE viewed) AS "views",
            COUNT("country") FILTER (WHERE clicked) AS "clicks",
            NOW() AS "created",
            NOW() AS "modified"
        FROM read_parquet('{parquet_url}') pf
        LEFT JOIN ethicaladsdb."adserver_publisher" pub ON (
            pf."publisher_id" = pub."id"
        )
        WHERE
            date >= ?
            AND date < ?
            AND (pf.paid_eligible OR NOT pub.allow_paid_campaigns)
        GROUP BY
            DATE_TRUNC('day', "date"),
            advertisement_id,
            publisher_id,
            country
        HAVING COUNT("country") > 0
        ORDER BY
            decisions DESC,
            advertisement_id,
            publisher_id,
            country
    """


class RegionAggregation(BaseAggregation):
    """Aggregate region impressions by day."""

    table = "adserver_regionimpression"

    query = """
        SELECT
            DATE_TRUNC('day', "date") AS "date",
            advertisement_id,
            publisher_id,
            region,
            COUNT(region) AS "decisions",
            COUNT(region) FILTER (WHERE advertisement_id IS NOT NULL) AS "offers",
            COUNT(region) FILTER (WHERE viewed) AS "views",
            COUNT(region) FILTER (WHERE clicked) AS "clicks",
            NOW() AS "created",
            NOW() AS "modified"
        FROM read_parquet('{parquet_url}') pf
        LEFT JOIN ethicaladsdb."adserver_publisher" pub ON (
            pf."publisher_id" = pub."id"
        )
        INNER JOIN tt_country_region cr ON cr.country = pf.country
        WHERE
            date >= ?
            AND date < ?
            AND (pf.paid_eligible OR NOT pub.allow_paid_campaigns)
        GROUP BY
            DATE_TRUNC('day', "date"),
            advertisement_id,
            publisher_id,
            region
        HAVING COUNT(region) > 0
        ORDER BY
            decisions DESC,
            advertisement_id,
            publisher_id,
            region
    """

    def __init__(self, start_date, end_date, parquet_url=None):
        super().__init__(start_date, end_date, parquet_url=parquet_url)

        # Build a country_region dictionary and insert it into in-memory DuckDB temp table
        country_region = []
        for cc, _ in countries:
            country_region.append((cc, Region.get_region_from_country_code(cc)))

        duckdb.sql("DROP TABLE IF EXISTS tt_country_region;")
        duckdb.sql(
            "CREATE TEMPORARY TABLE tt_country_region (country VARCHAR(10), region VARCHAR(100));"
        )
        duckdb.executemany(
            "INSERT INTO tt_country_region VALUES (?, ?);", country_region
        )
