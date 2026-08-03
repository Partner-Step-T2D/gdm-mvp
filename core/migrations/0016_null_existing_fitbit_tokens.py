from django.db import migrations


def null_existing_fitbit_tokens(apps, schema_editor):
    """
    Fitbit OAuth is no longer used to pull step data for any active
    participant (superseded by the Google integration). Rather than encrypt
    dead credentials at rest, clear them out entirely so there's nothing to
    leak. This nulls the live tokens on core_participant and the token
    values (but not the audit rows themselves) in
    core_participant_fitbit_token_history, preserving the timestamps/participant
    linkage of the rotation history without retaining the actual secrets.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE core_participant "
            "SET fitbit_access_token = NULL, fitbit_refresh_token = NULL "
            "WHERE fitbit_access_token IS NOT NULL OR fitbit_refresh_token IS NOT NULL"
        )

        cursor.execute(
            "UPDATE core_participant_fitbit_token_history "
            "SET old_refresh_token = NULL, new_refresh_token = NULL "
            "WHERE old_refresh_token IS NOT NULL OR new_refresh_token IS NOT NULL"
        )


def noop_reverse(apps, schema_editor):
    # Nulled tokens can't be un-nulled; this migration is intentionally
    # irreversible in practice.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_alter_participant_fitbit_tokens"),
    ]

    operations = [
        migrations.RunPython(null_existing_fitbit_tokens, noop_reverse),
    ]
