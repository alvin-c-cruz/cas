"""The administrator may edit or delete a POSTED journal voucher (wave 1 item 1.3).

Bug report #6 (30 Oct 2026, JV-2026-10-0002): "follow the CV implementation on how the admin
can modify Journal Entry." The rules are the ones settled for every document on 6 Oct 2026
(app-docs/admin-override-checklist.md, row 6): admin only; a reason of 10+ characters; edit in
place (the voucher stays posted under the same number and posting stamp); delete is a hard
delete that frees the number; a closed period, a bank-reconciled line and a fixed-asset tag
still refuse. A journal entry that belongs to another document (a CDV, an invoice, a
reversal pair, a legacy import) is changed through that document, never here.
"""
import html
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from flask import g

from app import db
from app.audit.models import AuditLog
from app.journal_entries.models import JournalEntry
from tests.integration.test_jv_draft_edit import _accounts, _draft, _edit_payload, _lines

pytestmark = [pytest.mark.integration, pytest.mark.journal_entries]

POSTED_AT = datetime(2026, 10, 30, 10, 0, 0)


@pytest.fixture
def jv(admin_user, main_branch):
    a, b, c = _accounts()
    entry = _draft(main_branch, admin_user, b, a, number='JV-2026-10-0002',
                   entry_date=date(2026, 10, 30), amount='500.00', status='posted')
    entry.posted_by_id = admin_user.id
    entry.posted_at = POSTED_AT
    db.session.commit()
    return SimpleNamespace(entry=entry, a=a, b=b, c=c)


def _as(client, user, password, branch, login_user):
    g.pop('_login_user', None)
    login_user(client, user.username, password)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def admin(client, admin_user, main_branch, login_user):
    _as(client, admin_user, 'admin123', main_branch, login_user)
    return client


def _edit(client, jv, reason='Reclassify CD 1328E to fuel', lines=None, **over):
    lines = lines or _lines((jv.c.id, 'new debit', '750.00', '0'), (jv.a.id, 'new credit', '0', '750.00'))
    data = _edit_payload(jv.entry, lines, **over)
    if reason is not None:
        data['admin_reason'] = reason
    return client.post(f'/journal-entries/{jv.entry.id}/edit', data=data, follow_redirects=True)


def _delete(client, entry_id, reason='Entered twice by mistake'):
    data = {} if reason is None else {'delete_reason': reason}
    return client.post(f'/journal-entries/{entry_id}/delete', data=data, follow_redirects=True)


def _reload(entry_id):
    db.session.expire_all()
    return db.session.get(JournalEntry, entry_id)


def _audit(action, record_id):
    return (AuditLog.query.filter_by(module='journal_entry', action=action, record_id=record_id)
            .order_by(AuditLog.id.desc()).first())


def _close_period(d):
    from app.periods.models import AccountingPeriod
    db.session.add(AccountingPeriod(year=d.year, month=d.month, status='closed'))
    db.session.commit()


# ----------------------------------------------------------------------------- edit

