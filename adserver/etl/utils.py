"""Utilities for ETL."""

import glob
import logging
import os

import duckdb
import ibis
from django.conf import settings


log = logging.getLogger(__name__)

QUERYDUMP_OFFERS_PREFIX = "querydumps/offers/"
MONTHLY_QUERYDUMP_OFFERS_PREFIX = "querydumps/monthly-offers/"
DATA_BUCKET_NAME = getattr(settings, "AWS_DATA_STORAGE_BUCKET_NAME", None)


def _get_duckdb_con(con=None):
    """Return raw duckdb connection from an Ibis backend, duckdb connection, or default module."""
    if con is None:
        return duckdb
    if isinstance(con, ibis.backends.duckdb.Backend):
        return con.con
    return con


def set_duckdb_memory_limit(limit_mb=3000, con=None):
    """Set duckdb memory limit in MB."""
    limit_mb = int(limit_mb)  # Enforce int to prevent SQL injection
    target = _get_duckdb_con(con)
    target.sql(f"SET memory_limit = '{limit_mb}MB';")


def setup_duckdb_pg_connection(con=None):
    """
    Setup connection to database (PostgreSQL or SQLite fallback) as ethicaladsdb.

    Should be a noop on 2nd execution.
    """
    target = _get_duckdb_con(con)

    # Try replica DB first, fallback to primary DATABASE_URL or settings.DATABASES
    db_url = os.getenv("REPLICA_DATABASE_URL", default=os.getenv("DATABASE_URL"))
    primary_db_url = os.getenv("DATABASE_URL")

    if not db_url and hasattr(settings, "DATABASES"):
        db_conf = settings.DATABASES.get(
            "replica", settings.DATABASES.get("default", {})
        )
        engine = db_conf.get("ENGINE", "")
        if "sqlite" in engine:
            db_path = db_conf.get("NAME")
            if db_path and os.path.exists(db_path):
                db_url = f"sqlite:///{db_path}"
                primary_db_url = db_url

    if db_url:
        if db_url.startswith(("postgresql://", "postgres://", "psql://")):
            target.sql("INSTALL postgres;")
            target.sql("LOAD postgres;")
            pg_conn_string = db_url.replace("psql://", "postgresql://")
            target.sql(
                f"ATTACH IF NOT EXISTS '{pg_conn_string}' AS ethicaladsdb (TYPE POSTGRES);"
            )
        elif db_url.startswith("sqlite:///"):
            target.sql("INSTALL sqlite;")
            target.sql("LOAD sqlite;")
            sqlite_path = db_url.replace("sqlite:///", "")
            target.sql(
                f"ATTACH IF NOT EXISTS '{sqlite_path}' AS ethicaladsdb (TYPE SQLITE);"
            )

    if primary_db_url:
        if primary_db_url.startswith(("postgresql://", "postgres://", "psql://")):
            target.sql("INSTALL postgres;")
            target.sql("LOAD postgres;")
            pg_conn_string = primary_db_url.replace("psql://", "postgresql://")
            target.sql(
                f"ATTACH IF NOT EXISTS '{pg_conn_string}' AS ethicaladsdb_primary (TYPE POSTGRES);"
            )
        elif primary_db_url.startswith("sqlite:///"):
            target.sql("INSTALL sqlite;")
            target.sql("LOAD sqlite;")
            sqlite_path = primary_db_url.replace("sqlite:///", "")
            target.sql(
                f"ATTACH IF NOT EXISTS '{sqlite_path}' AS ethicaladsdb_primary (TYPE SQLITE);"
            )


def setup_duckdb_aws_connection(con=None):
    """Setup duckdb connection to AWS (S3). Should be a noop on 2nd execution."""
    target = _get_duckdb_con(con)

    target.sql("INSTALL httpfs;")
    target.sql("LOAD httpfs;")
    target.sql("INSTALL aws;")
    target.sql("LOAD aws;")

    bucket_name = getattr(settings, "AWS_DATA_STORAGE_BUCKET_NAME", DATA_BUCKET_NAME)
    if not bucket_name:
        raise RuntimeError("AWS_DATA_STORAGE_BUCKET_NAME not found in settings")

    secret_query = f"""
        CREATE OR REPLACE SECRET s3_ethicalads_data (
            TYPE S3,
            PROVIDER credential_chain,
            SCOPE 's3://{bucket_name}'
        );
    """
    target.sql(secret_query)


