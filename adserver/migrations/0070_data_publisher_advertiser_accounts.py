"""
Creates advertiser accounts for each publisher.
"""
from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    """Add advertiser accounts for all our publishers."""
    Advertiser = apps.get_model("adserver", "Advertiser")
    Publisher = apps.get_model("adserver", "Publisher")
    Campaign = apps.get_model("adserver", "Campaign")
    Flight = apps.get_model("adserver", "Flight")

    for publisher in Publisher.objects.all():
        # Check if the account exists already
        # If it does, skip this one.
        if not Advertiser.objects.filter(publisher=publisher).exists():
            advertiser = Advertiser.objects.create(
                name=publisher.name,
                slug=publisher.slug,
                publisher=publisher,
            )
            campaign = Campaign.objects.create(
                advertiser=advertiser,
                name=publisher.name,
                slug=publisher.slug,
                campaign_type="publisher-house",
            )

            flight_name = f"{publisher.name} House Ads"
            Flight.objects.create(
                campaign=campaign,
                name=flight_name,
                slug=slugify(flight_name),
                sold_impressions=999_999_999,
                live=True,
                targeting_parameters={
                    "include_publishers": [publisher.slug],
                },
            )

            for pub_group in publisher.publisher_groups.all():
                campaign.publisher_groups.add(pub_group)


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0069_publisher_house_ads'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop)
    ]
