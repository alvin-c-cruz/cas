import json, pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product

pytestmark = [pytest.mark.integration, pytest.mark.quotations]


@pytest.fixture(autouse=True)
def quotations_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('quotations', 'sales_orders', 'products', 'units_of_measure', 'employees'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _customer(db_session):
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    return c


def _product(db_session):
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add(p); db.session.commit()
    return p


def test_create_draft_quote_persists(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'exclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.filter_by(customer_id=c.id).first()
    assert q is not None and q.status == 'draft' and q.vat_treatment == 'exclusive'
    assert q.customer_name and q.line_items[0].quantity == Decimal('2')


def test_create_quote_logs_audit_entry(client, db_session, admin_user, main_branch):
    from app.audit.models import AuditLog
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.filter_by(customer_id=c.id).first()
    entry = AuditLog.query.filter_by(module='quotations', record_id=q.id).first()
    assert entry is not None and entry.action == 'create'
    assert q.quotation_number in entry.record_identifier


def test_view_is_branch_scoped(client, db_session, admin_user, main_branch, branch_manila):
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.first()
    assert client.get(f'/quotations/{q.id}').status_code == 200
    with client.session_transaction() as s: s['selected_branch_id'] = branch_manila.id
    assert client.get(f'/quotations/{q.id}').status_code == 404


def test_print_renders_summary_and_has_no_peso_glyph(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'exclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.filter_by(customer_id=c.id).first()
    body = client.get(f'/quotations/{q.id}/print').get_data(as_text=True)
    assert q.quotation_number in body and 'Widget' in body
    assert 'VAT-Exclusive' in body           # treatment label
    assert 'Subtotal' in body and 'VAT' in body and 'Total' in body
    assert '2.0000' in body                   # quantity actually renders
    assert '₱' not in body                    # no peso glyph on the printout


def test_print_is_branch_scoped(client, db_session, admin_user, main_branch, branch_manila):
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.first()
    with client.session_transaction() as s: s['selected_branch_id'] = branch_manila.id
    assert client.get(f'/quotations/{q.id}/print').status_code == 404


def test_edit_draft_updates_treatment_and_lines(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.first()
    new_lines = json.dumps([{'product_id': str(p.id), 'quantity': '5', 'unit_price': '100.00',
                             'vat_category': 'V12', 'vat_rate': '12'}])
    client.post(f'/quotations/{q.id}/edit', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'row_version': q.row_version,
        'vat_treatment': 'zero_rated', 'payment_terms': 'Net 30', 'lines': new_lines},
        follow_redirects=True)
    db_session.refresh(q)
    assert q.vat_treatment == 'zero_rated'
    assert q.line_items[0].quantity == Decimal('5')
