# Purchase Bill Totals Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 4-row totals panel on purchase bill form and detail pages with a 6-row layout that mirrors the BIR accounting flow (Gross → Less: VAT → Net of VAT → Add: VAT back → Less: WHT → Net Amount Payable).

**Architecture:** Two template-only changes — no model or view changes. `form.html` gets new HTML rows and two JS lines in `calculateTotals()`. `detail.html` gets the same structure in Jinja2. All existing IDs and override UX stay intact.

**Tech Stack:** Jinja2 templates, vanilla JavaScript, CSS variables (`var(--mono)`, `var(--text-2)`, `var(--border)`, `var(--blue)`, `var(--red)`)

---

### Task 1: Update `form.html` — totals panel HTML

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html:111-161`

- [ ] **Step 1: Confirm baseline tests pass**

```
pytest tests/unit/test_purchase_bill_models.py tests/integration/test_purchase_bill_je.py -v
```

Expected: all green. If not, stop and investigate before making any changes.

- [ ] **Step 2: Replace the totals panel HTML block**

In `form.html`, replace lines 111–161 (the entire `<!-- Totals Panel -->` div through its closing `</div>`) with:

```html
                    <!-- Totals Panel -->
                    <div style="background: var(--bg); padding: 20px; border-radius: 6px; min-width: 320px;">
                        <!-- Row 1: Gross Amount -->
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                            <span style="color: var(--text-2);">Gross Amount:</span>
                            <span id="subtotalDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                        </div>

                        <!-- Row 2: Less: Input VAT — pencil-click override -->
                        <div style="margin-bottom: 12px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="color: var(--text-2);">Less: Input VAT:</span>
                                <div id="vatDisplayMode" style="display: flex; align-items: center; gap: 6px;">
                                    <span id="vatDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                                    <button type="button" class="totals-pencil" onclick="startVatOverride()" title="Override Input VAT" aria-label="Override Input VAT">✏️</button>
                                </div>
                                <div id="vatEditMode" style="display: none; flex-direction: column; align-items: flex-end;">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <input type="number" id="vatOverrideInput" step="0.01" min="0"
                                               style="width: 110px; text-align: right; font-family: var(--mono); border: 1px solid var(--blue); border-radius: 4px; padding: 3px 7px;"
                                               oninput="onVatOverrideInput(this.value)">
                                        <button type="button" class="totals-revert" onclick="revertVatOverride()" title="Revert to auto">↺</button>
                                    </div>
                                    <div id="vatAutoHint" style="font-size: 11px; color: var(--text-2); margin-top: 2px;"></div>
                                </div>
                            </div>
                        </div>

                        <!-- Row 3: Net of VAT -->
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                            <span style="color: var(--text-2);">Net of VAT:</span>
                            <span id="netOfVatDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                        </div>

                        <!-- Row 4: Add: Input VAT (mirrors row 2, no edit) -->
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                            <span style="color: var(--text-2);">Add: Input VAT:</span>
                            <span id="vatAddBackDisplay" style="font-family: var(--mono); font-weight: 600;">₱0.00</span>
                        </div>

                        <!-- Row 5: Less: Withholding Tax -->
                        <div style="margin-bottom: 12px; padding-top: 8px; border-top: 1px solid var(--border);">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="color: var(--text-2);">Less: Withholding Tax:</span>
                                <div id="wtDisplayMode" style="display: flex; align-items: center; gap: 6px;">
                                    <span id="wtDisplay" style="font-family: var(--mono); font-weight: 600; color: var(--red);">-₱0.00</span>
                                    <button type="button" class="totals-pencil" onclick="startWtOverride()" title="Override Withholding Tax" aria-label="Override Withholding Tax">✏️</button>
                                </div>
                                <div id="wtEditMode" style="display: none; flex-direction: column; align-items: flex-end;">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <input type="number" id="wtOverrideInput" step="0.01" min="0"
                                               style="width: 110px; text-align: right; font-family: var(--mono); border: 1px solid var(--blue); border-radius: 4px; padding: 3px 7px;"
                                               oninput="onWtOverrideInput(this.value)">
                                        <button type="button" class="totals-revert" onclick="revertWtOverride()" title="Revert to auto">↺</button>
                                    </div>
                                    <div id="wtAutoHint" style="font-size: 11px; color: var(--text-2); margin-top: 2px;"></div>
                                </div>
                            </div>
                        </div>

                        <!-- Row 6: Net Amount Payable -->
                        <div style="display: flex; justify-content: space-between; padding-top: 12px; border-top: 2px solid var(--border);">
                            <span style="font-size: 16px; font-weight: 700;">Net Amount Payable:</span>
                            <span id="totalDisplay" style="font-family: var(--mono); font-size: 18px; font-weight: 700; color: var(--blue);">₱0.00</span>
                        </div>
                    </div>
