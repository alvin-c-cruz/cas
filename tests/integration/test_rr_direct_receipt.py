"""A receiving report can record goods that arrived WITHOUT a purchase order.

Owner request, 2026-09-06. Until rrdirect_0001 every receipt line pointed at a
purchase-order line (`purchase_order_item_id` NOT NULL), so a walk-in purchase, a
replacement part or a sample had nowhere to be recorded at all.

THE CONSTRAINT THAT SHAPES EVERYTHING HERE: "RR cannot have unit price" (owner). A
receiving report records what ARRIVED, never what it is worth -- the receiver is not
the person who sets costs. So a direct line carries a product and a quantity and
nothing else, and its cost is taken from the PRODUCT MASTER at approval:

    Product.standard_cost  ->  StockBalance.average_unit_cost  ->  REFUSE

Both fallbacks are existing conventions rather than inventions: a production run posts
finished goods at standard cost and ignores what is passed to post_movement
(app/production_runs/service.py), and a physical count values found stock at the running
average (app/stock_adjustments/physical_count_service.py).

WHY IT REFUSES rather than posting zero, which is the decision most likely to be
revisited by someone who has not read the billing path: a zero accrual makes GRNI zero,
so when the AP bill arrives `variance = net_base - 0` and the ENTIRE cost posts to
`inventory_variance` instead of Inventory (app/accounts_payable/views.py). The goods
would sit on the shelf valued at nothing, permanently -- not "until billed". Refusing is
the only outcome that leaves the ledger honest, and it names the product to fix.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from app.settings import AppSettings
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture
def grni_accounts(db_session, make_account):
    """The two control accounts post_rr_receipt resolves before it values anything.

    Without them it fails closed on the ACCOUNT, never reaching the costing chain -- so a
    test meaning to exercise the valuation would pass or fail for the wrong reason.
    Mirrors test_receiving_report_stock_posting's _assign helper.
    """
    for setting, code in (('inventory_account_code', '1401'),
                          ('grni_account_code', '2015')):
        make_account(code)
        AppSettings.set_setting(setting, code, updated_by='test')
    db_session.commit()


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='DIR-V', name='Direct Delivery Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def untracked_product(db_session):
    """The common case for a direct receipt: freight, a repair, a consumable. Nothing is
    posted to stock for it, so no valuation question arises at all."""
    from app.products.models import Product
    p = Product(code='SVC-001', name='Delivery Freight', track_inventory=False,
                is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _draft(db_session, branch, vendor, user, number='RR-DIR-1'):
    rr = ReceivingReport(rr_number=number, receipt_date=date(2026, 9, 6),
                         branch_id=branch.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, status='draft',
                         created_by_id=user.id)
    db_session.add(rr); db_session.commit()
    return rr


def _create_via_form(client, vendor, payload, number='RR-DIR-FORM'):
    """Save a receipt through the REAL create route, then return (response, receipt).

    The route, not a direct insert: _parse_rr_lines is the seam a raw POST reaches, and
    it is where the product is validated. Bypassing it would test nothing that matters.
    A refused save leaves the receipt None.
    """
    import json
    resp = client.post('/receiving-reports/create', data={
        'vendor_id': vendor.id,
        'receipt_date': '2026-09-06',
        'remarks': '',
        'rr_number': number,
        'lines': json.dumps(payload),
    }, follow_redirects=True)
    return resp, ReceivingReport.query.filter_by(rr_number=number).first()


class TestTheSchemaAllowsIt:

    def test_the_fk_is_nullable(self):
        """The migration's whole content. Asserted against the MAPPER rather than by
        inserting a row, so it fails with a clear message if the migration is ever
        reverted while this feature's code stays."""
        col = ReceivingReportItem.__table__.c.purchase_order_item_id
        assert col.nullable is True

    def test_a_line_knows_which_kind_it_is(self, db_session, main_branch, vendor,
                                           admin_user, untracked_product):
        rr = _draft(db_session, main_branch, vendor, admin_user)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None,
            product_id=untracked_product.id, received_quantity=Decimal('3')))
        db_session.commit()
        assert rr.line_items[0].is_direct is True

    def test_a_direct_line_contributes_no_purchase_order(self, db_session, main_branch,
                                                         vendor, admin_user,
                                                         untracked_product):
        """`.purchase_orders` derives the receipt's orders per line. A direct line has
        none, and must not make that property raise."""
        rr = _draft(db_session, main_branch, vendor, admin_user)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None,
            product_id=untracked_product.id, received_quantity=Decimal('3')))
        db_session.commit()
        assert rr.purchase_orders == []


