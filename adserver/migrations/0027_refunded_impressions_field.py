# Generated by Django 2.2.13 on 2020-07-31 23:34
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0026_data_migrate_paid_campaigns_only'),
    ]

    operations = [
        migrations.AddField(
            model_name='click',
            name='is_refunded',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='view',
            name='is_refunded',
            field=models.BooleanField(default=False),
        ),
    ]
