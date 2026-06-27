"""Integration tests: BIR book header macro adoption in General Ledger print."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


# ── Helpers (verbatim from test_general_ledger_views.py) ─────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _post_je(branch_id, account, contra, when, number):
    je = JournalEntry(entry_number=number, entry_date=when, description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True,
                      total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=account.id,
                                    debit_amount=Decimal('100'), credit_amount=Decimal('0'),
                                    description='dr'))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=contra.id,
                                    debit_amount=Decimal('0'), credit_amount=Decimal('100'),
                                    description='cr'))
    db.session.commit()
    return je


# ── Company seed helper ───────────────────────────────────────────────────────

def _set_company(name='Acme Trading Inc.', tin='123-456-789', rdo='050'):
    for k, v in [('company_name', name), ('company_tin', tin), ('tin_branch_code', '00000'),
                 ('rdo_code', rdo), ('company_address', '1 Rizal St, Manila')]:
        db.session.add(AppSettings(key=k, value=v))
    db.session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_general_ledger_print_shows_bir_header(client, db_session, main_branch,
                                               admin_user, cash_account, revenue_account):
    _set_company()
    _post_je(main_branch.id, cash_account, revenue_account, date.today(), 'JE-H1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/general-ledger/print')
    assert resp.status_code == 200
    assert b'ACME TRADING INC.' in resp.data
    assert b'TIN: 123-456-789-00000' in resp.data
    assert b'RDO: 050' in resp.data
