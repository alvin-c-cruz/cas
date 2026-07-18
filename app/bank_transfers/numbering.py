"""BT-YYYY-MM-NNNN numbering, mirroring generate_po_number's pattern exactly."""
from app.utils import ph_now
from app.bank_transfers.models import BankTransfer


def generate_bank_transfer_number():
    today = ph_now().date()
    prefix = f"BT-{today.year:04d}-{today.month:02d}-"
    rows = (BankTransfer.query
            .filter(BankTransfer.transfer_number.like(prefix + '%'))
            .with_entities(BankTransfer.transfer_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
