"""Sales by Product Line report generator (revenue-only, source-document based).

Reads posted Sales-Invoice and credit/debit-memo LINE items, attributes each line's
net-of-VAT amount to its product's category, and buckets untagged lines as 'Unassigned'.
The GL is NOT touched — see spec 2026-07-11-sales-by-product-line-design.md.
"""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import func

from app import db
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem
from app.reports.financial import generate_income_statement

# Invoices are "on the books" once posted and through their paid lifecycle.
_SI_ON_BOOKS = ('posted', 'partially_paid', 'paid')


def _net_by_category(item_model, header_model, header_fk, date_col,
                     start_date, end_date, branch_id, extra_filters):
    """Return [(category_id_or_None, net_decimal_as_db_number)] grouped by product category.

    net per line = line_total - vat_amount. An outer join to Product means a NULL
    product_id yields category_id None; a product with a NULL category also yields None.
    """
    branch = [header_model.branch_id == branch_id] if branch_id else []
    return db.session.query(
        Product.category_id,
        func.coalesce(func.sum(item_model.line_total - item_model.vat_amount), 0),
    ).select_from(item_model).join(
        header_model, getattr(item_model, header_fk) == header_model.id
    ).outerjoin(
        Product, item_model.product_id == Product.id
    ).filter(
        date_col >= start_date, date_col <= end_date, *extra_filters, *branch,
    ).group_by(Product.category_id).all()


def generate_sales_by_product_line(start_date, end_date, branch_id=None):
    acc = defaultdict(lambda: Decimal('0.00'))

    # + Sales Invoices
    for cid, net in _net_by_category(
            SalesInvoiceItem, SalesInvoice, 'invoice_id', SalesInvoice.invoice_date,
            start_date, end_date, branch_id, [SalesInvoice.status.in_(_SI_ON_BOOKS)]):
        acc[cid] += Decimal(str(net))

    # - Credit memos (returns/allowances reduce sales)
    for cid, net in _net_by_category(
            SalesMemoItem, SalesMemo, 'sales_memo_id', SalesMemo.memo_date,
            start_date, end_date, branch_id,
            [SalesMemo.status == 'posted', SalesMemo.memo_type == 'credit']):
        acc[cid] -= Decimal(str(net))

    # + Debit notes (additional charges add to sales)
    for cid, net in _net_by_category(
            SalesMemoItem, SalesMemo, 'sales_memo_id', SalesMemo.memo_date,
            start_date, end_date, branch_id,
            [SalesMemo.status == 'posted', SalesMemo.memo_type == 'debit']):
        acc[cid] += Decimal(str(net))

    cats = {c.id: c for c in ProductCategory.query.all()}
    rows, unassigned, total = [], Decimal('0.00'), Decimal('0.00')
    for cid, net in acc.items():
        total += net
        if cid is None or cid not in cats:
            unassigned += net
            continue
        c = cats[cid]
        rows.append({'category_id': c.id, 'code': c.code, 'name': c.name, 'net': float(net)})
    rows.sort(key=lambda r: r['code'])
    return {'period_start': start_date, 'period_end': end_date, 'rows': rows,
            'unassigned': float(unassigned), 'total': float(total)}


def _pct(net, total):
    return round(net / total * 100, 2) if total else 0.0


def build_sales_by_product_line(as_of, mtd_start, ytd_start, branch_id=None):
    mtd = generate_sales_by_product_line(mtd_start, as_of, branch_id)
    ytd = generate_sales_by_product_line(ytd_start, as_of, branch_id)

    mtd_by_id = {r['category_id']: r for r in mtd['rows']}
    ytd_by_id = {r['category_id']: r for r in ytd['rows']}
    meta = {r['category_id']: r for r in (*ytd['rows'], *mtd['rows'])}

    rows = []
    for cid in sorted(set(mtd_by_id) | set(ytd_by_id), key=lambda i: meta[i]['code']):
        m = mtd_by_id.get(cid, {}).get('net', 0.0)
        y = ytd_by_id.get(cid, {}).get('net', 0.0)
        rows.append({'category_id': cid, 'code': meta[cid]['code'], 'name': meta[cid]['name'],
                     'mtd': m, 'ytd': y,
                     'mtd_pct': _pct(m, mtd['total']), 'ytd_pct': _pct(y, ytd['total'])})

    unassigned = {'mtd': mtd['unassigned'], 'ytd': ytd['unassigned'],
                  'mtd_pct': _pct(mtd['unassigned'], mtd['total']),
                  'ytd_pct': _pct(ytd['unassigned'], ytd['total'])}
    total = {'mtd': mtd['total'], 'ytd': ytd['total']}

    is_mtd = generate_income_statement(mtd_start, as_of, branch_id=branch_id).get('net_sales', 0.0)
    is_ytd = generate_income_statement(ytd_start, as_of, branch_id=branch_id).get('net_sales', 0.0)
    var_mtd = round(is_mtd - total['mtd'], 2)
    var_ytd = round(is_ytd - total['ytd'], 2)
    reconciliation = {'is_net_sales_mtd': is_mtd, 'is_net_sales_ytd': is_ytd,
                      'variance_mtd': var_mtd, 'variance_ytd': var_ytd,
                      'reconciled': abs(var_mtd) < 0.01 and abs(var_ytd) < 0.01}

    return {'as_of': as_of, 'mtd_start': mtd_start, 'ytd_start': ytd_start,
            'rows': rows, 'unassigned': unassigned, 'total': total,
            'reconciliation': reconciliation}
