# device_integration/google_views.py

import requests
from django.shortcuts import redirect, get_object_or_404
from django.conf import settings
from urllib.parse import urlencode
from core.models import Participant
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404, render
from django.core.mail import send_mail
from django.http import HttpResponse


def google_auth_start(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly openid email",
        "access_type": "offline",
        "prompt": "consent",
        "state": str(participant.fitbit_auth_token),
        "login_hint": participant.user.email,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(url)


def google_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")

    if error or not code:
        return redirect("/admin/")

    try:
        participant = Participant.objects.get(fitbit_auth_token=state)
    except Participant.DoesNotExist:
        return redirect("/admin/")

    # Exchange code for tokens
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )

    if token_resp.status_code != 200:
        return redirect("/admin/")

    tokens = token_resp.json()

    # Verify Google identity matches participant's email
    userinfo_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    if userinfo_resp.status_code != 200:
        return redirect("/admin/?error=identity_check_failed")

    google_email = userinfo_resp.json().get("email", "").lower()
    if google_email != participant.user.email.lower():
        messages.error(request, f"Wrong Google account. Please authenticate with {participant.user.email}.")
        return redirect(f"/admin/core/participant/{participant.id}/change/")

    participant.google_access_token = tokens["access_token"]
    participant.google_refresh_token = tokens.get("refresh_token", "")
    participant.google_token_expires = timezone.now() + timedelta(seconds=tokens.get("expires_in", 3600))
    participant.save(update_fields=["google_access_token", "google_refresh_token", "google_token_expires"])

    if request.user.is_authenticated and request.user.is_staff:
    	return redirect(f"/admin/core/customuser/{participant.user.id}/change/")
    return render(request, "admin/google_success.html")


def send_auth_link(request, participant_id):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    participant = get_object_or_404(Participant, pk=participant_id)
    
    # Build the OAuth start URL
    auth_url = request.build_absolute_uri(f"/oauth/start/{participant.pk}/")
    
    # Bilingual email body
    subject = "PartnerSteps – Google Health Authorization / Autorisation Google Santé"
    message = (
        "Please follow this link to initiate the Google Health authorization process:\n"
        f"{auth_url}\n\n"
        "Veuillez suivre ce lien pour initier le processus d'autorisation Google Santé :\n"
        f"{auth_url}\n\n"
        "Thank you,\nThe Partner Steps Team\n\n"
        "Merci,\nL'équipe Partner Steps"
    )

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'partnersteprimuhc@gmail.com')
    recipient_email = participant.user.email

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
        messages.success(request, f"Authorization link sent to {recipient_email}.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {str(e)}")

    return redirect(f"/admin/participant/{participant.id}/")
