from app.journal_entries.models import JournalEntry
import pytest

pytestmark = [pytest.mark.unit]


def _je(entry_number, reference, entry_type):
    return JournalEntry(entry_number=entry_number, reference=reference,
                        entry_type=entry_type, entry_date=None, description='x',
                        branch_id=1)


def test_manual_voucher_shows_jv_number():
    je = _je('JV-2026-06-0001', 'JV-2026-06-0001', 'adjustment')
    assert je.display_number == 'JV-2026-06-0001'


def test_new_reversal_shows_jv_number():
    je = _je('JV-2026-06-0002', 'CANCEL-AR-2026-06-0001', 'reversal')
    assert je.display_number == 'JV-2026-06-0002'


def test_sale_posting_shows_reference_not_je_number():
    je = _je('JE-2026-0047', 'AR-2026-06-0001', 'sale')
    assert je.display_number == 'AR-2026-06-0001'


def test_purchase_receipt_disbursement_show_reference():
    assert _je('JE-2026-0048', 'AP-2026-06-0003', 'purchase').display_number == 'AP-2026-06-0003'
    assert _je('JE-2026-0049', 'CR-2026-06-0002', 'receipt').display_number == 'CR-2026-06-0002'
    assert _je('JE-2026-0050', 'CD-2026-06-0005', 'disbursement').display_number == 'CD-2026-06-0005'


def test_legacy_je_reversal_falls_through_to_reference():
    je = _je('JE-2026-0051', 'VOID-AR-2026-06-0009', 'reversal')
    assert je.display_number == 'VOID-AR-2026-06-0009'


def test_falls_back_to_entry_number_when_reference_empty():
    je = _je('JE-2026-0052', '', 'sale')
    assert je.display_number == 'JE-2026-0052'
