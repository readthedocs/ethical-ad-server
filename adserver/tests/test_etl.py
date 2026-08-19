"""Tests for ETL app, parquet dumps, DuckDB aggregations, and audience estimator."""

import datetime
import json
import os
import sqlite3
import tempfile
from datetime import timedelta
from unittest import mock

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from adserver.etl.aggregations import BaseAggregation
from adserver.etl.aggregations import DomainAggregation
from adserver.etl.aggregations import GeoAggregation
from adserver.etl.aggregations import RegionAggregation
from adserver.etl.aggregations import RotationAggregation
from adserver.etl.aggregations import UpliftAggregation
from adserver.etl.forms import AudienceEstimatorForm
from adserver.etl.tasks import daily_etl_pipeline
from adserver.etl.tasks import daily_offers_dump
from adserver.etl.tasks import monthly_offers_dump
from adserver.etl.utils import day_to_offers_parquet_url
from adserver.etl.utils import dump_monthly_offers
from adserver.etl.utils import dump_offers
from adserver.etl.utils import get_offers_base_path
from adserver.etl.utils import month_to_daily_offers_parquet_glob
from adserver.etl.utils import month_to_offers_parquet_url
from adserver.etl.utils import monthly_offers_dump_exists
from adserver.etl.utils import offers_dump_exists
from adserver.etl.utils import set_duckdb_memory_limit
from adserver.etl.utils import setup_duckdb_aws_connection
from adserver.etl.utils import setup_duckdb_pg_connection
from adserver.etl.views import AudienceEstimatorView
from adserver.etl.views import from_json
from adserver.etl.views import json_contains
from adserver.etl.views import list_intersect
from adserver.models import Keyword
from adserver.models import Topic
from adserver.tasks import daily_update_domains
from adserver.tasks import daily_update_geos
from adserver.tasks import daily_update_rotations
from adserver.tasks import daily_update_uplift
from adserver.utils import get_day

from .common import BaseAdModelsTestCase


User = get_user_model()


def write_test_offers_parquet(file_path, offers_data=None):
    """Helper to write sample offers parquet data for testing."""
    if offers_data is None:
        offers_data = [
            {
                "id": "01900000-0000-7000-0000-000000000001",
                "date": "2025-05-13 10:00:00",
                "advertisement_id": 1,
                "advertiser_id": 1,
                "flight_id": 1,
                "flight_cpc": 0.5,
                "flight_cpm": 100,
                "publisher_id": 1,
                "country": "US",
                "url": "https://docs.readthedocs.io/en/latest/",
                "domain": "docs.readthedocs.io",
                "viewed": True,
                "clicked": True,
                "paid_eligible": True,
                "uplifted": True,
                "view_time": 15,
                "rotations": 1,
                "keywords": json.dumps(["docs", "python", "sphinx"]),
                "div_id": "ethical-ads",
                "ad_type_slug": "image-v1",
            },
            {
                "id": "01900000-0000-7000-0000-000000000002",
                "date": "2025-05-13 11:00:00",
                "advertisement_id": 1,
                "advertiser_id": 1,
                "flight_id": 1,
                "flight_cpc": 0.5,
                "flight_cpm": 100,
                "publisher_id": 1,
                "country": "US",
                "url": "https://docs.readthedocs.io/en/latest/django/",
                "domain": "docs.readthedocs.io",
                "viewed": True,
                "clicked": False,
                "paid_eligible": True,
                "uplifted": False,
                "view_time": 10,
                "rotations": 2,
                "keywords": json.dumps(["documentation", "django", "python"]),
                "div_id": "ethical-ads",
                "ad_type_slug": "image-v1",
            },
            {
                "id": "01900000-0000-7000-0000-000000000003",
                "date": "2025-05-13 12:00:00",
                "advertisement_id": 2,
                "advertiser_id": 1,
                "flight_id": 1,
                "flight_cpc": 0.5,
                "flight_cpm": 100,
                "publisher_id": 1,
                "country": "DE",
                "url": "https://docs.readthedocs.io/en/latest/guide/",
                "domain": "docs.readthedocs.io",
                "viewed": True,
                "clicked": True,
                "paid_eligible": True,
                "uplifted": None,
                "view_time": 20,
                "rotations": 2,
                "keywords": json.dumps(["frontend", "javascript"]),
                "div_id": "ethical-ads",
                "ad_type_slug": "text-v1",
            },
            {
                "id": "01900000-0000-7000-0000-000000000004",
                "date": "2025-05-13 13:00:00",
                "advertisement_id": 2,
                "advertiser_id": 1,
                "flight_id": 1,
                "flight_cpc": 0.5,
                "flight_cpm": 100,
                "publisher_id": 1,
                "country": "CA",
                "url": "https://docs.readthedocs.io/en/latest/faq/",
                "domain": "docs.readthedocs.io",
                "viewed": False,
                "clicked": False,
                "paid_eligible": True,
                "uplifted": None,
                "view_time": None,
                "rotations": 1,
                "keywords": json.dumps(["python", "docs"]),
                "div_id": "ethical-ads",
                "ad_type_slug": "text-v1",
            },
            {
                "id": "01900000-0000-7000-0000-000000000005",
                "date": "2025-05-13 14:00:00",
                "advertisement_id": 1,
                "advertiser_id": 1,
                "flight_id": 1,
                "flight_cpc": 0.5,
                "flight_cpm": 100,
                "publisher_id": 2,
                "country": "GB",
                "url": "https://example.com/blog/",
                "domain": "example.com",
                "viewed": True,
                "clicked": False,
                "paid_eligible": False,
                "uplifted": None,
                "view_time": 5,
                "rotations": 1,
                "keywords": json.dumps(["news"]),
                "div_id": "ethical-ads",
                "ad_type_slug": "image-v1",
            },
        ]

    cols = {
        "id": [r["id"] for r in offers_data],
        "date": [datetime.datetime.fromisoformat(r["date"]) for r in offers_data],
        "advertisement_id": [r["advertisement_id"] for r in offers_data],
        "advertiser_id": [r["advertiser_id"] for r in offers_data],
        "flight_id": [r["flight_id"] for r in offers_data],
        "flight_cpc": [r["flight_cpc"] for r in offers_data],
        "flight_cpm": [r["flight_cpm"] for r in offers_data],
        "publisher_id": [r["publisher_id"] for r in offers_data],
        "country": [r["country"] for r in offers_data],
        "url": [r["url"] for r in offers_data],
        "domain": [r["domain"] for r in offers_data],
        "viewed": [r["viewed"] for r in offers_data],
        "clicked": [r["clicked"] for r in offers_data],
        "paid_eligible": [r["paid_eligible"] for r in offers_data],
        "uplifted": [r["uplifted"] for r in offers_data],
        "view_time": [r["view_time"] for r in offers_data],
        "rotations": [r["rotations"] for r in offers_data],
        "keywords": [r["keywords"] for r in offers_data],
        "div_id": [r["div_id"] for r in offers_data],
        "ad_type_slug": [r["ad_type_slug"] for r in offers_data],
    }
    table = pa.Table.from_pydict(cols)
    pq.write_table(table, str(file_path))


