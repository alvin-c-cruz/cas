# Project Foundations
### Headstart document for CAS and THCI independent workspaces

This document captures the architectural decisions, development rules, reusable patterns, and project state established during joint development. When either project moves to its own workspace, copy the relevant sections into that workspace's `CLAUDE.md`.

---

## 1. Non-Negotiable Development Rules

These rules apply to both projects and must be re-stated in any new workspace's `CLAUDE.md`.

### Never use JavaScript popups
Never use `confirm()`, `alert()`, or `prompt()`. Always build custom HTML modal forms with CSRF tokens instead. Reason: JS popups are unstyled, untestable, and violate the UX standard established across both projects.

### Model changes require approval
Any database model change — new column, new table, renamed field, changed constraint — must be proposed and explicitly approved by the user before touching any `models.py` file or running migrations. Describe: field name, type, nullable, default, and migration impact.

### Propose before seeding or bulk-writing data
Always show proposed data (COA structure, seed content, user list, schema changes) for review before running any script that writes to the database. Do not seed and ask forgiveness.

### Audit trail in every CRUD test
After every Create / Update / Delete operation (and after any approval/rejection), navigate to the audit log and verify an entry exists. Check: action type is correct, record is referenced, actor (username) is correct. A test that only checks the UI has not fully verified the operation.

### Responsive design on all UI
All UI must work on desktop, tablet, and mobile. Follow established breakpoints. Never build desktop-only layouts.

### Use skill-creator before creating or editing skills
Always invoke the `skill-creator` skill before creating or modifying any skill document. Never edit `SKILL.md` files directly.

---

## 2. Flask Architecture Patterns

Both projects use Flask with a blueprint-based modular architecture. These patterns are proven and should be continued.

### Blueprint structure
Each feature area is a blueprint registered in the app factory. Blueprints own their routes, templates, and (optionally) forms. Keep business logic out of route functions — extract to service functions when routes grow long.

### Approval workflow pattern
Established in CAS accounts module. Any write operation by a non-sole-accountant goes to a pending queue for review. Key components:
- `ChangeRequest` model: stores `change_type`, `change_data` (JSON), `status`, `requested_by`, `reviewed_by`, `reviewed_at`, `rejection_reason`
- `can_auto_approve()`: returns True only if the requesting user is the sole accountant. Admins always go to pending.
- `can_be_approved_by(username)`: prevents self-approval when other reviewers exist.
- Three states: `pending` → `approved` or `rejected`
- Audit log entries: approvals log the change type (`create`/`update`/`delete`) with "Approved by {user}" in notes; rejections log `action='reject'` (not the original change type — this was a bug that was fixed).

### Audit trail pattern
Every write operation calls `log_audit(module, action, record_id, record_identifier, old_values, new_values, notes)`. Auth events (login, logout, branch selection) are also logged. The audit log is filterable by branch, module, action, user, and date range.

### Role-based access
Roles: `admin`, `accountant`, `staff`, `viewer`. Use decorators for route-level enforcement. Template-level: check `current_user.role in ['accountant', 'admin']` to show/hide write actions. Staff and viewer see read-only views with a flash message explaining the restriction.

### No hardcoded values in templates
Use design tokens and CSS variables. Never hardcode colors, spacing, or font sizes inline — define them in the design system and reference by variable name.

---

## 3. Reusable Technical Solutions

### Hierarchical data — leaf-node rule
For tree-structured data (e.g., Chart of Accounts), determine whether a node is a "group" (non-posting) or "leaf" (posting) dynamically from the data — no model field needed:

```python
has_children = {a.parent_id for a in accounts if a.parent_id}
is_header = account.id in has_children
```

Any node with children is a GROUP; any node without children is a posting/leaf node. This handles arbitrary depth automatically and updates without migrations when the hierarchy changes.

### Depth computation for indentation
Compute display depth via memoized recursion in the view:

```python
depth_cache = {}
def get_depth(account_id):
    if account_id in depth_cache:
        return depth_cache[account_id]
    acct = id_to_account.get(account_id)
    if not acct or not acct.parent_id:
        depth_cache[account_id] = 0
        return 0
    d = 1 + get_depth(acct.parent_id)
    depth_cache[account_id] = d
    return d
```

Pass `depth` to the template and use `padding-left: {{ row.depth * 18 }}px` for indentation.

### Two-pass seeding for self-referential tables
When seeding data with parent-child FK relationships (e.g., accounts with `parent_id`), use two passes:
1. Pass 1: insert all rows without parent links
2. Pass 2: set `parent_id` for each row using a lookup dict

This avoids FK ordering issues regardless of the order accounts are defined in the seed file.

