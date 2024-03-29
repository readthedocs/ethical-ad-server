# Generated by Django 3.2.12 on 2022-04-19 16:10
import django.db.models.deletion
import django_extensions.db.fields
import jsonfield.fields
import simple_history.models
from django.conf import settings
from django.db import migrations
from django.db import models

import adserver.analyzer.validators


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('adserver', '0067_add_adimpression_viewtime'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoricalAnalyzedUrl',
            fields=[
                ('id', models.IntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(auto_now_add=True, verbose_name='created')),
                ('modified', django_extensions.db.fields.ModificationDateTimeField(auto_now=True, verbose_name='modified')),
                ('url', models.URLField(db_index=True, help_text='URL of the page being analyzed after certain query parameters are stripped away', max_length=1024)),
                ('keywords', jsonfield.fields.JSONField(blank=True, null=True, validators=[adserver.analyzer.validators.KeywordsValidator()], verbose_name='Keywords for this URL')),
                ('last_analyzed_date', models.DateTimeField(blank=True, db_index=True, default=None, help_text='Last time the ad server analyzed this URL', null=True)),
                ('last_ad_served_date', models.DateTimeField(blank=True, default=None, help_text='Last time an ad was served for this URL', null=True)),
                ('visits_since_last_analyzed', models.PositiveIntegerField(default=0, help_text='Number of times ads have been served for this URL since it was last analyzed')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField()),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('publisher', models.ForeignKey(blank=True, db_constraint=False, help_text='Publisher where this URL appears', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='adserver.publisher')),
            ],
            options={
                'verbose_name': 'historical analyzed url',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': 'history_date',
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='AnalyzedUrl',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(auto_now_add=True, verbose_name='created')),
                ('modified', django_extensions.db.fields.ModificationDateTimeField(auto_now=True, verbose_name='modified')),
                ('url', models.URLField(db_index=True, help_text='URL of the page being analyzed after certain query parameters are stripped away', max_length=1024)),
                ('keywords', jsonfield.fields.JSONField(blank=True, null=True, validators=[adserver.analyzer.validators.KeywordsValidator()], verbose_name='Keywords for this URL')),
                ('last_analyzed_date', models.DateTimeField(blank=True, db_index=True, default=None, help_text='Last time the ad server analyzed this URL', null=True)),
                ('last_ad_served_date', models.DateTimeField(blank=True, default=None, help_text='Last time an ad was served for this URL', null=True)),
                ('visits_since_last_analyzed', models.PositiveIntegerField(default=0, help_text='Number of times ads have been served for this URL since it was last analyzed')),
                ('publisher', models.ForeignKey(help_text='Publisher where this URL appears', on_delete=django.db.models.deletion.CASCADE, to='adserver.publisher')),
            ],
            options={
                'unique_together': {('url', 'publisher')},
            },
        ),
    ]
