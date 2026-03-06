from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0106_add_advertiser_flight_logos'),
    ]

    operations = [
        migrations.AddField(
            model_name='publisher',
            name='batch_impression_writes',
            field=models.BooleanField(
                default=False,
                help_text='Batch AdImpression counter updates in Redis and flush periodically. Reduces per-request DB load. Requires Redis cache backend.',
            ),
        ),
        migrations.AddField(
            model_name='publisher',
            name='batch_offer_writes',
            field=models.BooleanField(
                default=False,
                help_text='Batch Offer row creation in Redis and flush periodically. Reduces per-request DB load. Requires Redis cache backend.',
            ),
        ),
        migrations.AddField(
            model_name='historicalpublisher',
            name='batch_impression_writes',
            field=models.BooleanField(
                default=False,
                help_text='Batch AdImpression counter updates in Redis and flush periodically. Reduces per-request DB load. Requires Redis cache backend.',
            ),
        ),
        migrations.AddField(
            model_name='historicalpublisher',
            name='batch_offer_writes',
            field=models.BooleanField(
                default=False,
                help_text='Batch Offer row creation in Redis and flush periodically. Reduces per-request DB load. Requires Redis cache backend.',
            ),
        ),
    ]
