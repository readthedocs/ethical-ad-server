"""Tasks for ETL."""

import datetime
import logging

from django.conf import settings
from django_slack import slack_message

from config.celery_app import app

from ..utils import get_day
from .utils import dump_monthly_offers
from .utils import dump_offers
from .utils import monthly_offers_dump_exists
from .utils import offers_dump_exists


log = logging.getLogger(__name__)


@app.task
def daily_etl_pipeline(day=None):
    start_date, _ = get_day(day)

    if not day:
        # If not specified, do the previous day now that the day is complete
        start_date -= datetime.timedelta(days=1)

    # Only run customer ETL jobs in production when ethicalads_ext.etl is available
    run_customer_jobs = (
        not settings.DEBUG and "ethicalads_ext.etl" in settings.INSTALLED_APPS
    )

    daily_offers_dump.delay(start_date, run_customer_jobs=run_customer_jobs)


@app.task(
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=True,
)
def daily_offers_dump(day=None, run_customer_jobs=False, force=False):
    start_date, end_date = get_day(day)

    # Usually, you don't want to re-run the offers dump if it already exists.
    # This is expensive on the DB and unnecessary unless something has changed.
    # However, if there's an error in the dump, you may want to re-run it (with `force=True`)
    if offers_dump_exists(start_date) and not force:
        log.info("Skipping offers dump for %s since it already exists.", day)
        return

    log.info("Creating offers parquet dump...")
    offers_parquet_url = dump_offers(start_date, end_date)

    # Send notification to Slack about parquet dump
    slack_message(
        "adserver/slack/generic-message.slack",
        {
            "text": f"Completed offers dump for {start_date:%Y-%m-%d}: {offers_parquet_url}. :parking:"
        },
    )

    if run_customer_jobs and "ethicalads_ext.etl" in settings.INSTALLED_APPS:
        from ethicalads_ext.etl.tasks import daily_customer_etl

        daily_customer_etl.delay(day)


@app.task(
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=True,
)
def monthly_offers_dump(day=None, force=False):
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

    # Send notification to Slack about parquet dump
    slack_message(
        "adserver/slack/generic-message.slack",
        {
            "text": f"Completed monthly offers parquet dump for {day.strftime('%Y-%m')}: {offers_parquet_url}. :calendar:"
        },
    )