class TestItDerivesFromTheProduct:
    """A direct line has no order line to take its wording or unit from, so both come
    from the product -- the same master the cost comes from."""

    def test_the_description_falls_back_to_the_product_name(self, db_session, main_branch,
                                                            vendor, admin_user,
                                                            untracked_product):
        rr = _draft(db_session, main_branch, vendor, admin_user)
        li = ReceivingReportItem(line_number=1, purchase_order_item_id=None,
                                 product_id=untracked_product.id,
                                 received_quantity=Decimal('3'))
        rr.line_items.append(li); db_session.commit()
        assert li.description == 'Delivery Freight'

    def test_the_unit_falls_back_to_the_products_default(self, db_session, main_branch,
                                                         vendor, admin_user):
        from app.products.models import Product
        from app.units_of_measure.models import UnitOfMeasure
        uom = UnitOfMeasure(code='BOX', name='Box', is_active=True)
        db_session.add(uom); db_session.commit()
        p = Product(code='BOXED-1', name='Boxed Thing', track_inventory=False,
                    default_unit_of_measure_id=uom.id, is_active=True)
        db_session.add(p); db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        li = ReceivingReportItem(line_number=1, purchase_order_item_id=None,
                                 product_id=p.id, received_quantity=Decimal('1'))
        rr.line_items.append(li); db_session.commit()
        assert li.unit_of_measure is not None
        assert li.unit_of_measure.code == 'BOX'

    def test_the_line_stores_no_price_of_its_own(self):
        """The owner's constraint, made executable. A price column on this table is the
        one change that would quietly undo the whole design."""
        stored = {c.key for c in ReceivingReportItem.__table__.columns}
        assert 'unit_price' not in stored
        assert 'unit_cost' not in stored


class TestValuingATrackedDirectReceipt:
    """The part with money in it."""

    def _approve(self, client, rr):
        return client.post('/receiving-reports/%s/approve' % rr.id, follow_redirects=True)

    def _tracked_line(self, db_session, rr, product, qty='10'):
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None, product_id=product.id,
            received_quantity=Decimal(qty)))
        db_session.commit()

    def test_it_values_at_the_products_standard_cost(self, client, db_session, main_branch,
                                                     vendor, admin_user, product_tracked,
                                                     grni_accounts):
        product_tracked.standard_cost = Decimal('125.00')
        db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        self._tracked_line(db_session, rr, product_tracked)
        _login(client, admin_user, main_branch)
        self._approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'approved'
        mv = rr.line_items[0].stock_movement
        assert mv is not None
        assert Decimal(str(mv.unit_cost)) == Decimal('125.00')

    def test_the_accrual_matches_what_the_stock_was_valued_at(self, client, db_session,
                                                              main_branch, vendor,
                                                              admin_user, product_tracked,
                                                              grni_accounts):
        """Inventory and GRNI must agree with the movement, or the AP bill's true-up --
        which reads the movement back to compute the variance -- starts from a figure the
        ledger never saw."""
        product_tracked.standard_cost = Decimal('125.00')
        db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        self._tracked_line(db_session, rr, product_tracked)
        _login(client, admin_user, main_branch)
        self._approve(client, rr)
        db_session.refresh(rr)
        je = rr.line_items[0].stock_movement.journal_entry_id
        from app.journal_entries.models import JournalEntryLine
        legs = JournalEntryLine.query.filter_by(entry_id=je).all()
        assert sum(Decimal(str(l.debit_amount or 0)) for l in legs) == Decimal('1250.00')
        assert sum(Decimal(str(l.credit_amount or 0)) for l in legs) == Decimal('1250.00')

    def test_it_falls_back_to_the_running_average(self, client, db_session, main_branch,
                                                  vendor, admin_user, product_tracked,
                                                  grni_accounts):
        """No standard cost, but the company already holds this item: value the receipt at
        what the stock on hand is carried at, exactly as a physical count does."""
        from app.stock_adjustments.models import StockBalance
        product_tracked.standard_cost = None
        db_session.add(StockBalance(product_id=product_tracked.id, branch_id=main_branch.id,
                                    quantity_on_hand=Decimal('4'),
                                    average_unit_cost=Decimal('80.00'),
                                    total_value=Decimal('320.00')))
        db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        self._tracked_line(db_session, rr, product_tracked)
        _login(client, admin_user, main_branch)
        self._approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'approved'
        assert Decimal(str(rr.line_items[0].stock_movement.unit_cost)) == Decimal('80.00')

    def test_the_standard_cost_wins_over_the_average(self, client, db_session, main_branch,
                                                     vendor, admin_user, product_tracked,
                                                     grni_accounts):
        """CONTROL for the ordering. Without it, a chain that consulted the average first
        would satisfy both tests above."""
        from app.stock_adjustments.models import StockBalance
        product_tracked.standard_cost = Decimal('125.00')
        db_session.add(StockBalance(product_id=product_tracked.id, branch_id=main_branch.id,
                                    quantity_on_hand=Decimal('4'),
                                    average_unit_cost=Decimal('80.00'),
                                    total_value=Decimal('320.00')))
        db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        self._tracked_line(db_session, rr, product_tracked)
        _login(client, admin_user, main_branch)
        self._approve(client, rr)
        db_session.refresh(rr)
        assert Decimal(str(rr.line_items[0].stock_movement.unit_cost)) == Decimal('125.00')


