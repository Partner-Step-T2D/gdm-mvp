# device_integration/google_health.py

import requests
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404
from core.models import Participant


def refresh_google_tokens(participant):
    if participant.google_token_expires and participant.google_token_expires > timezone.now():
        return participant.google_access_token

    from django.conf import settings
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": participant.google_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise Exception(f"Failed to refresh Google token: {resp.text}")

    tokens = resp.json()
    participant.google_access_token = tokens["access_token"]
    participant.google_token_expires = timezone.now() + timedelta(seconds=tokens.get("expires_in", 3600))
    participant.save(update_fields=["google_access_token", "google_token_expires"])
    return participant.google_access_token


def fetch_google_data_for_participant(participant_id, force_refetch=False):
    participant = get_object_or_404(Participant, pk=participant_id)
    print(f"--- Fetching Google Health data for participant {participant_id} ---")

    if not participant.google_access_token:
        return {"error": "No Google access token"}, 400

    try:
        daily_steps = participant.daily_steps or []
        if force_refetch or not daily_steps:
            start_fetch_date = participant.start_date - timedelta(days=7)
        else:
            last_date = max(day["date"] for day in daily_steps)
            start_fetch_date = datetime.strptime(last_date, "%Y-%m-%d").date()

        end_fetch_date = min(timezone.now().date(), participant.start_date + timedelta(days=365))

        if start_fetch_date > end_fetch_date:
            return {"steps": daily_steps, "message": "Already up to date"}, 200

        access_token = refresh_google_tokens(participant)

        url = "https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Fetch in 90-day chunks (API limit)
        all_new_steps = []
        chunk_start = start_fetch_date
        while chunk_start < end_fetch_date:
            chunk_end = min(chunk_start + timedelta(days=89), end_fetch_date)

            body = {
                "range": {
                    "start": {
                        "date": {"year": chunk_start.year, "month": chunk_start.month, "day": chunk_start.day},
                        "time": {"hours": 0, "minutes": 0}
                    },
                    "end": {
                        "date": {"year": chunk_end.year, "month": chunk_end.month, "day": chunk_end.day},
                        "time": {"hours": 23, "minutes": 59}
                    }
                }
            }

            resp = requests.post(url, headers=headers, json=body, timeout=10)
            print(f"DEBUG chunk {chunk_start} to {chunk_end}: status={resp.status_code} body={resp.text[:500]}")

            if resp.status_code != 200:
                return {"error": resp.text}, resp.status_code

            for point in resp.json().get("rollupDataPoints", []):
                civil_start = point.get("civilStartTime", {}).get("date", {})
                date_str = f"{civil_start.get('year')}-{str(civil_start.get('month')).zfill(2)}-{str(civil_start.get('day')).zfill(2)}"
                value = point.get("steps", {}).get("countSum", 0)
                if date_str and int(value) > 0:
                    all_new_steps.append({"date": date_str, "value": int(value)})

            chunk_start = chunk_end + timedelta(days=1)

        steps_dict = {day["date"]: day for day in daily_steps}
        for day in all_new_steps:
            steps_dict[day["date"]] = day
        merged_steps = sorted(steps_dict.values(), key=lambda x: x["date"])
        participant.daily_steps = merged_steps
        participant.save(update_fields=["daily_steps"])
        print(f"Fetched and merged {len(merged_steps)} days of step data.")

        return {"steps": merged_steps}, 200

    except requests.RequestException as e:
        logging.error(f"Google Health API request failed: {e}")
        return {"error": "Failed to fetch data from Google Health"}, 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return {"error": "Internal server error"}, 500
