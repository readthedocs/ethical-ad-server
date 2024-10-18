# Generated by Django 5.0.9 on 2024-10-18 18:03

import django.db.models.deletion
import django_extensions.db.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0097_migrate_jsonfield'),
    ]

    operations = [
        migrations.CreateModel(
            name='RotationImpression',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(auto_now_add=True, verbose_name='created')),
                ('modified', django_extensions.db.fields.ModificationDateTimeField(auto_now=True, verbose_name='modified')),
                ('date', models.DateField(db_index=True, verbose_name='Date')),
                ('decisions', models.PositiveIntegerField(default=0, help_text="The number of times the Ad Decision API was called. The server might not respond with an ad if there isn't inventory.", verbose_name='Decisions')),
                ('offers', models.PositiveIntegerField(default=0, help_text='The number of times an ad was proposed by the ad server. The client may not load the ad (a view) for a variety of reasons ', verbose_name='Offers')),
                ('views', models.PositiveIntegerField(default=0, help_text='Number of times the ad was legitimately viewed', verbose_name='Views')),
                ('clicks', models.PositiveIntegerField(default=0, help_text='Number of times the ad was legitimately clicked', verbose_name='Clicks')),
                ('advertisement', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='rotated_impressions', to='adserver.advertisement')),
                ('publisher', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='rotated_impressions', to='adserver.publisher')),
            ],
            options={
                'ordering': ('-date',),
                'unique_together': {('publisher', 'advertisement', 'date')},
            },
        ),
    ]
