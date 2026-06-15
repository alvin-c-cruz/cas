# CAS User Management — Full Test Plan

**System:** http://127.0.0.1:5000/  
**Date:** 2026-06-15  
**Tester:** Admin  
**Scope:** User registration, CRUD, role-based access, security

---

## PHASE 0 — Pre-Test Setup

### 0.1 Route Map

| Route | Methods | Who can access |
|-------|---------|----------------|
| `/register` | GET, POST | Public |
| `/login` | GET, POST | Public |
| `/logout` | GET | Logged-in |
| `/select-branch` | GET, POST | Logged-in |
| `/profile` | GET | Logged-in |
| `/profile/change-password` | GET, POST | Logged-in |
| `/users` | GET | Admin, Accountant |
| `/users/create` | GET, POST | Admin, Accountant |
| `/users/<id>/edit` | GET, POST | Admin, Accountant* |
| `/users/<id>/delete` | POST | Admin only |
| `/approved-emails` | GET | Admin only |
| `/approved-emails/add` | GET, POST | Admin only |
| `/approved-emails/<id>/delete` | POST | Admin only |

*Accountant cannot edit users with role=`admin`

### 0.2 Role Matrix

| Action | admin | accountant | staff | viewer |
|--------|-------|------------|-------|--------|
| View user list `/users` | ✓ | ✓ | ✗ | ✗ |
| Create user `/users/create` | ✓ | ✓ | ✗ | ✗ |
| Edit any user | ✓ | ✓ (non-admin only) | ✗ | ✗ |
| Delete user | ✓ | ✗ | ✗ | ✗ |
| Manage approved emails | ✓ | ✗ | ✗ | ✗ |
| View own profile | ✓ | ✓ | ✓ | ✓ |
| Change own password | ✓ | ✓ | ✓ | ✓ |

### 0.3 Registration Behavior (read before testing)

- `/register` is public; submitting creates a user with **role=`viewer`** and **`is_active=False`**
- User **cannot log in** until an admin sets `is_active=True` ("Your account is pending approval" shown)
- If the submitted email matches an `ApprovedEmail` record, that record is marked `is_used=True`
- Verify at start of testing whether an unrecognized email **blocks** registration at form level or just skips the marking step

### 0.4 Setup Steps

| # | Step | Notes |
|---|------|-------|
| S1 | Log in as `admin` | Credentials: `admin` / `ac1123581321` |
| S2 | Navigate to `/approved-emails/add` and add `testuser@example.com` | Required before testing email-approved registration path |
| S3 | Note current user count at `/users` | Baseline for after-test cleanup |
| S4 | Confirm Flask server running at port 5000 | |
| S5 | If using Playwright/automation: `click('#password')` before `fill()` — password field is `readonly` until focused | Known CAS quirk |

---

## PHASE 1 — Functional Testing (Happy Path)

### 1.1 Self-Registration via `/register`

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 1 | Register with **approved email** | All valid fields; email = `testuser@example.com` (added in S2) | User created, `is_active=False`; `ApprovedEmail` record marked `is_used=True` |
| 2 | Register with **non-approved email** | Valid fields; email not in approved list | Note result: either form rejects it OR user created with `is_active=False` |
| 3 | Attempt login with newly registered account (`is_active=False`) | Correct credentials | Blocked: "Your account is pending approval" |
| 4 | Admin activates the new account | Edit user → `is_active=True` | User can now log in |
| 5 | Newly activated user logs in | Correct credentials | Successful login; redirected to branch select |
| 6 | Required fields only | Omit `full_name` if optional | Accept or reject per validation; note result |
| 7 | Password confirmation match | Matching passwords | Account created |
| 8 | Password confirmation mismatch | Different values in password/confirm | Error shown; user NOT created |

