# Generated by Django 5.0.10 on 2025-01-02 21:27

import uuid_utils.compat
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adserver', '0101_domainimpression_aggregation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='historicalpublisherpayout',
            name='id',
            field=models.UUIDField(db_index=True, default=uuid_utils.compat.uuid7, editable=False),
        ),
        migrations.AlterField(
            model_name='offer',
            name='id',
            field=models.UUIDField(default=uuid_utils.compat.uuid7, editable=False, primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name='publisherpayout',
            name='id',
            field=models.UUIDField(default=uuid_utils.compat.uuid7, editable=False, primary_key=True, serialize=False),
        ),
    ]
