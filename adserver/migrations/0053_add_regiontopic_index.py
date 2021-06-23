# Generated by Django 2.2.13 on 2021-06-08 20:17
import django.db.models.deletion
import django_extensions.db.fields
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0052_publisher_ctr_sample'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegionTopicImpression',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(auto_now_add=True, verbose_name='created')),
                ('modified', django_extensions.db.fields.ModificationDateTimeField(auto_now=True, verbose_name='modified')),
                ('date', models.DateField(db_index=True, verbose_name='Date')),
                ('decisions', models.PositiveIntegerField(default=0, help_text="The number of times the Ad Decision API was called. The server might not respond with an ad if there isn't inventory.", verbose_name='Decisions')),
                ('offers', models.PositiveIntegerField(default=0, help_text='The number of times an ad was proposed by the ad server. The client may not load the ad (a view) for a variety of reasons ', verbose_name='Offers')),
                ('views', models.PositiveIntegerField(default=0, help_text='Number of times the ad was legitimately viewed', verbose_name='Views')),
                ('clicks', models.PositiveIntegerField(default=0, help_text='Number of times the ad was legitimately clicked', verbose_name='Clicks')),
                ('region', models.CharField(max_length=100, verbose_name='Region')),
                ('topic', models.CharField(max_length=100, verbose_name='Topic')),
            ],
            options={
                'ordering': ('-date',),
                'unique_together': {('date', 'region', 'topic')},
            },
        ),
    ]