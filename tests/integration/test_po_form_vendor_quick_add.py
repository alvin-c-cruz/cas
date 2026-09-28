"""The purchase order form offers "+ Add Vendor" on its vendor picker.

Owner, 2026-09-28, from /purchase-orders/create: "the vendor field is missing
the Add Vendor feature". The AP and CDV forms carry it -- the shared
vendor-quick-add.js pins an add-action on the picker and opens the inline
modal, which embeds the FULL vendor form (vendors/_form_fields.html), so a
vendor created mid-order is a complete vendor, not a stub. The PO form had
been left out on the belief that a quick-add could not carry enough fields.

Asserted on GET renders, on applied attributes, never on a bare class or
function name that inline JS/CSS text would leak anyway.
"""
import pytest

from app import db
from app.settings import AppSettings
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an OPTIONAL module -- without this every route 404s."""
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{key}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _assert_quick_add_wired(html):
    # The modal partial is on the page (its overlay id is what the JS looks up)...
    assert 'id="vendorQuickAddOverlay"' in html, 'the Add Vendor modal is not on the page'
    # ...its form posts to the vendors create endpoint...
    assert 'id="vendorQuickAddForm"' in html and 'action="/vendors/create"' in html
    # ...the shared scripts that drive it are loaded...
    assert 'vendor-quick-add.js' in html, 'vendor-quick-add.js is not loaded'
    assert 'vendor-form-widgets.js' in html, 'the modal VAT/WT pickers need vendor-form-widgets.js'
    # ...and the vendor picker is built through it, not the bare search-select.
    assert 'initVendorQuickAdd({ selectEl: vSel' in html, \
        'the vendor picker is not initialised through initVendorQuickAdd'


def test_create_form_offers_add_vendor(client, db_session, main_branch, admin_user):
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-orders/create')
    assert resp.status_code == 200
    _assert_quick_add_wired(resp.data.decode())


def test_edit_form_offers_add_vendor(client, db_session, main_branch, admin_user):
    """Every render of form.html carries it, not just the create GET."""
    from app.purchase_orders.models import PurchaseOrder
    vendor = Vendor(code='QAPO1', name='Acme', is_active=True)
    db.session.add(vendor); db.session.commit()
    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-QA01',
                       vendor_id=vendor.id, vendor_name=vendor.name)
    db.session.add(po); db.session.commit()

    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-orders/{po.id}/edit')
    assert resp.status_code == 200
    _assert_quick_add_wired(resp.data.decode())


def test_modal_carries_the_full_vendor_form(client, db_session, main_branch, admin_user):
    """The reason the PO form was left out was 'not enough fields': the modal
    embeds the real vendor form, so the fields a vendor needs are all there."""
    _login(client, admin_user, main_branch)
    html = client.get('/purchase-orders/create').data.decode()
    modal = html[html.index('id="vendorQuickAddOverlay"'):]
    modal = modal[:modal.index('</form>')]
    for field in ('name="code"', 'name="name"', 'name="tin"', 'name="address"',
                  'name="payment_terms"', 'name="default_vat_category"'):
        assert field in modal, 'vendor field %s missing from the quick-add modal' % field