class TestItRefusesWhatItCannotValue:
    """FAIL-CLOSED. See the module docstring for why zero is not an option."""

    def test_approval_is_refused_when_the_master_cannot_value_it(
            self, client, db_session, main_branch, vendor, admin_user, product_tracked,
            grni_accounts):
        product_tracked.standard_cost = None
        db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None, product_id=product_tracked.id,
            received_quantity=Decimal('10')))
        db_session.commit()
        _login(client, admin_user, main_branch)
        body = client.post('/receiving-reports/%s/approve' % rr.id,
                           follow_redirects=True).data.decode()
        db_session.refresh(rr)
        assert rr.status == 'draft'                    # refused, not half-approved
        assert 'standard cost' in body.lower()

    def test_the_refusal_names_the_product_to_fix(self, client, db_session, main_branch,
                                                  vendor, admin_user, product_tracked,
                                                  grni_accounts):
        """A refusal the receiver cannot act on is only marginally better than a 500."""
        product_tracked.standard_cost = None
        db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None, product_id=product_tracked.id,
            received_quantity=Decimal('10')))
        db_session.commit()
        _login(client, admin_user, main_branch)
        body = client.post('/receiving-reports/%s/approve' % rr.id,
                           follow_redirects=True).data.decode()
        assert product_tracked.code in body
        assert product_tracked.name in body

    def test_nothing_is_posted_when_it_refuses(self, client, db_session, main_branch,
                                               vendor, admin_user, product_tracked,
                                               grni_accounts):
        """The rollback matters as much as the refusal: a half-written receipt with a
        stock movement and no journal entry is worse than no receipt."""
        from app.journal_entries.models import JournalEntry
        product_tracked.standard_cost = None
        db_session.commit()
        before = JournalEntry.query.count()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None, product_id=product_tracked.id,
            received_quantity=Decimal('10')))
        db_session.commit()
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/approve' % rr.id, follow_redirects=True)
        db_session.refresh(rr)
        assert JournalEntry.query.count() == before
        assert rr.line_items[0].stock_movement_id is None

    def test_an_untracked_product_needs_no_cost_at_all(self, client, db_session,
                                                       main_branch, vendor, admin_user,
                                                       untracked_product, grni_accounts):
        """THE common case, and the reason the refusal above is narrow rather than a
        blanket ban on PO-less receipts. Freight and repairs never touch stock, so
        post_rr_receipt returns before any valuation is attempted."""
        rr = _draft(db_session, main_branch, vendor, admin_user)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=None, product_id=untracked_product.id,
            received_quantity=Decimal('2')))
        db_session.commit()
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/approve' % rr.id, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'approved'
        assert rr.line_items[0].stock_movement_id is None      # nothing posted to stock


