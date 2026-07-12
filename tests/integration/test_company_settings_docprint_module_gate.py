"""Documents & Print tab: si_dr_billing_consolidate, ap_billing_consolidate, and
so_print_form are each tied to an optional module (delivery_receipts;
purchase_orders/receiving_reports; sales_orders). When the tied module is
disabled, the control has zero effect -- BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS.

These are render-assertion GET tests (not POST-contract tests) per memory
render-assertions-miss-order-and-attributes / csrf-only-render-drops-hidden-fields:
a POST test can't catch a template that renders a field unconditionally.
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.settings]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _set_modules(db_session, **states):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k, on in states.items():
        AppSettings.set_setting(f'module_enabled:{k}', '1' if on else '0')
    db_session.commit()
    clear_module_config_cache()


class TestSiDrBillingConsolidateGate:
    def test_hidden_when_delivery_receipts_disabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, delivery_receipts=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="si_dr_billing_consolidate"' not in body
        assert b'Enable the Delivery Receipts module' in body

    def test_shown_when_delivery_receipts_enabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, delivery_receipts=True)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="si_dr_billing_consolidate"' in body


class TestApBillingConsolidateGate:
    def test_hidden_when_po_and_rr_disabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, purchase_orders=False, receiving_reports=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="ap_billing_consolidate"' not in body
        assert b'Enable the Purchase Orders' in body or b'Enable Purchase Orders' in body

    def test_shown_when_only_purchase_orders_enabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, purchase_orders=True, receiving_reports=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="ap_billing_consolidate"' in body

    def test_shown_when_only_receiving_reports_enabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, purchase_orders=False, receiving_reports=True)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="ap_billing_consolidate"' in body


class TestSoPrintFormGate:
    def test_hidden_when_sales_orders_disabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, sales_orders=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="so_print_form"' not in body
        assert b'Enable the Sales Orders module' in body

    def test_shown_when_sales_orders_enabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, sales_orders=True)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="so_print_form"' in body
