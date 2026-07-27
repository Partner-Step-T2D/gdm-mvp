from django.db import migrations
from django.conf import settings
from cryptography.fernet import Fernet, MultiFernet


def encrypt_existing_tokens(apps, schema_editor):
    fernet = MultiFernet([Fernet(k.encode()) for k in settings.FIELD_ENCRYPTION_KEYS])

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, google_access_token, google_refresh_token FROM core_participant"
        )
        rows = cursor.fetchall()

        for row_id, access_token, refresh_token in rows:
            updates = {}
            if access_token:
                updates["google_access_token"] = fernet.encrypt(access_token.encode()).decode()
            if refresh_token:
                updates["google_refresh_token"] = fernet.encrypt(refresh_token.encode()).decode()

            if updates:
                set_clause = ", ".join(f"{col} = %s" for col in updates)
                cursor.execute(
                    f"UPDATE core_participant SET {set_clause} WHERE id = %s",
                    list(updates.values()) + [row_id],
                )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_alter_participant_google_access_token_and_more"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_tokens, noop_reverse),
    ]