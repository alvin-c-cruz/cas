# Journals Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single "Journal Entries" page with a dedicated "Journals" sidebar section containing four specialized filtered journal views (AP Journal, Cash Receipts, Cash Disbursements, Journal Voucher).

**Architecture:** New `app/journals/` blueprint owns four list views; `journal_entries` blueprint keeps all CRUD. Journals blueprint queries `JournalEntry` with `entry_type` filters. No model changes — existing `entry_type` field already discriminates all entry origins.

**Tech Stack:** Flask blueprints, SQLAlchemy, Jinja2, existing CSS design tokens (no new dependencies)

---

## File Map

**Create:**
- `app/journals/__init__.py` — empty blueprint package init
- `app/journals/views.py` — four journal routes + redirects for CR/CD
- `app/journals/templates/journals/ap_journal.html` — AP Journal list
- `app/journals/templates/journals/voucher.html` — Journal Voucher list
- `tests/integration/test_journals.py` — integration tests

**Modify:**
- `app/journal_entries/utils.py` — add `generate_jv_number()`
- `app/journal_entries/views.py` — use `generate_jv_number()` in create GET; redirect `list_entries` to journals.voucher
- `app/__init__.py` — register `journals_bp`
- `app/templates/base.html` — add Journals sidebar section, remove JE from Ledger, rename topbar item

---

## Task 1: JV Number Generator

**Files:**
- Modify: `app/journal_entries/utils.py`
- Modify: `app/journal_entries/views.py` (one line)
- Test: `tests/unit/test_journal_utils.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_journal_utils.py`:

```python
import pytest
from app import create_app, db
from app.journal_entries.utils import generate_jv_number
from app.journal_entries.models import JournalEntry
from app.branches.models import Branch
from app.users.models import User
import os


@pytest.fixture(scope='function')
def app_ctx():
    os.environ['SECRET_KEY'] = 'test-secret-key'
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_generate_jv_number_first(app_ctx):
    """First JV for a branch uses sequence 0001."""
    with app_ctx.app_context():
        branch = Branch(name='Main', code='MAIN')
        db.session.add(branch)
        db.session.commit()
        result = generate_jv_number(branch.id)
        from app.utils import ph_now
        now = ph_now()
        expected_prefix = f'JV-{now.year}-{now.month:02d}-'
        assert result.startswith(expected_prefix)
        assert result.endswith('0001')


def test_generate_jv_number_increments(app_ctx):
    """Subsequent JVs increment the sequence."""
    with app_ctx.app_context():
        branch = Branch(name='Main', code='MAIN')
        user = User(username='acc', email='acc@test.com', full_name='A', role='accountant', is_active=True)
        user.set_password('pass')
        db.session.add_all([branch, user])
        db.session.commit()

        from app.utils import ph_now
        from datetime import date
        now = ph_now()
        existing = JournalEntry(
            entry_number=f'JV-{now.year}-{now.month:02d}-0001',
            entry_date=date.today(),
            description='Test',
            entry_type='adjustment',
            branch_id=branch.id,
            created_by_id=user.id,
            is_balanced=True,
            total_debit=0,
            total_credit=0,
            status='draft'
        )
        db.session.add(existing)
        db.session.commit()

        result = generate_jv_number(branch.id)
        assert result.endswith('0002')


def test_generate_jv_number_ignores_je_prefix(app_ctx):
    """Old JE-prefixed entries do not affect JV sequence."""
    with app_ctx.app_context():
        branch = Branch(name='Main', code='MAIN')
        user = User(username='acc', email='acc@test.com', full_name='A', role='accountant', is_active=True)
        user.set_password('pass')
        db.session.add_all([branch, user])
        db.session.commit()

        from datetime import date
        from app.utils import ph_now
        now = ph_now()
        old = JournalEntry(
            entry_number=f'JE-{now.year}-0099',
            entry_date=date.today(),
            description='Old style',
            entry_type='adjustment',
            branch_id=branch.id,
            created_by_id=user.id,
            is_balanced=True,
            total_debit=0,
            total_credit=0,
            status='draft'
        )
        db.session.add(old)
        db.session.commit()

        result = generate_jv_number(branch.id)
        assert result.endswith('0001')
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/test_journal_utils.py -v
```
Expected: FAIL — `generate_jv_number` not yet defined.

