# Generated by Django 3.2.12 on 2022-03-17 16:51
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0066_disable_publishers'),
    ]

    operations = [
        migrations.AddField(
            model_name='adimpression',
            name='view_time',
            field=models.PositiveIntegerField(null=True, verbose_name='Seconds that the ad was in view'),
        ),
    ]