```

The exact old block to replace starts with `                    <!-- Totals Panel -->` (line 111) and ends with `                    </div>` closing the outer totals div (line 161, right before the blank line and `                </div>`).

- [ ] **Step 3: Commit**

```bash
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "feat: update purchase bill form totals panel to 6-row BIR layout (HTML)"
```

---

### Task 2: Update `form.html` — calculateTotals JS

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/form.html:365-377` (inside `calculateTotals()`)

- [ ] **Step 1: Add two lines to `calculateTotals()`**

Find this block inside `calculateTotals()` (currently around line 365–377):

```javascript
    const netPayable = subtotal - wtUsed;

    document.getElementById('subtotalDisplay').textContent = fmt(subtotal);

    if (!vatOverrideActive) {
        document.getElementById('vatDisplay').textContent = fmt(autoVat);
    }
    if (!wtOverrideActive) {
        document.getElementById('wtDisplay').textContent = '-' + fmt(autoWt);
    }
    document.getElementById('totalDisplay').textContent = fmt(netPayable);

    renderJEPreview(subtotal, vatUsed, wtUsed);
```

Replace with:

```javascript
    const netPayable = subtotal - wtUsed;
    const netOfVat = subtotal - vatUsed;

    document.getElementById('subtotalDisplay').textContent = fmt(subtotal);

    if (!vatOverrideActive) {
        document.getElementById('vatDisplay').textContent = fmt(autoVat);
    }
    if (!wtOverrideActive) {
        document.getElementById('wtDisplay').textContent = '-' + fmt(autoWt);
    }
    document.getElementById('totalDisplay').textContent = fmt(netPayable);
    document.getElementById('netOfVatDisplay').textContent = fmt(netOfVat);
    document.getElementById('vatAddBackDisplay').textContent = fmt(vatUsed);

    renderJEPreview(subtotal, vatUsed, wtUsed);
```

`vatUsed` is already computed above this block (override or autoVat), so `vatAddBackDisplay` will always mirror the active Input VAT value — including when the user is typing in the override input.

- [ ] **Step 2: Run tests to confirm no regressions**

```
pytest tests/unit/test_purchase_bill_models.py tests/integration/test_purchase_bill_je.py -v
```

Expected: all green.

- [ ] **Step 3: Visual smoke check in browser**

Start the dev server (`python flask_app.py`), navigate to `http://localhost:5000/purchase-bills/create`, add a line item with VAT (e.g. amount=1000, VAT=VAT-Inclusive 12%), and verify:

- Row 1 "Gross Amount" = ₱1,000.00
- Row 2 "Less: Input VAT" = ₱107.14 with ✏️ pencil
- Row 3 "Net of VAT" = ₱892.86
- Row 4 "Add: Input VAT" = ₱107.14 (no pencil)
- Row 5 "Less: Withholding Tax" = -₱0.00 with ✏️ pencil
- Row 6 "Net Amount Payable" = ₱1,000.00

