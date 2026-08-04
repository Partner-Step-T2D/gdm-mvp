# device_integration/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from core.models import Participant
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required

@staff_member_required
def fetch_step_data(request, participant_id):
    """Admin button fetch — pulls step data via Google Health."""
    from device_integration.google_health import fetch_google_data_for_participant

    participant = get_object_or_404(Participant, pk=participant_id)

    if not participant.google_access_token:
        return render(request, "admin/popup_result.html", {
            "success": False,
            "error": "No Google access token on file for this participant.",
        })

    result, status = fetch_google_data_for_participant(participant_id)
    source = "Google Health"

    if status == 200:
        context = {
            "success": True,
            "fitbit_id": participant.fitbit_user_id,
            "message": f"{source}: Fetched {len(result.get('steps', []))} days of steps."
        }
    else:
        context = {
            "success": False,
            "error": result.get("error", "Unknown error")
        }
    return render(request, "admin/popup_result.html", context)