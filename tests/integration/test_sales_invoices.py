import pytest
from decimal import Decimal
from datetime import date


@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def revenue_account(db_session):
    from app.accounts.models import Account
    a = Account(code='40001', name='Service Revenue', account_type='Revenue',
                normal_balance='credit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if not b:
        b = Branch(name='Main Branch', code='MB', is_active=True)
        db_session.add(b)
        db_session.commit()
    return b


def test_sales_invoice_has_required_fields(db_session, customer, branch):
    from app.sales_invoices.models import SalesInvoice
    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-0001',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    assert inv.journal_entry_id is None
    assert inv.withholding_tax_amount == Decimal('0.00')
    assert inv.vat_override is False
    assert inv.wt_override is False
    assert inv.total_before_wt == Decimal('0.00')
    assert inv.customer_po_number is None


def test_sales_invoice_calculate_totals_no_items(db_session, customer, branch):
    """calculate_totals() with no line items zeros all totals (AccountsPayable pattern)."""
    from app.sales_invoices.models import SalesInvoice
    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-0002',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    inv.calculate_totals()
    assert inv.subtotal == Decimal('0.00')
    assert inv.total_before_wt == Decimal('0.00')
    assert inv.total_amount == Decimal('0.00')
    assert inv.balance == Decimal('0.00')


@pytest.fixture
def wht_code(db_session):
    from app.withholding_tax.models import WithholdingTax
    w = WithholdingTax(code='WC010', name='EWT 10%', rate=Decimal('10.00'), is_active=True)
    db_session.add(w)
    db_session.commit()
    return w


def test_invoice_item_calculate_amounts_vat_inclusive(db_session, revenue_account, wht_code):
    from app.sales_invoices.models import SalesInvoiceItem
    item = SalesInvoiceItem(
        line_number=1,
        description='Service',
        amount=Decimal('11200.00'),
        vat_rate=Decimal('12.00'),
        wt_rate=Decimal('10.00'),
        account_id=revenue_account.id,
    )
    item.calculate_amounts()
    # VAT-inclusive: net_base = 11200 / 1.12 = 10000
    net_base = Decimal('11200.00') / Decimal('1.12')
    expected_vat = (Decimal('11200.00') - net_base).quantize(Decimal('0.01'))
    expected_wt = (net_base * Decimal('0.10')).quantize(Decimal('0.01'))
    assert item.line_total == Decimal('11200.00')
    assert abs(item.vat_amount - expected_vat) < Decimal('0.02')
    assert abs(item.wt_amount - expected_wt) < Decimal('0.02')


def test_invoice_item_zero_vat(db_session, revenue_account):
    from app.sales_invoices.models import SalesInvoiceItem
    item = SalesInvoiceItem(
        line_number=1,
        description='Exempt Service',
        amount=Decimal('5000.00'),
        vat_rate=Decimal('0.00'),
        account_id=revenue_account.id,
    )
    item.calculate_amounts()
    assert item.line_total == Decimal('5000.00')
    assert item.vat_amount == Decimal('0.00')
    assert item.wt_amount == Decimal('0.00')


def test_invoice_attachment_model_structure(db_session):
    from app.sales_invoices.models import SalesInvoiceAttachment
    col_names = [c.name for c in SalesInvoiceAttachment.__table__.columns]
    assert 'invoice_id' in col_names
    assert 'stored_filename' in col_names
    assert 'mime_type' in col_names
    assert 'file_size' in col_names
    assert 'uploaded_by_id' in col_names


def test_post_invoice_je_creates_balanced_entry(db_session, customer, revenue_account, branch, accountant_user):
    """_post_invoice_je creates a balanced JE with correct debit/credit structure."""
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.accounts.models import Account
    from app.sales_vat_categories.models import SalesVATCategory

    # Create required GL accounts
    ar = Account.query.filter_by(code='10201').first()
    if not ar:
        ar = Account(code='10201', name='AR - Trade', account_type='Asset',
                     normal_balance='debit', is_active=True)
        db_session.add(ar)

    output_vat = Account.query.filter_by(code='20201').first()
    if not output_vat:
        output_vat = Account(code='20201', name='Output VAT', account_type='Liability',
                             normal_balance='credit', is_active=True)
        db_session.add(output_vat)
    db_session.flush()

    vat_cat = SalesVATCategory.query.filter_by(code='V12TEST').first()
    if not vat_cat:
        vat_cat = SalesVATCategory(code='V12TEST', name='VAT 12% Test', rate=Decimal('12.00'),
                                   transaction_nature='regular',
                                   output_vat_account_id=output_vat.id)
        db_session.add(vat_cat)
    db_session.flush()

    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-JE01',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.flush()

    item = SalesInvoiceItem(
        invoice_id=inv.id, line_number=1, description='Service',
        amount=Decimal('11200.00'), vat_category='V12TEST',
        vat_rate=Decimal('12.00'), account_id=revenue_account.id,
    )
    item.calculate_amounts()
    db_session.add(item)
    db_session.flush()
    inv.calculate_totals()

    from app.sales_invoices import views as sv_views
    je = sv_views._post_invoice_je(inv, accountant_user.id)
    db_session.flush()

    assert je.is_balanced
    assert je.total_debit == je.total_credit
    # AR is a debit; revenue + output VAT are credits
    debit_lines = [l for l in je.lines if l.debit_amount > 0]
    credit_lines = [l for l in je.lines if l.credit_amount > 0]
    assert len(debit_lines) >= 1  # AR at minimum
    assert len(credit_lines) >= 1  # Revenue at minimum


def test_post_invoice_je_line_order(db_session, customer, revenue_account, branch, accountant_user):
    """JE lines read debits-first: AR, Creditable WHT, Output VAT, Sales (matches APV)."""
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.accounts.models import Account
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax

    def _acct(code, name, typ, nb):
        a = Account.query.filter_by(code=code).first()
        if not a:
            a = Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True)
            db_session.add(a)
            db_session.flush()
        return a

    _acct('10201', 'AR - Trade', 'Asset', 'debit')
    _acct('10212', 'Creditable WHT Receivable', 'Asset', 'debit')
    ovat = _acct('20201', 'Output VAT', 'Liability', 'credit')

    if not SalesVATCategory.query.filter_by(code='V12ORD').first():
        db_session.add(SalesVATCategory(code='V12ORD', name='VAT 12% Ord', rate=Decimal('12.00'),
                                        transaction_nature='regular', output_vat_account_id=ovat.id))
    if not WithholdingTax.query.filter_by(code='WC999').first():
        db_session.add(WithholdingTax(code='WC999', name='Test WHT', rate=Decimal('1.00'), is_active=True))
    db_session.flush()
    wt = WithholdingTax.query.filter_by(code='WC999').first()

    inv = SalesInvoice(branch_id=branch.id, invoice_number='SI-ORD-01',
                       invoice_date=date(2026, 6, 14), due_date=date(2026, 7, 14),
                       customer_id=customer.id, customer_name=customer.name, notes='',
                       status='draft', amount_paid=Decimal('0.00'))
    db_session.add(inv)
    db_session.flush()
    item = SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='Service',
                            amount=Decimal('11200.00'), vat_category='V12ORD', vat_rate=Decimal('12.00'),
                            account_id=revenue_account.id, wt_id=wt.id, wt_rate=Decimal('1.00'))
    item.calculate_amounts()
    db_session.add(item)
    db_session.flush()
    inv.calculate_totals()
    assert inv.withholding_tax_amount > 0  # ensure a Creditable WHT line is emitted

    from app.sales_invoices import views as sv_views
    je = sv_views._post_invoice_je(inv, accountant_user.id)
    db_session.flush()

    ordered = sorted(je.lines, key=lambda l: l.line_number)
    codes = [l.account.code for l in ordered]
    assert codes == ['10201', '10212', '20201', revenue_account.code]
    assert ordered[0].debit_amount > 0 and ordered[1].debit_amount > 0   # AR, CWT
    assert ordered[2].credit_amount > 0 and ordered[3].credit_amount > 0  # Output VAT, Sales
    assert je.is_balanced


