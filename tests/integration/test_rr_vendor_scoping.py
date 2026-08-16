"""_eligible_purchase_orders() becomes vendor-scoped: the create form's PO picker
must offer only the chosen vendor's receivable POs, in the session branch, that
still have an open line -- and offer NOTHING before a vendor is chosen (the create
view has no vendor on first load; silently returning every vendor's POs would
defeat the vendor-first design this task exists for).

Called directly, not through the route: this pins the data-layer contract Task 4's
template/picker will consume, independent of how the picker itself is built.

TestABouncedEditIgnoresAPostedVendor at the foot of this file is the exception --
it goes through the edit ROUTE, because WHICH vendor edit() scopes by is a property
of the route, not of the helper.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _po(db_session, branch, vendor, number, qty=10, status='approved'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='OTH-VEND-VS', name='Other Vendor VS', tin='111-222-333-001')
    db_session.add(v); db_session.commit()
    return v


class TestVendorScoping:
    """Only the chosen vendor's POs are offered."""

    def test_a_po_of_the_chosen_vendor_with_an_open_line_is_offered(
            self, db_session, main_branch, vl_vendor):
        """CONTROL for every restriction test below: prove the ordinary case
        still comes through before proving narrower cases are excluded."""
        from app.receiving_reports.views import _eligible_purchase_orders
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-001')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert po in eligible

    def test_a_po_of_another_vendor_is_never_offered(
            self, db_session, main_branch, vl_vendor, other_vendor):
        from app.receiving_reports.views import _eligible_purchase_orders
        mine = _po(db_session, main_branch, vl_vendor, 'PO-VS-002')
        theirs = _po(db_session, main_branch, other_vendor, 'PO-VS-003')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert mine in eligible
        assert theirs not in eligible


class TestNoOpenLineExcluded:
    def test_a_po_with_no_open_line_is_excluded(self, db_session, main_branch, vl_vendor):
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        from app.receiving_reports.views import _eligible_purchase_orders
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-004', qty=10)
        poi = po.line_items[0]
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-VS-FULL',
                             receipt_date=date(2026, 7, 11),
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='approved')
        rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                                  received_quantity=Decimal('10')))
        db_session.add(rr); db_session.commit()

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert po not in eligible

    def test_a_po_still_holding_open_quantity_is_offered(self, db_session, main_branch, vl_vendor):
        """CONTROL. A partial receipt must not exhaust the whole PO's eligibility."""
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        from app.receiving_reports.views import _eligible_purchase_orders
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-005', qty=10)
        poi = po.line_items[0]
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-VS-PARTIAL',
                             receipt_date=date(2026, 7, 11),
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='approved')
        rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                                  received_quantity=Decimal('4')))
        db_session.add(rr); db_session.commit()

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert po in eligible


class TestBranchScoping:
    def test_a_po_in_another_branch_is_excluded(
            self, db_session, main_branch, branch_manila, vl_vendor):
        from app.receiving_reports.views import _eligible_purchase_orders
        elsewhere = _po(db_session, branch_manila, vl_vendor, 'PO-VS-006')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert elsewhere not in eligible

    def test_the_same_po_in_the_session_branch_is_offered(
            self, db_session, main_branch, branch_manila, vl_vendor):
        """CONTROL. Same vendor, same shape of PO -- only the branch differs --
        proving the exclusion above is the branch filter, not something else."""
        from app.receiving_reports.views import _eligible_purchase_orders
        here = _po(db_session, main_branch, vl_vendor, 'PO-VS-007')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert here in eligible


class TestNoVendorChosenYet:
    """The create view has no vendor selected on first load. Silently returning
    every vendor's receivable POs at that point would defeat the whole feature."""

    def test_no_vendor_chosen_offers_nothing(self, db_session, main_branch, vl_vendor, other_vendor):
        from app.receiving_reports.views import _eligible_purchase_orders
        _po(db_session, main_branch, vl_vendor, 'PO-VS-008')
        _po(db_session, main_branch, other_vendor, 'PO-VS-009')

        assert _eligible_purchase_orders(main_branch.id, None) == []

    def test_a_falsy_vendor_id_of_zero_also_offers_nothing(self, db_session, main_branch, vl_vendor):
        """CONTROL for the exact sentinel the '-- Select vendor --' choice submits."""
        from app.receiving_reports.views import _eligible_purchase_orders
        _po(db_session, main_branch, vl_vendor, 'PO-VS-010')

        assert _eligible_purchase_orders(main_branch.id, 0) == []


