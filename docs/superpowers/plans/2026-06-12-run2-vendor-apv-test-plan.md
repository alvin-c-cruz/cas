# Run 2 — Vendor & AP Voucher Test Plan Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix staff role permissions for Tier 1 vendor and AP voucher operations, then execute the 67-scenario Run 2 browser test plan.

**Architecture:** Two TDD code tasks add a `staff_or_above_required` decorator to `app/vendors/views.py` and `app/purchase_bills/views.py`. Tier 1 routes (create, edit, void, upload) allow staff; Tier 2 routes (delete, post, cancel) stay accountant/admin only. Templates updated to show buttons for staff. Six execution tasks use Playwright MCP for browser tests across 4 users.

**Tech Stack:** Flask + Jinja2, pytest + SQLAlchemy, Playwright MCP

**Spec:** `docs/superpowers/specs/2026-06-12-run2-vendor-apv-test-plan-design.md`

**Browser creds:** admin = `admin` / `admin123`  
**Test user creds:** testaccountant=`TestAcc!Pass123`, teststaff=`TestStf!Pass123`, testviewer=`TestVwr!Pass123`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `app/vendors/views.py` | Modify | Add `staff_or_above_required`; apply to `create()` (~line 123) and `edit()` (~line 193) |
| `app/vendors/templates/vendors/list.html` | Modify | Show "+ Create Vendor" for staff |
| `tests/integration/test_vendor_views.py` | Modify | Remove `test_staff_cannot_edit()`; add `TestVendorStaffPermissions` class |
| `app/purchase_bills/views.py` | Modify | Add `staff_or_above_required`; apply to `create()` (~459), `edit()` (~622), `void()` (~1085), `upload_attachment()` (~1163) |
| `app/purchase_bills/templates/purchase_bills/list.html` | Modify | Show "+ New AP Voucher" for staff |
| `app/purchase_bills/templates/purchase_bills/detail.html` | Modify | Show Edit/Void buttons for staff on draft bills; Post remains accountant/admin |
| `tests/integration/test_purchase_bill_views.py` | Modify | Add `TestStaffPermissions` class |

---

## Playwright Notes (applies to all browser tasks)

- **Readonly login fields:** `#username` and `#password` are `readonly` on load. **Click first, then type.**
- **Login page password selector:** `#password`
- **Register page password selector:** `#password-field`
- **Branch selection:** After login, if prompted, click "Main Branch" before proceeding.
- **Choices.js dropdowns (vendor, account, VAT, EWT pickers):** Click the wrapper element to open it, type to search, then click the matching option.
- **Snapshot after navigation** to verify page state before asserting.

---

## Task 1 — Fix vendor Tier 1 permissions

**Files:** `app/vendors/views.py`, `app/vendors/templates/vendors/list.html`, `tests/integration/test_vendor_views.py`

- [ ] **Step 1: Write failing tests — add `TestVendorStaffPermissions` to `tests/integration/test_vendor_views.py`**

Append this class to the end of the file:

```python
class TestVendorStaffPermissions:
    """Staff can create and edit vendors (Tier 1); delete remains Tier 2."""

    def _login(self, client, username, password):
        client.post('/login', data={'username': username, 'password': password},
                    follow_redirects=True)

    def test_staff_can_access_create_form(self, client, db_session, admin_user,
                                          staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'staff', 'staff123')
        resp = client.get('/vendors/create')
        assert resp.status_code == 200

    def test_viewer_blocked_from_create(self, client, db_session, admin_user,
                                        viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'viewer', 'viewer123')
        resp = client.get('/vendors/create', follow_redirects=True)
        assert resp.status_code == 200
        assert b'permission' in resp.data or b'Only' in resp.data

    def test_staff_can_access_edit_form(self, client, db_session, admin_user,
                                        staff_user, accountant_user, main_branch):
        from app.vendors.models import Vendor
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'accountant', 'accountant123')
        client.post('/vendors/create', data={
            'code': 'V-PERM-TEST', 'name': 'Perm Test Co.', 'is_active': 'y',
        }, follow_redirects=True)
        vendor = Vendor.query.filter_by(code='V-PERM-TEST').first()
        assert vendor is not None
        client.get('/logout')
        self._login(client, 'staff', 'staff123')
        resp = client.get(f'/vendors/{vendor.id}/edit')
        assert resp.status_code == 200

    def test_staff_still_blocked_from_delete(self, client, db_session, admin_user,
                                              staff_user, accountant_user, main_branch):
        from app.vendors.models import Vendor
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'accountant', 'accountant123')
        client.post('/vendors/create', data={
            'code': 'V-DEL-PERM', 'name': 'Del Perm Co.', 'is_active': 'y',
        }, follow_redirects=True)
        vendor = Vendor.query.filter_by(code='V-DEL-PERM').first()
        client.get('/logout')
        self._login(client, 'staff', 'staff123')
        client.post(f'/vendors/{vendor.id}/delete', follow_redirects=True)
        assert Vendor.query.get(vendor.id) is not None
```

