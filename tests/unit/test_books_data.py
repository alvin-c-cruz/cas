from datetime import date
from decimal import Decimal
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.books_data import collect_books, BOOKS


def _voucher(branch_id, dr, cr, amount):
    e = JournalEntry(entry_number='JV-BD-1', entry_date=date(2026, 6, 12),
                     description='adj', entry_type='adjustment', branch_id=branch_id,
                     status='posted', total_debit=amount, total_credit=amount, reference='JV-1')
    db.session.add(e); db.session.flush()
    db.session.add(JournalEntryLine(entry_id=e.id, line_number=1, account_id=dr.id,
                                    debit_amount=amount, credit_amount=Decimal('0.00')))
    db.session.add(JournalEntryLine(entry_id=e.id, line_number=2, account_id=cr.id,
                                    debit_amount=Decimal('0.00'), credit_amount=amount))
    db.session.commit()


def test_books_list_has_six_books_in_order():
    keys = [b['key'] for b in BOOKS]
    assert keys == ['general_journal', 'general_ledger', 'sales_journal',
                    'purchase_journal', 'cash_receipts', 'cash_disbursements']


def test_collect_books_returns_period_and_six_books(db_session, main_branch,
                                                    cash_account, revenue_account):
    _voucher(main_branch.id, cash_account, revenue_account, Decimal('250'))
    args = {'date_from': '2026-01-01', 'date_to': '2026-12-31'}
    result = collect_books(main_branch.id, args)
    assert 'period' in result and 'label' in result['period']
    assert set(result['books'].keys()) == {
        'general_journal', 'general_ledger', 'sales_journal',
        'purchase_journal', 'cash_receipts', 'cash_disbursements'}
    gj = result['books']['general_journal']
    assert gj['kind'] == 'gj'
    assert gj['data']['total_debit'] == Decimal('250')
