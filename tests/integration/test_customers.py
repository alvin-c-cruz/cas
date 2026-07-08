"""
Integration tests for the customer list view.
"""
from app import db


def test_customer_list_renders_empty(client, db_session, accountant_user, main_branch):
    """Customer list returns 200 with empty state on a fresh DB."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Customer Maintenance' in response.data
    assert b'No customers found' in response.data


def test_customer_list_shows_customer(client, db_session, accountant_user, main_branch):
    """Customer list shows code, name, and BIR-incomplete badge when TIN is missing."""
    from app.customers.models import Customer
    cust = Customer(code='C001', name='Test Corp', payment_terms='Net 30',
                    is_active=True)
    db_session.add(cust)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)
    response = client.get('/customers')
    assert response.status_code == 200
    assert b'Test Corp' in response.data
    assert b'C001' in response.data
    assert b'BIR incomplete' in response.data


def test_customer_list_delete_modal_present(client, db_session, accountant_user, main_branch):
    """Delete modal is in the HTML — no data-confirm HTML attribute on any form element."""
    from app.customers.models import Customer
    cust = Customer(code='C001', name='Test Corp', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)
    response = client.get('/customers')
    assert b'delete-modal-' in response.data
    # base.html JS contains 'data-confirm' as a string literal in script; the real
    # check is that no HTML element uses the attribute assignment form data-confirm="
    assert b'data-confirm="' not in response.data


def _login_accountant(client, accountant_user, main_branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)


def test_customer_delete_blocked_when_referenced_by_sales_invoice(
        client, db_session, accountant_user, main_branch):
    """A customer linked to a sales invoice cannot be deleted (would orphan the SI)."""
    from datetime import date
    from app.customers.models import Customer
    from app.sales_invoices.models import SalesInvoice
    from app.audit.models import AuditLog

    cust = Customer(code='C001', name='Linked Corp', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()
    si = SalesInvoice(invoice_number='SI-2026-06-0001', invoice_date=date(2026, 6, 1),
                      due_date=date(2026, 7, 1), customer_id=cust.id,
                      customer_name='Linked Corp', branch_id=main_branch.id)
    db_session.add(si)
    db_session.commit()

    _login_accountant(client, accountant_user, main_branch)
    resp = client.post(f'/customers/{cust.id}/delete', follow_redirects=True)

    assert resp.status_code == 200
    assert db.session.get(Customer, cust.id) is not None, 'customer must not be deleted'
    assert AuditLog.query.filter_by(module='customer', action='delete').count() == 0
    assert 'Cannot delete' in resp.data.decode()


def test_customer_delete_blocked_when_referenced_by_cash_receipt(
        client, db_session, accountant_user, main_branch, cash_account):
    """A customer linked to a cash receipt cannot be deleted (would orphan the CRV)."""
    from datetime import date
    from app.customers.models import Customer
    from app.cash_receipts.models import CashReceiptVoucher
    from app.audit.models import AuditLog

    cust = Customer(code='C002', name='Payer Corp', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()
    crv = CashReceiptVoucher(crv_number='CR-2026-06-0001', crv_date=date(2026, 6, 1),
                             customer_id=cust.id, customer_name='Payer Corp',
                             branch_id=main_branch.id, cash_account_id=cash_account.id)
    db_session.add(crv)
    db_session.commit()

    _login_accountant(client, accountant_user, main_branch)
    resp = client.post(f'/customers/{cust.id}/delete', follow_redirects=True)

    assert db.session.get(Customer, cust.id) is not None, 'customer must not be deleted'
    assert AuditLog.query.filter_by(module='customer', action='delete').count() == 0
    assert 'Cannot delete' in resp.data.decode()


def test_customer_create_records_acting_user(
        client, db_session, accountant_user, main_branch):
    """Creating a customer stamps created_by_id / updated_by_id with the actor."""
    from app.customers.models import Customer

    _login_accountant(client, accountant_user, main_branch)
    resp = client.post('/customers/create', data={
        'code': 'C001', 'name': 'Authored Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_vat_category': '', 'default_wt_code': '',
    }, follow_redirects=True)

    assert resp.status_code == 200
    cust = Customer.query.filter_by(code='C001').first()
    assert cust is not None
    assert cust.created_by_id == accountant_user.id
    assert cust.updated_by_id == accountant_user.id


def test_customer_list_search_filters_server_side(
        client, db_session, accountant_user, main_branch):
    """?q= filters the rows returned by the server, not just client-side JS."""
    from app.customers.models import Customer
    db_session.add(Customer(code='C001', name='Alpha Trading',
                            payment_terms='Net 30', is_active=True))
    db_session.add(Customer(code='C002', name='Beta Supplies',
                            payment_terms='Net 30', is_active=True))
    db_session.commit()

    _login_accountant(client, accountant_user, main_branch)
    body = client.get('/customers?q=Alpha').data.decode()

    assert 'Alpha Trading' in body
    assert 'Beta Supplies' not in body


def test_customer_list_paginates_at_25_per_page(
        client, db_session, accountant_user, main_branch):
    """The list caps at 25 rows per page; page 2 shows the overflow."""
    from app.customers.models import Customer
    for i in range(30):
        db_session.add(Customer(code=f'C{i:03d}', name=f'Cust {i:03d}',
                                payment_terms='Net 30', is_active=True))
    db_session.commit()

    _login_accountant(client, accountant_user, main_branch)
    page1 = client.get('/customers').data.decode()
    assert 'Cust 000' in page1
    assert 'Cust 025' not in page1

    page2 = client.get('/customers?page=2').data.decode()
    assert 'Cust 025' in page2


def test_create_form_marks_required_fields(client, db_session, accountant_user, main_branch):
    """Code and Name are DataRequired — the form shows the shared required '*' marker."""
    _login_accountant(client, accountant_user, main_branch)
    resp = client.get('/customers/create')
    assert resp.status_code == 200
    assert b'<span class="required"' in resp.data


def test_customer_csv_export_includes_customer_row(
        client, db_session, accountant_user, main_branch):
    """CSV export carries the customer's code/name/TIN (locks export columns for refactor)."""
    from app.customers.models import Customer
    db_session.add(Customer(code='C001', name='Exporter Corp', tin='123-456-789-000',
                            payment_terms='Net 30', is_active=True))
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.get('/customers/export/csv')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'C001' in body
    assert 'Exporter Corp' in body
    assert '123-456-789-000' in body


