# device_integration/urls.py

from django.urls import path
from .views import fetch_step_data

app_name = "device_integration"

urlpatterns = [
    path("fetch-smart/<int:participant_id>/", fetch_step_data, name="fetch_step_data"),
]
