"""Draft journal vouchers are editable; posted and cancelled ones are not.

Owner, 2026-10-01: "Draft should be editable". BIR permanence still holds -- a posted
entry has no edit path (CAS-DEVELOPMENT.md, "posted documents are never edited"); a
draft is not in the books yet, so changing it is ordinary data entry.

Also covers the JV number following the ENTRY DATE's month (owner, same day: "the
numbering should be for August" for a JV dated 31 Aug entered on 1 Oct).
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration, pytest.mark.journal_entries]


def _accounts():
    a = Account(code='11700', name='Edit Test Input VAT', account_type='Asset',
                normal_balance='Debit', is_active=True)
    b = Account(code='65100', name='Edit Test Fuel', account_type='Expense',
                normal_balance='Debit', is_active=True)
    c = Account(code='65200', name='Edit Test Other', account_type='Expense',
                normal_balance='Debit', is_active=True)
    db.session.add_all([a, b, c])
    db.session.commit()
    return a, b, c


def _lines(*rows):
    return json.dumps([{'account_id': acct, 'description': desc, 'debit': dr, 'credit': cr}
                       for acct, desc, dr, cr in rows])


def _login(client, login_user, branch):
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _draft(branch, user, debit_acct, credit_acct, number='JV-2026-08-0001',
           entry_date=date(2026, 8, 31), amount='100.00', status='draft'):
    entry = JournalEntry(entry_number=number, entry_date=entry_date,
                         description='original description', reference='CV#1',
                         entry_type='adjustment', branch_id=branch.id,
                         created_by_id=user.id, status=status)
    entry.lines.append(JournalEntryLine(line_number=1, account_id=debit_acct.id,
                                        description='orig debit',
                                        debit_amount=Decimal(amount), credit_amount=Decimal('0')))
    entry.lines.append(JournalEntryLine(line_number=2, account_id=credit_acct.id,
                                        description='orig credit',
                                        debit_amount=Decimal('0'), credit_amount=Decimal(amount)))
    entry.calculate_totals()
    db.session.add(entry)
    db.session.commit()
    return entry


def _edit_payload(entry, lines, **over):
    data = {
        'entry_number': entry.entry_number,
        'entry_date': entry.entry_date.isoformat(),
        'description': 'edited description',
        'reference': 'CV#1634',
        'entry_type': 'adjustment',
        'lines': lines,
    }
    data.update(over)
    return data


# --------------------------------------------------------------------- edit: drafts

def test_edit_page_opens_for_a_draft_prefilled(client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()
    entry = _draft(main_branch, admin_user, a, b)

    resp = client.get(f'/journal-entries/{entry.id}/edit')

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Edit Journal Entry' in html
    assert 'original description' in html
    # the existing lines are handed to the line builder, not two blank rows
    assert '"orig debit"' in html and '"orig credit"' in html


def test_editing_a_draft_replaces_header_and_lines(client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, c = _accounts()
    entry = _draft(main_branch, admin_user, a, b)

    resp = client.post(f'/journal-entries/{entry.id}/edit', data=_edit_payload(
        entry, _lines((a.id, 'new debit', '250.00', 0),
                      (c.id, 'new credit a', 0, '200.00'),
                      (b.id, 'new credit b', 0, '50.00'))))

    assert resp.status_code == 302
    db.session.expire_all()
    edited = db.session.get(JournalEntry, entry.id)
    assert edited.status == 'draft'
    assert edited.entry_number == 'JV-2026-08-0001'
    assert edited.description == 'edited description'
    assert edited.reference == 'CV#1634'
    assert [(l.account_id, l.debit_amount, l.credit_amount) for l in edited.lines] == [
        (a.id, Decimal('250.00'), Decimal('0.00')),
        (c.id, Decimal('0.00'), Decimal('200.00')),
        (b.id, Decimal('0.00'), Decimal('50.00')),
    ]
    assert edited.total_debit == Decimal('250.00') == edited.total_credit
    assert edited.is_balanced
    assert JournalEntryLine.query.filter_by(entry_id=entry.id).count() == 3


def test_editing_a_draft_writes_a_real_audit_diff(client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()
    entry = _draft(main_branch, admin_user, a, b)

    client.post(f'/journal-entries/{entry.id}/edit', data=_edit_payload(
        entry, _lines((a.id, 'd', '300.00', 0), (b.id, 'c', 0, '300.00'))))

    row = AuditLog.query.filter_by(module='journal_entry', action='update',
                                   record_id=entry.id).order_by(AuditLog.id.desc()).first()
    assert row is not None, 'an edit must leave an audit row'
    old = json.loads(row.old_values) if isinstance(row.old_values, str) else row.old_values
    new = json.loads(row.new_values) if isinstance(row.new_values, str) else row.new_values
    assert old.get('description') == 'original description'
    assert new.get('description') == 'edited description'
    assert str(old.get('total_debit')) in ('100.00', '100')
    assert str(new.get('total_debit')) in ('300.00', '300')


def test_an_unbalanced_edit_is_refused_and_changes_nothing(client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()
    entry = _draft(main_branch, admin_user, a, b)

    resp = client.post(f'/journal-entries/{entry.id}/edit', data=_edit_payload(
        entry, _lines((a.id, 'd', '300.00', 0), (b.id, 'c', 0, '299.00'))))

    assert resp.status_code == 200, 'the form re-renders with the error, it does not vanish'
    assert 'not balanced' in resp.get_data(as_text=True)
    db.session.expire_all()
    same = db.session.get(JournalEntry, entry.id)
    assert same.description == 'original description'
    assert same.total_debit == Decimal('100.00')
    assert [l.description for l in same.lines] == ['orig debit', 'orig credit']


def test_moving_a_draft_to_another_month_renumbers_it_for_that_month(
        client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()
    entry = _draft(main_branch, admin_user, a, b, number='JV-2026-10-0001',
                   entry_date=date(2026, 10, 1))

    client.post(f'/journal-entries/{entry.id}/edit', data=_edit_payload(
        entry, _lines((a.id, 'd', '100.00', 0), (b.id, 'c', 0, '100.00')),
        entry_date='2026-08-31'))

    db.session.expire_all()
    moved = db.session.get(JournalEntry, entry.id)
    assert moved.entry_date == date(2026, 8, 31)
    assert moved.entry_number == 'JV-2026-08-0001'


# ------------------------------------------------------------- edit: not drafts

@pytest.mark.parametrize('status', ['posted', 'cancelled'])
def test_posted_and_cancelled_entries_cannot_be_edited(
        client, admin_user, main_branch, login_user, status):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()
    entry = _draft(main_branch, admin_user, a, b, status=status)

    get = client.get(f'/journal-entries/{entry.id}/edit')
    post = client.post(f'/journal-entries/{entry.id}/edit', data=_edit_payload(
        entry, _lines((a.id, 'd', '999.00', 0), (b.id, 'c', 0, '999.00'))))

    assert get.status_code == 302 and post.status_code == 302
    assert f'/journal-entries/{entry.id}' in post.headers['Location']
    db.session.expire_all()
    same = db.session.get(JournalEntry, entry.id)
    assert same.description == 'original description'
    assert same.total_debit == Decimal('100.00')


def test_a_draft_in_a_branch_the_user_cannot_reach_cannot_be_edited(
        client, admin_user, accountant_user, main_branch, branch_manila, login_user):
    """An accountant assigned only to MAIN gets a 404 for a Manila draft. (A full-access
    user is switched to the record's branch instead -- require_same_branch's design.)"""
    login_user(client, 'accountant', 'accountant123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    a, b, _ = _accounts()
    foreign = _draft(branch_manila, admin_user, a, b)

    resp = client.post(f'/journal-entries/{foreign.id}/edit', data=_edit_payload(
        foreign, _lines((a.id, 'd', '5.00', 0), (b.id, 'c', 0, '5.00'))))

    assert resp.status_code == 404
    db.session.expire_all()
    assert db.session.get(JournalEntry, foreign.id).description == 'original description'


def test_detail_page_offers_edit_only_on_a_draft(client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()
    draft = _draft(main_branch, admin_user, a, b, number='JV-2026-08-0001')
    posted = _draft(main_branch, admin_user, a, b, number='JV-2026-08-0002', status='posted')

    draft_html = client.get(f'/journal-entries/{draft.id}').get_data(as_text=True)
    posted_html = client.get(f'/journal-entries/{posted.id}').get_data(as_text=True)

    assert f'href="/journal-entries/{draft.id}/edit"' in draft_html
    assert f'href="/journal-entries/{posted.id}/edit"' not in posted_html


# ------------------------------------------------- numbering follows the entry date

def test_create_dated_in_a_past_month_takes_that_months_number(
        client, admin_user, main_branch, login_user):
    """The form suggests a number for TODAY's month; a JV dated in another month must
    not keep it -- the saved number follows the entry date."""
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()

    client.post('/journal-entries/create', data={
        'entry_number': 'JV-2026-10-0001',          # what the form suggested on 1 Oct
        'entry_date': '2026-08-31',
        'description': 'august adjustment',
        'reference': 'CV#1634',
        'entry_type': 'adjustment',
        'lines': _lines((a.id, 'd', '32185.71', 0), (b.id, 'c', 0, '32185.71')),
    })

    saved = JournalEntry.query.filter_by(description='august adjustment').one()
    assert saved.entry_number == 'JV-2026-08-0001'


def test_create_keeps_a_typed_number_that_matches_the_entry_month(
        client, admin_user, main_branch, login_user):
    _login(client, login_user, main_branch)
    a, b, _ = _accounts()

    client.post('/journal-entries/create', data={
        'entry_number': 'JV-2026-08-0007',
        'entry_date': '2026-08-31',
        'description': 'typed number',
        'reference': '',
        'entry_type': 'adjustment',
        'lines': _lines((a.id, 'd', '1.00', 0), (b.id, 'c', 0, '1.00')),
    })

    assert JournalEntry.query.filter_by(description='typed number').one().entry_number == 'JV-2026-08-0007'
