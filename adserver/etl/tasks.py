"""Tasks for ETL."""

import datetime
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from config.celery_app import app

from ..utils import get_day
from .utils import dump_monthly_offers
from .utils import dump_offers
from .utils import monthly_offers_dump_exists
from .utils import offers_dump_exists


log = logging.getLogger(__name__)


@app.task
def daily_etl_pipeline(day=None):
    # Only run customer ETL jobs in production when ethicalads_ext.etl is available
    run_customer_jobs = (
        not settings.DEBUG and "ethicalads_ext.etl" in settings.INSTALLED_APPS
    )

    daily_offers_dump.delay(day, run_customer_jobs=run_customer_jobs)


@app.task(
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=True,
)
def daily_offers_dump(day=None, run_customer_jobs=False, force=False):
    manual_run = day is not None
    start_date, end_date = get_day(day)

    if not day:
        # If not specified, do the previous day now that the day is complete
        start_date -= datetime.timedelta(days=1)
        end_date -= datetime.timedelta(days=1)

    # Usually, you don't want to re-run the offers dump if it already exists.
    # This is expensive on the DB and unnecessary unless something has changed.
    # However, if there's an error in the dump, you may want to re-run it (with `force=True`)
    if offers_dump_exists(start_date) and not force:
        log.info("Skipping offers dump for %s since it already exists.", day)
        return

    log.info("Creating offers parquet dump...")
    dump_offers(start_date, end_date)

    if run_customer_jobs and "ethicalads_ext.etl" in settings.INSTALLED_APPS:
        from ethicalads_ext.etl.tasks import daily_customer_etl

        daily_customer_etl.delay(day)

    if not manual_run:
        # Update cache with last successful run timestamp - used in health checks
        # Only do this for the nightly task,
        # not for manual runs of the task with a specific day.
        cache.set(
            "health.daily_offers_dump",
            timezone.now().isoformat(),
            timeout=None,  # Never expire
        )


@app.task(
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=True,
)
def monthly_offers_dump(day=None, force=False):
    manual_run = day is not None
    if not day:
        today = datetime.date.today()
        first_of_month = today.replace(day=1)
        day = first_of_month - datetime.timedelta(days=1)
    elif isinstance(day, str):
        day = datetime.datetime.strptime(day, "%Y-%m-%d").date()
    elif isinstance(day, datetime.datetime):
        day = day.date()

    if monthly_offers_dump_exists(day) and not force:
        log.info(
            "Skipping monthly offers parquet dump for %s since it already exists.",
            day.strftime("%Y-%m"),
        )
        return

    log.info("Creating monthly offers parquet dump for %s...", day.strftime("%Y-%m"))
    offers_parquet_url = dump_monthly_offers(day)
    if not offers_parquet_url:
        log.warning(
            "Skipping monthly offers parquet dump notification for %s as no parquet was generated.",
            day.strftime("%Y-%m"),
        )
        return

    if not manual_run:
        # Update cache with last successful run timestamp - used in health checks
        # Only do this for the monthly task,
        # not for manual runs of the task with a specific month.
        cache.set(
            "health.monthly_offers_dump",
            timezone.now().isoformat(),
            timeout=None,  # Never expire
        )
