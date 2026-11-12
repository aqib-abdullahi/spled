from django import forms
from django.contrib.gis.geos import Point

from registry.models import Site

from .boundary_field import BoundaryField


class SiteForm(forms.ModelForm):
    latitude = forms.FloatField(
        min_value=-90, max_value=90, help_text="Decimal degrees, e.g. 9.0765"
    )
    longitude = forms.FloatField(
        min_value=-180, max_value=180, help_text="Decimal degrees, e.g. 7.3986"
    )
    boundary = BoundaryField()

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
        "progress", "latitude", "longitude", "description", "boundary",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.location:
            self.initial["latitude"] = self.instance.location.y
            self.initial["longitude"] = self.instance.location.x
        if self.instance.pk and self.instance.boundary:
            self.initial["boundary"] = self.instance.boundary.geojson

    def clean_progress(self):
        value = self.cleaned_data["progress"]
        if value > 100:
            raise forms.ValidationError("Progress can’t be more than 100%.")
        return value

    def clean(self):
        data = super().clean()
        boundary = data.get("boundary")
        lat, lon = data.get("latitude"), data.get("longitude")
        if boundary is not None and lat is not None and lon is not None:
            if not boundary.contains(Point(lon, lat, srid=4326)):
                raise forms.ValidationError(
                    "The location pin must be inside the boundary. "
                    "Move the pin, or redraw the shape."
                )
        return data

    def save(self, commit=True):
        site = super().save(commit=False)
        site.location = Point(
            self.cleaned_data["longitude"], self.cleaned_data["latitude"], srid=4326
        )
        # Only touch the boundary if the form actually sent it.
        if self.data.get(self.add_prefix("boundary")) is not None:
            site.boundary = self.cleaned_data.get("boundary")
        if commit:
            site.save()
        return site