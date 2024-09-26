# Generated by Django 4.2.11 on 2024-09-26 16:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("adserver_analyzer", "0001_squashed_0006_remove_embedding"),
    ]

    operations = [
        migrations.AddField(
            model_name="analyzedadvertiserurl",
            name="flights",
            field=models.ManyToManyField(
                help_text="Flights to filter this URL by",
                blank=True,
                to="adserver.flight",
            ),
        ),
    ]
