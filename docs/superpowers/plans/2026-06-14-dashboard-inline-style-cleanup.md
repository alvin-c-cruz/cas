# Dashboard Inline Style Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every `style=""` attribute from `app/dashboard/templates/dashboard/index.html` by extracting them into named CSS classes in `app/static/css/style.css`.

**Architecture:** Two-file change — CSS classes appended to `style.css` under a new dashboard section (using existing `:root` design tokens), then `index.html` updated to reference those classes. No Python, no models, no migrations.

**Tech Stack:** Jinja2 templates, CSS custom properties (`:root` variables already defined in `style.css`)

---

### Task 1: Add dashboard CSS classes to style.css

**Files:**
- Modify: `app/static/css/style.css` (append after line 1503)

- [ ] **Step 1: Append the dashboard CSS section to the end of `style.css`**

```css
/* ─── Dashboard ─────────────────────────────────────── */

.dashboard-hero {
  background: linear-gradient(135deg, var(--login-grad-start) 0%, var(--login-grad-end) 100%);
  border: none;
  color: white;
}

.dashboard-hero .card-body { padding: 24px; }

.dashboard-hero-layout {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.dashboard-hero-title  { margin: 0 0 8px; font-size: 28px; font-weight: 700; color: white; }
.dashboard-hero-subtitle { margin: 0; font-size: 14px; opacity: 0.9; }

.dashboard-datepicker-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.15);
  padding: 12px 16px;
  border-radius: 8px;
  backdrop-filter: blur(10px);
}

.dashboard-datepicker-inner {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  margin-right: 8px;
}

.dashboard-datepicker-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  opacity: 0.9;
  margin-bottom: 4px;
}

.dashboard-datepicker-form { display: flex; gap: 8px; align-items: center; }

.dashboard-datepicker-input {
  background: white;
  border: 2px solid rgba(255, 255, 255, 0.3);
  color: var(--text);
  font-weight: 600;
  padding: 8px 12px;
  font-size: 13px;
  width: 160px;
}

.dashboard-today-btn {
  background: rgba(255, 255, 255, 0.25);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.3);
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.stat-grid--2col { grid-template-columns: repeat(2, 1fr); }

.dashboard-chart { max-height: 300px; }

.text-right  { text-align: right; }
.text-center { text-align: center; }
.font-mono   { font-family: var(--mono); }
```

- [ ] **Step 2: Commit**

```bash
git add app/static/css/style.css
git commit -m "style: add dashboard CSS classes for inline-style cleanup"
```

---

### Task 2: Replace hero header inline styles

**Files:**
- Modify: `app/dashboard/templates/dashboard/index.html` (lines 9–38)

The hero header block has 11 `style=""` attributes across 5 nested elements. Replace the entire block.

- [ ] **Step 1: Replace lines 9–38 with the clean version**

Find the comment `<!-- Dashboard Header with Date Picker -->` and replace everything through the closing `</div>` of the hero block with:

