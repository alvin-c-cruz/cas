"""The SI create form exposes the DR-billing picker + a single source_dr_ids field."""
import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True; s['selected_branch_id'] = branch.id


def test_si_create_form_has_dr_billing_picker(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, main_branch)
    resp = client.get('/sales-invoices/create')
    assert resp.status_code == 200
    assert b'id="drBillingSection"' in resp.data
    # BUG-DR-DUP-LINES class: the hidden field must appear exactly once.
    assert resp.data.count(b'name="source_dr_ids"') == 1
    assert b'js/si_dr_billing.js' in resp.data


def _set_modules(db_session, **states):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k, on in states.items():
        AppSettings.set_setting(f'module_enabled:{k}', '1' if on else '0')
    db_session.commit(); clear_module_config_cache()


def test_si_form_hides_dr_picker_when_module_off(client, db_session, accountant_user, main_branch):
    _set_modules(db_session, delivery_receipts=False)
    _login(client, accountant_user, main_branch)
    body = client.get('/sales-invoices/create').data
    assert b'drBillingSection' not in body       # picker card absent
    assert b'source_dr_ids' not in body          # hidden field absent
    assert b'js/si_dr_billing.js' not in body    # gated script not loaded


def test_si_form_shows_dr_picker_when_module_on(client, db_session, accountant_user, main_branch):
    _set_modules(db_session, delivery_receipts=True)
    _login(client, accountant_user, main_branch)
    body = client.get('/sales-invoices/create').data
    assert b'drBillingSection' in body
    assert b'source_dr_ids' in body
    assert b'js/si_dr_billing.js' in body
