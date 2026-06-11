# CAS Manual Test Runbook

## 1. Purpose & How to Use

This runbook is a **repeatable full acceptance test** of CAS, executed manually in a browser against a **clean starting-company state** (fresh database, one admin, one branch, no master data, no transactions).

How to use it:

1. Confirm every item in **Preconditions** before starting. Do not skip.
2. Execute the scenarios **in order** — later scenarios depend on data and role changes made by earlier ones.
3. Each scenario has a **Goal**, numbered **Steps** (concrete browser actions with real URLs), an **Expected Result**, **Pass Criteria** checkboxes (every DB write includes an audit-log check), a short **UX Review** checklist, and a **Workflow Clarity** verdict.
4. Scenarios marked **⏸** are **User-Approval Gates**: pause, present the proposed data to the product owner, and wait for sign-off before writing anything to the database (see section 4).
5. If a bug is found, log it in the **Bug Log** (section 9). A cross-module bug **stops the run** — fix it first, re-run the affected scenario, then continue.
6. At the end, fill in the **Workflow Clarity Summary** and add a row to the **Test Run Log**.
7. On the first run, fill in the **Appendix: Test Data** tables so later runs reuse the same data.

> **Code-reality notes:** Where the codebase currently differs from the intended behavior, scenarios carry a **Note (code reality)** box. Treat divergences as findings — record them in the Bug Log rather than silently adjusting expectations.

## 2. Test Run Log

| Date | Tester | Result | Notes |
|------|--------|--------|-------|
| 2026-06-11 | | In progress | First run |

## 3. Preconditions

Clean-state database checklist (verify via DB browser or `flask shell` before starting):

- [ ] `users` = 1 (the seeded `admin` user)
- [ ] `branches` = 1 (Main Branch)
- [ ] `user_branches` = 1 (admin assigned to Main Branch)
- [ ] `app_settings` rows present (seeded keys: `company_name`, `company_tin`, `company_address`, `fiscal_year_start`, `environment`)
- [ ] `accounts` = 0
- [ ] `vat_categories` = 0
- [ ] `withholding_tax` = 0
- [ ] `vendors` = 0
- [ ] `purchase_bills` = 0
- [ ] Dev server running at `http://127.0.0.1:5000` (`python flask_app.py`)
- [ ] Admin credentials available: username `admin` — the password is known to the team and is **never written in this document**

> **Important sequencing fact:** the COA used by AP Vouchers requires accounts `20101` (Accounts Payable - Trade), `10501` (Input VAT - Current), and `20301` (WHT Payable - Expanded) to exist before any APV can be saved (the create view builds a journal entry immediately). These are created in Phase 2 (scenarios 11–13, gated).

## 4. User-Approval Gates ⏸

Per project rules (propose-before-seeding / model-change approval), the test run **PAUSES** and prompts the user (product owner) with the **proposed data for review**, and waits for explicit sign-off, **before** any of the following writes:

1. **Creating VAT Categories** (scenario 16)
2. **Creating Withholding Tax codes** (scenario 17)
3. **Creating VAT/WHT-related accounts** — Input VAT (10501), WHT Payable (20301), and any related accounts, wherever they are created within scenarios 11–13

Gated scenarios are marked with **⏸** in their headers. The prompt must show the exact codes, names, rates, and account types to be created. Do not proceed without sign-off; record the sign-off (who/when) in the scenario notes.

## 5. Per-Scenario Qualitative Checks

Each scenario ends with two qualitative checks. They are explained once here; the scenarios carry the short versions.

**UX Review** — inspect the page(s) touched by the scenario for:

- Layout/alignment correct (no overlapping or misaligned elements)
- Responsive behavior (resize to tablet ~768px and mobile ~375px widths)
- Design-token consistency — no visibly hardcoded one-off styles
- Readable labels (clear field names, no truncation, sensible casing)
- Sensible empty states (helpful message + call-to-action, not a bare table)
- No broken styling (missing CSS, unstyled buttons, broken icons)
- UX notes: ___ (free text)

**Workflow Clarity** — could a **first-time user** figure out the next action without help? Consider visible buttons, hints, flash messages, and sidebar badges.

- **Verdict: Clear / Needs hint / Confusing** + one-line note

## 6. Dashboard Baseline

Right after the first login (scenario 1), open `http://127.0.0.1:5000/dashboard` and record the **empty state** for comparison in scenario 25:

- [ ] Revenue MTD / YTD = 0.00
- [ ] Expenses MTD / YTD = 0.00
- [ ] Receivables total / count / overdue = 0
- [ ] Payables total / count / overdue = 0
- [ ] Top Customers and Top Vendors panels show a sensible empty state (no errors, no broken charts)
- [ ] Revenue trend / expense breakdown charts render without errors on zero data
- [ ] Screenshot saved as `dashboard-baseline.png` (or values recorded here): ___

## 7. Test Scenarios

---

### Phase 0 — Initial Company Setup

---

#### Scenario 1 — Login

**Goal:** Admin can log in; failed access control redirects; logins are audited.

**Steps:**
1. While logged out, navigate directly to `http://127.0.0.1:5000/users` (a protected admin page).
2. Confirm you are redirected to `http://127.0.0.1:5000/login`.
3. On `/login`, enter username `admin` and the team-known password. Click **Sign In**.
4. Confirm redirect to the dashboard (`/dashboard`) with a "Welcome back" flash (admin has one branch, so no branch-selection page appears).
5. Capture the **Dashboard Baseline** (section 6).
6. Open `http://127.0.0.1:5000/audit-log` and filter module `auth`.

**Expected Result:** Logged-out access to protected pages redirects to `/login`; valid login lands on the dashboard with a welcome flash; audit log shows `login_success` for `admin`.

**Pass Criteria:**
- [ ] Protected URL while logged out → redirected to `/login`
- [ ] Valid credentials → dashboard with welcome flash
- [ ] Audit log entry: module `auth`, action `login_success`, record identifier `admin`
- [ ] Sidebar shows "Current Branch: Main Branch"

**UX Review:**
- [ ] Login page layout/alignment, responsive, design tokens, readable labels, no broken styling
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 2 — Logout

**Goal:** Logout works, is audited, and the browser back-button does not reveal protected content.

**Steps:**
1. While logged in as `admin`, navigate to `http://127.0.0.1:5000/logout`.
2. Confirm redirect to `/login` with a "logged out successfully" flash.
3. Press the browser **Back** button.
4. Confirm the protected page is not served from cache as a usable session (any action redirects to `/login`).
5. Log back in as `admin` and check `/audit-log` (module `auth`).

**Expected Result:** Session ends, flash confirms, back-button does not give access, audit shows `logout`.

**Pass Criteria:**
- [ ] Logout redirects to `/login` with confirmation flash
- [ ] Back button does not restore an authenticated session
- [ ] Audit log entry: module `auth`, action `logout`, identifier `admin`

**UX Review:**
- [ ] Logout flash visible and styled; login page state clean after logout
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 3 — App Settings — initial setup