class TestOffersParquetUtils(TestCase):
    """Test parquet dump and existence utils."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.day = datetime.date(2025, 5, 13)
        self.start_date, self.end_date = get_day(self.day)
        self.parquet_path = os.path.join(self.temp_dir.name, "2025-05-13.parquet")
        write_test_offers_parquet(self.parquet_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_set_duckdb_memory_limit(self):
        set_duckdb_memory_limit(1024)
        con = duckdb.connect()
        set_duckdb_memory_limit(512, con=con)

    def test_setup_duckdb_pg_connection(self):
        mock_con = mock.MagicMock()
        with mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb",
                "REPLICA_DATABASE_URL": "postgresql://user:pass@replica:5432/testdb",
            },
        ):
            setup_duckdb_pg_connection(con=mock_con)
            self.assertTrue(mock_con.sql.called)

        mock_con.reset_mock()
        with mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": "sqlite:///tmp/test.db",
                "REPLICA_DATABASE_URL": "sqlite:///tmp/test.db",
            },
        ):
            setup_duckdb_pg_connection(con=mock_con)
            self.assertTrue(mock_con.sql.called)

        # Test with no env vars (uses settings.DATABASES)
        mock_con.reset_mock()
        with mock.patch.dict(os.environ, {}, clear=True):
            setup_duckdb_pg_connection(con=mock_con)

    def test_setup_duckdb_aws_connection(self):
        mock_con = mock.MagicMock()
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="mybucket"):
            setup_duckdb_aws_connection(con=mock_con)
            self.assertTrue(mock_con.sql.called)

        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME=None):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                with self.assertRaises(RuntimeError):
                    setup_duckdb_aws_connection(con=mock_con)

    def test_get_offers_base_path(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            self.assertEqual(get_offers_base_path(), "s3://test-bucket")

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH="/custom/media",
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                self.assertEqual(get_offers_base_path(), "/custom/media")

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH=None,
            MEDIA_ROOT="/media/root",
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                self.assertEqual(get_offers_base_path(), "/media/root")

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH=None,
            MEDIA_ROOT=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                with self.assertRaises(RuntimeError):
                    get_offers_base_path()

        # In production (DEBUG=False, TESTING=False), S3 bucket is mandatory
        with override_settings(
            DEBUG=False,
            TESTING=False,
            AWS_DATA_STORAGE_BUCKET_NAME="prod-bucket",
        ):
            self.assertEqual(get_offers_base_path(), "s3://prod-bucket")

        with override_settings(
            DEBUG=False,
            TESTING=False,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH="/custom/media",
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                with self.assertRaises(RuntimeError) as ctx:
                    get_offers_base_path()
                self.assertIn("production", str(ctx.exception).lower())

    def test_day_to_offers_parquet_url(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            url = day_to_offers_parquet_url(self.day)
            self.assertEqual(
                url, "s3://test-bucket/querydumps/offers/2025-05-13.parquet"
            )

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH="/custom/media",
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                url = day_to_offers_parquet_url(self.day)
                self.assertEqual(
                    url, "/custom/media/querydumps/offers/2025-05-13.parquet"
                )

    def test_month_to_offers_parquet_url(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            url = month_to_offers_parquet_url(self.day)
            self.assertEqual(
                url, "s3://test-bucket/querydumps/monthly-offers/2025-05.parquet"
            )

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH="/custom/media",
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                url = month_to_offers_parquet_url(self.day)
                self.assertEqual(
                    url, "/custom/media/querydumps/monthly-offers/2025-05.parquet"
                )

    def test_month_to_daily_offers_parquet_glob(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            url = month_to_daily_offers_parquet_glob(self.day)
            self.assertEqual(
                url, "s3://test-bucket/querydumps/offers/2025-05-*.parquet"
            )

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH="/custom/media",
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                url = month_to_daily_offers_parquet_glob(self.day)
                self.assertEqual(
                    url, "/custom/media/querydumps/offers/2025-05-*.parquet"
                )

    def test_dump_offers_options(self):
        with mock.patch("adserver.etl.utils.setup_duckdb_aws_connection") as mock_aws:
            with mock.patch("adserver.etl.utils.setup_duckdb_pg_connection"):
                with mock.patch("ibis.duckdb.connect") as mock_connect:
                    mock_backend = mock.MagicMock()
                    mock_connect.return_value = mock_backend
                    mock_table = mock.MagicMock()
                    mock_backend.table.return_value = mock_table
                    mock_table.select.return_value = mock_table
                    mock_table.left_join.return_value = mock_table
                    mock_table.filter.return_value = mock_table
                    mock_table.date.__ge__.return_value = mock_table
                    mock_table.date.__lt__.return_value = mock_table
                    mock_table.__and__.return_value = mock_table

                    with override_settings(
                        AWS_DATA_STORAGE_BUCKET_NAME="test-bucket",
                        ADSERVER_OFFER_DB_TABLE="custom_offers",
                    ):
                        url = dump_offers(self.start_date, self.end_date)
                        self.assertEqual(
                            url,
                            "s3://test-bucket/querydumps/offers/2025-05-13.parquet",
                        )
                        mock_aws.assert_called_once()
                        mock_backend.table.assert_any_call(
                            "custom_offers", database="ethicaladsdb"
                        )
                        mock_backend.to_parquet.assert_called_once()

    def test_offers_dump_exists_local(self):
        self.assertTrue(offers_dump_exists(self.day, parquet_path=self.parquet_path))
        non_existent = os.path.join(self.temp_dir.name, "non_existent.parquet")
        self.assertFalse(offers_dump_exists(self.day, parquet_path=non_existent))

    def test_offers_dump_exists_s3(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.utils.setup_duckdb_aws_connection"):
                mock_backend = mock.MagicMock()
                self.assertTrue(
                    offers_dump_exists(
                        self.day,
                        parquet_path="s3://test-bucket/querydumps/offers/2025-05-13.parquet",
                        con=mock_backend,
                    )
                )

                mock_backend.read_parquet.side_effect = duckdb.IOException(
                    "File not found"
                )
                self.assertFalse(
                    offers_dump_exists(
                        self.day,
                        parquet_path="s3://test-bucket/querydumps/offers/2025-05-13.parquet",
                        con=mock_backend,
                    )
                )

    def test_offers_dump_exists_setting(self):
        offers_dir = os.path.join(self.temp_dir.name, "querydumps", "offers")
        os.makedirs(offers_dir, exist_ok=True)
        target = os.path.join(offers_dir, "2025-05-13.parquet")
        write_test_offers_parquet(target)

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=self.temp_dir.name,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                self.assertTrue(offers_dump_exists(self.day))

    def test_offers_dump_exists_no_settings(self):
        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=None,
            MEDIA_ROOT=None,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                self.assertFalse(offers_dump_exists(self.day))
                self.assertFalse(
                    offers_dump_exists(
                        self.day,
                        parquet_path="s3://test-bucket/path.parquet",
                    )
                )

    def test_dump_monthly_offers(self):
        offers_dir = os.path.join(self.temp_dir.name, "querydumps", "offers")
        os.makedirs(offers_dir, exist_ok=True)
        day1_path = os.path.join(offers_dir, "2025-05-13.parquet")
        day2_path = os.path.join(offers_dir, "2025-05-14.parquet")
        write_test_offers_parquet(day1_path)
        write_test_offers_parquet(day2_path)

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=self.temp_dir.name,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                result_path = dump_monthly_offers(self.day)
                expected_path = os.path.join(
                    self.temp_dir.name,
                    "querydumps",
                    "monthly-offers",
                    "2025-05.parquet",
                )
                self.assertEqual(result_path, expected_path)
                self.assertTrue(os.path.exists(result_path))

                con = duckdb.connect()
                count = con.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{result_path}')"
                ).fetchone()[0]
                self.assertEqual(count, 10)

                # Test with explicit parquet_path
                custom_path = os.path.join(
                    self.temp_dir.name, "custom", "2025-05.parquet"
                )
                custom_result = dump_monthly_offers(self.day, parquet_path=custom_path)
                self.assertEqual(custom_result, custom_path)
                self.assertTrue(os.path.exists(custom_path))

    def test_dump_monthly_offers_s3(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.utils.setup_duckdb_aws_connection"):
                mock_backend = mock.MagicMock()
                res = dump_monthly_offers(self.day, con=mock_backend)
                self.assertEqual(
                    res,
                    "s3://test-bucket/querydumps/monthly-offers/2025-05.parquet",
                )
                mock_backend.to_parquet.assert_called_once()

        with override_settings(
            AWS_DATA_STORAGE_BUCKET_NAME=None,
            ADSERVER_OFFERS_LOCAL_PATH=None,
            MEDIA_ROOT=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                with self.assertRaises(RuntimeError):
                    dump_monthly_offers(self.day)

    def test_dump_monthly_offers_no_daily_files(self):
        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=self.temp_dir.name,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                res = dump_monthly_offers(datetime.date(2020, 1, 1))
                self.assertIsNone(res)

    def test_monthly_offers_dump_exists(self):
        monthly_path = os.path.join(self.temp_dir.name, "2025-05.parquet")
        write_test_offers_parquet(monthly_path)
        self.assertTrue(monthly_offers_dump_exists(self.day, parquet_path=monthly_path))
        non_existent = os.path.join(self.temp_dir.name, "non_existent.parquet")
        self.assertFalse(
            monthly_offers_dump_exists(self.day, parquet_path=non_existent)
        )

        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.utils.setup_duckdb_aws_connection"):
                mock_backend = mock.MagicMock()
                self.assertTrue(monthly_offers_dump_exists(self.day, con=mock_backend))
                mock_backend.read_parquet.side_effect = duckdb.IOException("Missing")
                self.assertFalse(monthly_offers_dump_exists(self.day, con=mock_backend))

        monthly_dir = os.path.join(self.temp_dir.name, "querydumps", "monthly-offers")
        os.makedirs(monthly_dir, exist_ok=True)
        local_target = os.path.join(monthly_dir, "2025-05.parquet")
        write_test_offers_parquet(local_target)

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=self.temp_dir.name,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                self.assertTrue(monthly_offers_dump_exists(self.day))


class TestDumpOffersFromDatabase(BaseAdModelsTestCase):
    """Test dump_offers creating parquet from database records."""

    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.day = datetime.date(2025, 5, 13)
        self.start_date, self.end_date = get_day(self.day)

        self.sqlite_path = os.path.join(self.temp_dir.name, "test_db.sqlite3")
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute("CREATE TABLE adserver_advertiser (id INTEGER PRIMARY KEY);")
            conn.execute(
                "CREATE TABLE adserver_campaign (id INTEGER PRIMARY KEY, advertiser_id INTEGER);"
            )
            conn.execute(
                "CREATE TABLE adserver_flight (id INTEGER PRIMARY KEY, campaign_id INTEGER, cpc REAL, cpm INTEGER);"
            )
            conn.execute(
                "CREATE TABLE adserver_advertisement (id INTEGER PRIMARY KEY, flight_id INTEGER);"
            )
            conn.execute(
                """
                CREATE TABLE adserver_offer (
                    id TEXT PRIMARY KEY,
                    date TIMESTAMP,
                    advertisement_id INTEGER,
                    publisher_id INTEGER,
                    country TEXT,
                    url TEXT,
                    domain TEXT,
                    viewed INTEGER,
                    clicked INTEGER,
                    paid_eligible INTEGER,
                    uplifted INTEGER,
                    view_time INTEGER,
                    rotations INTEGER,
                    keywords TEXT,
                    div_id TEXT,
                    ad_type_slug TEXT
                );
            """
            )
            conn.execute("INSERT INTO adserver_advertiser VALUES (1);")
            conn.execute("INSERT INTO adserver_campaign VALUES (1, 1);")
            conn.execute("INSERT INTO adserver_flight VALUES (1, 1, 0.5, 100);")
            conn.execute("INSERT INTO adserver_advertisement VALUES (1, 1);")
            conn.execute(
                """
                INSERT INTO adserver_offer VALUES (
                    '01900000-0000-7000-0000-000000000001',
                    '2025-05-13 10:00:00',
                    1,
                    1,
                    'US',
                    'https://docs.readthedocs.io/en/latest/',
                    'docs.readthedocs.io',
                    1,
                    0,
                    1,
                    0,
                    10,
                    1,
                    '["python", "docs"]',
                    'test-div',
                    'image-v1'
                );
            """
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dump_offers_from_db(self):
        output_path = os.path.join(self.temp_dir.name, "dumped_offers.parquet")
        with mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": f"sqlite:///{self.sqlite_path}",
                "REPLICA_DATABASE_URL": f"sqlite:///{self.sqlite_path}",
            },
        ):
            result = dump_offers(
                self.start_date, self.end_date, parquet_path=output_path
            )
            self.assertEqual(result, output_path)
            self.assertTrue(os.path.exists(output_path))

            con = duckdb.connect()
            df = con.execute(f"SELECT * FROM read_parquet('{output_path}')").fetchdf()
            self.assertEqual(len(df), 1)
            self.assertEqual(df["domain"].iloc[0], "docs.readthedocs.io")
            self.assertEqual(df["country"].iloc[0], "US")


class TestETLAggregations(TestCase):
    """Test DuckDB aggregation queries against test parquet data."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.day = datetime.date(2025, 5, 13)
        self.start_date, self.end_date = get_day(self.day)
        self.parquet_path = os.path.join(self.temp_dir.name, "2025-05-13.parquet")
        write_test_offers_parquet(self.parquet_path)

        self.sqlite_path = os.path.join(self.temp_dir.name, "test_db.sqlite3")
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                "CREATE TABLE adserver_publisher (id INTEGER PRIMARY KEY, allow_paid_campaigns BOOLEAN);"
            )
            conn.execute("INSERT INTO adserver_publisher VALUES (1, 1), (2, 0);")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_base_aggregation_errors(self):
        agg = BaseAggregation(
            self.start_date, self.end_date, parquet_url=self.parquet_path
        )
        with self.assertRaises(RuntimeError):
            agg.get_expression()
        with self.assertRaises(RuntimeError):
            agg.aggregate()

    def test_base_aggregation_s3_url(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch(
                "adserver.etl.aggregations.setup_duckdb_aws_connection"
            ) as mock_aws:
                with mock.patch("adserver.etl.aggregations.setup_duckdb_pg_connection"):
                    agg = BaseAggregation(
                        self.start_date,
                        self.end_date,
                        parquet_url="s3://test-bucket/test.parquet",
                    )
                    self.assertEqual(agg.parquet_url, "s3://test-bucket/test.parquet")
                    mock_aws.assert_called_once()

    def test_base_aggregation_aggregate(self):
        agg = DomainAggregation(
            self.start_date, self.end_date, parquet_url=self.parquet_path
        )
        mock_backend = mock.MagicMock()
        agg.backend = mock_backend
        with mock.patch.object(agg, "get_expression", return_value=mock.MagicMock()):
            agg.aggregate()
            mock_backend.insert.assert_called_once()

    def test_domain_aggregation(self):
        agg = DomainAggregation(
            self.start_date, self.end_date, parquet_url=self.parquet_path
        )
        self.assertIn("adserver_domainimpression", agg.table)
        expr = agg.get_expression()
        results = expr.execute()

        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results["domain"].iloc[0], "docs.readthedocs.io")

    def test_uplift_aggregation(self):
        agg = UpliftAggregation(
            self.start_date, self.end_date, parquet_url=self.parquet_path
        )
        self.assertIn("adserver_upliftimpression", agg.table)
        expr = agg.get_expression()
        results = expr.execute()

        self.assertEqual(len(results), 1)
        self.assertEqual(results["advertisement_id"].iloc[0], 1)
        self.assertEqual(results["publisher_id"].iloc[0], 1)
        self.assertEqual(results["decisions"].iloc[0], 2)
        self.assertEqual(results["views"].iloc[0], 2)

    def test_rotation_aggregation(self):
        agg = RotationAggregation(
            self.start_date, self.end_date, parquet_url=self.parquet_path
        )
        self.assertIn("adserver_rotationimpression", agg.table)
        expr = agg.get_expression()
        results = expr.execute()

        self.assertEqual(len(results), 2)

    def test_geo_and_region_aggregation_queries(self):
        with mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": f"sqlite:///{self.sqlite_path}",
                "REPLICA_DATABASE_URL": f"sqlite:///{self.sqlite_path}",
            },
        ):
            geo_agg = GeoAggregation(
                self.start_date, self.end_date, parquet_url=self.parquet_path
            )
            self.assertIn("adserver_geoimpression", geo_agg.table)
            geo_expr = geo_agg.get_expression()
            self.assertIsNotNone(geo_expr)
            geo_results = geo_expr.execute()
            self.assertGreaterEqual(len(geo_results), 1)

            region_agg = RegionAggregation(
                self.start_date, self.end_date, parquet_url=self.parquet_path
            )
            self.assertIn("adserver_regionimpression", region_agg.table)
            region_expr = region_agg.get_expression()
            self.assertIsNotNone(region_expr)
            region_results = region_expr.execute()
            self.assertGreaterEqual(len(region_results), 1)


