# Generated by Django 5.0.9 on 2024-11-27 00:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0098_rotation_aggregation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='advertisement',
            name='link',
            field=models.URLField(help_text="URL of your landing page. This may contain UTM parameters so you know the traffic came from us. The publisher will be added in the 'ea-publisher' query parameter. Additional variable substitutions are available. See the <a href='https://www.ethicalads.io/advertiser-guide/#measuring-conversions'>advertiser guide</a>. ", max_length=1024, verbose_name='Link URL'),
        ),
        migrations.AlterField(
            model_name='historicaladvertisement',
            name='link',
            field=models.URLField(help_text="URL of your landing page. This may contain UTM parameters so you know the traffic came from us. The publisher will be added in the 'ea-publisher' query parameter. Additional variable substitutions are available. See the <a href='https://www.ethicalads.io/advertiser-guide/#measuring-conversions'>advertiser guide</a>. ", max_length=1024, verbose_name='Link URL'),
        ),
    ]
