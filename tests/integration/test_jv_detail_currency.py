from datetime import date
from decimal import Decimal
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.models import Account


def _jv(branch):
    a1 = Account(code='10101', name='Cash on Hand', account_type='Asset',
                 normal_balance='Debit', is_active=True)
    a2 = Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',
                 normal_balance='Debit', is_active=True)
    db.session.add_all([a1, a2]); db.session.commit()
    e = JournalEntry(entry_number='JV-2026-07-0001', entry_date=date(2026, 7, 8),
                     description='Test', entry_type='adjustment', branch_id=branch.id,
                     total_debit=Decimal('5000.00'), total_credit=Decimal('5000.00'),
                     is_balanced=True, status='draft')
    db.session.add(e); db.session.commit()
    db.session.add_all([
        JournalEntryLine(entry_id=e.id, line_number=1, account_id=a1.id,
                         debit_amount=Decimal('5000.00'), credit_amount=Decimal('0.00')),
        JournalEntryLine(entry_id=e.id, line_number=2, account_id=a2.id,
                         debit_amount=Decimal('0.00'), credit_amount=Decimal('5000.00')),
    ]); db.session.commit()
    return e


def test_jv_detail_has_no_currency_symbol(client, admin_user, main_branch, login_user):
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    e = _jv(main_branch)
    html = client.get(f'/journal-entries/{e.id}').get_data(as_text=True)
    assert html.count('₱') == 0          # no peso glyph anywhere
    assert '5,000.00' in html                 # the figures still render (bare)
