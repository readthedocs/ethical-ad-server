# Generated by Django 5.0.9 on 2024-12-02 23:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0099_link_advertiser_guide'),
    ]

    operations = [
        migrations.AddField(
            model_name='click',
            name='domain',
            field=models.CharField(blank=True, max_length=10000, null=True, verbose_name='Domain'),
        ),
        migrations.AddField(
            model_name='offer',
            name='domain',
            field=models.CharField(blank=True, max_length=10000, null=True, verbose_name='Domain'),
        ),
        migrations.AddField(
            model_name='view',
            name='domain',
            field=models.CharField(blank=True, max_length=10000, null=True, verbose_name='Domain'),
        ),
    ]
