"""The unit of measure reaches the screen and the printout.

Owner, 2026-08-29, looking at a live PO: "where is the UOM?" It was stored --
PO 00004 line 1 was 1000 KG, `unit_of_measure_id = 8` -- and simply never
rendered. The Purchase Order was the only document in its family that dropped
it from BOTH its detail page and its standard printout:

    document            detail   print
    purchase_orders     no       no
    purchase_requests   yes      yes
    receiving_reports   no       yes
    sales_orders        yes      yes
    accounts_payable    yes      --

RENDER assertions, deliberately. A POST-contract test writes the value and
reads it back from the database, so it passes whether or not any template ever
prints it -- which is exactly how a column goes missing for months while the
suite stays green (same shape as BUG-DR-EDIT-FALSE-CONFLICT, which shipped for
the same reason). The only thing that catches this is asserting on the rendered
HTML.

Each test pairs the UOM assertion with a control from the SAME table -- the
quantity -- so a template that fails to render at all cannot pass by absence.

Two traps this file already fell into, both caught by mutation rather than by
review:

  * The heading assertion was `b'UOM' in resp.data` while the fixture numbered
    its order PO-UOM-1. The page prints the document number, so the assertion
    matched THAT and could not fail -- deleting the column heading left every
    test green. The documents are now numbered PO-UNIT-n and the assertion is
    on the exact `<th>UOM</th>` markup.
  * `li.uom_display` looks like a model property but is only a key inside
    to_dict(), so it renders as empty in Jinja. The unit is read the way every
    sibling template reads it, straight off the relationship.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from app.settings import AppSettings
from app.units_of_measure.models import UnitOfMeasure
from app.utils.cache_helpers import clear_module_config_cache
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _modules_on(app, db_session):
    """purchase_orders and receiving_reports are optional and default-off, so
    every route below 404s until they are enabled -- a module gate, not a
    missing route. Cleared both sides (optional-module-gating-traps, trap 2)."""
    with app.app_context():
        clear_module_config_cache()
    for key in ('purchase_orders', 'receiving_reports'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def uom(db_session):
    u = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def vendor(db_session):
    v = Vendor(code='V-UNIT', name='UOM Test Supplies')
    db_session.add(v)
    db_session.commit()
    return v


@pytest.fixture
def po(db_session, main_branch, admin_user, vendor, uom):
    order = PurchaseOrder(po_number='PO-UNIT-1', order_date=date(2026, 8, 29),
                          branch_id=main_branch.id, status='submitted',
                          vendor_id=vendor.id, vendor_name=vendor.name,
                          vat_treatment='inclusive', created_by_id=admin_user.id)
    order.line_items.append(PurchaseOrderItem(
        line_number=1, description='For production use',
        quantity=Decimal('1000'), unit_price=Decimal('12.50'),
        amount=Decimal('12500'), unit_of_measure_id=uom.id))
    db_session.add(order)
    db_session.commit()
    return order


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


class TestThePurchaseOrder:

    def test_the_detail_page_shows_the_unit(self, client, db_session, admin_user,
                                            main_branch, po):
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-orders/%d' % po.id)
        assert resp.status_code == 200
        assert b'1,000.0000' in resp.data, 'the quantity did not render at all'
        assert b'KG' in resp.data, 'the quantity rendered but its unit did not'
        assert b'<th>UOM</th>' in resp.data, 'no UOM column heading'

    def test_the_printout_shows_the_unit(self, client, db_session, admin_user,
                                         main_branch, po):
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-orders/%d/print' % po.id)
        assert resp.status_code == 200
        assert b'1,000.0000' in resp.data, 'the quantity did not render at all'
        assert b'KG' in resp.data, 'the quantity rendered but its unit did not'

    def test_a_line_with_no_unit_renders_blank_not_none(self, client, db_session,
                                                        admin_user, main_branch,
                                                        vendor):
        """CONTROL. UOM is nullable -- a services line carries no unit, and the
        cell must be empty rather than printing the word None.

        The order is SUBMITTED, not draft: a draft PO is refused by the
        print-access gate and redirects, so a draft here would test that
        gate instead of the UOM cell.

        The page-wide None check is only meaningful because the fixture sets
        vendor_name the way create() does: without it the header renders
        'Vendor: None' and this assertion fails for an unrelated reason."""
        order = PurchaseOrder(po_number='PO-UNIT-2', order_date=date(2026, 8, 29),
                              branch_id=main_branch.id, status='submitted',
                              vendor_id=vendor.id, vendor_name=vendor.name,
                              vat_treatment='inclusive', created_by_id=admin_user.id)
        order.line_items.append(PurchaseOrderItem(
            line_number=1, description='Consultancy', quantity=Decimal('1'),
            unit_price=Decimal('5000'), amount=Decimal('5000')))
        db_session.add(order)
        db_session.commit()
        _login(client, admin_user, main_branch)
        for url in ('/purchase-orders/%d' % order.id,
                    '/purchase-orders/%d/print' % order.id):
            data = client.get(url).data
            assert b'Consultancy' in data, '%s did not render the line' % url
            assert b'None' not in data, '%s printed the literal None' % url


class TestTheReceivingReport:

    def test_the_detail_page_shows_the_unit(self, client, db_session, admin_user,
                                            main_branch, vendor, uom, po):
        """The RR reads its unit THROUGH the purchase-order line it receives --
        ReceivingReportItem.unit_of_measure is a property delegating to
        `purchase_order_item`, not a column of its own."""
        rr = ReceivingReport(rr_number='RR-UNIT-1', receipt_date=date(2026, 8, 29),
                             branch_id=main_branch.id, status='draft',
                             vendor_id=vendor.id, vendor_name=vendor.name,
                             created_by_id=admin_user.id)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=po.line_items[0].id,
            received_quantity=Decimal('400')))
        db_session.add(rr)
        db_session.commit()

        _login(client, admin_user, main_branch)
        resp = client.get('/receiving-reports/%d' % rr.id)
        assert resp.status_code == 200
        assert b'400.0000' in resp.data, 'the received quantity did not render'
        assert b'KG' in resp.data, 'the quantity rendered but its unit did not'
        assert b'<th>UOM</th>' in resp.data, 'no UOM column heading'
