# device_integration/google_urls.py
from django.urls import path
from . import google_views

urlpatterns = [
    path('callback/', google_views.google_callback, name='google_callback'),
    path('start/<int:participant_id>/', google_views.google_auth_start, name='google_auth_start'),
]