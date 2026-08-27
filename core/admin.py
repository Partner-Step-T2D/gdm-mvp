# core/admin.py
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.utils.html import format_html, format_html_join
from core.models import Participant, CustomUser
from django.urls import reverse
from django.utils import timezone
from urllib.parse import quote
from base64 import b32encode
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django_otp.conf import settings as otp_settings
from django_otp.plugins.otp_totp.admin import TOTPDeviceAdmin as BaseTOTPDeviceAdmin
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_static.admin import StaticDeviceAdmin as DefaultStaticDeviceAdmin
from django.middleware.csrf import get_token
import json

# Import your custom forms
from .forms import CustomUserCreationForm, CustomUserChangeForm

from django_otp.admin import OTPAdminSite
admin.site.__class__ = OTPAdminSite

admin.site.site_header = "Partner Step T2D"
admin.site.site_title = "Partner Step T2D"
admin.site.index_title = "Welcome to Partner Step T2D Administration"


### Restrict Managers to only see their own OTP devices
class OwnDeviceOnlyMixin:
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

    def has_view_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser:
            return obj.user_id == request.user.id
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser:
            return obj.user_id == request.user.id
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser:
            return obj.user_id == request.user.id
        return super().has_delete_permission(request, obj)


class RestrictedTOTPDeviceAdmin(OwnDeviceOnlyMixin, BaseTOTPDeviceAdmin):
    """Own-device-only TOTP admin, including the manual-key config view
    for setting up authenticators that can't scan a QR code."""

    def config_view(self, request, pk):
        if otp_settings.OTP_ADMIN_HIDE_SENSITIVE_DATA:
            raise PermissionDenied()
        device = TOTPDevice.objects.get(pk=pk)
        if not self.has_view_or_change_permission(request, device):
            raise PermissionDenied()
        # Base32 secret, grouped into 4-character blocks for easy manual typing.
        raw_secret = b32encode(device.bin_key).decode()
        manual_key = raw_secret
        context = dict(
            self.admin_site.each_context(request),
            device=device,
            manual_key=manual_key,
        )
        return TemplateResponse(request, 'otp_totp/admin/config.html', context)


class RestrictedStaticDeviceAdmin(OwnDeviceOnlyMixin, DefaultStaticDeviceAdmin):
    pass


admin.site.unregister(TOTPDevice)
admin.site.register(TOTPDevice, RestrictedTOTPDeviceAdmin)
admin.site.unregister(StaticDevice)
admin.site.register(StaticDevice, RestrictedStaticDeviceAdmin)


###############
# Mixin with shared button methods
class ParticipantButtonMixin:
    def calculate_weekly_goals_button(self, obj):
        if obj.pk:
            url = reverse("goals:calculate_weekly_goals", args=[obj.pk])
            return format_html(
                '<a class="button" href="{}" target="_blank">Calculate Weekly Goals</a>', url
            )
        return "Save participant first"

    def fetch_step_data_button(self, obj):
        if obj.pk:
            url = reverse("device_integration:fetch_step_data", args=[obj.pk])
            return format_html(
                '<a class="button" href="{}" target="_blank">Fetch Step Data</a>', url
            )
        return "Save participant first"
    fetch_step_data_button.short_description = "Fetch Step Data"
    
    def authenticate_google_button(self, obj):
        if obj.pk:
            request = getattr(self, 'request', None)
            if not request:
                return "-"
            email = obj.user.email
            next_param = quote(request.path)
            token = get_token(request)
            return format_html(
                '<button type="button" class="button" onclick="'
                'if(confirm(\'Are you sure you want to send the authorization email to {}?\')){{'
                'var f=document.createElement(\'form\');f.method=\'POST\';f.action=\'/oauth/send-auth-link/{}/\';'
                'var c=document.createElement(\'input\');c.type=\'hidden\';c.name=\'csrfmiddlewaretoken\';c.value=\'{}\';f.appendChild(c);'
                'var n=document.createElement(\'input\');n.type=\'hidden\';n.name=\'next\';n.value=\'{}\';f.appendChild(n);'
                'document.body.appendChild(f);f.submit();'
                '}}">Send Authorization Link</button>',
                email, obj.pk, token, next_param
            )
        return "Save participant first"
    authenticate_google_button.short_description = "Google Authentication"

    def send_notification_button(self, obj):
        """Button to send goal notification - only enabled if recent goals exist"""
        if not obj.pk:
            return "Save participant first"

        from datetime import date, timedelta

        # Check if there's a goal from today or yesterday
        today = date.today()
        yesterday = today - timedelta(days=1)

        today_key = today.strftime("%Y-%m-%d")
        yesterday_key = yesterday.strftime("%Y-%m-%d")

        targets = obj.targets or {}
        recent_goal = None
        goal_date = None

        # Check today first, then yesterday
        if today_key in targets and targets[today_key].get('new_target'):
            recent_goal = targets[today_key]
            goal_date = today_key
        elif yesterday_key in targets and targets[yesterday_key].get('new_target'):
            recent_goal = targets[yesterday_key]
            goal_date = yesterday_key

        if recent_goal:
            url = reverse("goals:send_notification", args=[obj.pk])
            return format_html(
                '<a class="button" href="{}" target="_blank">Send Notification ({})</a>',
                url, goal_date
        )
        else:
            return format_html(
                '<span style="color: #666; font-style: italic;">No recent goals to notify about</span>'
            )
    send_notification_button.short_description = "Send Goal Notification"


