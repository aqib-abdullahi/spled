from django import forms
from django.contrib.gis.geos import Point

from registry.models import Site


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