"""Income Statement by Product Line (Phase 3a+3b) -- re-projects generate_income_statement()
onto product-line columns. See
docs/superpowers/specs/2026-07-12-income-statement-by-product-line-phase3-design.md
(2026-07-19 addendum) for the master invariant and traversal rule this implements.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem
from app.expense_allocation_rules.models import ExpenseAllocationRule
from app.reports.financial import generate_income_statement
from app.reports.product_line import generate_sales_by_product_line
from app.reports.sections import IS_SECTIONS

UNALLOCATED = 'unallocated'
TOTAL = 'total'
_SI_ON_BOOKS = ('posted', 'partially_paid', 'paid')


def _resolve_leaves(section_lines):
    """Flatten a rollup() section's 'lines' into real leaf {account_id, amount} dicts.

    Per the traversal rule (spec addendum): a top-level entry WITH children distributes
    each CHILD (the real leaf account); a top-level entry with NO children IS the leaf
    itself (there is no finer account underneath it).
    """
    leaves = []
    for entry in section_lines:
        children = entry.get('children') or []
        if children:
            for c in children:
                leaves.append({'account_id': c['account_id'], 'amount': Decimal(str(c['amount']))})
        else:
            leaves.append({'account_id': entry['account_id'], 'amount': Decimal(str(entry['total']))})
    return leaves


def _categories():
    """All product categories (active AND inactive -- a historical sale against a now-
    inactive category must still show as its own column, not fall into Unassigned;
    mirrors generate_sales_by_product_line's own `ProductCategory.query.all()`)."""
    return {c.id: c for c in ProductCategory.query.all()}


def _revenue_by_category(start_date, end_date, branch_id):
    data = generate_sales_by_product_line(start_date, end_date, branch_id)
    return {r['category_id']: Decimal(str(r['net'])) for r in data['rows']}


def _standard_cogs_by_category(start_date, end_date, branch_id):
    """Standard COGS by category: Sigma(qty x product.standard_cost), signed like revenue
    (SI +, credit memo -, debit note +). Uncosted products (standard_cost NULL) and
    non-itemized lines (qty NULL) contribute zero -- their true cost surfaces in the
    COGS-variance row, never as a mis-stated line COGS."""
    def _by_cat(item_model, header_model, header_fk, date_col, filters, sign):
        branch = [header_model.branch_id == branch_id] if branch_id else []
        rows = db.session.query(
            Product.category_id, Product.standard_cost,
            func.coalesce(func.sum(item_model.quantity), 0),
        ).select_from(item_model).join(
            header_model, getattr(item_model, header_fk) == header_model.id
        ).join(
            Product, item_model.product_id == Product.id
        ).filter(
            date_col >= start_date, date_col <= end_date, *filters, *branch,
            item_model.quantity.isnot(None), Product.standard_cost.isnot(None),
        ).group_by(Product.category_id, Product.standard_cost).all()
        out = defaultdict(lambda: Decimal('0'))
        for cid, cost, qty in rows:
            out[cid] += sign * Decimal(str(qty)) * Decimal(str(cost))
        return out

    cogs = defaultdict(lambda: Decimal('0'))
    for cid, v in _by_cat(SalesInvoiceItem, SalesInvoice, 'invoice_id', SalesInvoice.invoice_date,
                          [SalesInvoice.status.in_(_SI_ON_BOOKS)], 1).items():
        cogs[cid] += v
    for cid, v in _by_cat(SalesMemoItem, SalesMemo, 'sales_memo_id', SalesMemo.memo_date,
                          [SalesMemo.status == 'posted', SalesMemo.memo_type == 'credit'], -1).items():
        cogs[cid] += v
    for cid, v in _by_cat(SalesMemoItem, SalesMemo, 'sales_memo_id', SalesMemo.memo_date,
                          [SalesMemo.status == 'posted', SalesMemo.memo_type == 'debit'], 1).items():
        cogs[cid] += v
    return dict(cogs)


def _units_sold_by_category(start_date, end_date, branch_id):
    """Sigma(SI line qty) by category -- the 'units_sold' allocation driver. SI only, per
    spec; does not net memos (memo netting is the COGS driver's own job, not this one)."""
    branch = [SalesInvoice.branch_id == branch_id] if branch_id else []
    rows = db.session.query(
        Product.category_id,
        func.coalesce(func.sum(SalesInvoiceItem.quantity), 0),
    ).select_from(SalesInvoiceItem).join(
        SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id
    ).join(
        Product, SalesInvoiceItem.product_id == Product.id
    ).filter(
        SalesInvoice.invoice_date >= start_date, SalesInvoice.invoice_date <= end_date,
        SalesInvoice.status.in_(_SI_ON_BOOKS), *branch,
        SalesInvoiceItem.quantity.isnot(None),
    ).group_by(Product.category_id).all()
    return {cid: Decimal(str(q)) for cid, q in rows}


def _allocation_shares(basis, revenue_by_cat, gross_profit_by_cat, units_by_cat, category_ids):
    """{category_id: Decimal fraction of 1} for a basis, or {} -> the whole amount falls to
    Unallocated (no rule / basis='none' / zero total basis in the period -- never divide
    by zero, spec-locked explicit default)."""
    if not basis or basis == 'none':
        return {}
    if basis == 'equal':
        if not category_ids:
            return {}
        share = Decimal('1') / Decimal(len(category_ids))
        return {cid: share for cid in category_ids}
    source = {'revenue_share': revenue_by_cat, 'gross_profit_share': gross_profit_by_cat,
             'units_sold': units_by_cat}.get(basis)
    if source is None:
        return {}
    total = sum((source.get(cid, Decimal('0')) for cid in category_ids), Decimal('0'))
    if total == 0:
        return {}
    return {cid: source.get(cid, Decimal('0')) / total for cid in category_ids}


def _distribute(amount, shares):
    """{category_id: Decimal, ..., UNALLOCATED: Decimal} splitting `amount` per `shares`
    (fractions of 1); any residual (empty shares, or shares not summing to 1) falls to
    Unallocated. Exact-tie invariant: sum(returned.values()) == amount always, by
    construction (Unallocated soaks up whatever the explicit shares didn't claim)."""
    out = {}
    allocated = Decimal('0')
    for cid, frac in shares.items():
        out[cid] = amount * frac
        allocated += out[cid]
    out[UNALLOCATED] = amount - allocated
    return out


_REVENUE_SECTION_KEYS = {'revenue', 'contra_revenue'}
_SIGN_BY_KEY = {s['key']: s['sign'] for s in IS_SECTIONS}
_SIGN_BY_KEY['cogs_variance'] = _SIGN_BY_KEY['cogs']  # participates in Gross Profit like COGS itself


def _cogs_variance_distribution(actual_cogs_total, standard_cogs_by_cat, category_ids):
    """Variance = actual GL COGS - Sigma(ALL recognized standard COGS, incl. any
    uncategorized-product bucket). Distributed by each KNOWN category's own standard-COGS
    share of that total; the unshared remainder (the uncategorized bucket's share, plus a
    zero-standard-COGS period) falls to Unallocated via _distribute's leftover mechanic --
    never divide by zero, and the cogs row + this row always sum to exactly actual_cogs_total
    regardless of an uncategorized-product bucket (see _matrix_for_period's 'cogs' branch)."""
    standard_total = sum(standard_cogs_by_cat.values(), Decimal('0'))
    variance = actual_cogs_total - standard_total
    if standard_total == 0:
        return {UNALLOCATED: variance}
    shares = {cid: standard_cogs_by_cat.get(cid, Decimal('0')) / standard_total
             for cid in category_ids}
    return _distribute(variance, shares)


def _matrix_for_period(start_date, end_date, branch_id, categories):
    stmt = generate_income_statement(start_date, end_date, branch_id=branch_id)
    category_ids = list(categories.keys())

    revenue_by_cat = _revenue_by_category(start_date, end_date, branch_id)
    total_revenue = sum(revenue_by_cat.values(), Decimal('0'))
    revenue_shares = ({cid: revenue_by_cat.get(cid, Decimal('0')) / total_revenue
                      for cid in category_ids} if total_revenue != 0 else {})

    standard_cogs_by_cat = _standard_cogs_by_category(start_date, end_date, branch_id)
    units_by_cat = _units_sold_by_category(start_date, end_date, branch_id)
    gross_profit_by_cat = {cid: revenue_by_cat.get(cid, Decimal('0'))
                                - standard_cogs_by_cat.get(cid, Decimal('0'))
                          for cid in category_ids}

    rules = {r.account_id: r.basis for r in ExpenseAllocationRule.query.all()}

    rows = []
    running_by_col = defaultdict(lambda: Decimal('0'))

    def _row_dict(key, label, kind, by_col):
        return {'key': key, 'label': label, 'kind': kind,
               'by_column': {**{c: by_col.get(c, Decimal('0')) for c in category_ids},
                             UNALLOCATED: by_col.get(UNALLOCATED, Decimal('0')),
                             TOTAL: sum(by_col.values(), Decimal('0'))}}

    def _add_row(key, label, distributions):
        by_col = defaultdict(lambda: Decimal('0'))
        for dist in distributions:
            for col, amt in dist.items():
                by_col[col] += amt
        sign = _SIGN_BY_KEY.get(key, 1)
        for col, amt in by_col.items():
            running_by_col[col] += sign * amt
        rows.append(_row_dict(key, label, 'line', by_col))

    def _add_subtotal(key, label):
        rows.append(_row_dict(key, label, 'subtotal', running_by_col))

    for section in stmt['sections']:
        leaves = _resolve_leaves(section['lines'])
        if section['key'] in _REVENUE_SECTION_KEYS:
            distributions = [_distribute(leaf['amount'], revenue_shares) for leaf in leaves]
            _add_row(section['key'], section['label'], distributions)
        elif section['key'] == 'cogs':
            # The 'cogs' row shows STANDARD cost by category (an independent absolute
            # driver, not a proportion of the actual leaf amount); 'cogs_variance' is the
            # exact plug back to the actual GL total, so together they always tie.
            cogs_by_col = {cid: standard_cogs_by_cat.get(cid, Decimal('0')) for cid in category_ids}
            cogs_by_col[UNALLOCATED] = standard_cogs_by_cat.get(None, Decimal('0'))
            _add_row('cogs', section['label'], [cogs_by_col])
            variance_dist = _cogs_variance_distribution(
                Decimal(str(section['total'])), standard_cogs_by_cat, category_ids)
            _add_row('cogs_variance', 'COGS Variance', [variance_dist])
        else:
            distributions = []
            for leaf in leaves:
                basis = rules.get(leaf['account_id'], 'none')
                shares = _allocation_shares(basis, revenue_by_cat, gross_profit_by_cat,
                                            units_by_cat, category_ids)
                distributions.append(_distribute(leaf['amount'], shares))
            _add_row(section['key'], section['label'], distributions)
        if section.get('subtotal_label'):
            key = section['subtotal_label'].lower().replace(' ', '_')
            _add_subtotal(key, section['subtotal_label'])

    return {'rows': rows, 'stmt': stmt}


_RECON_KEYS = ('net_sales', 'gross_profit', 'operating_income', 'income_before_tax', 'net_income')


def _reconcile(period):
    stmt = period['stmt']
    row_by_key = {r['key']: r for r in period['rows']}
    checks = {}
    for key in _RECON_KEYS:
        row = row_by_key.get(key)
        matrix_total = float(row['by_column'][TOTAL]) if row else 0.0
        is_total = stmt[key]
        checks[key] = {'is_total': is_total, 'matrix_total': matrix_total,
                      'ties': abs(is_total - matrix_total) < 0.01}
    return checks


def _finalize_rows(period):
    return [{'key': r['key'], 'label': r['label'], 'kind': r['kind'],
            'by_column': {k: float(v) for k, v in r['by_column'].items()}}
           for r in period['rows']]


def generate_income_statement_by_product_line(as_of, mtd_start, ytd_start, branch_id=None):
    categories = _categories()
    mtd = _matrix_for_period(mtd_start, as_of, branch_id, categories)
    ytd = _matrix_for_period(ytd_start, as_of, branch_id, categories)

    columns = ([{'category_id': c.id, 'code': c.code, 'name': c.name}
               for c in sorted(categories.values(), key=lambda c: c.code)]
              + [{'category_id': UNALLOCATED, 'code': None, 'name': 'Unallocated'},
                 {'category_id': TOTAL, 'code': None, 'name': 'Total'}])

    return {'as_of': as_of, 'columns': columns,
           'mtd': {'rows': _finalize_rows(mtd), 'reconciliation': _reconcile(mtd)},
           'ytd': {'rows': _finalize_rows(ytd), 'reconciliation': _reconcile(ytd)}}