def test_create_error_preserves_customer_and_line_items(client, db_session, accountant_user, customer, revenue_account, branch):
    """A failed save (blank line description) must re-render WITH the user's customer and
    line items intact — not a blank form forcing full re-entry."""
    import json as _json
    import re
    from app.accounts.models import Account
    if not Account.query.filter_by(code='10201').first():
        db_session.add(Account(code='10201', name='AR - Trade', account_type='Asset',
                               normal_balance='debit', is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    bad_line = {'description': '', 'amount': '1000.00', 'vat_category': '',
                'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id)}
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-ERR-01',
        'invoice_date': '2026-06-14',
        'due_date': '2026-07-14',
        'customer_id': str(customer.id),
        'payment_terms': 'Net 30',
        'notes': 'x',
        'line_items': _json.dumps([bad_line]),
    })
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200                                  # re-render, not redirect
    assert 'Each line item must have a description.' in body        # user is notified
    # line items survive: the row-seed must carry the submitted line (with its amount)
    assert 'existingItems' in body and '1000' in body
    # customer survives: its option is re-selected (not reset to the placeholder)
    assert re.search(r'value="%d"[^>]*selected' % customer.id, body) is not None


def test_edit_error_preserves_submitted_line_items(client, db_session, accountant_user, customer, revenue_account, branch):
    """A failed edit must re-render with the user's SUBMITTED line edits, not revert to the saved lines."""
    import json as _json
    inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    # User changes the amount to a distinctive value but blanks the description -> validation fails.
    bad_line = {'description': '', 'amount': '777777.00', 'vat_category': '',
                'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id)}
    resp = client.post(f'/sales-invoices/{inv.id}/edit', data={
        'invoice_number': inv.invoice_number,
        'invoice_date': '2026-06-14',
        'due_date': '2026-07-14',
        'customer_id': str(customer.id),
        'payment_terms': 'Net 30',
        'notes': 'x',
        'line_items': _json.dumps([bad_line]),
    })
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'Each line item must have a description.' in body
    # The submitted edit (777777) survives — not reverted to the saved line.
    assert 'existingItems' in body and '777777' in body


def test_create_error_flash_shown_once(client, db_session, accountant_user, customer, revenue_account, branch):
    """The validation flash must appear exactly once — not duplicated by a redundant render."""
    import json as _json
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    bad_line = {'description': '', 'amount': '1000.00', 'vat_category': '',
                'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id)}
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-ONCE-01', 'invoice_date': '2026-06-14', 'due_date': '2026-07-14',
        'customer_id': str(customer.id), 'payment_terms': 'Net 30', 'notes': 'x',
        'line_items': _json.dumps([bad_line]),
    })
    body = resp.get_data(as_text=True)
    assert body.count('Each line item must have a description.') == 1


def test_create_invoice_notes_optional(client, db_session, accountant_user, customer, revenue_account, branch):
    """Notes is optional for SI: a valid invoice saves with notes omitted entirely."""
    import json as _json
    from app.accounts.models import Account
    from app.sales_invoices.models import SalesInvoice
    for code, name, typ, nb in [('10201', 'AR - Trade', 'Asset', 'debit'),
                                ('20201', 'Output VAT', 'Liability', 'credit')]:
        if not Account.query.filter_by(code=code).first():
            db_session.add(Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    line = {'description': 'Service', 'amount': '5000.00', 'vat_category': '',
            'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id)}
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-NONOTES-01', 'invoice_date': '2026-06-14', 'due_date': '2026-07-14',
        'customer_id': str(customer.id), 'payment_terms': 'Net 30',
        # notes intentionally omitted
        'line_items': _json.dumps([line]),
    }, follow_redirects=False)

    assert resp.status_code == 302  # saved (redirect), not re-rendered with a validation error
    inv = SalesInvoice.query.filter_by(invoice_number='SI-NONOTES-01').first()
    assert inv is not None and inv.notes == ''


def test_create_invoice_posts_to_books(client, db_session, accountant_user, customer, revenue_account, branch):
    """Creating an SV saves draft JE and audit log entry."""
    from app.accounts.models import Account
    from app.audit.models import AuditLog
    from app.sales_invoices.models import SalesInvoice
    import json as _json

    # Ensure GL accounts exist
    if not Account.query.filter_by(code='10201').first():
        db_session.add(Account(code='10201', name='AR - Trade', account_type='Asset',
                               normal_balance='debit', is_active=True))
    if not Account.query.filter_by(code='20201').first():
        db_session.add(Account(code='20201', name='Output VAT', account_type='Liability',
                               normal_balance='credit', is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    line_item = {
        'description': 'Consulting', 'amount': '11200.00',
        'vat_category': '', 'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id),
    }
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-2026-0001',
        'invoice_date': '2026-06-14',
        'due_date': '2026-07-14',
        'customer_id': str(customer.id),
        'payment_terms': 'Net 30',
        'notes': 'Test invoice',
        'line_items': _json.dumps([line_item]),
    })

    assert resp.status_code == 302
    inv = SalesInvoice.query.filter_by(invoice_number='SI-2026-0001').first()
    assert inv is not None
    assert inv.journal_entry_id is not None
    assert inv.total_amount == Decimal('11200.00')

    audit = AuditLog.query.filter_by(module='sales_invoice', action='create',
                                     record_id=inv.id).first()
    assert audit is not None
    assert audit.user_id == accountant_user.id


def _make_draft_invoice(db_session, customer, revenue_account, branch, user):
    """Helper: create a draft SV with one line item and a linked draft JE."""
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.accounts.models import Account

    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-TEST',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status='draft',
        subtotal=Decimal('10000.00'),
        vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('10000.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('10000.00'),
        amount_paid=Decimal('0.00'),
        balance=Decimal('10000.00'),
        created_by_id=user.id,
    )
    db_session.add(inv)
    db_session.flush()

    item = SalesInvoiceItem(
        invoice_id=inv.id, line_number=1, description='Service',
        amount=Decimal('10000.00'), vat_rate=Decimal('0.00'),
        line_total=Decimal('10000.00'), vat_amount=Decimal('0.00'),
        wt_amount=Decimal('0.00'), account_id=revenue_account.id,
    )
    db_session.add(item)

    ar = Account.query.filter_by(code='10201').first()
    if not ar:
        ar = Account(code='10201', name='AR', account_type='Asset',
                     normal_balance='debit', is_active=True)
        db_session.add(ar)
    db_session.flush()

    je = JournalEntry(
        entry_number='JE-2026-0001', entry_date=date(2026, 6, 14),
        description='Test', reference='SI-2026-TEST', entry_type='sale',
        branch_id=branch.id, created_by_id=user.id, status='draft',
        is_balanced=True, total_debit=Decimal('10000.00'), total_credit=Decimal('10000.00'),
    )
    db_session.add(je)
    db_session.flush()
    inv.journal_entry_id = je.id

    db_session.add(JournalEntryLine(
        entry_id=je.id, line_number=1, account_id=ar.id,
        description='AR', debit_amount=Decimal('10000.00'), credit_amount=Decimal('0.00')))
    db_session.add(JournalEntryLine(
        entry_id=je.id, line_number=2, account_id=revenue_account.id,
        description='Revenue', debit_amount=Decimal('0.00'), credit_amount=Decimal('10000.00')))
    db_session.commit()
    return inv


def test_post_invoice(client, db_session, accountant_user, customer, revenue_account, branch):
    from app.audit.models import AuditLog
    inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)
    resp = client.post(f'/sales-invoices/{inv.id}/post', data={'csrf_token': 'test'},
                       follow_redirects=False)
    assert resp.status_code == 302
    db_session.refresh(inv)
    assert inv.status == 'posted'
    assert inv.journal_entry.status == 'posted'
    audit = AuditLog.query.filter_by(module='sales_invoice', action='post', record_id=inv.id).first()
    assert audit is not None


