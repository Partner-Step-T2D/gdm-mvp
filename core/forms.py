# core/forms.py
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.utils.translation import gettext_lazy as _
from .models import CustomUser

class CustomUserCreationForm(forms.ModelForm):
    """
    A form for creating new users. Includes all the required
    fields, plus a repeated password.
    """
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Password confirmation', widget=forms.PasswordInput)
    backup_email = forms.EmailField(required=False, label="Backup Email (optional)")

    class Meta:
        model = CustomUser
        fields = ('email', 'backup_email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Show the actual password requirements up front instead of only
        # surfacing them after a failed submission.
        self.fields["password1"].help_text = password_validation.password_validators_help_text_html()

    def clean_password2(self):
        # Check that the two password entries match
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def _post_clean(self):
        super()._post_clean()
        # Enforce AUTH_PASSWORD_VALIDATORS (min length, common password, etc.)
        # self.instance is populated with the submitted data by this point,
        # so UserAttributeSimilarityValidator can compare against the email.
        password = self.cleaned_data.get("password2")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error("password2", error)

    def save(self, commit=True):
        # Save the provided password in hashed format
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user

class CustomUserChangeForm(forms.ModelForm):
    """
    A form for updating users. Includes all the fields on
    the user, but replaces the password field with admin's
    password hash display field.
    """
    password = ReadOnlyPasswordHashField(
        label=_("Password"),
        help_text=_(
            'Raw passwords are not stored, so there is no way to see this '
            'user\'s password, but you can change the password using '
            '<a href="../password/">this form</a>.'
        ),
    )
    backup_email = forms.EmailField(required=False, label="Backup Email (optional)")
    
    class Meta:
        model = CustomUser
        fields = ('email', 'password', 'backup_email', 'is_active', 'is_staff', 'is_superuser')