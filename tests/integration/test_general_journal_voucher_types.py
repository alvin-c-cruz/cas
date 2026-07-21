def test_stock_adjustment_and_receiving_report_in_voucher_types():
    from app.journals.views import VOUCHER_TYPES
    assert 'stock_adjustment' in VOUCHER_TYPES
    assert 'receiving_report' in VOUCHER_TYPES


def test_stock_adjustment_and_receiving_report_in_general_journal_entry_types():
    from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES
    assert 'stock_adjustment' in VOUCHER_ENTRY_TYPES
    assert 'receiving_report' in VOUCHER_ENTRY_TYPES
