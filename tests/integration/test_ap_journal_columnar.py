from decimal import Decimal
from datetime import date
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journals.ap_journal_data import build_columnar


def _acct(code, name, atype, normal):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=atype,
                    normal_balance=normal, is_active=True)
        db.session.add(a)
        db.session.commit()
    return a


def _entry(branch_id, status, entry_date, number, lines):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=entry_date,
                      description='x', reference=number, entry_type='purchase',
                      branch_id=branch_id, status=status, is_balanced=True,
                      total_debit=Decimal('0'), total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=n, account_id=acct.id,
            debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
        n += 1
    db.session.commit()
    return je


def test_build_columnar_posted_pivot_and_balance(db_session):
    branch = Branch(name='Main', code='MAIN'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    wt = _acct('20301', 'WHT Payable - Expanded', 'Liability', 'credit')
    vat = _acct('10610', 'Input VAT', 'Asset', 'debit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')

    # Bill: Dr Rent 10,000 + Dr Input VAT 1,200 ; Cr WHT 200 + Cr AP 11,000
    je = _entry(branch.id, 'posted', date(2026, 6, 1), 'JE-1',
                [(rent, 10000, 0), (vat, 1200, 0), (wt, 0, 200), (ap, 0, 11000)])

    matrix = build_columnar(
        posted_entries=[je], draft_entries=[],
        ap_account_id=ap.id, wt_account_id=wt.id, input_vat_account_ids={vat.id})

    codes = [c['code'] for c in matrix['columns']]
    assert codes == ['20101', '20301', '10610', '60400']  # AP, WHT, VAT, other
    row = matrix['rows'][0]
    assert row['is_draft'] is False
    assert row['cells'][ap.id] == Decimal('-11000')   # credit → negative
    assert row['cells'][rent.id] == Decimal('10000')
    assert matrix['totals'][ap.id] == Decimal('-11000')
    assert matrix['grand_total'] == Decimal('0')
    assert matrix['balanced'] is True


def test_build_columnar_draft_excluded_from_totals_and_columns(db_session):
    branch = Branch(name='B2', code='B2'); db.session.add(branch); db.session.commit()
    ap = _acct('20101', 'Accounts Payable - Trade', 'Liability', 'credit')
    rent = _acct('60400', 'Rent Expense', 'Expense', 'debit')
    util = _acct('60500', 'Utilities Expense', 'Expense', 'debit')

    posted = _entry(branch.id, 'posted', date(2026, 6, 2), 'JE-P',
                    [(rent, 5000, 0), (ap, 0, 5000)])
    draft = _entry(branch.id, 'draft', date(2026, 6, 3), 'JE-D',
                   [(util, 999, 0), (ap, 0, 999)])

    matrix = build_columnar([posted], [draft], ap.id, None, set())

    codes = [c['code'] for c in matrix['columns']]
    assert '60500' not in codes               # draft-only account makes no column
    assert matrix['totals'].get(rent.id) == Decimal('5000')
    # draft row present, flagged, no cells
    draft_rows = [r for r in matrix['rows'] if r['is_draft']]
    assert len(draft_rows) == 1
    assert draft_rows[0]['cells'] == {}
