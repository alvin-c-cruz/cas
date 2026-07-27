"""Bank Transfer numbering, mirroring generate_invoice_number's pattern exactly."""
from app.bank_transfers.models import BankTransfer


def generate_bank_transfer_number():
    """Plain continuous 5-digit sequence: 00001, 00002, ... No prefix, no reset.

    Each transfer gets the next number after the highest existing purely-numeric
    transfer_number. Legacy prefixed numbers (e.g. the old 'BT-2026-07-0030'
    format) are ignored.
    """
    rows = BankTransfer.query.with_entities(BankTransfer.transfer_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    next_num = (max(nums) + 1) if nums else 1
    return f'{next_num:05d}'