- [ ] **Step 2: Run to verify baseline**

```powershell
cd C:\envs\cas; pytest tests/integration/test_vendor_views.py::TestVendorStaffPermissions -v
```

Expected: `test_staff_can_access_create_form` FAIL, `test_staff_can_access_edit_form` FAIL, viewer/delete tests PASS.

- [ ] **Step 3: Add `staff_or_above_required` decorator to `app/vendors/views.py`**

Insert after the closing `return decorated_function` / `return` of `accountant_or_admin_required` (around line 30):

```python
def staff_or_above_required(f):
    """Tier 1 vendor ops — staff, accountant, and admin allowed."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function
```

- [ ] **Step 4: Swap decorator on `create()` and `edit()` in `app/vendors/views.py`**

- ~line 123: `@accountant_or_admin_required` on `create()` → `@staff_or_above_required`
- ~line 193: `@accountant_or_admin_required` on `edit(id)` → `@staff_or_above_required`
- ~line 280: `@accountant_or_admin_required` on `delete(id)` — **leave unchanged**

- [ ] **Step 5: Remove `test_staff_cannot_edit` from `TestVendorCrud`**

In `tests/integration/test_vendor_views.py`, find and delete the `test_staff_cannot_edit` method from `TestVendorCrud` (the new `TestVendorStaffPermissions` covers both directions correctly). Keep `test_staff_cannot_delete` and `test_staff_can_view_detail`.

- [ ] **Step 6: Update vendor list template — show "+ Create Vendor" for staff**

```powershell
cd C:\envs\cas; grep -n "Create Vendor\|accountant.*admin" app/vendors/templates/vendors/list.html | head -20
```

Find the role-check on the Create Vendor button. Change:
```html
{% if current_user.role in ['accountant', 'admin'] %}
```
to:
```html
{% if current_user.role in ['staff', 'accountant', 'admin'] %}
```

Only change the gate on the Create button — leave any delete-button gates untouched.

- [ ] **Step 7: Run all vendor tests**

```powershell
cd C:\envs\cas; pytest tests/integration/test_vendor_views.py -v
```

Expected: All PASS.

- [ ] **Step 8: Commit**

```powershell
cd C:\envs\cas
git add -f tests/integration/test_vendor_views.py
git add app/vendors/views.py app/vendors/templates/vendors/list.html
git commit -m "feat: staff can create/edit vendors (Tier 1 permission split)"
git push
```

---

## Task 2 — Fix AP voucher Tier 1 permissions

**Files:** `app/purchase_bills/views.py`, `app/purchase_bills/templates/purchase_bills/list.html`, `app/purchase_bills/templates/purchase_bills/detail.html`, `tests/integration/test_purchase_bill_views.py`

- [ ] **Step 1: Write failing tests — add `TestStaffPermissions` to `tests/integration/test_purchase_bill_views.py`**

Append to the end of the file:

```python
class TestStaffPermissions:
    """Staff can create/edit/void draft APVs (Tier 1); post/cancel blocked (Tier 2)."""

    def _login(self, client, username, password):
        client.post('/login', data={'username': username, 'password': password},
                    follow_redirects=True)

    def test_staff_can_access_create_form(self, client, db_session, admin_user,
                                          staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'staff', 'staff123')
        resp = client.get('/purchase-bills/create')
        assert resp.status_code == 200

    def test_viewer_blocked_from_create(self, client, db_session, admin_user,
                                        viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'viewer', 'viewer123')
        resp = client.get('/purchase-bills/create', follow_redirects=True)
        assert b'permission' in resp.data or b'Only' in resp.data

    def test_staff_blocked_from_post(self, client, db_session, admin_user,
                                     staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'staff', 'staff123')
        resp = client.post('/purchase-bills/99999/post', follow_redirects=True)
        assert b'permission' in resp.data or b'Only' in resp.data

    def test_staff_blocked_from_cancel(self, client, db_session, admin_user,
                                       staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'staff', 'staff123')
        resp = client.post('/purchase-bills/99999/cancel', follow_redirects=True)
        assert b'permission' in resp.data or b'Only' in resp.data
```