> **Note (code reality):** No settings UI route currently exists in the codebase. `AppSettings` rows (`company_name`, `company_tin`, `company_address`, `fiscal_year_start`) are only created by `flask seed-db`, and the sole runtime setter is the JSON API `POST /api/environment` (admin-only, `environment` key only). There is also **no audit logging** on `AppSettings.set_setting()` (it records `updated_by`/`updated_at` on the row itself, but writes no `audit_log` entry). If no settings page exists at run time, log this scenario as a **bug/missing feature** in the Bug Log and record N/A for the steps below.

**Goal:** Set initial company settings — company name, TIN, address, fiscal year start — and verify persistence + audit per setting.

**Steps:**
1. As `admin`, locate the Settings page in the sidebar/Admin section (if absent → Bug Log, N/A).
2. Enter Company Name, TIN (format `XXX-XXX-XXX-XXX`), Address, and any other available settings. Save.
3. Reload the page and confirm values persisted.
4. Verify the values appear wherever the app displays company info (e.g., report headers).
5. Check `/audit-log` for one entry per changed setting.

**Expected Result:** Each setting persists, displays where used, and produces an audit entry recording the new value.

**Pass Criteria:**
- [ ] Settings page reachable from navigation (or Bug logged)
- [ ] All values persist after reload
- [ ] Audit entry per setting write
- [ ] `updated_by` on each `app_settings` row = `admin`

**UX Review:**
- [ ] Form layout, responsive, tokens, labels, validation messages
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 3b — App Settings — change

> **Note (code reality):** Same gap as scenario 3 — execute only if a settings UI exists; otherwise N/A + Bug Log reference.

**Goal:** Edit existing settings to new values; new values appear everywhere displayed; audit records old → new.

**Steps:**
1. As `admin`, open the Settings page again.
2. Change Company Name and TIN to clearly different values. Save.
3. Reload and confirm the new values everywhere company info is displayed.
4. Check `/audit-log`: the update entries must record **old value → new value** for each changed key.

**Expected Result:** Changes persist and propagate; audit shows old and new values.

**Pass Criteria:**
- [ ] New values persist and display everywhere applicable
- [ ] Audit entries contain both old and new values
- [ ] No stale old values remain anywhere in the UI

**UX Review:**
- [ ] Edit flow obvious; saved confirmation flash shown
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 4 — Approved Emails

**Goal:** Admin pre-approves the new user's email so self-registration is possible.

**Steps:**
1. As `admin`, open **Admin → Approved Emails** (`http://127.0.0.1:5000/approved-emails`).
2. Confirm the empty state is sensible.
3. Click to add (`/approved-emails/add`). Enter the new user's email (record it in Appendix) and an optional note. Submit.
4. Confirm flash `Email "<email>" has been approved for registration.` and the email listed with status "available"/not used.
5. Check `/audit-log` for an entry recording the approved-email addition.

**Expected Result:** Email appears in the approved list, available for registration.

> **Note (code reality):** `add_approved_email()` in `app/users/views.py` performs **no audit logging**. If no audit entry appears, that is a code gap — log it in the Bug Log (it will also surface in scenario 26 reconciliation).

**Pass Criteria:**
- [ ] Email added and listed as unused
- [ ] Duplicate add of the same email is rejected with a clear message
- [ ] Audit entry exists for the addition (if missing → Bug Log)

**UX Review:**
- [ ] List + form layout, responsive, tokens, labels, empty state
- UX notes: ___

**Clarity verdict:** ___

---

### Phase 1 — Users & Branches

---

#### Scenario 5 — Registration

**Goal:** Registration enforces approved emails, the password policy, and uniqueness; valid registration goes to pending state.

Password policy under test: **≥12 chars, at least one uppercase, one lowercase, one number, one special character**; must not contain the username; common passwords rejected.

**Steps:**
1. Log out. Navigate to `http://127.0.0.1:5000/register`.
2. **Negative — non-approved email:** submit with an email NOT in the approved list. Expect validation error "This email is not pre-approved for registration…".
3. **Negative — weak password:** use the approved email but password `short1!` (too short), then `alllowercase123!` (no uppercase), then `NoSpecial12345` (no special char). Each must be rejected with a specific policy message.
4. **Positive:** submit username, full name, the pre-approved email, and a policy-compliant password. Expect flash `Registration successful! Your account is pending admin approval…` and redirect to `/login`.
5. As `admin`, open `/approved-emails` and confirm the email is now marked **used**.
6. **Login while pending:** attempt to log in as the new user. Expect a clear message: "Your account is pending approval…".
7. **Negative — duplicates:** attempt to register again with the same username (different email) and with the same email. Both must be rejected ("Username already exists…" / "Email already registered…").
8. As `admin`, check `/audit-log` for module `user_registration`, action `registration_success`.

**Expected Result:** Only pre-approved emails with strong passwords can register; account is inactive pending approval; approved email flips to used; duplicates blocked.

**Pass Criteria:**
- [ ] Non-approved email rejected with explanatory message
- [ ] Each weak-password variant rejected with the specific policy violation named
- [ ] Valid registration → "pending admin approval" flash
- [ ] Approved email marked used (shows the registering username)
- [ ] Pending user cannot log in; message clearly says pending approval
- [ ] Duplicate username and duplicate email registrations rejected
- [ ] Audit: `user_registration` / `registration_success` entry exists

**UX Review:**
- [ ] Registration form layout, responsive, tokens, labels, inline validation messages readable
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 6 — Admin approves user

**Goal:** Admin activates the pending user, keeping the default `viewer` role.

**Steps:**
1. As `admin`, open **Admin → User Management** (`http://127.0.0.1:5000/users`).
2. Confirm the new user is listed as inactive, role `viewer`.
3. Open `/users/<id>/edit` for the new user. Check **Active**. Do NOT change the role. Save.
4. Confirm flash `User "<username>" updated successfully!`.
5. Check `/audit-log`: module `user`, action `update`, with old/new values showing `is_active: false → true`.
6. Log out; log in as the new user. Login must now succeed (single branch? — the viewer has **no** branch assigned yet, so expect "No branches available. Please contact the administrator." and a bounce back to `/login` — this is correct until scenario 8).

**Expected Result:** User active with role `viewer`; activation audited with old → new values; login blocked only by missing branch assignment (clear message).

**Pass Criteria:**
- [ ] User activated, role remains `viewer`
- [ ] Audit `user`/`update` entry with `is_active` change
- [ ] New user's login attempt gives the "No branches available" message (not a crash)

**UX Review:**
- [ ] User list and edit form layout, responsive, tokens, labels
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 6b — Account lockout & unlock

**Goal:** 5 wrong passwords lock the new user's account for 15 minutes; admin unlocks; audit trail complete.

