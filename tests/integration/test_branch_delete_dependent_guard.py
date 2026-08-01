"""Deleting a branch must not orphan the transactions it owns.

`branches.delete` guarded only two things: the MAIN branch, and branches with
assigned users. It never looked at transactional data. Combined with two facts
this codebase already documents, that silently orphans records:

  * SQLite foreign-key enforcement is OFF app-wide (no PRAGMA) -- memory
    `sqlite-fk-off-delete-guard` -- so the database will not refuse the delete.
  * `SalesInvoice.branch_id` and its siblings are nullable, so nothing at the
    model layer refuses it either.

The orphaned rows then disappear from every branch-scoped query while still
sitting in the tables, which is exactly how an "all branches" financial report
can silently understate a total (found 2026-08-01 on the combined AR aging
report, fixed there by making "all branches" mean "no branch filter").

The dependent set is derived from the mapper registry rather than hardcoded:
CLAUDE.md's branch-scoping rule requires every NEW transactional model to carry
`branch_id` from day one, so a literal list would rot silently the moment
someone follows that rule.
"""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.branches.models import Branch
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.integration]


def _login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def _set_branch(client, branch_id):
    """create_app's before_request validates session['selected_branch_id'] on
    every request and bounces to the branch picker when it is unset, so every
    authenticated POST in these tests needs one."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _branch(db_session, code, name=None):
    b = Branch(code=code, name=name or f'Branch {code}', address='x', phone='x',
               email=f'{code.lower()}@test.com', is_active=True)
    db_session.add(b)
    db_session.commit()
    return b


def _invoice_in(db_session, branch, number='SI-DEL-1'):
    c = Customer(code=f'CDEL-{number}', name=f'Cust {number}', is_active=True)
    db_session.add(c)
    db_session.commit()
    inv = SalesInvoice(
        branch_id=branch.id, invoice_number=number,
        invoice_date=date(2026, 1, 1), due_date=date(2026, 1, 31),
        customer_id=c.id, customer_name=c.name, notes='', status='posted',
        amount_paid=Decimal('0.00'), balance=Decimal('100.00'),
        total_amount=Decimal('100.00'), subtotal=Decimal('100.00'),
        vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestBranchDeleteDependentGuard:

    def test_blocked_when_branch_owns_a_transaction(self, client, db_session,
                                                    admin_user, main_branch):
        """The core guard: a branch owning a Sales Invoice must not be deletable."""
        target = _branch(db_session, 'DEL1')
        _invoice_in(db_session, target, 'SI-DEL-1')
        target_id = target.id

        _login(client)

        _set_branch(client, main_branch.id)
        resp = client.post(f'/branches/{target_id}/delete', follow_redirects=True)

        assert resp.status_code == 200
        assert db.session.get(Branch, target_id) is not None, 'branch was deleted anyway'
        body = resp.data.decode()
        assert 'Cannot delete' in body
        assert 'Sales Invoice' in body or 'SalesInvoice' in body

    def test_orphan_is_not_created(self, client, db_session, admin_user, main_branch):
        """The consequence the guard exists to prevent: the invoice must still
        resolve to a real branch after the blocked delete."""
        target = _branch(db_session, 'DEL2')
        inv = _invoice_in(db_session, target, 'SI-DEL-2')
        inv_id, target_id = inv.id, target.id

        _login(client)

        _set_branch(client, main_branch.id)
        client.post(f'/branches/{target_id}/delete', follow_redirects=True)

        kept = db.session.get(SalesInvoice, inv_id)
        assert kept is not None
        assert db.session.get(Branch, kept.branch_id) is not None, 'invoice was orphaned'

    def test_succeeds_when_branch_has_no_dependents(self, client, db_session,
                                                   admin_user, main_branch):
        """Positive half -- the guard must not block a genuinely empty branch."""
        target = _branch(db_session, 'DEL3')
        target_id = target.id

        _login(client)

        _set_branch(client, main_branch.id)
        resp = client.post(f'/branches/{target_id}/delete', follow_redirects=True)

        assert resp.status_code == 200
        assert db.session.get(Branch, target_id) is None, 'empty branch should delete'
        assert 'deleted successfully' in resp.data.decode()

    def test_audit_rows_alone_do_not_block(self, client, db_session, admin_user,
                                           main_branch):
        """AuditLog carries branch_id but is immutable history. Blocking on it
        would make any branch that ever saw activity permanently undeletable."""
        from app.audit.models import AuditLog
        target = _branch(db_session, 'DEL4')
        target_id = target.id
        db_session.add(AuditLog(module='branch', action='create', branch_id=target_id))
        db_session.commit()

        _login(client)

        _set_branch(client, main_branch.id)
        resp = client.post(f'/branches/{target_id}/delete', follow_redirects=True)

        assert db.session.get(Branch, target_id) is None, \
            'audit history must not block deletion'
        assert 'deleted successfully' in resp.data.decode()

    def test_main_branch_still_blocked(self, client, db_session, admin_user,
                                       main_branch):
        """Pre-existing guard must survive."""
        _login(client)
        _set_branch(client, main_branch.id)
        resp = client.post(f'/branches/{main_branch.id}/delete', follow_redirects=True)
        assert db.session.get(Branch, main_branch.id) is not None
        assert 'cannot be deleted' in resp.data.decode()

    def test_branch_with_users_still_blocked(self, client, db_session, admin_user,
                                             main_branch, staff_user):
        """Pre-existing guard must survive, and keep its own clearer message."""
        target = _branch(db_session, 'DEL5')
        staff_user.set_branches([target])
        db_session.commit()
        target_id = target.id

        _login(client)

        _set_branch(client, main_branch.id)
        resp = client.post(f'/branches/{target_id}/delete', follow_redirects=True)

        assert db.session.get(Branch, target_id) is not None
        assert 'assigned user' in resp.data.decode()
