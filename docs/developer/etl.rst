ETL & Analytical Data Pipeline
==============================

This document explains the Ethical Ad Server's periodic ETL (Extract, Transform, Load) pipeline,
the architecture for processing reporting data, and why analytical offer data is archived to
`Apache Parquet <https://parquet.apache.org/>`_ files rather than retained in PostgreSQL indefinitely.


Why Parquet Instead of Long-Term PostgreSQL Storage?
----------------------------------------------------

This ad server can process millions of ad decisions and impressions every day.
Storing and querying this volume of historical offer data directly in PostgreSQL causes several major operational challenges:

1. **Database Bloat and Storage Growth**:
   Raw offer logs accumulate hundreds of gigabytes (and eventually terabytes) of data.
   Keeping historical offers in transactional relational storage is costly and inefficient.

2. **Index Bloat and Memory Pressure**:
   To query offers by various dimensions (dates, advertisers, publishers, countries, domains, keywords),
   many indexes are required. Over time, these indexes become huge and take up the majority of the DB size.

3. **Performance Degradation on Transactional Traffic**:
   The primary job of the ad server database is low-latency, transactional ad serving (OLTP).
   Offloading analytical and aggregate reporting queries (OLAP) from PostgreSQL
   simplifies our performance and reduces the risk of reporting causing slowdowns for ad serving.

To solve these challenges, we offload historical analytical data to **Parquet files** on object storage (AWS S3)
and query them with `DuckDB <https://duckdb.org/>`_ and `Ibis <https://ibis-project.org/>`_:

- **Columnar Compression**: Parquet organizes data by column and is optimized for fast querying.
- **Fast Columnar Analytics**: Query engines like DuckDB only scan and decompress the columns and row groups required for a query.
- **Separation of Storage and Compute**: Archiving offers to S3 frees PostgreSQL to focus exclusively on fast transactional operations and recent data.


ETL Architecture & Periodic Jobs
--------------------------------

The ETL pipeline lives in the ``adserver.etl`` app and runs periodically via Celery / Celery Beat:

- **Nightly Offers ETL**: Reads a day's worth of data and writes to a daily Parquet file in S3 (``querydumps/offers/YYYY-MM-DD.parquet``)
- **Monthly Consolidation ETL**: Reads a month's worth of nightly Parquet files and writes to a monthly Parquet file in S3 (``querydumps/monthly-offers/YYYY-MM.parquet``)

Reporting queries for advertisers, publishers, or staff can be executed directly against these Parquet files in S3 using DuckDB and Ibis,
or they can be downloaded to a local machine for offline analysis.


Configuration & Local Development
---------------------------------

Key settings in ``config/settings/``:

- ``AWS_DATA_STORAGE_BUCKET_NAME``: S3 bucket where Parquet dumps are read and written in production.
- ``ADSERVER_OFFERS_LOCAL_PATH``: Base directory for local offers Parquet files in development (defaults to ``MEDIA_ROOT`` / ``./media``). In local development without S3, the folder structure mirrors production S3 (``querydumps/offers/`` and ``querydumps/monthly-offers/``).