**Steps:**
1. Log out. On `/login`, enter the new user's username with a wrong password **5 times**.
2. Observe warnings: at ≤2 remaining attempts the flash warns "Warning: N attempts remaining before account lockout."; on the 5th failure: "Too many failed login attempts. Your account has been locked for 15 minutes."
3. Attempt a 6th login (even with the **correct** password). Expect "Your account is locked… try again in N minutes or contact the administrator."
4. Log in as `admin`, open `/audit-log`, module `auth`, filter by the new user.
5. Verify the failure trail: **4 × `login_failed`** ("Invalid password") **+ 1 × `account_locked`** on the 5th attempt, plus `login_failed` ("Account locked…") for the post-lock attempt.
   > **Note (code reality):** the 5th failed attempt is logged as `account_locked` instead of a 5th `login_failed` — expect 4 `login_failed` + 1 `account_locked`, not 5 + 1.
6. Open `/users/<id>/edit` for the new user, tick the **Unlock account** checkbox, save.
7. Check `/audit-log` for module `user`, action `account_unlocked` (notes name the admin).
8. Log out; log in as the new user with the correct password — must succeed (will still hit "No branches available" until scenario 8; that bounce is acceptable here — the lockout itself must be cleared, i.e., no "locked" message).

**Expected Result:** Lockout engages on the 5th failure with a 15-minute message; admin unlock works; full audit trail present.

**Pass Criteria:**
- [ ] Remaining-attempts warning shown at ≤2 attempts left
- [ ] 5th failure locks the account with the 15-minute message
- [ ] Correct password rejected while locked
- [ ] Audit: 4 × `login_failed` + 1 × `account_locked` (+ post-lock `login_failed`)
- [ ] Admin unlock via `/users/<id>/edit` works
- [ ] Audit: `user` / `account_unlocked` entry exists
- [ ] User authenticates fine after unlock (no locked message)

**UX Review:**
- [ ] Lockout warnings clear and non-alarming; unlock control discoverable on the edit form
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 7 — Branch CRUD

**Goal:** Admin creates a second branch and edits it; both writes audited.

**Steps:**
1. As `admin`, open **Admin → Branch Management** (`http://127.0.0.1:5000/branches`).
2. Click **Create** (`/branches/create`). Enter code, name (record in Appendix), address, phone, email. Save.
3. Confirm the new branch appears in the list.
4. Open `/branches/<id>/edit` for the new branch; change the address. Save.
5. Check `/audit-log`: module `branch`, action `create` (new values) and action `update` (old → new address).

**Expected Result:** Second branch created and edited; both operations audited with values.

**Pass Criteria:**
- [ ] Branch created with all fields persisted
- [ ] Branch edit persists; list reflects changes
- [ ] Audit: `branch`/`create` with new values
- [ ] Audit: `branch`/`update` with old and new values

**UX Review:**
- [ ] Branch list/form layout, responsive, tokens, labels, empty/secondary states
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 8 — Assign user to branch

**Goal:** Map the new user to the **second branch only**.

**Steps:**
1. As `admin`, open `/branches/<id>/users` for the **second** branch.
2. Assign the new user (POST via the **Assign** button → `/branches/<id>/assign-user/<user_id>`). Alternatively use the Branch Assignments multi-select on `/users/<id>/edit`, ticking only the second branch.
3. Confirm the user is listed under the second branch and NOT under Main Branch (`/branches/<main_id>/users`).
4. Check `/audit-log`: module `branch`, action `assign_user` (or module `user`, action `branch_assigned` if done from the user form).

**Expected Result:** New user is assigned exactly one branch — the second branch.

**Pass Criteria:**
- [ ] User assigned to second branch only
- [ ] Main Branch user list does not include the new user
- [ ] Audit entry for the assignment exists

**UX Review:**
- [ ] Assignment UI obvious; current assignments visible at a glance
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 9 — User scope test (viewer)

**Goal:** As the new `viewer` user, confirm role gating: no Action Items, no admin pages, read-only transactions.

**Steps:**
1. Log in as the new user (now succeeds; lands on dashboard scoped to the second branch).
2. Confirm the sidebar shows **no Action Items item/badge** (it is rendered only for admin/accountant/staff).
3. Confirm the sidebar hides: Branch Management, User Management, Approved Emails, Audit Log, VAT Categories, Withholding Tax.
4. Hit each protected URL directly and confirm redirect + explanatory flash:
   - `/users` → redirected, "You need administrator or accountant privileges…"
   - `/approved-emails` → redirected with flash
   - `/action-items` → page loads but shows no pending-request content for viewers (list is built only for accountant/admin) — record what a viewer actually sees
   - `/audit-log` → redirected, "Only Accountants and Administrators can view audit logs."
   - `/branches` → redirected (admin only)
5. Open `/purchase-bills` and `/vendors`: lists must render read-only. Try `/purchase-bills/create` directly → redirect with flash "Only Accountants and Administrators can manage AP Vouchers."

**Expected Result:** Viewer sees read-only content with explanatory flashes; no admin or approval surfaces.

**Pass Criteria:**
- [ ] No Action Items nav item or badge for viewer
- [ ] All admin URLs redirect with explanatory flash (no 500s, no blank pages)
- [ ] Transaction pages read-only; write URLs blocked with flash
- [ ] No write buttons (Enter APV / Create / Edit / Delete) visible to the viewer

**UX Review:**
- [ ] Read-only states look intentional, not broken; flashes explain *why*
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 10 — Branch scope test

> **ORDERING NOTE:** This scenario MUST run **before** scenario 10b. Accountants (and admins) see **all** branches; once the user is promoted, branch scoping can no longer be tested with this account.

**Goal:** Branch data isolation for a branch-scoped user; admin branch switching is audited.

**Steps:**
1. As the new user (`viewer`, second branch only), confirm the sidebar branch indicator shows the **second branch**.
2. Navigate to `/select-branch`: only the second branch must be offered (or it auto-redirects because only one branch is accessible).
3. As `admin` (separate session/browser), note the ID of any Main-Branch-scoped record (after Phase 3 exists this is a purchase bill URL; at this point verify with whatever branch-scoped record exists, and **re-verify in Phase 3**: as the non-assigned user, open `/purchase-bills/<id>` of a Main Branch APV).
4. As the scoped user, request that Main-Branch record URL directly. Expect access denial.
   > **Note (code reality):** cross-branch purchase-bill access returns **404 Not Found** (`_get_bill_or_404`), not 403. Treat 404 as a pass for "denied"; record the 403-vs-404 mismatch in notes.
5. As `admin`, go to `/select-branch`, switch to the second branch, and confirm the dashboard/lists now show second-branch data; switch back to Main Branch.
6. Check `/audit-log`: module `auth`, action `branch_selected` entries for each admin switch.

**Expected Result:** Scoped user sees only their branch; direct URLs to other-branch records are denied; admin switching works and is audited.

**Pass Criteria:**
- [ ] Scoped user offered only the assigned branch in `/select-branch`
- [ ] Direct URL to other-branch record denied (404/403 — record which)
- [ ] Admin branch switch changes displayed data
- [ ] Audit: `auth`/`branch_selected` per switch

**UX Review:**
- [ ] Current branch always visible; switch flow discoverable
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 10b — Promote to accountant

