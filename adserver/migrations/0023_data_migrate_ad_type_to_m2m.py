from django.db import migrations


def forwards(apps, schema_editor):
    """
    Migrate Advertisement.ad_type FK to many-to-many.

    This allows a single ad to have multiple ad types
    which allows it to be displayed in multiple ways.
    """
    Advertisement = apps.get_model("adserver", "Advertisement")

    for ad in Advertisement.objects.all().select_related("ad_type"):
        if ad.ad_type:
            ad.ad_types.add(ad.ad_type)


def backwards(apps, schema_editor):
    """Migrate Advertisement.ad_type many-to-many back to a single FK."""
    Advertisement = apps.get_model("adserver", "Advertisement")

    # This is imperfect and involves a loss of precision.
    # When migrating back from AdType being many-to-many
    # back to a single foreign key, just choose the first ad type
    for ad in Advertisement.objects.all().select_related("ad_type").prefetch_related("ad_types"):
        if not ad.ad_type:
            ad.ad_type = ad.ad_types.all().first()
            ad.save()


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0022_ad_types_m2m'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards)
    ]
