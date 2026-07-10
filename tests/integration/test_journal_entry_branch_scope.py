"""Journal-entry routes must be branch-scoped, like every other document.

`view`, `print`, `post`, `cancel` and `delete` fetched a JournalEntry by bare id
with no branch check -- so a user assigned to Branch A, holding the journal_entries
book, could read or mutate any other branch's voucher (and its plug legs, amounts,
descriptions) by walking integer ids. SI/AP/CDV/CRV all 404 on a branch mismatch.

No admin bypass: the canonical helpers scope on the ONE `selected_branch_id`, and a
full-access user reaches another branch by switching the session branch.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration, pytest.mark.journal_entries]


def _login_admin(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _set_branch(client, branch_id):
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id


def _make_je(db_session, branch_id, user, status='posted'):
    acct = Account(code='10302', name='JE Scope Account', account_type='Asset',
                   normal_balance='debit', is_active=True)
    db_session.add(acct)
    db_session.flush()
    je = JournalEntry(
        entry_number='JV-SCOPE-0001', entry_date=date(2099, 1, 5),
        description='Voucher in the other branch', entry_type='adjustment',
        branch_id=branch_id, created_by_id=user.id, status=status,
        is_balanced=True, total_debit=Decimal('500.00'), total_credit=Decimal('500.00'),
    )
    db_session.add(je)
    db_session.flush()
    db_session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=acct.id,
                         debit_amount=Decimal('500.00'), credit_amount=Decimal('0.00')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=acct.id,
                         debit_amount=Decimal('0.00'), credit_amount=Decimal('500.00')),
    ])
    db_session.commit()
    return je


class TestJEBranchScoping:
    """Session branch = main_branch; the JE lives in branch_manila."""

    def test_view_cross_branch_returns_404(self, client, db_session, admin_user,
                                           main_branch, branch_manila):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = _make_je(db_session, branch_manila.id, admin_user)
        assert client.get(f'/journal-entries/{je.id}').status_code == 404

    def test_print_cross_branch_returns_404(self, client, db_session, admin_user,
                                            main_branch, branch_manila):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = _make_je(db_session, branch_manila.id, admin_user)
        assert client.get(f'/journal-entries/{je.id}/print').status_code == 404

    def test_post_cross_branch_returns_404_and_stays_draft(self, client, db_session,
                                                           admin_user, main_branch, branch_manila):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = _make_je(db_session, branch_manila.id, admin_user, status='draft')
        assert client.post(f'/journal-entries/{je.id}/post').status_code == 404
        db_session.refresh(je)
        assert je.status == 'draft'

    def test_cancel_cross_branch_returns_404_and_stays_posted(self, client, db_session,
                                                             admin_user, main_branch, branch_manila):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = _make_je(db_session, branch_manila.id, admin_user, status='posted')
        assert client.post(f'/journal-entries/{je.id}/cancel').status_code == 404
        db_session.refresh(je)
        assert je.status == 'posted'
        assert je.cancelled_at is None

    def test_delete_cross_branch_returns_404_and_row_survives(self, client, db_session,
                                                            admin_user, main_branch, branch_manila):
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = _make_je(db_session, branch_manila.id, admin_user, status='draft')
        assert client.post(f'/journal-entries/{je.id}/delete').status_code == 404
        assert db.session.get(JournalEntry, je.id) is not None

    def test_same_branch_view_still_200(self, client, db_session, admin_user, main_branch):
        """The guard must not be over-broad: same-branch access still works."""
        _login_admin(client)
        _set_branch(client, main_branch.id)
        je = _make_je(db_session, main_branch.id, admin_user)
        assert client.get(f'/journal-entries/{je.id}').status_code == 200
