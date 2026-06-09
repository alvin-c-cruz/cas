from decimal import Decimal
from app.utils import ph_now


def compute_ap_aging(vendor_id):
    """Return AP aging buckets for a vendor (posted bills only)."""
    from app.purchase_bills.models import PurchaseBill
    today = ph_now().date()
    bills = PurchaseBill.query.filter_by(vendor_id=vendor_id, status='posted').all()
    buckets = {
        'current': Decimal('0.00'),
        '1_30': Decimal('0.00'),
        '31_60': Decimal('0.00'),
        '61_90': Decimal('0.00'),
        '90_plus': Decimal('0.00'),
    }
    for bill in bills:
        if bill.due_date is None:
            continue
        days_overdue = (today - bill.due_date).days
        amount = bill.balance or Decimal('0.00')
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


def compute_wht_ytd(vendor_id):
    """Return list of {code, name, total} dicts for WHT withheld this calendar year."""
    from app import db
    from app.purchase_bills.models import PurchaseBill, PurchaseBillItem
    from app.withholding_tax.models import WithholdingTax
    from sqlalchemy import extract
    year = ph_now().year
    rows = (
        db.session.query(
            PurchaseBillItem.wt_id,
            db.func.sum(PurchaseBillItem.wt_amount).label('total')
        )
        .join(PurchaseBill, PurchaseBillItem.bill_id == PurchaseBill.id)
        .filter(
            PurchaseBill.vendor_id == vendor_id,
            PurchaseBill.status == 'posted',
            extract('year', PurchaseBill.bill_date) == year,
            PurchaseBillItem.wt_id.isnot(None),
        )
        .group_by(PurchaseBillItem.wt_id)
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
