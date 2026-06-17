# core/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.utils.html import format_html, format_html_join
from device_integration.fitbit import fetch_fitbit_data_for_participant
from core.models import Participant, CustomUser
from django.urls import reverse
from django.utils import timezone
import json

# Import your custom forms
from .forms import CustomUserCreationForm, CustomUserChangeForm

# In your admin.py
admin.site.site_header = "PartnerStep"
admin.site.site_title = "PartnerStep"
admin.site.index_title = "Welcome to PartnerStep Administration"


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

    def fetch_fitbit_data_button(self, obj):
        if obj.pk:
            url = reverse("device_integration:fetch_fitbit_data", args=[obj.pk])
            return format_html(
                '<a class="button" href="{}" target="_blank">Fetch Step Data</a>', url
            )
        return "Save participant first"
    fetch_fitbit_data_button.short_description = "Fetch Step Data"

    def authenticate_fitbit_button(self, obj):
        if obj.pk:
            url = reverse("device_integration:fitbit_auth_start", args=[obj.pk])
            return format_html(
                '<a class="button" href="{}" target="_blank">Authenticate Fitbit</a>', url
            )
        return "Save participant first"
    authenticate_fitbit_button.short_description = "Fitbit Authentication"

    def authenticate_google_button(self, obj):
        if obj.pk:
            return format_html(
                '<a class="button" href="/oauth/start/{}/" target="_blank">Authenticate Google</a>', obj.pk
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
        'authenticate_fitbit_button',
        'authenticate_google_button',
        'fetch_fitbit_data_button',
        'calculate_weekly_goals_button',
        'send_notification_button',
    	'fitbit_access_token',         
    	'fitbit_refresh_token',
        'fitbit_token_expires',
        'fitbit_auth_token',
        'device_type',
        'google_access_token',
        'google_refresh_token',
        'google_token_expires',
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
            'fitbit_user_id',
            'fitbit_access_token', 
            'fitbit_refresh_token',
            'fitbit_token_expires',
            'fitbit_auth_token',
            'device_type',
            'google_access_token',
            'google_refresh_token',
            'google_token_expires',
        ]
        
        button_fields = [
            'authenticate_fitbit_button',
            'authenticate_google_button',
            'fetch_fitbit_data_button',
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

###############
# Custom User Admin
class CustomUserAdmin(DefaultUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    
    # Disable the top “Start typing to filter” box
    search_fields = []  # make sure it’s empty

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2', 'is_staff', 'is_active'),
        }),
    )
    
    ordering = ('email',)
    list_display = ('email', 'participant_start_date', 'is_active', 'is_staff')
    #list_filter = ('is_active', 'is_staff', 'is_superuser', 'participant__start_date', 'participant__device_type')
    search_fields = ('email', 'first_name', 'last_name')
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
                        'fields': ('email', 'password1', 'password2', 'is_active'),
                    }),
                )
            return self.add_fieldsets

        # For editing, Managers: email + password only
        if request.user.groups.filter(name='Managers').exists() and not request.user.is_superuser:
            return (
                (None, {
                    'fields': ('email', 'password'),
                }),
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

###############
# Register the custom User admin
admin.site.register(CustomUser, CustomUserAdmin)