def dump_offers(start_date, end_date, parquet_path=None, con=None) -> str:
    """
    Dumps offers [start_date, end_date) to `parquet_path` in parquet format using Ibis.

    For a weekday's worth of offers (~5M records), this takes between 5-45 minutes
    and the file will be ~250MB.

    The file can be read with:
    con.read_parquet('s3://.../2026-03-25.parquet')
    """
    if parquet_path is None:
        parquet_path = day_to_offers_parquet_url(start_date)

    backend = con if con is not None else ibis.duckdb.connect()

    if str(parquet_path).startswith("s3://"):
        setup_duckdb_aws_connection(con=backend)
    else:
        os.makedirs(os.path.dirname(str(parquet_path)), exist_ok=True)

    setup_duckdb_pg_connection(con=backend)

    # Set a smaller memory limit -- otherwise the default is 80% of total RAM
    set_duckdb_memory_limit(con=backend)

    offer_table = getattr(settings, "ADSERVER_OFFER_DB_TABLE", None) or "adserver_offer"

    offers = backend.table(offer_table, database="ethicaladsdb")
    advertisement = backend.table(
        "adserver_advertisement", database="ethicaladsdb"
    ).select(ad_id="id", flight_id="flight_id")
    flight = backend.table("adserver_flight", database="ethicaladsdb").select(
        flight_id="id", campaign_id="campaign_id", flight_cpc="cpc", flight_cpm="cpm"
    )
    campaign = backend.table("adserver_campaign", database="ethicaladsdb").select(
        campaign_id="id", advertiser_id="advertiser_id"
    )
    advertiser = backend.table("adserver_advertiser", database="ethicaladsdb").select(
        advertiser_id="id"
    )

    joined = (
        offers.left_join(advertisement, offers.advertisement_id == advertisement.ad_id)
        .left_join(flight, advertisement.flight_id == flight.flight_id)
        .left_join(campaign, flight.campaign_id == campaign.campaign_id)
        .left_join(advertiser, campaign.advertiser_id == advertiser.advertiser_id)
    )

    filtered = joined.filter(
        (offers.date >= start_date) & (offers.date < end_date)
    ).select(
        id=offers.id,
        date=offers.date,
        advertisement_id=offers.advertisement_id,
        advertiser_id=advertiser.advertiser_id,
        flight_id=flight.flight_id,
        flight_cpc=flight.flight_cpc,
        flight_cpm=flight.flight_cpm,
        publisher_id=offers.publisher_id,
        country=offers.country,
        url=offers.url,
        domain=offers.domain,
        viewed=offers.viewed,
        clicked=offers.clicked,
        paid_eligible=offers.paid_eligible,
        uplifted=offers.uplifted,
        view_time=offers.view_time,
        rotations=offers.rotations,
        keywords=offers.keywords,
        div_id=offers.div_id,
        ad_type_slug=offers.ad_type_slug,
    )

    backend.to_parquet(filtered, str(parquet_path))

    return str(parquet_path)


def get_offers_base_path():
    """
    Get the base path or S3 URL prefix for parquet offer dumps.

    In production (DEBUG=False and TESTING=False): requires AWS_DATA_STORAGE_BUCKET_NAME and returns 's3://<bucket_name>'.
    In development/testing: returns 's3://<bucket_name>' if configured, or settings.ADSERVER_OFFERS_LOCAL_PATH (defaults to settings.MEDIA_ROOT).
    """
    bucket_name = getattr(settings, "AWS_DATA_STORAGE_BUCKET_NAME", DATA_BUCKET_NAME)
    if bucket_name:
        return f"s3://{bucket_name}"

    is_production = not getattr(settings, "DEBUG", True) and not getattr(
        settings, "TESTING", False
    )
    if is_production:
        raise RuntimeError("AWS_DATA_STORAGE_BUCKET_NAME is required in production")

    local_path = getattr(settings, "ADSERVER_OFFERS_LOCAL_PATH", None)
    if local_path:
        return local_path

    if getattr(settings, "MEDIA_ROOT", None):
        return settings.MEDIA_ROOT

    raise RuntimeError(
        "Neither AWS_DATA_STORAGE_BUCKET_NAME nor ADSERVER_OFFERS_LOCAL_PATH configured"
    )