**Goal:** Admin promotes the new user to `accountant`; promotion audited; user gains Action Items.

**Steps:**
1. As `admin`, open `/users/<id>/edit` for the new user. Change Role from `Viewer` to `Accountant`. Save.
2. Check `/audit-log`: module `user`, action `update`, old/new values showing `role: viewer → accountant`.
3. Log in as the user. Confirm the **Action Items** nav item now appears, and branch selection now offers **all branches** (accountants see all — which is why scenario 10 had to run first).
4. Confirm the user can now open `/audit-log` and `/users` (accountant-level pages).

**Expected Result:** Role change persisted and audited with old/new role; accountant surfaces unlocked.

**Pass Criteria:**
- [ ] Role = accountant after save
- [ ] Audit `user`/`update` entry contains old role and new role
- [ ] Action Items visible to the user
- [ ] User now sees all branches in `/select-branch`

**UX Review:**
- [ ] Role selector clear; consequences of role change communicated
- UX notes: ___

**Clarity verdict:** ___

---

### Phase 2 — Reference Data (approval workflow + audit)

> **Approval rules under test:**
> - Admin submissions always go to **pending** (admins never auto-approve).
> - A **sole accountant** auto-approves their own submissions instantly.
> - With **≥2 accountants**, requests go pending and **self-approval is blocked** (`can_be_approved_by` rejects the requester).
>
> **Note (code reality):** all three `can_auto_approve()` implementations (`app/accounts/views.py:29`, `app/vat_categories/views.py:32`, `app/withholding_tax/views.py:32`) return True when the count of active users with role **accountant OR admin** equals 1. Because the `admin` account is always active, the count is ≥2 throughout this run, so **auto-approval can never trigger** and **admins are not specially excluded**. This contradicts the documented rule ("sole accountant auto-approves; admins always pending"). Scenario 12 verifies this discrepancy explicitly.

---

#### Scenario 11 — COA — admin path ⏸ (gate applies to VAT/WHT-related accounts in #11–13)

**Goal:** Admin-created account goes to **pending** (not auto-approved), then is approved from Action Items; audited.

**⏸ Gate:** before creating Input VAT (10501), WHT Payable (20301), or any VAT/WHT-related account in scenarios 11–13, present the proposed codes/names/types to the product owner and wait for sign-off.

**Steps:**
1. As `admin`, open **Ledger → Chart of Accounts** (`http://127.0.0.1:5000/accounts/`). Confirm sensible empty state.
2. Click create (`/accounts/create`). Propose the account set needed for APVs (present at the ⏸ gate): at minimum `20101 Accounts Payable - Trade` (Liability), one expense account for line items, plus the gated `10501 Input VAT - Current` (Asset) and `20301 WHT Payable - Expanded` (Liability). Create the **first** account here (e.g., 20101); remaining accounts may be created in scenarios 12–13 (still honoring the gate).
3. Submit. Expect flash "Account creation request submitted for approval by another accountant." — i.e., **pending**, NOT auto-approved.
4. Confirm the sidebar **Action Items badge** increments (admin and the accountant both see it).
5. As the **accountant** user, open `/action-items`, find the request, follow its review link, and approve from `/accounts/pending-approvals` (Approve button → POST `/accounts/approve/<request_id>`). (The requester must not approve — see scenario 13 for the negative.)
6. Confirm the account now exists in `/accounts/`.
7. Check `/audit-log`: module `account`, action `create` entries for submission ("Pending approval") and approval ("Approved by <username>").

**Expected Result:** Admin request is pending; another accountant approves; account created; both steps audited.

**Pass Criteria:**
- [ ] ⏸ Sign-off obtained before VAT/WHT-related account creation (record who/when)
- [ ] Admin submission → pending (no instant creation)
- [ ] Action Items badge count correct
- [ ] Approval by the accountant creates the account
- [ ] Audit: `account`/`create` with notes "Pending approval"
- [ ] Audit: `account`/`create` with notes "Approved by …"

**UX Review:**
- [ ] COA list (hierarchy), create form, pending-approvals page — layout, responsive, tokens, labels, empty states
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 12 — COA — sole accountant path

**Goal:** Verify the auto-approval rule for a sole accountant.

> **Note (code reality):** as implemented, auto-approval requires exactly **one active accountant-or-admin in the entire system**. With `admin` active, this run always has ≥2, so the accountant's request will go **pending**, not auto-approve. Execute the steps, record the actual behavior, and log the discrepancy against the documented rule in the Bug Log (design clarification needed: should admins be excluded from the count?).

**Steps:**
1. As the **accountant** user, open `/accounts/create` and create the next account from the approved set (e.g., the expense account; if it is VAT/WHT-related, the ⏸ gate from scenario 11 applies).
2. Observe the flash: auto-approve → "Account created successfully! (Auto-approved - you are the only accountant)"; pending → "…submitted for approval by another accountant."
3. If pending (expected per code reality), have `admin` approve it via `/accounts/pending-approvals` so the data exists for Phase 3.
4. Check `/audit-log` for the corresponding `account`/`create` entries (auto-approved entries carry notes "Auto-approved (single accountant)").

**Expected Result (documented rule):** sole accountant → instant auto-approval, no pending request. **Actual (code):** record what happens.

**Pass Criteria:**
- [ ] Behavior recorded (auto-approved vs pending) with screenshot
- [ ] Account ends up created (via auto-approve or admin approval)
- [ ] Audit entries present for every step taken
- [ ] Discrepancy (if any) logged in Bug Log

**UX Review:**
- [ ] Flash wording matches what actually happened
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 13 — COA — multi-accountant path

**Goal:** With 2 accountants, requests go pending and self-approval is blocked; the second accountant approves.

**Steps:**
1. As `admin`: add a 2nd approved email (`/approved-emails/add`).
2. Register the 2nd accountant via `/register` (policy-compliant password), then as `admin` activate them and set role `accountant` via `/users/<id>/edit` (audit checks as in scenarios 6/10b).
3. As the **1st accountant**, create the next account from the approved set (gate ⏸ applies if VAT/WHT-related) via `/accounts/create`. Expect **pending**.
4. Still as the 1st accountant, open `/accounts/pending-approvals`: the own request must show **no Approve button** (or approving must fail with "You cannot approve your own request when there are other accountants available.") — record which safeguard fires.
5. As the **2nd accountant**, open `/action-items` → review → approve the request.
6. Check `/audit-log` for submission and approval entries; also for the 2nd accountant's registration/activation/role-change entries.

**Expected Result:** Pending request, requester blocked from self-approval, peer approves; full audit trail.

**Pass Criteria:**
- [ ] 2nd accountant registered, activated, promoted (each step audited)
- [ ] 1st accountant's request → pending
- [ ] Self-approval blocked (UI hides button and/or POST rejected with flash)
- [ ] 2nd accountant approves successfully; account created
- [ ] Audit: submission + approval entries present

**UX Review:**
- [ ] Pending list clearly distinguishes own requests vs reviewable ones
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 14 — Action Items page

