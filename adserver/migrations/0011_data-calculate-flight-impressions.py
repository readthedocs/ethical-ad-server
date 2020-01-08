from django.db import migrations
from django.db import models


def forwards(apps, schema_editor):
    Flight = apps.get_model("adserver", "Flight")

    for flight in Flight.objects.all().annotate(
            flight_total_clicks=models.Sum(models.F("advertisements__impressions__clicks")),
            flight_total_views=models.Sum(models.F("advertisements__impressions__views")),
    ):
        flight.total_clicks = flight.flight_total_clicks or 0
        flight.total_views = flight.flight_total_views or 0
        flight.save()


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0010_add-denormalized-flight-fields'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop)
    ]