class TestThePayloadPath:
    """views._parse_rr_lines: the seam a raw POST reaches."""

    def test_a_direct_line_saves_through_the_form(self, client, db_session, main_branch,
                                                  vendor, admin_user, untracked_product):
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                   'received_quantity': '4'}])
        assert rr is not None, 'the receipt was refused'
        assert len(rr.line_items) == 1
        assert rr.line_items[0].is_direct is True
        assert Decimal(str(rr.line_items[0].received_quantity)) == Decimal('4')

    def test_both_kinds_can_share_one_receipt(self, client, db_session, main_branch,
                                              vendor, admin_user, untracked_product,
                                              product_tracked):
        """One delivery often brings both: the ordered goods, and something extra that was
        never on the order. Line numbers must follow SUBMISSION order rather than herding
        the direct lines to the end, so the receipt reads the way it was entered."""
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        po = PurchaseOrder(branch_id=main_branch.id, po_number='PO-MIX-1',
                           order_date=date(2026, 9, 1), vendor_id=vendor.id,
                           vendor_name=vendor.name, status='approved',
                           vat_treatment='inclusive', created_by_id=admin_user.id)
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='Ordered thing', quantity=Decimal('5'),
            unit_price=Decimal('100'), amount=Decimal('500'),
            product_id=product_tracked.id, vat_rate=Decimal('12')))
        db_session.add(po)
        db_session.commit()
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [
            {'purchase_order_item_id': po.line_items[0].id, 'received_quantity': '5'},
            {'product_id': untracked_product.id, 'received_quantity': '1'},
        ], number='RR-DIR-MIX')
        assert rr is not None, 'the receipt was refused'
        kinds = [li.is_direct for li in sorted(rr.line_items, key=lambda x: x.line_number)]
        assert kinds == [False, True]

    def test_an_unknown_product_is_refused(self, client, db_session, main_branch, vendor,
                                           admin_user):
        """A PICKER FILTER IS NOT ENFORCEMENT -- the existing ceiling check says exactly
        that about PO lines, and a raw POST reaches this path just the same."""
        _login(client, admin_user, main_branch)
        resp, rr = _create_via_form(client, vendor, [{'product_id': 999999,
                                                      'received_quantity': '4'}])
        assert rr is None
        body = resp.data.decode().lower()
        assert 'does not exist' in body or 'not a valid reference' in body

    def test_an_inactive_product_is_refused(self, client, db_session, main_branch, vendor,
                                            admin_user, untracked_product):
        """Inactive is how a product is retired. A retired product must not start
        appearing on new receipts just because the picker was bypassed."""
        untracked_product.is_active = False
        db_session.commit()
        _login(client, admin_user, main_branch)
        resp, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                      'received_quantity': '4'}])
        assert rr is None
        assert 'no longer' in resp.data.decode().lower()

    def test_a_zero_quantity_line_is_dropped(self, client, db_session, main_branch, vendor,
                                             admin_user, untracked_product):
        """Clearing the quantity is the remove gesture, for a direct line as much as a
        PO-backed one -- and a receipt left with nothing is refused, not saved empty."""
        _login(client, admin_user, main_branch)
        resp, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                      'received_quantity': '0'}])
        assert rr is None
        assert 'at least one received line' in resp.data.decode().lower()


@pytest.fixture
def unit_box(db_session):
    from app.units_of_measure.models import UnitOfMeasure
    u = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    db_session.add(u); db_session.commit()
    return u


