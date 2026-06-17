# core/models.py

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.conf import settings
from django.core.validators import MinLengthValidator, RegexValidator
import uuid

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
            
        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    objects = CustomUserManager() 
    
class Participant(models.Model):
    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('fr', 'Français'),
    ]
    
    TREATMENT_ARM_CHOICES = [
        (0, 'Control'),
        (1, 'Intervention'),
    ]
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start_date = models.DateField()
    treatment_arm = models.IntegerField(
        choices=TREATMENT_ARM_CHOICES,
        help_text="Treatment arm assignment: 0=Control, 1=Intervention"
    )
    daily_steps = models.JSONField(default=list, blank=True)
    targets = models.JSONField(default=dict, blank=True)
    device_sync_status = models.JSONField(default=dict, blank=True)
    
    language = models.CharField(
        max_length=2, 
        choices=LANGUAGE_CHOICES, 
        default='en',
        verbose_name='Language'
    )
    	
    message_history = models.JSONField(default=list, blank=True, help_text="History of messages sent to participant")
    
    device_type = models.CharField(
        max_length=50,
        default=getattr(settings, 'DEFAULT_DEVICE_TYPE', 'fitbit')
    )
    fitbit_user_id = models.CharField(
   		max_length=6,
    	blank=True,
    	null=False,
    	validators=[
        	RegexValidator(
            	regex='^[A-Za-z0-9]{6}$',
            	message='Fitbit User ID must be exactly 6 alphanumeric characters',
        	)
    	],
    	help_text="Required: Participant's Fitbit User ID (6 characters, found in Fitbit app: You > Edit Profile)"
	)

    fitbit_access_token = models.TextField(null=True, blank=True)
    fitbit_refresh_token = models.TextField(null=True, blank=True)
    fitbit_token_expires = models.DateTimeField(null=True, blank=True)
    fitbit_auth_token = models.UUIDField(default=uuid.uuid4, unique=True)
    
    google_access_token = models.TextField(null=True, blank=True)
    google_refresh_token = models.TextField(null=True, blank=True)
    google_token_expires = models.DateTimeField(null=True, blank=True)
    
    # New: Status flags for error/success tracking (Fitbit and general process)
    status_flags = models.JSONField(default=dict, blank=True, help_text="Flexible status and error flags for sync, auth, etc.")

    def __str__(self):
        return f"{self.user.email} ({self.get_language_display()})"
    
    @property
    def email(self):
        return self.user.email