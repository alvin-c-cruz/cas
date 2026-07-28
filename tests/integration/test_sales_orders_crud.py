"""Integration tests — Sales Orders create/edit, uniqueness, audit."""
import json
import re
import datetime
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.customers.models import Customer
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Enable the optional sales_orders module for all SO tests.

    Also enables job_order_slips: print_job_order's endpoint prefix is registered
    under the job_order_slips module key (Task 5), not sales_orders, so the
    company-level module_enabled() gate -- which applies to every role including
    admin -- would otherwise 404 this file's print_job_order tests.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:job_order_slips', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


# ── helpers ──────────────────────────────────────────────────────────────────

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    # Flask-Login caches the loaded user on flask.g for the life of the app
    # context. The `app` fixture keeps ONE app context open for the whole test
    # function, and Flask's test client reuses that same context per request
    # rather than pushing a fresh one -- so g._login_user (and therefore
    # current_user) would otherwise stay stale across a mid-test user switch
    # (log in as accountant, do something, log in as staff: current_user would
    # still resolve to accountant on the next request). Bust the cache here so
    # every _login() call is guaranteed to take effect on the very next request.
    import flask
    flask.g.pop('_login_user', None)


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _customer(db_session):
    c = Customer(code='ACME01', name='Acme', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _product(db_session, code='WIDGET', name='Widget'):
    from app.units_of_measure.models import UnitOfMeasure
    from app.products.models import Product
    uom = UnitOfMeasure.query.filter_by(code='pcs').first()
    if uom is None:
        uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
        db_session.add(uom); db_session.commit()
    p = Product(code=code, name=name, default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('100.00'), is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _enable_products(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    db_session.commit()
    clear_module_config_cache()


def _delivery_site(db_session, customer, name='WAREHOUSE A', is_active=True):
    from app.customers.models import CustomerDeliverySite
    site = CustomerDeliverySite(customer_id=customer.id, name=name, is_active=is_active)
    db_session.add(site)
    db_session.commit()
    return site


def _line_items_row(html, line_number):
    """Return the raw HTML of the single <tr> for a given line_number within the
    Sales Order line-items table.

    detail.html and print.html each contain exactly one <tbody> (the line-items
    table) -- scoping the search to it avoids ever matching a header/footer row.
    """
    tbody_html = html[html.index('<tbody>'):html.index('</tbody>')]
    rows = re.findall(r'<tr>.*?</tr>', tbody_html, re.DOTALL)
    marker = f'<td>{line_number}</td>'
    matches = [row for row in rows if marker in row]
    assert len(matches) == 1, (
        f'expected exactly one line-items row for line_number={line_number}, '
        f'found {len(matches)}'
    )
    return matches[0]


def _delivery_cells(row_html, trailing_extra=0):
    """Return (delivery_date_cell, delivery_site_cell) -- the last two <td>
    cells of a line-items row, before any trailing columns added after Delivery
    Site (e.g. detail.html's Status column, Task 9 -- pass trailing_extra=1 to
    skip it). Delivery Date and Delivery Site are the 8th and 9th columns in
    both detail.html and print.html; print.html has no columns after them."""
    cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
    if trailing_extra:
        cells = cells[:-trailing_extra]
    return cells[-2].strip(), cells[-1].strip()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_create_sales_order_persists_and_audits(client, db_session, admin_user, main_branch):
    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0001', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0001').first()
    assert so is not None
    assert so.status == 'draft'
    assert so.total_amount == Decimal('200.00')
    # no journal entry — SalesOrder is operational only
    assert not hasattr(so, 'journal_entry_id') or so.journal_entry_id is None
    assert AuditLog.query.filter_by(module='sales_orders', action='create').count() >= 1


def test_create_sales_order_persists_delivery_date_and_site(client, db_session, admin_user, main_branch):
    """Task 5: a line's delivery_date/delivery_site_id round-trip through the full
    create POST, via _parse_and_attach_so_lines."""
    c = _customer(db_session)
    p = _product(db_session)
    site = _delivery_site(db_session, c)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0',
                         'delivery_date': '2026-08-15', 'delivery_site_id': str(site.id)}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0099', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0099').first()
    assert so is not None
    line = so.line_items[0]
    assert line.delivery_date == datetime.date(2026, 8, 15)
    assert line.delivery_site_id == site.id


def test_create_sales_order_persists_wt_id(client, db_session, admin_user, main_branch):
    """A WT selection on an SO line round-trips through the full create POST."""
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db_session.add(wt); db_session.commit()

    c = _customer(db_session)
    c.withholding_taxes = [wt]
    db_session.commit()
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0', 'wt_id': str(wt.id)}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0003', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0003').first()
    assert so.line_items[0].wt_id == wt.id