def test_customer_create_audit_captures_field_values(
        client, db_session, accountant_user, main_branch):
    """Create audit new_values snapshot covers the full audited field set (locks CUSTOMER_FIELDS)."""
    import json
    from app.audit.models import AuditLog
    _login_accountant(client, accountant_user, main_branch)

    client.post('/customers/create', data={
        'code': 'C001', 'name': 'Audited Corp', 'tin': '111-222-333-000',
        'payment_terms': 'Net 30', 'is_active': '1',
        'default_vat_category': '', 'default_wt_code': '',
    }, follow_redirects=True)

    entry = AuditLog.query.filter_by(module='customer', action='create').first()
    assert entry is not None
    vals = json.loads(entry.new_values)
    for field in ['code', 'name', 'contact_person', 'phone', 'email', 'tin',
                  'payment_terms', 'address', 'postal_code', 'default_vat_category',
                  'default_wt_code', 'is_active']:
        assert field in vals, f'audit snapshot missing {field}'
    assert vals['code'] == 'C001'
    assert vals['name'] == 'Audited Corp'


def test_customer_create_audit_captures_withholding_taxes_str(
        client, db_session, accountant_user, main_branch):
    """The audit new_values snapshot records the assigned WHT codes (withholding_taxes_str)."""
    import json
    from app.audit.models import AuditLog
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    db_session.add(wt)
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    client.post('/customers/create', data={
        'code': 'C950', 'name': 'WHT Audited', 'payment_terms': 'Net 30',
        'is_active': '1', 'withholding_tax_ids': [str(wt.id)],
    }, follow_redirects=True)

    entry = AuditLog.query.filter_by(module='customer', action='create').first()
    assert entry is not None
    vals = json.loads(entry.new_values)
    assert vals.get('withholding_taxes_str') == 'WC158'


def test_generate_next_customer_code_is_numeric_safe_past_999(db_session):
    """Code sequencing must be numeric, not lexicographic.

    With C999 and C1000 both present, the next code must be C1001. A lexicographic
    order_by(code.desc()) wrongly ranks 'C999' above 'C1000' and re-proposes the
    already-taken C1000.
    """
    from app.customers.models import Customer
    from app.customers.views import generate_next_customer_code

    db_session.add(Customer(code='C999', name='Niner Corp',
                            payment_terms='Net 30', is_active=True))
    db_session.add(Customer(code='C1000', name='Kilo Corp',
                            payment_terms='Net 30', is_active=True))
    db_session.commit()

    assert generate_next_customer_code() == 'C1001'


def test_customer_export_excel_blocked_for_viewer(
        client, db_session, viewer_user, main_branch):
    """A viewer cannot export the customer list (PII) — export is accountant/admin only."""
    viewer_user.add_branch(main_branch)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': viewer_user.username,
                                'password': 'viewer123'}, follow_redirects=True)

    resp = client.get('/customers/export/excel', follow_redirects=False)

    assert resp.status_code == 302, 'viewer should be redirected by the role gate'
    assert '/dashboard' in resp.headers.get('Location', ''), \
        'role gate redirects to dashboard, not the spreadsheet'


