"""SI pre-printed layout: the elements Philgen's legacy invoice prints that CAS lacked (owner, 3 Nov 2026).

Legacy salvejesalva `delivery/print_invoice.html` prints right-justified totals, the DR number, the
buyer's business style, a note under each line, a "**NOTHING FOLLOWS**" marker and a MM-DD-YYYY date.
CAS is shared by several clients, so every new element must default to hidden/off: an existing
layout renders exactly as before until someone places the element in the designer.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_invoices.preprinted_layout import (
    DEFAULT_SV_PREPRINTED_LAYOUT, _layout_key, get_layout, sanitize_layout)
from app.settings import AppSettings

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


@pytest.fixture
def _customer(db_session):
    c = Customer(code='C002', name='MEMER FOOD DEALER', payment_terms='Net 30', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def _product(db_session):
    from app.products.models import Product
    p = Product(code='P-616', name='A ONE DRIED PAPAYA CHUNKS 100g', is_active=True)
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def _invoice(db_session, main_branch, _customer, _product):
    inv = SalesInvoice(
        branch_id=main_branch.id, invoice_number='0261', invoice_date=date(2026, 9, 25),
        due_date=date(2026, 10, 25), customer_id=_customer.id, customer_name=_customer.name,
        reference='DR 0257', notes='', status='draft', amount_paid=Decimal('0.00'),
        subtotal=Decimal('16800.00'), vat_amount=Decimal('1800.00'), total_amount=Decimal('16800.00'))
    db_session.add(inv)
    db_session.flush()
    db_session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='5 BOXES',
                                    product_id=_product.id, quantity=Decimal('25'),
                                    unit_price=Decimal('672.00'), amount=Decimal('16800.00')))
    db_session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=2, description='FREIGHT',
                                    product_id=None, amount=Decimal('0.00')))
    db_session.commit()
    return inv


def _save(branch_id, mutate):
    layout = get_layout(branch_id)
    mutate(layout)
    AppSettings.set_setting(_layout_key(branch_id), json.dumps(layout), 'system')


def _print_html(client, invoice):
    AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
    AppSettings.set_setting('sv_print_form', 'preprinted', 'system')
    login(client)
    resp = client.get(f'/sales-invoices/{invoice.id}/print')
    assert resp.status_code == 200
    return resp.data.decode()


def _el(html, key):
    """The opening tag and text of the primary (non-copy) field element `key`."""
    m = re.search(r'(<div class="([^"]*)" data-el="%s"(?![^>]*data-extra)[^>]*>)([^<]*)</div>' % key, html)
    assert m, f'no element for {key}'
    return m.group(1), m.group(2), m.group(3).strip()


# --- the layout checker -------------------------------------------------------------------------

class TestSanitizer:
    def test_new_elements_default_hidden(self):
        clean = sanitize_layout({})
        assert clean['fields']['dr_number']['hidden'] is True
        assert clean['fields']['customer_business_style']['hidden'] is True
        note = [c for c in clean['lineItems']['columns'] if c['key'] == 'note'][0]
        assert note['visible'] is False
        assert clean['lineItems']['endMarker']['visible'] is False

    def test_layout_saved_before_the_new_elements_keeps_them_hidden(self):
        old = json.loads(json.dumps(DEFAULT_SV_PREPRINTED_LAYOUT))
        for k in ('dr_number', 'customer_business_style'):
            old['fields'].pop(k, None)
        old['lineItems']['columns'] = [c for c in old['lineItems']['columns'] if c['key'] != 'note']
        old['lineItems'].pop('endMarker', None)
        clean = sanitize_layout(old)
        assert clean['fields']['dr_number']['hidden'] is True
        assert [c for c in clean['lineItems']['columns'] if c['key'] == 'note'][0]['visible'] is False
        assert clean['lineItems']['endMarker']['visible'] is False
        # existing fields keep today's left alignment and content width
        assert clean['fields']['gross_sales']['align'] == 'left'
        assert clean['fields']['gross_sales']['width'] == 0

    def test_align_and_width_kept_and_clamped(self):
        raw = {'fields': {'gross_sales': {'x': 646, 'y': 733, 'fontSize': 14, 'bold': True,
                                          'align': 'right', 'width': 113},
                          'output_vat': {'x': 646, 'y': 752, 'align': 'centre', 'width': 99999}},
               'extras': [{'key': 'net_of_vat', 'x': 208, 'y': 756, 'fontSize': 14,
                           'align': 'right', 'width': 113}]}
        clean = sanitize_layout(raw)
        assert clean['fields']['gross_sales']['align'] == 'right'
        assert clean['fields']['gross_sales']['width'] == 113
        assert clean['fields']['output_vat']['align'] == 'left'       # unknown value -> left
        assert clean['fields']['output_vat']['width'] == 912          # clamped to the canvas
        assert clean['extras'][0]['align'] == 'right'
        assert clean['extras'][0]['width'] == 113

    def test_column_row_offset_kept_and_clamped(self):
        raw = {'lineItems': {'columns': [{'key': 'note', 'x': 181, 'visible': True, 'width': 300, 'dy': 17},
                                         {'key': 'amount', 'x': 650, 'visible': True, 'width': 121, 'dy': -500}]}}
        cols = {c['key']: c for c in sanitize_layout(raw)['lineItems']['columns']}
        assert cols['note']['dy'] == 17
        assert cols['amount']['dy'] == -80                             # clamped to -ROW_MAX
        assert cols['product']['dy'] == 0

    def test_end_marker_kept(self):
        raw = {'lineItems': {'endMarker': {'text': '  **NOTHING FOLLOWS**  ', 'x': 357, 'dy': 14,
                                           'visible': True}}}
        em = sanitize_layout(raw)['lineItems']['endMarker']
        assert em == {'text': '**NOTHING FOLLOWS**', 'x': 357, 'dy': 14, 'visible': True}

    def test_dashed_us_date_format_allowed(self):
        assert sanitize_layout({'dateFormat': 'us_dash'})['dateFormat'] == 'us_dash'


# --- the print page ------------------------------------------------------------------------------

class TestPrint:
    def test_default_layout_does_not_show_new_elements(self, client, db_session, admin_user,
                                                       main_branch, _invoice):
        html = _print_html(client, _invoice)
        assert 'pp-field-hidden' in _el(html, 'dr_number')[1]
        assert 'pp-field-hidden' in _el(html, 'customer_business_style')[1]
        note = re.search(r'<div class="([^"]*)"\s+data-col="note"', html)
        assert note and 'pp-col-hidden' in note.group(1)
        assert re.search(r'class="pp-el pp-endmark pp-field-hidden"', html)

    def test_right_aligned_field_has_box_width(self, client, db_session, admin_user,
                                               main_branch, _invoice):
        def m(l):
            l['fields']['gross_sales'].update(align='right', width=113)
        _save(main_branch.id, m)
        tag, _cls, text = _el(_print_html(client, _invoice), 'gross_sales')
        assert 'width:113px;text-align:right;' in tag
        assert text == '16,800.00'
        # a left field carries no forced width
        assert 'text-align:right' not in _el(_print_html(client, _invoice), 'output_vat')[0]

    def test_right_aligned_copy_has_box_width(self, client, db_session, admin_user,
                                              main_branch, _invoice):
        def m(l):
            l['extras'] = [{'key': 'net_of_vat', 'x': 208, 'y': 756, 'fontSize': 14, 'bold': True,
                            'align': 'right', 'width': 113}]
        _save(main_branch.id, m)
        html = _print_html(client, _invoice)
        tag = re.search(r'<div class="pp-el" data-el="net_of_vat"[^>]*data-extra="1"[^>]*>', html).group(0)
        assert 'width:113px;text-align:right;' in tag

    def test_dr_number_falls_back_to_reference(self, client, db_session, admin_user,
                                               main_branch, _invoice):
        assert _el(_print_html(client, _invoice), 'dr_number')[2] == 'DR 0257'

    def test_dr_number_lists_billed_drs(self, client, db_session, admin_user, main_branch,
                                        _customer, _invoice):
        from app.sales_orders.models import SalesOrder
        from app.delivery_receipts.models import DeliveryReceipt
        so = SalesOrder(branch_id=main_branch.id, so_number='SO-1', order_date=date(2026, 9, 20),
                        customer_id=_customer.id, customer_name=_customer.name, status='confirmed')
        db_session.add(so)
        db_session.flush()
        for num, d in (('00259', date(2026, 9, 24)), ('00257', date(2026, 9, 23))):
            db_session.add(DeliveryReceipt(dr_number=num, branch_id=main_branch.id, delivery_date=d,
                                           sales_order_id=so.id, customer_id=_customer.id,
                                           customer_name=_customer.name, status='billed',
                                           sales_invoice_id=_invoice.id))
        db_session.commit()
        assert _el(_print_html(client, _invoice), 'dr_number')[2] == '00257, 00259'   # by delivery date

    def test_business_style_from_customer(self, client, db_session, admin_user, main_branch,
                                          _customer, _invoice):
        _customer.business_style = 'Food Repacking and Distribution'
        db_session.commit()
        assert _el(_print_html(client, _invoice), 'customer_business_style')[2] == \
            'Food Repacking and Distribution'

    def test_blank_business_style_prints_nothing(self, client, db_session, admin_user,
                                                 main_branch, _invoice):
        assert _el(_print_html(client, _invoice), 'customer_business_style')[2] == ''

    def test_dashed_date(self, client, db_session, admin_user, main_branch, _invoice):
        _save(main_branch.id, lambda l: l.update(dateFormat='us_dash'))
        html = _print_html(client, _invoice)
        assert _el(html, 'invoice_date')[2] == '09-25-2026'
        assert '<option value="us_dash"' in html             # the designer's dropdown offers it

    def test_note_column_prints_description_of_product_lines_only(self, client, db_session,
                                                                  admin_user, main_branch, _invoice):
        def m(l):
            for c in l['lineItems']['columns']:
                if c['key'] == 'note':
                    c.update(visible=True, x=181, dy=17)
        _save(main_branch.id, m)
        html = _print_html(client, _invoice)
        col = re.search(r'<div class="pp-col"\s+data-col="note"[^>]*style="([^"]*)"', html)
        assert col, 'note column not rendered visible'
        assert f'top:{get_layout(main_branch.id)["lineItems"]["y"] + 17}px' in col.group(1)
        segment = html[col.end():html.index('pp-endmark', col.end())]   # note is the last column
        cells = [c.strip() for c in re.findall(r'<div class="pp-cell"[^>]*>([^<]*)</div>', segment)]
        assert cells == ['5 BOXES', '']          # line 2 has no product: its description is the product text

    def test_end_marker_after_last_row(self, client, db_session, admin_user, main_branch, _invoice):
        def m(l):
            l['lineItems'].update(y=360, rowHeight=34)
            l['lineItems']['endMarker'] = {'text': '**NOTHING FOLLOWS**', 'x': 357, 'dy': 14, 'visible': True}
        _save(main_branch.id, m)
        html = _print_html(client, _invoice)
        tag = re.search(r'<div class="pp-el pp-endmark"[^>]*>\s*\*\*NOTHING FOLLOWS\*\*\s*</div>', html)
        assert tag, 'end marker not rendered'
        assert 'left:357px;top:442px;' in tag.group(0)      # 360 + 2 rows x 34 + 14


# --- business style on the customer record -------------------------------------------------------

class TestCustomerBusinessStyle:
    def _login(self, client, accountant_user, main_branch):
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        client.post('/login', data={'username': accountant_user.username, 'password': 'accountant123'},
                    follow_redirects=True)

    def test_create_saves_and_audits_business_style(self, client, db_session, accountant_user, main_branch):
        from app.audit.models import AuditLog
        self._login(client, accountant_user, main_branch)
        client.post('/customers/create', data={
            'code': 'C950', 'name': 'Styled Corp', 'payment_terms': 'Net 30', 'is_active': '1',
            'default_vat_category': '', 'default_wt_code': '',
            'business_style': 'Food Repacking and Distribution'}, follow_redirects=True)
        cust = Customer.query.filter_by(code='C950').first()
        assert cust.business_style == 'Food Repacking and Distribution'
        entry = AuditLog.query.filter_by(module='customer', action='create').first()
        assert json.loads(entry.new_values)['business_style'] == 'Food Repacking and Distribution'

    def test_csv_export_columns_stay_under_their_headers(self, client, db_session, accountant_user,
                                                         main_branch):
        import csv
        import io
        db_session.add(Customer(code='C952', name='Export Style Corp', tin='123-456-789-000',
                                business_style='Food Repacking and Distribution',
                                payment_terms='Net 60', is_active=True))
        db_session.commit()
        self._login(client, accountant_user, main_branch)
        rows = list(csv.reader(io.StringIO(client.get('/customers/export/csv').data.decode('utf-8-sig'))))
        header_row = next(r for r in rows if 'Customer Code' in r)
        row = dict(zip(header_row, next(r for r in rows if 'C952' in r)))
        assert row['TIN'] == '123-456-789-000'
        assert row['Business Style'] == 'Food Repacking and Distribution'
        assert row['Payment Terms'] == 'Net 60'
        assert row['Active'] == 'Yes'

    def test_edit_updates_business_style(self, client, db_session, accountant_user, main_branch):
        c = Customer(code='C951', name='Edit Style Corp', payment_terms='Net 30', is_active=True)
        db_session.add(c)
        db_session.commit()
        self._login(client, accountant_user, main_branch)
        page = client.get(f'/customers/{c.id}/edit').data.decode()
        assert 'name="business_style"' in page
        client.post(f'/customers/{c.id}/edit', data={
            'code': 'C951', 'name': 'Edit Style Corp', 'payment_terms': 'Net 30', 'is_active': '1',
            'default_vat_category': '', 'default_wt_code': '', 'business_style': 'Trading'},
            follow_redirects=True)
        db_session.refresh(c)
        assert c.business_style == 'Trading'
        assert 'Trading' in client.get(f'/customers/{c.id}').data.decode()
