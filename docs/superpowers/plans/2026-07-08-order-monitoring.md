# Order Monitoring Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only, count-based Order Monitoring dashboard at `/sales-orders/monitor` that surfaces open/draft/overdue/due-soon order counts plus by-status, aging, and top-customer breakdowns — branch-scoped, no monetary values, no schema change.

**Architecture:** A pure metrics function (`app/sales_orders/monitoring.py::get_order_monitoring`) computes a plain dict from branch-scoped `SalesOrder` counts; a thin `sales_orders.monitor` view renders it into `monitoring.html` (count cards + Chart.js donut/bar reusing the bundled `chart.umd.min.js`, mirroring `dashboard/index.html`). Two additive `overdue`/`due_soon` filters on the SO list power card drill-through, and a link on the SO list header is the entry point.

**Tech Stack:** Flask + SQLAlchemy + SQLite; Chart.js (bundled at `app/static/chart.umd.min.js`; CSP forbids CDNs); pytest (run single-threaded with `-p no:cov`).

## Global Constraints

- **No monetary value anywhere** — bare integer counts only; no peso glyph, no amounts.
- **No new columns / no migration** — read-over of existing `status` / `order_date` / `expected_delivery_date` / `customer_name`.
- **Branch-scoped** — every metric filters `branch_id == session['selected_branch_id']`.
- **Definitions (locked):** *Open = `status=='confirmed'`* (drafts separate); *overdue* = confirmed & `expected_delivery_date` set & `< today`; *due soon* = confirmed & `today <= expected_delivery_date <= today+7`; *aging* buckets confirmed orders by `(today - order_date).days` into `0-7/8-30/31-60/60+`; *cancelled* excluded from open/overdue/due-soon/aging.
- **`today` is injected** into the service (view passes `ph_now().date()`) so unit tests are deterministic.
- Gating is automatic: the `sales_orders.monitor` endpoint matches the `sales_orders.` prefix in the module registry, so the existing module gate + branch `before_request` guard apply — no registry change.

---

### Task 1: The metrics service `get_order_monitoring`

**Files:**
- Create: `app/sales_orders/monitoring.py`
- Test: `tests/integration/test_order_monitoring.py`

**Interfaces:**
- Produces: `get_order_monitoring(branch_id, today) -> dict` with keys `cards` (`{'open','drafts','overdue','due_soon'}` → int), `by_status` (`{'labels':['Draft','Confirmed','Cancelled'],'data':[int,int,int]}`), `aging` (`{'labels':['0-7','8-30','31-60','60+'],'data':[int,int,int,int]}`), `top_customers` (`list[{'customer_name':str,'count':int}]`, ≤5, desc).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_order_monitoring.py`:

```python
import pytest
from datetime import date
from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.monitoring import get_order_monitoring

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

_TODAY = date(2026, 7, 8)


def _so(db_session, branch_id, n, status, order_date, expected=None, customer='Acme'):
    so = SalesOrder(so_number=f'SO-MON-{n:04d}', order_date=order_date, customer_id=1,
                    customer_name=customer, branch_id=branch_id, status=status,
                    expected_delivery_date=expected)
    db_session.add(so); db_session.commit()
    return so


def test_metrics_counts_buckets_and_branch_isolation(db_session, main_branch, branch_manila):
    b = main_branch.id
    # three confirmed (open) orders
    _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), date(2026, 7, 1), 'Acme')   # overdue, aging 0-7
    _so(db_session, b, 2, 'confirmed', date(2026, 6, 20), date(2026, 7, 10), 'Acme')  # due_soon, aging 8-30
    _so(db_session, b, 3, 'confirmed', date(2026, 5, 1), None, 'Beta')                # aging 60+
    _so(db_session, b, 4, 'draft', date(2026, 7, 7))
    _so(db_session, b, 5, 'cancelled', date(2026, 7, 7))
    # another branch's confirmed order must NOT leak in
    _so(db_session, branch_manila.id, 6, 'confirmed', date(2026, 7, 1), date(2026, 7, 1))

    m = get_order_monitoring(b, _TODAY)
    assert m['cards'] == {'open': 3, 'drafts': 1, 'overdue': 1, 'due_soon': 1}
    assert m['by_status'] == {'labels': ['Draft', 'Confirmed', 'Cancelled'], 'data': [1, 3, 1]}
    assert m['aging'] == {'labels': ['0-7', '8-30', '31-60', '60+'], 'data': [1, 1, 0, 1]}
    assert m['top_customers'] == [{'customer_name': 'Acme', 'count': 2},
                                  {'customer_name': 'Beta', 'count': 1}]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_order_monitoring.py -p no:cov -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sales_orders.monitoring'`.

