# device_integration/urls.py

from django.urls import path
from . import views
from .views import fetch_fitbit_data
from .views import fetch_fitbit_data, fetch_step_data

app_name = "device_integration"

urlpatterns = [
    path("start/<int:participant_id>/", views.fitbit_auth_start, name="fitbit_auth_start"),
    path("callback/", views.fitbit_callback, name="fitbit_callback"),
    path("fetch/<int:participant_id>/", fetch_fitbit_data, name="fetch_fitbit_data"),
    path("fetch-smart/<int:participant_id>/", fetch_step_data, name="fetch_step_data"),
]
