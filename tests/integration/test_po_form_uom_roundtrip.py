"""The PO form must carry a line's unit of measure back to the server.

`_assign_po_line_fields` has ALWAYS read `uom_id` and `uom_text` off each
submitted line (views.py) -- but the form never sent either. So every draft edit
and every amendment set `unit_of_measure_id = None` and `uom_text = None` on
every line, silently. It bites hardest on a PO converted from an approved
requisition: `purchase_requests.convert()` copies the requisition's UoM onto the
new PO's lines, and merely opening that PO and saving it erased them.

Server-side POST tests cannot see this class of bug -- the test client supplies
`uom_id` itself, so the payload is well-formed no matter what the template emits.
These tests therefore run the form's OWN JavaScript (the same node harness the
amend line-identity tests use) and inspect what a real browser would post.
"""
from datetime import date

import pytest

from tests.integration import _line_identity_js as _js

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration]

_MARKER = 'poItemIdOf'
_FORM_ID = 'poForm'


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders and units_of_measure are optional modules; without them
    enforce_module_access 404s the route and there is no UoM picker to test."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'units_of_measure'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def uom(db_session):
    from app.units_of_measure.models import UnitOfMeasure
    u = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def vendor(db_session):
    """vendor_id is DataRequired on the PO form -- a POST without it fails
    validation and re-renders 200, writing nothing."""
    from app.vendors.models import Vendor
    v = Vendor(code='V001', name='THAI SHIN-I', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture
def draft_po(db_session, admin_user, main_branch, uom):
    po = PurchaseOrder(po_number='UOM-1', order_date=date(2026, 8, 14),
                       branch_id=main_branch.id, status='draft',
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Ginaca spare', quantity=3, unit_price=100,
        amount=300, unit_of_measure_id=uom.id))
    db_session.add(po)
    db_session.commit()
    return po


def _edit_html(client, po):
    resp = client.get(f'/purchase-orders/{po.id}/edit')
    assert resp.status_code == 200, f'edit GET -> {resp.status_code}'
    return resp.data.decode()


class TestTheFormEmitsAUomColumn:

    def test_the_line_grid_has_a_uom_header(self, client, admin_user, main_branch, draft_po):
        _login(client, admin_user, main_branch)
        assert 'UOM' in _edit_html(client, draft_po)

    def test_each_row_carries_a_uom_picker(self, client, admin_user, main_branch, draft_po):
        """The class the serialiser reads. Renaming it on one side only is the
        failure this pins."""
        _login(client, admin_user, main_branch)
        assert 'po-uom' in _edit_html(client, draft_po)


class TestTheSubmittedPayloadCarriesTheUom:
    """Executes the template's real submit handler and reads the JSON it writes."""

    def test_posted_line_includes_a_uom_id_key(self, tmp_path, client, admin_user,
                                               main_branch, draft_po):
        _login(client, admin_user, main_branch)
        posted = _js.serialise_lines(tmp_path, _edit_html(client, draft_po),
                                     marker=_MARKER, form_id=_FORM_ID)
        assert posted, 'the submit handler posted no lines at all'
        assert 'uom_id' in posted[0], (
            'the serialiser omits uom_id -- _assign_po_line_fields will read None '
            'and wipe unit_of_measure_id on every line it touches')

    def test_posted_line_includes_a_uom_text_key(self, tmp_path, client, admin_user,
                                                 main_branch, draft_po):
        """A legacy line may carry free text with no FK; the form has to hand it
        back or saving erases the unit."""
        _login(client, admin_user, main_branch)
        posted = _js.serialise_lines(tmp_path, _edit_html(client, draft_po),
                                     marker=_MARKER, form_id=_FORM_ID)
        assert 'uom_text' in posted[0]

    def test_control_the_other_line_fields_still_post(self, tmp_path, client, admin_user,
                                                      main_branch, draft_po):
        """Control: adding the UoM column must not drop any field that already
        worked. A serialiser that posted ONLY uom_id would pass the two tests
        above and destroy the document."""
        _login(client, admin_user, main_branch)
        posted = _js.serialise_lines(tmp_path, _edit_html(client, draft_po),
                                     marker=_MARKER, form_id=_FORM_ID)
        for key in ('po_item_id', 'product_id', 'description', 'quantity',
                    'unit_price', 'amount', 'vat_category', 'vat_rate'):
            assert key in posted[0], f'{key} no longer posted'


class TestTheServerKeepsTheUom:
    """The other half: the server stores what the form now sends. Together with
    the harness tests above this closes the loop the bug lived in -- form emits
    it, route persists it.

    Every test here asserts a WITNESS field it also changed, not just the UoM.
    Without one these are vacuous: `vendor_id` is DataRequired, so a POST that
    omits it fails validation and re-renders 200, leaving the ORIGINAL line --
    which already carries the UoM -- in place. The first draft of this class did
    exactly that and passed while writing nothing.
    """

    def _post(self, client, po, lines, vendor):
        import json as _json
        return client.post(f'/purchase-orders/{po.id}/edit', data={
            'po_number': po.po_number, 'order_date': '2026-08-14',
            'vendor_id': vendor.id,
            'vat_treatment': 'inclusive', 'payment_terms': 'Net 30',
            'row_version': po.row_version,
            'line_items': _json.dumps(lines),
        }, follow_redirects=True)

    def test_editing_a_draft_preserves_the_unit(self, client, db_session, admin_user,
                                                main_branch, draft_po, uom, vendor):
        _login(client, admin_user, main_branch)
        resp = self._post(client, draft_po, [{
            'po_item_id': draft_po.line_items[0].id,
            'description': 'WITNESS-KEPT', 'quantity': '3',
            'unit_price': '100', 'amount': '300',
            'uom_id': uom.id, 'uom_text': None,
        }], vendor)
        assert resp.status_code == 200

        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.line_items[0].description == 'WITNESS-KEPT', (
            'the edit never applied -- this test would pass vacuously on the '
            'untouched original line')
        assert po.line_items[0].unit_of_measure_id == uom.id, (
            'the unit was dropped on a plain draft edit')

    def test_a_line_with_no_uom_is_still_accepted(self, client, db_session, admin_user,
                                                  main_branch, draft_po, vendor):
        """Control: UoM is optional. Sending none must not become an error, and
        must actually clear it rather than leaving the old value behind."""
        _login(client, admin_user, main_branch)
        resp = self._post(client, draft_po, [{
            'po_item_id': draft_po.line_items[0].id,
            'description': 'WITNESS-BLANK', 'amount': '500',
            'uom_id': None, 'uom_text': None,
        }], vendor)
        assert resp.status_code == 200

        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.line_items[0].description == 'WITNESS-BLANK'
        assert po.line_items[0].unit_of_measure_id is None

    def test_free_text_uom_survives_when_no_fk_is_chosen(self, client, db_session,
                                                         admin_user, main_branch,
                                                         draft_po, vendor):
        """The legacy path the row's dataset carry-over exists for."""
        _login(client, admin_user, main_branch)
        resp = self._post(client, draft_po, [{
            'po_item_id': draft_po.line_items[0].id,
            'description': 'WITNESS-TEXT', 'amount': '75',
            'uom_id': None, 'uom_text': 'DRUM',
        }], vendor)
        assert resp.status_code == 200

        po = db.session.get(PurchaseOrder, draft_po.id)
        assert po.line_items[0].description == 'WITNESS-TEXT'
        assert po.line_items[0].uom_text == 'DRUM'
