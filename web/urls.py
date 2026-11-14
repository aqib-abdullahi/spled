from django.contrib.auth import views as auth_views
from .twofactor_views import TwoFactorLoginView
from django.urls import path

from registry import photo_views
from . import public_views, views
from .signup_forms import SignInForm


urlpatterns = [
    path("", public_views.public_home, name="home"),
    path("projects/", public_views.public_projects, name="projects"),
    path("projects/<int:pk>/", public_views.public_project, name="project"),
    path("photos/<int:pk>/<str:variant>/", photo_views.photo_file, name="photo"),
    path(
        "signin/",
        TwoFactorLoginView.as_view(
            template_name="sign_in.html", redirect_authenticated_user=True,
            authentication_form=SignInForm,
        ),
        name="signin",
    ),
    path("signout/", auth_views.LogoutView.as_view(), name="signout"),
    path("app/", views.overview, name="overview"),
    path("app/sites/", views.sites_list, name="sites"),
    path("app/sites/new/", views.site_create, name="site_new"),
    path("app/sites/<int:pk>/edit/", views.site_edit, name="site_edit"),
    path("app/sites/<int:pk>/", views.site_detail, name="site_detail"),
    path("app/sites/<int:pk>/evidence/new/", views.evidence_new, name="evidence_new"),
    path("app/sites/<int:pk>/publish/", views.site_publish, name="site_publish"),
    path("app/review/", views.review_queue, name="review"),
    path("app/audit/", views.audit_log, name="audit_log"),
    path("app/review/<int:pk>/", views.review_decide, name="review_decide"),
    path("app/evidence/<int:pk>/amend/", views.evidence_amend, name="evidence_amend"),
]

from . import team_views  # noqa: E402

urlpatterns += [
    path("app/team/", team_views.team_page, name="team"),
    path("app/team/invite/", team_views.invite_create, name="invite_create"),
    path("app/team/invite/<int:pk>/revoke/", team_views.invite_revoke, name="invite_revoke"),
    path("app/team/members/<int:pk>/role/", team_views.member_role, name="member_role"),
    path("app/team/members/<int:pk>/remove/", team_views.member_remove, name="member_remove"),
    path("invite/<str:token>/", team_views.invite_accept, name="invite_accept"),
]

from django.urls import reverse_lazy

from . import signup_views

urlpatterns += [
    path("signup/", signup_views.sign_up, name="signup"),
    path("signup/sent/", signup_views.signup_sent, name="signup_sent"),
    path("signup/verify/<str:token>/", signup_views.verify_email, name="verify_email"),
    path("signup/resend/", signup_views.resend_verification, name="resend_verification"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="password_reset_form.html",
            email_template_name="emails/password_reset_email.txt",
            subject_template_name="emails/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(template_name="password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="password_reset_complete.html"),
        name="password_reset_complete",
    ),
]

from . import milestone_views  # noqa: E402

urlpatterns += [
    path("app/sites/<int:pk>/milestones/", milestone_views.milestones_page, name="milestones"),
    path("app/sites/<int:pk>/milestones/add/", milestone_views.milestone_add, name="milestone_add"),
    path("app/sites/<int:pk>/milestones/settings/", milestone_views.milestone_settings, name="milestone_settings"),
    path("app/sites/<int:pk>/milestones/<int:mpk>/toggle/", milestone_views.milestone_toggle, name="milestone_toggle"),
    path("app/sites/<int:pk>/milestones/<int:mpk>/edit/", milestone_views.milestone_edit, name="milestone_edit"),
    path("app/sites/<int:pk>/milestones/<int:mpk>/move/", milestone_views.milestone_move, name="milestone_move"),
    path("app/sites/<int:pk>/milestones/<int:mpk>/delete/", milestone_views.milestone_delete, name="milestone_delete"),
]


from . import org_views  # noqa: E402

urlpatterns += [
    path("app/organisation/", org_views.org_settings, name="org_settings"),
]


from . import map_views  # noqa: E402

urlpatterns += [
    path("map/", map_views.public_map, name="public_map"),
    path("map/data/", map_views.public_map_data, name="public_map_data"),
]


from . import report_views  # noqa: E402

urlpatterns += [
    path("app/reports/", report_views.reports_page, name="reports"),
    path("app/reports/site/", report_views.report_site, name="report_site"),
    path("app/reports/site/download/", report_views.report_site_download, name="report_site_download"),
    path("app/reports/portfolio.csv", report_views.report_portfolio_csv, name="report_portfolio_csv"),
]


from . import share_views  # noqa: E402

urlpatterns += [
    path("app/sites/<int:pk>/share/", share_views.share_links, name="share_links"),
    path("app/sites/<int:pk>/share/create/", share_views.share_create, name="share_create"),
    path("app/sites/<int:pk>/share/<int:lpk>/revoke/", share_views.share_revoke, name="share_revoke"),
    path("s/<str:token>/", share_views.share_view, name="share_view"),
    path("s/<str:token>/photos/<int:pk>/<str:variant>/", share_views.share_photo, name="share_photo"),
]


from . import twofactor_views  # noqa: E402

urlpatterns += [
    path("signin/verify/", twofactor_views.verify_signin, name="signin_verify"),
    path("app/security/", twofactor_views.account_security, name="account_security"),
    path("app/security/2fa/setup/", twofactor_views.twofactor_setup, name="twofactor_setup"),
    path("app/security/2fa/disable/", twofactor_views.twofactor_disable, name="twofactor_disable"),
    path("app/security/2fa/codes/", twofactor_views.twofactor_new_codes, name="twofactor_codes"),
]


from . import profile_views  # noqa: E402

urlpatterns += [
    path("app/profile/", profile_views.profile_page, name="profile"),
    path("app/profile/save/", profile_views.profile_save, name="profile_save"),
    path("app/profile/password/", profile_views.profile_password, name="profile_password"),
]

# Step 37: staff-wide map
from . import staff_map_views  # noqa: E402

urlpatterns += [
    path("app/map/", staff_map_views.staff_map, name="staff_map"),
    path("app/map/data/", staff_map_views.staff_map_data, name="staff_map_data"),
]
