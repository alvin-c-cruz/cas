"""Integration tests for the Expense Allocation Rule CRUD blueprint (Phase 3b)."""
import pytest
from app import db
from app.accounts.models import Account
from app.expense_allocation_rules.models import ExpenseAllocationRule
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


@pytest.fixture
def expense_allocation_rules_module_enabled(db_session):
    """Enable the optional expense_allocation_rules module for the duration of the test.

    default_enabled=False (optional); mirrors sales_by_product_line_module_enabled /
    products_module_enabled -- the before_request module gate 404s otherwise.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:expense_allocation_rules', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _account(code='52201', name='Office Supplies'):
    a = Account(code=code, name=name, account_type='Administrative Expense',
                normal_balance='debit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


class TestExpenseAllocationRuleCRUD:
    def test_list_renders(self, client, admin_user, main_branch, login_user,
                          expense_allocation_rules_module_enabled):
        login_user(client, 'admin', 'admin123')
        resp = client.get('/expense-allocation-rules')
        assert resp.status_code == 200

    def test_create(self, client, admin_user, main_branch, login_user,
                    expense_allocation_rules_module_enabled):
        login_user(client, 'admin', 'admin123')
        a = _account()
        resp = client.post('/expense-allocation-rules/create',
                           data={'account_id': str(a.id), 'basis': 'revenue_share'},
                           follow_redirects=True)
        assert resp.status_code == 200
        rule = ExpenseAllocationRule.query.filter_by(account_id=a.id).first()
        assert rule is not None
        assert rule.basis == 'revenue_share'

    def test_create_duplicate_account_rejected(self, client, admin_user, main_branch, login_user,
                                               expense_allocation_rules_module_enabled):
        login_user(client, 'admin', 'admin123')
        a = _account()
        db.session.add(ExpenseAllocationRule(account_id=a.id, basis='equal'))
        db.session.commit()
        resp = client.post('/expense-allocation-rules/create',
                           data={'account_id': str(a.id), 'basis': 'none'})
        assert resp.status_code == 200  # re-renders the form with an error, no redirect
        assert ExpenseAllocationRule.query.filter_by(account_id=a.id).count() == 1

    def test_edit(self, client, admin_user, main_branch, login_user,
                  expense_allocation_rules_module_enabled):
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

    def test_audit_logged_on_create(self, client, admin_user, main_branch, login_user,
                                    expense_allocation_rules_module_enabled):
        login_user(client, 'admin', 'admin123')
        a = _account()
        client.post('/expense-allocation-rules/create',
                    data={'account_id': str(a.id), 'basis': 'units_sold'})
        entry = AuditLog.query.filter_by(module='expense_allocation_rules', action='create').first()
        assert entry is not None

    def test_404_when_module_disabled(self, client, admin_user, main_branch, login_user):
        """Do NOT use the module-enabled fixture; explicitly disable instead so the
        before_request module gate 404s the route (mirrors
        test_sales_by_product_line_views.py::test_404_when_module_disabled)."""
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        AppSettings.set_setting('module_enabled:expense_allocation_rules', '0')
        db.session.commit()
        clear_module_config_cache()
        login_user(client, 'admin', 'admin123')
        resp = client.get('/expense-allocation-rules')
        assert resp.status_code == 404
        clear_module_config_cache()