class TestEdit:
    def test_the_edit_page_opens_with_a_reason_box(self, admin, jv):
        html = admin.get(f'/journal-entries/{jv.entry.id}/edit').get_data(as_text=True)
        assert 'name="admin_reason"' in html
        assert 'Edit Posted Journal Entry (admin)' in html

    def test_admin_edits_a_posted_voucher_in_place(self, admin, jv, admin_user):
        resp = _edit(admin, jv)
        assert resp.status_code == 200
        entry = _reload(jv.entry.id)
        assert entry.status == 'posted'
        assert entry.entry_number == 'JV-2026-10-0002'
        assert (entry.posted_at, entry.posted_by_id) == (POSTED_AT, admin_user.id)
        assert entry.description == 'edited description'
        assert [(l.account_id, l.debit_amount, l.credit_amount) for l in entry.lines] == [
            (jv.c.id, Decimal('750.00'), Decimal('0.00')), (jv.a.id, Decimal('0.00'), Decimal('750.00'))]
        assert (entry.total_debit, entry.total_credit, entry.is_balanced) == (
            Decimal('750.00'), Decimal('750.00'), True)

    def test_the_edit_is_audited_with_its_reason_and_the_lines(self, admin, jv):
        _edit(admin, jv)
        row = _audit('admin_edit_posted', jv.entry.id)
        assert row is not None
        assert 'Reclassify CD 1328E to fuel' in row.notes
        assert 'lines' in (row.old_values or '') and 'lines' in (row.new_values or '')

    def test_a_number_outside_the_month_is_kept_not_renumbered(self, admin, jv):
        """In place means under the same number, even when the date moves month."""
        _edit(admin, jv, entry_date='2026-11-02')
        entry = _reload(jv.entry.id)
        assert (entry.entry_number, entry.entry_date) == ('JV-2026-10-0002', date(2026, 11, 2))

    @pytest.mark.parametrize('reason', [None, '', 'too short'])
    def test_a_reason_is_required(self, admin, jv, reason):
        resp = _edit(admin, jv, reason=reason)
        assert b'A reason of at least 10 characters is required' in resp.data
        assert _reload(jv.entry.id).total_debit == Decimal('500.00')

    def test_unbalanced_lines_are_refused(self, admin, jv):
        resp = _edit(admin, jv, lines=_lines((jv.c.id, 'd', '750.00', '0'), (jv.a.id, 'c', '0', '700.00')))
        assert b'Entry is not balanced' in resp.data
        assert _reload(jv.entry.id).total_debit == Decimal('500.00')

    def test_a_closed_period_refuses(self, admin, jv):
        _close_period(jv.entry.entry_date)
        resp = _edit(admin, jv)
        assert b'Cannot edit posted journal entry JV-2026-10-0002' in resp.data
        assert _reload(jv.entry.id).total_debit == Decimal('500.00')

    def test_moving_it_into_a_closed_period_refuses(self, admin, jv):
        _close_period(date(2026, 9, 1))
        _edit(admin, jv, entry_date='2026-09-30')
        assert _reload(jv.entry.id).entry_date == date(2026, 10, 30)

    def test_accountants_and_chief_accountants_cannot(
            self, client, jv, accountant_user, chief_accountant_user, main_branch, login_user):
        for user, password in ((accountant_user, 'accountant123'), (chief_accountant_user, 'chief123')):
            _as(client, user, password, main_branch, login_user)
            resp = _edit(client, jv)
            assert b'Only draft journal entries can be edited' in resp.data
        assert _reload(jv.entry.id).total_debit == Decimal('500.00')


# --------------------------------------------------------------------------- delete

class TestDelete:
    def test_admin_deletes_a_posted_voucher_and_frees_its_number(self, admin, jv):
        entry_id = jv.entry.id
        resp = _delete(admin, entry_id)
        assert ('Journal Entry "JV-2026-10-0002" deleted. Its number is free again.'
                in html.unescape(resp.get_data(as_text=True)))
        assert _reload(entry_id) is None
        assert JournalEntry.query.filter_by(entry_number='JV-2026-10-0002').count() == 0

    def test_the_delete_keeps_a_full_snapshot(self, admin, jv):
        entry_id = jv.entry.id
        _delete(admin, entry_id)
        row = _audit('admin_delete', entry_id)
        assert row is not None and 'Entered twice by mistake' in row.notes
        assert 'JV-2026-10-0002' in row.old_values and '500.00' in row.old_values

    @pytest.mark.parametrize('reason', [None, 'short'])
    def test_a_reason_is_required(self, admin, jv, reason):
        resp = _delete(admin, jv.entry.id, reason=reason)
        assert b'A reason of at least 10 characters is required' in resp.data
        assert _reload(jv.entry.id) is not None

    def test_accountants_cannot_delete_a_posted_voucher(
            self, client, jv, accountant_user, main_branch, login_user):
        _as(client, accountant_user, 'accountant123', main_branch, login_user)
        resp = _delete(client, jv.entry.id)
        assert b'Only draft journal entries can be deleted' in resp.data
        assert _reload(jv.entry.id) is not None

    def test_a_draft_still_deletes_without_a_reason(self, admin, jv, admin_user, main_branch):
        draft = _draft(main_branch, admin_user, jv.b, jv.a, number='JV-2026-10-0009',
                       entry_date=date(2026, 10, 30))
        _delete(admin, draft.id, reason=None)
        assert _reload(draft.id) is None

    def test_a_cancelled_voucher_cannot_be_deleted(self, admin, jv):
        jv.entry.status = 'cancelled'
        db.session.commit()
        resp = _delete(admin, jv.entry.id)
        assert b'Only draft journal entries can be deleted' in resp.data
        assert _reload(jv.entry.id) is not None


