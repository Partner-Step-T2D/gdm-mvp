# core/middleware.py

from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth import logout

from django.utils import timezone

class ForcePasswordChangeMiddleware:
    """
    Forces users with must_change_password=True to change their password
    before accessing anything else. If their temporary password has expired
    without being changed, the account is deactivated.
    """
    EXEMPT_PATHS = (
        '/admin/password_change/',
        '/admin/logout/',
        '/admin/login/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and getattr(user, 'must_change_password', False):
            if user.password_expires_at and timezone.now() > user.password_expires_at:
                user.is_active = False
                user.save(update_fields=['is_active'])
                from django.contrib.auth import logout
                logout(request)
                return redirect('/admin/login/?error=temp_password_expired')

            if not any(request.path.startswith(p) for p in self.EXEMPT_PATHS):
                return redirect('/admin/password_change/')

        return self.get_response(request)
        
class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(), payment=(), usb=()",
        )
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
        return response