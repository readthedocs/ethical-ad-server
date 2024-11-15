"""
This migration was autocreated but has been customized.

See: https://docs.djangoproject.com/en/5.0/howto/writing-migrations/#changing-a-manytomanyfield-to-use-a-through-model
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0098_rotation_aggregation'),
        ('adserver_auth', '0008_data_flight_notifications'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='UserAdvertiserMember',
                    fields=[
                        ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        # We add this in a separate operation below
                        # ('role', models.CharField(choices=[('Admin', 'Admin'), ('Manager', 'Manager'), ('Reporter', 'Reporter')], default='Admin', max_length=100)),
                        ('advertiser', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='adserver.advertiser')),
                        ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'adserver_auth_user_advertisers',
                    },
                ),
                migrations.AlterField(
                    model_name='user',
                    name='advertisers',
                    field=models.ManyToManyField(blank=True, through='adserver_auth.UserAdvertiserMember', to='adserver.advertiser'),
                ),
                migrations.CreateModel(
                    name='UserPublisherMember',
                    fields=[
                        ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        # We add this in a separate operation below
                        # ('role', models.CharField(choices=[('Admin', 'Admin'), ('Manager', 'Manager'), ('Reporter', 'Reporter')], default='Admin', max_length=100)),
                        ('publisher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='adserver.publisher')),
                        ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'adserver_auth_user_publishers',
                    },
                ),
                migrations.AlterField(
                    model_name='user',
                    name='publishers',
                    field=models.ManyToManyField(blank=True, through='adserver_auth.UserPublisherMember', to='adserver.publisher'),
                ),
            ],
        ),
        migrations.AddField(
            model_name="useradvertisermember",
            name="role",
            field=models.CharField(choices=[('Admin', 'Admin'), ('Manager', 'Manager'), ('Reporter', 'Reporter')], default='Admin', max_length=100),
        ),
        migrations.AddField(
            model_name="userpublishermember",
            name="role",
            field=models.CharField(choices=[('Admin', 'Admin'), ('Manager', 'Manager'), ('Reporter', 'Reporter')], default='Admin', max_length=100),
        ),
    ]