class TestTheReceiverCanSetTheUnit:
    """Owner, 2026-09-07: "user should be able to set UOM for +Add Item Without PO."

    A PO-backed line takes its unit from the order line -- that is what the vendor was
    asked for, and the receipt should not disagree with it. A direct line has no order
    line, and the product's default is often right but not always: goods arrive by the
    box for a product carried by the piece, and a product may carry no default at all.
    The person unpacking the delivery is the one who can see which it was.

    OPTIONAL, and that matters for the migration: a line saved before rruom_0001 has NULL
    here and must keep resolving its unit exactly as it did.
    """

    def test_the_chosen_unit_wins_over_the_products_default(self, db_session, main_branch,
                                                            vendor, admin_user, unit_box):
        from app.products.models import Product
        from app.units_of_measure.models import UnitOfMeasure
        piece = UnitOfMeasure(code='PC', name='Piece', is_active=True)
        db_session.add(piece); db_session.commit()
        prod = Product(code='DFLT-1', name='Defaulted Thing', track_inventory=False,
                       default_unit_of_measure_id=piece.id, is_active=True)
        db_session.add(prod); db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        li = ReceivingReportItem(line_number=1, purchase_order_item_id=None,
                                 product_id=prod.id, unit_of_measure_id=unit_box.id,
                                 received_quantity=Decimal('2'))
        rr.line_items.append(li); db_session.commit()
        assert li.unit_of_measure.code == 'BOX'

    def test_without_a_choice_it_still_falls_back_to_the_product(self, db_session,
                                                                 main_branch, vendor,
                                                                 admin_user):
        """THE backward-compatibility guarantee: every line saved before rruom_0001 has
        NULL here."""
        from app.products.models import Product
        from app.units_of_measure.models import UnitOfMeasure
        piece = UnitOfMeasure(code='PC', name='Piece', is_active=True)
        db_session.add(piece); db_session.commit()
        prod = Product(code='DFLT-2', name='Defaulted Thing 2', track_inventory=False,
                       default_unit_of_measure_id=piece.id, is_active=True)
        db_session.add(prod); db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        li = ReceivingReportItem(line_number=1, purchase_order_item_id=None,
                                 product_id=prod.id, unit_of_measure_id=None,
                                 received_quantity=Decimal('2'))
        rr.line_items.append(li); db_session.commit()
        assert li.unit_of_measure.code == 'PC'

    def test_an_order_line_still_settles_the_unit(self, db_session, main_branch, vendor,
                                                  admin_user, product_tracked, unit_box):
        """A PO-backed line ignores this column even if something sets it: the order says
        what was asked for, and the receipt must not quietly disagree."""
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        from app.units_of_measure.models import UnitOfMeasure
        kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
        db_session.add(kg); db_session.commit()
        po = PurchaseOrder(branch_id=main_branch.id, po_number='PO-UOM-1',
                           order_date=date(2026, 9, 1), vendor_id=vendor.id,
                           vendor_name=vendor.name, status='approved',
                           vat_treatment='inclusive', created_by_id=admin_user.id)
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='Ordered by the kilo', quantity=Decimal('5'),
            unit_price=Decimal('100'), amount=Decimal('500'),
            product_id=product_tracked.id, unit_of_measure_id=kg.id,
            vat_rate=Decimal('12')))
        db_session.add(po); db_session.commit()
        rr = _draft(db_session, main_branch, vendor, admin_user)
        li = ReceivingReportItem(line_number=1,
                                 purchase_order_item_id=po.line_items[0].id,
                                 product_id=product_tracked.id,
                                 unit_of_measure_id=unit_box.id,      # ignored
                                 received_quantity=Decimal('5'))
        rr.line_items.append(li); db_session.commit()
        assert li.unit_of_measure.code == 'KG'

    def test_it_saves_and_reopens_through_the_form(self, client, db_session, main_branch,
                                                   vendor, admin_user, untracked_product,
                                                   unit_box):
        """Round-trip, because the edit path rebuilds the grid from a SEPARATE channel for
        direct lines -- the PO-backed one is keyed by purchase_order_item_id, which a
        direct line does not have. A unit that saved but did not come back would look
        like it had never been set."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                   'received_quantity': '4',
                                                   'unit_of_measure_id': unit_box.id}],
                                 number='RR-UOM-FORM')
        assert rr is not None, 'the receipt was refused'
        assert rr.line_items[0].unit_of_measure_id == unit_box.id
        body = client.get('/receiving-reports/%s/edit' % rr.id).data.decode()
        assert '"unit_of_measure_id": %d' % unit_box.id in body.replace("'", '"')

    def test_an_unknown_unit_is_refused(self, client, db_session, main_branch, vendor,
                                        admin_user, untracked_product):
        """A PICKER FILTER IS NOT ENFORCEMENT, for the unit as much as the product."""
        _login(client, admin_user, main_branch)
        resp, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                      'received_quantity': '4',
                                                      'unit_of_measure_id': 999999}],
                                    number='RR-UOM-BAD')
        assert rr is None
        assert 'unit of measure' in resp.data.decode().lower()

    def test_an_inactive_unit_is_refused(self, client, db_session, main_branch, vendor,
                                         admin_user, untracked_product, unit_box):
        unit_box.is_active = False
        db_session.commit()
        _login(client, admin_user, main_branch)
        resp, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                      'received_quantity': '4',
                                                      'unit_of_measure_id': unit_box.id}],
                                    number='RR-UOM-OFF')
        assert rr is None
        assert 'no longer active' in resp.data.decode().lower()

    def test_omitting_the_unit_is_allowed(self, client, db_session, main_branch, vendor,
                                          admin_user, untracked_product):
        """CONTROL for the two refusals: they must not have made the unit mandatory. A
        payload written before rruom_0001 carries no such key at all."""
        _login(client, admin_user, main_branch)
        _, rr = _create_via_form(client, vendor, [{'product_id': untracked_product.id,
                                                   'received_quantity': '4'}],
                                 number='RR-UOM-NONE')
        assert rr is not None
        assert rr.line_items[0].unit_of_measure_id is None
