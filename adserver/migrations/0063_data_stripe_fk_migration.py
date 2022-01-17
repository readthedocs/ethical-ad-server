"""
Migrates the existing model attributes:
 - Advertiser.stripe_customer_id
 - Publisher.stripe_connected_account_id

This migration *MUST* be run after ./manage.py djstripe_sync_models
"""
from django.db import migrations


def forwards(apps, schema_editor):
    """Migrate to proper Stripe FKs."""
    Advertiser = apps.get_model("adserver", "Advertiser")
    Publisher = apps.get_model("adserver", "Publisher")
    Customer = apps.get_model("djstripe", "Customer")
    Account = apps.get_model("djstripe", "Account")

    for advertiser in Advertiser.objects.all():
        if advertiser.stripe_customer_id:
            advertiser.djstripe_customer = Customer.objects.get(id=advertiser.stripe_customer_id)
            advertiser.save()

    for publisher in Publisher.objects.all():
        if publisher.stripe_connected_account_id:
            publisher.djstripe_account = Account.objects.get(id=publisher.stripe_connected_account_id)
            publisher.save()


def backwards(apps, schema_editor):
    """Migrate data back from FKs to regular fields."""
    Advertiser = apps.get_model("adserver", "Advertiser")
    Publisher = apps.get_model("adserver", "Publisher")

    for advertiser in Advertiser.objects.all():
        if advertiser.djstripe_customer:
            advertiser.stripe_customer_id = advertiser.djstripe_customer.id
            advertiser.save()

    for publisher in Publisher.objects.all():
        if publisher.djstripe_account:
            publisher.stripe_connected_account_id = publisher.djstripe_account.id
            publisher.save()


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0062_stripe_fks'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards)
    ]