###############
# Inline for Participant
class ParticipantInline(ParticipantButtonMixin, admin.StackedInline):
    model = Participant
    can_delete = False
    extra = 0
    max_num = 1
    min_num = 1

    readonly_fields = [
        'daily_steps_display',
        'targets_display',
        'authenticate_google_button',
        'fetch_step_data_button',
        'calculate_weekly_goals_button',
        'send_notification_button',
        'device_type',
        'google_access_token',
        'google_refresh_token',
        'google_token_expires',
        'delete_google_tokens_button',
    ]

    def get_readonly_fields(self, request, obj=None):
        # Save the request object for use in display methods
        self.request = request
        return super().get_readonly_fields(request, obj)

    def render_json(self, value):
        """Format JSON data into readable HTML lists"""
        if not value:
            return "-"
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except Exception:
            return value

        if isinstance(data, list):
            # reverse list for Managers
            data = list(reversed(data))
            return format_html_join(
                "", "<li>{}: {} steps</li>",
                ((d.get("date") or d.get("dateTime"), d.get("value")) for d in data)
            )
        elif isinstance(data, dict):
            # sort by date descending
            items = sorted(data.items(), key=lambda x: x[0], reverse=True)
            return format_html_join(
                "", "<li>{}: increase {}, new target {}, avg {}</li>",
                ((date, info.get("increase"), info.get("new_target"), info.get("average_steps")) for date, info in items)
            )
        return value

    def get_fields(self, request, obj=None):
        # Customize visible fields based on user permissions
        base_fields = [
            'start_date',
            'language',
            'treatment_arm',
        ]

        # Data fields - different for Managers vs Superusers
        if request.user.groups.filter(name="Managers").exists() and not request.user.is_superuser:
            # Managers see read-only display versions
            data_fields = ['daily_steps_display', 'targets_display']
        else:
            # Superusers see editable versions
            data_fields = ['daily_steps', 'targets']

        # Technical fields (always readonly)
        tech_fields = [
            'google_access_token',
            'google_refresh_token',
            'google_token_expires',
            'delete_google_tokens_button',
            'device_type',
        ]

        button_fields = [
            'authenticate_google_button',
            'fetch_step_data_button',
            'calculate_weekly_goals_button',
            'send_notification_button',
        ]
        return base_fields + data_fields + button_fields + tech_fields

    def daily_steps_display(self, obj):
        """Display formatted daily steps for Managers"""
        if getattr(self, 'request', None) and self.request.user.groups.filter(name="Managers").exists() \
            and not self.request.user.is_superuser:
            formatted = self.render_json(obj.daily_steps)
            return format_html("<ul style='margin:0 0 0 1em;'>{}</ul>", formatted)
        else:
            return obj.daily_steps

    def targets_display(self, obj):
        """Display formatted targets for Managers"""
        if getattr(self, 'request', None) and self.request.user.groups.filter(name="Managers").exists() \
            and not self.request.user.is_superuser:
            formatted = self.render_json(obj.targets)
            return format_html("<ul style='margin:0 0 0 1em;'>{}</ul>", formatted)
        else:
            return obj.targets
        
    def delete_google_tokens_button(self, obj):
        if obj.pk and (obj.google_access_token or obj.google_refresh_token):
            request = getattr(self, 'request', None)
            if not request:
                return "-"
            email = obj.user.email
            next_param = quote(request.path)
            token = get_token(request)
            return format_html(
                '<button type="button" class="button" style="background:#ba2121;" onclick="'
                'if(confirm(\'This will revoke Google Health access for {} and delete the stored tokens. Continue?\')){{'
                'var f=document.createElement(\'form\');f.method=\'POST\';f.action=\'/oauth/delete-tokens/{}/\';'
                'var c=document.createElement(\'input\');c.type=\'hidden\';c.name=\'csrfmiddlewaretoken\';c.value=\'{}\';f.appendChild(c);'
                'var n=document.createElement(\'input\');n.type=\'hidden\';n.name=\'next\';n.value=\'{}\';f.appendChild(n);'
                'document.body.appendChild(f);f.submit();'
                '}}">Delete Google access tokens</button>',
                email, obj.pk, token, next_param
            )
        elif obj.pk:
            return format_html('<span style="color: #666; font-style: italic;">No tokens to delete</span>')
        return "Save participant first"
    delete_google_tokens_button.short_description = "Delete Google access tokens"

