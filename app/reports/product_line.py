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
