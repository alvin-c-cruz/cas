"""Product.code becomes optional, then invisible.

Owner, 2026-09-08: clients do not use the product code. Approach C was chosen
deliberately over deleting the column -- make it optional and hide it, so the 555
codes already recorded survive and the decision stays reversible.

The unique index is KEPT. SQLite permits multiple NULLs under a unique index, so
new products simply have no code while existing ones stay unique. Dropping the
index is the irreversible half and is not part of this change.

`name` is NOT made unique. That would be a second, irreversible decision smuggled
in beside a reversible one -- and the master legitimately allows two products to
share a name.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.products.models import Product
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _set_modules(db_session, **states):
    """Shared by TestPurchasingDocumentsDoNotShowIt below -- not autouse, since
    the rest of this file's tests (TestTheColumn, TestAProductCanExistWithoutACode,
    TestTheProductScreens) neither need nor expect purchase_orders/purchase_requests
    to be forced on."""
    from app.utils.cache_helpers import clear_module_config_cache
    for key, on in states.items():
        AppSettings.set_setting(f'module_enabled:{key}', '1' if on else '0')
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture
def products_module_enabled(db_session):
    """Enable the products module for tests that need it."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


class TestTheColumn:

    def test_code_is_optional(self):
        assert Product.__table__.c.code.nullable is True

    def test_code_keeps_its_unique_index(self):
        """The reversible half of the change. Dropping this would let duplicate
        codes in among the 555 already recorded, which no later step could undo."""
        assert Product.__table__.c.code.unique is True

    def test_name_did_not_become_unique(self):
        """CONTROL. The owner asked for optional-and-hidden; a new NOT NULL or
        UNIQUE constraint elsewhere is not part of that."""
        assert not Product.__table__.c.name.unique

    def test_customer_code_is_untouched(self):
        """A different field -- the CUSTOMER's own SKU. Easy to catch in a sweep
        for the word 'code' and delete by accident."""
        assert 'customer_code' in {c.key for c in Product.__table__.columns}


class TestAProductCanExistWithoutACode:

    def test_it_saves(self, db_session):
        p = Product(code=None, name='CODELESS ITEM', is_active=True)
        db_session.add(p)
        db_session.commit()
        assert p.id is not None
        assert p.code is None

    def test_two_of_them_can_coexist(self, db_session):
        """THE reason the unique index is safe to keep: NULLs do not collide."""
        db_session.add(Product(code=None, name='CODELESS ONE', is_active=True))
        db_session.add(Product(code=None, name='CODELESS TWO', is_active=True))
        db_session.commit()
        assert Product.query.filter(Product.code.is_(None)).count() == 2

    def test_a_duplicate_REAL_code_is_still_refused(self, db_session):
        """CONTROL for the two tests above: making NULLs legal must not make
        duplicate codes legal. The 555 existing codes stay unique."""
        from sqlalchemy.exc import IntegrityError
        db_session.add(Product(code='RM-DUP-1', name='FIRST', is_active=True))
        db_session.commit()
        db_session.add(Product(code='RM-DUP-1', name='SECOND', is_active=True))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestTheProductScreens:
    """The owner's rule is that the code is not visible ANYWHERE in the app, and
    the product's own screens are where it was most prominent."""

    def _login(self, client, user, branch):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = branch.id

    def test_the_form_does_not_offer_a_code_field(self, client, admin_user,
                                                  main_branch, db_session):
        """Scoped to the INPUT, not the word: `code` appears in this page for the
        unit-of-measure and account selects, which must keep working."""
        import re
        self._login(client, admin_user, main_branch)
        html = client.get('/products/create').data.decode()
        assert not re.search(r'<input[^>]*name="code"', html)

    def test_the_customer_code_field_survives(self, client, admin_user,
                                              main_branch, db_session):
        """CONTROL. customer_code is the CUSTOMER's own SKU -- a different field
        that stays, and the one most likely to be deleted by a careless sweep."""
        import re
        self._login(client, admin_user, main_branch)
        html = client.get('/products/create').data.decode()
        assert re.search(r'<input[^>]*name="customer_code"', html)

    def test_a_product_created_through_the_form_has_no_code(self, client, admin_user,
                                                            main_branch, db_session):
        self._login(client, admin_user, main_branch)
        # NOTE: is_active is a SelectField restricted to choices '1'/'0' (see
        # ProductForm.is_active); 'y' is not a member and fails WTForms choice
        # validation regardless of the code field, so '1' is used here instead
        # (matches every other product-form POST in this suite, e.g.
        # tests/integration/test_products_crud.py).
        client.post('/products/create', data={
            'name': 'FORM CREATED ITEM', 'is_active': '1'}, follow_redirects=True)
        p = Product.query.filter_by(name='FORM CREATED ITEM').first()
        assert p is not None, 'the form refused to save without a code'
        assert p.code is None

    def test_the_list_does_not_show_a_code_column(self, client, admin_user,
                                                  main_branch, db_session,
                                                  products_module_enabled):
        self._login(client, admin_user, main_branch)
        html = client.get('/products').data.decode()
        # Headers in this template are rendered in ALL CAPS, so the removed CODE header
        # was '<th>CODE</th>', not '<th>Code</th>'. An assertion on the wrong case
        # cannot fail and proves nothing.
        assert '<th>CODE</th>' not in html
        # Positive control: verify a header that SHOULD be present still is.
        assert '<th>NAME</th>' in html


