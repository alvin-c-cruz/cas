"""source_pr_item_id must survive the round-trip, and the ceiling must hold.

The serialiser test uses the node line-identity harness, the only thing that
executes the form's real JS. A POST-based test cannot see a dropped render --
the test client supplies the field itself.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from tests.integration import _line_identity_js as _js

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]

_MARKER = 'poItemIdOf'
_FORM_ID = 'poForm'


@pytest.fixture(autouse=True)
def modules_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'purchase_orders', 'units_of_measure'):
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
def vendor(db_session):
    v = Vendor(code='V001', name='THAI SHIN-I', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture
def pr_item(db_session, main_branch, admin_user):
    p = PurchaseRequest(pr_number='SRC-1', request_date=date(2026, 8, 15),
                        branch_id=main_branch.id, status='approved',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(line_number=1, description='Carbide', quantity=20))
    db_session.add(p)
    db_session.commit()
    return p.line_items[0]


def _post_po(client, vendor, lines, number='SRC-PO-1'):
    return client.post('/purchase-orders/create', data={
        'po_number': number, 'order_date': '2026-08-15', 'vendor_id': vendor.id,
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30',
        'line_items': json.dumps(lines),
    }, follow_redirects=True)


class TestItPersists:

    def test_a_pulled_line_stores_its_source(self, client, db_session, admin_user,
                                             main_branch, vendor, pr_item):
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': '8', 'unit_price': '10',
            'amount': '80', 'source_pr_item_id': pr_item.id,
        }])
        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-1').first()
        assert po is not None, 'the purchase order was not created'
        assert po.line_items[0].source_pr_item_id == pr_item.id

    def test_a_hand_typed_line_stores_none(self, client, db_session, admin_user,
                                           main_branch, vendor):
        """Control: nothing changes for a PO that never touches a requisition."""
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'Typed', 'quantity': '3', 'unit_price': '5', 'amount': '15',
        }], number='SRC-PO-2')
        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-2').first()
        assert po.line_items[0].source_pr_item_id is None


class TestTheCeilingHolds:

    def test_over_ordering_is_refused(self, client, db_session, admin_user,
                                      main_branch, vendor, pr_item):
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': '21', 'unit_price': '10',
            'amount': '210', 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-OVER')
        assert PurchaseOrder.query.filter_by(po_number='SRC-PO-OVER').first() is None

    def test_editing_a_draft_unchanged_succeeds(self, client, db_session, admin_user,
                                                main_branch, vendor, pr_item):
        """Self-collision: without exclude_po_id the PO's own line counts
        against itself and an unchanged save fails."""
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': '20', 'unit_price': '10',
            'amount': '200', 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-EDIT')
        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-EDIT').first()

        resp = client.post(f'/purchase-orders/{po.id}/edit', data={
            'po_number': 'SRC-PO-EDIT', 'order_date': '2026-08-15',
            'vendor_id': vendor.id, 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'row_version': po.row_version,
            'line_items': json.dumps([{
                'po_item_id': po.line_items[0].id, 'description': 'WITNESS-EDIT',
                'quantity': '20', 'unit_price': '10', 'amount': '200',
                'source_pr_item_id': pr_item.id,
            }]),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(PurchaseOrder, po.id).line_items[0].description == 'WITNESS-EDIT'

    def test_another_branch_line_is_refused(self, client, db_session, admin_user,
                                            main_branch, branch_manila, vendor):
        """The picker filters by branch; a crafted POST must not bypass it."""
        other = PurchaseRequest(pr_number='SRC-OTHER', request_date=date(2026, 8, 15),
                                branch_id=branch_manila.id, status='approved',
                                created_by_id=admin_user.id)
        other.line_items.append(PurchaseRequestItem(line_number=1, description='X', quantity=5))
        db_session.add(other)
        db_session.commit()
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'X', 'quantity': '5', 'unit_price': '1', 'amount': '5',
            'source_pr_item_id': other.line_items[0].id,
        }], number='SRC-PO-XBRANCH')
        assert PurchaseOrder.query.filter_by(po_number='SRC-PO-XBRANCH').first() is None


class TestStatusIsKeptCurrent:

    def test_saving_a_po_moves_the_requisition(self, client, db_session, admin_user,
                                               main_branch, vendor, pr_item):
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': '8', 'unit_price': '10',
            'amount': '80', 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-ST')
        assert db.session.get(PurchaseRequest, pr_item.purchase_request_id).status \
            == 'partially_converted'

    def test_cancelling_the_po_reopens_it(self, client, db_session, admin_user,
                                          main_branch, vendor, pr_item):
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': '20', 'unit_price': '10',
            'amount': '200', 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-CANCEL')
        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-CANCEL').first()
        client.post(f'/purchase-orders/{po.id}/cancel', data={'cancel_reason': 'no longer needed'},
                    follow_redirects=True)
        assert db.session.get(PurchaseRequest, pr_item.purchase_request_id).status == 'approved'


class TestTheSerialiserEmitsIt:

    def test_the_posted_line_carries_source_pr_item_id(self, tmp_path, client,
                                                       admin_user, main_branch,
                                                       vendor, pr_item):
        """Runs the form's real JS. Without this the draft-edit path silently
        orphans every pulled line and reopens the requisition."""
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-orders/create').data.decode()
        posted = _js.serialise_lines(tmp_path, html, marker=_MARKER, form_id=_FORM_ID)
        assert posted, 'the submit handler posted no lines'
        assert 'source_pr_item_id' in posted[0]


class TestAmendingAPulledLine:
    """The amend path updates lines IN PLACE -- it does not delete-and-rebuild
    the way edit() does. So its own lines are still in the database when the
    ceiling is checked, and without exclude_po_id the order is measured against
    itself: amending a PO that took a requisition line in full is refused with
    "only 0 ... remain unordered".

    This is also where exclude_po_id is load-bearing. On the EDIT path the
    wholesale DELETE runs first, so dropping exclude_po_id there changes
    nothing -- a mutation aimed at edit() survives and proves nothing.
    """

    def _approved_pulled_po(self, client, db_session, vendor, pr_item, qty='20'):
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': qty, 'unit_price': '10',
            'amount': str(int(qty) * 10), 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-AMD')
        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-AMD').first()
        po.status = 'approved'
        db_session.commit()
        return po

    def _amend(self, client, po, line, unit_price='12'):
        return client.post(f'/purchase-orders/{po.id}/amend', data={
            'po_number': po.po_number, 'order_date': '2026-08-15',
            'vendor_id': po.vendor_id, 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'notes': '',
            'amend_reason': 'vendor corrected the unit price',
            'row_version': po.row_version,
            'line_items': json.dumps([{
                'po_item_id': line.id, 'description': 'Carbide',
                'quantity': '20', 'unit_price': unit_price,
                'amount': str(20 * int(unit_price)),
                'source_pr_item_id': line.source_pr_item_id,
            }]),
        }, follow_redirects=True)

    def test_amending_unchanged_quantities_is_not_refused_by_its_own_lines(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        _login(client, admin_user, main_branch)
        po = self._approved_pulled_po(client, db_session, vendor, pr_item)
        line = po.line_items[0]
        resp = self._amend(client, po, line)
        assert b'remain unordered' not in resp.data, (
            'the order was measured against its own lines')
        assert db.session.get(PurchaseOrderItem, line.id).unit_price == Decimal('12')

    def test_the_amended_line_keeps_its_requisition_link(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        _login(client, admin_user, main_branch)
        po = self._approved_pulled_po(client, db_session, vendor, pr_item)
        line = po.line_items[0]
        self._amend(client, po, line)
        assert db.session.get(PurchaseOrderItem, line.id).source_pr_item_id == pr_item.id
        assert db.session.get(PurchaseRequest, pr_item.purchase_request_id).status \
            == 'converted'


class TestTheDraftEditRoundTrip:
    """The half the create form cannot show: an EXISTING pulled line must be
    handed back to the form and re-posted with its source intact.

    PurchaseOrderItem.to_dict() feeds the form's EXISTING payload. If it omits
    source_pr_item_id nothing errors -- addRow never sets the dataset key, the
    serialiser posts null, and re-saving a draft orphans every pulled line and
    reopens a requisition that is still on order.
    """

    def _pulled_po(self, client, vendor, pr_item):
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': '8', 'unit_price': '10',
            'amount': '80', 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-RT')
        return PurchaseOrder.query.filter_by(po_number='SRC-PO-RT').first()

    def test_the_edit_form_renders_the_source_back(self, client, db_session,
                                                   admin_user, main_branch,
                                                   vendor, pr_item):
        _login(client, admin_user, main_branch)
        po = self._pulled_po(client, vendor, pr_item)
        html = client.get(f'/purchase-orders/{po.id}/edit').data.decode()
        assert f'"source_pr_item_id": {pr_item.id}' in html or \
               f'"source_pr_item_id":{pr_item.id}' in html, (
            'the edit form does not hand the requisition link back to the browser')

    def test_the_serialiser_reposts_it_from_an_existing_row(self, tmp_path, client,
                                                            db_session, admin_user,
                                                            main_branch, vendor,
                                                            pr_item):
        """Executes the real JS over the EXISTING row, not a hand-added one."""
        _login(client, admin_user, main_branch)
        po = self._pulled_po(client, vendor, pr_item)
        html = client.get(f'/purchase-orders/{po.id}/edit').data.decode()
        posted = _js.serialise_lines(tmp_path, html, marker=_MARKER, form_id=_FORM_ID)
        assert posted, 'the submit handler posted no lines'
        assert str(posted[0]['source_pr_item_id']) == str(pr_item.id), (
            'the pulled line came back without its requisition link')

    def test_resaving_a_draft_keeps_the_requisition_partially_converted(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        """The user-visible consequence of the two above."""
        _login(client, admin_user, main_branch)
        po = self._pulled_po(client, vendor, pr_item)
        line = po.line_items[0]
        client.post(f'/purchase-orders/{po.id}/edit', data={
            'po_number': 'SRC-PO-RT', 'order_date': '2026-08-15',
            'vendor_id': vendor.id, 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'row_version': po.row_version,
            'line_items': json.dumps([{
                'po_item_id': line.id, 'description': 'Carbide',
                'quantity': '8', 'unit_price': '10', 'amount': '80',
                'source_pr_item_id': line.source_pr_item_id,
            }]),
        }, follow_redirects=True)
        assert db.session.get(PurchaseRequest, pr_item.purchase_request_id).status \
            == 'partially_converted'
