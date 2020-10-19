"""
Indexes the impression and offer/click/view tables.

This migration indexes a few potentially *VERY LARGE* tables.
As a result, it is probably best faked and run concurrently.

https://www.postgresql.org/docs/9.1/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY

CREATE INDEX CONCURRENTLY "adserver_adimpression_date_2d0c27df" ON "adserver_adimpression" ("date");
CREATE INDEX CONCURRENTLY "adserver_click_date_e4990df6" ON "adserver_click" ("date");
CREATE INDEX CONCURRENTLY "adserver_offer_date_727b287b" ON "adserver_offer" ("date");
CREATE INDEX CONCURRENTLY "adserver_placementimpression_date_a840af08" ON "adserver_placementimpression" ("date");
CREATE INDEX CONCURRENTLY "adserver_view_date_a6d72ef8" ON "adserver_view" ("date");
"""
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0033_add_keyword_placement_impressions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='adimpression',
            name='date',
            field=models.DateField(db_index=True, verbose_name='Date'),
        ),
        migrations.AlterField(
            model_name='click',
            name='date',
            field=models.DateTimeField(db_index=True, verbose_name='Impression date'),
        ),
        migrations.AlterField(
            model_name='offer',
            name='date',
            field=models.DateTimeField(db_index=True, verbose_name='Impression date'),
        ),
        migrations.AlterField(
            model_name='placementimpression',
            name='date',
            field=models.DateField(db_index=True, verbose_name='Date'),
        ),
        migrations.AlterField(
            model_name='view',
            name='date',
            field=models.DateTimeField(db_index=True, verbose_name='Impression date'),
        ),
    ]
