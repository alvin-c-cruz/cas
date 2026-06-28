from datetime import date
from decimal import Decimal
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.books_data import collect_books, BOOKS


def _voucher(branch_id, dr, cr, amount, entry_date=date(2026, 6, 12), entry_number='JV-BD-1'):
    e = JournalEntry(entry_number=entry_number, entry_date=entry_date,
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


def test_collect_books_honors_explicit_date_range(db_session, main_branch,
                                                   cash_account, revenue_account):
    """Part B: collect_books must honour an explicit date_from/date_to even when
    mode='custom' is absent (the hub never sent it before the fix).

    Avoids current-month masking by using January 2026 — a month that CANNOT
    match today (June 2026 or later).  A June entry with a different amount
    proves the in-range entry is selected and the out-of-range one is excluded.
    """
    # Entry dated 2026-01-15 — inside the target range, outside current month
    _voucher(main_branch.id, cash_account, revenue_account,
             Decimal('100'), entry_date=date(2026, 1, 15), entry_number='JV-BD-JAN')
    # Entry dated 2026-06-12 — current month; must NOT appear in January query
    _voucher(main_branch.id, cash_account, revenue_account,
             Decimal('200'), entry_date=date(2026, 6, 12), entry_number='JV-BD-JUN')

    # Explicit Jan range, NO mode key — this is exactly what the hub submitted before the fix
    args = {'date_from': '2026-01-01', 'date_to': '2026-01-31'}
    result = collect_books(main_branch.id, args)

    gj = result['books']['general_journal']
    # Only the January entry (100) must appear; June entry (200) must not
    assert gj['data']['total_debit'] == Decimal('100'), (
        f"Expected 100 (Jan only) but got {gj['data']['total_debit']} — "
        "range not honored; mode='custom' normalization is missing"
    )
