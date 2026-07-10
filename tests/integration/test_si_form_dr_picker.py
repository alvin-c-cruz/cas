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
