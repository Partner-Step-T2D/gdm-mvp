# core/fields.py

from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django.conf import settings
from django.db import models


def _get_fernet():
    keys = [Fernet(k.encode()) for k in settings.FIELD_ENCRYPTION_KEYS]
    if not keys:
        raise ValueError(
            "FIELD_ENCRYPTION_KEYS is empty — set it in settings_local.py "
            "or the FIELD_ENCRYPTION_KEYS env var."
        )
    return MultiFernet(keys)


class EncryptedTextField(models.TextField):
    """A TextField that transparently encrypts/decrypts its value at rest."""

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        if isinstance(value, bytes):
            value = value.decode()
        return _get_fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Value isn't encrypted yet (e.g. pre-migration plaintext row).
            # Remove this fallback once the data migration has run.
            return value