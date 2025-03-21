from django.db import migrations
from django.contrib.auth import get_user_model


def forwards(apps, schema_editor):
    """Mark all existing users verified."""
    User = get_user_model()

    for user in User.objects.all():
        for email in user.emailaddress_set.filter(email=user.email):
            email.set_verified()


class Migration(migrations.Migration):

    dependencies = [
        ('adserver_auth', '0009_user_advertiser_publisher_roles'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop)
    ]
