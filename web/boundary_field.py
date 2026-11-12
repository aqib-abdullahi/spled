from django import forms
from django.core.exceptions import ValidationError

from registry.geo import parse_boundary


class BoundaryField(forms.CharField):
    """A hidden field carrying drawn GeoJSON. Cleans to a Polygon, or None."""

    widget = forms.HiddenInput

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("label", "Boundary")
        super().__init__(**kwargs)

    def to_python(self, value):
        try:
            return parse_boundary(value)
        except ValueError as exc:
            raise ValidationError(str(exc))

    def clean(self, value):
        return self.to_python(value)

    def has_changed(self, initial, data):
        if data is None:  # the form didn't send it at all
            return False

        def parse(value):
            try:
                return parse_boundary(value)
            except ValueError:
                return "invalid"

        before, after = parse(initial), parse(data)
        if isinstance(before, str) or isinstance(after, str):
            return True
        if before is None and after is None:
            return False
        if before is None or after is None:
            return True
        return not before.equals_exact(after, 1e-6)