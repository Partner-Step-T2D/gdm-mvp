# Generated for encrypting Fitbit tokens at rest

import core.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_participant_google_oauth_state_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='participant',
            name='fitbit_access_token',
            field=core.fields.EncryptedTextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='participant',
            name='fitbit_refresh_token',
            field=core.fields.EncryptedTextField(blank=True, null=True),
        ),
    ]