### 1.2 Admin-Created User via `/users/create`

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 9 | Create user as `admin` | All valid fields, role=`staff`, assign branch | User created and visible in `/users` list |
| 10 | Create user as `accountant` | Same | User created (accountant has this right) |
| 11 | Assign role=`admin` during create as `accountant` | Set role=`admin` | Note result — should be restricted |
| 12 | Create with no branch assigned | Omit branch selection | User created; confirm whether login is blocked or allowed |

### 1.3 READ — View Users

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 13 | View user list as `admin` | GET `/users` | All users displayed |
| 14 | View user list as `accountant` | Log in as accountant, GET `/users` | Allowed |
| 15 | View user list as `staff` | Log in as staff, GET `/users` | Redirected or 403 |
| 16 | View user list as `viewer` | Log in as viewer, GET `/users` | Redirected or 403 |
| 17 | View own profile | GET `/profile` (any role) | Own details shown |

### 1.4 UPDATE — Edit User (as admin)

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 18 | Edit `full_name` | Change to new value | Updated and reflected |
| 19 | Edit `role` | Change staff → accountant | Updated |
| 20 | Edit `is_active` | Deactivate another user | User blocked from login |
| 21 | Edit book permissions | Toggle any of the 5 flags | Saved and reflected |
| 22 | Edit branch assignment | Add/remove branch | Updated |
| 23 | Set new password via edit | Valid password + confirm | Password changed; old password no longer works |
| 24 | Leave password blank on edit | Submit with empty password fields | Password unchanged (optional field) |
| 25 | Try to edit own `role` | Admin changes own role | Blocked: "You cannot change your own role" |
| 26 | Try to deactivate own account | Admin unchecks own `is_active` | Blocked: "You cannot deactivate your own account" |
| 27 | Try to edit `username` via form | Modify username field value | Field immutable — change ignored or blocked |
| 28 | Try to edit `email` via form | Modify email field value | Field immutable — change ignored or blocked |
| 29 | Cancel edit | Click cancel | No changes saved |

### 1.5 UPDATE — Edit User (as accountant)

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 30 | Accountant edits a `staff` user | Change full_name | Allowed |
| 31 | Accountant edits a `viewer` user | Change role to staff | Allowed |
| 32 | Accountant tries to edit an `admin` user | Navigate to `/users/<admin_id>/edit` | Blocked — accountant cannot edit admin-role users |
| 33 | Accountant tries to assign `admin` role | Set role=admin in edit form | Note result — should be restricted |

### 1.6 Profile Self-Service

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 34 | View own profile (any role) | GET `/profile` | Own details shown; username/email not editable |
| 35 | Change password at `/profile/change-password` | Valid current + new + confirm | Password updated |
| 36 | Change password with wrong current password | Wrong current password | Rejected with error |
| 37 | Change password — new and confirm mismatch | Different new/confirm | Rejected with error |

### 1.7 DELETE

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 38 | Admin deletes another user (non-admin) | POST `/users/<id>/delete` | User removed from list |
| 39 | Delete confirmation prompt | Trigger delete | Custom HTML modal appears (no JS `confirm()`); CSRF token present |
| 40 | Cancel delete | Click cancel on modal | User NOT deleted |
| 41 | Admin tries to delete own account | POST `/users/<current_user_id>/delete` | Blocked: "You cannot delete your own account" |
| 42 | Accountant tries to delete a user | POST `/users/<id>/delete` as accountant | Blocked (delete is admin-only) |
| 43 | Delete last remaining admin | Delete all admins but one, then try to delete the last | **Expected FAIL — no last-admin guard in code; deletion likely succeeds. Note as bug.** |

### 1.8 Approved Emails

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 44 | Admin adds approved email | POST `/approved-emails/add` | Email added to list |
| 45 | Accountant tries to access `/approved-emails` | GET as accountant | Blocked (admin-only inner check) |
| 46 | Delete approved email | POST `/approved-emails/<id>/delete` | Removed from list |

---

## PHASE 2 — Hacker Mindset

### 2.1 Input Validation & Injection

