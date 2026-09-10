"""A no-PO line is flagged when the vendor has an open order line for that product.

Owner request 2026-09-07. PO-less receipts are expected weekly or more, so the mismatch
is caught at ENTRY rather than only repaired afterwards.

It WARNS, it does not block. The match is a heuristic: it knows this vendor has an open
line for this product, not that this carton came off that order. A free replacement, a
sample, or a second delivery are all legitimate direct receipts against an open order,
and blocking would make them unrecordable.

KNOWN LIMIT, by owner decision: the warning fires at pick time in the browser, and the
server stores the override reason WITHOUT refusing a line that lacks one. A raw POST, or
an order approved between picking and saving, gets past it. Recorded here so it is not
mistaken for an oversight.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.receiving_reports.models import ReceivingReport
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='WARN-V', name='Warning Test Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='WARN-V2', name='Other Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='WARN-P', name='Warned Item', track_inventory=False, is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _open_po(db_session, branch, vendor, product, user, number='PO-WARN-1', qty='10'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       order_date=date(2026, 9, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive', created_by_id=user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Ordered thing', quantity=Decimal(qty),
        unit_price=Decimal('100'), amount=Decimal(qty) * 100,
        product_id=product.id, vat_rate=Decimal('12')))
    db_session.add(po); db_session.commit()
    return po


class TestThePayloadCarriesTheProduct:

    def test_open_lines_name_their_product_id(self, client, db_session, main_branch,
                                              vendor, product, admin_user):
        """Without product_id the browser cannot match a chosen product to an open
        order line at all -- product_code is display text, not an identity.

        Asserted against the ENDPOINT, not the create page. On a fresh GET of
        /receiving-reports/create the view sets `eligible = []` deliberately -- there is
        no vendor until the receiver picks one -- so the page-load payload is empty and
        proves nothing. The endpoint is what the browser actually reads.
        """
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        rows = client.get('/receiving-reports/open-lines?vendor_id=%s'
                          % vendor.id).get_json()['lines']
        assert rows, 'the endpoint offered no open lines'
        assert rows[0]['product_id'] == product.id

    def test_another_vendors_open_line_is_not_offered(self, client, db_session,
                                                      main_branch, other_vendor,
                                                      vendor, product, admin_user):
        """CONTROL, and the reason the warning needs no vendor check of its own: the
        endpoint is already scoped, so a match can only ever be this vendor's."""
        _open_po(db_session, main_branch, other_vendor, product, admin_user,
                 number='PO-WARN-OTHER')
        _login(client, admin_user, main_branch)
        rows = client.get('/receiving-reports/open-lines?vendor_id=%s'
                          % vendor.id).get_json()['lines']
        assert rows == []


class TestTheFormCanWarn:

    def _create_page(self, client, vendor):
        # No vendor_id query param: the create view ignores one on GET, and these
        # assertions are about STATIC markup that renders regardless.
        return client.get('/receiving-reports/create').data.decode()

    def test_the_modal_has_somewhere_to_show_the_warning(self, client, db_session,
                                                         main_branch, vendor, product,
                                                         admin_user):
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        assert 'id="directPoWarning"' in self._create_page(client, vendor)

    def test_the_modal_has_somewhere_to_type_the_override(self, client, db_session,
                                                          main_branch, vendor, product,
                                                          admin_user):
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        assert 'id="directNoPoReason"' in self._create_page(client, vendor)

    def test_no_blocking_dialog_is_used(self, client, db_session, main_branch, vendor,
                                        product, admin_user):
        """Project rule: no confirm()/alert()/prompt(), ever -- they wedge an automated
        browser until dismissed by hand. Comments count; the test scans served HTML."""
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        page = self._create_page(client, vendor)
        for banned in ('confirm(', 'alert(', 'prompt('):
            assert banned not in page, '%s is forbidden -- use inline HTML' % banned


def _create_via_form(client, vendor, payload, number='RR-WARN-FORM'):
    import json
    resp = client.post('/receiving-reports/create', data={
        'vendor_id': vendor.id, 'receipt_date': '2026-09-07', 'remarks': '',
        'rr_number': number, 'lines': json.dumps(payload),
    }, follow_redirects=True)
    return resp, ReceivingReport.query.filter_by(rr_number=number).first()


class TestTheReasonIsPersisted:

    def test_it_is_stored_on_the_line(self, client, db_session, main_branch, vendor,
                                      product, admin_user):
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'Free replacement for the damaged unit'}])
        assert rr is not None, 'the receipt was refused'
        assert rr.line_items[0].no_po_reason == 'Free replacement for the damaged unit'

    def test_it_reaches_the_audit_log(self, client, db_session, main_branch, vendor,
                                      product, admin_user):
        """The column holds the current value; the audit log is the permanent record."""
        from app.audit.models import AuditLog
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'Sample from the rep'}], number='RR-WARN-AUD')
        notes = ' '.join(
            (e.notes or '') for e in
            AuditLog.query.filter_by(module='receiving_reports', record_id=rr.id).all())
        assert 'Sample from the rep' in notes

    def test_a_line_with_no_reason_stores_none(self, client, db_session, main_branch,
                                               vendor, product, admin_user):
        """CONTROL: the field is optional. A direct line for a product with no matching
        order has nothing to explain, and a reason on it would be noise."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2'}],
            number='RR-WARN-NONE')
        assert rr is not None
        assert rr.line_items[0].no_po_reason is None

    def test_an_overlong_reason_is_truncated_not_refused(self, client, db_session,
                                                         main_branch, vendor, product,
                                                         admin_user):
        """A raw POST can send any length. Refusing would lose the receipt over a
        cosmetic problem; the text is capped instead."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'x' * 500}], number='RR-WARN-LONG')
        assert rr is not None
        assert len(rr.line_items[0].no_po_reason) == 200

    def test_it_round_trips_into_the_edit_form(self, client, db_session, main_branch,
                                               vendor, product, admin_user):
        """Direct lines are re-rendered from their own channel; a reason that saved but
        did not come back would look like it had never been given."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{
            'product_id': product.id, 'received_quantity': '2',
            'no_po_reason': 'Warranty swap'}], number='RR-WARN-RT')
        body = client.get('/receiving-reports/%s/edit' % rr.id).data.decode()
        assert 'Warranty swap' in body


class TestTheListShowsWhichReceiptsHadNoPo:
    """At weekly frequency these need reviewing without opening each one -- and this is
    the same view that shows whether the warning is working."""

    def test_a_receipt_with_a_direct_line_is_marked(self, client, db_session, main_branch,
                                                    vendor, product, admin_user):
        _login(client, admin_user, main_branch)
        _create_via_form(client, vendor, [{'product_id': product.id,
                                           'received_quantity': '2'}],
                         number='RR-WARN-LIST')
        body = client.get('/receiving-reports').data.decode()
        assert 'title="Contains items received without a purchase order"' in body

    def test_a_fully_ordered_receipt_is_not_marked(self, client, db_session, main_branch,
                                                   vendor, product, admin_user):
        """CONTROL. A marker on every row tells the reviewer nothing."""
        po = _open_po(db_session, main_branch, vendor, product, admin_user,
                      number='PO-WARN-LIST')
        _login(client, admin_user, main_branch)
        _create_via_form(client, vendor,
                         [{'purchase_order_item_id': po.line_items[0].id,
                           'received_quantity': '2'}], number='RR-WARN-PO')
        body = client.get('/receiving-reports').data.decode()
        assert 'title="Contains items received without a purchase order"' not in body
