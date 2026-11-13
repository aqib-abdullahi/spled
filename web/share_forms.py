from django import forms

from sharing.models import EXPIRY_DAYS


class ShareForm(forms.Form):
    label = forms.CharField(
        label="Label", max_length=100,
        help_text="Who it’s for, for example “Investor update, Q4”.",
    )
    days = forms.TypedChoiceField(
        label="Expires after", coerce=int, initial=30,
        choices=[(d, f"{d} days") for d in EXPIRY_DAYS],
    )
    include_photos = forms.BooleanField(label="Include photos", required=False, initial=True)
    include_milestones = forms.BooleanField(
        label="Include milestones", required=False, initial=True
    )
    password = forms.CharField(
        label="Password (optional)", required=False, strip=False,
        min_length=8, max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 8 characters. Without a password, anyone with the link can open it.",
    )