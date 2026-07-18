# Fix unexpected CAS session logout (BUG-PA-SESSION-UNEXPECTED-LOGOUT)

**Date:** 2026-07-18
**Severity:** Medium (UX/trust gap — no data loss, but disruptive during active use; affects all 5 live clients)
**Status:** Design approved, pending implementation

## Problem

Reported by Lea Rose Samonte-Matias (Zhiyuan's Chief Accountant) via the owner: the
live PythonAnywhere-hosted CAS session logs her out unexpectedly during normal use —
not a deliberate logout, and not simply closing the browser.

## Investigation (live, evidence-based — not guessed)

Static analysis first ruled out several candidates: not PA-specific (reproduced
locally too, per owner), not the 1-hour config timeout (happens on a much shorter
scale in some reports), not machine/tab sleep, no client-side idle-timer JS exists,
the dev server's auto-reloader is hard-disabled (`use_reloader=False`), and
`SECRET_KEY` is a fixed value in `.env` (stable across any process restart).

A scripted local repro (25 minutes idle, machine awake, single account) did not
reproduce it. Pulling Zhiyuan's live PythonAnywhere `server.log` and `error.log` via
the PA Files API (read-only) surfaced a concrete, confirmed incident from earlier the
same day (times below converted from the log's UTC to PHT, +8h):

- **11:29 PHT** — last confirmed authenticated action (`GET /staff-management`, 200).
- **~2h gap**, nothing logged (tab idle or closed).
- **13:27 PHT** — `GET /accounts-payable` → immediately redirected to
  `/login?next=/accounts-payable`. The session was already dead by this point — no
  click or action triggered it, it was simply gone on the next request.
- **~2h10m gap** — the resulting stale `/login` page sits open, untouched.
- **15:37:18 PHT** — submitting that stale login form crashes with an **unhandled
  500**: `flask_wtf.csrf.CSRFError: The CSRF session token is missing.` (confirmed
  twice in today's log, not a one-off).
- **15:37:35 PHT** — page reload, login succeeds normally.

Root cause, confirmed by reading the code (not inferred):

1. **`session.permanent` is never set anywhere in `app/`** (verified: no matches for
   `.permanent` in the whole codebase). `config.py`'s `PERMANENT_SESSION_LIFETIME`
   (currently `3600`, 1 hour) therefore never takes effect — Flask only applies that
   lifetime to a session marked `permanent`. The actual cookie carries no explicit
   expiry and instead rides on the browser's own undefined "session cookie"
   lifetime, so users get deauthenticated at unpredictable moments that don't match
   any configured, intentional timeout.
2. **No `CSRFError` handler is registered.** When a request arrives on an
   already-dead session (for whatever reason it died), Flask-WTF's CSRF check fails
   with `ValidationError("The CSRF session token is missing.")`, which propagates as
   an unhandled 500 instead of a graceful redirect — compounding a plain session
   expiry into a crash.

## Fix

### 1. Make sessions permanent, with a 12-hour lifetime

- `app/users/views.py::login()` — add `session.permanent = True` alongside the
  existing `login_user(user, remember=form.remember_me.data)` call.
- `config.py` — change the `PERMANENT_SESSION_LIFETIME` default from `3600` to
  `43200` (12 hours), covering a full workday including breaks while still expiring
  overnight.
- `.env.example` — update the documented default/comment to match (`43200  # 12
  hours in seconds`).
- `REMEMBER_COOKIE_DURATION` (7 days) is untouched — "remember me" stays a separate,
  longer-lived opt-in cookie; this change only affects the plain session lifetime.

### 2. Graceful CSRF-error handling

- `app/__init__.py::create_app` — register `@app.errorhandler(CSRFError)` (import
  `from flask_wtf.csrf import CSRFError`) alongside the existing 404/403/500/`Exception`
  handlers. On a CSRF error: clear any stale session, flash `"Your session has
  expired. Please log in again."` (category `info`, matching the existing
  `login_message` convention), and redirect to `users.login`.
- This is a general hardening independent of fix #1 — it protects against *any*
  cause of session loss (expiry, cookie corruption, etc.), not just the specific
  scenario above.

## Testing (TDD)

1. Integration test: after a successful `POST /login`, assert `session.permanent is
   True`.
2. Config test (or assertion alongside an existing config test): confirm
   `PERMANENT_SESSION_LIFETIME` resolves to `43200` seconds by default.
3. Integration test: a POST to a CSRF-protected route with no CSRF session token
   present returns a redirect to `/login` with the expected flash message, instead of
   a 500 — this directly regresses the confirmed production crash.
4. Full existing login/session/CSRF test suites must remain green unchanged — this
   is additive (new permanence + a new error handler), not a change to any existing
   happy path.

No migration, no model change — config plus two small code additions. The
migration-verify-on-real-DB-copy gate does not apply.

## Rollout

This lives in the shared `projects/cas` codebase, so once merged to `main` it
applies to **all 5 live clients** (RIC, alvinccruz, philgen, bccruz, zhiyuan) on
their next `/deploy`, not only Zhiyuan. Each client's own `.env` may already set
`PERMANENT_SESSION_LIFETIME` explicitly — check and update it per client during
deploy so the new 12-hour default actually takes effect rather than being silently
overridden by a stale per-client value.

Per the project's standing convention: implement on its own branch + worktree in
`projects/cas`, never directly on `main`.

## Scope / non-goals

- No change to `REMEMBER_COOKIE_DURATION` or the "remember me" checkbox behavior.
- No change to `WTF_CSRF_TIME_LIMIT` (stays `None` — token itself still doesn't
  expire by time; this fix addresses the *session* dying under it, not the token).
- No attempt to diagnose or fix *why* a given session cookie is lost before its
  12-hour expiry (e.g. browser-specific cookie eviction) — out of scope; the fix
  makes the intended lifetime explicit and makes any session loss fail gracefully,
  which is the actionable part.
