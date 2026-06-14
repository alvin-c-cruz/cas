from decimal import Decimal
from app.utils import ph_now


def compute_cdv_summary(branch_id):
    from app import db
    from app.cash_disbursements.models import CashDisbursementVoucher
    today = ph_now().date()
    import calendar
    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    disbursed = (
        db.session.query(db.func.coalesce(db.func.sum(CashDisbursementVoucher.total_amount), 0))
        .filter(
            CashDisbursementVoucher.branch_id == branch_id,
            CashDisbursementVoucher.status == 'posted',
            CashDisbursementVoucher.cdv_date >= month_start,
            CashDisbursementVoucher.cdv_date <= month_end,
        )
        .scalar()
    )
    draft_count = (
        db.session.query(db.func.count(CashDisbursementVoucher.id))
        .filter(
            CashDisbursementVoucher.branch_id == branch_id,
            CashDisbursementVoucher.status == 'draft',
        )
        .scalar()
    )
    cancelled_count = (
        db.session.query(db.func.count(CashDisbursementVoucher.id))
        .filter(
            CashDisbursementVoucher.branch_id == branch_id,
            CashDisbursementVoucher.status == 'cancelled',
        )
        .scalar()
    )
    return {
        'disbursed_this_month': Decimal(str(disbursed)).quantize(Decimal('0.01')),
        'draft_count': draft_count,
        'cancelled_count': cancelled_count,
    }