- [ ] **Step 3: Write the service**

Create `app/sales_orders/monitoring.py`:

```python
"""Read-only, count-based metrics for the Order Monitoring dashboard.

Pure query -> dict; no ORM objects escape, so the result is safe to hand straight
to the template. `today` is a parameter for deterministic tests. Branch-scoped.
"""
from datetime import timedelta
from sqlalchemy import func
from app.sales_orders.models import SalesOrder


def get_order_monitoring(branch_id, today):
    base = SalesOrder.query.filter_by(branch_id=branch_id)
    confirmed = base.filter_by(status='confirmed')

    open_ct = confirmed.count()
    drafts = base.filter_by(status='draft').count()
    cancelled = base.filter_by(status='cancelled').count()

    overdue = confirmed.filter(
        SalesOrder.expected_delivery_date.isnot(None),
        SalesOrder.expected_delivery_date < today).count()
    soon_end = today + timedelta(days=7)
    due_soon = confirmed.filter(
        SalesOrder.expected_delivery_date.isnot(None),
        SalesOrder.expected_delivery_date >= today,
        SalesOrder.expected_delivery_date <= soon_end).count()

    # aging of open (confirmed) orders by days since order_date
    aging = [0, 0, 0, 0]  # 0-7, 8-30, 31-60, 60+
    for (od,) in confirmed.with_entities(SalesOrder.order_date).all():
        days = (today - od).days
        if days <= 7:
            aging[0] += 1
        elif days <= 30:
            aging[1] += 1
        elif days <= 60:
            aging[2] += 1
        else:
            aging[3] += 1

    rows = (confirmed.with_entities(SalesOrder.customer_name, func.count(SalesOrder.id))
            .group_by(SalesOrder.customer_name)
            .order_by(func.count(SalesOrder.id).desc(), SalesOrder.customer_name)
            .limit(5).all())
    top_customers = [{'customer_name': name, 'count': cnt} for (name, cnt) in rows]

    return {
        'cards': {'open': open_ct, 'drafts': drafts, 'overdue': overdue, 'due_soon': due_soon},
        'by_status': {'labels': ['Draft', 'Confirmed', 'Cancelled'],
                      'data': [drafts, open_ct, cancelled]},
        'aging': {'labels': ['0-7', '8-30', '31-60', '60+'], 'data': aging},
        'top_customers': top_customers,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_order_monitoring.py -p no:cov -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/sales_orders/monitoring.py tests/integration/test_order_monitoring.py
git commit -m "feat(sales-orders): order-monitoring metrics service (count-based, branch-scoped)"
```

---

### Task 2: SO-list drill-through filters (`overdue`, `due_soon`)

