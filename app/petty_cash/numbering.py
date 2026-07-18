"""PCV-YYYY-MM-NNNN / PCR-YYYY-MM-NNNN numbering, mirroring
generate_bank_transfer_number's pattern exactly (R-04 slice 4)."""
from app.utils import ph_now
from app.petty_cash.models import PettyCashVoucher, PettyCashReplenishment


def _next_number(Model, number_attr, prefix_letters):
    today = ph_now().date()
    prefix = f"{prefix_letters}-{today.year:04d}-{today.month:02d}-"
    rows = (Model.query.filter(getattr(Model, number_attr).like(prefix + '%'))
            .with_entities(getattr(Model, number_attr)).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"


def generate_pcv_number():
    return _next_number(PettyCashVoucher, 'voucher_number', 'PCV')


def generate_pcr_number():
    return _next_number(PettyCashReplenishment, 'replenishment_number', 'PCR')
