"""Integration tests: DR print_dr route honors the dr_print_form setting
(current/preprinted/hidden), the full-access-gated layout-save route, note-line
truncation on the pre-printed print, and the detail page's Print button gating.
"""
import pytest
from datetime import date
from app.settings import AppSettings
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
from app.delivery_receipts.preprinted_layout import MAX_NOTE_LINES
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _login(client, u, p):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _billed_dr(db_session, main_branch, admin_user, packing_notes=None, schedule_notes=None):
    """A minimal DR with one line, ready to print."""
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-PP-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='Acme', branch_id=main_branch.id, status='confirmed',
                    customer_po_number='2200099999')
    soi = SalesOrderItem(line_number=1, product_id=p.id, quantity=10, unit_price=100, amount=1000)
    so.line_items.append(soi)
    db.session.add(so); db.session.commit()
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-PP-1',
                          delivery_date=date(2026, 7, 10), sales_order_id=so.id,
                          customer_id=c.id, customer_name=c.name, status='billed',
                          created_by_id=admin_user.id,
                          packing_notes=packing_notes, schedule_notes=schedule_notes)
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=p.id, delivered_quantity=10))
    db.session.add(dr); db.session.commit()
    return dr


def test_print_current_renders_standard_form(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'current')
    dr = _billed_dr(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}/print')
    assert resp.status_code == 200
    assert b'pp-canvas' not in resp.data  # not the pre-printed canvas


def test_print_preprinted_renders_overlay(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'preprinted')
    dr = _billed_dr(db_session, main_branch, admin_user,
                    packing_notes='350 BAGS X 20 PCS = 7,000 PCS',
                    schedule_notes='BO: JULY 16 - 17, 2026')
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}/print')
    assert resp.status_code == 200
    assert b'pp-canvas' in resp.data
    assert b'350 BAGS X 20 PCS' in resp.data
    assert b'BO: JULY 16 - 17, 2026' in resp.data
    assert b'2200099999' in resp.data  # customer_po, sourced from the linked SO


def test_print_preprinted_blank_notes_render_nothing(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'preprinted')
    dr = _billed_dr(db_session, main_branch, admin_user)  # notes left None
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}/print')
    assert resp.status_code == 200
    assert b'BAGS X' not in resp.data
    assert b'BO: JULY' not in resp.data


def test_print_hidden_is_refused(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'hidden')
    dr = _billed_dr(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}/print', follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_note_lines_truncated_on_print(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'preprinted')
    lines = [f'ROW {i}' for i in range(MAX_NOTE_LINES + 5)]
    dr = _billed_dr(db_session, main_branch, admin_user, packing_notes='\n'.join(lines))
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}/print')
    body = resp.data.decode('utf-8')
    assert f'ROW {MAX_NOTE_LINES - 1}' in body
    assert f'ROW {MAX_NOTE_LINES}' not in body


def test_save_layout_requires_full_access(client, db_session, admin_user, staff_user, main_branch):
    staff_user.set_branches([main_branch])
    staff_user.set_book_permissions({'delivery_receipts': True})
    db_session.commit()
    _login(client, 'staff', 'staff123')
    resp = client.post('/delivery-receipts/print-layout', json={'paper': 'letter'})
    assert resp.status_code == 403


def test_save_layout_persists_for_admin(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.post('/delivery-receipts/print-layout', json={'paper': 'letter'})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True


def test_detail_button_hidden_when_setting_hidden(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'hidden')
    dr = _billed_dr(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}')
    assert resp.status_code == 200
    assert f'/delivery-receipts/{dr.id}/print'.encode() not in resp.data


def test_detail_button_shown_when_setting_current(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('dr_print_form', 'current')
    dr = _billed_dr(db_session, main_branch, admin_user)
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/delivery-receipts/{dr.id}')
    assert resp.status_code == 200
    assert f'/delivery-receipts/{dr.id}/print'.encode() in resp.data