```html
<!-- Dashboard Header with Date Picker -->
<div class="card mb-4 dashboard-hero">
    <div class="card-body">
        <div class="dashboard-hero-layout">
            <div>
                <h2 class="dashboard-hero-title">Financial Dashboard</h2>
                <p class="dashboard-hero-subtitle">Real-time insights into your business performance</p>
            </div>
            <div class="dashboard-datepicker-wrap">
                <div class="dashboard-datepicker-inner">
                    <label class="dashboard-datepicker-label">As of Date</label>
                    <form method="GET" action="{{ url_for('dashboard.home') }}" id="dateForm" class="dashboard-datepicker-form">
                        <input type="date"
                               name="as_of_date"
                               id="asOfDate"
                               value="{{ as_of_date }}"
                               class="form-control dashboard-datepicker-input"
                               onchange="this.form.submit()">
                        <button type="button"
                                onclick="document.getElementById('asOfDate').value='{{ today }}'; document.getElementById('dateForm').submit();"
                                class="btn btn-sm dashboard-today-btn">
                            📅 Today
                        </button>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Verify lines 9–38 are clean**

```bash
grep -n 'style=' app/dashboard/templates/dashboard/index.html | head -5
```

Expected: no matches in the first 40 lines (hero block is now clean).

- [ ] **Step 3: Commit**

```bash
git add app/dashboard/templates/dashboard/index.html
git commit -m "style: remove inline styles from dashboard hero header"
```

---

### Task 3: Replace remaining inline styles (stat grid, charts, tables)

**Files:**
- Modify: `app/dashboard/templates/dashboard/index.html` (lines ~41, ~136, ~146, ~167–168, ~175–176, ~200–201, ~209–210)

- [ ] **Step 1: Fix the stat grid (line ~41)**

Change:
```html
<div class="stat-grid" style="grid-template-columns:repeat(2,1fr)">
```
To:
```html
<div class="stat-grid stat-grid--2col">
```

- [ ] **Step 2: Fix the Revenue Trend chart canvas (line ~136)**

Change:
```html
<canvas id="revenueTrendChart" style="max-height: 300px;"></canvas>
```
To:
```html
<canvas id="revenueTrendChart" class="dashboard-chart"></canvas>
```

- [ ] **Step 3: Fix the Expense Breakdown chart canvas (line ~146)**

Change:
```html
<canvas id="expenseBreakdownChart" style="max-height: 300px;"></canvas>
```
To:
```html
<canvas id="expenseBreakdownChart" class="dashboard-chart"></canvas>
```

- [ ] **Step 4: Fix the Top Customers table header (line ~167–168)**

Change:
```html
<th style="text-align: right;">Total Sales</th>
<th style="text-align: center;">Invoices</th>
```
To:
```html
<th class="text-right">Total Sales</th>
<th class="text-center">Invoices</th>
```

- [ ] **Step 5: Fix the Top Customers table data cells (line ~175–176)**

Change:
```html
<td style="text-align: right; font-family: var(--mono);">₱{{ '{:,.2f}'.format(customer.total_sales) }}</td>
<td style="text-align: center;">{{ customer.invoice_count }}</td>
```
To:
```html
<td class="text-right font-mono">₱{{ '{:,.2f}'.format(customer.total_sales) }}</td>
<td class="text-center">{{ customer.invoice_count }}</td>
```

- [ ] **Step 6: Fix the Top Vendors table header (line ~200–201)**

Change:
```html
<th style="text-align: right;">Total Purchases</th>
<th style="text-align: center;">Bills</th>
```
To:
```html
<th class="text-right">Total Purchases</th>
<th class="text-center">Bills</th>
```

- [ ] **Step 7: Fix the Top Vendors table data cells (line ~209–210)**

Change:
```html
<td style="text-align: right; font-family: var(--mono);">₱{{ '{:,.2f}'.format(vendor.total_purchases) }}</td>
<td style="text-align: center;">{{ vendor.bill_count }}</td>
```
To:
```html
<td class="text-right font-mono">₱{{ '{:,.2f}'.format(vendor.total_purchases) }}</td>
<td class="text-center">{{ vendor.bill_count }}</td>
```

- [ ] **Step 8: Verify zero inline styles remain**

```bash
grep -n 'style=' app/dashboard/templates/dashboard/index.html
```

Expected output: **no output at all** (zero matches).

- [ ] **Step 9: Commit**

```bash
git add app/dashboard/templates/dashboard/index.html
git commit -m "style: remove remaining inline styles from dashboard template"
```

---

### Task 4: Smoke test and visual verification

**Files:** none (read-only)

- [ ] **Step 1: Run the smoke tests**

```bash
pytest tests/test_smoke.py -v
```

Expected: all tests pass. The dashboard page must return 200 with no template errors.

- [ ] **Step 2: Start the dev server and verify visually**

```bash
python flask_app.py
```

Open `http://localhost:5000/dashboard` and confirm:
- Purple gradient hero header renders with white text
- "As of Date" glass container appears with label + date input + "📅 Today" button
- Revenue and Expenses stat cards display in 2 columns
- Revenue Trend (line chart) and Expense Breakdown (doughnut) render at correct height
- Top Customers and Top Vendors tables show right-aligned peso amounts in monospace font
- No visual regressions anywhere on the page