Then click the VAT pencil, change to 100.00, and verify rows 3 and 4 both update to reflect the new value.

- [ ] **Step 4: Commit**

```bash
git add app/purchase_bills/templates/purchase_bills/form.html
git commit -m "feat: update calculateTotals to populate netOfVatDisplay and vatAddBackDisplay"
```

---

### Task 3: Update `detail.html` — totals panel

**Files:**
- Modify: `app/purchase_bills/templates/purchase_bills/detail.html:188-211`

- [ ] **Step 1: Replace the totals block in `detail.html`**

Find and replace lines 188–211 — the `<!-- Totals -->` wrapper starts at line 187 and the block to replace is the inner div (lines 189–211 through the closing `</div>` that ends the `amount_paid` section boundary). Specifically replace lines 190–211 (inside the already-existing `<div style="background:var(--bg); padding:20px; border-radius:6px; min-width:340px;">`) with:

```html
                <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                    <span style="color:var(--text-2);">Gross Amount:</span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.subtotal) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                    <span style="color:var(--text-2);">
                        Less: Input VAT:
                        {% if bill.vat_override %}<span style="font-size:10px; font-weight:700; color:var(--amber); margin-left:4px; border:1px solid currentColor; border-radius:3px; padding:1px 4px;">MANUAL</span>{% endif %}
                    </span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                    <span style="color:var(--text-2);">Net of VAT:</span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.subtotal - bill.vat_amount) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                    <span style="color:var(--text-2);">Add: Input VAT:</span>
                    <span style="font-family:var(--mono); font-weight:600;">₱{{ '{:,.2f}'.format(bill.vat_amount) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:12px; padding-top:8px; border-top:1px solid var(--border);">
                    <span style="color:var(--text-2);">
                        Less: Withholding Tax:
                        {% if bill.wt_override %}<span style="font-size:10px; font-weight:700; color:var(--amber); margin-left:4px; border:1px solid currentColor; border-radius:3px; padding:1px 4px;">MANUAL</span>{% endif %}
                    </span>
                    <span style="font-family:var(--mono); font-weight:600; color:var(--red);">-₱{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}</span>
                </div>
                <div style="display:flex; justify-content:space-between; padding-top:12px; border-top:2px solid var(--border); margin-bottom:12px;">
                    <span style="font-size:16px; font-weight:700;">Net Amount Payable:</span>
                    <span style="font-family:var(--mono); font-size:18px; font-weight:700; color:var(--blue);">₱{{ '{:,.2f}'.format(bill.total_amount) }}</span>
                </div>
```

The old block being replaced is the 4-row structure (lines 190–211):
```
190:                <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
191:                    <span style="color:var(--text-2);">Subtotal (VAT-incl.):</span>
...through...
211:                </div>
```

Leave the `{% if bill.amount_paid and bill.amount_paid > 0 %}` block (line 212 onwards) untouched.

- [ ] **Step 2: Run full test suite**

```
pytest -v
```

Expected: all tests pass. Failures in unrelated modules should be investigated before committing.

- [ ] **Step 3: Visual smoke check in browser**

Navigate to a posted bill's detail page (e.g. `http://localhost:5000/purchase-bills/<id>`). Verify:

- Row 1 "Gross Amount" shows the bill subtotal
- Row 2 "Less: Input VAT" shows `bill.vat_amount`; if `bill.vat_override` is True, "MANUAL" badge appears
- Row 3 "Net of VAT" = Gross − Input VAT
- Row 4 "Add: Input VAT" = same as row 2, no MANUAL badge
- Row 5 "Less: Withholding Tax" shows WHT; if `bill.wt_override` is True, "MANUAL" badge appears
- Row 6 "Net Amount Payable" = `bill.total_amount`, bold blue, large font

- [ ] **Step 4: Commit**

```bash
git add app/purchase_bills/templates/purchase_bills/detail.html
git commit -m "feat: update purchase bill detail totals panel to 6-row BIR layout"
```
