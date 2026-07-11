import json, pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _confirmed_so(db_session, branch_id):
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-C-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='Acme', branch_id=branch_id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                                        unit_price=Decimal('100'), amount=Decimal('1000')))
    db.session.add(so); db.session.commit()
    return so


def test_create_draft_dr_persists_and_snapshots_customer(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    assert dr is not None and dr.status == 'draft'
    assert dr.customer_name == 'Acme' and dr.customer_id == so.customer_id
    assert dr.line_items[0].delivered_quantity == Decimal('4')
    assert dr.dr_number.startswith('DR-')


def test_create_form_renders_lines_field_exactly_once(client, db_session, admin_user, main_branch):
    """Regression (BUG-DR-DUP-LINES): the hidden `lines` field must render EXACTLY ONCE.

    `form.hidden_tag()` auto-emits every WTForms HiddenField (incl. `lines`), so ALSO
    rendering `{{ form.lines(id="lines-json") }}` explicitly produced a duplicate
    name="lines" input. The browser then posted `lines` twice, and Flask's
    request.form.get('lines') read the empty first copy -> every real-browser DR
    creation failed 'Add at least one delivered line.' (unit tests miss it because the
    test client posts a single `lines` key)."""
    _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    resp = client.get('/delivery-receipts/create')
    assert resp.status_code == 200
    count = resp.data.count(b'name="lines"')
    assert count == 1, f'expected exactly one name="lines" input, found {count}'


def test_create_dr_logs_audit_entry(client, db_session, admin_user, main_branch):
    from app.audit.models import AuditLog
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '2'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    entry = AuditLog.query.filter_by(module='delivery_receipts', record_id=dr.id).first()
    assert entry is not None and entry.action == 'create'
    assert dr.dr_number in entry.record_identifier


def test_create_dr_rejects_empty_lines(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    resp = client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': '[]'},
        follow_redirects=True)
    assert DeliveryReceipt.query.count() == 0
    assert b'at least one delivered line' in resp.data


def test_view_is_branch_scoped(client, db_session, admin_user, main_branch, branch_manila):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.first()
    assert client.get(f'/delivery-receipts/{dr.id}').status_code == 200
    with client.session_transaction() as s: s['selected_branch_id'] = branch_manila.id
    assert client.get(f'/delivery-receipts/{dr.id}').status_code == 404


def test_edit_draft_updates_quantities(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    soi_id = so.line_items[0].id
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09',
        'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '4'}])},
        follow_redirects=True)
    dr = DeliveryReceipt.query.first()
    client.post(f'/delivery-receipts/{dr.id}/edit', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-10',
        'row_version': dr.row_version,
        'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '6'}])},
        follow_redirects=True)
    db_session.refresh(dr)
    assert dr.line_items[0].delivered_quantity == Decimal('6')
    assert dr.delivery_date == date(2026, 7, 10)


def test_edit_form_renders_row_version_field(client, db_session, admin_user, main_branch):
    """Regression (BUG-DR-EDIT-FALSE-CONFLICT): the edit form MUST emit the
    `row_version` hidden input, or the lost-update guard false-conflicts every save.

    The DR form renders csrf-only (`{{ form.csrf_token }}`, the BUG-DR-DUP-LINES fix),
    which does NOT auto-emit `RowVersionFormMixin.row_version`. `submitted_version()`
    reads the token from the raw POST body only, so a form that never renders the field
    posts no token -> `claim_version(dr.id, None)` returns False -> "changed by another
    user" on every real-browser draft-DR edit. pytest missed it because the edit tests
    POST `row_version` directly, bypassing the template render."""
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09',
        'lines': json.dumps([{'sales_order_item_id': so.line_items[0].id,
                              'delivered_quantity': '4'}])},
        follow_redirects=True)
    dr = DeliveryReceipt.query.first()
    resp = client.get(f'/delivery-receipts/{dr.id}/edit')
    assert resp.status_code == 200
    rv_count = resp.data.count(b'name="row_version"')
    assert rv_count == 1, f'expected exactly one name="row_version" input, found {rv_count}'
    # The lines-field-once invariant (BUG-DR-DUP-LINES) must still hold on the edit form.
    assert resp.data.count(b'name="lines"') == 1


def test_print_renders_lines_and_has_no_currency_glyph(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '3'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    body = client.get(f'/delivery-receipts/{dr.id}/print').get_data(as_text=True)
    assert dr.dr_number in body and 'Widget' in body
    # The delivered quantity must actually render -- qty_fmt returns '' for a line
    # item that does not expose `quantity`, which would leave the column blank.
    assert '3.0000' in body
    assert '₱' not in body     # no peso glyph on a delivery document


def test_print_is_branch_scoped(client, db_session, admin_user, main_branch, branch_manila):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '3'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.first()
    with client.session_transaction() as s: s['selected_branch_id'] = branch_manila.id
    assert client.get(f'/delivery-receipts/{dr.id}/print').status_code == 404


def test_so_detail_offers_create_dr_when_module_on(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    # The SO detail page itself lives behind the optional sales_orders module gate.
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit(); clear_module_config_cache()

    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    body = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    assert f'/delivery-receipts/create?so={so.id}' in body


def test_so_detail_hides_create_dr_when_module_off(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:delivery_receipts', '0')   # override the autouse fixture
    db_session.commit(); clear_module_config_cache()

    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    body = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    assert '/delivery-receipts/create' not in body