def test_cancel_posted_invoice(client, db_session, accountant_user, customer, revenue_account, branch):
    from app.audit.models import AuditLog
    inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
    inv.status = 'posted'
    inv.journal_entry.status = 'posted'
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)
    resp = client.post(f'/sales-invoices/{inv.id}/cancel',
                       data={'cancel_reason': 'Customer cancelled the order',
                             'reversal_date': '2026-06-15'},
                       follow_redirects=False)
    assert resp.status_code == 302
    db_session.refresh(inv)
    assert inv.status == 'cancelled'
    audit = AuditLog.query.filter_by(module='sales_invoice', action='cancel', record_id=inv.id).first()
    assert audit is not None


def test_void_draft_invoice(client, db_session, accountant_user, customer, revenue_account, branch):
    from app.audit.models import AuditLog
    inv = _make_draft_invoice(db_session, customer, revenue_account, branch, accountant_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)
    resp = client.post(f'/sales-invoices/{inv.id}/void',
                       data={'void_reason': 'Entered by mistake on wrong date',
                             'reversal_date': '2026-06-14'},
                       follow_redirects=False)
    assert resp.status_code == 302
    db_session.refresh(inv)
    assert inv.status == 'voided'
    audit = AuditLog.query.filter_by(module='sales_invoice', action='void', record_id=inv.id).first()
    assert audit is not None


