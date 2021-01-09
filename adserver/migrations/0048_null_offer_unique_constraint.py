"""
Fixes a possible race condition where two entries for the same date/publisher with advertisement=null can occur.

This migration will fail if there are records that won't satisfy the constraint in the DB.
Here's a query to find all such records:

    SELECT ai1.id, ai2.id, ai1.date, ai1.publisher_id, ai1.advertisement_id
    FROM adserver_adimpression ai1
    INNER JOIN adserver_adimpression ai2
    ON (
        ai1.publisher_id = ai2.publisher_id
        AND ai1.date = ai2.date
        AND ai1.id < ai2.id
        AND ai1.advertisement_id IS NULL
        AND ai2.advertisement_id IS NULL
    )
    ORDER BY ai2.id;
"""
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0047_breakout_ad_parts'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='adimpression',
            constraint=models.UniqueConstraint(condition=models.Q(advertisement=None), fields=('publisher', 'date'), name='null_offer_unique'),
        ),
    ]
