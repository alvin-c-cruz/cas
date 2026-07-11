"""Phase 3 UI: the AP form's PO/RR billing picker is wholly gated (Zhiyuan render-parity),
and the ap_billing_consolidate company setting exists."""
import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _set_modules(db_session, **states):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k, on in states.items():
        AppSettings.set_setting(f'module_enabled:{k}', '1' if on else '0')
    db_session.commit(); clear_module_config_cache()


def test_ap_form_hides_picker_when_modules_off(client, db_session, accountant_user, main_branch):
    _set_modules(db_session, purchase_orders=False, receiving_reports=False)
    _login(client, accountant_user, main_branch)
    body = client.get('/accounts-payable/create').data
    assert b'poBillingSection' not in body       # picker card absent
    assert b'source_po_ids' not in body          # hidden fields absent
    assert b'source_rr_ids' not in body
    assert b'ap_po_billing.js' not in body       # gated script not loaded


def test_ap_form_shows_picker_when_module_on(client, db_session, accountant_user, main_branch):
    _set_modules(db_session, purchase_orders=True, receiving_reports=False)
    _login(client, accountant_user, main_branch)
    body = client.get('/accounts-payable/create').data
    assert b'poBillingSection' in body
    assert b'source_po_ids' in body
    assert b'ap_po_billing.js' in body


def test_ap_form_shows_picker_when_only_rr_on(client, db_session, accountant_user, main_branch):
    _set_modules(db_session, purchase_orders=False, receiving_reports=True)
    _login(client, accountant_user, main_branch)
    assert b'poBillingSection' in client.get('/accounts-payable/create').data


def test_ap_billing_consolidate_setting_roundtrips(db_session):
    from app.settings import AppSettings
    from app.purchase_billing import ap_billing_consolidate
    assert ap_billing_consolidate() is False              # default off
    AppSettings.set_setting('ap_billing_consolidate', '1'); db_session.commit()
    assert ap_billing_consolidate() is True


def test_company_settings_form_has_ap_billing_field(db_session):
    from app.company_settings.forms import CompanySettingsForm
    assert hasattr(CompanySettingsForm, 'ap_billing_consolidate')
