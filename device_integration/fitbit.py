# device_integration/fitbit.py

from django.utils import timezone

###############
# Helpers
#
# NOTE: Fitbit's own OAuth flow (token refresh/exchange, direct step fetch)
# has been removed - Fitbit device data is now pulled via Google Health
# instead (see device_integration/google_health.py). _log_status_flag stays
# here because the fetch_fitbit_data management command still imports it
# directly for status bookkeeping on both paths.
def _log_status_flag(participant, key, error_message=None):
    """Helper to set or clear status flags for Fitbit operations."""
    # Get a mutable copy of status_flags to ensure Django detects the change
    flags = participant.status_flags.copy() if participant.status_flags else {}
    
    if error_message:
        flags[key] = True
        flags[f"{key}_last_error"] = error_message
        flags[f"{key}_last_error_time"] = timezone.now().isoformat()
    else:
        flags[key] = False
        flags.pop(f"{key}_last_error", None)
        flags.pop(f"{key}_last_error_time", None)
    
    # Reassign to trigger JSONField update detection
    participant.status_flags = flags
    participant.save(update_fields=["status_flags"])

###############
# Add device account
def add_device_account_for_participant(participant, device_type):
    from core.models import DeviceAccount
    if DeviceAccount.objects.filter(participant=participant, device_type=device_type).exists():
        return None, f"{device_type} account already exists for this participant."
    device = DeviceAccount(participant=participant, device_type=device_type)
    device.save()
    return device, None