### Custom delete modal (no JS confirm)
```html
<button type="button" onclick="showDeleteModal(id, code, name)">🗑️</button>

<div id="delete-modal" class="modal" style="display:none;">
  <div class="modal-content">
    <h3>Delete [Entity]</h3>
    <p id="delete-modal-message"></p>
    <form id="delete-form" method="POST" action="">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="btn btn-danger">Confirm Delete</button>
      <button type="button" onclick="closeDeleteModal()">Cancel</button>
    </form>
  </div>
</div>

<script>
function showDeleteModal(id, code, name) {
    document.getElementById('delete-form').action = '/entity/' + id + '/delete';
    document.getElementById('delete-modal-message').textContent = 
        'Are you sure you want to delete ' + code + ' - ' + name + '?';
    document.getElementById('delete-modal').style.display = 'flex';
}
function closeDeleteModal() {
    document.getElementById('delete-modal').style.display = 'none';
}
</script>
```

### COA homepage pattern (Option A)
Established in CAS. Reusable for any list page with type-based filtering:
- Summary cards at top: one per category, clickable to activate tab filter
- Type filter tabs: All + one per category
- Live search: filters by name and code simultaneously
- Combined JS filtering: tab + search applied together, no page reload
- Row count footer: "Showing X of Y accounts"
- Empty state: shown when filters produce zero results

---

## 4. Playwright / Browser Testing

### CAS login — readonly password field
The CAS login form uses a `readonly` attribute on the password field as anti-autofill protection. Playwright's `fill()` will timeout. Fix: click the field first (JS removes readonly), then type:

```python
page.click('#password')
page.fill('#password', 'password_value')
# or
page.type('#password', 'password_value')
```

### Test credentials (CAS)
| Role | Username | Password |
|------|----------|----------|
| admin | admin | Admin@2024! |
| accountant | accountant | Acct@2024! |
| staff | staff | Staff@2024! |
| viewer | viewer | View@2024! |

### Strict mode — avoid ambiguous selectors
When clicking elements by text (e.g., `text=Approve`), strict mode may match multiple elements. Prefer specific selectors: `button[title="Approve"]`, or use `data-` attributes on elements you need to target in tests.

### Audit trail verification in tests
After every write operation, call `page.evaluate()` to read the most recent audit log entry and assert the action type, record identifier, and actor match expectations. Don't just check the UI outcome.

---

## 5. CAS — Project State

**What it is:** Accounting-first ERP for Philippine SMEs, BIR-compliant. Expanding into procurement, billing, and collection.

**Core modules built:**
- Chart of Accounts (full construction company COA, 173 accounts, approval workflow, leaf-node rule, Option A homepage)
- User management with role-based access (admin, accountant, staff, viewer)
- Branch management (multi-branch support)
- Audit log (filterable, full trail of all writes and auth events)
- BIR compliance features (in progress)

**Architecture decisions:**
- SQLAlchemy with SQLite (file-based, suitable for SME scale)
- All model changes require user approval before implementation
- Approval workflow for all account mutations (create, edit, delete)
- `can_auto_approve()` — only sole accountants can auto-approve; admins always go to pending

**Pending work (as of 2026-06-08):**
- `base.html` CSS/JS extraction (~999 lines of embedded CSS to move to static files)
- Dead macros removal in `macros.html` (`action_buttons`, `account_type_badge`, `normal_balance`)
- pytest integration tests for COA POST routes (create, edit, delete, approve, reject)
- Procurement module (planned)
- Billing and collection module (planned)

**Key files:**
- `app/accounts/views.py` — COA routes, approval workflow
- `app/accounts/templates/accounts/list.html` — Option A homepage
- `app/seeds/seed_data.py` — 173-account construction company COA
- `scripts/cas/reset_data.py` — resets DB to clean state (1 branch, 4 users, full COA)

---

## 6. THCI — Project State

**What it is:** Vertical ERP for health/wellness businesses. POS-first, expanding into full ERP (inventory, patient/client records, billing, scheduling, reporting).

**Core modules built:**
- Blueprint-based modular architecture with automatic registration
- Role-based access control with `@roles_accepted` decorator
- Philippine timezone utilities (`ph_today()`)
- Git-based versioning system
- Audit trail system
- Strict design token system (no hardcoded values, enforced by pre-commit hook)
- POS module (in progress)

**Architecture decisions:**
- Port 9000
- Design tokens are non-negotiable — pre-commit hook blocks hardcoded values
- Advanced blueprint pattern with automatic registration (no manual blueprint list)
- Database: `the_health_collective_inc.db`

**Planned modules:**
- POS (Point of Sale)
- Inventory management
- Patient/client records
- Billing and collection
- Scheduling/appointments
- Financial reporting

**Key differences from CAS:**
- Health/wellness domain (not pure accounting)
- POS as a core function, not an add-on
- Stricter design system enforcement at commit level

---

## 7. When to Split into Separate Workspaces

Split a project into its own workspace when:
- Claude regularly runs out of context understanding project structure before doing real work
- Skills and docs from the other project create noise rather than value
- The project has 8+ active modules with distinct domain logic

**Planned split:**
1. **Accounting ERPs workspace** — CAS + future accounting projects (shared BIR, COA, approval workflow skills)
2. **THCI workspace** — health/wellness ERP, fully independent
3. **This workspace** — retained as shared skills library and cross-project reference

When splitting, copy this document plus the project-specific sections into the new workspace's `CLAUDE.md`, and bring over the relevant skills from `docs/skills/`.
