from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from audit.log import record
from audit.models import AuditEvent
from organisations.models import Invitation, Membership
from organisations.permissions import MANAGE_TEAM, can
from organisations.team import LastAdminError, change_role, remove_member

from .context import get_current_membership
from .team_forms import InviteForm, JoinForm


def _org_or_deny(request):
    membership = get_current_membership(request)
    if not membership:
        return None
    org = membership.organisation
    if not can(request.user, MANAGE_TEAM, org):
        raise PermissionDenied
    return org


def _context(org, form):
    return {
        "active": "team",
        "org": org,
        "form": form,
        "members": Membership.objects.filter(organisation=org)
        .select_related("user")
        .order_by("user__full_name"),
        "invites": Invitation.objects.filter(
            organisation=org, accepted_at__isnull=True, revoked_at__isnull=True
        ).order_by("-created_at"),
        "roles": Membership.Role.choices,
    }


@login_required
def team_page(request):
    org = _org_or_deny(request)
    if org is None:
        return redirect("overview")
    return render(request, "team.html", _context(org, InviteForm(org=org)))


@login_required
@require_POST
def invite_create(request):
    org = _org_or_deny(request)
    if org is None:
        return redirect("overview")
    form = InviteForm(request.POST, org=org)
    if not form.is_valid():
        return render(request, "team.html", _context(org, form))

    email, role = form.cleaned_data["email"], form.cleaned_data["role"]
    try:
        with transaction.atomic():
            invitation, raw = Invitation.create_for(org, email, role, request.user)
            record(
                request.user, org, AuditEvent.Action.MEMBER_INVITED,
                None, email, email=email, role=role,
            )
    except IntegrityError:
        form.add_error("email", "That person already has an open invitation.")
        return render(request, "team.html", _context(org, form))

    link = request.build_absolute_uri(reverse("invite_accept", args=[raw]))
    role_label = dict(Membership.Role.choices)[role]
    send_mail(
        f"You’re invited to join {org.name} on Spled",
        f"{request.user.full_name} invited you to join {org.name} on Spled "
        f"as {role_label}.\n\n"
        f"Open this link to accept. It works once and expires in 7 days:\n{link}\n\n"
        "If you weren’t expecting this, you can ignore this email.",
        None,
        [email],
    )
    messages.success(request, f"Invitation sent to {email}.")
    if settings.DEBUG:
        messages.info(request, f"Development only, the invitation link: {link}")
    return redirect("team")


@login_required
@require_POST
def invite_revoke(request, pk):
    org = _org_or_deny(request)
    if org is None:
        return redirect("overview")
    invitation = get_object_or_404(
        Invitation,
        pk=pk,
        organisation=org,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
    )
    with transaction.atomic():
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at"])
        record(
            request.user, org, AuditEvent.Action.INVITE_REVOKED,
            None, invitation.email, email=invitation.email,
        )
    messages.success(request, f"The invitation to {invitation.email} was revoked.")
    return redirect("team")


@login_required
@require_POST
def member_role(request, pk):
    org = _org_or_deny(request)
    if org is None:
        return redirect("overview")
    member = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, organisation=org
    )
    new_role = request.POST.get("role", "")
    if new_role not in Membership.Role.values:
        messages.error(request, "Choose a role from the list.")
        return redirect("team")
    try:
        with transaction.atomic():
            old = change_role(member, new_role)
            if old != new_role:
                record(
                    request.user, org, AuditEvent.Action.MEMBER_ROLE_CHANGED,
                    None, member.user.email,
                    email=member.user.email, **{"from": old, "to": new_role},
                )
    except LastAdminError:
        messages.error(
            request, "That would leave the organisation without an admin."
        )
    else:
        messages.success(request, f"Updated the role for {member.user.full_name}.")
    return redirect("team")


@login_required
@require_POST
def member_remove(request, pk):
    org = _org_or_deny(request)
    if org is None:
        return redirect("overview")
    member = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, organisation=org
    )
    name, email, role = member.user.full_name, member.user.email, member.role
    try:
        with transaction.atomic():
            remove_member(member)
            record(
                request.user, org, AuditEvent.Action.MEMBER_REMOVED,
                None, email, email=email, role=role,
            )
    except LastAdminError:
        messages.error(
            request, "That would leave the organisation without an admin."
        )
    else:
        messages.success(request, f"{name} was removed from the team.")
    return redirect("team")


def _accept(request, invitation, user):
    org = invitation.organisation
    with transaction.atomic():
        invitation.accept(user)
        record(
            user, org, AuditEvent.Action.MEMBER_JOINED,
            None, user.email, email=user.email, role=invitation.role,
        )
    request.session["org_id"] = org.pk


def invite_accept(request, token):
    invitation = Invitation.lookup(token)
    if invitation is None:
        raise Http404
    org = invitation.organisation
    context = {"inv": invitation, "org": org, "state": invitation.state}
    if invitation.state != "pending":
        return render(request, "invite_accept.html", context)

    user = request.user
    if user.is_authenticated:
        if user.email.lower() != invitation.email:
            context["wrong_account"] = True
            return render(request, "invite_accept.html", context)
        if request.method == "POST":
            _accept(request, invitation, user)
            return redirect("overview")
        context["signed_in_ok"] = True
        return render(request, "invite_accept.html", context)

    if User.objects.filter(email__iexact=invitation.email).exists():
        context["signin_url"] = (
            f"{reverse('signin')}?next={reverse('invite_accept', args=[token])}"
        )
        return render(request, "invite_accept.html", context)

    form = JoinForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            new_user = User.objects.create_user(
                invitation.email,
                form.cleaned_data["password1"],
                full_name=form.cleaned_data["full_name"],
                email_verified_at=timezone.now(),
            )
            _accept(request, invitation, new_user)
        login(request, new_user)
        return redirect("overview")
    context["form"] = form
    return render(request, "invite_accept.html", context)