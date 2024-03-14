# Generated by Django 4.2.11 on 2024-03-14 21:27
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("adserver", "0093_publisher_ignore_mobile_traffic"),
        ("adserver_analyzer", "0006_add_analyzedad"),
    ]

    operations = [
        migrations.RenameField(
            model_name="analyzedad",
            old_name="ad",
            new_name="advertisement",
        ),
        migrations.AlterUniqueTogether(
            name="analyzedad",
            unique_together={("url", "advertisement")},
        ),
    ]
