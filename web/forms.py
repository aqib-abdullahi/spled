from django import forms

from .site_form import SiteForm  # noqa: F401
from django.contrib.gis.geos import Point

from registry.models import EvidenceEntry, Site
from registry.photos import MAX_PHOTOS, PhotoError, process_image


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            result = [single(d, initial) for d in data]
        else:
            result = [single(data, initial)]
        return [f for f in result if f]


class EvidenceForm(forms.Form):
    kind = forms.ChoiceField(
        choices=[
            (EvidenceEntry.Kind.NOTE, "Note"),
            (EvidenceEntry.Kind.CHECK_IN, "Field check-in"),
            (EvidenceEntry.Kind.PHOTO, "Photo"),
        ]
    )
    body = forms.CharField(
        label="What happened?", widget=forms.Textarea(attrs={"rows": 4})
    )
    tags = forms.CharField(
        required=False, help_text="Separate with commas, e.g. inspection, delivery"
    )
    # Filled in only by the "Use my current location" button. Nobody can type these.
    latitude = forms.FloatField(
        required=False, min_value=-90, max_value=90, widget=forms.HiddenInput
    )
    longitude = forms.FloatField(
        required=False, min_value=-180, max_value=180, widget=forms.HiddenInput
    )
    accuracy = forms.FloatField(
        required=False, min_value=0, max_value=100000, widget=forms.HiddenInput
    )
    fix_age = forms.FloatField(
        required=False, min_value=0, max_value=604800, widget=forms.HiddenInput
    )
    new_status = forms.ChoiceField(
        required=False,
        label="Also update the site’s status",
        choices=[("", "Keep the current status")] + list(Site.Status.choices),
    )

    photos = MultipleFileField(
        required=False,
        label="Photos",
        widget=MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )

    def clean_photos(self):
        files = self.cleaned_data.get("photos") or []
        if len(files) > MAX_PHOTOS:
            raise forms.ValidationError(f"Add at most {MAX_PHOTOS} photos at a time.")
        processed = []
        for f in files:
            try:
                processed.append(process_image(f))
            except PhotoError as e:
                raise forms.ValidationError(f"{f.name}: {e}")
        return processed

    def __init__(self, *args, site, allow_status=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.site = site
        if not allow_status:
            del self.fields["new_status"]

    def clean_tags(self):
        tags = []
        for part in self.cleaned_data["tags"].split(","):
            tag = part.strip().lower()[:40]
            if tag and tag not in tags:
                tags.append(tag)
        if len(tags) > 10:
            raise forms.ValidationError("Use at most 10 tags.")
        return tags

    def clean(self):
        data = super().clean()
        lat, lon = data.get("latitude"), data.get("longitude")
        if (lat is None) != (lon is None):
            raise forms.ValidationError(
                "Give both latitude and longitude, or leave both empty."
            )
        if lat is not None and (data.get("accuracy") is None or data.get("fix_age") is None):
            raise forms.ValidationError(
                "Your device’s location wasn’t captured. Use the “Use my current location” "
                "button; locations can’t be typed in."
            )
        if data.get("kind") == EvidenceEntry.Kind.CHECK_IN and lat is None:
            raise forms.ValidationError("A field check-in needs a location.")
        if (
            data.get("kind") == EvidenceEntry.Kind.PHOTO
            and not data.get("photos")
            and "photos" not in self.errors
        ):
            raise forms.ValidationError("A photo entry needs at least one photo.")
        if data.get("new_status") == self.site.status:
            data["new_status"] = ""
        return data

class AmendForm(forms.Form):
    body = forms.CharField(
        label="Corrected text", widget=forms.Textarea(attrs={"rows": 4})
    )
    reason = forms.CharField(
        label="Reason for the correction",
        max_length=200,
        help_text="This is shown next to the correction.",
    )
