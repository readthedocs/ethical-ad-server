"""Views for ETL and audience estimation."""

import functools
import json
import logging
import operator
from datetime import timedelta

import duckdb
import ibis
from django.utils import timezone
from django.views.generic import FormView

from ..mixins import StaffUserMixin
from ..models import Topic
from ..utils import COUNTRY_DICT
from .forms import AudienceEstimatorForm
from .utils import month_to_daily_offers_parquet_glob
from .utils import month_to_offers_parquet_url
from .utils import monthly_offers_dump_exists
from .utils import setup_duckdb_aws_connection


log = logging.getLogger(__name__)


# DuckDB Built-in Scalar UDF Declarations
# ---------------------------------------------------------------------------
# The functions below expose native DuckDB SQL functions to Ibis expressions.
# They are not executed in Python (hence the ellipsis body `...`); rather, they
# declare the SQL function name, input types, and return type so Ibis can compile
# them into DuckDB SQL queries when executing audience estimation against Parquet files.


@ibis.udf.scalar.builtin
def from_json(json_str: str, schema: str) -> list[str]:
    """
    Exposes DuckDB's native ``from_json`` function to Ibis.

    In the offers Parquet files, keywords are stored as a JSON-encoded string
    (e.g., '["python", "django"]'). This function parses that JSON string column
    into a typed DuckDB array of strings in SQL so downstream array operations
    (like ``list_intersect``) can be evaluated directly in the query engine.
    """
    ...


@ibis.udf.scalar.builtin
def list_intersect(l1: list[str], l2: list[str]) -> list[str]:
    """
    Exposes DuckDB's native ``list_intersect`` function to Ibis.

    Used by the audience estimator for topic matching. Each Topic expands into
    a list of keywords; this function computes the array intersection between
    an offer's parsed keywords and the topic's keyword set in DuckDB. If the
    intersection length is greater than 0, the offer matches the topic.
    """
    ...


@ibis.udf.scalar.builtin
def json_contains(json_doc: str, val: str) -> bool:
    """
    Exposes DuckDB's native ``json_contains`` function to Ibis.

    Used by the audience estimator for keyword matching. Directly tests
    whether the raw JSON keyword string contains a specific serialized keyword
    value in DuckDB SQL.
    """
    ...


class AudienceEstimatorView(StaffUserMixin, FormView):
    """Audience estimation view for staff."""

    form_class = AudienceEstimatorForm
    template_name = "etl/audience-estimator.html"

    def form_valid(self, form):
        """Rather than redirect, just perform and display the estimate."""
        ctx = self.get_context_data()

        countries = form.cleaned_data["countries"]
        topics = form.cleaned_data["topics"]
        keywords = form.cleaned_data["keywords"]
        domains = form.cleaned_data["domains"]

        ctx["estimate"] = True
        ctx["estimated_views"] = self.get_estimate(countries, topics, keywords, domains)

        ctx["countries"] = [COUNTRY_DICT[c] for c in countries]
        ctx["topics"] = topics
        ctx["keywords"] = keywords
        ctx["domains"] = domains

        return self.render_to_response(ctx)

    def get_parquet_path(self, parquet_path=None, con=None):
        """
        Get the parquet path or glob to use for the estimate.

        Prefers the previous month's consolidated monthly parquet file.
        Falls back to daily parquet files for the month.
        """
        if parquet_path:
            return parquet_path

        today = (
            timezone.now().date() if hasattr(timezone.now(), "date") else timezone.now()
        )
        first_of_month = today.replace(day=1)
        prev_month = first_of_month - timedelta(days=1)

        if monthly_offers_dump_exists(prev_month, con=con):
            return month_to_offers_parquet_url(prev_month)

        return month_to_daily_offers_parquet_glob(prev_month)

    def get_estimate(self, countries, topics, keywords, domains, parquet_path=None):
        """Get an audience traffic estimate for the previous month."""
        con = ibis.duckdb.connect()
        try:
            target_path = self.get_parquet_path(parquet_path=parquet_path, con=con)
        except RuntimeError as e:
            log.warning(
                "Could not determine parquet path for audience estimation: %s", e
            )
            return 0

        if not target_path:
            return 0

        if str(target_path).startswith("s3://"):
            setup_duckdb_aws_connection(con.con)

        try:
            t = con.read_parquet(target_path)
        except (duckdb.IOException, duckdb.Error, FileNotFoundError) as e:
            log.warning("Failed to read parquet for audience estimation: %s", e)
            return 0

        query = t.filter(t.paid_eligible == True, t.viewed == True)  # noqa: E712

        if countries:
            query = query.filter(query.country.isin(countries))

        if domains:
            query = query.filter(query.domain.isin(domains))

        if topics:
            kw_parsed = from_json(query.keywords, '["VARCHAR"]')
            topic_conds = []
            for tp in topics:
                topic = Topic.objects.filter(slug=tp).first()
                if topic:
                    keyword_set = [kw.slug for kw in topic.keywords.all()]
                    if keyword_set:
                        topic_kws = ibis.literal(keyword_set, type=list[str])
                        topic_conds.append(
                            list_intersect(kw_parsed, topic_kws).length() > 0
                        )
            if topic_conds:
                query = query.filter(
                    query.keywords.notnull()
                    & functools.reduce(operator.or_, topic_conds)
                )

        if keywords:
            kw_conds = [
                json_contains(query.keywords, json.dumps(kw)) for kw in keywords
            ]
            if kw_conds:
                query = query.filter(functools.reduce(operator.or_, kw_conds))

        try:
            estimated_views = int(query.count().execute())
        except (duckdb.IOException, duckdb.Error) as e:
            log.warning("Failed to execute audience estimation query: %s", e)
            return 0

        return estimated_views