- [ ] **Step 2: Run to verify baseline**

```powershell
cd C:\envs\cas; pytest tests/integration/test_purchase_bill_views.py::TestStaffPermissions -v
```

Expected: `test_staff_can_access_create_form` FAIL; viewer/post/cancel blocked tests PASS.

- [ ] **Step 3: Add `staff_or_above_required` decorator to `app/purchase_bills/views.py`**

Insert after the closing `return decorated_function` of `accountant_or_admin_required` (~line 202):

```python
def staff_or_above_required(f):
    """Tier 1 AP voucher ops — staff, accountant, and admin allowed."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function
```

- [ ] **Step 4: Swap decorator on Tier 1 routes in `app/purchase_bills/views.py`**

- ~line 459: `create()` → `@staff_or_above_required`
- ~line 622: `edit(id)` → `@staff_or_above_required`
- ~line 1085: `void(id)` → `@staff_or_above_required`
- ~line 1163: `upload_attachment(id)` → `@staff_or_above_required`
- ~lines 790, 846, 1291: `post()`, `cancel()`, `delete_attachment()` — **leave as `@accountant_or_admin_required`**

- [ ] **Step 5: Update AP voucher list template — show "+ New AP Voucher" for staff**

```powershell
cd C:\envs\cas; grep -n "New AP\|purchase-bills/create\|accountant.*admin" app/purchase_bills/templates/purchase_bills/list.html | head -20
```

Change the role gate on the New AP Voucher button from:
```html
{% if current_user.role in ['accountant', 'admin'] %}
```
to:
```html
{% if current_user.role in ['staff', 'accountant', 'admin'] %}
```

- [ ] **Step 6: Update AP voucher detail template — Edit/Void visible for staff on drafts**

```powershell
cd C:\envs\cas; grep -n "Edit\|edit.*draft\|Void\|void.*draft\|Post\|accountant.*admin" app/purchase_bills/templates/purchase_bills/detail.html | head -30
```

For the Edit button gate (draft only):
```html
{% if current_user.role in ['staff', 'accountant', 'admin'] and bill.status == 'draft' %}
    <!-- Edit button -->
{% endif %}
```

For the Void button gate (draft only):
```html
{% if current_user.role in ['staff', 'accountant', 'admin'] and bill.status == 'draft' %}
    <!-- Void form/button -->
{% endif %}
```

For the Post button gate — **must stay Tier 2**:
```html
{% if current_user.role in ['accountant', 'admin'] and bill.status == 'draft' %}
    <!-- Post button -->
{% endif %}
```

If Edit, Void, and Post share a single combined gate, split them into separate `{% if %}` blocks as shown above.

- [ ] **Step 7: Run all purchase bill tests**

```powershell
cd C:\envs\cas; pytest tests/integration/test_purchase_bill_views.py -v
```

Expected: All PASS. If any existing test breaks (staff-was-blocked assertion), update it to match the new Tier 1 behavior.

- [ ] **Step 8: Run full suite to check for regressions**

```powershell
cd C:\envs\cas; pytest -m "not slow" -q
```

Expected: All PASS.

- [ ] **Step 9: Commit**

```powershell
cd C:\envs\cas
git add -f tests/integration/test_purchase_bill_views.py
git add app/purchase_bills/views.py
git add app/purchase_bills/templates/purchase_bills/list.html
git add app/purchase_bills/templates/purchase_bills/detail.html
git commit -m "feat: staff can create/edit/void AP voucher drafts (Tier 1 permission split)"
git push
```

---

## Task 3 — Execute Section U: User Setup (U-01 to U-14)

**Pre-condition:** Dev server running at `http://localhost:5000`. Confirm with `browser_navigate` to `/login`.

**Login helper (use for each actor change):**
1. `browser_navigate("http://localhost:5000/login")`
2. `browser_click(selector="#username")` — removes readonly
3. `browser_type(selector="#username", text="<username>")`
4. `browser_click(selector="#password")`
5. `browser_type(selector="#password", text="<password>")`
6. `browser_click(selector="button[type='submit']")`
7. If branch selection: `browser_snapshot()`, click "Main Branch"

