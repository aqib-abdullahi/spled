from django import forms
from django.contrib.auth.password_validation import validate_password

from organisations.models import Invitation, Membership


class InviteForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(
        choices=Membership.Role.choices, initial=Membership.Role.VIEWER
    )

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        self.org = org

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Membership.objects.filter(
            organisation=self.org, user__email__iexact=email
        ).exists():
            raise forms.ValidationError("That person is already on the team.")
        open_invite = Invitation.objects.filter(
            organisation=self.org,
            email=email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
        ).first()
        if open_invite and not open_invite.is_expired:
            raise forms.ValidationError(
                "That person already has an open invitation. "
                "Revoke it first if you want to send a new one."
            )
        return email


class JoinForm(forms.Form):
    full_name = forms.CharField(label="Full name", max_length=150)
    password1 = forms.CharField(
        label="Create a password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_password1(self):
        password = self.cleaned_data["password1"]
        validate_password(password)
        return password