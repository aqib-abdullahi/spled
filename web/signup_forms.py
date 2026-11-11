from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from accounts.models import User
from organisations.models import Organisation


class SignInForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "That email and password don’t match.",
        "unverified": "Verify your email first. We sent you a link when you signed up.",
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError as exc:
            if exc.code != "invalid_login":
                raise
            email = self.cleaned_data.get("username")
            password = self.cleaned_data.get("password")
            if email and password:
                user = User.objects.filter(
                    email__iexact=email, is_active=False, email_verified_at__isnull=True
                ).first()
                # Only say "verify first" to someone who knows the password.
                if user and user.check_password(password):
                    raise forms.ValidationError(
                        self.error_messages["unverified"], code="unverified"
                    )
            raise


class SignUpForm(forms.Form):
    full_name = forms.CharField(
        label="Full name", max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="Work email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    organisation_name = forms.CharField(
        label="Organisation", max_length=200,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
    )
    kind = forms.ChoiceField(label="We are a…", choices=Organisation.Kind.choices)
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_password1(self):
        password = self.cleaned_data["password1"]
        validate_password(password)
        return password


class ResendForm(forms.Form):
    email = forms.EmailField(
        label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()