# -- the edit route's own scoping ---------------------------------------------

@pytest.fixture
def rr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po_lines_keys(body):
    """The PO ids the re-rendered form's grid was handed, read out of
    `const PO_LINES = {...};`.

    raw_decode rather than a regex or a split on ';': the payload carries product
    names and descriptions, so any delimiter guess is a delimiter a product name
    can contain.
    """
    marker = 'const PO_LINES = '
    start = body.index(marker) + len(marker)
    payload, _ = json.JSONDecoder().raw_decode(body, start)
    return {int(k) for k in payload}


class TestABouncedEditIgnoresAPostedVendor:
    """edit() scopes the picker by the RECEIPT's own vendor, never by the POSTed one.

    The vendor is a snapshot fixed at create, so a POSTed vendor_id has no standing
    on this route -- and the save already refuses a line whose PO belongs to anyone
    else, so data integrity never depended on this. What DOES depend on it is the
    bounce RE-RENDER: honour the POSTed vendor and a raw POST carrying a foreign
    vendor_id plus an over-ceiling quantity gets a grid full of ANOTHER vendor's PO
    lines, inviting the receiver to build a payload the save will only refuse.

    Unpinned until now: mutating line ~497 to honour `request.form['vendor_id']`
    left the whole receiving_reports marker green.
    """

    def _bounce(self, client, rr, poi, qty, vendor_id):
        return client.post(f'/receiving-reports/{rr.id}/edit', data={
            'vendor_id': str(vendor_id), 'receipt_date': '2026-07-11', 'remarks': '',
            'rr_number': rr.rr_number, 'row_version': str(rr.row_version),
            'lines': json.dumps([{'purchase_order_item_id': poi.id,
                                  'received_quantity': str(qty)}]),
        }, follow_redirects=True)

    @pytest.fixture
    def draft_rr(self, db_session, main_branch, vl_vendor):
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-EDIT-OWN', qty=10)
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-VS-EDIT',
                             receipt_date=date(2026, 7, 11),
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='draft')
        rr.line_items.append(ReceivingReportItem(line_number=1,
                                                 purchase_order_item_id=po.line_items[0].id,
                                                 received_quantity=Decimal('1')))
        db_session.add(rr); db_session.commit()
        return rr, po

    def test_a_foreign_posted_vendor_does_not_reach_the_re_rendered_grid(
            self, client, db_session, admin_user, main_branch, vl_vendor, other_vendor,
            rr_enabled, draft_rr):
        _login(client, admin_user, main_branch)
        rr, own_po = draft_rr
        # A second PO of the RECEIPT's vendor that the receipt does NOT draw on:
        # it can only be offered by the vendor scoping, never by the
        # `for po in rr.purchase_orders` fold-in below it.
        also_mine = _po(db_session, main_branch, vl_vendor, 'PO-VS-EDIT-MINE2', qty=10)
        theirs = _po(db_session, main_branch, other_vendor, 'PO-VS-EDIT-THEIRS', qty=10)

        # 11 against 10 open -> refused -> the bounce re-render this test is about.
        resp = self._bounce(client, rr, own_po.line_items[0], 11, vendor_id=other_vendor.id)

        assert resp.status_code == 200
        assert b'remain open' in resp.data                  # it really did bounce
        keys = _po_lines_keys(resp.data.decode())
        assert theirs.id not in keys                        # the forged vendor's PO
        assert {own_po.id, also_mine.id} <= keys            # the receipt's own vendor's

    def test_posting_the_receipts_own_vendor_renders_the_same_grid(
            self, client, db_session, admin_user, main_branch, vl_vendor, other_vendor,
            rr_enabled, draft_rr):
        """CONTROL. The grid above is not narrow because the bounce renders nothing
        useful -- posting the honest vendor produces exactly the same PO set."""
        _login(client, admin_user, main_branch)
        rr, own_po = draft_rr
        also_mine = _po(db_session, main_branch, vl_vendor, 'PO-VS-EDIT-MINE3', qty=10)
        theirs = _po(db_session, main_branch, other_vendor, 'PO-VS-EDIT-THEIRS2', qty=10)

        resp = self._bounce(client, rr, own_po.line_items[0], 11, vendor_id=vl_vendor.id)

        keys = _po_lines_keys(resp.data.decode())
        assert theirs.id not in keys
        assert {own_po.id, also_mine.id} <= keys