**Logout:** `browser_navigate("http://localhost:5000/logout")` — verify flash "logged out".

- [ ] **U-01: Admin pre-approves 3 emails**

```
Login as: admin / admin123
Navigate: /approved-emails
Add email: testaccountant@testcas.com (notes: Run 2)
Add email: teststaff@testcas.com
Add email: testviewer@testcas.com
Snapshot — verify all 3 appear as "Available" (unused)
```
Result: ✅ / ❌

- [ ] **U-02: Register testaccountant**

```
Navigate: /register
Fill username: testaccountant
Fill email: testaccountant@testcas.com
Fill full_name: Test Accountant
Click #password-field, type: TestAcc!Pass123
Click confirm password field, type: TestAcc!Pass123
Submit
Verify: Redirected to /login, flash contains "pending admin approval"
```
Result: ✅ / ❌

- [ ] **U-03: Register teststaff**

```
Navigate: /register
Fill username: teststaff, email: teststaff@testcas.com, full_name: Test Staff
Click #password-field, type: TestStf!Pass123
Click confirm, type: TestStf!Pass123
Submit → verify "pending admin approval"
```
Result: ✅ / ❌

- [ ] **U-04: Register testviewer**

```
Navigate: /register
Fill username: testviewer, email: testviewer@testcas.com, full_name: Test Viewer
Click #password-field, type: TestVwr!Pass123
Click confirm, type: TestVwr!Pass123
Submit → verify "pending admin approval"
```
Result: ✅ / ❌

- [ ] **U-05: Admin activates testaccountant → Accountant role**

```
Navigate: /users
Find testaccountant → click Edit
Check "Active" checkbox
Set role = Accountant
Save → verify flash "updated successfully"
```
Result: ✅ / ❌

- [ ] **U-06: Admin activates teststaff → Staff role**

```
Navigate: /users → teststaff → Edit
Check "Active", set role = Staff
Save → verify "updated successfully"
```
Result: ✅ / ❌

- [ ] **U-07: Admin activates testviewer (role stays Viewer)**

```
Navigate: /users → testviewer → Edit
Check "Active" (role stays Viewer)
Save → verify "updated successfully"
```
Result: ✅ / ❌

- [ ] **U-08: testviewer dashboard checks**

```
Logout → Login as: testviewer / TestVwr!Pass123
Select Main Branch
Snapshot dashboard
Verify: Welcome flash present
Verify: id="topbarNewBtn" NOT in page source
Verify: "Action Items" NOT in page
Verify: "User Management" NOT in page
Verify: "VAT Categories" NOT in page
```
Result: ✅ / ❌

- [ ] **U-09: testviewer logout**

```
Logout → verify "logged out successfully"
```
Result: ✅ / ❌

- [ ] **U-10: teststaff dashboard checks**

```
Login as: teststaff / TestStf!Pass123 → Main Branch
Snapshot dashboard
Verify: id="topbarNewBtn" IN page
Verify: "Action Items" IN page
Verify: "User Management" NOT in page
Verify: "VAT Categories" NOT in page
```
Result: ✅ / ❌

- [ ] **U-11: teststaff logout**

```
Logout → verify "logged out successfully"
```
Result: ✅ / ❌

- [ ] **U-12: testaccountant dashboard checks**

```
Login as: testaccountant / TestAcc!Pass123 → Main Branch
Snapshot dashboard
Verify: id="topbarNewBtn" IN page
Verify: "Action Items" IN page
Verify: "VAT Categories" IN page
Verify: "Audit Log" IN page
Verify: "User Management" NOT in page
```
Result: ✅ / ❌

- [ ] **U-13: testaccountant logout**

```
Logout → verify "logged out successfully"
```
Result: ✅ / ❌

- [ ] **U-14: Admin full nav check**

```
Login as: admin / admin123 → Main Branch
Snapshot dashboard
Verify: "User Management" IN page
Verify: "Approved Emails" IN page
Verify: "Company Settings" IN page
Verify: "Audit Log" IN page
Verify: "VAT Categories" IN page
```
Result: ✅ / ❌

**Section U: __ / 14 PASS**

---

## Task 4 — Execute Section V: Vendor CRUD (V-01 to V-14)

**Note:** After V-04 and V-05, record V-TEST and V-DEL vendor IDs from the detail page URL (e.g., `/vendors/42`). Use these IDs for direct navigation in V-07 through V-14.

