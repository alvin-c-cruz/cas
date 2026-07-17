"""Regression test for the Task 4 review Critical finding: after Task 4 wrapped the Sales
Order form's UOM <select> with Choices.js, `onProductPick`'s auto-fill of a product's default
UOM still set the hidden native <select>.value directly. Choices.js renders its own separate
widget UI and does not reflect changes made directly to the native element it wraps, so the
on-screen UOM picker silently failed to visually update when a user picked a product (the
underlying JS model / submitted value was still correct -- this was a visual-only regression).

Fix: `onProductPick` must update the UOM Choices instance via its own API
(`lineChoices[id].uom.setChoiceByValue(...)`) when one exists for the line, falling back to the
direct `.value` assignment only for the plain-text-input case (units_of_measure module off)."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Enable the optional sales_orders module for all SO tests."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_on_product_pick_updates_uom_via_choices_api(client, db_session, accountant_user, main_branch):
    """onProductPick must drive the UOM Choices widget through setChoiceByValue when a Choices
    instance exists for the line, not just set the hidden native select's .value."""
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    assert 'function onProductPick(' in body

    # Extract the onProductPick function body for a scoped assertion.
    start = body.index('function onProductPick(')
    end = body.index('\n}\n', start)
    fn_body = body[start:end]

    assert 'lineChoices[id] && lineChoices[id].uom' in fn_body, (
        'onProductPick must check for an existing UOM Choices instance on this line before '
        'falling back to direct native-select assignment')
    assert 'lineChoices[id].uom.setChoiceByValue(String(p.default_uom_id))' in fn_body, (
        'when a UOM Choices instance exists, onProductPick must visually sync it via the '
        'Choices.js API (setChoiceByValue), not just mutate the hidden native <select>.value')

    # The plain-text-input fallback (units_of_measure module off) must still be present.
    assert 'uomEl.value = String(p.default_uom_id)' in fn_body, (
        'the direct .value fallback must remain for the plain-text-input (uomMasterOn=false) case')
