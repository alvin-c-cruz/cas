# APV Demo Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 30 AP voucher entries (April–June 2026) through the live browser UI for client demos and UI/UX testing.

**Architecture:** Pure browser automation via Playwright MCP. No code changes. Admin user creates all 30 bills as drafts, then applies status changes (post/void/cancel) in a second pass. Task 1 looks up live DB IDs; Tasks 2–4 create drafts; Tasks 5–7 apply statuses; Task 8 verifies.

**Tech Stack:** Playwright MCP (`browser_evaluate`, `browser_navigate`, `browser_click`), Flask app at `http://127.0.0.1:5000`, admin credentials `admin` / `admin123`.

---

## Key Patterns

### Create a draft bill
```javascript
// Run on /purchase-bills/create page after navigation
async () => {
  // 1. Select vendor by code substring
  const vendorSel = document.querySelector('select[name="vendor_id"]');
  const opt = Array.from(vendorSel.options).find(o => o.text.includes('VENDOR_CODE'));
  vendorSel.value = opt.value;
  vendorSel.dispatchEvent(new Event('change', { bubbles: true }));

  // 2. Set header fields
  document.querySelector('input[name="bill_date"]').value = 'YYYY-MM-DD';
  document.querySelector('input[name="due_date"]').value = 'YYYY-MM-DD';
  const ref = document.querySelector('input[name="reference"]');
  if (ref) ref.value = 'PO-XXX-000';

  // 3. Configure line item (remove second default, set first)
  if (typeof removeLineItem === 'function') removeLineItem(2);
  updateLineItem(1, 'description', 'DESCRIPTION');
  updateLineItem(1, 'amount', AMOUNT);
  updateLineItem(1, 'vat_category', 'VAT_CODE');
  updateLineItem(1, 'account_id', ACCOUNT_ID);
  if (WT_ID) updateLineItem(1, 'wt_id', WT_ID);
  calculateTotals();

  // 4. Submit
  const btn = Array.from(document.querySelectorAll('button[type="submit"]'))
    .find(b => b.textContent.includes('Save'));
  btn.click();
  return { submitted: true };
}
```
After submit, the page redirects to `/purchase-bills/<id>`. Read the ID from `window.location.pathname`.

### Post a bill (from its detail page)
```javascript
// Trigger modal
Array.from(document.querySelectorAll('button'))
  .find(b => b.type === 'button' && b.textContent.includes('Post APV'))
  .click();
```
Then click: `form[action*="/post"] button[type="submit"]`

### Void a bill (from its detail page — must be draft)
```javascript
Array.from(document.querySelectorAll('button'))
  .find(b => b.type === 'button' && b.textContent.includes('Void APV'))
  .click();
// Then fill reason and submit:
document.querySelector('#voidModal textarea[name="void_reason"]').value = 'REASON';
// reversal_date already defaults to today
```
Then click: `form[action*="/void"] button[type="submit"]`

### Cancel a bill (from its detail page — must be posted)
```javascript
Array.from(document.querySelectorAll('button'))
  .find(b => b.type === 'button' && b.textContent.includes('Cancel APV'))
  .click();
document.querySelector('#cancelModal textarea[name="cancel_reason"]').value = 'REASON';
```
Then click: `form[action*="/cancel"] button[type="submit"]`

---

## Task 1: Prerequisites — Verify login and look up IDs

**Files:** None (browser automation only)

- [ ] **Step 1: Ensure admin is logged in**

Navigate to `http://127.0.0.1:5000/dashboard`. If redirected to login, log in:
```javascript
// On /login page:
() => {
  const u = document.querySelector('#username');
  const p = document.querySelector('#password');
  u.removeAttribute('readonly'); u.value = 'admin';
  p.removeAttribute('readonly'); p.value = 'admin123';
  return { ready: true };
}
```
Then click `button[type="submit"]`. Expected: redirects to `/dashboard`.

- [ ] **Step 2: Look up vendor IDs**

Navigate to `http://127.0.0.1:5000/purchase-bills/create`, then run:
```javascript
() => {
  const sel = document.querySelector('select[name="vendor_id"]');
  const vendors = {};
  Array.from(sel.options).forEach(o => {
    if (o.value) vendors[o.text.trim()] = o.value;
  });
  return vendors;
}
```
Record the ID for each vendor code. Expected result shape:
```
{ "MOS - Mega Office Supplies Co.": "X", "VND001 - MOS Trading Corp": "X", ... }
```

