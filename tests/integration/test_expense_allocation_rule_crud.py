"""Integration tests for the Expense Allocation Rule CRUD blueprint (Phase 3b)."""
import pytest
from app import db
from app.accounts.models import Account
from app.expense_allocation_rules.models import ExpenseAllocationRule
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _account(code='52201', name='Office Supplies'):
    a = Account(code=code, name=name, account_type='Administrative Expense',
                normal_balance='debit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


class TestExpenseAllocationRuleCRUD:
    def test_list_renders(self, client, admin_user, main_branch, login_user):
        login_user(client, 'admin', 'admin123')
        resp = client.get('/expense-allocation-rules')
        assert resp.status_code == 200

    def test_create(self, client, admin_user, main_branch, login_user):
        login_user(client, 'admin', 'admin123')
        a = _account()
        resp = client.post('/expense-allocation-rules/create',
                           data={'account_id': str(a.id), 'basis': 'revenue_share'},
                           follow_redirects=True)
        assert resp.status_code == 200
        rule = ExpenseAllocationRule.query.filter_by(account_id=a.id).first()
        assert rule is not None
        assert rule.basis == 'revenue_share'

    def test_create_duplicate_account_rejected(self, client, admin_user, main_branch, login_user):
        login_user(client, 'admin', 'admin123')
        a = _account()
        db.session.add(ExpenseAllocationRule(account_id=a.id, basis='equal'))
        db.session.commit()
        resp = client.post('/expense-allocation-rules/create',
                           data={'account_id': str(a.id), 'basis': 'none'})
        assert resp.status_code == 200  # re-renders the form with an error, no redirect
        assert ExpenseAllocationRule.query.filter_by(account_id=a.id).count() == 1

    def test_edit(self, client, admin_user, main_branch, login_user):
        login_user(client, 'admin', 'admin123')
        a = _account()
        r = ExpenseAllocationRule(account_id=a.id, basis='equal')
        db.session.add(r)
        db.session.commit()
        resp = client.post(f'/expense-allocation-rules/{r.id}/edit',
                           data={'account_id': str(a.id), 'basis': 'gross_profit_share'},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(ExpenseAllocationRule, r.id).basis == 'gross_profit_share'

    def test_audit_logged_on_create(self, client, admin_user, main_branch, login_user):
        login_user(client, 'admin', 'admin123')
        a = _account()
        client.post('/expense-allocation-rules/create',
                    data={'account_id': str(a.id), 'basis': 'units_sold'})
        entry = AuditLog.query.filter_by(module='expense_allocation_rules', action='create').first()
        assert entry is not None
