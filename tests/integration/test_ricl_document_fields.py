"""RICL-4a / 4e / 4d: the fields RIC's pre-printed forms carry that CAS lacked (migration riclay_0001).

Owner, 17 Nov 2026, typed in the root:
  * 4a, SI "SO No.": "If SO is activated then this can be the source. If not, the user can type the SO."
    -> printed from the sales orders behind the DRs the invoice bills; else the typed SO No. on the invoice.
  * 4e, SI Delivery Address, "A (my pick)": a typed box on the SI. When the SI is pulled from a DR whose SO line has a
    delivery site, it starts with that site's name; otherwise it is blank.
  * 4d, PO signature lines: "request by should be added and is pre-filled from PR. Philgen still does not show this in
    printouts" -> a "Requested by" on the PO, pre-filled from the requisition's Prepared by (else the requisition's
    creator), editable, typed when there is none; printed on the pre-printed layout and as a fourth signature on the
    standard print.
Every new pre-printed element arrives hidden on an existing layout (CAS serves several clients).
"""
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import db
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices, pytest.mark.purchase_orders]

_APP = Path(__file__).resolve().parents[2] / 'app'


def _session(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _so_dr(db_session, branch, customer, so_number, dr_number, site_name=None):
    from app.customers.models import CustomerDeliverySite
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    site = None
    if site_name:
        site = CustomerDeliverySite(customer_id=customer.id, name=site_name, is_active=True)
        db_session.add(site); db_session.commit()
    so = SalesOrder(so_number=so_number, order_date=date(2026, 11, 1), customer_id=customer.id,
                    customer_name=customer.name, branch_id=branch.id, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('5.00'), amount=Decimal('50.00'),
                        delivery_site_id=site.id if site else None)
    so.line_items.append(li)
    db_session.add(so); db_session.commit()
    dr = DeliveryReceipt(dr_number=dr_number, delivery_date=date(2026, 11, 5), sales_order_id=so.id,
                         customer_id=customer.id, customer_name=customer.name, status='delivered',
                         branch_id=branch.id)
    db_session.add(dr); db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('10')))
    db_session.commit()
    return so, dr


def _invoice(db_session, branch, customer, number, **kw):
    from app.sales_invoices.models import SalesInvoice
    inv = SalesInvoice(branch_id=branch.id, invoice_number=number, invoice_date=date(2026, 11, 6),
                       due_date=date(2026, 12, 6), customer_id=customer.id, customer_name=customer.name,
                       notes='', status='draft', amount_paid=Decimal('0.00'), subtotal=Decimal('50.00'),
                       vat_amount=Decimal('0.00'), total_amount=Decimal('50.00'), **kw)
    db_session.add(inv); db_session.commit()
    return inv


def _si_print(client, inv, mutate=None):
    from app.sales_invoices.preprinted_layout import _layout_key, get_layout
    if mutate:
        lay = get_layout(inv.branch_id)
        mutate(lay)
        AppSettings.set_setting(_layout_key(inv.branch_id), json.dumps(lay), 'system')
    AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
    AppSettings.set_setting('sv_print_form', 'preprinted', 'system')
    resp = client.get(f'/sales-invoices/{inv.id}/print')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _el_text(html, key):
    m = re.search(r'<div class="([^"]*)" data-el="%s"(?![^>]*data-extra)[^>]*>([^<]*)</div>' % key, html)
    assert m, f'no element for {key}'
    return m.group(1), m.group(2).strip()


class TestMigrationColumns:

    def test_the_three_columns_exist(self, db_session):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        si = {c['name'] for c in insp.get_columns('sales_invoices')}
        po = {c['name'] for c in insp.get_columns('purchase_orders')}
        assert {'so_number', 'delivery_address'} <= si
        assert 'requested_by' in po

    def test_migration_file_chains_after_cdvslip(self):
        src = (_APP.parent / 'migrations/versions/riclay_0001_ric_document_fields.py').read_text(encoding='utf-8')
        assert "revision = 'riclay_0001'" in src and "down_revision = 'cdvslip_0001'" in src