def test_create_sales_order_drops_foreign_customer_delivery_site(client, db_session, admin_user, main_branch):
    """A line's delivery_site_id must belong to the SO's own customer. A direct POST
    (or a stale in-memory line array) naming another customer's site must not persist
    -- silently dropped to None, matching this parser's existing tolerant style for
    other soft-reference fields (e.g. an invalid uom_id is likewise just int()'d with
    no cross-check), not a validation error that blocks the whole save."""
    customer_a = _customer(db_session)
    customer_b = Customer(code='OTHR01', name='Other Co', is_active=True)
    db_session.add(customer_b)
    db_session.commit()
    p = _product(db_session)
    foreign_site = _delivery_site(db_session, customer_b, name='OTHER WAREHOUSE')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0',
                         'delivery_date': '2026-08-15', 'delivery_site_id': str(foreign_site.id)}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0098', 'order_date': '2026-06-15',
        'customer_id': str(customer_a.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0098').first()
    assert so is not None
    line = so.line_items[0]
    assert line.delivery_site_id is None
    # delivery_date is independent of the site and is not itself a cross-reference --
    # it must survive untouched.
    assert line.delivery_date == datetime.date(2026, 8, 15)


def test_edit_sales_order_drops_foreign_customer_delivery_site_on_customer_change(
        client, db_session, admin_user, main_branch):
    """Editing a draft SO to switch its customer must not let a stale line still
    carrying the OLD customer's delivery_site_id survive -- the server, not just
    client-side JS, must re-check the site against the (new) so.customer_id."""
    customer_a = _customer(db_session)
    customer_b = Customer(code='OTHR02', name='Other Co 2', is_active=True)
    db_session.add(customer_b)
    db_session.commit()
    p = _product(db_session)
    site_a = _delivery_site(db_session, customer_a, name='ACME WAREHOUSE')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0',
                         'delivery_date': '2026-08-15', 'delivery_site_id': str(site_a.id)}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0097', 'order_date': '2026-06-15',
        'customer_id': str(customer_a.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0097').first()
    assert so.line_items[0].delivery_site_id == site_a.id

    # Now edit the SO, switching its customer to B while the line still (as a stale
    # client array would) carries customer A's site id.
    edit_lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                              'vat_category': None, 'vat_rate': '0',
                              'delivery_date': '2026-08-15', 'delivery_site_id': str(site_a.id)}])
    resp = client.post(f'/sales-orders/{so.id}/edit', data={
        'so_number': 'SO-2026-06-0097', 'order_date': '2026-06-15',
        'customer_id': str(customer_b.id), 'customer_name': 'Other Co 2',
        'payment_terms': 'Net 30', 'notes': '', 'line_items': edit_lines,
        'row_version': str(so.row_version)}, follow_redirects=True)
    assert resp.status_code == 200
    so = db.session.get(SalesOrder, so.id)
    db.session.refresh(so)
    assert so.customer_id == customer_b.id
    assert so.line_items[0].delivery_site_id is None


def test_detail_view_no_entity_leak_and_no_currency_glyph(client, db_session, admin_user, main_branch):
    """SO detail must render em-dashes as the literal glyph (never the '&#8212;'
    entity, which Jinja autoescaping leaks as literal text when it sits inside a
    {{ }} string fallback), and must show bare numbers with no peso glyph
    (no-currency-symbol convention). A line with no UOM exercises the em-dash
    fallback; a unit price exercises the money cells."""
    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0009', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0009').first()
    html = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    assert '&#8212;' not in html          # em-dash entity (leaks or clutters — use the glyph)
    assert '₱' not in html           # peso sign U+20B1