- [ ] **Step 3: Look up account ID for 60101**

On the same create page, find the account select or run:
```javascript
() => {
  // Account 60101 will be in the line item account dropdown
  // Try to find it by inspecting the JS account data or select options
  const acctEl = document.querySelector('[id*="account"]');
  // Alternatively fetch from API
  return fetch('/api/accounts').then(r => r.json())
    .then(data => {
      const acc = (data.accounts || data).find(a => a.code === '60101');
      return { id: acc?.id, code: acc?.code, name: acc?.name };
    });
}
```
Record the numeric ID for account code `60101`.

- [ ] **Step 4: Look up WHT IDs**

```javascript
() => fetch('/api/withholding-taxes').then(r => r.json())
  .then(data => {
    const codes = ['WC158', 'WC160', 'WC100'];
    const result = {};
    (data.withholding_taxes || data).forEach(wt => {
      if (codes.includes(wt.code)) result[wt.code] = wt.id;
    });
    return result;
  });
```
If the API endpoint doesn't exist, look them up from the WHT select in the line item area of the create form.

Record: `WC158_ID`, `WC160_ID`, `WC100_ID`.

---

## Task 2: Create April drafts (bills 1–10)

**Pre-condition:** IDs from Task 1 are known. Admin logged in.

Use the create pattern from the Key Patterns section. For each bill: navigate to `/purchase-bills/create`, run the evaluate block, wait for redirect, record the new bill ID from the URL.

**Vendor lookup strings** (match by `includes`):
- VND002 → `'VND002'`
- VND005 → `'VND005'`
- MOS → `'MOS - Mega'`
- VND003 → `'VND003'`
- VND006 → `'VND006'`
- VND004 → `'VND004'`
- VND001 → `'VND001'`
- VND008 → `'VND008'`
- VND007 → `'VND007'`

**April bills data** (ACCOUNT_ID = looked-up 60101 ID):

| # | Vendor match | bill_date | due_date | reference | description | amount | vat_category | wt_id |
|---|-------------|-----------|----------|-----------|-------------|--------|--------------|-------|
| 1 | VND002 | 2026-04-01 | 2026-05-01 | PO-APR-001 | Office rent - April 2026 | 45000 | V12DG | WC100_ID |
| 2 | VND005 | 2026-04-05 | 2026-05-05 | PO-APR-002 | Electricity - April 2026 | 8500 | VEX | null |
| 3 | MOS - Mega | 2026-04-08 | 2026-05-08 | PO-APR-003 | Office supplies restock | 12300 | V12DG | WC158_ID |
| 4 | VND003 | 2026-04-10 | 2026-05-10 | PO-APR-004 | Quarterly IT maintenance | 35000 | V12SV | WC160_ID |
| 5 | VND006 | 2026-04-12 | 2026-05-12 | PO-APR-005 | Document delivery services | 2800 | INV | null |
| 6 | VND004 | 2026-04-15 | 2026-05-15 | PO-APR-006 | Legal retainer fee - April | 25000 | V12SV | WC160_ID |
| 7 | VND001 | 2026-04-18 | 2026-05-18 | PO-APR-007 | Paper and printing supplies | 6750 | V12DG | WC158_ID |
| 8 | VND003 | 2026-04-22 | 2026-05-22 | PO-APR-008 | Software license renewal | 18000 | V12SV | WC160_ID |
| 9 | VND008 | 2026-04-25 | 2026-05-25 | PO-APR-009 | Toner cartridges and accessories | 9200 | V12DG | WC158_ID |
| 10 | VND007 | 2026-04-28 | 2026-05-28 | PO-APR-010 | Export packaging materials | 5500 | V0 | null |

- [ ] **Step 1: Create bill 1 (VND002, ₱45,000, rent)**

