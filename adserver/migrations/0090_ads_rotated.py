# Generated by Django 4.2.4 on 2024-01-03 20:50
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("adserver", "0089_paid_eligible_isproxy"),
    ]

    operations = [
        migrations.AddField(
            model_name="click",
            name="rotated",
            field=models.BooleanField(
                default=None, null=True, verbose_name="Ad was rotated"
            ),
        ),
        migrations.AddField(
            model_name="offer",
            name="rotated",
            field=models.BooleanField(
                default=None, null=True, verbose_name="Ad was rotated"
            ),
        ),
        migrations.AddField(
            model_name="view",
            name="rotated",
            field=models.BooleanField(
                default=None, null=True, verbose_name="Ad was rotated"
            ),
        ),
    ]
