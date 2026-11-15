from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from organisations.permissions import (
    EXPORT_REPORTS,
    MANAGE_ORGANISATION,
    MANAGE_TEAM,
    can,
)

from .context import get_current_membership


def _card(title, text, url_name, icon):
    return {"title": title, "text": text, "url": reverse(url_name), "icon": icon}


@login_required
def settings_hub(request):
    membership = get_current_membership(request)
    account_cards = [
        _card("Profile", "Your name, time zone and password.", "profile", "user"),
        _card("Security", "Two-step verification and backup codes.", "account_security", "shield"),
    ]
    org_cards = []
    org = None
    if membership:
        org = membership.organisation
        user = request.user
        if can(user, MANAGE_ORGANISATION, org):
            org_cards.append(_card(
                "Organisation",
                "Public name, quiet-site threshold, on-site rule and auto-publishing.",
                "org_settings", "building-2",
            ))
        if can(user, MANAGE_TEAM, org):
            org_cards.append(_card(
                "Team", "Invite people, change roles and remove members.", "team", "users",
            ))
        if can(user, MANAGE_ORGANISATION, org):
            org_cards.append(_card(
                "Audit log", "A record of every change made in your organisation.",
                "audit_log", "clipboard-list",
            ))
        if can(user, EXPORT_REPORTS, org):
            org_cards.append(_card(
                "Reports", "Portfolio CSV and printable site reports.", "reports", "file-text",
            ))
    return render(request, "settings_hub.html", {
        "active": "settings",
        "membership": membership,
        "org": org,
        "account_cards": account_cards,
        "org_cards": org_cards,
    })