**Goal:** The Action Items hub gives reviewers everything needed to decide.

**Steps:**
1. Queue up pending requests: have one accountant submit 1 COA request (`/accounts/create`), 1 VAT request (`/vat-categories/create` — ⏸ gate, see scenario 16; you may reuse its approved data and submit it here), and 1 WHT request (`/withholding-tax/create` — ⏸ gate, see scenario 17). (If you prefer, run 16/17 first and return here while their requests are pending.)
2. As the other accountant (or `admin`), verify the sidebar **badge count equals the number of pending requests** and updates after each approve/reject (page reload acceptable).
3. Open `http://127.0.0.1:5000/action-items`. For **each** item verify: request type (AccountChange / VATChange / WTChange), change type (create/update/delete), record identifier (code), proposed values/description, requester username, timestamp, and a working **review link**.
   > **Note (code reality):** the COA item's review link points to `/accounts/review-change-request/<id>`, but no such route exists in `app/accounts/views.py` (review actions live at `/accounts/pending-approvals`). If the link 404s, log a bug. VAT/WHT links (`/vat-categories/change-requests/<id>/review`, `/withholding-tax/change-requests/<id>/review`) should work.
4. Approve one item and reject another **with notes** from their review pages.
5. As the `viewer`-style negative: confirm a non-accountant cannot reach the pending content (already covered in scenario 9 — re-verify quickly).
6. Clarity question to answer explicitly: **could a reviewer decide from this page alone**, without opening other modules?

**Expected Result:** Badge accurate, items complete and reviewable, approve/reject reachable, page restricted to accountant/admin.

**Pass Criteria:**
- [ ] Badge count matches pending requests and updates after each action
- [ ] Each item shows type, change type, identifier, proposed values, requester, timestamp, review link
- [ ] Review links navigate to working pages (COA link bug recorded if 404)
- [ ] Approve and reject (with notes) both work from the review surfaces
- [ ] Page content restricted to accountant/admin
- [ ] Audit entries for the approve and the reject

**UX Review:**
- [ ] Scannable list, statuses obvious, empty state when queue is clear
- UX notes: ___

**Clarity verdict:** ___ (include the "decide from this page alone?" answer)

---

#### Scenario 15 — Reject flow

**Goal:** Rejection with notes leaves the record unchanged and is fully audited; requester can see the outcome.

