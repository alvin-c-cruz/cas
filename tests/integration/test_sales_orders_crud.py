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


def _delivery_cells(row_html):
    """Return (delivery_date_cell, delivery_site_cell) -- the last two <td>
    cells of a line-items row. Delivery Date and Delivery Site are always the
    8th and 9th (final) columns in both detail.html and print.html."""
    cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
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
    date_cell, site_cell = _delivery_cells(row1)
    assert date_cell == 'Aug 15, 2026'            # set delivery_date, detail's own date format
    assert site_cell == 'PLANT WAREHOUSE'         # set delivery_site name
    assert '—' not in date_cell and '—' not in site_cell

    row2 = _line_items_row(detail_html, 2)
    date_cell, site_cell = _delivery_cells(row2)
    assert date_cell == '—'                       # unset delivery_date falls back to em-dash
    assert site_cell == '—'                       # unset delivery_site falls back to em-dash

    row3 = _line_items_row(detail_html, 3)
    date_cell, site_cell = _delivery_cells(row3)
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
    resp = client.get(f'/sales-orders/{so.id}/print-job-order')
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
    resp = client.get(f'/sales-orders/{so.id}/print-job-order')
    assert resp.status_code == 404