Navigate to `/purchase-bills/create`. Run:
```javascript
async () => {
  const sel = document.querySelector('select[name="vendor_id"]');
  const opt = Array.from(sel.options).find(o => o.text.includes('VND002'));
  sel.value = opt.value; sel.dispatchEvent(new Event('change', {bubbles:true}));
  document.querySelector('input[name="bill_date"]').value = '2026-04-01';
  document.querySelector('input[name="due_date"]').value = '2026-05-01';
  document.querySelector('input[name="reference"]').value = 'PO-APR-001';
  if (typeof removeLineItem === 'function') removeLineItem(2);
  updateLineItem(1,'description','Office rent - April 2026');
  updateLineItem(1,'amount',45000);
  updateLineItem(1,'vat_category','V12DG');
  updateLineItem(1,'account_id', ACCOUNT_60101_ID);
  updateLineItem(1,'wt_id', WC100_ID);
  calculateTotals();
  Array.from(document.querySelectorAll('button[type="submit"]'))
    .find(b=>b.textContent.includes('Save')).click();
  return {submitted:true};
}
```
Expected: redirect to `/purchase-bills/<id>`. Record ID as `B1`.

- [ ] **Step 2: Create bills 2–10**

Repeat the same pattern for bills 2–10 using the data table above. After each save, record the bill ID from the URL (`B2` through `B10`).

Key differences per bill:
- Bill 2: VND005, VEX vat, null wt_id
- Bill 3: `'MOS - Mega'`, V12DG, WC158_ID
- Bill 4: VND003, V12SV, WC160_ID
- Bill 5: VND006, INV, null wt_id
- Bill 6: VND004, V12SV, WC160_ID
- Bill 7: VND001, V12DG, WC158_ID
- Bill 8: VND003, V12SV, WC160_ID
- Bill 9: VND008, V12DG, WC158_ID
- Bill 10: VND007, V0, null wt_id

- [ ] **Step 3: Verify 10 April drafts exist**

Navigate to `http://127.0.0.1:5000/purchase-bills`. Filter by status=draft. Confirm 10+ draft bills appear with reference numbers PO-APR-001 through PO-APR-010.

---

## Task 3: Create May drafts (bills 11–20)

**May bills data:**

| # | Vendor match | bill_date | due_date | reference | description | amount | vat_category | wt_id |
|---|-------------|-----------|----------|-----------|-------------|--------|--------------|-------|
| 11 | VND002 | 2026-05-01 | 2026-05-31 | PO-MAY-001 | Office rent - May 2026 | 45000 | V12DG | WC100_ID |
| 12 | VND005 | 2026-05-05 | 2026-06-04 | PO-MAY-002 | Electricity - May 2026 | 9200 | VEX | null |
| 13 | MOS - Mega | 2026-05-07 | 2026-06-06 | PO-MAY-003 | Stationery and office supplies | 7800 | V12DG | WC158_ID |
| 14 | VND004 | 2026-05-10 | 2026-06-09 | PO-MAY-004 | Contract review services | 15000 | V12SV | WC160_ID |
| 15 | VND006 | 2026-05-12 | 2026-06-11 | PO-MAY-005 | Courier and delivery | 3100 | INV | null |
| 16 | VND003 | 2026-05-15 | 2026-06-14 | PO-MAY-006 | Network infrastructure repair | 28500 | V12SV | WC160_ID |
| 17 | VND001 | 2026-05-18 | 2026-06-17 | PO-MAY-007 | Printer paper bulk order | 11200 | V12DG | WC158_ID |
| 18 | VND008 | 2026-05-20 | 2026-06-19 | PO-MAY-008 | Filing cabinets (2 units) | 22000 | V12DG | WC158_ID |
| 19 | VND007 | 2026-05-22 | 2026-06-21 | PO-MAY-009 | Shipping and packaging materials | 4300 | V0 | null |
| 20 | VND002 | 2026-05-28 | 2026-06-27 | PO-MAY-010 | Parking fee adjustment - May | 5000 | V12DG | WC100_ID |

- [ ] **Step 1: Create bills 11–20**

Navigate to `/purchase-bills/create` for each. Use the same evaluate pattern from Task 2. Record IDs `B11` through `B20` from the redirect URL after each save.

- [ ] **Step 2: Verify 10 May drafts**

Navigate to `/purchase-bills`. Confirm reference numbers PO-MAY-001 through PO-MAY-010 appear as drafts.

---

## Task 4: Create June drafts (bills 21–30)