class TestPurchasingDocumentsDoNotShowIt:
    """32 references across the purchasing area, done first at the owner's
    instruction. Each document is asserted separately so a failure names which
    one regressed.

    Only the ONE test below is marked purchase_requests (not the whole module):
    the classes above this one are about the Product screens themselves and must
    not be forced to run under a purchase-requests-only test slice, nor need
    purchase_orders/purchase_requests turned on."""

    pytestmark = [pytest.mark.purchase_requests]

    def test_the_requisition_overlay_prints_the_name_only(self, client, db_session,
                                                          admin_user, main_branch):
        """Build a requisition with a coded product, render the pre-printed
        overlay, and assert the NAME prints while the CODE does not.

        The positive half is not optional: an assertion that only checks the
        code's absence would also pass on a blank page, or on a template that
        dropped the whole product column outright."""
        from app.units_of_measure.models import UnitOfMeasure
        from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

        # purchase_requests `depends_on: ['purchase_orders']`, and both default
        # to OFF -- without this, enforce_module_access 404s the print route for
        # every user, admin included, and the positive assertion below would
        # 'pass' against a 404 page that happens not to contain the product's
        # code either, for the wrong reason. Pattern copied from
        # `p2p_modules_enabled` in tests/integration/test_p2p_preprinted_print.py.
        _set_modules(db_session, products=True, purchase_orders=True,
                     purchase_requests=True)

        uom = UnitOfMeasure(code='PC', name='Piece', is_active=True)
        db.session.add(uom)
        db.session.commit()

        # 'ZQXV-40217' is chosen so its absence is a real assertion, not an
        # accident of what else the page renders: it matches no quantity, date,
        # id, or CSS/JS token anywhere on this overlay (inline <style> and the
        # designer's own script text leak into the response -- see
        # tests/integration/test_so_signatory_fields.py:239 -- so a short or
        # generic value like 'P1' or 'BOX' could pass incidentally).
        product = Product(code='ZQXV-40217', name='Retired-Code Test Widget',
                          is_active=True, default_unit_of_measure_id=uom.id)
        db.session.add(product)
        db.session.commit()

        pr = PurchaseRequest(pr_number='RCODE-001', request_date=date(2026, 9, 9),
                             date_needed=date(2026, 9, 20), reason='Stock replenishment',
                             status='approved', branch_id=main_branch.id)
        pr.line_items.append(PurchaseRequestItem(
            line_number=1, description='widget', quantity=Decimal('5'),
            product_id=product.id, unit_of_measure_id=uom.id))
        db.session.add(pr)
        db.session.commit()

        AppSettings.set_setting('pr_print_form', 'preprinted')
        db_session.commit()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/purchase-requests/{pr.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Control: the overlay itself rendered, and not e.g. a redirect to the
        # standard 'current' form or a module-gate refusal -- either of which
        # would also lack the code, but for a reason unrelated to this fix.
        assert 'id="ppCanvas"' in body, 'the pre-printed overlay did not render'
        assert product.name in body
        assert product.code not in body

    def test_the_requisition_form_picker_lists_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """The requisition's OWN data-entry screen, not the print overlay.

        Asserted on the DISPLAY EXPRESSION in the page's script rather than on
        the code's value, and deliberately so: the picker is built in the
        browser from `PRODUCTS = {{ products | tojson }}`, and that payload is
        `Product.to_dict()`, which still carries `code` (Task 5's territory).
        The value is therefore still IN the body; what must be gone is the code
        being rendered into the option label.

        Why this mattered: the label was `escHtml(p.code) + ': ' + escHtml(p.name)`,
        and escHtml does `String(s)`. Since the code became optional, every new
        product carries None -> null -> the buyer read "null: Widget"."""
        _set_modules(db_session, products=True, purchase_orders=True,
                     purchase_requests=True)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get('/purchase-requests/create').data.decode()

        # Control: the line-item script rendered at all, so the two assertions
        # below are about the label and not about an empty or refused page.
        assert 'function productOptions(' in body

        assert 'escHtml(p.code)' not in body
        assert "p.code + ': '" not in body
        # Positive pair: the name IS still what the option shows.
        assert 'escHtml(p.name)' in body

    def test_the_quick_add_modal_does_not_ask_for_a_code(
            self, client, db_session, admin_user, main_branch):
        """The shared "+ Add Product" modal, asserted through the requisition
        form that includes it.

        It carried a REQUIRED `Code *` input. ProductForm no longer has a `code`
        field, so WTForms discarded whatever was typed -- the app was demanding a
        value from the user and then throwing it away, which is the plainest
        possible violation of "the user should not have to supply a code".

        The modal is shared by eight transaction forms (requisitions, orders,
        receipts, AP, CDV, quotations, sales orders and invoices), so this one
        assertion stands in for all of them; the requisition form is simply the
        one this task owns."""
        _set_modules(db_session, products=True, purchase_orders=True,
                     purchase_requests=True)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get('/purchase-requests/create').data.decode()

        # Control: the modal rendered at all, so the absence below is real.
        assert 'id="pqa_name"' in body, 'the quick-add modal did not render'

        assert 'id="pqa_code"' not in body
        assert 'name="code"' not in body

    def test_the_purchase_order_overlay_prints_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """Task 4: the order's OWN pre-printed overlay, not the requisition's.

        Same shape as test_the_requisition_overlay_prints_the_name_only above --
        build a PO with a coded product, render the pre-printed overlay, and
        assert the NAME prints while the CODE does not. The positive half is not
        optional: an assertion that only checks the code's absence would also
        pass on a blank page.

        Scoped to the line-items band (`pp-lineitems`), not the whole page: the
        overlay draws several independently-positioned column stacks, and other
        bands / the designer's own inline <style> and script text can contain
        incidental substrings unrelated to this fix (see
        tests/integration/test_so_signatory_fields.py:239 and
        test_po_overlay_grouped_render.py's `_columns` helper, which slices the
        same way for the same reason)."""
        from app.vendors.models import Vendor
        from app.units_of_measure.models import UnitOfMeasure
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

        _set_modules(db_session, products=True, purchase_orders=True)
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()

        vendor = Vendor(code='V-PO-CODE', name='ACME Trading', is_active=True)
        uom = UnitOfMeasure(code='PC', name='Piece', is_active=True)
        db.session.add_all([vendor, uom])
        db.session.commit()

        # 'ZQXV-40217' matches no quantity, date, id, or CSS/JS token anywhere on
        # this overlay -- see the requisition overlay test above for why a short
        # or generic value would pass incidentally even after this fix.
        product = Product(code='ZQXV-40217', name='Retired-Code Test Widget',
                          is_active=True, default_unit_of_measure_id=uom.id)
        db.session.add(product)
        db.session.commit()

        po = PurchaseOrder(po_number='PO-RCODE-001', order_date=date(2026, 9, 9),
                           vendor_id=vendor.id, branch_id=main_branch.id,
                           status='approved')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='widget', quantity=Decimal('5'),
            unit_price=Decimal('10.00'), amount=Decimal('50.00'),
            line_total=Decimal('50.00'), product_id=product.id,
            unit_of_measure_id=uom.id))
        db.session.add(po)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/purchase-orders/{po.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'id="ppCanvas"' in body, 'the pre-printed overlay did not render'

        band = body[body.index('class="pp-lineitems"'):]
        assert product.name in band
        assert product.code not in band

    def test_the_purchase_order_form_picker_lists_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """Task 4: the PO's OWN data-entry screen -- the highest-value part of
        this task, because it is a SECOND bug the requisition fix (Task 3,
        commit f1e6fb07) did not cover.

        `productOptions()` and the "+ Add Product" onSelect handler built their
        label from `escHtml(p.code) + ': ' + escHtml(p.name)` / `p.code + ': ' +
        p.name`. escHtml does `String(s)`, and since the code became optional
        every product created through the UI now carries None -> null, so the
        line-item dropdown read literally "null: Widget" on the order's main
        data-entry screen.

        Asserted on the DISPLAY EXPRESSIONS, not the code's value: PRODUCTS is
        built from `Product.to_dict()` (via `_common_form_ctx()`), which still
        CARRIES the code -- that payload is Task 5's territory -- so the value
        legitimately remains in the body; what must be gone is the code being
        rendered into either option label."""
        _set_modules(db_session, products=True, purchase_orders=True)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get('/purchase-orders/create').data.decode()

        # Control: the line-item script rendered at all, so the assertions
        # below are about the label and not about an empty or refused page.
        assert 'function productOptions(' in body

        assert 'escHtml(p.code)' not in body
        assert "p.code + ': '" not in body
        # Positive pair: the name IS still what both option labels show.
        assert 'escHtml(p.name)' in body

    def test_the_receipt_picker_shows_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """Task 5: the receipt's OWN data-entry screen and its "Pull from
        Purchase Orders" picker.

        Both surfaces are built from ONE server-side row dict,
        `_po_lines_payload()` (app/receiving_reports/views.py) -- the grid's
        `PO_LINES`/`RR_LINE_INDEX` and the picker modal's `/open-lines` JSON
        share it. It is not named in the Task 5 brief's file list; found by
        grepping app/receiving_reports/ for `.code\\b` rather than the narrower
        `product_code` search, and confirmed as the payload both display sites
        actually read from.

        The grid itself renders empty until a vendor is picked client-side
        (create() seeds `po_lines` from an empty `eligible` list when no vendor
        is selected -- see _eligible_purchase_orders), so the picker's real
        data source, /open-lines, is hit directly rather than scraped out of
        the create page's initial HTML."""
        from app.vendors.models import Vendor
        from app.units_of_measure.models import UnitOfMeasure
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

        _set_modules(db_session, products=True, purchase_orders=True,
                     receiving_reports=True)

        vendor = Vendor(code='V-RR-CODE', name='ACME Trading', is_active=True)
        uom = UnitOfMeasure(code='PC', name='Piece', is_active=True)
        db.session.add_all([vendor, uom])
        db.session.commit()

        # 'ZQXV-63820' matches no quantity, date, id, or CSS/JS token anywhere
        # on this page -- see the requisition overlay test above for why a
        # short or generic value would pass incidentally even after this fix.
        product = Product(code='ZQXV-63820', name='Retired-Code Test Widget',
                          is_active=True, default_unit_of_measure_id=uom.id)
        db.session.add(product)
        db.session.commit()

        po = PurchaseOrder(po_number='PO-RRCODE-001', order_date=date(2026, 9, 9),
                           vendor_id=vendor.id, vendor_name=vendor.name,
                           branch_id=main_branch.id, status='approved')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='widget', quantity=Decimal('5'),
            unit_price=Decimal('10.00'), amount=Decimal('50.00'),
            line_total=Decimal('50.00'), product_id=product.id,
            unit_of_measure_id=uom.id))
        db.session.add(po)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id

        # The picker's actual data source.
        resp = client.get(f'/receiving-reports/open-lines?vendor_id={vendor.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['lines'], 'no open lines returned -- the fixture PO is not eligible'
        row = data['lines'][0]
        assert row['product_name'] == product.name
        assert 'product_code' not in row

        # Control: the create page's line-item script rendered at all, so the
        # absence assertions below are about the display code, not a blank or
        # refused page.
        body = client.get('/receiving-reports/create').data.decode()
        assert 'function rrRowHtml(' in body, 'the line-item script did not render'

        assert 'product_code' not in body
        # Positive pair: the name IS still what the grid row and the picker
        # row both show.
        assert 'r.product_name' in body

    def test_the_stock_journal_entry_describes_the_product_by_name(
            self, db_session, branch_main, admin_user, product_tracked,
            vl_vendor, make_account):
        """Task 5's one non-cosmetic change: stock_posting writes the product
        into the JOURNAL ENTRY's line description -- a permanent accounting
        record, not a screen. Approving a receipt of a tracked product must
        now describe it by name.

        Modeled on tests/integration/test_receiving_report_stock_posting.py,
        which already assigns the inventory and GRNI control accounts through
        get_control_account() rather than a hardcoded GL code."""
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        from app.receiving_reports.stock_posting import post_rr_receipt
        from app.posting.control_accounts import get_control_account

        make_account('1401')
        AppSettings.set_setting('inventory_account_code', '1401', updated_by='test')
        make_account('2015')
        AppSettings.set_setting('grni_account_code', '2015', updated_by='test')
        db_session.commit()

        po = PurchaseOrder(branch_id=branch_main.id, po_number='PO-RRNAME-0001',
                           order_date=date(2026, 7, 21), vendor_id=vl_vendor.id,
                           vendor_name=vl_vendor.name, status='approved',
                           vat_treatment='inclusive')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description=product_tracked.name,
            product_id=product_tracked.id, quantity=Decimal('10'),
            unit_price=Decimal('11.20'), vat_rate=Decimal('12.00'),
            amount=Decimal('112.00')))
        po.calculate_totals()
        db.session.add(po)
        db.session.commit()

        rr = ReceivingReport(branch_id=branch_main.id, rr_number='RR-RRNAME-0001',
                             receipt_date=date(2026, 7, 21), vendor_id=po.vendor_id,
                             vendor_name=po.vendor_name, status='draft')
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=po.line_items[0].id,
            product_id=po.line_items[0].product_id,
            received_quantity=Decimal('10')))
        db.session.add(rr)
        db.session.commit()

        post_rr_receipt(rr, admin_user)
        db.session.commit()

        assert rr.journal_entry_id is not None
        inv_account = get_control_account('inventory')
        grni_account = get_control_account('grni')
        dr = next(l for l in rr.journal_entry.lines if l.account_id == inv_account.id)
        cr = next(l for l in rr.journal_entry.lines if l.account_id == grni_account.id)

        assert dr.description == f'{product_tracked.name} received'
        assert cr.description == f'{product_tracked.name} accrued'
        # Discriminating half: the OLD text is gone, not merely "a" new text
        # present alongside it.
        assert product_tracked.code not in dr.description
        assert product_tracked.code not in cr.description

    def test_a_previously_posted_je_line_keeps_its_original_code_based_text(
            self, db_session, branch_main, admin_user, product_tracked,
            vl_vendor, make_account):
        """Non-retroactivity proof for the change above. Journal entries are
        permanent accounting records -- there is no edit route on one, only
        reversing entries (app/accounts_payable/views.py:1677's rule applies
        here too) -- so a line written by the OLD, code-based stock_posting.py
        must keep reading exactly as it was written.

        This directly inserts a JE line carrying the pre-change text (as a real
        pre-change `post_rr_receipt` would have written it), then exercises the
        CHANGED code path on a separate receipt, and re-reads the original line
        to prove nothing rewrote it. Nothing in this change touches existing
        rows -- no migration, no backfill -- and this test is what stands in
        for that absence."""
        from app.journal_entries.models import JournalEntry, JournalEntryLine
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        from app.receiving_reports.stock_posting import post_rr_receipt
        from app.posting.control_accounts import get_control_account
        from app.utils import ph_now

        inv_account = make_account('1401')
        AppSettings.set_setting('inventory_account_code', '1401', updated_by='test')
        make_account('2015')
        AppSettings.set_setting('grni_account_code', '2015', updated_by='test')
        db_session.commit()

        old_text = f'{product_tracked.code} received'   # what a PRE-change post_rr_receipt wrote
        old_je = JournalEntry(
            entry_number='JE-OLDTXT-0001', entry_date=date(2026, 7, 1),
            description=f'Receiving Report RR-OLDTXT-0000 — {vl_vendor.name}',
            reference='RR-OLDTXT-0000', entry_type='receiving_report',
            branch_id=branch_main.id, created_by_id=admin_user.id, status='posted',
            posted_by_id=admin_user.id, posted_at=ph_now(), is_balanced=True,
            total_debit=Decimal('100.00'), total_credit=Decimal('100.00'))
        db.session.add(old_je)
        db.session.flush()
        old_line = JournalEntryLine(
            entry_id=old_je.id, line_number=1, account_id=inv_account.id,
            description=old_text, debit_amount=Decimal('100.00'), credit_amount=Decimal('0.00'))
        db.session.add(old_line)
        db.session.commit()
        old_line_id = old_line.id

        # Exercise the CHANGED code path -- a separate, new receipt.
        po = PurchaseOrder(branch_id=branch_main.id, po_number='PO-OLDTXT-0001',
                           order_date=date(2026, 7, 21), vendor_id=vl_vendor.id,
                           vendor_name=vl_vendor.name, status='approved',
                           vat_treatment='inclusive')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description=product_tracked.name,
            product_id=product_tracked.id, quantity=Decimal('10'),
            unit_price=Decimal('11.20'), vat_rate=Decimal('12.00'),
            amount=Decimal('112.00')))
        po.calculate_totals()
        db.session.add(po)
        db.session.commit()
        rr = ReceivingReport(branch_id=branch_main.id, rr_number='RR-OLDTXT-0001',
                             receipt_date=date(2026, 7, 21), vendor_id=po.vendor_id,
                             vendor_name=po.vendor_name, status='draft')
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=po.line_items[0].id,
            product_id=po.line_items[0].product_id,
            received_quantity=Decimal('10')))
        db.session.add(rr)
        db.session.commit()
        post_rr_receipt(rr, admin_user)
        db.session.commit()

        # The NEW receipt's own lines use the name (control -- proves the code
        # path really did change, so the assertion below is about permanence,
        # not a fix that silently never landed).
        new_descriptions = [l.description for l in rr.journal_entry.lines]
        assert f'{product_tracked.name} received' in new_descriptions

        # The OLD line, re-read from the database, is untouched.
        reread = db.session.get(JournalEntryLine, old_line_id)
        assert reread.description == old_text, (
            'a pre-existing journal entry line was rewritten -- posted '
            'documents must never change')

    # -- Task 6: payables, disbursements and purchase memos ---------------------
    #
    # Found by grepping app/accounts_payable, app/cash_disbursements,
    # app/purchase_memos and app/purchase_billing.py for the WIDE `.code\b`
    # pattern (not the brief's narrower `product_code`) and classifying every
    # hit by hand -- Account/UOM/Vendor/WithholdingTax/VATCategory codes stay;
    # only Product.code is retired. The same "null: Widget" defect Task 3 fixed
    # on the requisition form (f1e6fb07) and Task 4 on the order form
    # (927044e6) was present on BOTH the AP voucher form and the CDV form, and
    # a THIRD, DIFFERENT live bug -- a real "CODE: Name" label, not a null one
    # -- was found in app/static/js/purchase_memos_form.js, fed by
    # AccountsPayableItem.to_dict()'s now-retired 'product_code' key. None of
    # these three were named in the Task 6 brief's file list.

    def test_the_ap_voucher_form_picker_lists_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """The AP voucher's OWN data-entry screen.

        `products.map(...)` built its option label from
        `${escHtml(p.code)}: ${escHtml(p.name)}`, and the "+ Add Product"
        onSelect handler from `escHtml(p.code) + ': ' + escHtml(p.name)`.
        escHtml does `String(s)`, so since the code became optional every
        product created through the UI carries None -> null -> the bookkeeper
        read "null: Widget" on the voucher's main data-entry screen.

        Asserted on the DISPLAY EXPRESSIONS, not a code's value: PRODUCTS is
        built from Product.to_dict(), which still CARRIES the code (Task 5's
        territory) -- what must be gone is the code being rendered into either
        option label."""
        _set_modules(db_session, products=True)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get('/accounts-payable/create').data.decode()

        # Control: the line-item script rendered at all.
        assert 'function addLineItem(' in body

        assert 'escHtml(p.code)' not in body
        assert "p.code) + ': '" not in body
        # Positive pair: the name IS still what both option labels show.
        assert 'escHtml(p.name)' in body

    def test_the_ap_voucher_overlay_prints_the_name_only(
            self, client, db_session, admin_user, main_branch, make_account):
        """The AP voucher's own pre-printed overlay.

        Same shape as the requisition/order overlay tests above -- build a
        posted AP voucher with a coded product line, render the pre-printed
        overlay, and assert the NAME prints while the CODE does not. Scoped to
        the line-items band, not the whole page, for the same reason as the PO
        overlay test (other bands / the designer's own inline <style> and
        script text can contain incidental substrings)."""
        from app.vendors.models import Vendor
        from app.settings import AppSettings
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem

        _set_modules(db_session, products=True)
        AppSettings.set_setting('ap_print_form', 'preprinted')
        db_session.commit()

        vendor = Vendor(code='V-AP-CODE', name='ACME Trading', is_active=True)
        db.session.add(vendor)
        account = make_account('50199')
        db.session.commit()

        # 'ZQXV-71930' matches no quantity, date, id, or CSS/JS token anywhere on
        # this overlay -- see the requisition overlay test above for why a short
        # or generic value would pass incidentally even after this fix.
        product = Product(code='ZQXV-71930', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-RCODE-001',
                              ap_date=date(2026, 9, 9), due_date=date(2026, 10, 9),
                              payee_type='vendor', payee_id=vendor.id,
                              vendor_id=vendor.id, vendor_name=vendor.name,
                              status='posted')
        ap.line_items.append(AccountsPayableItem(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(ap)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'id="ppCanvas"' in body, 'the pre-printed overlay did not render'

        band = body[body.index('class="pp-lineitems'):]
        assert product.name in band
        assert product.code not in band

    def test_the_ap_voucher_print_page_shows_the_name_only(
            self, client, db_session, admin_user, main_branch, make_account):
        """The AP voucher's plain (non-preprinted) print page -- a separate
        template from the overlay above, with its own `item.product.code`
        reference."""
        from app.vendors.models import Vendor
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem

        _set_modules(db_session, products=True)

        vendor = Vendor(code='V-AP-CODE-2', name='ACME Trading', is_active=True)
        db.session.add(vendor)
        account = make_account('50198')
        db.session.commit()

        product = Product(code='ZQXV-71931', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-RCODE-002',
                              ap_date=date(2026, 9, 9), due_date=date(2026, 10, 9),
                              payee_type='vendor', payee_id=vendor.id,
                              vendor_id=vendor.id, vendor_name=vendor.name,
                              status='posted')
        ap.line_items.append(AccountsPayableItem(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(ap)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get(f'/accounts-payable/{ap.id}/print').data.decode()
        # Control: the line-items table rendered with the product column.
        assert '<th style="width:14%">Product</th>' in body
        assert product.name in body
        assert product.code not in body

    def test_the_ap_voucher_detail_page_shows_the_name_only(
            self, client, db_session, admin_user, main_branch, make_account):
        """The AP voucher's own detail page."""
        from app.vendors.models import Vendor
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem

        _set_modules(db_session, products=True)

        vendor = Vendor(code='V-AP-CODE-3', name='ACME Trading', is_active=True)
        db.session.add(vendor)
        account = make_account('50197')
        db.session.commit()

        product = Product(code='ZQXV-71932', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-RCODE-003',
                              ap_date=date(2026, 9, 9), due_date=date(2026, 10, 9),
                              payee_type='vendor', payee_id=vendor.id,
                              vendor_id=vendor.id, vendor_name=vendor.name,
                              status='posted')
        ap.line_items.append(AccountsPayableItem(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(ap)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get(f'/accounts-payable/{ap.id}').data.decode()
        # Control: the detail page's Journal / line-items section rendered.
        assert product.name in body
        assert product.code not in body

    def test_the_cdv_form_picker_lists_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """The CDV's OWN data-entry screen -- same defect class as the AP
        voucher form above, in a separate template."""
        _set_modules(db_session, products=True)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get('/cash-disbursements/create').data.decode()

        assert 'function addExpenseLine(' in body

        assert 'escHtml(p.code)' not in body
        assert "p.code) + ': '" not in body
        assert 'escHtml(p.name)' in body

    def test_the_cdv_overlay_prints_the_name_only(
            self, client, db_session, admin_user, main_branch, make_account):
        """The CDV's own pre-printed overlay. Same shape as the AP overlay
        test above."""
        from app.vendors.models import Vendor
        from app.settings import AppSettings
        from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

        _set_modules(db_session, products=True)
        AppSettings.set_setting('cd_print_form', 'preprinted')
        db_session.commit()

        vendor = Vendor(code='V-CD-CODE', name='ACME Trading', is_active=True)
        db.session.add(vendor)
        account = make_account('60199')
        cash = make_account('10199')
        db.session.commit()

        product = Product(code='ZQXV-82041', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        cdv = CashDisbursementVoucher(
            cash_account_id=cash.id, branch_id=main_branch.id,
            cdv_number='CDV-RCODE-001', cdv_date=date(2026, 9, 9),
            vendor_id=vendor.id, vendor_name=vendor.name, status='posted')
        cdv.expense_lines.append(CDVExpenseLine(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(cdv)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/cash-disbursements/{cdv.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'id="ppCanvas"' in body, 'the pre-printed overlay did not render'

        band = body[body.index('class="pp-lineitems'):]
        assert product.name in band
        assert product.code not in band

    def test_the_cdv_print_page_shows_the_name_only(
            self, client, db_session, admin_user, main_branch, make_account):
        """The CDV's plain (non-preprinted) print page -- a separate template
        from the overlay above, with its own `exp.product.code` reference."""
        from app.vendors.models import Vendor
        from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

        _set_modules(db_session, products=True)

        vendor = Vendor(code='V-CD-CODE-2', name='ACME Trading', is_active=True)
        db.session.add(vendor)
        account = make_account('60198')
        cash = make_account('10198')
        db.session.commit()

        product = Product(code='ZQXV-82042', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        cdv = CashDisbursementVoucher(
            cash_account_id=cash.id, branch_id=main_branch.id,
            cdv_number='CDV-RCODE-002', cdv_date=date(2026, 9, 9),
            vendor_id=vendor.id, vendor_name=vendor.name, status='posted')
        cdv.expense_lines.append(CDVExpenseLine(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(cdv)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get(f'/cash-disbursements/{cdv.id}/print').data.decode()
        assert '<th>Product</th>' in body
        assert product.name in body
        assert product.code not in body

    def test_the_cdv_detail_page_shows_the_name_only(
            self, client, db_session, admin_user, main_branch, make_account):
        """The CDV's own detail page."""
        from app.vendors.models import Vendor
        from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine

        _set_modules(db_session, products=True)

        vendor = Vendor(code='V-CD-CODE-3', name='ACME Trading', is_active=True)
        db.session.add(vendor)
        account = make_account('60197')
        cash = make_account('10197')
        db.session.commit()

        product = Product(code='ZQXV-82043', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        cdv = CashDisbursementVoucher(
            cash_account_id=cash.id, branch_id=main_branch.id,
            cdv_number='CDV-RCODE-003', cdv_date=date(2026, 9, 9),
            vendor_id=vendor.id, vendor_name=vendor.name, status='posted')
        cdv.expense_lines.append(CDVExpenseLine(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(cdv)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        body = client.get(f'/cash-disbursements/{cdv.id}').data.decode()
        assert product.name in body
        assert product.code not in body

    def _build_debit_memo(self, db_session, main_branch, vendor_code, account_code,
                          product_code, ap_number):
        """Shared builder for the two purchase-memo document tests below: one
        posted AP bill with a coded product line, and one posted Vendor Debit
        Memo referencing it with the SAME product on its own line."""
        from app.vendors.models import Vendor
        from app.accounts.models import Account
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
        from app.purchase_memos.models import PurchaseMemo, PurchaseMemoItem, \
            generate_purchase_memo_number

        vendor = Vendor(code=vendor_code, name='ACME Trading', is_active=True)
        account = Account(code=account_code, name=f'Acct {account_code}',
                          account_type='Expense', normal_balance='Debit',
                          is_active=True)
        db.session.add_all([vendor, account])
        db.session.commit()

        product = Product(code=product_code, name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        bill = AccountsPayable(
            branch_id=main_branch.id, ap_number=ap_number,
            ap_date=date(2026, 9, 9), due_date=date(2026, 10, 9),
            payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
            vendor_name=vendor.name, status='posted')
        item = AccountsPayableItem(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id)
        bill.line_items.append(item)
        db.session.add(bill)
        db.session.commit()

        memo = PurchaseMemo(
            memo_type='debit', memo_number=generate_purchase_memo_number('debit'),
            vendor_id=vendor.id, accounts_payable_id=bill.id,
            original_ap_number=bill.ap_number, vendor_name=vendor.name,
            branch_id=main_branch.id, memo_date=bill.ap_date, destination='ap',
            reason='return', status='posted')
        db.session.add(memo)
        db.session.flush()
        memo.line_items.append(PurchaseMemoItem(
            purchase_memo_id=memo.id, accounts_payable_item_id=item.id,
            line_number=1, amount=Decimal('112.00'), line_total=Decimal('112.00'),
            vat_category='V12', vat_rate=Decimal('12.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.commit()
        return memo, product

    def test_the_vendor_debit_memo_detail_shows_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """The Vendor Debit Memo's own detail page."""
        _set_modules(db_session, products=True, vendor_debit_memos=True)
        memo, product = self._build_debit_memo(
            db_session, main_branch, 'V-PM-CODE-1', '50196', 'ZQXV-93152',
            'AP-PMCODE-001')

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/vendor-debit-memos/{memo.id}')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Control: the line-items table rendered at all.
        assert memo.memo_number in body
        assert product.name in body
        assert product.code not in body

    def test_the_vendor_debit_memo_print_page_shows_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """The Vendor Debit Memo's own print page -- a separate template from
        the detail page above."""
        _set_modules(db_session, products=True, vendor_debit_memos=True)
        memo, product = self._build_debit_memo(
            db_session, main_branch, 'V-PM-CODE-2', '50195', 'ZQXV-93153',
            'AP-PMCODE-002')

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/vendor-debit-memos/{memo.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert memo.memo_number in body
        assert product.name in body
        assert product.code not in body

    def test_the_debit_memo_line_grid_lists_the_name_only(
            self, client, db_session, admin_user, main_branch):
        """The Vendor Debit Memo CREATE screen's AP-bill line grid
        (app/static/js/purchase_memos_form.js), fed by
        `/vendor-debit-memos/ap-lines/<ap_id>`.

        This is a DIFFERENT bug shape from the "null: Widget" defects above: the
        label was `r.product_code ? r.product_code + ': ' + r.product_name :
        (r.product_name || '(no product)')` -- a real "CODE: Name" join that
        fires whenever a bill line actually HAS a code (not just when it is
        null), so it slipped past the `escHtml(p.code)` grep signature entirely.
        Not named in the Task 6 brief's file list; found by tracing
        AccountsPayableItem.to_dict()'s 'product_code' key (retired alongside
        this) to its one real consumer.

        Asserted on BOTH the live JSON payload (the actual data source) and the
        static JS file (the actual rendering code) -- the JSON assertion alone
        would pass even if the label expression still preferred a code that
        merely never arrives."""
        from app.vendors.models import Vendor
        from app.accounts.models import Account
        from app.accounts_payable.models import AccountsPayable, AccountsPayableItem

        _set_modules(db_session, products=True, vendor_debit_memos=True)

        vendor = Vendor(code='V-PM-CODE-3', name='ACME Trading', is_active=True)
        account = Account(code='50194', name='Acct 50194', account_type='Expense',
                          normal_balance='Debit', is_active=True)
        db.session.add_all([vendor, account])
        db.session.commit()

        # 'ZQXV-93154' matches no quantity, date, id, or CSS/JS token anywhere on
        # this page -- see the requisition overlay test above for why a short or
        # generic value would pass incidentally even after this fix.
        product = Product(code='ZQXV-93154', name='Retired-Code Test Widget',
                          is_active=True)
        db.session.add(product)
        db.session.commit()

        bill = AccountsPayable(
            branch_id=main_branch.id, ap_number='AP-PMCODE-003',
            ap_date=date(2026, 9, 9), due_date=date(2026, 10, 9),
            payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
            vendor_name=vendor.name, status='posted')
        bill.line_items.append(AccountsPayableItem(
            line_number=1, description='widget', amount=Decimal('112.00'),
            vat_rate=Decimal('12.00'), vat_category='V12', vat_nature='regular',
            line_total=Decimal('112.00'), vat_amount=Decimal('12.00'),
            account_id=account.id, product_id=product.id))
        db.session.add(bill)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = main_branch.id

        # The picker's actual data source.
        resp = client.get(f'/vendor-debit-memos/ap-lines/{bill.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['lines'], 'no lines returned -- the fixture bill is not eligible'
        row = data['lines'][0]
        assert row['product_name'] == product.name
        assert 'product_code' not in row

        # The actual rendering code: served as a static asset, not scraped out
        # of an inline <script> block.
        js_resp = client.get('/static/js/purchase_memos_form.js')
        assert js_resp.status_code == 200
        js_body = js_resp.data.decode()
        assert 'r.product_code' not in js_body
        assert 'r.product_name' in js_body