**Delete modal:** Vendor delete requires clicking a Delete button that opens a confirmation modal — fill any reason field and submit the modal form (no JS `confirm()`).

- [ ] **V-01: testviewer — list renders, no Create button**

```
Login as: testviewer / TestVwr!Pass123 → Main Branch
Navigate: /vendors
Snapshot
Verify: Page renders, vendor list visible
Verify: "+ Create Vendor" button NOT present
```
Result: ✅ / ❌

- [ ] **V-02: teststaff — list renders, Create button visible**

```
Logout → Login as: teststaff / TestStf!Pass123 → Main Branch
Navigate: /vendors
Snapshot
Verify: "+ Create Vendor" button IS present
```
Result: ✅ / ❌

- [ ] **V-03: testviewer blocked from /vendors/create**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /vendors/create
Snapshot
Verify: Redirected to dashboard with flash error (not create form)
```
Result: ✅ / ❌

- [ ] **V-04: teststaff creates V-TEST**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /vendors/create
Fill code: V-TEST
Fill name: Test Vendor Co.
Select payment_terms: Net 30 (or first available option)
Select VAT category: click Choices.js wrapper → type first few chars → pick first match
Select WHT code: pick first available
Submit
Verify: Flash "Vendor created" (or "created successfully")
Navigate: /vendors → verify V-TEST in list as Active
Note V-TEST vendor ID from detail URL → VTEST_ID
```
Result: ✅ / ❌

- [ ] **V-05: teststaff creates V-DEL**

```
Navigate: /vendors/create
Fill code: V-DEL
Fill name: Delete Me Corp.
Submit
Verify: Flash "Vendor created"
Note V-DEL vendor ID → VDEL_ID
```
Result: ✅ / ❌

- [ ] **V-06: testviewer views V-TEST detail**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /vendors/<VTEST_ID>
Snapshot
Verify: Code, name, payment terms, VAT category, WHT codes all visible
Verify: No "Edit" button, no "Delete" button
```
Result: ✅ / ❌

- [ ] **V-07: testviewer blocked from edit**

```
Navigate: /vendors/<VTEST_ID>/edit
Snapshot
Verify: Redirected with flash error (not edit form)
```
Result: ✅ / ❌

- [ ] **V-08: teststaff edits V-TEST**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /vendors/<VTEST_ID>/edit
Fill phone: 09171234567
Fill address: 123 Test St.
Save
Verify: Flash "Vendor updated"
Navigate: /vendors/<VTEST_ID> → verify phone and address visible
```
Result: ✅ / ❌

- [ ] **V-09: testviewer blocked from deactivate (edit page itself)**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /vendors/<VTEST_ID>/edit
Verify: Blocked — redirected with flash error
```
Result: ✅ / ❌

- [ ] **V-10: teststaff deactivates V-TEST**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /vendors/<VTEST_ID>/edit
Uncheck "Active" checkbox
Save
Verify: Flash "Vendor updated"
Verify: V-TEST detail shows "Inactive"
```
Result: ✅ / ❌

- [ ] **V-11: teststaff re-activates V-TEST** *(required — vendor must be active for AP section)*

```
Navigate: /vendors/<VTEST_ID>/edit
Check "Active" checkbox
Save
Verify: Flash "Vendor updated"
Verify: V-TEST detail shows "Active"
```
Result: ✅ / ❌

- [ ] **V-12: testviewer blocked from deleting V-DEL**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /vendors/<VDEL_ID>
Verify: No "Delete" button visible
(If attempting direct form POST — verify redirected with error)
Verify: V-DEL still in /vendors list
```
Result: ✅ / ❌

- [ ] **V-13: teststaff blocked from deleting V-DEL**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /vendors/<VDEL_ID>
Verify: No "Delete" button visible
(Attempt direct POST if needed — verify error)
Verify: V-DEL still in list
```
Result: ✅ / ❌

- [ ] **V-14: testaccountant deletes V-DEL + audit check**

```
Logout → Login as: testaccountant / TestAcc!Pass123
Navigate: /vendors/<VDEL_ID>
Click "Delete" → fill modal if prompted → confirm / submit
Verify: Flash "Vendor deleted"
Verify: V-DEL no longer in /vendors list
Navigate: /audit-log
Filter/search: module=vendor, action=delete
Verify: Entry for "V-DEL - Delete Me Corp.", user=testaccountant, old_values contains vendor data
```
Result: ✅ / ❌

