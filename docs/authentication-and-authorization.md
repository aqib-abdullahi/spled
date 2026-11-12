# Authentication and authorization

## 1. Authentication model

Authentication is handled by Django's auth system, but the project replaces the default user model with a custom one.

The custom user model is declared in `config/settings.py`:

- `AUTH_USER_MODEL = "accounts.User"`
- `LOGIN_URL = "signin"`
- `LOGIN_REDIRECT_URL = "overview"`
- `LOGOUT_REDIRECT_URL = "signin"`

The user model in `accounts/models.py` uses:

- `email` as the login field (`USERNAME_FIELD = "email"`)
- password hashing via Django's default password management
- `is_active` to allow or block login
- `is_staff` only for admin dashboard access

## 2. Sign-up and verification flow

The sign-up flow is implemented in `web/signup_views.py`.

1. User submits sign-up form.
2. New user is created as inactive.
3. A new organisation is created automatically for that user.
4. The user is assigned the `admin` role in that organisation.
5. Verification email is sent.
6. User clicks the link to verify email.
7. `is_active` becomes `True` and `email_verified_at` is stored.

This means every new organisation begins with an admin user who owns the initial setup.

## 3. Login flow

Login is wired in `web/urls.py` through `django.contrib.auth.views.LoginView`.

Important settings:

- template: `sign_in.html`
- custom form: `SignInForm`
- `redirect_authenticated_user=True`

Unauthenticated users are redirected to the sign-in screen when they hit protected routes.

## 4. Organisation-based authorization

Authorization is not managed by global Django permissions alone. It is modelled around organisation membership.

The key concept is `Membership`:

- user belongs to an organisation
- that membership has a `role`
- the role gates which actions are allowed

The core permission helper lives in `organisations/permissions.py`.

```python
role_in(user, organisation)
can(user, action, organisation)
needs_review(user, organisation)
```

This is the main access-control layer used by views and templates.

## 5. Roles and permissions matrix

The permission matrix is centered on a single dictionary:

```python
PERMISSIONS = {
    VIEW_SITES: ALL_ROLES,
    LOG_EVIDENCE: {Role.ADMIN, Role.EDITOR, Role.FIELD, Role.CONTRACTOR},
    APPROVE_ENTRIES: {Role.ADMIN, Role.EDITOR},
    EDIT_SITES: {Role.ADMIN, Role.EDITOR},
    AMEND_ENTRY: {Role.ADMIN, Role.EDITOR},
    SIGN_OFF: {Role.ADMIN, Role.EDITOR, Role.OWNER},
    PUBLISH: {Role.ADMIN, Role.EDITOR},
    CREATE_SHARE_LINKS: {Role.ADMIN, Role.EDITOR, Role.OWNER},
    MANAGE_TEAM: {Role.ADMIN},
    MANAGE_ORGANISATION: {Role.ADMIN},
}
```

### Role behaviour summary

- `admin` — full organisation control and team management
- `editor` — can edit and approve core site/evidence operations
- `field` — can log evidence on site
- `contractor` — can log evidence, but it may require review before counting
- `owner` — wider publishing/sign-off access
- `viewer` — read-only access

## 6. How views enforce access

Protected pages use `@login_required` and then inspect the current organisation membership.

Examples:

- `site_create` checks `can(user, EDIT_SITES, org)`
- `site_detail` checks membership and exposes action flags to the template
- `team_page` requires `MANAGE_TEAM`
- `review_queue` and `review_decide` rely on approval permissions

Where access is denied, the app raises `PermissionDenied` rather than silently proceeding.

## 7. Invitation flow and onboarding

Team membership is expanded through invitations in `organisations/models.py` and `web/team_views.py`.

Flow:

1. Admin invites a user by email.
2. Invitation is created with a signed token and expiry.
3. Invite email includes a link.
4. User accepts the invite or signs in to match the email.
5. A `Membership` is created and the user is added to the organisation.

This keeps org membership outside of a static Django group model and inside a domain-specific lifecycle.

## 8. Public access model

Public pages are not general guest access to all data. Visibility is limited by:

- whether the user is authenticated in the app
- whether the site is marked `is_public`
- whether the organisation has `verification == VERIFIED`

This is enforced in the site/public portal logic and is a key part of the operational trust model.

## 9. Security notes

Important patterns used in this project:

- `login_required` is used before business logic
- organisation membership is checked before data access
- permission checks happen at the view layer and in domain logic
- audit/history is maintained to help review privileged actions
- evidence is append-only and not mutable after creation

This gives the app a strong domain-specific authorization model without overly relying on generic Django admin permissions.