class TestSalesInvoiceFields:

    def test_billable_drs_carry_the_so_number_and_delivery_site(self, client, db_session, admin_user,
                                                               main_branch, customer):
        AppSettings.set_setting('module_enabled:sales_invoices', '1'); db_session.commit()
        _so_dr(db_session, main_branch, customer, 'SO-R-0001', 'DR-R-0001', site_name='Calamba Plant')
        _session(client, admin_user, main_branch)
        dr = client.get(f'/sales-invoices/billable-drs?customer_id={customer.id}').get_json()['drs'][0]
        assert dr['so_number'] == 'SO-R-0001'
        assert dr['delivery_site'] == 'Calamba Plant'

    def test_no_site_is_none(self, client, db_session, admin_user, main_branch, customer):
        AppSettings.set_setting('module_enabled:sales_invoices', '1'); db_session.commit()
        _so_dr(db_session, main_branch, customer, 'SO-R-0002', 'DR-R-0002')
        _session(client, admin_user, main_branch)
        dr = client.get(f'/sales-invoices/billable-drs?customer_id={customer.id}').get_json()['drs'][0]
        assert dr['delivery_site'] is None

    def test_the_dr_pull_fills_both_boxes_when_empty(self):
        js = (_APP / 'static/js/si_dr_billing.js').read_text(encoding='utf-8')
        assert re.search(r"getElementById\('so_number'\)", js)
        assert re.search(r"getElementById\('delivery_address'\)", js)
        assert 'dr.delivery_site' in js and 'dr.so_number' in js

    def test_the_form_has_both_boxes(self):
        from app.sales_invoices.forms import SalesInvoiceForm
        assert hasattr(SalesInvoiceForm, 'so_number') and hasattr(SalesInvoiceForm, 'delivery_address')
        tpl = (_APP / 'sales_invoices/templates/sales_invoices/form.html').read_text(encoding='utf-8')
        assert 'render_field(form.so_number)' in tpl and 'render_field(form.delivery_address)' in tpl

    def test_create_and_edit_save_them(self, client, db_session, accountant_user, main_branch, customer):
        from app.accounts.models import Account
        from app.sales_invoices.models import SalesInvoice
        from tests.conftest import assign_control_accounts
        rev = Account(code='40001', name='Sales', account_type='Revenue', normal_balance='credit', is_active=True)
        db_session.add(rev)
        for code, name, typ, nb in [('10201', 'AR - Trade', 'Asset', 'debit'),
                                    ('20201', 'Output VAT', 'Liability', 'credit')]:
            if not Account.query.filter_by(code=code).first():
                db_session.add(Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True))
        db_session.commit()
        assign_control_accounts(db_session)
        _session(client, accountant_user, main_branch)
        line = {'description': 'Cans', 'amount': '500.00', 'vat_category': '', 'vat_rate': '0', 'wt_id': '',
                'account_id': str(rev.id)}
        data = {'invoice_number': 'SI-RICL-01', 'invoice_date': '2026-11-19', 'due_date': '2026-12-19',
                'customer_id': str(customer.id), 'payment_terms': 'Net 30', 'notes': 'Cans',
                'so_number': ' 4512 ', 'delivery_address': 'Calamba Plant, Bldg 2',
                'line_items': json.dumps([line])}
        assert client.post('/sales-invoices/create', data=data).status_code == 302
        inv = SalesInvoice.query.filter_by(invoice_number='SI-RICL-01').one()
        assert inv.so_number == '4512' and inv.delivery_address == 'Calamba Plant, Bldg 2'
        data.update(so_number='', delivery_address='Sta. Rosa warehouse', row_version=str(inv.row_version))
        assert client.post(f'/sales-invoices/{inv.id}/edit', data=data).status_code == 302
        db_session.refresh(inv)
        assert inv.so_number is None and inv.delivery_address == 'Sta. Rosa warehouse'

    def test_print_takes_the_so_number_from_the_billed_drs(self, client, db_session, admin_user,
                                                         main_branch, customer):
        _so_a, dr_a = _so_dr(db_session, main_branch, customer, 'SO-R-0011', 'DR-R-0011')
        _so_b, dr_b = _so_dr(db_session, main_branch, customer, 'SO-R-0012', 'DR-R-0012')
        inv = _invoice(db_session, main_branch, customer, 'SI-R-0011', so_number='TYPED-9',
                       delivery_address='Calamba Plant')
        dr_a.sales_invoice_id = inv.id; dr_b.sales_invoice_id = inv.id; db_session.commit()
        _session(client, admin_user, main_branch)

        def show(lay):
            lay['fields']['so_number']['hidden'] = False
            lay['fields']['delivery_address']['hidden'] = False
        html = _si_print(client, inv, show)
        assert _el_text(html, 'so_number')[1] == 'SO-R-0011, SO-R-0012'
        assert _el_text(html, 'delivery_address')[1] == 'Calamba Plant'

    def test_print_falls_back_to_the_typed_so_number(self, client, db_session, admin_user, main_branch, customer):
        inv = _invoice(db_session, main_branch, customer, 'SI-R-0021', so_number='4512')
        _session(client, admin_user, main_branch)
        html = _si_print(client, inv, lambda lay: lay['fields']['so_number'].update(hidden=False))
        assert _el_text(html, 'so_number')[1] == '4512'

    def test_new_elements_arrive_hidden(self, client, db_session, admin_user, main_branch, customer):
        from app.sales_invoices.preprinted_layout import sanitize_layout
        assert sanitize_layout({})['fields']['so_number']['hidden'] is True
        assert sanitize_layout({})['fields']['delivery_address']['hidden'] is True
        inv = _invoice(db_session, main_branch, customer, 'SI-R-0031', so_number='4512')
        _session(client, admin_user, main_branch)
        cls, _ = _el_text(_si_print(client, inv), 'so_number')
        assert 'pp-field-hidden' in cls

    def test_detail_page_shows_them(self, client, db_session, admin_user, main_branch, customer):
        inv = _invoice(db_session, main_branch, customer, 'SI-R-0041', so_number='4512',
                       delivery_address='Calamba Plant')
        _session(client, admin_user, main_branch)
        html = client.get(f'/sales-invoices/{inv.id}').get_data(as_text=True)
        assert '4512' in html and 'Calamba Plant' in html


