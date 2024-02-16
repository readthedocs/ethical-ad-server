# Generated by Django 4.2.4 on 2024-02-16 20:54
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("adserver", "0091_publisher_group_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalpublisher",
            name="github_sponsors_name",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=200,
                null=True,
                verbose_name="GitHub sponsors name",
            ),
        ),
        migrations.AddField(
            model_name="publisher",
            name="github_sponsors_name",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=200,
                null=True,
                verbose_name="GitHub sponsors name",
            ),
        ),
        migrations.AlterField(
            model_name="historicalpublisher",
            name="payout_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("stripe", "Stripe (Bank transfer, debit card)"),
                    ("paypal", "PayPal"),
                    ("opencollective", "Open Collective"),
                    ("github", "GitHub sponsors"),
                    ("other", "Other"),
                ],
                default=None,
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicalpublisherpayout",
            name="method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("stripe", "Stripe (Bank transfer, debit card)"),
                    ("paypal", "PayPal"),
                    ("opencollective", "Open Collective"),
                    ("github", "GitHub sponsors"),
                    ("other", "Other"),
                ],
                default=None,
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="publisher",
            name="payout_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("stripe", "Stripe (Bank transfer, debit card)"),
                    ("paypal", "PayPal"),
                    ("opencollective", "Open Collective"),
                    ("github", "GitHub sponsors"),
                    ("other", "Other"),
                ],
                default=None,
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="publisherpayout",
            name="method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("stripe", "Stripe (Bank transfer, debit card)"),
                    ("paypal", "PayPal"),
                    ("opencollective", "Open Collective"),
                    ("github", "GitHub sponsors"),
                    ("other", "Other"),
                ],
                default=None,
                max_length=100,
                null=True,
            ),
        ),
    ]
