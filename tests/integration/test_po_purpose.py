"""
A Purchase Order carries a PURPOSE -- what the order is for ("FOR PRODUCTION
USE", "FOR THE REPAIR OF INNOVA"), printed once above the line items.

Why a HEADER field and not a per-line one with grouping: PhilGen's legacy system
stored the purpose on every PO line (`purchase_order_detail.side_note`) and its
print grouped lines by it. Measured against the real legacy data on 2026-08-19:
across 168 POs -- 118 of them multi-line -- EVERY one carries exactly one
distinct purpose. The grouping machinery has never produced a second group. So
the purpose is a header attribute that was stored redundantly per line, and this
models it as what it is. (Owner decision, same date.)

The print consequence follows: one caption above the items, never a column and
never repeated per line.
"""
import json
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is an OPTIONAL module -- without this every route 404s
    and each assertion below fails for a reason unrelated to the purpose."""
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{key}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()

PURPOSE = 'FOR PRODUCTION USE'


def test_purpose_defaults_to_none_on_an_existing_style_order(db_session, main_branch):
    """Nothing is guessed: an order created without a purpose simply has none."""
    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-0001', vendor_name='Acme')
    db.session.add(po)
    db.session.commit()

    assert po.purpose is None


def test_purpose_round_trips_through_the_database(db_session, main_branch):
    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-0002',
                       vendor_name='Acme', purpose=PURPOSE)
    db.session.add(po)
    db.session.commit()
    db.session.expire_all()

    assert db.session.get(PurchaseOrder, po.id).purpose == PURPOSE


def test_purpose_is_carried_in_the_amendment_snapshot(db_session, main_branch):
    """A post-approval amendment must preserve WHAT the order was for.

    Rev 0 records the header as approved; a purpose missing from
    SNAPSHOT_HEADER_FIELDS would silently vanish from the amendment history.
    """
    assert 'purpose' in PurchaseOrder.SNAPSHOT_HEADER_FIELDS

    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-0003',
                       vendor_name='Acme', purpose=PURPOSE)
    db.session.add(po)
    db.session.commit()

    snapshot = po.build_snapshot()
    assert snapshot['header']['purpose'] == PURPOSE


# --- form + surfaces -------------------------------------------------------

def _login(client, user, branch):
    """admin is full-access, so the instance flag is enough here -- but the
    branch must be assigned and selected or before_request bounces to the picker."""
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po_form_data(vendor, po_number, **extra):
    data = {'po_number': po_number, 'order_date': '2026-08-19',
            'vendor_id': str(vendor.id), 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'notes': '',
            'line_items': json.dumps([{'description': 'Salt', 'quantity': '1',
                                       'unit_price': '10', 'amount': '10'}])}
    data.update(extra)
    return data


def _create(client, vendor, po_number, **extra):
    return client.post('/purchase-orders/create',
                       data=_po_form_data(vendor, po_number, **extra),
                       follow_redirects=True)


def _edit(client, po, vendor, **extra):
    # PurchaseOrderForm carries RowVersionFormMixin: without the current
    # row_version the optimistic-lock guard rejects the save as a conflict and
    # the edit silently does nothing.
    data = _po_form_data(vendor, po.po_number, **extra)
    data['row_version'] = str(po.row_version or 0)
    return client.post(f'/purchase-orders/{po.id}/edit', data=data,
                       follow_redirects=True)


def test_create_form_offers_a_purpose_field(client, db_session, main_branch, admin_user):
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-orders/create')

    assert resp.status_code == 200
    assert b'name="purpose"' in resp.data, \
        'the PO form does not render a purpose input, so it can never be filled in'


def test_purpose_survives_a_create_then_edit_round_trip(client, db_session, main_branch,
                                                        vl_vendor, admin_user):
    """Create with a purpose, reopen, change it, save -- the new value persists.

    Both halves matter and each hides a different bug. Rendering-only would miss
    an edit path that never assigns the field; saving-only would miss an edit
    form that renders the box blank, which silently ERASES the purpose the next
    time anyone saves the order.
    """
    _login(client, admin_user, main_branch)
    _create(client, vl_vendor, 'PP-0100', purpose=PURPOSE)
    po = PurchaseOrder.query.filter_by(po_number='PP-0100').first()
    assert po is not None and po.purpose == PURPOSE, 'create did not save the purpose'

    resp = client.get(f'/purchase-orders/{po.id}/edit')
    assert resp.status_code == 200
    assert PURPOSE.encode() in resp.data,         'the edit form renders an empty purpose, so the next save would erase it'

    _edit(client, po, vl_vendor, purpose='FOR BOILER USE')
    db.session.expire_all()
    assert db.session.get(PurchaseOrder, po.id).purpose == 'FOR BOILER USE'


def test_print_shows_the_purpose_once_above_the_lines(client, db_session, main_branch,
                                                      admin_user):
    """Once, as a caption -- never a per-line column (the whole point of the
    header-field decision)."""
    # approved, not draft: po_print_access is default-deny for drafts, so a
    # draft here would 302 and the assertions would never run.
    #
    # TWO line items, and that is load-bearing: with no lines the row loop never
    # runs, so a purpose rendered PER LINE would still appear exactly once and
    # this test would pass while asserting nothing (mutation-caught).
    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-0101',
                       vendor_name='Acme', purpose=PURPOSE, status='approved')
    for n, what in ((1, 'Chlorine'), (2, 'Foamklin')):
        po.line_items.append(PurchaseOrderItem(
            line_number=n, description=what, quantity=Decimal('1'),
            unit_price=Decimal('10'), amount=Decimal('10')))
    db.session.add(po)
    db.session.commit()
    assert len(po.line_items) == 2, 'the per-line mutation cannot be detected without lines'

    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-orders/{po.id}/print')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert body.count(PURPOSE) == 1, (
        f'expected the purpose exactly once on the print, found {body.count(PURPOSE)} '
        '-- more than one means it is being repeated per line'
    )
    assert body.index(PURPOSE) < body.index('<tbody'), \
        'the purpose caption must sit ABOVE the line-item rows'


def test_print_omits_the_caption_entirely_when_there_is_no_purpose(client, db_session,
                                                                   main_branch, admin_user):
    """CONTROL: no purpose means no label, no empty caption, no stray colon.

    Every PO that exists today has purpose=None, so this is the common case, not
    the edge case.
    """
    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-0102',
                       vendor_name='Acme', status='approved')
    db.session.add(po)
    db.session.commit()

    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-orders/{po.id}/print')
    assert resp.status_code == 200, 'the control never reached the print page'
    body = resp.data.decode()

    assert 'po-purpose' not in body, \
        'the purpose caption element is rendered even though the order has no purpose'
    assert 'None' not in body, 'a None purpose leaked onto the printed form'


def test_the_preprinted_overlay_carries_the_purpose(client, db_session, main_branch,
                                                    admin_user):
    """PhilGen prints on its own stationery, so the OVERLAY is the surface that
    matters to them -- the standard print.html is not what they hand a supplier.

    A field declared in the layout but never given a value renders as an empty
    box in the designer and silently prints nothing.
    """
    AppSettings.set_setting('po_print_form', 'preprinted')
    db.session.commit()

    po = PurchaseOrder(branch_id=main_branch.id, po_number='PP-0103',
                       vendor_name='Acme', purpose=PURPOSE, status='approved')
    db.session.add(po)
    db.session.commit()

    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-orders/{po.id}/print')

    assert resp.status_code == 200
    assert PURPOSE in resp.data.decode(), \
        'the pre-printed overlay declares a purpose field but never feeds it a value'


def test_the_preprinted_layout_declares_purpose_as_a_positionable_field(client, db_session,
                                                                       main_branch, admin_user):
    """Declared but unpositionable is useless: the client must be able to drag it
    onto their own stationery like every other field."""
    from app.purchase_orders import preprinted_layout as pl

    assert 'purpose' in pl.FIELD_KEYS
    assert pl.FIELD_LABELS['purpose'] == 'Purpose'
    assert 'purpose' in pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'], \
        'no default box, so it lands at 0,0 on every client that has not customised'