def test_so_persists_salesperson_when_employees_enabled(client, db_session, admin_user, main_branch, request):
    from app.employees.models import Employee
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    db_session.commit(); clear_module_config_cache()
    # Clear again at teardown -- see tests/unit/test_salesperson_field.py's
    # sibling fix for why this cache leak matters (an uncleared '1' here
    # can leak into any later test in the same run).
    request.addfinalizer(clear_module_config_cache)
    e = Employee(employee_no='E-9', first_name='Rey', last_name='Santos',
                 branch_id=main_branch.id, is_active=True)
    db_session.add(e); db_session.commit()
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '1', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    client.post('/sales-orders/create', data={
        'so_number': 'SO-SP-100', 'order_date': '2026-07-08', 'customer_id': str(c.id),
        'customer_name': 'Acme', 'payment_terms': 'Net 30', 'notes': '',
        'salesperson_id': str(e.id), 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-SP-100').first()
    assert so is not None and so.salesperson_id == e.id


def test_list_overdue_filter(client, db_session, admin_user, main_branch):
    """?overdue=1 narrows the SO list to confirmed orders whose expected delivery is past."""
    import datetime
    from app.utils import ph_now
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    today = ph_now().date()
    db.session.add(SalesOrder(so_number='SO-OVD-1', order_date=today, customer_id=c.id,
                              customer_name='Acme', branch_id=main_branch.id, status='confirmed',
                              expected_delivery_date=today - datetime.timedelta(days=3)))
    db.session.add(SalesOrder(so_number='SO-FUT-1', order_date=today, customer_id=c.id,
                              customer_name='Acme', branch_id=main_branch.id, status='confirmed',
                              expected_delivery_date=today + datetime.timedelta(days=30)))
    db.session.commit()
    html = client.get('/sales-orders?overdue=1').get_data(as_text=True)
    assert 'SO-OVD-1' in html
    assert 'SO-FUT-1' not in html


def test_create_form_is_product_first_no_description(client, db_session, admin_user, main_branch):
    """The SO create form is product-first: the product picker is present and there is
    no free-text line Description input anywhere in the editor JS/markup."""
    _product(db_session)
    _enable_products(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    assert 'onProductPick' in html          # product picker is present
    assert 'desc-${id}' not in html         # the description input template is gone
    assert "'description'" not in html and 'item.description' not in html


def test_line_without_product_is_rejected(client, db_session, admin_user, main_branch):
    """A real line (amount > 0) with no product must be rejected server-side and the
    SO must not persist — product is required per line."""
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': None, 'quantity': '1', 'unit_price': '50.00',
                         'vat_category': None, 'vat_rate': '0'}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0100', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'select a product' in resp.data
    assert SalesOrder.query.filter_by(so_number='SO-2026-06-0100').first() is None


def test_create_form_renders_so_number_and_line_editor(client, db_session, admin_user, main_branch):
    """GET /sales-orders/create → 200; full editor present (so_number editable, line table, add-line btn)."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    # editable so_number input
    assert b'so_number' in resp.data
    # line-item editor markers
    assert b'lineItemsTable' in resp.data
    assert b'lineItemsBody' in resp.data
    assert b'lineItemsData' in resp.data
    assert b'addLineBtn' in resp.data


def test_create_form_offers_product_and_uom_quick_add_when_module_on(client, db_session, admin_user, main_branch):
    """With the Products/UOM modules on, the SO form must render the product AND uom quick-add
    modals + scripts and the line grid's '+ Add Product' / '+ Add UOM' sentinels, so a delegate
    can inline-add master data while building an SO -- mirrors the Quotation form's existing
    wiring (test_quotations_crud.py::test_create_form_offers_product_quick_add_when_module_on).
    Browser-only surface -- assert the RENDERED form, a POST-contract test cannot see template wiring."""
    _enable_products(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data
    assert b'productQuickAddOverlay' in body     # product modal partial included
    assert b'product-quick-add.js' in body       # product quick-add JS loaded
    assert b'initProductQuickAdd' in body        # product init call present
    assert b'__add_product__' in body            # line-grid "+ Add Product" sentinel wired
    assert b'uomQuickAddOverlay' in body         # uom modal partial included
    assert b'uom-quick-add.js' in body           # uom quick-add JS loaded
    assert b'initUomQuickAdd' in body            # uom init call present
    assert b'__add_uom__' in body                # line-grid "+ Add UOM" sentinel wired


def test_create_form_renders_delivery_date_and_site_grid_columns(client, db_session, admin_user, main_branch):
    """Task 5: the line grid must show Delivery Date/Delivery Site <th> headers and wire
    the per-line hooks -- a native date input bound via updateLineItem, and a Choices-backed
    site select stored on lineChoices[id].site (mirrors lineChoices[id].uom/.prod).
    Not gated by module_enabled -- delivery sites carry no module flag."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data
    assert b'Delivery Date' in body
    assert b'Delivery Site' in body
    assert b'deliverySites' in body              # baked-in delivery sites context data
    assert b'lineChoices[id].site' in body       # per-line site Choices hook
    assert b'onDeliverySitePick' in body         # site select onchange handler wired
    assert b"type=\"date\"" in body              # native date input for delivery_date
    assert b"updateLineItem(${id}, 'delivery_date'" in body


def test_create_form_offers_delivery_site_quick_add(client, db_session, admin_user, main_branch):
    """Delivery Site quick-add modal + JS must be wired on the SO form (mirrors the
    Product/UOM quick-add pattern), with a trailing '+ Add Site' sentinel in the line grid."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data
    assert b'deliverySiteQuickAddOverlay' in body    # site quick-add modal partial included
    assert b'delivery-site-quick-add.js' in body     # site quick-add JS loaded
    assert b'initDeliverySiteQuickAdd' in body       # site quick-add init call present
    assert b'__add_site__' in body                   # line-grid "+ Add Site" sentinel wired


def test_create_form_bakes_active_delivery_sites_tagged_with_customer_id(client, db_session, admin_user, main_branch):
    """_common_form_ctx() must bake in all ACTIVE CustomerDeliverySite rows across all
    customers, each carrying its own customer_id, for client-side filtering -- same
    flat-list approach already used for products/units. Inactive sites are excluded."""
    c = _customer(db_session)
    _delivery_site(db_session, c, name='PLANT WAREHOUSE')
    _delivery_site(db_session, c, name='RETIRED SITE', is_active=False)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    assert 'PLANT WAREHOUSE' in html
    assert 'RETIRED SITE' not in html
    assert f'"customer_id": {c.id}' in html or f'"customer_id":{c.id}' in html


def test_duplicate_so_number_rejected(client, db_session, admin_user, main_branch):
    import datetime
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    db.session.add(SalesOrder(
        so_number='SO-DUP',
        order_date=datetime.date.today(),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
    ))
    db.session.commit()
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-DUP', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme',
        'payment_terms': 'Net 30',
        'notes': '', 'line_items': '[]'}, follow_redirects=True)
    # must not create a second SO with the same number
    assert SalesOrder.query.filter_by(so_number='SO-DUP').count() == 1


def test_view_sales_order_detail(client, db_session, admin_user, main_branch):
    """GET /sales-orders/<id> → 200; SO number, line product, and amount render."""
    c = _customer(db_session)
    p = _product(db_session, code='BLUE', name='Blue Widget')
    _enable_products(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    so = SalesOrder(
        so_number='SO-VIEW-0001',
        order_date=datetime.date(2026, 6, 28),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
        status='draft',
    )
    db_session.add(so)
    db_session.flush()

    line = SalesOrderItem(
        sales_order_id=so.id,
        line_number=1,
        product_id=p.id,
        quantity=Decimal('3.0000'),
        unit_price=Decimal('50.00'),
        amount=Decimal('150.00'),
        vat_rate=Decimal('0.00'),
        line_total=Decimal('150.00'),
        vat_amount=Decimal('0.00'),
    )
    so.line_items.append(line)
    so.calculate_totals()
    db_session.commit()

    resp = client.get(f'/sales-orders/{so.id}')
    assert resp.status_code == 200
    assert b'SO-VIEW-0001' in resp.data
    assert b'Blue Widget' in resp.data   # product name renders in the line
    assert b'150' in resp.data  # amount appears in the line


def test_detail_and_print_render_delivery_date_and_site_columns(client, db_session, admin_user,
                                                                  main_branch):
    """Task 6: detail.html and print.html line-items tables show the Delivery Date /
    Delivery Site columns -- header, a SET value, and the em-dash fallback when unset.

    Both lines share one product (whose own cell hardcodes an unrelated ' — '
    separator) and neither line sets a UOM (whose own fallback is independently
    '—'), so a bare `html.count('—') >= 1` on the whole page would still pass
    even if the Delivery Date/Site columns' own fallback logic were broken --
    those other columns already guarantee an em-dash on every row. To make the
    assertion provative: (1) both lines get an explicit UOM so that column
    never falls back, and (2) each line's Delivery Date/Delivery Site cells are
    located precisely (via `_line_items_row`/`_delivery_cells`, using the fixed
    9-column layout) and asserted individually, isolating the two columns under
    test from the product column's unrelated hardcoded dash. A third, mixed-state
    line (date set, site unset) covers the reviewer's partial-fallback case.
    """
    c = _customer(db_session)
    p = _product(db_session, code='DDS', name='Delivery Date Site Widget')
    site = _delivery_site(db_session, c, name='PLANT WAREHOUSE')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    so = SalesOrder(
        so_number='SO-DDS-0001',
        order_date=datetime.date(2026, 6, 28),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
        status='draft',
    )
    db_session.add(so)
    db_session.flush()

    # Every line sets its own UOM so the UOM column never independently falls
    # back to '—' -- isolating the em-dash to the columns under test.
    line_with_delivery = SalesOrderItem(
        sales_order_id=so.id, line_number=1, product_id=p.id,
        quantity=Decimal('1.0000'), unit_price=Decimal('100.00'), amount=Decimal('100.00'),
        vat_rate=Decimal('0.00'), line_total=Decimal('100.00'), vat_amount=Decimal('0.00'),
        uom_text='PCS',
        delivery_date=datetime.date(2026, 8, 15), delivery_site_id=site.id,
    )
    line_without_delivery = SalesOrderItem(
        sales_order_id=so.id, line_number=2, product_id=p.id,
        quantity=Decimal('1.0000'), unit_price=Decimal('50.00'), amount=Decimal('50.00'),
        vat_rate=Decimal('0.00'), line_total=Decimal('50.00'), vat_amount=Decimal('0.00'),
        uom_text='PCS',
    )
    # Mixed state: date set, site left unset -- proves the two columns fall
    # back independently rather than one flag gating both.
    line_partial_delivery = SalesOrderItem(
        sales_order_id=so.id, line_number=3, product_id=p.id,
        quantity=Decimal('1.0000'), unit_price=Decimal('25.00'), amount=Decimal('25.00'),
        vat_rate=Decimal('0.00'), line_total=Decimal('25.00'), vat_amount=Decimal('0.00'),
        uom_text='PCS',
        delivery_date=datetime.date(2026, 9, 1),
    )
    so.line_items.append(line_with_delivery)
    so.line_items.append(line_without_delivery)
    so.line_items.append(line_partial_delivery)
    so.calculate_totals()
    db_session.commit()

    detail_html = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    assert 'Delivery Date' in detail_html
    assert 'Delivery Site' in detail_html
    assert '&#8212;' not in detail_html           # never the entity (leaks as literal text)

    row1 = _line_items_row(detail_html, 1)
    date_cell, site_cell = _delivery_cells(row1, trailing_extra=1)  # skip Task 9's Status column
    assert date_cell == 'Aug 15, 2026'            # set delivery_date, detail's own date format
    assert site_cell == 'PLANT WAREHOUSE'         # set delivery_site name
    assert '—' not in date_cell and '—' not in site_cell

    row2 = _line_items_row(detail_html, 2)
    date_cell, site_cell = _delivery_cells(row2, trailing_extra=1)
    assert date_cell == '—'                       # unset delivery_date falls back to em-dash
    assert site_cell == '—'                       # unset delivery_site falls back to em-dash

    row3 = _line_items_row(detail_html, 3)
    date_cell, site_cell = _delivery_cells(row3, trailing_extra=1)
    assert date_cell == 'Sep 01, 2026'             # mixed state: date set...
    assert site_cell == '—'                        # ...site still falls back independently

    print_html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)
    assert 'Delivery Date' in print_html
    assert 'Delivery Site' in print_html
    assert '&#8212;' not in print_html

    row1 = _line_items_row(print_html, 1)
    date_cell, site_cell = _delivery_cells(row1)
    assert date_cell == '15 August 2026'          # set delivery_date, print's own date format
    assert site_cell == 'PLANT WAREHOUSE'
    assert '—' not in date_cell and '—' not in site_cell

    row2 = _line_items_row(print_html, 2)
    date_cell, site_cell = _delivery_cells(row2)
    assert date_cell == '—'
    assert site_cell == '—'

    row3 = _line_items_row(print_html, 3)
    date_cell, site_cell = _delivery_cells(row3)
    assert date_cell == '01 September 2026'
    assert site_cell == '—'


def test_list_shows_so_number_and_status_badge(client, db_session, admin_user, main_branch):
    """GET /sales-orders → 200; SO number and draft status badge appear in the list."""
    import datetime
    c = _customer(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    # Create one SO directly in the DB (branch-scoped)
    so = SalesOrder(
        so_number='SO-2026-06-LIST1',
        order_date=datetime.date(2026, 6, 28),
        customer_id=c.id,
        customer_name='Acme',
        branch_id=main_branch.id,
        status='draft',
    )
    db_session.add(so)
    db_session.commit()

    resp = client.get('/sales-orders')
    assert resp.status_code == 200
    assert b'SO-2026-06-LIST1' in resp.data
    # Status badge renders the text "Draft"
    assert b'badge-draft' in resp.data
    assert b'Draft' in resp.data


def test_print_preprinted_renders_designer_no_currency_glyph(client, db_session, admin_user, main_branch):
    """With so_print_form='preprinted', the Print route serves the drag-designer canvas
    (no peso glyph). Printing is now setting-driven like SI."""
    from app.settings import AppSettings
    AppSettings.set_setting('so_print_form', 'preprinted')
    db_session.commit()
    c = _customer(db_session)
    p = _product(db_session, code='PPF', name='PrePrint Widget')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-PPF1', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-PPF1').first()
    assert so is not None
    resp = client.get(f'/sales-orders/{so.id}/print')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'ppCanvas' in html            # drag-designer canvas rendered
    assert '₱' not in html          # peso sign U+20B1


def test_print_job_order_hides_pricing_and_uses_job_order_name(client, db_session, admin_user,
                                                                main_branch):
    """The Job Order Slip shows job_order_name (falling back to name) and Quantity -- and NEVER
    unit price, amount, VAT, or the Total Sales summary."""
    c = _customer(db_session)
    p_named = _product(db_session, code='JON-P1', name='Regular Name One')
    p_named.job_order_name = 'PROD-NAME-ONE'
    p_blank = _product(db_session, code='JON-P2', name='Regular Name Two')
    db.session.commit()

    so = SalesOrder(so_number='SO-2026-06-JOS1', order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft')
    db.session.add(so); db.session.flush()
    li1 = SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p_named.id,
                         quantity=Decimal('5'), unit_price=Decimal('999.99'),
                         amount=Decimal('4999.95'), line_total=Decimal('4999.95'))
    li2 = SalesOrderItem(sales_order_id=so.id, line_number=2, product_id=p_blank.id,
                         quantity=Decimal('3'), unit_price=Decimal('50.00'),
                         amount=Decimal('150.00'), line_total=Decimal('150.00'))
    db.session.add_all([li1, li2])
    so.total_amount = Decimal('5149.95')
    db.session.commit()

    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/sales-orders/{so.so_number}/print-job-order')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'JOB ORDER' in html
    assert 'PROD-NAME-ONE' in html          # job_order_name used when set
    assert 'Regular Name Two' in html       # falls back to product.name when blank
    assert 'Regular Name One' not in html   # the SET job_order_name replaces the regular name
    assert '999.99' not in html
    assert '4,999.95' not in html
    assert '5,149.95' not in html
    assert 'Total Sales' not in html
    assert 'Unit Price' not in html
    assert 'Amount' not in html


def test_print_job_order_cross_branch_404(client, db_session, admin_user, main_branch,
                                          branch_manila):
    c = _customer(db_session)
    so = SalesOrder(so_number='SO-2026-06-JOS2', order_date=datetime.date(2026, 6, 16),
                    customer_id=c.id, customer_name='Acme', branch_id=branch_manila.id,
                    status='draft')
    db.session.add(so); db.session.commit()

    _login(client, admin_user)
    _select_branch(client, main_branch.id)   # different branch than the SO
    resp = client.get(f'/sales-orders/{so.so_number}/print-job-order')
    assert resp.status_code == 404


def test_detail_shows_salesperson_and_plain_vat_code(client, db_session, admin_user, main_branch):
    """SO detail must show a Salesperson row (parity with DR/SI detail) and the VT
    cell must show only the code, not the rate — parity with sales_invoices/detail.html."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:employees', '1')
    db_session.commit()
    clear_module_config_cache()

    from app.employees.models import Employee
    emp = Employee(employee_no='E001', first_name='Jane', last_name='Cruz',
                    branch_id=main_branch.id, is_active=True, is_salesperson=True)
    db_session.add(emp); db_session.commit()

    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'VAT', 'vat_rate': '12'}])
    from app.sales_vat_categories.models import SalesVATCategory
    if not SalesVATCategory.query.filter_by(code='VAT').first():
        db_session.add(SalesVATCategory(code='VAT', name='Vatable Sale', rate=Decimal('12.00'),
                                        transaction_nature='regular', is_active=True))
        db_session.commit()

    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0002', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'salesperson_id': str(emp.id), 'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200

    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0002').first()
    so.salesperson_id = emp.id
    db_session.commit()

    resp = client.get(f'/sales-orders/{so.id}')
    html = resp.get_data(as_text=True)
    assert 'Salesperson' in html
    assert 'Jane Cruz' in html or emp.full_name in html
    row = _line_items_row(html, 1)
    assert 'VAT (12.00%)' not in row
    assert '>VAT<' in row


