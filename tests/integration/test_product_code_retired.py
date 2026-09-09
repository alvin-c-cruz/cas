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