class TestPurchaseOrderRequestedBy:

    @pytest.fixture(autouse=True)
    def _modules(self, db_session):
        from app.utils.cache_helpers import clear_module_config_cache
        for k in ('products', 'purchase_orders', 'purchase_requests'):
            AppSettings.set_setting(f'module_enabled:{k}', '1')
        db_session.commit()
        clear_module_config_cache()
        yield
        clear_module_config_cache()

    def _pr(self, db_session, branch, number, creator, prepared_by=None):
        from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
        pr = PurchaseRequest(pr_number=number, request_date=date(2026, 11, 3), status='approved',
                             branch_id=branch.id, created_by_id=creator.id, prepared_by=prepared_by)
        pr.line_items.append(PurchaseRequestItem(line_number=1, description='Tinplate', quantity=Decimal('5')))
        db_session.add(pr); db_session.commit()
        return pr

    def test_open_lines_carry_the_requisitions_preparer(self, db_session, admin_user, main_branch):
        from app.purchase_requests.allocation import open_lines_for_branch
        self._pr(db_session, main_branch, 'PR-R-1', admin_user, prepared_by='Jasmin')
        self._pr(db_session, main_branch, 'PR-R-2', admin_user)
        rows = {r['pr_number']: r for r in open_lines_for_branch(main_branch.id)}
        assert rows['PR-R-1']['requested_by'] == 'Jasmin'
        assert rows['PR-R-2']['requested_by'] == admin_user.full_name    # no Prepared by: the creator

    def test_the_pr_pull_fills_requested_by_when_empty(self):
        tpl = (_APP / 'purchase_orders/templates/purchase_orders/form.html').read_text(encoding='utf-8')
        assert 'render_field(form.requested_by)' in tpl or 'form.requested_by' in tpl
        assert re.search(r"getElementById\('requested_by'\)", tpl) and 'row.requested_by' in tpl

    def test_create_and_edit_save_it(self, client, db_session, accountant_user, main_branch, vl_vendor):
        from app.purchase_orders.models import PurchaseOrder
        _session(client, accountant_user, main_branch)
        data = {'po_number': '09001', 'order_date': '2026-11-19', 'vendor_id': str(vl_vendor.id),
                'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'notes': '',
                'requested_by': ' Warlito ',
                'line_items': json.dumps([{'description': 'Tinplate', 'quantity': '1', 'unit_price': '10',
                                           'amount': '10'}])}
        client.post('/purchase-orders/create', data=data, follow_redirects=True)
        po = PurchaseOrder.query.filter_by(po_number='09001').one()
        assert po.requested_by == 'Warlito'
        data.update(requested_by='Salve', row_version=str(po.row_version))
        client.post(f'/purchase-orders/{po.id}/edit', data=data, follow_redirects=True)
        db_session.refresh(po)
        assert po.requested_by == 'Salve'

    def test_amendment_snapshot_keeps_it(self):
        from app.purchase_orders.models import PurchaseOrder
        assert 'requested_by' in PurchaseOrder.SNAPSHOT_HEADER_FIELDS

    def test_preprinted_layout_has_the_field_hidden_on_an_old_layout(self):
        from app.purchase_orders import preprinted_layout as pl
        assert 'requested_by' in pl.FIELD_KEYS and pl.FIELD_LABELS['requested_by'] == 'Requested by'
        old = {'fields': {'po_no': {'x': 100, 'y': 100, 'w': 200, 'fontSize': 10, 'bold': False}}}
        assert pl.sanitize_layout(old, hide_unknown=True)['fields']['requested_by']['hidden'] is True

    def test_both_prints_carry_it(self, client, db_session, admin_user, main_branch, vl_vendor):
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        po = PurchaseOrder(po_number='09002', order_date=date(2026, 11, 19), status='approved',
                           vendor_id=vl_vendor.id, vendor_name=vl_vendor.name, notes='', payment_terms='Net 30',
                           vat_treatment='inclusive', branch_id=main_branch.id, requested_by='Mitch')
        po.line_items.append(PurchaseOrderItem(line_number=1, description='Tinplate', quantity=Decimal('1'),
                                               unit_price=Decimal('10'), amount=Decimal('10')))
        po.calculate_totals()
        db_session.add(po); db_session.commit()
        _session(client, admin_user, main_branch)
        AppSettings.set_setting('po_print_form', 'current'); db_session.commit()
        plain = client.get(f'/purchase-orders/{po.id}/print').get_data(as_text=True)
        assert 'Requested by' in plain and 'Mitch' in plain
        AppSettings.set_setting('po_print_form', 'preprinted'); db_session.commit()
        pre = client.get(f'/purchase-orders/{po.id}/print').get_data(as_text=True)
        m = re.search(r'<div[^>]*data-el="requested_by"[^>]*>([^<]*)</div>', pre)
        assert m and m.group(1).strip() == 'Mitch'
