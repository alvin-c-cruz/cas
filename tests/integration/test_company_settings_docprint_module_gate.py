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


class TestManufacturingModeGate:
    """BUG-MANUFACTURING-MODE-GATED-BEHIND-SALES-ORDERS.

    The two manufacturing mode toggles were rendered inside
    `{% if module_states.sales_orders %}`, a module with no relationship to
    manufacturing. Since "at least one mode must be on before a Bill of Materials
    can be created", a manufacturing-only company that enabled Bill of Materials /
    Work Centers / Work Orders but not Sales Orders could not switch manufacturing
    on AT ALL -- the whole shipped R-07 arc was unreachable.

    Invisible to every other test because they set the mode directly via
    `AppSettings.set_setting('manufacturing_discrete_enabled', '1')` and never
    render this template. Found by the R-07 D5 pre-merge browser pass, 2026-08-02.
    """

    def test_shown_when_bom_enabled_even_though_sales_orders_disabled(
            self, client, db_session, admin_user, main_branch):
        """The bug, reproduced: manufacturing on, Sales Orders off."""
        _set_modules(db_session, bill_of_materials=True, sales_orders=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="manufacturing_discrete_enabled"' in body
        assert b'name="manufacturing_process_enabled"' in body

    def test_shown_when_both_enabled(self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, bill_of_materials=True, sales_orders=True)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="manufacturing_discrete_enabled"' in body
        assert b'name="manufacturing_process_enabled"' in body

    def test_hidden_when_bom_disabled(self, client, db_session, admin_user, main_branch):
        """Still gated -- the fix must re-home the toggles, not un-gate them."""
        _set_modules(db_session, bill_of_materials=False, sales_orders=True)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="manufacturing_discrete_enabled"' not in body
        assert b'name="manufacturing_process_enabled"' not in body

    def test_job_order_slips_stays_gated_on_sales_orders(
            self, client, db_session, admin_user, main_branch):
        """Guards against over-correcting: job_order_slips_show_drafts shares the
        block being split and DOES belong to sales_orders, so it must stay hidden
        when Sales Orders is off even while manufacturing is on."""
        _set_modules(db_session, bill_of_materials=True, sales_orders=False)
        _login(client, admin_user, main_branch)
        body = client.get('/settings').data
        assert b'name="job_order_slips_show_drafts"' not in body