- [ ] **Step 3: Add `generate_jv_number` to utils**

In `app/journal_entries/utils.py`, append after `generate_entry_number`:

```python
def generate_jv_number(branch_id):
    """Generate next JV number for a branch: JV-YYYY-MM-NNNN. Resets each month."""
    from app.journal_entries.models import JournalEntry
    from app.utils import ph_now
    now = ph_now()
    prefix = f'JV-{now.year}-{now.month:02d}-'

    latest = JournalEntry.query.filter(
        JournalEntry.entry_number.like(f'{prefix}%'),
        JournalEntry.branch_id == branch_id
    ).order_by(JournalEntry.entry_number.desc()).first()

    if latest:
        try:
            last_num = int(latest.entry_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'
```

- [ ] **Step 4: Update `create` view to use `generate_jv_number`**

In `app/journal_entries/views.py`:

Change the import line from:
```python
from app.journal_entries.utils import generate_entry_number
```
to:
```python
from app.journal_entries.utils import generate_entry_number, generate_jv_number
```

In the `create` view, find the GET block (around line 193) and change:
```python
        form.entry_number.data = generate_entry_number(current_branch_id)
```
to:
```python
        form.entry_number.data = generate_jv_number(current_branch_id)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/unit/test_journal_utils.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```
git add app/journal_entries/utils.py app/journal_entries/views.py tests/unit/test_journal_utils.py
git commit -m "feat: add JV number generator (JV-YYYY-MM-NNNN) for Journal Voucher entries"
```

---

## Task 2: Journals Blueprint + Routes

**Files:**
- Create: `app/journals/__init__.py`
- Create: `app/journals/views.py`
- Modify: `app/__init__.py`
- Test: `tests/integration/test_journals.py` (routes return 200/302)

- [ ] **Step 1: Write failing route tests**

Create `tests/integration/test_journals.py`:

```python
import pytest
from app import create_app, db
from app.users.models import User
from app.branches.models import Branch
import os


@pytest.fixture(scope='function')
def setup(db_session):
    branch = Branch(name='Main', code='MAIN')
    db_session.add(branch)
    db_session.commit()

    users = {
        'admin': User(username='admin', email='admin@t.com', full_name='Admin',
                      role='admin', is_active=True),
        'accountant': User(username='accountant', email='acc@t.com', full_name='Acc',
                           role='accountant', is_active=True),
        'staff': User(username='staff', email='staff@t.com', full_name='Staff',
                      role='staff', is_active=True),
        'viewer': User(username='viewer', email='viewer@t.com', full_name='Viewer',
                       role='viewer', is_active=True),
    }
    for u in users.values():
        u.set_password('pass')
        u.branches.append(branch)
        db_session.add(u)
    db_session.commit()
    return users, branch


def login(client, username):
    client.post('/login', data={'username': username, 'password': 'pass'},
                follow_redirects=True)


def test_ap_journal_requires_login(client, setup):
    res = client.get('/journals/ap')
    assert res.status_code in (302, 401)


def test_ap_journal_accessible_all_roles(client, setup):
    users, branch = setup
    for role in ['admin', 'accountant', 'staff', 'viewer']:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
        login(client, role)
        res = client.get('/journals/ap')
        assert res.status_code == 200, f"{role} got {res.status_code} on /journals/ap"
        client.get('/logout')


def test_voucher_accessible_all_roles(client, setup):
    users, branch = setup
    for role in ['admin', 'accountant', 'staff', 'viewer']:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
        login(client, role)
        res = client.get('/journals/voucher')
        assert res.status_code == 200, f"{role} got {res.status_code} on /journals/voucher"
        client.get('/logout')


def test_cr_redirects_to_under_development(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'staff')
    res = client.get('/journals/cr')
    assert res.status_code == 302
    assert 'under_development' in res.location or 'Cash+Receipts' in res.location or 'Cash' in res.location


def test_cd_redirects_to_under_development(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'staff')
    res = client.get('/journals/cd')
    assert res.status_code == 302
    assert 'under_development' in res.location or 'Cash' in res.location


