# Generated by Django 5.0.8 on 2024-09-30 21:04

import adserver.analyzer.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("adserver_analyzer", "0007_add_advertiser_flights"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analyzedadvertiserurl",
            name="keywords",
            field=models.JSONField(
                blank=True,
                null=True,
                validators=[adserver.analyzer.validators.KeywordsValidator()],
                verbose_name="Keywords for this URL",
            ),
        ),
        migrations.AlterField(
            model_name="analyzedurl",
            name="keywords",
            field=models.JSONField(
                blank=True,
                null=True,
                validators=[adserver.analyzer.validators.KeywordsValidator()],
                verbose_name="Keywords for this URL",
            ),
        ),
    ]
