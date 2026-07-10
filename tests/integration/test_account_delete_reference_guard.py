"""Deleting a Chart-of-Accounts account that is referenced must be blocked.

SQLite FK enforcement is off app-wide, so nothing stops `db.session.delete(account)`
from orphaning posted journal_entry_lines (and document lines, cash headers, tax-
config FKs, child accounts). Customers and vendors have this guard; the Chart of
Accounts -- the highest-impact table -- did not, at either apply site: the
auto-approve path inside `delete`, and the reviewer `approve_request` path.

The account delete flows through the change-request approval workflow, so both apply
sites must fail closed, and references appearing between request and review must be
caught at approval time (TOCTOU) -- leaving the request pending so the reviewer
rejects it with a reason.
"""
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.accounts.approval_models import AccountChangeRequest
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.users.models import User
from app.users.module_access import default_all_permissions

pytestmark = [pytest.mark.integration, pytest.mark.accounts]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _acct(code, name='Acct', account_type='Asset', normal_balance='debit',
          parent_id=None, is_active=True):
    a = Account(code=code, name=name, account_type=account_type,
                normal_balance=normal_balance, parent_id=parent_id, is_active=is_active)
    db.session.add(a)
    db.session.commit()
    return a


def _je_line_on(account, branch_id, user_id):
    """A posted JE whose one line references `account` -- the highest-impact referent."""
    from datetime import date
    je = JournalEntry(entry_number='JV-DEL-0001', entry_date=date(2099, 1, 1),
                      description='refs account', entry_type='adjustment',
                      branch_id=branch_id, created_by_id=user_id, status='posted',
                      is_balanced=True, total_debit=Decimal('1.00'), total_credit=Decimal('1.00'))
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=account.id,
                                    debit_amount=Decimal('1.00'), credit_amount=Decimal('0.00')))
    db.session.commit()
    return je


class TestAutoApproveDeleteGuard:
    """A sole active accountant auto-approves -- so `delete` deletes in-request."""

    def _sole_accountant(self, db_session, branch):
        acc = User(username='soleacct', email='sole@test.com', full_name='Sole',
                   role='accountant', is_active=True)
        acc.set_password('accountant123')
        acc.set_book_permissions(default_all_permissions())
        db_session.add(acc)
        db_session.flush()
        acc.set_branches([branch])   # accountants are branch-scoped; unassigned => picker
        db_session.commit()
        return acc

    def test_delete_blocked_when_account_has_je_lines(
            self, client, db_session, admin_user, main_branch):
        acc = self._sole_accountant(db_session, main_branch)
        target = _acct('55501', 'Referenced Expense', 'Expense')
        _je_line_on(target, main_branch.id, admin_user.id)

        _login(client, 'soleacct', 'accountant123')
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id

        before = AccountChangeRequest.query.count()
        resp = client.post(f'/accounts/{target.id}/delete',
                           data={'request_reason': 'no longer used'}, follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(Account, target.id) is not None
        assert AccountChangeRequest.query.count() == before, 'no doomed request may be queued'
        assert b'inactive' in resp.data.lower()

    def test_delete_blocked_when_account_has_children(
            self, client, db_session, admin_user, main_branch):
        self._sole_accountant(db_session, main_branch)
        parent = _acct('55000', 'Parent')
        _acct('55010', 'Child', parent_id=parent.id)

        _login(client, 'soleacct', 'accountant123')
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id

        client.post(f'/accounts/{parent.id}/delete',
                    data={'request_reason': 'no longer used'}, follow_redirects=True)
        assert db.session.get(Account, parent.id) is not None

    def test_delete_blocked_when_account_is_wht_payable_target(
            self, client, db_session, admin_user, main_branch):
        from app.withholding_tax.models import WithholdingTax
        self._sole_accountant(db_session, main_branch)
        target = _acct('20301', 'WHT Payable', 'Liability', 'credit')
        db_session.add(WithholdingTax(code='WC158', name='WC158', rate=Decimal('1.00'),
                                      is_active=True, payable_account_id=target.id))
        db_session.commit()

        _login(client, 'soleacct', 'accountant123')
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id

        client.post(f'/accounts/{target.id}/delete',
                    data={'request_reason': 'no longer used'}, follow_redirects=True)
        assert db.session.get(Account, target.id) is not None

    def test_delete_allowed_when_unreferenced(
            self, client, db_session, admin_user, main_branch):
        from app.audit.models import AuditLog
        self._sole_accountant(db_session, main_branch)
        target = _acct('59999', 'Orphan Expense', 'Expense')

        _login(client, 'soleacct', 'accountant123')
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id

        client.post(f'/accounts/{target.id}/delete',
                    data={'request_reason': 'no longer used'}, follow_redirects=True)
        assert db.session.get(Account, target.id) is None
        req = AccountChangeRequest.query.filter_by(change_type='delete').first()
        assert req is not None and req.status == 'approved'
        assert AuditLog.query.filter_by(module='account', action='delete').first() is not None


class TestReviewerApproveDeleteGuard:
    """Two active accountants -> requests go pending -> a second one approves."""

    def _two_accountants(self, db_session, branch):
        users = []
        for i in (1, 2):
            u = User(username=f'acct{i}', email=f'acct{i}@test.com', full_name=f'Acct {i}',
                     role='accountant', is_active=True)
            u.set_password('accountant123')
            u.set_book_permissions(default_all_permissions())
            db_session.add(u)
            db_session.flush()
            u.set_branches([branch])
            users.append(u)
        db_session.commit()
        return users

    def test_reference_appearing_after_request_blocks_approval(
            self, client, db_session, admin_user, main_branch):
        self._two_accountants(db_session, main_branch)
        target = _acct('55502', 'Later-Referenced', 'Expense')

        _login(client, 'acct1', 'accountant123')
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        client.post(f'/accounts/{target.id}/delete',
                    data={'request_reason': 'no longer used'}, follow_redirects=True)
        req = AccountChangeRequest.query.filter_by(change_type='delete').first()
        assert req is not None and req.status == 'pending'

        # A reference appears between request and review.
        _je_line_on(target, main_branch.id, admin_user.id)

        _login(client, 'acct2', 'accountant123')
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        client.post(f'/accounts/approve/{req.id}', follow_redirects=True)

        assert db.session.get(Account, target.id) is not None
        db_session.refresh(req)
        assert req.status == 'pending', 'a blocked delete stays pending, not approved'