def test_print_list_get_empty(client, db_session, accountant_user, branch):
    """Print list renders 200 with no invoices."""
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)
    response = client.get('/sales-invoices/print')
    assert response.status_code == 200
    assert b'SALES INVOICES' in response.data


def test_si_create_form_vat_context(client, db_session, accountant_user, branch):
    """SI create form must pass 7 VAT categories and 3 WHT codes to JS globals.

    Regression for BUG-02: empty dropdowns in dynamic line item rows caused by
    missing seed data. Verify server always sends non-empty arrays.
    """
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax

    # Seed minimal Sales VAT + WHT data (SI reads SalesVATCategory, not VATCategory)
    vat_codes = ['VEX', 'V0', 'INV', 'V12CG', 'V12DG', 'V12SV', 'V12IM']
    for code in vat_codes:
        db_session.add(SalesVATCategory(code=code, name=code, rate=0.0,
                                        transaction_nature='regular',
                                        is_active=True))
    for code in ['WC158', 'WC160', 'WC100']:
        db_session.add(WithholdingTax(code=code, name=code,
                                      description='', rate=1.0, is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    response = client.get('/sales-invoices/create')
    assert response.status_code == 200

    # All 7 VAT codes must appear in the rendered JS globals
    for code in vat_codes:
        assert code.encode() in response.data, f"VAT code {code} missing from form context"

    # All 3 WHT codes must appear
    for code in ['WC158', 'WC160', 'WC100']:
        assert code.encode() in response.data, f"WHT code {code} missing from form context"
