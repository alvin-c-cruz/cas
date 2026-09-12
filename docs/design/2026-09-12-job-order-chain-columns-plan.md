# Job Order Slips chain columns — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `DR # · SI # · CR #` document-chain columns to `/sales-orders/job-order-slips`, mirroring the Purchase Requests list.

**Architecture:** One new module `app/sales_orders/chain_links.py` with three page-level link resolvers (one query each, `{so_id: [(doc_id, number)]}`), called from `job_order_list()` and rendered as three cells copied from the PR list's markup. Spec: `docs/design/2026-09-12-job-order-chain-columns-design.md`.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, Jinja, pytest (markers `sales_orders`, `integration`, `unit`).

## Global Constraints

- No pricing/amount columns on the Job Order Slips page (route docstring, spec).
- Never resolve links per row; resolve once per page (PR list rule).
- DR counts only when `status in COMMITTED_STATUSES` (`app/delivery_receipts/models.py:10`).
- CRV counts only when `status not in ('voided', 'cancelled')`.
- SI link: `delivery_receipts.sales_invoice_id` alone (cleared on SI void/cancel by `_unbill_drs`).
- Em dash `—` for an empty cell.
- Register no new marker; use `sales_orders` (already in `pytest.ini`).
- Commit after each task; end commit messages with the attribution block in the session reminder.

---

### Task 1: `chain_links.py` — three resolvers

**Files:**
- Create: `app/sales_orders/chain_links.py`
- Test: `tests/unit/test_so_chain_links.py`

**Interfaces:**
- Produces: `dr_links_for_so_ids(so_ids) -> dict[int, list[tuple[int, str]]]`, `si_links_for_so_ids(so_ids)`, `cr_links_for_so_ids(so_ids)` — same return shape; `[]`/`None` → `{}`.

- [ ] **Step 1: Write the failing tests** (`tests/unit/test_so_chain_links.py`; fixtures build real rows through the ORM — see file in repo after this task).
- [ ] **Step 2: Run** `pytest tests/unit/test_so_chain_links.py -q` → FAIL `ModuleNotFoundError: app.sales_orders.chain_links`.
- [ ] **Step 3: Implement** `app/sales_orders/chain_links.py` (queries below).
- [ ] **Step 4: Run** the file again → all PASS.
- [ ] **Step 5: Commit** `feat(so): chain-link resolvers for the Job Order Slips page`.

Queries:

```python
# DR: SalesOrder -> DeliveryReceipt(sales_order_id), committed only
db.session.query(DeliveryReceipt.sales_order_id, DeliveryReceipt.id, DeliveryReceipt.dr_number)
  .filter(DeliveryReceipt.sales_order_id.in_(ids), DeliveryReceipt.status.in_(COMMITTED_STATUSES))
  .order_by(DeliveryReceipt.dr_number.asc()).distinct()
# SI: ... -> SalesInvoice via DeliveryReceipt.sales_invoice_id
  .join(SalesInvoice, SalesInvoice.id == DeliveryReceipt.sales_invoice_id)
# CR: ... -> CRVArLine(invoice_id) -> CashReceiptVoucher, status not in ('voided','cancelled')
```

### Task 2: view + template

**Files:**
- Modify: `app/sales_orders/views.py` (`job_order_list`, ~line 979)
- Modify: `app/sales_orders/templates/sales_orders/job_order_list.html`
- Test: `tests/integration/test_job_order_chain_columns.py`

**Interfaces:**
- Consumes: the three resolvers from Task 1.

- [ ] **Step 1: Write the failing integration test** — SO with delivered DR + SI + posted CRV renders the three links; an untouched SO renders `—` ×3; the SO's row contains no amount; header order `Status · DR # · SI # · CR # · Actions`.
- [ ] **Step 2: Run** → FAIL (no `DR #` header).
- [ ] **Step 3: Implement** — view passes `dr_links`, `si_links`, `cr_links`; template adds the `<th>`s and `<td>`s copied from `purchase_requests/list.html:100-131` with the once-per-page comment.
- [ ] **Step 4: Run** the new test + `pytest -m sales_orders -q` → PASS.
- [ ] **Step 5: Commit** `feat(so): DR/SI/CR chain columns on the Job Order Slips page`.