def test_journal_entries_redirects_to_voucher(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    res = client.get('/journal-entries')
    assert res.status_code == 302
    assert 'voucher' in res.location
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/integration/test_journals.py -v
```
Expected: FAIL — blueprint not yet registered.

- [ ] **Step 3: Create blueprint package**

Create `app/journals/__init__.py` (empty):
```python
```

Create `app/journals/views.py`:

```python
"""Journals — filtered list views over JournalEntry for each journal type."""
from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_required
from app import db
from app.journal_entries.models import JournalEntry
from datetime import datetime

journals_bp = Blueprint('journals', __name__, template_folder='templates')

VOUCHER_TYPES = ('reversal', 'adjustment', 'closing', 'opening', 'reclassification')


def _branch_id():
    return session.get('selected_branch_id')


def _date_defaults():
    year = datetime.now().year
    return request.args.get('date_from', f'{year}-01-01'), request.args.get('date_to', f'{year}-12-31')


def _apply_date_filter(query, date_from, date_to):
    if date_from:
        try:
            query = query.filter(JournalEntry.entry_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(JournalEntry.entry_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass
    return query


@journals_bp.route('/journals/ap')
@login_required
def ap_journal():
    from app.purchase_bills.models import PurchaseBill
    branch_id = _branch_id()
    date_from, date_to = _date_defaults()

    if branch_id:
        query = JournalEntry.query.filter(
            JournalEntry.entry_type == 'purchase',
            JournalEntry.branch_id == branch_id
        )
    else:
        query = JournalEntry.query.filter_by(branch_id=-1)

    query = _apply_date_filter(query, date_from, date_to)
    entries = query.order_by(JournalEntry.entry_date.desc()).all()

    references = [e.reference for e in entries if e.reference]
    bills = PurchaseBill.query.filter(PurchaseBill.bill_number.in_(references)).all() if references else []
    bill_map = {b.bill_number: b for b in bills}

    return render_template('journals/ap_journal.html',
                           entries=entries,
                           bill_map=bill_map,
                           date_from=date_from,
                           date_to=date_to)


@journals_bp.route('/journals/voucher')
@login_required
def voucher():
    branch_id = _branch_id()
    date_from, date_to = _date_defaults()
    status_filter = request.args.get('status', 'all')

    if branch_id:
        query = JournalEntry.query.filter(
            JournalEntry.entry_type.in_(VOUCHER_TYPES),
            JournalEntry.branch_id == branch_id
        )
    else:
        query = JournalEntry.query.filter_by(branch_id=-1)

    if status_filter != 'all':
        query = query.filter(JournalEntry.status == status_filter)
    query = _apply_date_filter(query, date_from, date_to)
    entries = query.order_by(JournalEntry.entry_date.desc()).all()

    return render_template('journals/voucher.html',
                           entries=entries,
                           date_from=date_from,
                           date_to=date_to,
                           status_filter=status_filter)


@journals_bp.route('/journals/cr')
@login_required
def cr_journal():
    return redirect(url_for('dashboard.under_development', feature='Cash Receipts Journal'))


@journals_bp.route('/journals/cd')
@login_required
def cd_journal():
    return redirect(url_for('dashboard.under_development', feature='Cash Disbursements Journal'))
```

- [ ] **Step 4: Register blueprint in `app/__init__.py`**

After the existing `from app.journal_entries.views import journal_entries_bp` import line, add:
```python
    from app.journals.views import journals_bp
```

After `app.register_blueprint(journal_entries_bp)`, add:
```python
    app.register_blueprint(journals_bp)
```

- [ ] **Step 5: Redirect `list_entries` in `journal_entries/views.py`**

Replace the entire body of the `list_entries` function (keep decorator and signature) with a single redirect:

Old function body (everything after the `def list_entries():` line through the `return render_template(...)` call):
```python
@journal_entries_bp.route('/journal-entries')
@login_required
def list_entries():
    """List all journal entries for the current branch."""
    # Get current branch from session
    from flask import session
    current_branch_id = session.get('selected_branch_id')
```

Replace the full function with:
```python
@journal_entries_bp.route('/journal-entries')
@login_required
def list_entries():
    """Redirect to Journal Voucher (journals section)."""
    return redirect(url_for('journals.voucher'))
```

(Remove all the old list_entries query/filter/render logic — it is replaced by `journals.voucher`.)

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/integration/test_journals.py -v
```
Expected: 6 PASS

- [ ] **Step 7: Commit**

```
git add app/journals/ app/__init__.py app/journal_entries/views.py tests/integration/test_journals.py
git commit -m "feat: add journals blueprint with AP Journal, Journal Voucher, CR/CD placeholder routes"
```

---

## Task 3: AP Journal Template

**Files:**
- Create: `app/journals/templates/journals/ap_journal.html`

- [ ] **Step 1: Create template directory and file**

Create `app/journals/templates/journals/ap_journal.html`:

```html
{% extends "base.html" %}
{% block title %}Accounts Payable Journal{% endblock %}
{% block page_title %}Accounts Payable Journal{% endblock %}

{% block extra_css %}
<style>
.badge { padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
.badge-secondary { background: var(--text-3); color: white; }
.badge-info { background: var(--blue); color: white; }
.badge-danger { background: var(--red); color: white; }
</style>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <div class="card-header-actions"></div>
    </div>

    <div style="padding: 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
        <form method="GET" action="{{ url_for('journals.ap_journal') }}" style="display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 150px;">
                <label style="display: block; font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 6px; text-transform: uppercase;">From Date</label>
                <input type="date" name="date_from" value="{{ date_from }}" class="form-control form-control-sm">
            </div>
            <div style="flex: 1; min-width: 150px;">
                <label style="display: block; font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 6px; text-transform: uppercase;">To Date</label>
                <input type="date" name="date_to" value="{{ date_to }}" class="form-control form-control-sm">
            </div>
            <div style="display: flex; gap: 8px;">
                <button type="submit" class="btn btn-primary btn-sm">🔍 Filter</button>
                <a href="{{ url_for('journals.ap_journal') }}" class="btn btn-secondary btn-sm">Clear</a>
            </div>
        </form>
    </div>

    <div class="card-body">
        {% if entries %}
        <table class="table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>AP No.</th>
                    <th>Vendor</th>
                    <th>Accounts Payable</th>
                    <th style="text-align: right;">Amount</th>
                    <th>Status</th>
                    <th>Posted By</th>
                </tr>
            </thead>
            <tbody>
                {% for entry in entries %}
                {% set bill = bill_map.get(entry.reference) %}
                <tr>
                    <td>{{ entry.entry_date.strftime('%b %d, %Y') }}</td>
                    <td>
                        {% if bill %}
                        <a href="{{ url_for('purchase_bills.view', id=bill.id) }}" style="font-weight: 600; color: var(--blue);">{{ entry.reference }}</a>
                        {% else %}
                        <span style="color: var(--text-2);">{{ entry.reference or '—' }}</span>
                        {% endif %}
                    </td>
                    <td>{{ bill.vendor_name if bill else '—' }}</td>
                    <td style="color: var(--text-2); font-size: 13px;">Accounts Payable</td>
                    <td style="text-align: right; font-family: var(--mono);">₱{{ '{:,.2f}'.format(entry.total_credit) }}</td>
                    <td>
                        <span class="badge badge-{{ 'secondary' if entry.status == 'draft' else 'info' if entry.status == 'posted' else 'danger' }}">
                            {{ entry.status | title }}
                        </span>
                    </td>
                    <td style="color: var(--text-2); font-size: 13px;">
                        {{ entry.posted_by.username if entry.posted_by else (entry.created_by.username if entry.created_by else '—') }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty-state">
            <p>No AP entries found for this period.</p>
            <p style="font-size: 13px; color: var(--text-3);">AP journal entries are created automatically when an AP voucher is posted.</p>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Verify page loads in browser**

Navigate to `http://127.0.0.1:5000/journals/ap` — confirm:
- Page loads without error
- Table headers show: Date, AP No., Vendor, Accounts Payable, Amount, Status, Posted By
- Existing posted AP vouchers appear in the list
- AP No. links to the APV detail page

- [ ] **Step 3: Commit**

```
git add app/journals/templates/journals/ap_journal.html
git commit -m "feat: add Accounts Payable Journal list template"
```

---

## Task 4: Journal Voucher Template

**Files:**
- Create: `app/journals/templates/journals/voucher.html`

- [ ] **Step 1: Create template**

Create `app/journals/templates/journals/voucher.html`:

```html
{% extends "base.html" %}
{% block title %}Journal Voucher{% endblock %}
{% block page_title %}Journal Voucher{% endblock %}

{% block extra_css %}
<style>
.badge { padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
.badge-secondary { background: var(--text-3); color: white; }
.badge-info { background: var(--blue); color: white; }
.badge-danger { background: var(--red); color: white; }
</style>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <div class="card-header-actions">
            {% if current_user.role in ['accountant', 'admin'] %}
            <a href="{{ url_for('journal_entries.create') }}" class="btn btn-primary">📝 New Journal Voucher</a>
            {% endif %}
        </div>
    </div>

    <div style="padding: 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
        <form method="GET" action="{{ url_for('journals.voucher') }}" style="display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 150px;">
                <label style="display: block; font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 6px; text-transform: uppercase;">From Date</label>
                <input type="date" name="date_from" value="{{ date_from }}" class="form-control form-control-sm">
            </div>
            <div style="flex: 1; min-width: 150px;">
                <label style="display: block; font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 6px; text-transform: uppercase;">To Date</label>
                <input type="date" name="date_to" value="{{ date_to }}" class="form-control form-control-sm">
            </div>
            <div style="flex: 1; min-width: 120px;">
                <label style="display: block; font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 6px; text-transform: uppercase;">Status</label>
                <select name="status" class="form-control form-control-sm">
                    <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All Status</option>
                    <option value="draft" {% if status_filter == 'draft' %}selected{% endif %}>Draft</option>
                    <option value="posted" {% if status_filter == 'posted' %}selected{% endif %}>Posted</option>
                    <option value="cancelled" {% if status_filter == 'cancelled' %}selected{% endif %}>Cancelled</option>
                </select>
            </div>
            <div style="display: flex; gap: 8px;">
                <button type="submit" class="btn btn-primary btn-sm">🔍 Filter</button>
                <a href="{{ url_for('journals.voucher') }}" class="btn btn-secondary btn-sm">Clear</a>
            </div>
        </form>
    </div>

    <div class="card-body">
        {% if entries %}
        <table class="table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>JV No.</th>
                    <th>Description</th>
                    <th style="text-align: right;">Total Debit</th>
                    <th>Status</th>
                    <th>Posted By</th>
                </tr>
            </thead>
            <tbody>
                {% for entry in entries %}
                <tr>
                    <td>{{ entry.entry_date.strftime('%b %d, %Y') }}</td>
                    <td>
                        <a href="{{ url_for('journal_entries.view', id=entry.id) }}" style="font-weight: 600; color: var(--blue);">
                            {{ entry.entry_number }}
                        </a>
                    </td>
                    <td>{{ entry.description[:70] }}{% if entry.description | length > 70 %}...{% endif %}</td>
                    <td style="text-align: right; font-family: var(--mono);">₱{{ '{:,.2f}'.format(entry.total_debit) }}</td>
                    <td>
                        <span class="badge badge-{{ 'secondary' if entry.status == 'draft' else 'info' if entry.status == 'posted' else 'danger' }}">
                            {{ entry.status | title }}
                        </span>
                    </td>
                    <td style="color: var(--text-2); font-size: 13px;">
                        {{ entry.posted_by.username if entry.posted_by else (entry.created_by.username if entry.created_by else '—') }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty-state">
            <p>No journal vouchers found for this period.</p>
            {% if current_user.role in ['accountant', 'admin'] %}
            <a href="{{ url_for('journal_entries.create') }}" class="btn btn-primary">Enter First Journal Voucher</a>
            {% endif %}
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Verify page loads in browser**

Navigate to `http://127.0.0.1:5000/journals/voucher` — confirm:
- Page loads without error
- Table headers show: Date, JV No., Description, Total Debit, Status, Posted By
- Existing manual/reversal JEs appear in the list
- "New Journal Voucher" button visible to accountant/admin, hidden for staff/viewer
- Empty state shows "Enter First Journal Voucher" button for accountant/admin

- [ ] **Step 3: Commit**

```
git add app/journals/templates/journals/voucher.html
git commit -m "feat: add Journal Voucher list template"
```

---

## Task 5: Sidebar + Topbar + Redirect

**Files:**
- Modify: `app/templates/base.html`

**Context:** base.html Ledger section is around line 1105. The Journal Entries link is lines 1116–1119. The topbar New Journal Entry link is around line 1315.

- [ ] **Step 1: Remove "Journal Entries" from Ledger, add "Journals" section**

In `app/templates/base.html`, find and replace the Journal Entries nav item in the Ledger section:

Old (lines 1116–1119):
```html
                    <a href="{{ url_for('journal_entries.list_entries') }}" class="nav-item {% if request.endpoint and request.endpoint.startswith('journal_entries.') %}active{% endif %}">
                        <span class="nav-icon">📓</span>
                        <span class="nav-text">Journal Entries</span>
                    </a>
```

Remove those 4 lines entirely (the Journal Entries link is gone from Ledger).

- [ ] **Step 2: Insert Journals section before Financial Reports**

In `app/templates/base.html`, find the `<!-- Financial Reports Section -->` comment (around line 1127) and insert the new Journals section immediately before it:

```html
            <!-- Journals Section -->
            <div class="nav-section">
                <div class="nav-label nav-label-collapsible" data-section="journals">
                    <span>Journals</span>
                    <span class="nav-label-arrow">▼</span>
                </div>
                <div class="nav-section-content" id="section-journals">
                    <a href="{{ url_for('journals.ap_journal') }}" class="nav-item {% if request.endpoint == 'journals.ap_journal' %}active{% endif %}">
                        <span class="nav-icon">📋</span>
                        <span class="nav-text">Accounts Payable Journal</span>
                    </a>
                    <a href="{{ url_for('journals.cr_journal') }}" class="nav-item {% if request.endpoint == 'journals.cr_journal' %}active{% endif %}">
                        <span class="nav-icon">💰</span>
                        <span class="nav-text">Cash Receipts Journal</span>
                    </a>
                    <a href="{{ url_for('journals.cd_journal') }}" class="nav-item {% if request.endpoint == 'journals.cd_journal' %}active{% endif %}">
                        <span class="nav-icon">💸</span>
                        <span class="nav-text">Cash Disbursements Journal</span>
                    </a>
                    <a href="{{ url_for('journals.voucher') }}" class="nav-item {% if request.endpoint == 'journals.voucher' or (request.endpoint and request.endpoint.startswith('journal_entries.') and request.endpoint != 'journal_entries.list_entries') %}active{% endif %}">
                        <span class="nav-icon">📓</span>
                        <span class="nav-text">Journal Voucher</span>
                    </a>
                </div>
            </div>

```

- [ ] **Step 3: Update topbar New dropdown**

In `app/templates/base.html`, find:
```html
                        <a href="{{ url_for('journal_entries.create') }}" class="topbar-new-item">
                            📝 New Journal Entry
                        </a>
```

Replace with:
```html
                        <a href="{{ url_for('journal_entries.create') }}" class="topbar-new-item">
                            📝 New Journal Voucher
                        </a>
```

- [ ] **Step 4: Run full test suite**

```
pytest -x -q
```
Expected: all existing tests pass; no failures.

- [ ] **Step 5: Verify in browser**

1. Navigate to `http://127.0.0.1:5000/` — sidebar shows "Journals" section with four items
2. "Accounts Payable Journal" link opens `/journals/ap` correctly
3. "Cash Receipts Journal" redirects to Under Development page with correct title
4. "Cash Disbursements Journal" redirects to Under Development page with correct title
5. "Journal Voucher" link opens `/journals/voucher`
6. "Journal Entries" no longer appears in Ledger section
7. Old `/journal-entries` URL redirects to `/journals/voucher`
8. Log in as staff/viewer — Journals section still visible; no "New Journal Voucher" button on voucher page
9. Topbar New dropdown shows "New Journal Voucher" (not "New Journal Entry")

- [ ] **Step 6: Commit**

```
git add app/templates/base.html
git commit -m "feat: add Journals sidebar section; replace Journal Entries with Journal Voucher in nav and topbar"
```
