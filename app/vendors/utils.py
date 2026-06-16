from decimal import Decimal
from app.utils import ph_now


def compute_ap_aging(vendor_id):
    """Return AP aging buckets for a vendor (posted and partially-paid bills)."""
    from app.accounts_payable.models import AccountsPayable
    today = ph_now().date()
    bills = AccountsPayable.query.filter(
        AccountsPayable.vendor_id == vendor_id,
        AccountsPayable.status.in_(['posted', 'partially_paid'])
    ).all()
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
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.withholding_tax.models import WithholdingTax
    from sqlalchemy import extract
    year = ph_now().year
    rows = (
        db.session.query(
            AccountsPayableItem.wt_id,
            db.func.sum(AccountsPayableItem.wt_amount).label('total')
        )
        .join(AccountsPayable, AccountsPayableItem.ap_id == AccountsPayable.id)
        .filter(
            AccountsPayable.vendor_id == vendor_id,
            AccountsPayable.status == 'posted',
            extract('year', AccountsPayable.ap_date) == year,
            AccountsPayableItem.wt_id.isnot(None),
        )
        .group_by(AccountsPayableItem.wt_id)
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


def generate_next_vendor_code():
    """Generate the next vendor code in sequence (V001, V002, etc.)"""
    from app.vendors.models import Vendor
    latest_vendor = Vendor.query.order_by(Vendor.code.desc()).first()

    if not latest_vendor or not latest_vendor.code.startswith('V'):
        return 'V001'

    try:
        latest_number = int(latest_vendor.code[1:])  # Remove 'V' prefix
        next_number = latest_number + 1
        return f'V{next_number:03d}'  # Format as V001, V002, etc.
    except (ValueError, IndexError):
        return 'V001'


def populate_vat_category_choices(form):
    """Populate VAT category choices from database"""
    from app.vat_categories.models import VATCategory
    vat_categories = VATCategory.query.filter_by(is_active=True).order_by(VATCategory.code).all()
    choices = [('', '— Select VAT Category —')]
    choices.extend([(cat.code, f'{cat.code} — {cat.name}') for cat in vat_categories])
    form.default_vat_category.choices = choices