**June bills data:**

| # | Vendor match | bill_date | due_date | reference | description | amount | vat_category | wt_id |
|---|-------------|-----------|----------|-----------|-------------|--------|--------------|-------|
| 21 | VND002 | 2026-06-01 | 2026-07-01 | PO-JUN-001 | Office rent - June 2026 | 45000 | V12DG | WC100_ID |
| 22 | VND005 | 2026-06-05 | 2026-07-05 | PO-JUN-002 | Electricity - June 2026 | 10100 | VEX | null |
| 23 | MOS - Mega | 2026-06-07 | 2026-07-07 | PO-JUN-003 | Office supplies - June restock | 14500 | V12DG | WC158_ID |
| 24 | VND003 | 2026-06-10 | 2026-07-10 | PO-JUN-004 | Server maintenance and updates | 42000 | V12SV | WC160_ID |
| 25 | VND004 | 2026-06-12 | 2026-07-12 | PO-JUN-005 | Legal and compliance review | 30000 | V12SV | WC160_ID |
| 26 | VND006 | 2026-06-14 | 2026-07-14 | PO-JUN-006 | Courier services - June | 2500 | INV | null |
| 27 | VND001 | 2026-06-16 | 2026-07-16 | PO-JUN-007 | Office stationery order | 8900 | V12DG | WC158_ID |
| 28 | VND008 | 2026-06-18 | 2026-07-18 | PO-JUN-008 | Office chairs (5 units) | 35000 | V12DG | WC158_ID |
| 29 | VND003 | 2026-06-20 | 2026-07-20 | PO-JUN-009 | IT consulting - Q2 review | 55000 | V12SV | WC160_ID |
| 30 | VND007 | 2026-06-25 | 2026-07-25 | PO-JUN-010 | Export materials - June batch | 6800 | V0 | null |

- [ ] **Step 1: Create bills 21–30**

Navigate to `/purchase-bills/create` for each. Record IDs `B21` through `B30`.

- [ ] **Step 2: Verify all 30 drafts**

```javascript
() => {
  const rows = Array.from(document.querySelectorAll('tr'));
  const drafts = rows.filter(r => r.textContent.includes('Draft'));
  return { draftCount: drafts.length };
}
```
Expected: draftCount ≥ 30 (plus 1 from Run 2).

---

## Task 5: Post 24 bills

Bills to post (will remain posted): 1–8, 11–16, 18, 21–26, 28  
Bills to post then cancel (Tasks 6): 17, 27  
Bills to stay draft: 9, 19, 29, 30  
Bills to void (Task 7, from draft): 10, 20  

**Total to post in this task: 24** (bills 1–8, 11–16, 17, 18, 21–26, 27, 28)

For each bill: navigate to its detail URL, trigger post modal, confirm.

- [ ] **Step 1: Post bill B1 through B8 (April posted bills)**

For each ID in [B1, B2, B3, B4, B5, B6, B7, B8]:
```javascript
// Navigate to /purchase-bills/<ID>
// Open post modal:
() => {
  Array.from(document.querySelectorAll('button'))
    .find(b => b.type === 'button' && b.textContent.includes('Post APV'))
    .click();
  return { modalOpened: true };
}
// Then click submit:
// target: form[action*="/post"] button[type="submit"]
```
After each post, verify `.badge` text = "Posted".

- [ ] **Step 2: Post bills B11–B18 (May bills — includes B17 which will be cancelled later)**

Same pattern for B11, B12, B13, B14, B15, B16, B17, B18. Record that B17 is "posted, pending cancel."

- [ ] **Step 3: Post bills B21–B28 (June bills — includes B27 which will be cancelled later)**

Same pattern for B21, B22, B23, B24, B25, B26, B27, B28.

- [ ] **Step 4: Verify post count**

Navigate to `/purchase-bills`. Run:
```javascript
() => {
  const rows = Array.from(document.querySelectorAll('tr'));
  const posted = rows.filter(r => r.textContent.includes('Posted'));
  return { postedCount: posted.length };
}
```
Expected: postedCount = 24.

---

## Task 6: Cancel bills 17 and 27

Bills B17 (PO-MAY-007, ₱11,200) and B27 (PO-JUN-007, ₱8,900) are already posted. Cancel each.