**Section V: __ / 14 PASS**

---

## Task 5 — Execute Section AP: AP Voucher CRUD (AP-01 to AP-24)

**DB Baseline — record BEFORE AP-04:**
```
Login as: testaccountant / TestAcc!Pass123
Navigate: /dashboard → find "Accounts Payable" card
Record: baseline payables_total = ________  payables_count = ________
```

**Bill IDs:** After AP-04 note the bill number (e.g., AP-2026-06-0001) and URL ID → call it `BILL1_ID`. After AP-19 note `BILL2_ID`.

**Creating a draft bill (form fields):**
- Vendor: Choices.js — type "Test Vendor" → pick "Test Vendor Co."
- bill_date: today in YYYY-MM-DD
- due_date: today + 30 days
- Line item: description=`Test Expense`, amount=`11200`, VAT category=first available (12%), expense account=first leaf Expenses account, EWT=first available
- Leave vendor_invoice_number blank for initial create

- [ ] **AP-01: testviewer — AP list, no New button**

```
Login as: testviewer / TestVwr!Pass123 → Main Branch
Navigate: /purchase-bills
Snapshot
Verify: List renders
Verify: "+ New AP Voucher" button NOT present
```
Result: ✅ / ❌

- [ ] **AP-02: teststaff — AP list, New button visible**

```
Logout → Login as: teststaff / TestStf!Pass123 → Main Branch
Navigate: /purchase-bills
Snapshot
Verify: "+ New AP Voucher" button IS present
```
Result: ✅ / ❌

- [ ] **AP-03: testviewer blocked from create**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/create
Snapshot
Verify: Redirected with flash error
```
Result: ✅ / ❌

- [ ] **AP-04: teststaff creates first draft bill**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/create
Select vendor: "Test Vendor Co." via Choices.js
Fill bill_date: today
Fill due_date: today + 30 days
Add line item: description=Test Expense, amount=11200
  Select VAT category: first available (12%)
  Select expense account: first leaf Expenses account
  Select EWT code: first available
Leave vendor_invoice_number blank
Click "Enter Bill"
Verify: Flash success (APV created / draft created)
Verify: Status = Draft
Verify: Bill number = AP-YYYY-MM-XXXX
Verify: Subtotal = ₱11,200, VAT = ₱1,200
Note URL ID → BILL1_ID
```
Result: ✅ / ❌

- [ ] **AP-05: testviewer views draft detail**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Snapshot
Verify: Status = Draft
Verify: JE preview section visible (debit/credit lines)
Verify: No "Post", "Void", "Edit" buttons for viewer
```
Result: ✅ / ❌

- [ ] **AP-06: teststaff views draft detail**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Snapshot
Verify: "Edit" button visible
Verify: "Void" button visible
Verify: "Post" button NOT visible
```
Result: ✅ / ❌

- [ ] **AP-07: testaccountant views draft detail**

```
Logout → Login as: testaccountant / TestAcc!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Snapshot
Verify: "Edit" button visible
Verify: "Void" button visible
Verify: "Post" button visible
```
Result: ✅ / ❌

- [ ] **AP-08: testviewer blocked from edit**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>/edit
Snapshot
Verify: Redirected with flash error
```
Result: ✅ / ❌

- [ ] **AP-09: teststaff edits draft**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>/edit
Fill vendor_invoice_number: INV-TEST-001
Fill vendor_invoice_date: today
Fill reference: PO-2026-001
Save
Verify: Flash "APV updated" or "updated successfully"
Navigate: /purchase-bills/<BILL1_ID>
Verify: vendor_invoice_number = INV-TEST-001, reference = PO-2026-001
```
Result: ✅ / ❌

- [ ] **AP-10: testviewer blocked from upload**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Verify: No attachment upload UI visible for viewer
(If attempting direct POST to upload endpoint → verify error)
```
Result: ✅ / ❌

- [ ] **AP-11: teststaff uploads attachment + audit check**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Find attachment upload section
Upload a small file (create a tiny PDF/PNG if needed — any valid file works)
Verify: File appears in attachments list with filename and size
Navigate: /audit-log, filter module=purchase_bill_attachment, action=create
Verify: Entry for BILL1, user=teststaff
```
Result: ✅ / ❌