**Files:**
- Modify: `app/sales_orders/views.py` (imports: add `timedelta`; the `list()` view after the status-filter block, ~line 134)
- Test: `tests/integration/test_sales_orders_crud.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `/sales-orders?overdue=1` and `?due_soon=1` narrow the list to confirmed orders that are overdue / due within 7 days; both are no-ops when absent.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_sales_orders_crud.py` (uses the file's existing `_customer`, `_login`, `_select_branch` helpers and the autouse `sales_orders_module_enabled` fixture):

```python
def test_list_overdue_filter(client, db_session, admin_user, main_branch):
    import datetime
    from app.utils import ph_now
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    today = ph_now().date()
    # overdue: confirmed + expected delivery in the past
    db.session.add(SalesOrder(so_number='SO-OVD-1', order_date=today, customer_id=c.id,
                              customer_name='Acme', branch_id=main_branch.id, status='confirmed',
                              expected_delivery_date=today - datetime.timedelta(days=3)))
    # not overdue: confirmed, future delivery
    db.session.add(SalesOrder(so_number='SO-FUT-1', order_date=today, customer_id=c.id,
                              customer_name='Acme', branch_id=main_branch.id, status='confirmed',
                              expected_delivery_date=today + datetime.timedelta(days=30)))
    db.session.commit()
    html = client.get('/sales-orders?overdue=1').get_data(as_text=True)
    assert 'SO-OVD-1' in html
    assert 'SO-FUT-1' not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_list_overdue_filter" -p no:cov -v`
Expected: FAIL — `?overdue=1` is ignored, so both SO numbers render.

- [ ] **Step 3: Add `timedelta` to the imports**

In `app/sales_orders/views.py`, change `from datetime import date` to:

```python
from datetime import date, timedelta
```

- [ ] **Step 4: Add the two filters in `list()`**

In `app/sales_orders/views.py`, immediately after the status-filter block (the `if status_filter in VALID_SO_STATUSES:` lines), insert:

```python
    # Drill-through filters from Order Monitoring (applied only when present)
    _today = ph_now().date()
    if request.args.get('overdue') == '1':
        query = query.filter(SalesOrder.status == 'confirmed',
                             SalesOrder.expected_delivery_date.isnot(None),
                             SalesOrder.expected_delivery_date < _today)
    if request.args.get('due_soon') == '1':
        query = query.filter(SalesOrder.status == 'confirmed',
                             SalesOrder.expected_delivery_date.isnot(None),
                             SalesOrder.expected_delivery_date >= _today,
                             SalesOrder.expected_delivery_date <= _today + timedelta(days=7))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_list_overdue_filter" -p no:cov -v`
Expected: PASS.

- [ ] **Step 6: Run the SO marker suite (no regression)**

Run: `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/sales_orders/views.py tests/integration/test_sales_orders_crud.py
git commit -m "feat(sales-orders): additive overdue/due_soon list filters for monitor drill-through"
```

---

### Task 3: The monitor page — route, template, list-header link

**Files:**
- Modify: `app/sales_orders/views.py` (new `monitor()` route)
- Create: `app/sales_orders/templates/sales_orders/monitoring.html`
- Modify: `app/sales_orders/templates/sales_orders/list.html:116` (header link)
- Modify: `.claude/regression-map.json` (map `monitoring.py` under `sales_orders`)
- Test: `tests/integration/test_order_monitoring.py`

**Interfaces:**
- Consumes: `get_order_monitoring(branch_id, today)` (Task 1); the `overdue`/`due_soon` list filters (Task 2).
- Produces: `GET /sales-orders/monitor` (endpoint `sales_orders.monitor`).

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_order_monitoring.py`:

```python
def test_monitor_page_renders_and_is_gated(client, db_session, admin_user, main_branch, login_user):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    # enable the module + select branch
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit(); clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/sales-orders/monitor')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Order Monitoring' in body
    assert 'Overdue' in body and 'Due soon' in body        # card labels
    assert 'byStatusChart' in body and 'agingChart' in body  # canvas ids
    assert '₱' not in body                                   # no peso glyph

    # disabling the module blocks the page
    AppSettings.set_setting('module_enabled:sales_orders', '0')
    db_session.commit(); clear_module_config_cache()
    blocked = client.get('/sales-orders/monitor')
    assert blocked.status_code in (302, 403) or b'Order Monitoring' not in blocked.data
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_order_monitoring.py::test_monitor_page_renders_and_is_gated" -p no:cov -v`
Expected: FAIL with 404 (no `monitor` route yet).

- [ ] **Step 3: Add the `monitor` route**

In `app/sales_orders/views.py`, add (near the `list()` route):

```python
@sales_orders_bp.route('/sales-orders/monitor')
@login_required
def monitor():
    branch_id = session.get('selected_branch_id')
    if not branch_id:
        flash('Please select a branch first.', 'error')
        return redirect(url_for('users.select_branch', next=request.url))
    from app.sales_orders.monitoring import get_order_monitoring
    metrics = get_order_monitoring(branch_id, ph_now().date())
    return render_template('sales_orders/monitoring.html', **metrics)
```

- [ ] **Step 4: Create the template**

Create `app/sales_orders/templates/sales_orders/monitoring.html`:

```html
{% extends "base.html" %}
{% block title %}Order Monitoring{% endblock %}
{% block content %}
<div class="page-header" style="display:flex; justify-content:space-between; align-items:center;">
  <h1>Order Monitoring</h1>
  <a href="{{ url_for('sales_orders.list') }}" class="btn btn-secondary btn-sm">&#8592; Sales Orders</a>
</div>

<div style="display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:24px;">
  <a class="card" href="{{ url_for('sales_orders.list', status='confirmed') }}" style="text-decoration:none;">
    <div class="card-body" style="text-align:center;">
      <div style="font-size:28px; font-weight:700;">{{ cards.open }}</div>
      <div style="color:var(--text-2); font-size:12px; text-transform:uppercase;">Open</div>
    </div>
  </a>
  <a class="card" href="{{ url_for('sales_orders.list', status='draft') }}" style="text-decoration:none;">
    <div class="card-body" style="text-align:center;">
      <div style="font-size:28px; font-weight:700;">{{ cards.drafts }}</div>
      <div style="color:var(--text-2); font-size:12px; text-transform:uppercase;">Drafts</div>
    </div>
  </a>
  <a class="card" href="{{ url_for('sales_orders.list', status='confirmed', overdue='1') }}" style="text-decoration:none;">
    <div class="card-body" style="text-align:center;">
      <div style="font-size:28px; font-weight:700; color:var(--red,#dc2626);">{{ cards.overdue }}</div>
      <div style="color:var(--text-2); font-size:12px; text-transform:uppercase;">Overdue</div>
    </div>
  </a>
  <a class="card" href="{{ url_for('sales_orders.list', status='confirmed', due_soon='1') }}" style="text-decoration:none;">
    <div class="card-body" style="text-align:center;">
      <div style="font-size:28px; font-weight:700;">{{ cards.due_soon }}</div>
      <div style="color:var(--text-2); font-size:12px; text-transform:uppercase;">Due soon</div>
    </div>
  </a>
</div>

<div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px;">
  <div class="card"><div class="card-header"><div class="card-title">By Status</div></div>
    <div class="card-body">
      {% if by_status.data | sum %}<canvas id="byStatusChart"></canvas>
      {% else %}<div class="empty-state"><p>No orders yet</p></div>{% endif %}
    </div>
  </div>
  <div class="card"><div class="card-header"><div class="card-title">Aging of Open Orders</div></div>
    <div class="card-body">
      {% if aging.data | sum %}<canvas id="agingChart"></canvas>
      {% else %}<div class="empty-state"><p>No open orders</p></div>{% endif %}
    </div>
  </div>
</div>

<div class="card"><div class="card-header"><div class="card-title">Top Customers by Open Orders</div></div>
  <div class="card-body">
    {% if top_customers %}
    <table class="table"><thead><tr><th>Customer</th><th style="text-align:right;">Open Orders</th></tr></thead>
      <tbody>{% for row in top_customers %}
        <tr><td>{{ row.customer_name }}</td><td style="text-align:right;">{{ row.count }}</td></tr>
      {% endfor %}</tbody></table>
    {% else %}<div class="empty-state"><p>No open orders</p></div>{% endif %}
  </div>
</div>

<script src="{{ url_for('static', filename='chart.umd.min.js') }}"></script>
<script>
const byStatusCtx = document.getElementById('byStatusChart');
if (byStatusCtx) new Chart(byStatusCtx, {
  type: 'doughnut',
  data: { labels: {{ by_status.labels | tojson }},
          datasets: [{ data: {{ by_status.data | tojson }},
                       backgroundColor: ['#94a3b8', '#3b82f6', '#dc2626'] }] },
  options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
});
const agingCtx = document.getElementById('agingChart');
if (agingCtx) new Chart(agingCtx, {
  type: 'bar',
  data: { labels: {{ aging.labels | tojson }},
          datasets: [{ label: 'Open orders', data: {{ aging.data | tojson }},
                       backgroundColor: '#3b82f6' }] },
  options: { responsive: true, plugins: { legend: { display: false } },
             scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
});
</script>
{% endblock %}
```

- [ ] **Step 5: Add the entry-point link on the SO list header**

In `app/sales_orders/templates/sales_orders/list.html`, at line 116 (the "Enter Sales Order" link), add the monitor link right after it:

```html
            <a href="{{ url_for('sales_orders.create') }}" class="btn btn-green">&#x2795; Enter Sales Order</a>
            <a href="{{ url_for('sales_orders.monitor') }}" class="btn btn-secondary">&#x1F4CA; Order Monitoring</a>
```

- [ ] **Step 6: Map the new service in the regression guard**

In `.claude/regression-map.json`, add to `blast_radius`:

```json
    "app/sales_orders/monitoring.py":     ["sales_orders"],
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_order_monitoring.py -p no:cov -v`
Expected: PASS (both service and page tests).

- [ ] **Step 8: Run the SO marker suite**

Run: `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/sales_orders/views.py app/sales_orders/templates/sales_orders/monitoring.html \
        app/sales_orders/templates/sales_orders/list.html .claude/regression-map.json \
        tests/integration/test_order_monitoring.py
git commit -m "feat(sales-orders): Order Monitoring dashboard page + list-header entry point"
```

---

## Post-implementation

- Browser-verify via MCP (Products/UoM/SO enabled): the SO list shows the "Order Monitoring" link; the page renders 4 count cards, the by-status donut, the aging bar, and the top-customers table; each card drills through to the correctly-filtered SO list; no peso glyph anywhere.
- Confirm the page is hidden/blocked when the Sales Orders module is disabled.
- `/guard` before pushing (SO views/templates + regression-map are blast-radius).
