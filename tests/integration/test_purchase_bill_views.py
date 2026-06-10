"""Integration tests for the purchase bills list page redesign."""
import pytest
from datetime import timedelta
from decimal import Decimal

from app.vendors.models import Vendor
from app.purchase_bills.models import PurchaseBill
from app.utils import ph_now


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='PV001', name='Page Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True,
               payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_bill(db_session, vendor, branch, bill_number, status='posted',
              days_until_due=30, total_amount=Decimal('1000.00'), balance=None,
              bill_date=None):
    today = ph_now().date()
    b = PurchaseBill(
        bill_number=bill_number, vendor_id=vendor.id,
        vendor_name=vendor.name, vendor_tin='', vendor_address='',
        branch_id=branch.id,
        bill_date=bill_date or today,
        due_date=today + timedelta(days=days_until_due),
        status=status, subtotal=total_amount,
        vat_amount=Decimal('0.00'), total_before_wt=total_amount,
        withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'),
        total_amount=total_amount,
        amount_paid=Decimal('0.00'),
        balance=balance if balance is not None else total_amount,
        payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.commit()
    return b


class TestSummaryCards:
    def test_cards_render_with_totals(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBT-001',
                  days_until_due=-10, total_amount=Decimal('100.00'))   # overdue
        make_bill(db_session, vendor, main_branch, 'PBT-002',
                  days_until_due=3, total_amount=Decimal('200.00'))     # due soon
        make_bill(db_session, vendor, main_branch, 'PBT-003',
                  status='draft', total_amount=Decimal('999.00'))       # draft
        login(client)
        resp = client.get('/purchase-bills')
        assert resp.status_code == 200
        assert b'Outstanding AP' in resp.data
        assert b'Overdue' in resp.data
        assert b'Due in 7 Days' in resp.data
        assert b'Drafts' in resp.data
        assert b'300.00' in resp.data   # outstanding = 100 + 200
        assert b'100.00' in resp.data   # overdue


class TestFilters:
    def test_status_filter(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBF-001', status='posted')
        make_bill(db_session, vendor, main_branch, 'PBF-002', status='draft')
        login(client)
        resp = client.get('/purchase-bills?status=draft')
        assert b'PBF-002' in resp.data
        assert b'PBF-001' not in resp.data

    def test_vendor_filter(self, client, db_session, admin_user, main_branch):
        v1 = make_vendor(db_session, code='PV010', name='Vendor Ten')
        v2 = make_vendor(db_session, code='PV011', name='Vendor Eleven')
        make_bill(db_session, v1, main_branch, 'PBF-010')
        make_bill(db_session, v2, main_branch, 'PBF-011')
        login(client)
        resp = client.get(f'/purchase-bills?vendor={v1.id}')
        assert b'PBF-010' in resp.data
        assert b'PBF-011' not in resp.data

    def test_date_range_filter(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        today = ph_now().date()
        old_date = today - timedelta(days=60)
        make_bill(db_session, vendor, main_branch, 'PBF-020', bill_date=old_date)
        make_bill(db_session, vendor, main_branch, 'PBF-021')
        login(client)
        cutoff = (today - timedelta(days=30)).isoformat()
        resp = client.get(f'/purchase-bills?date_from={cutoff}')
        assert b'PBF-021' in resp.data
        assert b'PBF-020' not in resp.data

    def test_invalid_date_ignored(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBF-030')
        login(client)
        resp = client.get('/purchase-bills?date_from=not-a-date')
        assert resp.status_code == 200
        assert b'PBF-030' in resp.data

    def test_search_by_bill_number(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBQ-777')
        make_bill(db_session, vendor, main_branch, 'PBQ-888')
        login(client)
        resp = client.get('/purchase-bills?q=777')
        assert b'PBQ-777' in resp.data
        assert b'PBQ-888' not in resp.data

    def test_search_by_vendor_name(self, client, db_session, admin_user, main_branch):
        v1 = make_vendor(db_session, code='PV020', name='Acme Hardware')
        v2 = make_vendor(db_session, code='PV021', name='Bravo Foods')
        make_bill(db_session, v1, main_branch, 'PBQ-100')
        make_bill(db_session, v2, main_branch, 'PBQ-200')
        login(client)
        resp = client.get('/purchase-bills?q=acme')
        assert b'PBQ-100' in resp.data
        assert b'PBQ-200' not in resp.data


class TestTable:
    def test_balance_column_and_wt_dash(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBB-001',
                  status='partially_paid', total_amount=Decimal('1000.00'),
                  balance=Decimal('400.00'))
        login(client)
        resp = client.get('/purchase-bills')
        assert b'400.00' in resp.data           # balance column
        assert b'-\xe2\x82\xb10.00' not in resp.data  # no "-₱0.00" for zero WT

    def test_all_six_status_badges(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        statuses = ['draft', 'posted', 'partially_paid', 'paid', 'voided', 'cancelled']
        for i, status in enumerate(statuses):
            make_bill(db_session, vendor, main_branch, f'PBS-00{i}', status=status)
        login(client)
        resp = client.get('/purchase-bills')
        for cls in [b'badge-draft', b'badge-posted', b'badge-partial',
                    b'badge-paid', b'badge-void', b'badge-cancelled']:
            assert cls in resp.data

    def test_no_confirm_js(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/purchase-bills')
        assert b'confirm(' not in resp.data

    def test_pagination_preserves_filters(self, client, db_session, admin_user, main_branch):
        vendor = make_vendor(db_session)
        for i in range(51):  # per_page is 50
            make_bill(db_session, vendor, main_branch, f'PBP-{i:03d}')
        login(client)
        resp = client.get('/purchase-bills?status=posted')
        assert resp.status_code == 200
        assert b'status=posted' in resp.data  # filter param in pagination link


class TestExportSelection:
    def test_export_csv_with_ids_returns_only_selected(self, client, db_session,
                                                       admin_user, main_branch):
        vendor = make_vendor(db_session)
        b1 = make_bill(db_session, vendor, main_branch, 'PBX-001')
        b2 = make_bill(db_session, vendor, main_branch, 'PBX-002')
        login(client)
        resp = client.get(f'/purchase-bills/export/csv?ids={b1.id}')
        assert resp.status_code == 200
        assert b'PBX-001' in resp.data
        assert b'PBX-002' not in resp.data

    def test_export_csv_invalid_ids_ignored(self, client, db_session,
                                            admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBX-010')
        login(client)
        resp = client.get('/purchase-bills/export/csv?ids=abc')
        assert resp.status_code == 200
        assert b'PBX-010' in resp.data  # falls back to unfiltered export

    def test_export_csv_without_ids_respects_status_filter(self, client, db_session,
                                                           admin_user, main_branch):
        vendor = make_vendor(db_session)
        make_bill(db_session, vendor, main_branch, 'PBX-020', status='posted')
        make_bill(db_session, vendor, main_branch, 'PBX-021', status='draft')
        login(client)
        resp = client.get('/purchase-bills/export/csv?status=posted')
        assert resp.status_code == 200
        assert b'PBX-020' in resp.data
        assert b'PBX-021' not in resp.data


class TestAccess:
    def test_staff_can_view_list(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='staff', password='staff123')
        resp = client.get('/purchase-bills')
        assert resp.status_code == 200

    def test_viewer_can_view_list(self, client, db_session, viewer_user, main_branch):
        viewer_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='viewer', password='viewer123')
        resp = client.get('/purchase-bills')
        assert resp.status_code == 200


class TestBranchScoping:
    def test_cross_branch_detail_returns_404(self, client, db_session,
                                             viewer_user, main_branch, branch_manila):
        vendor = make_vendor(db_session, code='PVS-001', name='Scoping Vendor')
        main_bill = make_bill(db_session, vendor, main_branch, 'PBS-001')
        other_bill = make_bill(db_session, vendor, branch_manila, 'PBS-002')

        viewer_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='viewer', password='viewer123')

        resp = client.get(f'/purchase-bills/{main_bill.id}')
        assert resp.status_code == 200

        resp = client.get(f'/purchase-bills/{other_bill.id}')
        assert resp.status_code == 404

    def test_cross_branch_edit_returns_404(self, client, db_session,
                                           accountant_user, main_branch, branch_manila):
        vendor = make_vendor(db_session, code='PVS-002', name='Scoping Vendor 2')
        other_bill = make_bill(db_session, vendor, branch_manila, 'PBS-011', status='draft')

        login(client, username='accountant', password='accountant123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        resp = client.get(f'/purchase-bills/{other_bill.id}/edit')
        assert resp.status_code == 404
