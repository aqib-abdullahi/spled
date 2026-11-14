import re
import zoneinfo

from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError

from accounts.models import User

PHONE = re.compile(r"^[0-9+()\-\s]{0,30}$")


def timezone_choices():
    names = sorted(
        n for n in zoneinfo.available_timezones()
        if ("/" in n and not n.startswith("Etc/")) or n == "UTC"
    )
    return [(n, n.replace("_", " ")) for n in names]


class ProfileForm(forms.ModelForm):
    time_zone = forms.ChoiceField(label="Time zone")

    class Meta:
        model = User
        fields = ["full_name", "phone", "time_zone"]
        labels = {"full_name": "Full name", "phone": "Phone (optional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["time_zone"].choices = timezone_choices()

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if not name:
            raise ValidationError("Enter your name.")
        return name

    def clean_phone(self):
        phone = " ".join((self.cleaned_data.get("phone") or "").split())
        if not PHONE.match(phone):
            raise ValidationError("Use only digits, spaces and + - ( ).")
        return phone


class ChangePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Current password"
        self.fields["new_password1"].label = "New password"
        self.fields["new_password1"].help_text = "At least 10 characters."
        self.fields["new_password2"].label = "Confirm new password"

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get("new_password1")
        if new and not self.errors and self.user.check_password(new):
            self.add_error("new_password1", "Choose a different password from your current one.")
        return cleaned