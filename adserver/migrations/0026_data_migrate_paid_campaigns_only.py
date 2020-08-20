from django.db import migrations


def forwards(apps, schema_editor):
    """Migrate Publisher.paid_campaigns_only to separate fields."""
    Publisher = apps.get_model("adserver", "Publisher")

    for pub in Publisher.objects.all():
        if pub.paid_campaigns_only:
            pub.allow_paid_campaigns = True
            pub.allow_affiliate_campaigns = False
            pub.allow_community_campaigns = False
            pub.allow_house_campaigns = False
            pub.save()


def backwards(apps, schema_editor):
    """Migrate separate publisher campaign type allow fields back to Publisher.paid_campaigns_only"""
    Publisher = apps.get_model("adserver", "Publisher")

    for pub in Publisher.objects.all():
        if all([
            not pub.paid_campaigns_only,
            pub.allow_paid_campaigns,
            not pub.allow_affiliate_campaigns,
            not pub.allow_community_campaigns,
            not pub.allow_house_campaigns,
        ]):
            pub.paid_campaigns_only = True
            pub.save()


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0025_publisher_control_campaign_type'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