###############
# Custom User Admin
class CustomUserAdmin(DefaultUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    # Disable the top "Start typing to filter" box

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('backup_email',)}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'backup_email', 'is_staff', 'is_active'),
        }),
    )

    ordering = ('email',)
    list_display = ('email', 'participant_start_date', 'is_active', 'is_staff')
    #list_filter = ('is_active', 'is_staff', 'is_superuser', 'participant__start_date', 'participant__device_type')
    search_fields = ('email',)
    inlines = [ParticipantInline]

    def participant_email(self, obj):
        try:
            return obj.participant.email
        except:
            return "-"
    participant_email.short_description = "Email"

    def participant_start_date(self, obj):
        try:
            return obj.participant.start_date
        except:
            return "-"
    participant_start_date.short_description = "Start Date"

    def get_fieldsets(self, request, obj=None):
        # For the add form (obj is None), always use add_fieldsets
        if obj is None:
            if request.user.groups.filter(name='Managers').exists() and not request.user.is_superuser:
                return (
                    (None, {
                        'classes': ('wide',),
                        'fields': ('email', 'password1', 'password2', 'is_active',),
                }),
            )
            return self.add_fieldsets

        # For editing, Managers: email + password only
        if request.user.groups.filter(name='Managers').exists() and not request.user.is_superuser:
            return (
                (None, {
                    'fields': ('email', 'password')}),
                    ('Personal info', {'fields': ('backup_email',)}),
                    ('Permissions', {'fields': ('is_active',)}),
            )

        # Superusers and others: full fieldsets
        return self.fieldsets

    def get_form(self, request, obj=None, **kwargs):
        """
        Use CustomUserCreationForm when adding, CustomUserChangeForm when editing.
        """
        defaults = {}
        if obj is None:
            defaults['form'] = self.add_form
        else:
            defaults['form'] = self.form
        defaults.update(kwargs)
        return super().get_form(request, obj, **defaults)
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and hasattr(form, 'generated_password'):
            self._generated_password_message = (
            f"Temporary password for {obj.email}: {form.generated_password} "
            "(valid 48 hours; user must change it on first login)."
        )
    
    def response_add(self, request, obj, post_url_continue=None):
        msg = getattr(self, '_generated_password_message', None)
        if msg:
            messages.success(request, msg)
        return super().response_add(request, obj, post_url_continue)

###############
# Register the custom User admin
admin.site.register(CustomUser, CustomUserAdmin)