def day_to_offers_parquet_url(day):
    """
    Convert a day (date or datetime object) to the expected parquet path for that day's offer dumps.
    """
    base = get_offers_base_path()
    filename = f"{day:%Y-%m-%d}.parquet"
    if str(base).startswith("s3://"):
        return f"{base}/{QUERYDUMP_OFFERS_PREFIX}{filename}"
    return os.path.join(base, "querydumps", "offers", filename)


def month_to_offers_parquet_url(month_date):
    """
    Convert a month (date or datetime object) to the expected parquet path for that month's consolidated offer dumps.
    """
    base = get_offers_base_path()
    year_month = f"{month_date.year}-{month_date.month:02d}"
    filename = f"{year_month}.parquet"
    if str(base).startswith("s3://"):
        return f"{base}/{MONTHLY_QUERYDUMP_OFFERS_PREFIX}{filename}"
    return os.path.join(base, "querydumps", "monthly-offers", filename)


def month_to_daily_offers_parquet_glob(month_date):
    """
    Convert a month (date or datetime object) to the expected parquet glob for that month's daily offer dumps.
    """
    base = get_offers_base_path()
    year_month = f"{month_date.year}-{month_date.month:02d}"
    if str(base).startswith("s3://"):
        return f"{base}/{QUERYDUMP_OFFERS_PREFIX}{year_month}-*.parquet"
    return os.path.join(base, "querydumps", "offers", f"{year_month}-*.parquet")


def offers_dump_exists(day, parquet_path=None, con=None):
    """
    Check if the offers parquet dump exists for a specific day.
    """
    if parquet_path is not None:
        target_path = parquet_path
    else:
        try:
            target_path = day_to_offers_parquet_url(day)
        except RuntimeError:
            return False

    if str(target_path).startswith("s3://"):
        backend = con if con is not None else ibis.duckdb.connect()
        try:
            setup_duckdb_aws_connection(con=backend)
            table = backend.read_parquet(str(target_path))
            table.limit(1).execute()
            return True
        except Exception:
            log.exception("Error checking for offers dump at %s", target_path)
            return False

    return os.path.exists(str(target_path))


def dump_monthly_offers(month_date, parquet_path=None, con=None) -> str:
    """
    Combines daily offers parquets for the given month into a single monthly parquet on S3 or local storage using Ibis.
    month_date should be a date or datetime object within the target month.

    A normal month's worth of offers is ~7GB as of June 2026.
    """
    if parquet_path is None:
        parquet_path = month_to_offers_parquet_url(month_date)

    backend = con if con is not None else ibis.duckdb.connect()

    input_glob = month_to_daily_offers_parquet_glob(month_date)
    if str(parquet_path).startswith("s3://"):
        setup_duckdb_aws_connection(con=backend)
    else:
        if not glob.glob(input_glob):
            log.warning(
                "No daily offers parquet files found for %s (%s)",
                month_date,
                input_glob,
            )
            return None
        os.makedirs(os.path.dirname(str(parquet_path)), exist_ok=True)

    set_duckdb_memory_limit(con=backend)

    daily_offers = backend.read_parquet(input_glob)
    backend.to_parquet(daily_offers, str(parquet_path))

    return str(parquet_path)


def monthly_offers_dump_exists(month_date, parquet_path=None, con=None):
    """
    Check if the monthly offers parquet dump exists for a specific month.
    """
    if parquet_path is not None:
        target_path = parquet_path
    else:
        try:
            target_path = month_to_offers_parquet_url(month_date)
        except RuntimeError:
            return False

    if str(target_path).startswith("s3://"):
        backend = con if con is not None else ibis.duckdb.connect()
        try:
            setup_duckdb_aws_connection(con=backend)
            table = backend.read_parquet(str(target_path))
            table.limit(1).execute()
            return True
        except Exception:
            return False

    return os.path.exists(str(target_path))