**Steps:**
1. As one accountant, submit an account **change** request (e.g., edit an existing account's name via `/accounts/<id>/edit`) → pending.
2. As the other accountant, open `/accounts/pending-approvals` and **Reject** it, entering a rejection reason in the modal (POST `/accounts/reject/<request_id>`).
3. Confirm flash "Account update request rejected." and that the underlying account is **unchanged**.
4. As the requester, verify they can see the rejection and the notes (pending-approvals/history list, and notification if present).
5. Check `/audit-log` for the rejection entry.
   > **Note (code reality):** the documented convention is rejections log `action='reject'`. The **accounts** module instead logs `action=<change_type>` (e.g., `update`) with notes "Rejected by <user>: <reason>" (`app/accounts/views.py:551-602`); VAT and WHT reviews do log `action='reject'`. Verify the entry exists either way and log the convention mismatch as a bug.

**Expected Result:** Request → rejected with notes; record untouched; audit entry present; requester informed.

**Pass Criteria:**
- [ ] Reject requires/accepts notes; status becomes `rejected`
- [ ] Target account unchanged after rejection
- [ ] Audit entry for the rejection exists (record actual `action` value; mismatch vs `reject` → Bug Log)
- [ ] Requester can see rejection + notes

**UX Review:**
- [ ] Reject modal (custom HTML, no JS popups), reason field, outcome visibility
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 16 — ⏸ VAT category

**Goal:** Gated creation of VAT categories through the approval workflow.

**⏸ Gate:** PAUSE. Present the proposed VAT categories (code, name, rate, description) to the product owner — e.g., `VAT12 / VAT 12% / 12.00` and `EXEMPT / VAT Exempt / 0.00` — and wait for sign-off. Record sign-off.

**Steps:**
1. As one accountant, open **Maintenance → VAT Categories** (`http://127.0.0.1:5000/vat-categories/`). Confirm empty state.
2. Create the approved categories via `/vat-categories/create`. Expect each submission → **pending** change request.
3. As the other accountant, open `/vat-categories/change-requests`, review each (`/vat-categories/change-requests/<id>/review`), and **approve**.
4. Confirm the categories now appear in the list with correct rates.
5. Check `/audit-log`: `vat_category`/`create` entries with notes "Approved by …" (and submission entries).

**Expected Result:** Create → pending → approve; categories live; audited.

**Pass Criteria:**
- [ ] ⏸ Sign-off recorded before any DB write
- [ ] Submission produces pending request (no instant create)
- [ ] Peer approval creates the category with correct code/name/rate
- [ ] Requester cannot review own request ("You cannot review your own change request.")
- [ ] Audit entries for submission and approval

**UX Review:**
- [ ] List, form, change-requests, review pages — layout, responsive, tokens, labels, empty states
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 17 — ⏸ Withholding tax code

**Goal:** Gated creation of WHT codes through the approval workflow.

**⏸ Gate:** PAUSE. Present the proposed WHT codes (code, name, rate) — e.g., `WC158 / EWT - Professional fees / 10.00` or per BIR table as the owner directs — and wait for sign-off. Record sign-off.

**Steps:**
1. As one accountant, open **Maintenance → Withholding Tax** (`http://127.0.0.1:5000/withholding-tax/`). Confirm empty state.
2. Create the approved code(s) via `/withholding-tax/create`. Expect pending change request(s).
3. As the other accountant, review and approve via `/withholding-tax/change-requests` → `/withholding-tax/change-requests/<id>/review`.
4. Confirm codes live with correct rates.
5. Check `/audit-log`: `withholding_tax` submission + approval entries.

**Expected Result:** Create → pending → approve; codes live; audited.

**Pass Criteria:**
- [ ] ⏸ Sign-off recorded before any DB write
- [ ] Pending → approved flow works; self-review blocked
- [ ] Codes/rates correct in the list
- [ ] Audit entries for submission and approval

**UX Review:**
- [ ] Same surfaces as VAT — consistent with scenario 16's design
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 18 — Vendor

**Goal:** Vendor master data uses direct CRUD (no approval workflow); fully audited.

**Steps:**
1. As an accountant, open **Maintenance → Vendors** (`http://127.0.0.1:5000/vendors`). Confirm empty state and that the button says **Create** (master data) not "Enter".
2. Create a vendor via `/vendors/create`: code, name, TIN, address, contact details, payment terms (record in Appendix). Save — vendor must appear **immediately** (no pending request).
3. Edit via `/vendors/<id>/edit` (e.g., change phone). Save.
4. View `/vendors/<id>` and confirm all details render.
5. Check `/audit-log`: `vendor`/`create` (new values) and `vendor`/`update` (old → new).

**Expected Result:** Instant create/edit, detail view correct, both writes audited.

**Pass Criteria:**
- [ ] Create is immediate (no approval step)
- [ ] Edit persists; view shows current data
- [ ] Audit: `vendor`/`create` with new values
- [ ] Audit: `vendor`/`update` with old and new values

**UX Review:**
- [ ] Vendor list/form/detail — layout, responsive, tokens, labels, empty state
- UX notes: ___

**Clarity verdict:** ___

---

### Phase 3 — AP Voucher Flow

> The UI calls purchase bills **"AP Voucher / APV"**. Sidebar: **Transactions → AP Vouchers**. Buttons: **➕ Enter APV**, **Post APV**, **Void APV**, **Cancel APV**. Numbering: `AP-YYYY-MM-NNNN`, resetting monthly (voided numbers are skipped/not reused).
>
> Prereq from Phase 2: accounts `20101`, `10501`, `20301` + at least one expense account exist; VAT categories and WHT codes live; vendor created. The APV save will fail with an explicit error if `20101/10501/20301` are missing.

---

#### Scenario 19 — Enter APV (draft)

**Goal:** Accountant enters a draft APV with VAT + WHT lines and an image attachment; numbering, computations, and validations correct.

**Steps:**
1. As the accountant, ensure the working branch is their branch (sidebar indicator; `/select-branch` if needed).
2. Open `/purchase-bills` and click **➕ Enter APV** (`/purchase-bills/create`).
3. Verify the **AP Number** is pre-filled as `AP-<current year>-<current month>-0001` (first APV of the period).
4. Select the vendor; set Voucher Date = today, Due Date per terms. Leave **Vendor Invoice #** and **Vendor Invoice Date** **empty** (allowed for drafts).
5. Add 2 line items: each with description, amount, an expense account from the picker, a VAT category (12%), and a WHT code on at least one line. Record exact values in the Appendix.
6. **Computation check:** manually recompute from the entered amounts: VAT amount, WHT amount, gross, and net payable. Compare against the totals panel — must match **exactly** (to the centavo).
7. Save the draft. Expect flash `AP Voucher "AP-…" entered successfully!` and redirect to `/purchase-bills/<id>`.
8. Open `/purchase-bills/<id>/edit`, upload a vendor invoice **image** (`.png`/`.jpg`) via the attachment control (POST `/purchase-bills/<id>/attachments/upload`).
9. Verify the **preview popup** renders the image (`/purchase-bills/attachments/<aid>/preview`) and **download** returns the original file (`/purchase-bills/attachments/<aid>/download`).
10. **Validation negatives** (each must be blocked with a clear message, nothing saved):
    - line amount `0` and a negative amount
    - missing vendor ("-- Select Vendor --" left selected)
    - Due Date earlier than Voucher Date
11. Check `/audit-log`: `purchase_bill`/`create` and `purchase_bill_attachment`/`create`.

**Expected Result:** Draft saved without vendor invoice fields; number `AP-YYYY-MM-0001`; totals exact; attachment preview/download work; invalid inputs blocked.

**Pass Criteria:**
- [ ] Number follows `AP-YYYY-MM-NNNN` for the current period (0001)
- [ ] Draft saves without Vendor Invoice #/Date
- [ ] Manual recomputation of VAT, WHT, gross, net payable matches the totals panel exactly
- [ ] Image preview popup works; download returns the file
- [ ] Zero/negative amount blocked with clear message
- [ ] Missing vendor blocked with clear message
- [ ] Due date before voucher date blocked with clear message
- [ ] Audit: `purchase_bill`/`create` entry
- [ ] Audit: `purchase_bill_attachment`/`create` entry

**UX Review:**
- [ ] APV form (header, line grid, totals panel, attachments) — layout, responsive, tokens, labels
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 20 — Attachment security negatives

**Goal:** Dangerous/oversized files rejected; attachments not reachable across users/branches.

**Steps:**
1. On the draft APV's edit page, attempt to upload a `.svg` file → must be rejected ("File type … is not allowed", SVG is deliberately excluded).
2. Attempt to upload an `.exe` → rejected with the same allowlist message.
3. Attempt an oversized file (> 16 MB, the `MAX_CONTENT_LENGTH` default) → rejected (HTTP 413 or an error page/flash — record which; an unstyled 413 is a UX bug).
4. Copy a valid attachment's download URL (`/purchase-bills/attachments/<aid>/download`). As the **other** user working in **another branch** (e.g., admin switched to the second branch, or the 2nd accountant with a different selected branch), request that URL directly.
5. Expect denial: redirect to login if unauthenticated; for a cross-branch session expect **404** (code uses `_get_bill_or_404`; spec allows 403/redirect — record actual).

**Expected Result:** Allowlist enforced server-side; size cap enforced; no cross-branch/anonymous access to files.

**Pass Criteria:**
- [ ] `.svg` rejected
- [ ] `.exe` rejected
- [ ] Oversized upload rejected (record the response form)
- [ ] Logged-out request to attachment URL → redirect to `/login`
- [ ] Cross-branch request to attachment URL → denied (404/403, record which)

**UX Review:**
- [ ] Rejection messages name the allowed types; no raw stack traces or bare 413 pages
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 21 — Edit APV

**Goal:** Draft edit works; "required to post" hints visible; attachment delete + re-upload audited.

**Steps:**
1. Open `/purchase-bills/<id>/edit` for the draft.
2. Confirm the empty **Vendor Invoice #** and **Vendor Invoice Date** fields display a visible "Required to post" hint.
3. Change a line amount and the notes. Save. Confirm totals recompute and the detail page reflects changes.
4. Delete the existing attachment (custom modal — POST `/purchase-bills/attachments/<aid>/delete`), then re-upload it.
5. Check `/audit-log`: `purchase_bill`/`update` (old → new totals), `purchase_bill_attachment`/`delete`, `purchase_bill_attachment`/`create`.

**Expected Result:** Edits persist with recomputed totals; hints guide posting requirements; attachment cycle audited.

**Pass Criteria:**
- [ ] "Required to post" hints visible on empty vendor-invoice fields
- [ ] Edit persists; totals recompute correctly
- [ ] Attachment delete then re-upload both succeed
- [ ] Audit: `purchase_bill`/`update` with old and new values
- [ ] Audit: attachment `delete` and `create` entries

**UX Review:**
- [ ] Edit form parity with create form; hint styling consistent with design tokens
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 22 — Void APV

**Goal:** Voiding the draft removes it from the books and deletes attachment files from disk; audited.

**Steps:**
1. On `/purchase-bills/<id>` (the draft), click **Void APV**. A custom modal asks for a Void Date and a reason (minimum 10 characters — test a too-short reason first → blocked).
2. Submit a valid reason. Expect flash `AP Voucher "AP-…" voided.` and status badge **Voided** with the reason shown on the detail page.
3. On the server, check `instance/uploads/purchase_bills/<id>/` — the attachment file(s) must be **removed from disk** (folder empty or gone).
4. Confirm the draft's linked journal entry is gone (check `/journal-entries` — no entry referencing this APV).
5. Check `/audit-log`: `purchase_bill`/`void` with the reason and attachment-deletion note.

**Expected Result:** Draft voided, attachments purged from disk, JE removed, audit entry with reason.

**Pass Criteria:**
- [ ] Reason < 10 chars blocked with clear message
- [ ] Status → voided; reason displayed on detail page
- [ ] Attachment files deleted from `instance/uploads/purchase_bills/<id>/`
- [ ] No JE remains for the voided draft
- [ ] Audit: `purchase_bill`/`void` entry (notes include reason and attachment count)

**UX Review:**
- [ ] Void modal is a custom HTML modal (no `confirm()`), destructive action clearly styled
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 23 — Enter + Post APV

**Goal:** Second APV gets the next number; posting requires vendor invoice fields; posting audited.

**Steps:**
1. Click **➕ Enter APV** again. Verify the prefilled number is the **next NNNN** for the period (voided numbers are not reused — record the actual number; with #0001 voided, expect `…-0002`).
2. Enter the same vendor, valid dates, 1–2 lines with VAT + WHT, **leave Vendor Invoice # / Date empty**, save as draft.
3. On `/purchase-bills/<id>`, click **Post APV** (custom modal → POST `/purchase-bills/<id>/post`). Expect block: `Cannot post: Vendor Invoice # and Vendor Invoice Date is required.`
4. Edit the draft, fill Vendor Invoice # and Vendor Invoice Date (record in Appendix), save.
5. Click **Post APV** again. Expect flash `AP Voucher "AP-…" posted successfully!` and status **Posted**.
6. Verify the journal entry section on the detail page balances (debits = credits; expense net + Input VAT debit vs WHT Payable + AP credit).
7. Check `/audit-log`: `purchase_bill`/`create` and `purchase_bill`/`post`.

**Expected Result:** Numbering increments; post gate enforced; posted APV with balanced JE; audited.

**Pass Criteria:**
- [ ] Number is the next NNNN in sequence for the period
- [ ] Post blocked while vendor invoice fields empty (clear message)
- [ ] Post succeeds after filling them; status = posted
- [ ] JE lines balanced and use 20101/10501/20301 + expense accounts
- [ ] Audit: `purchase_bill`/`create` and `purchase_bill`/`post` entries

**UX Review:**
- [ ] Post modal communicates finality; status badges distinct
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 24 — Approve APV

> **Note (code reality):** there is **no approve route or "approved" status** for APVs. The lifecycle in `app/purchase_bills/views.py` is `draft → posted → (cancelled)` and `draft → voided` (plus payment statuses `partially_paid`/`paid`). Record the approve step as **N/A — no approval flow implemented** (log a Bug/design item if an approval step was expected), and run the **immutability checks below against the POSTED APV** — they are the real subject of this scenario.

**Goal:** Posted APVs are immutable: no edit/delete, no attachment changes.

**Steps:**
1. Open `/purchase-bills/<id>` for the **posted** APV. Confirm there are **no Edit / Void / attachment-upload / attachment-delete buttons** (only Cancel APV and download/preview should remain).
2. Request `/purchase-bills/<id>/edit` directly. Expect redirect with flash "Only draft APVs can be edited."
3. POST to `/purchase-bills/<id>/void` (e.g., re-submit a crafted form) — expect "Only draft APVs can be voided."
4. Attempt attachment upload on the posted APV (direct POST to `/purchase-bills/<id>/attachments/upload`) — expect "Attachments can only be uploaded while the APV is in draft status."
5. Attempt attachment delete — expect "Attachments can only be deleted while the APV is in draft status."
6. Confirm attachment **download/preview still work** on the posted APV.

**Expected Result:** All mutation paths blocked on posted APVs, with clear flashes; reads still work.

**Pass Criteria:**
- [ ] Approve step recorded as N/A (no approval flow in code) and noted in Bug Log if it was expected
- [ ] No edit/void/attachment-mutation buttons on a posted APV
- [ ] Direct `/edit` URL blocked with flash
- [ ] Direct void POST blocked
- [ ] Attachment upload and delete blocked after posting
- [ ] Attachment download/preview still available

**UX Review:**
- [ ] Posted state visually distinct; absence of buttons reads as intentional
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 24b — Cancel APV

> **Code check performed:** a **Cancel flow exists** and is distinct from Void — `POST /purchase-bills/<id>/cancel` cancels a **posted** APV, requires a reason (≥10 chars) + reversal date, creates a **reversal journal entry**, and — unlike Void — **retains attachments**. Not applicable to drafts.

**Goal:** Cancel a posted APV; reversal JE created; attachments retained; audited.

**Steps:**
1. (Use the posted APV from scenario 23, or enter+post a third APV if you want to keep one live for scenario 25 — recommended: enter + post APV #3 quickly and cancel **that** one, keeping #2 posted for the dashboard scenario. Record numbers in the Appendix.)
2. On the posted APV's detail page, click **Cancel APV**. The modal requires a Reversal Date and a reason ≥ 10 chars (test a short reason → blocked).
3. Submit. Expect flash `AP Voucher "AP-…" cancelled. Reversal journal entry created.` and status **Cancelled** with reason displayed.
4. Verify in `/journal-entries`: a reversal entry (`reversal`, reference `CANCEL-AP-…`) exists with mirrored debits/credits.
5. Check `instance/uploads/purchase_bills/<id>/`: attachment files **still present** (cancel retains; only void deletes).
6. Confirm a cancelled APV with payments applied is impossible (informational — payments module out of scope here).
7. Check `/audit-log`: `purchase_bill`/`cancel` with reason.

**Expected Result:** Posted → cancelled with reversal JE; attachments retained; audited.

**Pass Criteria:**
- [ ] Short reason blocked; valid cancel succeeds
- [ ] Reversal JE exists and balances
- [ ] Attachment files RETAINED on disk after cancel
- [ ] Audit: `purchase_bill`/`cancel` entry with reason

**UX Review:**
- [ ] Cancel modal explains the reversal consequence; cancelled banner shows who/when/why
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 25 — Dashboard

**Goal:** Dashboard payables stats and Top Vendors reflect the posted APV, scoped to branch; compare to the baseline.

**Steps:**
1. As the accountant in the branch holding the **posted** APV, open `/dashboard`.
2. Compare against the **Dashboard Baseline** (section 6): Payables total must equal the posted APV's net payable; payables count = number of open posted APVs; expenses MTD reflects the expense lines.
3. Verify **Top Vendors** lists the test vendor with the correct amount.
4. Verify cancelled/voided APVs are **excluded** from the totals.
5. Switch to the **other** branch (`/select-branch`) and reload `/dashboard`: payables from the first branch must **not** appear (branch scoping).
6. Use the "as of" date filter (`/dashboard?as_of_date=YYYY-MM-DD`) with a date **before** the APV: totals must drop back to baseline zeros.

**Expected Result:** Stats match the books, scoped by branch and as-of date; baseline deltas explained entirely by the test APVs.

**Pass Criteria:**
- [ ] Payables total/count match the posted APV exactly
- [ ] Top Vendors shows the vendor with correct amount
- [ ] Voided/cancelled APVs excluded
- [ ] Other branch shows baseline (zero) payables
- [ ] As-of date before the APV restores baseline values

**UX Review:**
- [ ] Cards/charts readable with real data; currency formatting consistent
- UX notes: ___

**Clarity verdict:** ___

---

#### Scenario 26 — Audit Log UI + full audit reconciliation

**Goal:** The audit log page works, and EVERY DB write performed during this run has an audit entry. **Any DB write with no audit entry = FAIL → Bug Log.**

**Steps:**
1. As `admin` (or accountant), open `http://127.0.0.1:5000/audit-log`.
2. Exercise the UI: filter by module, action, user, branch, date range; search; paginate (50/page). Each filter must narrow results correctly.
3. Reconcile the full run against the log. Tick each event class only when its audit entries are found:

**Reconciliation checklist:**
- [ ] Logins: `auth`/`login_success` for every successful login this run
- [ ] Lockout: 4 × `auth`/`login_failed` + `auth`/`account_locked` (scenario 6b)
- [ ] Unlock: `user`/`account_unlocked`
- [ ] Logouts: `auth`/`logout`
- [ ] Settings initial setup + change (scenarios 3/3b) — **known code gap if missing**; record
- [ ] Approved-email additions (scenario 4) — **known code gap: no audit call in `add_approved_email()`**; record as bug if absent
- [ ] Registrations: `user_registration`/`registration_success` (×2 users)
- [ ] Activations + role changes: `user`/`update` with old/new values
- [ ] Branch create/edit: `branch`/`create`, `branch`/`update`
- [ ] Branch assignment: `branch`/`assign_user` (or `user`/`branch_assigned`)
- [ ] Branch selections: `auth`/`branch_selected` for every switch
- [ ] COA change requests: submissions, approvals, rejection (note: accounts rejection logs `action=<change_type>` with "Rejected by" notes — record actual)
- [ ] VAT change requests: submission, approval (and `reject` if exercised)
- [ ] WHT change requests: submission, approval
- [ ] Vendor: `vendor`/`create`, `vendor`/`update`
- [ ] APV: `purchase_bill`/`create` (×2–3), `update`, `void`, `post`, `cancel`
- [ ] Attachments: `purchase_bill_attachment`/`create` (each upload), `delete`
4. For each entry spot-check: actor (user), timestamp (PH time), record identifier, and old/new values where applicable.
5. Confirm the page itself is restricted (viewer blocked — verified in scenario 9).

**Expected Result:** Filters work; every write reconciles to an audit entry (or the gap is logged as a bug).

**Pass Criteria:**
- [ ] All filters and search behave correctly
- [ ] Every checklist line above reconciled (or bug logged per miss)
- [ ] Entries carry correct actor, PH timestamp, identifiers, old/new values
- [ ] No unexplained audit entries (everything maps to a runbook action)

**UX Review:**
- [ ] Dense data remains scannable; filters discoverable; pagination clear
- UX notes: ___

**Clarity verdict:** ___

---

## 8. Workflow Clarity Summary

Fill in during the run (verdicts: Clear / Needs hint / Confusing).

| Scenario | Verdict | Note |
|----------|---------|------|
| 1 — Login | | |
| 2 — Logout | | |
| 3 — App Settings — initial | | |
| 3b — App Settings — change | | |
| 4 — Approved Emails | | |
| 5 — Registration | | |
| 6 — Approve user | | |
| 6b — Lockout & unlock | | |
| 7 — Branch CRUD | | |
| 8 — Assign user to branch | | |
| 9 — User scope (viewer) | | |
| 10 — Branch scope | | |
| 10b — Promote to accountant | | |
| 11 — COA admin path | | |
| 12 — COA sole accountant | | |
| 13 — COA multi-accountant | | |
| 14 — Action Items page | | |
| 15 — Reject flow | | |
| 16 — VAT category | | |
| 17 — Withholding tax code | | |
| 18 — Vendor | | |
| 19 — Enter APV (draft) | | |
| 20 — Attachment security | | |
| 21 — Edit APV | | |
| 22 — Void APV | | |
| 23 — Enter + Post APV | | |
| 24 — Approve APV / immutability | | |
| 24b — Cancel APV | | |
| 25 — Dashboard | | |
| 26 — Audit Log + reconciliation | | |

## 9. Bug Log

**Rule:** a cross-module bug **stops the run**, gets fixed, and the affected test re-runs before continuing. Severity: Critical / High / Medium / Low.

| # | Scenario | Severity | Description | Status |
|---|----------|----------|-------------|--------|
| | | | | |

## 10. Appendix: Test Data

Fill these in during the first run; reuse the same data in later runs. **Never record passwords here.**

### Users

| Username | Email | Role (final) | Notes |
|----------|-------|--------------|-------|
| admin | | admin | Seeded |
| | | accountant | Registered scenario 5, promoted 10b |
| | | accountant | Registered scenario 13 |

### Branches

| Code | Name | Notes |
|------|------|-------|
| | Main Branch | Seeded |
| | | Created scenario 7 |

### Accounts (Chart of Accounts)

| Code | Title | Type | Created in |
|------|-------|------|-----------|
| 20101 | Accounts Payable - Trade | Liability | Scenario 11 |
| 10501 | Input VAT - Current | Asset | Scenario 11–13 (⏸ gated) |
| 20301 | WHT Payable - Expanded | Liability | Scenario 11–13 (⏸ gated) |
| | | Expense | Scenario 12/13 |

### VAT Categories

| Code | Name | Rate % | Created in |
|------|------|--------|-----------|
| | | | Scenario 16 (⏸ gated) |
| | | | |

### WHT Codes

| Code | Name | Rate % | Created in |
|------|------|--------|-----------|
| | | | Scenario 17 (⏸ gated) |

### Vendor

| Code | Name | TIN | Terms | Created in |
|------|------|-----|-------|-----------|
| | | | | Scenario 18 |

### APV Documents

| Number | Date | Lines (desc / amount / VAT / WHT) | VAT amt | WHT amt | Net payable | Final status |
|--------|------|-----------------------------------|---------|---------|-------------|--------------|
| AP-____-__-0001 | | | | | | Voided (scenario 22) |
| AP-____-__-0002 | | | | | | Posted (scenarios 23–25) |
| AP-____-__-0003 | | | | | | Cancelled (scenario 24b) |

### Attachment Files

| Filename | Type | Size | Used in | Outcome |
|----------|------|------|---------|---------|
| | image (.png/.jpg) | | Scenario 19 | Deleted on void (22) |
| | .svg | | Scenario 20 | Rejected |
| | .exe | | Scenario 20 | Rejected |
| | > 16 MB | | Scenario 20 | Rejected |
| | image | | Scenario 23/24b | Retained on cancel |
