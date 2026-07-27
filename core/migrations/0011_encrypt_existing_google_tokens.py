from django.db import migrations


def encrypt_existing_tokens(apps, schema_editor):
    Participant = apps.get_model("core", "Participant")
    for obj in Participant.objects.exclude(google_access_token__isnull=True).exclude(google_access_token=""):
        obj.save(update_fields=["google_access_token"])
    for obj in Participant.objects.exclude(google_refresh_token__isnull=True).exclude(google_refresh_token=""):
        obj.save(update_fields=["google_refresh_token"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_alter_participant_google_access_token_and_more'),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_tokens, noop_reverse),
    ]