def test_customer_export_csv_blocked_for_viewer(
        client, db_session, viewer_user, main_branch):
    """A viewer cannot export the customer list as CSV."""
    viewer_user.add_branch(main_branch)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': viewer_user.username,
                                'password': 'viewer123'}, follow_redirects=True)

    resp = client.get('/customers/export/csv', follow_redirects=False)

    assert resp.status_code == 302, 'viewer should be redirected by the role gate'
    assert '/dashboard' in resp.headers.get('Location', '')


def test_customer_export_excel_allowed_for_accountant(
        client, db_session, accountant_user, main_branch):
    """An accountant can still export the customer list (gate must not over-block)."""
    _login_accountant(client, accountant_user, main_branch)

    resp = client.get('/customers/export/excel', follow_redirects=False)

    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers.get('Content-Type', '')


def test_customer_delete_succeeds_without_dependents(
        client, db_session, accountant_user, main_branch):
    """A customer with no transactions is deleted and the delete is audit-logged."""
    from app.customers.models import Customer
    from app.audit.models import AuditLog

    cust = Customer(code='C003', name='Free Corp', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()
    cust_id = cust.id

    _login_accountant(client, accountant_user, main_branch)
    resp = client.post(f'/customers/{cust_id}/delete', follow_redirects=True)

    assert resp.status_code == 200
    assert db.session.get(Customer, cust_id) is None
    assert AuditLog.query.filter_by(
        module='customer', action='delete', record_id=cust_id).count() == 1


def test_create_json_returns_customer_on_success(
        client, db_session, accountant_user, main_branch):
    """AJAX POST to customers.create returns ok=True + the new customer's id/label."""
    import json
    from app.customers.models import Customer
    from app.audit.models import AuditLog
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': 'Quick Corp',
                             'payment_terms': 'Net 30', 'is_active': '1',
                             'default_vat_category': '', 'default_wt_code': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body['ok'] is True
    cust = Customer.query.filter_by(code='C001').first()
    assert cust is not None
    assert body['customer']['id'] == cust.id
    assert body['customer']['label'] == 'C001 - Quick Corp'
    assert AuditLog.query.filter_by(module='customer', action='create',
                                    record_id=cust.id).count() == 1


def test_create_json_duplicate_code_returns_422(
        client, db_session, accountant_user, main_branch):
    """A duplicate code on the JSON path returns 422 with a code error (no HTML)."""
    import json
    from app.customers.models import Customer
    db_session.add(Customer(code='C001', name='Existing', payment_terms='Net 30',
                            is_active=True))
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': 'Dupe', 'payment_terms': 'Net 30',
                             'is_active': '1', 'default_vat_category': '',
                             'default_wt_code': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 422
    body = json.loads(resp.data)
    assert body['ok'] is False
    assert 'code' in body['errors']


def test_create_json_invalid_returns_422(
        client, db_session, accountant_user, main_branch):
    """Missing required name on the JSON path returns 422 with a field error."""
    import json
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': '', 'payment_terms': 'Net 30',
                             'is_active': '1', 'default_vat_category': '',
                             'default_wt_code': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 422
    body = json.loads(resp.data)
    assert body['ok'] is False
    assert 'name' in body['errors']


def test_staff_can_create_customer(client, db_session, staff_user, main_branch):
    """Access change: staff (not just accountant/admin) may create a customer."""
    from app.customers.models import Customer
    staff_user.set_branches([main_branch])
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': 'staff', 'password': 'staff123'},
                follow_redirects=True)

    resp = client.post('/customers/create',
                       data={'code': 'C001', 'name': 'Staff Made Corp',
                             'payment_terms': 'Net 30', 'is_active': '1',
                             'default_vat_category': '', 'default_wt_code': ''},
                       follow_redirects=True)

    assert resp.status_code == 200
    assert Customer.query.filter_by(code='C001').first() is not None


