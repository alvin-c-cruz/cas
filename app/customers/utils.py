from decimal import Decimal
from app.utils import ph_now


def compute_ar_aging(customer_id):
    """Return AR aging buckets for a customer (posted and partially-paid invoices)."""
    from app.sales_invoices.models import SalesInvoice
    today = ph_now().date()
    invoices = SalesInvoice.query.filter(
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status.in_(['posted', 'partially_paid'])
    ).all()
    buckets = {
        'current': Decimal('0.00'),
        '1_30': Decimal('0.00'),
        '31_60': Decimal('0.00'),
        '61_90': Decimal('0.00'),
        '90_plus': Decimal('0.00'),
    }
    for inv in invoices:
        if inv.due_date is None:
            continue
        days_overdue = (today - inv.due_date).days
        amount = inv.balance or Decimal('0.00')
        if days_overdue <= 0:
            buckets['current'] += amount
        elif days_overdue <= 30:
            buckets['1_30'] += amount
        elif days_overdue <= 60:
            buckets['31_60'] += amount
        elif days_overdue <= 90:
            buckets['61_90'] += amount
        else:
            buckets['90_plus'] += amount
    buckets['total'] = sum(buckets.values(), Decimal('0.00'))
    return buckets


def compute_creditable_wht_ytd(customer_id):
    """Return list of {code, name, total} for creditable WHT (BIR 2307) the customer
    withheld from us this calendar year. Mirrors vendors.compute_wht_ytd; the math is
    identical, only the AR-side meaning differs."""
    from app import db
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.withholding_tax.models import WithholdingTax
    from sqlalchemy import extract
    year = ph_now().year
    rows = (
        db.session.query(
            SalesInvoiceItem.wt_id,
            db.func.sum(SalesInvoiceItem.wt_amount).label('total')
        )
        .join(SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id)
        .filter(
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.status == 'posted',
            extract('year', SalesInvoice.invoice_date) == year,
            SalesInvoiceItem.wt_id.isnot(None),
        )
        .group_by(SalesInvoiceItem.wt_id)
        .all()
    )
    wt_ids = [row.wt_id for row in rows]
    wt_map = {wt.id: wt for wt in WithholdingTax.query.filter(WithholdingTax.id.in_(wt_ids)).all()}
    result = []
    for row in rows:
        wt = wt_map.get(row.wt_id)
        if wt:
            result.append({'code': wt.code, 'name': wt.name, 'total': row.total or Decimal('0.00')})
    return result
