from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0106_add_advertiser_flight_logos'),
    ]

    operations = [
        migrations.AddField(
            model_name='publisher',
            name='batch_db_writes',
            field=models.BooleanField(
                default=False,
                help_text='Batch database writes (offers, impressions) in Redis and flush periodically. Reduces per-request DB load. Requires Redis cache backend.',
            ),
        ),
    ]