- [ ] **Step 1: Cancel B17**

Navigate to `/purchase-bills/<B17>`. Open cancel modal:
```javascript
() => {
  Array.from(document.querySelectorAll('button'))
    .find(b => b.type === 'button' && b.textContent.includes('Cancel APV'))
    .click();
  return { opened: true };
}
```
Fill reason:
```javascript
() => {
  document.querySelector('#cancelModal textarea[name="cancel_reason"]')
    .value = 'Cancelled for testing purposes - duplicate order';
  return { filled: true };
}
```
Click: `form[action*="/cancel"] button[type="submit"]`

Verify: badge = "Cancelled", flash includes "cancelled".

- [ ] **Step 2: Cancel B27**

Same pattern. Navigate to `/purchase-bills/<B27>`. Cancel reason: `'Cancelled for testing purposes - wrong items ordered'`

Verify: badge = "Cancelled".

---

## Task 7: Void bills 10 and 20

Bills B10 (PO-APR-010, ₱5,500) and B20 (PO-MAY-010, ₱5,000) are still drafts.

- [ ] **Step 1: Void B10**

Navigate to `/purchase-bills/<B10>`. Open void modal:
```javascript
() => {
  Array.from(document.querySelectorAll('button'))
    .find(b => b.type === 'button' && b.textContent.includes('Void APV'))
    .click();
  return { opened: true };
}
```
Fill reason:
```javascript
() => {
  document.querySelector('#voidModal textarea[name="void_reason"]')
    .value = 'Wrong vendor — reissued under correct vendor';
  return { filled: true };
}
```
Click: `form[action*="/void"] button[type="submit"]`

Verify: badge = "Voided".

- [ ] **Step 2: Void B20**

Same pattern. Navigate to `/purchase-bills/<B20>`. Void reason: `'Incorrect amount — reissued with correct figure'`

Verify: badge = "Voided".

---

## Task 8: Final verification

- [ ] **Step 1: Verify status counts**

Navigate to `/purchase-bills`. Run:
```javascript
() => {
  const text = document.body.textContent;
  const count = (status) => (text.match(new RegExp(status, 'g')) || []).length;
  return {
    posted: count('Posted'),
    draft: count('Draft'),
    cancelled: count('Cancelled'),
    voided: count('Voided'),
  };
}
```
Expected (including Run 2 leftover bills):
- posted ≥ 22 (exactly 22 new)
- draft ≥ 4 (bills 9, 19, 29, 30)
- cancelled ≥ 2 (bills 17, 27) + 1 from Run 2 = 3
- voided ≥ 2 (bills 10, 20) + 1 from Run 2 = 3

- [ ] **Step 2: Verify dashboard payables**

Navigate to `/dashboard`. Check Accounts Payable card:
```javascript
() => {
  const cards = Array.from(document.querySelectorAll('.card, [class*="card"]'));
  const payCard = cards.find(c => c.textContent.toLowerCase().includes('payable'));
  return { text: payCard?.textContent?.replace(/\s+/g,' ').trim().substring(0,200) };
}
```
Expected: total ≥ ₱500,000, count ≥ 22 unpaid bills.

- [ ] **Step 3: Check AP list pagination and filters work**

Navigate to `/purchase-bills`. Confirm:
1. All 30+ bills visible (or paginated)
2. Status filter dropdown works (filter by "Draft" shows only 4+ draft bills)
3. Bill numbers follow the pattern AP-2026-0X-XXXX

- [ ] **Step 4: Spot-check one bill detail page**

Navigate to the detail page for bill 1 (rent, ₱45,000, VND002). Verify:
- Vendor Invoice section visible (yellow card)
- JE preview section shows correct debit/credit lines
- Status badge = Posted
- Amount matches ₱45,000

---

## Self-Review Notes

- Status counts verified: 22 posted + 4 draft + 2 cancelled + 2 voided = 30 ✓
- All 9 vendors used ✓
- Bills 17 and 27 are posted before cancelling (Task 5 posts them, Task 6 cancels) ✓
- Bills 10 and 20 are voided from draft state (never posted) ✓
- Task 1 ID lookups feed into Tasks 2–4 via controller context ✓
- No code changes required — pure browser automation ✓