def test_order_monitoring_is_first_link_in_sales_sidebar_area(client, db_session, admin_user, main_branch):
    """Order Monitoring must render before every other Sales-area nav link
    (Quotations, Sales Orders, etc.), not glued after Sales Orders."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/dashboard')
    html = resp.get_data(as_text=True)

    sales_section_start = html.index('data-area="sales"')
    monitor_pos = html.index('sales-orders/monitor', sales_section_start)
    # NOTE: the Sales Orders nav-text span concatenates the module label directly
    # against its "(Customer Order)" nav-subtext span with no intervening
    # whitespace/closing tag (see base.html's `{%- if m.key == ... %}` trim
    # markers), so the rendered HTML is `...Sales Orders<span class="nav-subtext">...`
    # -- there is no literal `>Sales Orders<` substring to match. Anchor on the
    # label text itself instead, which is unique within the Sales sidebar area.
    so_list_pos = html.index('Sales Orders', sales_section_start)
    assert monitor_pos < so_list_pos, (
        'Order Monitoring link must render before the Sales Orders link '
        'within the Sales sidebar area'
    )


def test_edit_form_customer_card_callback_populates_wht_and_rebuilds_selects(
        client, db_session, admin_user, main_branch):
    """Regression for the SO-Edit WT-picker bug: initCustomerCardOnEdit() -- the
    IIFE that fires on every SO Edit page load to populate the customer-card
    badges from /customers/<id>/defaults -- must ALSO set currentCustomerWHTs
    and call rebuildAllWhtSelects(), mirroring Sales Invoice's parallel block
    (sales_invoices/form.html's own initCustomerCardOnEdit). Without both lines,
    initItems() has already built every line's WT <select> against an empty
    currentCustomerWHTs (still its [] initial value) before this fetch resolves,
    so buildWhtOptions() renders only the disabled "No WT" placeholder and the
    saved wt_id is never reflected in the UI -- even though a customer WHT code
    exists and the line's wt_id is correctly persisted server-side.

    This is a client-side-only defect: a plain response-body substring check
    can't see it (the string "currentCustomerWHTs" appears elsewhere in the
    script for unrelated reasons -- declaration, the customer-picker's own
    change handler, buildWhtOptions/rebuildAllWhtSelects themselves), so the
    search is scoped to the initCustomerCardOnEdit function body specifically,
    the same technique used for the Sales-sidebar-ordering assertion above
    (index-from-offset rather than a bare `in html` check) and flagged by the
    Task 2 reviewer as the correct way to avoid a false-pass on an unscoped
    substring match.
    """
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db_session.add(wt); db_session.commit()

    c = _customer(db_session)
    c.withholding_taxes = [wt]
    db_session.commit()
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0', 'wt_id': str(wt.id)}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0004', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    assert resp.status_code == 200
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0004').first()
    assert so.line_items[0].wt_id == wt.id

    html = client.get(f'/sales-orders/{so.id}/edit').get_data(as_text=True)

    # Scope to the initCustomerCardOnEdit IIFE body only (its own `})();` close),
    # not the whole <script> block or any other function of the same shape.
    fn_start = html.index('function initCustomerCardOnEdit')
    fn_end = html.index('})();', fn_start) + len('})();')
    fn_body = html[fn_start:fn_end]

    assert 'currentCustomerWHTs' in fn_body and 'data.withholding_taxes' in fn_body, (
        'initCustomerCardOnEdit() must populate currentCustomerWHTs from the '
        '/customers/<id>/defaults response, like Sales Invoice does'
    )
    assert 'rebuildAllWhtSelects();' in fn_body, (
        'initCustomerCardOnEdit() must call rebuildAllWhtSelects() after '
        'populating currentCustomerWHTs, or every line WT <select> built by '
        'initItems() before this fetch resolves stays stuck on the disabled '
        '"No WT" placeholder for the whole edit session'
    )

    # rebuildAllWhtSelects() must now be call-able from >=2 places in this file:
    # the customer-picker's own change handler (create flow, existing items) and
    # this edit-load callback (fixed here). Count literal calls (semicolon-
    # terminated), not the `function rebuildAllWhtSelects() {` definition line.
    call_count = html.count('rebuildAllWhtSelects();')
    assert call_count >= 2, (
        f'expected rebuildAllWhtSelects() to be called from at least 2 places, '
        f'found {call_count}'
    )


def test_addfirstcustomerline_defaults_single_customer_wt(client, db_session, admin_user, main_branch):
    """Whole-branch-review finding: the SO WT picker must auto-default like SI's does (design
    spec section 4) -- when a customer has exactly ONE assigned WT code, a newly-added line
    for that customer defaults to it, same mechanism as the existing VT auto-default
    (currentCustomerVatCategory) and SI's own autoWht/rebuildAllWhtSelects pattern. This was a
    plan-writing gap (the plan's own code snippets omitted it), not an implementation
    deviation -- the spec is unambiguous, so this is not "still open."

    Client-side-only behavior (Choices.js selection state), so it is verified at the source
    level -- the same technique the WT-picker edit-load test above uses: scope the assertion
    to the specific function body, not a bare substring `in html` check (unreliable here since
    'currentCustomerWHTs' etc. appear in multiple unrelated places in the script)."""
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db_session.add(wt); db_session.commit()
    c = _customer(db_session)
    c.withholding_taxes = [wt]
    db_session.commit()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    html = client.get('/sales-orders/create').get_data(as_text=True)

    # addFirstCustomerLine(): the new-line default must reference a single-WT autoWht,
    # mirroring the VT auto-default already in the same function.
    fn1_start = html.index('function addFirstCustomerLine')
    fn1_end = html.index('function rebuildCustomerLineDefaults', fn1_start)
    fn1_body = html[fn1_start:fn1_end]
    assert 'currentCustomerWHTs.length === 1' in fn1_body, (
        'addFirstCustomerLine() must compute a single-WT autoWht from currentCustomerWHTs, '
        'like SI\'s form does')
    assert 'wt_id: autoWht ? autoWht.id : null' in fn1_body, (
        'addFirstCustomerLine() must default the new line\'s wt_id to the customer\'s sole '
        'WT code, not hardcode null')

    # rebuildAllWhtSelects(): a dropped/invalid code on customer switch must also fall
    # forward to the new customer's sole WT, not to null -- mirrors SI's rebuildAllWhtSelects.
    fn2_start = html.index('function rebuildAllWhtSelects')
    fn2_end = html.index('function addLineItem', fn2_start)
    fn2_body = html[fn2_start:fn2_end]
    assert 'currentCustomerWHTs.length === 1' in fn2_body, (
        'rebuildAllWhtSelects() must compute a single-WT autoWht from currentCustomerWHTs')
    assert 'item.wt_id = autoWht ? autoWht.id : null;' in fn2_body, (
        'rebuildAllWhtSelects() must default a dropped/invalid wt_id to the customer\'s '
        'sole WT code, not unconditionally null it out')


def test_detail_shows_wt_column(client, db_session, admin_user, main_branch):
    """SO detail must show a WT column (code or '—') on each line, matching
    the display pattern in sales_invoices/detail.html."""
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db_session.add(wt); db_session.commit()
    c = _customer(db_session)
    p = _product(db_session)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0', 'wt_id': str(wt.id)}])
    resp = client.post('/sales-orders/create', data={
        'so_number': 'SO-2026-06-0004', 'order_date': '2026-06-15',
        'customer_id': str(c.id), 'customer_name': 'Acme', 'payment_terms': 'Net 30',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-2026-06-0004').first()

    resp = client.get(f'/sales-orders/{so.id}')
    html = resp.get_data(as_text=True)
    row = _line_items_row(html, 1)
    assert '>WC160<' in row

    so2 = SalesOrder(branch_id=main_branch.id, so_number='SO-2026-06-0005',
                     order_date=datetime.date(2026, 6, 15), customer_id=c.id,
                     customer_name=c.name, status='draft')
    li2 = SalesOrderItem(line_number=1, quantity=Decimal('1'), unit_price=Decimal('50.00'),
                         product_id=p.id, amount=Decimal('50.00'))
    li2.calculate_amounts()
    so2.line_items.append(li2)
    db_session.add(so2); db_session.commit()
    resp2 = client.get(f'/sales-orders/{so2.id}')
    row2 = _line_items_row(resp2.get_data(as_text=True), 1)
    assert '>—<' in row2


def test_close_line_requires_confirmed_status_role_and_reason(client, db_session, admin_user,
                                                                accountant_user, staff_user, main_branch):
    from app.audit.models import AuditLog
    c = _customer(db_session)
    p = _product(db_session)

    so = SalesOrder(branch_id=main_branch.id, so_number='SO-CL-0001',
                    order_date=datetime.date(2026, 7, 28), customer_id=c.id,
                    customer_name=c.name, status='draft')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    # Draft SO: guard refuses (mirrors the header cancel's confirmed-only precondition).
    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'no longer needed'}, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(li)
    assert li.line_status == 'open'

    so.status = 'confirmed'
    db_session.commit()

    # Staff: role guard refuses.
    _login(client, staff_user)
    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'no longer needed'}, follow_redirects=True)
    db_session.refresh(li)
    assert li.line_status == 'open'

    # Accountant, reason too short: refused.
    _login(client, accountant_user)
    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'short'}, follow_redirects=True)
    db_session.refresh(li)
    assert li.line_status == 'open'

    # Accountant, valid reason: succeeds and is audit-logged.
    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'customer no longer wants the remainder'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(li)
    assert li.line_status == 'closed'
    assert li.closed_by_id == accountant_user.id
    assert li.closed_at is not None
    assert li.closed_reason == 'customer no longer wants the remainder'
    assert AuditLog.query.filter_by(module='sales_orders', action='update',
                                    record_id=so.id).filter(
                                        AuditLog.notes.like('%closed%')).count() >= 1


def test_close_line_branch_scope_returns_404(client, db_session, accountant_user, main_branch,
                                               branch_manila):
    """An SO belonging to a DIFFERENT branch than the one currently selected in session
    must 404 -- mirrors every other branch-scoped detail/action route. accountant_user is
    only assigned main_branch, but the guard is a session-vs-SO check, not an authz check,
    so we exercise it by selecting main_branch while the SO lives on branch_manila."""
    c = _customer(db_session)
    p = _product(db_session)

    so = SalesOrder(branch_id=branch_manila.id, so_number='SO-CL-BR01',
                    order_date=datetime.date(2026, 7, 28), customer_id=c.id,
                    customer_name=c.name, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'no longer needed'})
    assert resp.status_code == 404
    db_session.refresh(li)
    assert li.line_status == 'open'


def test_close_line_item_so_mismatch_returns_404(client, db_session, accountant_user, main_branch):
    """The URL carries both the SO id and the line-item id independently -- if item_id
    belongs to a DIFFERENT sales order than the one named by id in the URL, the route
    must 404 rather than close a line under the wrong SO's audit trail."""
    c = _customer(db_session)
    p = _product(db_session)

    so1 = SalesOrder(branch_id=main_branch.id, so_number='SO-CL-MIS01',
                     order_date=datetime.date(2026, 7, 28), customer_id=c.id,
                     customer_name=c.name, status='confirmed')
    li1 = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                         product_id=p.id, amount=Decimal('100.00'))
    li1.calculate_amounts()
    so1.line_items.append(li1)

    so2 = SalesOrder(branch_id=main_branch.id, so_number='SO-CL-MIS02',
                     order_date=datetime.date(2026, 7, 28), customer_id=c.id,
                     customer_name=c.name, status='confirmed')
    li2 = SalesOrderItem(line_number=1, quantity=Decimal('5'), unit_price=Decimal('10.00'),
                         product_id=p.id, amount=Decimal('50.00'))
    li2.calculate_amounts()
    so2.line_items.append(li2)

    db_session.add_all([so1, so2]); db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    # li2 belongs to so2, not so1 -- posting li2's id against so1's URL must 404.
    resp = client.post(f'/sales-orders/{so1.id}/lines/{li2.id}/close',
                       data={'closed_reason': 'no longer needed'})
    assert resp.status_code == 404
    db_session.refresh(li2)
    assert li2.line_status == 'open'


