# device_integration/google_urls.py
from django.urls import path
from . import google_views

urlpatterns = [
    path('callback/', google_views.google_callback, name='google_callback'),
    path('start/<str:token>/', google_views.google_auth_start, name='google_auth_start'),
    path('send-auth-link/<int:participant_id>/', google_views.send_auth_link, name='send_auth_link'),
    path('delete-tokens/<int:participant_id>/', google_views.delete_google_tokens, name='delete_google_tokens'),
]