- [ ] **AP-12: testviewer downloads attachment**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Click attachment download link
Verify: File downloads (200 response / browser save dialog)
```
Result: ✅ / ❌

- [ ] **AP-13: teststaff downloads attachment**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Click attachment download link
Verify: File downloads
```
Result: ✅ / ❌

- [ ] **AP-14: testviewer blocked from post**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Verify: No "Post" button visible
```
Result: ✅ / ❌

- [ ] **AP-15: teststaff blocked from post**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Verify: No "Post" button visible
```
Result: ✅ / ❌

- [ ] **AP-16: testaccountant posts bill + audit check**

```
Logout → Login as: testaccountant / TestAcc!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Click "Post" → confirm modal → submit
Verify: Flash "APV posted" or "posted successfully"
Verify: Status = Posted
Verify: "Post" button gone, "Edit"/"Void" gone
Verify: "Cancel" button visible
Navigate: /audit-log, filter module=purchase_bill, action=post
Verify: Entry for BILL1, user=testaccountant
```
Result: ✅ / ❌

- [ ] **AP-17: testviewer views posted detail**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Snapshot
Verify: Status = Posted
Verify: Attachment still visible
Verify: No edit/cancel buttons
```
Result: ✅ / ❌

- [ ] **AP-18: teststaff views posted detail**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Snapshot
Verify: Status = Posted
Verify: No edit/void/cancel buttons
```
Result: ✅ / ❌

- [ ] **AP-19: teststaff creates second draft (for void test)**

```
Navigate: /purchase-bills/create
Select vendor: Test Vendor Co.
Fill bill_date: today, due_date: today+30
Add line item: description=Test Expense 2, amount=11200, same VAT/account/EWT as AP-04
Leave vendor_invoice_number blank
Submit
Verify: Status = Draft, new bill number (next in sequence)
Note URL ID → BILL2_ID
```
Result: ✅ / ❌

- [ ] **AP-20: testviewer blocked from void**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL2_ID>
Verify: No "Void" button visible
```
Result: ✅ / ❌

- [ ] **AP-21: teststaff voids second draft + audit check**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL2_ID>
Click "Void"
Fill reason: Voided for testing purposes - Run 2
Fill void_date: today
Confirm / submit
Verify: Flash "APV voided"
Verify: Status = Voided
Navigate: /audit-log, filter module=purchase_bill, action=void
Verify: Entry for BILL2, user=teststaff, notes contains void reason
```
Result: ✅ / ❌

- [ ] **AP-22: testviewer blocked from cancel**

```
Logout → Login as: testviewer / TestVwr!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Verify: No "Cancel" button visible
```
Result: ✅ / ❌

- [ ] **AP-23: teststaff blocked from cancel**

```
Logout → Login as: teststaff / TestStf!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Verify: No "Cancel" button visible
```
Result: ✅ / ❌

- [ ] **AP-24: testaccountant cancels posted bill + audit check**

```
Logout → Login as: testaccountant / TestAcc!Pass123
Navigate: /purchase-bills/<BILL1_ID>
Click "Cancel"
Fill reason: Cancelled for testing purposes - Run 2
Fill reversal_date: today
Confirm / submit
Verify: Flash "APV cancelled"
Verify: Status = Cancelled
Verify: Reversal JE created (visible in JE list or detail)
Navigate: /audit-log, filter module=purchase_bill, action=cancel
Verify: Entry for BILL1, user=testaccountant, notes contains cancel reason
```
Result: ✅ / ❌

**Section AP: __ / 24 PASS**

---

## Task 6 — Execute Section DB: Dashboard Payables (DB-01 to DB-03)

**Pre-condition:** Baseline values were recorded before AP-04 (see Task 5 pre-condition block).

- [ ] **DB-01: After AP-04 — draft does NOT affect payables**

```
Login as: testaccountant / TestAcc!Pass123
Navigate: /dashboard → Accounts Payable card
Verify: payables_total = <baseline value recorded before AP-04>
Verify: payables_count = <baseline count>
(Draft bills must not be counted)
```
Result: ✅ / ❌

- [ ] **DB-02: After AP-16 — posted bill increases payables**

```
Navigate: /dashboard → Accounts Payable card
Verify: payables_count = baseline + 1
Verify: payables_total = baseline + BILL1 total_amount (₱11,200 − WT)
```
Result: ✅ / ❌

- [ ] **DB-03: After AP-24 — cancelled bill resets payables**

```
Navigate: /dashboard → Accounts Payable card
Verify: payables_total = baseline value (cancelled bill removed from outstanding)
Verify: payables_count = baseline count
```
Result: ✅ / ❌

