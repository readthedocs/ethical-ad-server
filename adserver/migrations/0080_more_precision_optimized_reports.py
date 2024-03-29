# Generated by Django 3.2.18 on 2023-03-01 23:03
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0079_prioritize_ads_by_ctr'),
    ]

    operations = [
        migrations.AlterField(
            model_name='advertiserimpression',
            name='spend',
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10, verbose_name='Daily spend'),
        ),
        migrations.AlterField(
            model_name='publisherimpression',
            name='revenue',
            field=models.DecimalField(decimal_places=4, default=0, help_text='This value has not been multiplied by the revenue share percentage', max_digits=10, verbose_name='Daily revenue'),
        ),
        migrations.AlterField(
            model_name='publisherpaidimpression',
            name='revenue',
            field=models.DecimalField(decimal_places=4, default=0, help_text='This value has not been multiplied by the revenue share percentage', max_digits=10, verbose_name='Daily revenue'),
        ),
    ]
