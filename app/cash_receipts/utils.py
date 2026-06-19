from decimal import Decimal
from app.cash_receipts.models import CashReceiptVoucher
from app.utils import ph_now


def compute_crv_summary(branch_id):
    now = ph_now()
    crvs_posted = CashReceiptVoucher.query.filter_by(branch_id=branch_id, status='posted').all()
    received_this_month = sum(
        Decimal(str(c.total_amount)) for c in crvs_posted
        if c.crv_date and c.crv_date.year == now.year and c.crv_date.month == now.month
    )
    draft_count = CashReceiptVoucher.query.filter_by(branch_id=branch_id, status='draft').count()
    cancelled_count = CashReceiptVoucher.query.filter_by(branch_id=branch_id, status='cancelled').count()
    return dict(
        received_this_month=received_this_month,
        draft_count=draft_count,
        cancelled_count=cancelled_count,
    )
