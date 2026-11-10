from django import forms
from django.contrib.gis.geos import Point

from registry.models import EvidenceEntry, Site


class SiteForm(forms.ModelForm):
    latitude = forms.FloatField(
        min_value=-90, max_value=90, help_text="Decimal degrees, e.g. 9.0765"
    )
    longitude = forms.FloatField(
        min_value=-180, max_value=180, help_text="Decimal degrees, e.g. 7.3986"
    )

    class Meta:
        model = Site
        fields = [
            "name", "kind", "status", "owner_name",
            "target_date", "progress", "description",
        ]
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    field_order = [
        "name", "kind", "status", "owner_name", "target_date",
        "progress", "latitude", "longitude", "description",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.location:
            self.initial["latitude"] = self.instance.location.y
            self.initial["longitude"] = self.instance.location.x

    def clean_progress(self):
        value = self.cleaned_data["progress"]
        if value > 100:
            raise forms.ValidationError("Progress can’t be more than 100%.")
        return value

    def save(self, commit=True):
        site = super().save(commit=False)
        site.location = Point(
            self.cleaned_data["longitude"], self.cleaned_data["latitude"], srid=4326
        )
        if commit:
            site.save()
        return site

class EvidenceForm(forms.Form):
    kind = forms.ChoiceField(
        choices=[
            (EvidenceEntry.Kind.NOTE, "Note"),
            (EvidenceEntry.Kind.CHECK_IN, "Field check-in"),
        ]
    )
    body = forms.CharField(
        label="What happened?", widget=forms.Textarea(attrs={"rows": 4})
    )
    tags = forms.CharField(
        required=False, help_text="Separate with commas, e.g. inspection, delivery"
    )
    latitude = forms.FloatField(required=False, min_value=-90, max_value=90)
    longitude = forms.FloatField(required=False, min_value=-180, max_value=180)
    new_status = forms.ChoiceField(
        required=False,
        label="Also update the site’s status",
        choices=[("", "Keep the current status")] + list(Site.Status.choices),
    )

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
        if data.get("kind") == EvidenceEntry.Kind.CHECK_IN and lat is None:
            raise forms.ValidationError("A field check-in needs a location.")
        if data.get("new_status") == self.site.status:
            data["new_status"] = ""
        return data