class TestAudienceEstimator(TestCase):
    """Test AudienceEstimatorForm and AudienceEstimatorView."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.parquet_path = os.path.join(self.temp_dir.name, "2025-05-13.parquet")
        write_test_offers_parquet(self.parquet_path)

        self.kw_python, _ = Keyword.objects.get_or_create(slug="python")
        self.kw_django, _ = Keyword.objects.get_or_create(slug="django")
        self.kw_js, _ = Keyword.objects.get_or_create(slug="javascript")

        self.topic_python, _ = Topic.objects.get_or_create(
            slug="python",
            defaults={"name": "Python"},
        )
        self.topic_python.keywords.add(self.kw_python, self.kw_django)

        self.topic_empty, _ = Topic.objects.get_or_create(
            slug="empty-topic",
            defaults={"name": "Empty Topic"},
        )

        self.staff_user, _ = User.objects.get_or_create(
            email="staff@example.com",
            defaults={
                "is_staff": True,
            },
        )
        self.staff_user.is_staff = True
        self.staff_user.set_password("password")
        self.staff_user.save()

        self.regular_user, _ = User.objects.get_or_create(
            email="reg@example.com",
            defaults={
                "is_staff": False,
            },
        )
        self.regular_user.is_staff = False
        self.regular_user.set_password("password")
        self.regular_user.save()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_udf_definitions(self):
        # Directly invoking the python stub functions defined for Ibis
        self.assertIsNone(from_json.__wrapped__("{}", "[]"))
        self.assertIsNone(list_intersect.__wrapped__([], []))
        self.assertIsNone(json_contains.__wrapped__("{}", ""))

    def test_form_validation_success(self):
        form = AudienceEstimatorForm(
            data={
                "countries": "US, CA, DE",
                "topics": ["python"],
                "keywords": "python, django",
                "domains": "docs.readthedocs.io, example.com",
                "urls": "https://docs.readthedocs.io/en/latest/, https://example.com/guide",
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["countries"], ["US", "CA", "DE"])
        self.assertEqual(form.cleaned_data["keywords"], ["python", "django"])
        self.assertEqual(
            form.cleaned_data["domains"], ["docs.readthedocs.io", "example.com"]
        )
        self.assertEqual(
            form.cleaned_data["urls"],
            ["https://docs.readthedocs.io/en/latest/", "https://example.com/guide"],
        )

    def test_form_validation_errors(self):
        form = AudienceEstimatorForm(data={"countries": "INVALID"})
        self.assertFalse(form.is_valid())
        self.assertIn("countries", form.errors)

        form = AudienceEstimatorForm(data={"keywords": "unknown_kw_123"})
        self.assertFalse(form.is_valid())
        self.assertIn("keywords", form.errors)

        form = AudienceEstimatorForm(data={"domains": "nodotdomain"})
        self.assertFalse(form.is_valid())
        self.assertIn("domains", form.errors)

        form = AudienceEstimatorForm(data={"urls": "not-a-valid-url"})
        self.assertFalse(form.is_valid())
        self.assertIn("urls", form.errors)

    def test_view_permissions(self):
        url = reverse("etl-staff-audience-estimator")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.regular_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_get_parquet_path(self):
        view = AudienceEstimatorView()

        path = view.get_parquet_path(parquet_path="/custom/path.parquet")
        self.assertEqual(path, "/custom/path.parquet")

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=None,
            AWS_DATA_STORAGE_BUCKET_NAME="test-bucket",
            DEBUG=False,
        ):
            with mock.patch(
                "adserver.etl.views.monthly_offers_dump_exists", return_value=True
            ):
                path = view.get_parquet_path()
                self.assertTrue(
                    path.startswith("s3://test-bucket/querydumps/monthly-offers/")
                )

            with mock.patch(
                "adserver.etl.views.monthly_offers_dump_exists", return_value=False
            ):
                path = view.get_parquet_path()
                self.assertTrue(path.startswith("s3://test-bucket/querydumps/offers/"))
                self.assertTrue(path.endswith("-*.parquet"))

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH="/custom/media",
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                with mock.patch(
                    "adserver.etl.views.monthly_offers_dump_exists", return_value=True
                ):
                    path = view.get_parquet_path()
                    self.assertTrue(
                        path.startswith("/custom/media/querydumps/monthly-offers/")
                    )

                with mock.patch(
                    "adserver.etl.views.monthly_offers_dump_exists", return_value=False
                ):
                    path = view.get_parquet_path()
                    self.assertTrue(path.startswith("/custom/media/querydumps/offers/"))
                    self.assertTrue(path.endswith("-*.parquet"))

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=None,
            MEDIA_ROOT=None,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                with mock.patch(
                    "adserver.etl.views.monthly_offers_dump_exists", return_value=False
                ):
                    with self.assertRaises(RuntimeError):
                        view.get_parquet_path()

    def test_get_estimate_ibis_queries(self):
        view = AudienceEstimatorView()

        est = view.get_estimate(
            countries=[],
            topics=[],
            keywords=[],
            domains=[],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est, 3)

        est_us = view.get_estimate(
            countries=["US"],
            topics=[],
            keywords=[],
            domains=[],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est_us, 2)

        est_domain = view.get_estimate(
            countries=[],
            topics=[],
            keywords=[],
            domains=["docs.readthedocs.io"],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est_domain, 3)

        est_kw = view.get_estimate(
            countries=[],
            topics=[],
            keywords=["python"],
            domains=[],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est_kw, 2)

        est_topic = view.get_estimate(
            countries=[],
            topics=["python", "empty-topic", "nonexistent-topic"],
            keywords=[],
            domains=[],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est_topic, 2)

        est_comb = view.get_estimate(
            countries=["US"],
            topics=[],
            keywords=["django"],
            domains=["docs.readthedocs.io"],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est_comb, 1)

    def test_get_estimate_s3_path(self):
        view = AudienceEstimatorView()
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch(
                "adserver.etl.views.setup_duckdb_aws_connection"
            ) as mock_aws:
                est = view.get_estimate(
                    countries=[],
                    topics=[],
                    keywords=[],
                    domains=[],
                    parquet_path="s3://test-bucket/nonexistent.parquet",
                )
                self.assertEqual(est, 0)
                mock_aws.assert_called_once()

    def test_get_estimate_urls_ext_disabled(self):
        view = AudienceEstimatorView()
        # When ethicalads_ext.etl is not installed, URLs are skipped and other filters still work
        est = view.get_estimate(
            countries=["US"],
            topics=[],
            keywords=[],
            domains=[],
            urls=["https://docs.readthedocs.io/en/latest/"],
            parquet_path=self.parquet_path,
        )
        self.assertEqual(est, 2)

    def test_view_post_estimate(self):
        self.client.force_login(self.staff_user)
        url = reverse("etl-staff-audience-estimator")

        today = (
            timezone.now().date() if hasattr(timezone.now(), "date") else timezone.now()
        )
        first_of_month = today.replace(day=1)
        prev_month = first_of_month - timedelta(days=1)
        year_month = f"{prev_month.year}-{prev_month.month:02d}"

        monthly_dir = os.path.join(self.temp_dir.name, "querydumps", "monthly-offers")
        os.makedirs(monthly_dir, exist_ok=True)
        monthly_file = os.path.join(monthly_dir, f"{year_month}.parquet")
        write_test_offers_parquet(monthly_file)

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=self.temp_dir.name,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                response = self.client.post(
                    url,
                    data={
                        "countries": "US",
                        "keywords": "python",
                        "domains": "docs.readthedocs.io",
                        "urls": "",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["estimate"])
                self.assertEqual(response.context["estimated_views"], 2)

    def test_view_post_estimate_urls_warning(self):
        self.client.force_login(self.staff_user)
        url = reverse("etl-staff-audience-estimator")

        today = (
            timezone.now().date() if hasattr(timezone.now(), "date") else timezone.now()
        )
        first_of_month = today.replace(day=1)
        prev_month = first_of_month - timedelta(days=1)
        year_month = f"{prev_month.year}-{prev_month.month:02d}"

        monthly_dir = os.path.join(self.temp_dir.name, "querydumps", "monthly-offers")
        os.makedirs(monthly_dir, exist_ok=True)
        monthly_file = os.path.join(monthly_dir, f"{year_month}.parquet")
        write_test_offers_parquet(monthly_file)

        with override_settings(
            ADSERVER_OFFERS_LOCAL_PATH=self.temp_dir.name,
            AWS_DATA_STORAGE_BUCKET_NAME=None,
        ):
            with mock.patch("adserver.etl.utils.DATA_BUCKET_NAME", None):
                response = self.client.post(
                    url,
                    data={
                        "countries": "US",
                        "keywords": "python",
                        "domains": "docs.readthedocs.io",
                        "urls": "https://docs.readthedocs.io/en/latest/",
                    },
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["estimate"])
                # Since URLs are skipped, the estimate for US/python/docs is still computed (2 views)
                self.assertEqual(response.context["estimated_views"], 2)
                messages_list = list(response.context["messages"])
                self.assertTrue(
                    any(
                        "Niche targeting URLs were ignored" in str(m)
                        for m in messages_list
                    )
                )

    def test_get_estimate_missing_file(self):
        view = AudienceEstimatorView()
        non_existent = os.path.join(self.temp_dir.name, "missing.parquet")
        est = view.get_estimate(
            countries=[],
            topics=[],
            keywords=[],
            domains=[],
            parquet_path=non_existent,
        )
        self.assertEqual(est, 0)


class TestETLCeleryTasks(TestCase):
    """Test Celery ETL tasks."""

    def test_daily_offers_dump_skips_when_exists(self):
        day = datetime.date(2025, 5, 13)
        with mock.patch(
            "adserver.etl.tasks.offers_dump_exists", return_value=True
        ) as mock_exists:
            with mock.patch("adserver.etl.tasks.dump_offers") as mock_dump:
                daily_offers_dump(day=day, force=False)
                mock_exists.assert_called_once()
                mock_dump.assert_not_called()

    def test_daily_offers_dump_runs_when_forced(self):
        day = datetime.date(2025, 5, 13)
        with mock.patch("adserver.etl.tasks.offers_dump_exists", return_value=True):
            with mock.patch(
                "adserver.etl.tasks.dump_offers",
                return_value="s3://bucket/path.parquet",
            ) as mock_dump:
                daily_offers_dump(day=day, force=True)
                mock_dump.assert_called_once()

    def test_daily_offers_dump_customer_jobs(self):
        day = datetime.date(2025, 5, 13)
        with mock.patch("adserver.etl.tasks.offers_dump_exists", return_value=False):
            with mock.patch(
                "adserver.etl.tasks.dump_offers",
                return_value="s3://bucket/path.parquet",
            ):
                mock_customer_task = mock.MagicMock()
                with mock.patch.dict(
                    "sys.modules",
                    {
                        "ethicalads_ext.etl.tasks": mock.MagicMock(
                            daily_customer_etl=mock_customer_task
                        )
                    },
                ):
                    daily_offers_dump(day=day, run_customer_jobs=True)
                    if "ethicalads_ext.etl" in settings.INSTALLED_APPS:
                        mock_customer_task.delay.assert_called_once()
                    else:
                        mock_customer_task.delay.assert_not_called()

    def test_monthly_offers_dump_skips_when_exists(self):
        day = datetime.date(2025, 5, 1)
        with mock.patch(
            "adserver.etl.tasks.monthly_offers_dump_exists", return_value=True
        ):
            with mock.patch("adserver.etl.tasks.dump_monthly_offers") as mock_dump:
                monthly_offers_dump(day=day, force=False)
                mock_dump.assert_not_called()

    def test_monthly_offers_dump_runs_when_forced(self):
        day = datetime.date(2025, 5, 1)
        with mock.patch(
            "adserver.etl.tasks.monthly_offers_dump_exists", return_value=True
        ):
            with mock.patch(
                "adserver.etl.tasks.dump_monthly_offers",
                return_value="s3://bucket/path.parquet",
            ) as mock_dump:
                monthly_offers_dump(day=day, force=True)
                mock_dump.assert_called_once()

    def test_monthly_offers_dump_date_types(self):
        with mock.patch(
            "adserver.etl.tasks.monthly_offers_dump_exists", return_value=False
        ):
            with mock.patch(
                "adserver.etl.tasks.dump_monthly_offers",
                return_value="s3://bucket/path.parquet",
            ) as mock_dump:
                monthly_offers_dump()
                self.assertTrue(mock_dump.called)

                mock_dump.reset_mock()
                monthly_offers_dump(day=datetime.datetime(2025, 5, 1, 10, 0))
                self.assertTrue(mock_dump.called)

                mock_dump.reset_mock()
                monthly_offers_dump(day="2025-05-01")
                self.assertTrue(mock_dump.called)

    def test_monthly_offers_dump_no_daily_parquets(self):
        with mock.patch(
            "adserver.etl.tasks.monthly_offers_dump_exists", return_value=False
        ):
            with mock.patch(
                "adserver.etl.tasks.dump_monthly_offers", return_value=None
            ):
                with mock.patch("adserver.etl.tasks.slack_message") as mock_slack:
                    monthly_offers_dump(day="2025-05-01")
                    mock_slack.assert_not_called()

    def test_daily_etl_pipeline(self):
        with mock.patch("adserver.etl.tasks.daily_offers_dump.delay") as mock_delay:
            daily_etl_pipeline(day="2025-05-13")
            mock_delay.assert_called_once()

            mock_delay.reset_mock()
            daily_etl_pipeline()
            mock_delay.assert_called_once()


class TestTasksUsingAggregations(TestCase):
    """Test daily aggregation tasks in adserver/tasks.py using DuckDB aggregations."""

    def test_daily_update_geos_with_offers_dump(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.aggregations.setup_duckdb_aws_connection"):
                with mock.patch("adserver.etl.aggregations.setup_duckdb_pg_connection"):
                    with mock.patch(
                        "adserver.tasks.offers_dump_exists", return_value=True
                    ):
                        with mock.patch(
                            "adserver.etl.aggregations.GeoAggregation.aggregate"
                        ) as mock_geo:
                            with mock.patch(
                                "adserver.etl.aggregations.RegionAggregation.aggregate"
                            ) as mock_region:
                                daily_update_geos(day="2025-05-13")
                                mock_geo.assert_called_once()
                                mock_region.assert_called_once()

    def test_daily_update_uplift_with_offers_dump(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.aggregations.setup_duckdb_aws_connection"):
                with mock.patch("adserver.etl.aggregations.setup_duckdb_pg_connection"):
                    with mock.patch(
                        "adserver.tasks.offers_dump_exists", return_value=True
                    ):
                        with mock.patch(
                            "adserver.etl.aggregations.UpliftAggregation.aggregate"
                        ) as mock_uplift:
                            daily_update_uplift(day="2025-05-13")
                            mock_uplift.assert_called_once()

    def test_daily_update_domains_with_offers_dump(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.aggregations.setup_duckdb_aws_connection"):
                with mock.patch("adserver.etl.aggregations.setup_duckdb_pg_connection"):
                    with mock.patch(
                        "adserver.tasks.offers_dump_exists", return_value=True
                    ):
                        with mock.patch(
                            "adserver.etl.aggregations.DomainAggregation.aggregate"
                        ) as mock_domain:
                            daily_update_domains(day="2025-05-13")
                            mock_domain.assert_called_once()

    def test_daily_update_rotations_with_offers_dump(self):
        with override_settings(AWS_DATA_STORAGE_BUCKET_NAME="test-bucket"):
            with mock.patch("adserver.etl.aggregations.setup_duckdb_aws_connection"):
                with mock.patch("adserver.etl.aggregations.setup_duckdb_pg_connection"):
                    with mock.patch(
                        "adserver.tasks.offers_dump_exists", return_value=True
                    ):
                        with mock.patch(
                            "adserver.etl.aggregations.RotationAggregation.aggregate"
                        ) as mock_rot:
                            daily_update_rotations(day="2025-05-13")
                            mock_rot.assert_called_once()
