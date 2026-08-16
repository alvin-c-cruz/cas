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
from tests.integration import _pr_picker_js as _picker

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


@pytest.fixture
def pr_item_b(db_session, main_branch, admin_user):
    """A SECOND requisition line, on its own requisition.

    The control for "two DIFFERENT requisition lines in one payload": a fix that
    simply refused any repeated source_pr_item_id would leave this passing, so
    the duplicate test alone cannot tell a correct fix from that one.
    """
    p = PurchaseRequest(pr_number='SRC-2', request_date=date(2026, 8, 15),
                        branch_id=main_branch.id, status='approved',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(line_number=1, description='Tungsten',
                                            quantity=200))
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


class TestOneSubmissionIsWeighedAsAWhole:
    """The live defect: the same requisition line pulled TWICE into ONE order.

    The ceiling is a SUM over PO lines already COMMITTED IN THE DATABASE, and it
    was consulted once per submitted line. Nothing in the submission being saved
    is in the database yet, so each duplicate was measured against the FULL open
    quantity and each passed on its own -- 20 <= 20, twice -- and the order went
    to the supplier for 40 against a requisition line with 20 open.

    The per-line check is not wrong; it simply answers a different question. The
    quantity that must fit under the ceiling is the payload's TOTAL per
    requisition line, so it is the payload that has to be weighed.
    """

    def test_the_same_requisition_line_twice_is_refused(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        """20 + 20 against 20 open. Each line is legal alone; the order is not."""
        _login(client, admin_user, main_branch)
        resp = _post_po(client, vendor, [
            {'description': 'Carbide', 'quantity': '20', 'unit_price': '10',
             'amount': '200', 'source_pr_item_id': pr_item.id},
            {'description': 'Carbide', 'quantity': '20', 'unit_price': '10',
             'amount': '200', 'source_pr_item_id': pr_item.id},
        ], number='SRC-PO-DUP')

        assert b'remain unordered' in resp.data, 'the over-allocation was not refused'
        assert PurchaseOrder.query.filter_by(po_number='SRC-PO-DUP').first() is None, \
            'the over-allocated purchase order was created anyway'
        # Nothing half-written: the refusal must roll the whole submission back,
        # not keep the first line and drop the second.
        assert PurchaseOrderItem.query.count() == 0
        assert db.session.get(PurchaseRequest, pr_item.purchase_request_id).status \
            == 'approved', 'the requisition was moved by an order that was refused'

    def test_two_different_requisition_lines_in_one_payload_both_save(
            self, client, db_session, admin_user, main_branch, vendor,
            pr_item, pr_item_b):
        """CONTROL. One order legitimately pulls several requisition lines at
        once -- that is what the picker's multi-select is for. A fix that keyed
        on "this payload names a requisition line more than once" without summing
        per line would break this."""
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [
            {'description': 'Carbide', 'quantity': '20', 'unit_price': '10',
             'amount': '200', 'source_pr_item_id': pr_item.id},
            {'description': 'Tungsten', 'quantity': '200', 'unit_price': '5',
             'amount': '1000', 'source_pr_item_id': pr_item_b.id},
        ], number='SRC-PO-TWO')

        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-TWO').first()
        assert po is not None, 'two distinct requisition lines were wrongly refused'
        assert len(po.line_items) == 2
        assert {li.source_pr_item_id for li in po.line_items} == \
            {pr_item.id, pr_item_b.id}

    def test_one_requisition_line_split_to_exactly_the_ceiling_saves(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        """CONTROL, and the boundary. 12 + 8 == 20 exactly: a buyer splitting one
        requisition line across two delivery dates on one order. An off-by-one
        that refuses the legal boundary is a real regression, not a safe
        over-tightening."""
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [
            {'description': 'Carbide (Aug)', 'quantity': '12', 'unit_price': '10',
             'amount': '120', 'source_pr_item_id': pr_item.id},
            {'description': 'Carbide (Sep)', 'quantity': '8', 'unit_price': '10',
             'amount': '80', 'source_pr_item_id': pr_item.id},
        ], number='SRC-PO-SPLIT')

        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-SPLIT').first()
        assert po is not None, 'a split that exactly fills the ceiling was refused'
        assert sum(li.quantity for li in po.line_items) == Decimal('20')
        assert db.session.get(PurchaseRequest, pr_item.purchase_request_id).status \
            == 'converted'

    def test_a_split_one_ten_thousandth_over_the_ceiling_is_refused(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        """The other side of the boundary, at the column's own scale
        (Numeric(15, 4)). Pairs with the test above so neither `>` nor `>=`
        passes both."""
        _login(client, admin_user, main_branch)
        _post_po(client, vendor, [
            {'description': 'Carbide (Aug)', 'quantity': '12', 'unit_price': '10',
             'amount': '120', 'source_pr_item_id': pr_item.id},
            {'description': 'Carbide (Sep)', 'quantity': '8.0001', 'unit_price': '10',
             'amount': '80', 'source_pr_item_id': pr_item.id},
        ], number='SRC-PO-OVERTINY')

        assert PurchaseOrder.query.filter_by(po_number='SRC-PO-OVERTINY').first() is None


class TestWhatThePullButtonDoesToTheGrid:
    """The client half, EXECUTED -- see tests/integration/_pr_picker_js.py.

    Both are answers, not strings, so neither is observable from a render
    assertion: the picker reads the DATABASE (open_lines_for_branch), and on
    CREATE there is no purchase-order id to exclude, so nothing in the unsaved
    form is subtracted from what the modal offers.

    The server is still the guard -- a POST never runs any of this. These tests
    are about what the buyer SEES.
    """

    def _pick(self, pr_item, qty):
        """One ticked modal row, shaped like an open_lines_for_branch row."""
        return {'qty': qty, 'row': {
            'pr_item_id': pr_item.id, 'pr_id': pr_item.purchase_request_id,
            'pr_number': 'SRC-1', 'date_needed': None, 'date_needed_asap': False,
            'product_id': None, 'product_code': None, 'product_name': None,
            'description': pr_item.description, 'uom_id': None, 'uom_code': None,
            'requested': '20', 'ordered': '0', 'open': qty,
        }}

    def test_pulling_consumes_the_blank_row_the_form_seeded(
            self, tmp_path, client, admin_user, main_branch, vendor, pr_item):
        """The grid read: empty row, then the pulled line. Cosmetic only --
        _po_line_is_blank drops the empty row on submit and line_number comes
        from a server-side kept counter, not DOM position -- but it reads as a
        mistake."""
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-orders/create').data.decode()
        seeded, posted = _picker.pull_and_serialise(
            tmp_path, html, [[self._pick(pr_item, '20')]])

        assert seeded == 1, (
            'the form no longer seeds a blank row on load -- this test then '
            'proves nothing about consuming one')
        assert len(posted) == 1, f'the blank row survived the pull: {posted}'
        assert posted[0]['source_pr_item_id'] == str(pr_item.id)

    def test_a_row_the_buyer_typed_into_survives_the_pull(
            self, tmp_path, client, admin_user, main_branch, vendor, pr_item):
        """CONTROL. The rule is BLANKNESS, not position: "drop the first row on
        pull" would pass the test above and silently eat real work."""
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-orders/create').data.decode()
        seeded, posted = _picker.pull_and_serialise(
            tmp_path, html, [[self._pick(pr_item, '20')]],
            edits=[{'row': 0, 'selector': '.po-desc', 'value': 'Freight'}])

        assert seeded == 1
        assert len(posted) == 2, f'the buyer\'s own line was deleted: {posted}'
        assert posted[0]['description'] == 'Freight'
        assert posted[0]['source_pr_item_id'] is None
        assert posted[1]['source_pr_item_id'] == str(pr_item.id)

    def test_re_pulling_one_line_updates_its_row_instead_of_stacking_a_second(
            self, tmp_path, client, admin_user, main_branch, vendor, pr_item):
        """The client half of the over-allocation. Two sessions, because the
        modal cannot offer one requisition line twice at once -- the buyer opens
        it, pulls, opens it again and pulls the same line."""
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-orders/create').data.decode()
        seeded, posted = _picker.pull_and_serialise(
            tmp_path, html, [[self._pick(pr_item, '20')],
                             [self._pick(pr_item, '20')]])

        assert len(posted) == 1, f'the re-pull stacked a duplicate row: {posted}'
        assert posted[0]['source_pr_item_id'] == str(pr_item.id)

    def test_pulling_two_different_lines_adds_both(
            self, tmp_path, client, admin_user, main_branch, vendor,
            pr_item, pr_item_b):
        """CONTROL for the merge, mirroring the server-side one: a fix that
        merged on anything coarser than the requisition line id would collapse
        these two into one."""
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-orders/create').data.decode()
        seeded, posted = _picker.pull_and_serialise(
            tmp_path, html, [[self._pick(pr_item, '20'),
                              self._pick(pr_item_b, '200')]])

        assert len(posted) == 2, f'two distinct requisition lines collapsed: {posted}'
        assert [p['source_pr_item_id'] for p in posted] == \
            [str(pr_item.id), str(pr_item_b.id)]


class TestTheAmendPathWeighsItsPayloadToo:
    """The amend path shares the call site and therefore shared the hole.

    It is also the path where the payload is the ONLY place the duplicate can be
    seen: amend updates lines IN PLACE, so exclude_po_id takes this order's own
    committed lines out of the ceiling entirely (see TestAmendingAPulledLine --
    without it an unchanged amendment is refused by its own lines). A mutation
    aimed at the edit path proves nothing there, because edit deletes every row
    before it re-parses.
    """

    def _approved_po(self, client, db_session, vendor, pr_item, qty='8'):
        _post_po(client, vendor, [{
            'description': 'Carbide', 'quantity': qty, 'unit_price': '10',
            'amount': str(int(qty) * 10), 'source_pr_item_id': pr_item.id,
        }], number='SRC-PO-AMDUP')
        po = PurchaseOrder.query.filter_by(po_number='SRC-PO-AMDUP').first()
        po.status = 'approved'
        db_session.commit()
        return po

    def _amend_lines(self, client, po, lines):
        return client.post(f'/purchase-orders/{po.id}/amend', data={
            'po_number': po.po_number, 'order_date': '2026-08-15',
            'vendor_id': po.vendor_id, 'vat_treatment': 'inclusive',
            'payment_terms': 'Net 30', 'notes': '',
            'amend_reason': 'buyer split the delivery',
            'row_version': po.row_version,
            'line_items': json.dumps(lines),
        }, follow_redirects=True)

    def test_amending_into_two_rows_over_the_ceiling_is_refused(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        """8 already ordered here, 12 still open; the amendment asks for 8 + 13."""
        _login(client, admin_user, main_branch)
        po = self._approved_po(client, db_session, vendor, pr_item)
        line = po.line_items[0]
        resp = self._amend_lines(client, po, [
            {'po_item_id': line.id, 'description': 'Carbide', 'quantity': '8',
             'unit_price': '10', 'amount': '80', 'source_pr_item_id': pr_item.id},
            {'po_item_id': None, 'description': 'Carbide', 'quantity': '13',
             'unit_price': '10', 'amount': '130', 'source_pr_item_id': pr_item.id},
        ])

        assert b'remain unordered' in resp.data, 'the amendment was not refused'
        db.session.expire_all()
        kept = PurchaseOrder.query.filter_by(po_number='SRC-PO-AMDUP').first()
        assert len(kept.line_items) == 1, 'the refused amendment was partly applied'
        assert kept.line_items[0].quantity == Decimal('8')

    def test_amending_into_two_rows_up_to_the_ceiling_succeeds(
            self, client, db_session, admin_user, main_branch, vendor, pr_item):
        """CONTROL on the same path: 8 + 12 == 20 exactly is a legal amendment."""
        _login(client, admin_user, main_branch)
        po = self._approved_po(client, db_session, vendor, pr_item)
        line = po.line_items[0]
        resp = self._amend_lines(client, po, [
            {'po_item_id': line.id, 'description': 'Carbide', 'quantity': '8',
             'unit_price': '10', 'amount': '80', 'source_pr_item_id': pr_item.id},
            {'po_item_id': None, 'description': 'Carbide', 'quantity': '12',
             'unit_price': '10', 'amount': '120', 'source_pr_item_id': pr_item.id},
        ])

        assert b'remain unordered' not in resp.data, (
            'a legal split amendment was refused')
        db.session.expire_all()
        kept = PurchaseOrder.query.filter_by(po_number='SRC-PO-AMDUP').first()
        assert len(kept.line_items) == 2
        assert sum(li.quantity for li in kept.line_items) == Decimal('20')


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