# ------------------------------------------------------------------------- refusals

class TestRefusals:
    """Each refusal holds for both edit and delete."""

    def _both_refused(self, admin, jv, message):
        resp = _edit(admin, jv)
        assert message in resp.data
        assert _reload(jv.entry.id).total_debit == Decimal('500.00')
        resp = _delete(admin, jv.entry.id)
        assert message in resp.data
        assert _reload(jv.entry.id) is not None

    def test_an_entry_another_document_owns(self, admin, jv, main_branch, admin_user):
        from tests.integration.test_cd_check_print import _check_cdv
        cdv = _check_cdv(db.session, main_branch)
        cdv.journal_entry_id = jv.entry.id
        db.session.commit()
        self._both_refused(admin, jv, b'belongs to a document (cash_disbursement_vouchers)')

    def test_a_reversal_pair(self, admin, jv, admin_user, main_branch):
        other = _draft(main_branch, admin_user, jv.b, jv.a, number='JE-OTHER-1',
                       entry_date=date(2026, 10, 1), status='posted')
        jv.entry.reversed_entry_id = other.id
        db.session.commit()
        self._both_refused(admin, jv, b'is part of a reversal')

    def test_a_legacy_import(self, admin, jv):
        jv.entry.source_ref = 'ric:journal:1'
        db.session.commit()
        self._both_refused(admin, jv, b'was imported from the legacy books')

    def test_a_bank_reconciled_line(self, admin, jv, main_branch):
        from app.bank_accounts.models import BankAccount
        from app.bank_reconciliation.models import BankReconciliation, ReconciliationItem
        bank = BankAccount(branch_id=main_branch.id, code='CBC919', name='CBC 919', account_id=jv.a.id)
        db.session.add(bank)
        db.session.flush()
        rec = BankReconciliation(bank_account_id=bank.id, statement_date=date.today(),
                                 statement_ending_balance=Decimal('0'), beginning_balance=Decimal('0'))
        db.session.add(rec)
        db.session.flush()
        db.session.add(ReconciliationItem(reconciliation_id=rec.id, je_line_id=jv.entry.lines.all()[1].id))
        db.session.commit()
        self._both_refused(admin, jv, b'cleared in a bank reconciliation')

    def test_a_fixed_asset_tag(self, admin, jv, monkeypatch):
        from app.fixed_assets import services
        monkeypatch.setattr(services, 'get_tags_for_document',
                            lambda kind, doc_id: [SimpleNamespace(code='FA-0007')] if kind == 'jv' else [])
        self._both_refused(admin, jv, b'fixed asset(s) FA-0007')

    def test_a_closed_period_refuses_the_delete(self, admin, jv):
        _close_period(jv.entry.entry_date)
        resp = _delete(admin, jv.entry.id)
        assert b'Cannot delete posted journal entry JV-2026-10-0002' in resp.data
        assert _reload(jv.entry.id) is not None


# -------------------------------------------------------------------------- buttons

class TestTheButtons:
    def test_admin_sees_edit_and_delete_on_a_posted_voucher(self, admin, jv):
        html = admin.get(f'/journal-entries/{jv.entry.id}').get_data(as_text=True)
        assert f'href="/journal-entries/{jv.entry.id}/edit"' in html and '>Edit (admin)</a>' in html
        assert 'id="adminDeleteModal"' in html and 'name="delete_reason"' in html

    def test_not_on_an_entry_another_document_owns(self, admin, jv, main_branch):
        from tests.integration.test_cd_check_print import _check_cdv
        cdv = _check_cdv(db.session, main_branch)
        cdv.journal_entry_id = jv.entry.id
        db.session.commit()
        html = admin.get(f'/journal-entries/{jv.entry.id}').get_data(as_text=True)
        assert '>Edit (admin)</a>' not in html and 'id="adminDeleteModal"' not in html

    def test_accountants_do_not_see_them(self, client, jv, accountant_user, main_branch, login_user):
        _as(client, accountant_user, 'accountant123', main_branch, login_user)
        html = client.get(f'/journal-entries/{jv.entry.id}').get_data(as_text=True)
        assert '>Edit (admin)</a>' not in html and 'id="adminDeleteModal"' not in html