| # | Test Case | Payload | Expected |
|---|-----------|---------|----------|
| 47 | SQL injection — login | `' OR '1'='1' --` in username | Rejected; no bypass |
| 48 | SQL injection — registration | `'; DROP TABLE users; --` in name field | Input sanitized/rejected |
| 49 | XSS — stored | `<script>alert('XSS')</script>` in full_name | Rendered as plain text; script not executed |
| 50 | XSS — reflected | Inject in URL params | Not reflected unescaped |
| 51 | HTML injection | `<h1>Hacked</h1>` in name field | Rendered as plain text |
| 52 | Command injection | `; ls -la` in any input field | Not executed |

### 2.2 Authentication & Authorization

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 53 | Access `/users` without login | Navigate directly | Redirected to `/login` |
| 54 | Access `/users/create` without login | Navigate directly | Redirected to `/login` |
| 55 | Access `/users/<id>/edit` without login | Navigate directly | Redirected to `/login` |
| 56 | `staff` accesses `/users` | Login as staff, navigate | Blocked — redirect or 403 |
| 57 | `viewer` accesses `/users/create` | Login as viewer, navigate | Blocked |
| 58 | `accountant` accesses `/users/<admin_id>/edit` | Navigate to an admin user's edit URL | Blocked — "cannot edit admin users" |
| 59 | `accountant` sends DELETE request to `/users/<id>/delete` | POST as accountant | Blocked (admin-only) |
| 60 | `accountant` accesses `/approved-emails` | GET as accountant | Blocked (admin-only inner check) |
| 61 | Session after logout | Log out, press browser Back | Cannot access protected pages; redirected to login |
| 62 | Reuse session token post-logout | Copy session cookie before logout; reuse after | Session invalidated |

### 2.3 IDOR (Insecure Direct Object Reference)

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 63 | View another user's edit page as `staff` | `/users/2/edit` as staff | Blocked |
| 64 | Edit another user's data as `viewer` | POST to `/users/2/edit` as viewer | Blocked |
| 65 | Delete another user as `accountant` | POST to `/users/2/delete` as accountant | Blocked |
| 66 | Sequential ID probing (unauthenticated) | Try `/users/1`, `/users/2` as anonymous | Redirected to login each time |
| 67 | IDOR on approved emails | POST `/approved-emails/1/delete` as accountant | Blocked |

### 2.4 Input Boundary Testing

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 68 | Empty form submission | Submit `/register` with no data | Validation errors on all required fields |
| 69 | Whitespace-only inputs | `"   "` in username, full_name | Treated as empty; rejected |
| 70 | Extremely long username | 10,000 characters | Rejected or truncated gracefully |
| 71 | Extremely long password | 10,000 characters | Rejected or handled without crash |
| 72 | Special characters in full_name | `!@#$%^&*()` | Handled without crash; stored safely |
| 73 | Invalid email format | `notanemail`, `@no.com` | Validation error |
| 74 | Duplicate username | Register same username twice | Error: username already taken |
| 75 | Duplicate email | Register same email twice | Error: email already registered |
| 76 | Weak password | `123`, `aaa` | Rejected if strength policy enforced; note result |
| 77 | Numeric-only username | `12345` | Accepted or rejected per policy; note result |
| 78 | Unicode in full_name | `José María Ñoño` | Stored and displayed correctly |

### 2.5 CSRF

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 79 | CSRF token present on registration form | Inspect `/register` page source | Hidden `csrf_token` field present |
| 80 | CSRF token present on all state-changing forms | Inspect create, edit, delete, change-password | Token present on all |
| 81 | Submit without CSRF token | Remove token from POST request | Request rejected (400 or 403) |
| 82 | CSRF cookie HttpOnly flag | Check `document.cookie` in browser console | **FAIL (KNOWN — BUG-SEC-03): cookie visible via JS** |