**Section DB: __ / 3 PASS**

---

## Task 7 — Execute Section AT: Audit Trail (AT-01 to AT-07)

**All checks by testaccountant (has Audit Log access). Navigate to `/audit-log` and use module/action filters.**

- [ ] **AT-01: Vendor create — V-TEST**

```
Login as: testaccountant / TestAcc!Pass123
Navigate: /audit-log
Filter: module=vendor, action=create
Verify: Entry for "V-TEST - Test Vendor Co.", user=teststaff
Verify: new_values contains code=V-TEST, name=Test Vendor Co., is_active=true
```
Result: ✅ / ❌

- [ ] **AT-02: Vendor update — V-TEST phone/address**

```
Navigate: /audit-log, filter module=vendor, action=update
Verify: Entry for "V-TEST - Test Vendor Co.", user=teststaff
Verify: old_values and new_values show phone and address changes
```
Result: ✅ / ❌

- [ ] **AT-03: Vendor delete — V-DEL**

```
Navigate: /audit-log, filter module=vendor, action=delete
Verify: Entry for "V-DEL - Delete Me Corp.", user=testaccountant
Verify: old_values contains full vendor snapshot
```
Result: ✅ / ❌

- [ ] **AT-04: AP voucher create — BILL1**

```
Navigate: /audit-log, filter module=purchase_bill, action=create
Verify: Entry for BILL1 number + vendor name, user=teststaff
Verify: new_values contains subtotal, vat_amount, total_amount, status=draft
```
Result: ✅ / ❌

- [ ] **AT-05: AP voucher post — BILL1**

```
Navigate: /audit-log, filter module=purchase_bill, action=post
Verify: Entry for BILL1 number, user=testaccountant
```
Result: ✅ / ❌

- [ ] **AT-06: AP voucher void — BILL2**

```
Navigate: /audit-log, filter module=purchase_bill, action=void
Verify: Entry for BILL2 number, user=teststaff
Verify: notes contains "Voided for testing purposes - Run 2"
```
Result: ✅ / ❌

- [ ] **AT-07: AP voucher cancel — BILL1**

```
Navigate: /audit-log, filter module=purchase_bill, action=cancel
Verify: Entry for BILL1 number, user=testaccountant
Verify: notes contains "Cancelled for testing purposes - Run 2"
```
Result: ✅ / ❌

**Section AT: __ / 7 PASS**

---

## Task 8 — Cleanup (C-01 to C-05)

- [ ] **C-01: testaccountant deletes V-TEST**

```
Login as: testaccountant / TestAcc!Pass123
Navigate: /vendors/<VTEST_ID>
Click Delete → confirm modal → submit
Verify: Flash "Vendor deleted"
Verify: V-TEST not in /vendors list
```
Result: ✅ / ❌

- [ ] **C-02: Admin deletes testaccountant user**

```
Logout → Login as: admin / admin123
Navigate: /users
Find testaccountant → delete (via edit or delete action)
Verify: Removed from user list
```
Result: ✅ / ❌

- [ ] **C-03: Admin deletes teststaff user**

```
Navigate: /users → find teststaff → delete
Verify: Removed
```
Result: ✅ / ❌

- [ ] **C-04: Admin deletes testviewer user**

```
Navigate: /users → find testviewer → delete
Verify: Removed
```
Result: ✅ / ❌

- [ ] **C-05: Verify approved emails page state**

```
Navigate: /approved-emails
Verify: testaccountant@testcas.com shows as "Used" (no linked user — expected, no action needed)
Verify: teststaff@testcas.com shows as "Used"
Verify: testviewer@testcas.com shows as "Used"
```
Result: ✅ / ❌

**Cleanup: __ / 5 PASS**

---

## Run 2 Final Scorecard

| Section | Scenarios | Pass | Fail |
|---------|-----------|------|------|
| U — Users | 14 | | |
| V — Vendor | 14 | | |
| AP — AP Voucher | 24 | | |
| DB — Dashboard | 3 | | |
| AT — Audit Trail | 7 | | |
| Cleanup | 5 | | |
| **Total** | **67** | | |

---

## Commit after test run

```powershell
cd C:\envs\cas
git add -f docs/superpowers/plans/2026-06-12-run2-vendor-apv-test-plan.md
git commit -m "docs: Run 2 vendor+APV test plan and results"
git push
```
