# Spled documentation

This folder contains the project architecture and operational docs for the Spled platform.

## Contents

- [System design](system-design.md)
- [Authentication and authorization](authentication-and-authorization.md)
- [User flows and lifecycle](user-flows.md)

## Product summary

Spled is a Django-based construction and field-progress platform for tracking sites, logging evidence, reviewing submissions, and publishing progress to a public portal.

The system combines:

- a custom identity and auth model for organisation-based access
- role-based permission checks per organisation
- append-only evidence records with review and audit trails
- public-facing project visibility for verified organisations
- a mobile-friendly app UI and server-rendered Django templates

## Core areas in the repo

- `accounts/` — custom user model and email-based authentication
- `organisations/` — organisations, memberships, roles, invitations
- `registry/` — sites, evidence entries/photos, reviews, authenticity checks
- `web/` — authenticated user views, public portal, sign-up, team flows
- `audit/` — immutable event logging
- `config/` — Django settings and URL routing
