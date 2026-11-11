from django import forms

from organisations.models import Organisation


class OrgSettingsForm(forms.ModelForm):
    name = forms.CharField(label="Organisation name", max_length=200)
    public_name = forms.CharField(
        label="Public name",
        max_length=200,
        required=False,
        help_text="Shown on the public portal. Leave empty to use the organisation name.",
    )
    stale_after_days = forms.IntegerField(
        label="Flag sites after this many days without evidence",
        min_value=1,
        max_value=365,
        widget=forms.NumberInput(attrs={"min": 1, "max": 365}),
        help_text="Between 1 and 365. Sites quiet for longer show as needing attention.",
    )
    require_onsite_for_status_changes = forms.BooleanField(
        label="Require an on-site location to change a site’s status",
        required=False,
    )
    publish_new_sites_automatically = forms.BooleanField(
        label="Publish new sites automatically",
        required=False,
    )

    class Meta:
        model = Organisation
        fields = [
            "name",
            "public_name",
            "stale_after_days",
            "require_onsite_for_status_changes",
            "publish_new_sites_automatically",
        ]