def test_customer_create_persists_withholding_taxes(
        client, db_session, accountant_user, main_branch):
    """Creating a customer with withholding_tax_ids persists the many-to-many relationship."""
    from app.customers.models import Customer
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    db_session.add(wt)
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)
    resp = client.post('/customers/create', data={
        'code': 'C900', 'name': 'WHT Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'withholding_tax_ids': [str(wt.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    c = Customer.query.filter_by(code='C900').first()
    assert c is not None
    assert [w.code for w in c.withholding_taxes] == ['WC158']
    assert c.withholding_taxes_str == 'WC158'


def test_customer_edit_updates_withholding_taxes(
        client, db_session, accountant_user, main_branch):
    """Editing a customer replaces the withholding_taxes relationship."""
    from app.customers.models import Customer
    from app.withholding_tax.models import WithholdingTax
    a = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    b = WithholdingTax(code='WC160', name='Services', rate=2.00, is_active=True)
    db_session.add_all([a, b])
    c = Customer(code='C901', name='Edit Corp', payment_terms='Net 30', is_active=True)
    c.withholding_taxes = [a]
    db_session.add(c)
    db_session.commit()
    cid = c.id
    _login_accountant(client, accountant_user, main_branch)
    resp = client.post(f'/customers/{cid}/edit', data={
        'code': 'C901', 'name': 'Edit Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'withholding_tax_ids': [str(b.id)],
    }, follow_redirects=True)
    assert resp.status_code == 200
    updated = db.session.get(Customer, cid)
    assert [w.code for w in updated.withholding_taxes] == ['WC160']


def test_customer_quick_add_json_persists_wht(
        client, db_session, accountant_user, main_branch):
    """WHT codes POSTed to the quick-add JSON endpoint are persisted on the new customer."""
    from app.customers.models import Customer
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    db_session.add(wt)
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)
    resp = client.post('/customers/create',
        data={'code': 'C902', 'name': 'QA Corp', 'payment_terms': 'Net 30',
              'is_active': '1', 'withholding_tax_ids': [str(wt.id)]},
        headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200 and resp.get_json()['ok'] is True
    c = Customer.query.filter_by(code='C902').first()
    assert [w.code for w in c.withholding_taxes] == ['WC158']


# ---------------------------------------------------------------------------
# B-10: warn-but-allow on duplicate customer names (case-insensitive)
# ---------------------------------------------------------------------------

def test_customer_create_duplicate_name_warns_and_saves(
        client, db_session, accountant_user, main_branch):
    """Creating two customers with the same name (different case) warns and saves both."""
    import html as html_mod
    from app.customers.models import Customer
    _login_accountant(client, accountant_user, main_branch)
    # Create first customer
    client.post('/customers/create', data={
        'code': 'C101', 'name': 'Acme Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_vat_category': '', 'default_wt_code': '',
    }, follow_redirects=True)
    # Create second customer with different-cased name
    resp = client.post('/customers/create', data={
        'code': 'C102', 'name': 'acme corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_vat_category': '', 'default_wt_code': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    # Both customers must be saved (warn-but-allow, not a block)
    count = Customer.query.filter(Customer.name.ilike('acme corp')).count()
    assert count == 2, f"Expected 2 customers with name 'acme corp' but got {count}"
    # Warning flash must be present
    body = html_mod.unescape(resp.data.decode())
    assert 'already exists' in body


def test_customer_create_unique_name_no_warning(
        client, db_session, accountant_user, main_branch):
    """Creating a customer with a unique name shows no duplicate-name warning."""
    _login_accountant(client, accountant_user, main_branch)
    resp = client.post('/customers/create', data={
        'code': 'C103', 'name': 'Totally Unique Customer 9999', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_vat_category': '', 'default_wt_code': '',
    }, follow_redirects=True)
    body = resp.data.decode()
    assert 'already exists' not in body


def test_customer_edit_keeping_own_name_no_warning(
        client, db_session, accountant_user, main_branch):
    """Editing a customer while keeping its own name must NOT trigger a duplicate warning."""
    import html as html_mod
    from app.customers.models import Customer
    _login_accountant(client, accountant_user, main_branch)
    c = Customer(code='C104', name='Self Name Corp', payment_terms='Net 30', is_active=True)
    db_session.add(c)
    db_session.commit()
    resp = client.post(f'/customers/{c.id}/edit', data={
        'code': 'C104', 'name': 'Self Name Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_vat_category': '', 'default_wt_code': '',
    }, follow_redirects=True)
    body = html_mod.unescape(resp.data.decode())
    assert 'already exists' not in body


def test_customer_create_persists_po_required(
        client, db_session, accountant_user, main_branch):
    """Ticking 'Requires Purchase Order' on create persists po_required=True."""
    from app.customers.models import Customer

    _login_accountant(client, accountant_user, main_branch)
    client.post('/customers/create', data={
        'code': 'C-POREQ', 'name': 'PO Required Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_vat_category': '', 'default_wt_code': '',
        'po_required': 'y',
    }, follow_redirects=True)
    c = Customer.query.filter_by(code='C-POREQ').first()
    assert c is not None and c.po_required is True
