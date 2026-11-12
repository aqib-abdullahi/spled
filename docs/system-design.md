# System design

## 1. Product purpose

Spled is a field evidence and progress tracking system for organisations managing sites or infrastructure assets. The application supports:

- creating and managing sites
- logging evidence such as notes, status updates, and photos
- assigning project roles to team members
- reviewing contractor-submitted evidence
- publishing verified project information externally
- maintaining audit trails for accountability

The architecture is intentionally server-centric and uses Django templates for a traditional web app rather than a front-end SPA.

## 2. Architectural layers

### Presentation layer

- Django templates under `templates/`
- CSS and UI behaviour under `static/css/`
- server-rendered pages for app screens and public pages

### Application layer

- `web/` handles authenticated app pages, public portal pages, onboarding, invites, and form flows
- `organisations/` owns organisation membership, role logic, and invitation lifecycle
- `registry/` owns core operational data: sites, evidence, reviews, and photo handling
- `audit/` stores immutable audit events
- `accounts/` owns the custom user identity model

### Data layer

- PostgreSQL via Django ORM with GIS support
- `Site.location` and `Site.boundary` use GeoDjango fields
- `EvidenceEntry.location` and `distance_to_site_m` help determine on-site verification
- append-only constraints and hash checks preserve evidence integrity

## 3. Domain model

### User

The custom user model is in `accounts/models.py`.

- `email` is the unique login identifier
- `full_name` is required
- `is_active` controls whether the account can log in
- `is_staff` is reserved for Django admin access
- `date_joined` and `email_verified_at` track onboarding status

### Organisation

`Organisation` contains the operating context for a group of sites and team members.

Key fields:

- `name`, `slug`, `kind`
- `verification` state: pending, verified, more info, rejected
- `stale_after_days`
- `publish_new_sites_automatically`

### Membership and roles

Each user can belong to an organisation through one `Membership` record.

Roles are defined as:

- admin
- editor
- field
- contractor
- owner
- viewer

That membership and role model is the primary access-control boundary for the application.

### Site

A site represents a physical location / work area.

Key fields:

- `organisation`
- `name`, `kind`, `status`
- `owner_name`, `target_date`
- `location` and optional `boundary`
- `progress`, `progress_from_milestones`
- `is_public`, `archived_at`

### Evidence and review

Evidence is stored in `EvidenceEntry` and includes:

- `site`
- `author`
- `kind` (note, photo, check-in, status)
- `body`, `tags`
- `captured_at`, `created_at`
- `location`, `distance_to_site_m`, `verified_on_site`
- `needs_review`, `content_hash`, `previous_hash`

The registry model uses chained hashes and append-only semantics to prevent edits to existing evidence records. If a correction is needed, the project creates a new amendment record instead of mutating the original.

### Audit log

Audit events are stored in `audit/models.py` and record actions such as:

- site creation or edit
- membership changes
- invitations issued or revoked
- review decisions
- evidence amendments

These records are intentionally protected from direct modification.

## 4. Request flow and platform behaviour

### Public portal

The public pages are mounted in `web/urls.py` and serve:

- home
- project list
- project detail
- static media/photo access

Public visibility is gated by organisation verification and per-site `is_public` setting.

### Authenticated app

The main app area is under `/app/` and includes:

- overview dashboard
- site listing and creation
- site detail and evidence timeline
- review queue
- audit log
- organisation settings
- team management

### Review and validation pipeline

Evidence may require review depending on role. Contractors are treated specially so their submissions are not treated as fully counted until approved or not required.

This is enforced in `organisations/permissions.py` and model-layer logic around evidence counting.

## 5. Security and correctness model

Several design choices increase trust in the system:

- custom user model with email-based login
- organisation-scoped membership instead of global admin-only access
- access checks via `can(user, action, org)`
- `login_required` on protected views
- `PermissionDenied` for unauthorized actions
- immutable evidence model and audit log
- protected admin actions for changing or deleting audit/review/evidence records

## 6. Core files to understand the system

- `config/settings.py` — Django app config, auth settings, login redirects
- `config/urls.py` — top-level route wiring
- `web/urls.py` — user app routes and public portal routes
- `accounts/models.py` — custom user model
- `organisations/models.py` — org, membership, invitations
- `organisations/permissions.py` — access matrix
- `registry/models.py` — sites, evidence, hashing, review logic
- `web/views.py` — main authenticated flows
- `web/team_views.py` — invites and role management
- `web/signup_views.py` — email registration and verification

## 7. Notable implementation choices

- The app uses a classic Django server-rendered pattern rather than React or a separate API layer.
- Organisation membership is the main security boundary.
- Public project pages are intentionally separate from internal app pages.
- Evidence is treated as an append-only operational record, not a mutable document.
- Audit events protect operational accountability and help trace who changed what.