### 2.6 Rate Limiting & Brute Force

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 83 | Login brute force | 20+ failed login attempts | **FAIL (KNOWN — BUG-SEC-01): no rate limiting implemented** |
| 84 | Registration spam | Register 10+ accounts rapidly | **FAIL (KNOWN — BUG-SEC-01): same gap** |
| 85 | Rapid delete requests | Send multiple DELETE POSTs quickly | Handled gracefully; no crash or double-delete |

### 2.7 Business Logic

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 86 | Delete own admin account | Admin POSTs to own `/users/<id>/delete` | Blocked: "You cannot delete your own account" |
| 87 | Delete the last remaining admin | Create scenario with only 1 admin; try to delete | **FAIL (KNOWN — no last-admin guard): deletion succeeds. Note as bug.** |
| 88 | Admin demotes own role via edit | Admin sets own role to `viewer` | Blocked: "You cannot change your own role" |
| 89 | Admin deactivates own account | Admin unchecks own `is_active` | Blocked: "You cannot deactivate your own account" |
| 90 | Register with `role=admin` in form body | Intercept POST, add `role=admin` to payload | Role not assigned — default `viewer` applied |
| 91 | Mass assignment — `is_active=true` in POST | Add `is_active=true` to registration POST | Ignored — new users always start inactive |
| 92 | Activate account without admin | Registered user tries to set own `is_active` | Not possible — no self-activation route |
| 93 | Honeypot fields | Fill `fake_username` and `fake_password` before submitting login | Bot detection triggered |
| 94 | Accountant assigns `admin` role to a user | Edit user, set role=`admin` as accountant | Note result — should be restricted |
| 95 | Create user with no branch | Admin creates user, omits branch | Note whether login is blocked or allowed |

---

## PHASE 3 — Known Expected Failures

Record these as **FAIL (KNOWN BUG)** — do not investigate during this session:

| Test # | Bug ID | Description |
|--------|--------|-------------|
| 82 | BUG-SEC-03 | CSRF cookie not HttpOnly — visible via `document.cookie` |
| 83, 84 | BUG-SEC-01 | No rate limiting on login or registration |
| — | BUG-SEC-02 | Failed login returns HTTP 200 instead of 401 |
| 43, 87 | (no ID) | No last-admin guard — last admin can be deleted |
| — | BUG-11 | Stale JS validation: "This field is required" persists even when field is filled; form still submits correctly |
| — | BUG-06 | Register page shows hardcoded company name regardless of AppSettings |

---

## PHASE 4 — Summary & Reporting

After each test record one of:

| Status | Meaning |
|--------|---------|
| **PASS** | Behaves as expected |
| **FAIL** | Unexpected behavior or vulnerability |
| **FAIL (KNOWN BUG)** | Pre-documented; skip investigation |
| **INFO** | Noteworthy observation (policy ambiguity, UX gap) |

Severity for new FAILs:

| Level | Meaning |
|-------|---------|
| 🔴 Critical | Auth bypass, SQLi, data exposure, privilege escalation |
| 🟠 High | Stored XSS, IDOR, CSRF missing, last-admin deletion |
| 🟡 Medium | Missing validation, rate limiting absent, HTTP 200 on auth failure |
| 🟢 Low | UI/UX issues, minor input handling, cosmetic |

---

## Testing Order

Run phases in this sequence to avoid state contamination:

1. **Phase 0** — setup, add approved email, confirm routes
2. **Phase 1.1–1.2** — registration and admin-create (builds users needed for later tests)
3. **Phase 1.3** — read tests (all roles)
4. **Phase 1.6** — profile self-service (each role)
5. **Phase 1.4–1.5** — edit tests (admin then accountant)
6. **Phase 1.8** — approved emails
7. **Phase 2.1–2.6** — security tests (use a throwaway test user)
8. **Phase 2.7** — business logic last (tests #87 and #43 touch admin session state; run with a dedicated test admin account)
9. **Phase 1.7** — delete tests last (cleans up test users created in Phase 1)