def test_close_line_already_closed_is_idempotent(client, db_session, accountant_user, main_branch):
    """Closing an already-closed line must be refused with a flash, not silently
    re-processed -- guards against a double-submit overwriting closed_by/closed_at/
    closed_reason or emitting a duplicate audit entry."""
    c = _customer(db_session)
    p = _product(db_session)

    so = SalesOrder(branch_id=main_branch.id, so_number='SO-CL-IDEM01',
                    order_date=datetime.date(2026, 7, 28), customer_id=c.id,
                    customer_name=c.name, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    # First close: succeeds.
    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'customer no longer wants the remainder'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(li)
    assert li.line_status == 'closed'
    first_closed_at = li.closed_at
    first_closed_reason = li.closed_reason
    audit_count_after_first_close = AuditLog.query.filter_by(
        module='sales_orders', action='update', record_id=so.id).filter(
            AuditLog.notes.like('%closed%')).count()

    # Second close attempt on the SAME already-closed line: refused, state untouched.
    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'trying to close it again'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'already closed' in resp.data
    db_session.refresh(li)
    assert li.line_status == 'closed'
    assert li.closed_at == first_closed_at
    assert li.closed_reason == first_closed_reason
    assert AuditLog.query.filter_by(
        module='sales_orders', action='update', record_id=so.id).filter(
            AuditLog.notes.like('%closed%')).count() == audit_count_after_first_close


def test_detail_shows_close_button_then_closed_badge(client, db_session, admin_user,
                                                       accountant_user, main_branch):
    c = _customer(db_session)
    p = _product(db_session)
    so = SalesOrder(branch_id=main_branch.id, so_number='SO-CL-0002',
                    order_date=datetime.date(2026, 7, 28), customer_id=c.id,
                    customer_name=c.name, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    resp = client.get(f'/sales-orders/{so.id}')
    html = resp.get_data(as_text=True)
    row = _line_items_row(html, 1)
    assert 'openCloseLineModal' in row
    assert 'Closed' not in row

    resp = client.post(f'/sales-orders/{so.id}/lines/{li.id}/close',
                       data={'closed_reason': 'customer no longer wants the remainder'},
                       follow_redirects=True)
    html2 = resp.get_data(as_text=True)
    row2 = _line_items_row(html2, 1)
    assert 'Closed' in row2
    assert 'openCloseLineModal' not in row2


def test_monitoring_shows_closed_badge_for_cancelled_so(client, db_session, admin_user,
                                                          accountant_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()

    c = _customer(db_session)
    p = _product(db_session)
    so = SalesOrder(branch_id=main_branch.id, so_number='SO-CL-0003',
                    order_date=datetime.date.today(), customer_id=c.id,
                    customer_name=c.name, status='cancelled')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    today = datetime.date.today()
    resp = client.get(f'/sales-orders/monitor?date_from={today.isoformat()}&date_to={today.isoformat()}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Closed' in html

    # Tighter than a bare-substring "10" absence check (the ordered-qty column
    # legitimately shows "10" in this same row -- asserting its absence would be
    # a false-fragile test). Instead, isolate the Undelivered <td> specifically
    # (the last <td>...</td> in the row, keyed on the product name) and assert
    # THAT cell holds the badge, not a raw undelivered-quantity number.
    row_match = re.search(r'<tr>\s*<td>Widget</td>.*?</tr>', html, re.DOTALL)
    assert row_match, 'expected a Widget row in the Order Monitoring table'
    row = row_match.group(0)
    cells = re.findall(r'<td[^>]*>.*?</td>', row, re.DOTALL)
    undelivered_cell = cells[-1]
    assert 'badge' in undelivered_cell and 'Closed' in undelivered_cell
    assert not re.search(r'>\s*10\s*<', undelivered_cell)
