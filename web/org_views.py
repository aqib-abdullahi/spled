from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render

from audit.log import record
from audit.models import AuditEvent
from organisations.models import Organisation
from organisations.permissions import MANAGE_ORGANISATION, can

from .context import get_current_membership
from .org_forms import OrgSettingsForm


@login_required
def org_settings(request):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    if not can(request.user, MANAGE_ORGANISATION, org):
        raise PermissionDenied

    # The form edits a separate copy, so a rejected form never changes what we show.
    form = OrgSettingsForm(request.POST or None, instance=Organisation.objects.get(pk=org.pk))
    if request.method == "POST" and form.is_valid():
        changed = [str(form[name].label) for name in form.changed_data]
        if changed:
            with transaction.atomic():
                form.save()
                record(
                    request.user, org, AuditEvent.Action.ORG_SETTINGS_CHANGED,
                    None, form.instance.name, fields=changed,
                )
            messages.success(request, "Settings saved.")
        else:
            messages.info(request, "Nothing changed.")
        return redirect("org_settings")

    return render(request, "org_settings.html", {
        "active": "settings", "org": org, "form": form,
    })