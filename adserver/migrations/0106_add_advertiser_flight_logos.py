from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0105_historicalpublisher_send_bid_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='advertiser',
            name='advertiser_logo',
            field=models.ImageField(blank=True, help_text='The logo for the advertiser. Returned in ad responses. Recommended size 200x200.', null=True, upload_to='advertiser_logos/%Y/%m/', verbose_name='Advertiser Logo'),
        ),
        migrations.AddField(
            model_name='flight',
            name='flight_logo',
            field=models.ImageField(blank=True, help_text='Overrides the advertiser logo for this specific flight. Recommended size 200x200.', null=True, upload_to='flight_logos/%Y/%m/', verbose_name='Flight Logo'),
        ),
        migrations.AddField(
            model_name='historicaladvertiser',
            name='advertiser_logo',
            field=models.TextField(blank=True, help_text='The logo for the advertiser. Returned in ad responses. Recommended size 200x200.', max_length=100, null=True, verbose_name='Advertiser Logo'),
        ),
        migrations.AddField(
            model_name='historicalflight',
            name='flight_logo',
            field=models.TextField(blank=True, help_text='Overrides the advertiser logo for this specific flight. Recommended size 200x200.', max_length=100, null=True, verbose_name='Flight Logo'),
        ),
    ]
