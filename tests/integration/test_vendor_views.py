"""Integration tests for vendor views — CRUD, detail page, role checks."""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event

from app import db
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.audit.models import AuditLog
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
from app.utils import ph_now


class _QueryCounter:
    """Counts SQL statements issued on db.engine within the block."""
    def __init__(self):
        self.count = 0

    def _on_exec(self, *args, **kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(db.engine, 'before_cursor_execute', self._on_exec)
        return self

    def __exit__(self, *exc):
        event.remove(db.engine, 'before_cursor_execute', self._on_exec)
pytestmark = [pytest.mark.vendors, pytest.mark.integration]


def make_vat_category(db_session, code='V12DG', name='Input Tax Domestic Goods', rate='12.00'):
    """Ensure an active VAT category exists (the vendor form requires one)."""
    cat = VATCategory.query.filter_by(code=code).first()
    if not cat:
        cat = VATCategory(code=code, name=name, rate=Decimal(rate), is_active=True)
        db_session.add(cat)
        db_session.commit()
    return cat



def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='IV001', name='Integration Vendor'):
    v = Vendor(code=code, name=name, check_payee_name=name, is_active=True,
               payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def make_ap(db_session, vendor, branch, ap_number='PB-IT-001',
              status='posted', days_overdue=0):
    today = ph_now().date()
    due = today - timedelta(days=days_overdue)
    b = AccountsPayable(
        ap_number=ap_number, vendor_id=vendor.id,
        vendor_name=vendor.name, vendor_tin='', vendor_address='',
        branch_id=branch.id, ap_date=today, due_date=due,
        status=status, subtotal=Decimal('1000.00'),
        vat_amount=Decimal('0.00'), total_before_wt=Decimal('1000.00'),
        withholding_tax_rate=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('1000.00'), balance=Decimal('1000.00'),
        amount_paid=Decimal('0.00'), payment_terms='Net 30',
    )
    db_session.add(b)
    db_session.commit()
    return b


class TestVendorList:
    def test_list_renders(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)
        resp = client.get('/vendors')
        assert resp.status_code == 200
        assert b'Integration Vendor' in resp.data

    def test_list_vendor_name_is_link_to_detail(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='IV002', name='Link Test Vendor')
        resp = client.get('/vendors')
        assert resp.status_code == 200
        assert f'/vendors/{vendor.id}'.encode() in resp.data

    def test_delete_modal_has_no_confirm_js(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/vendors')
        assert resp.status_code == 200
        assert b'confirm(' not in resp.data


class TestVendorDetail:
    def test_detail_overview_loads(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV001', name='Detail Test Vendor')
        resp = client.get(f'/vendors/{vendor.id}')
        assert resp.status_code == 200
        assert b'Detail Test Vendor' in resp.data
        assert b'AP Aging' in resp.data
        assert b'WHT Withheld' in resp.data

    def test_detail_shows_vendor_info(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV002', name='Info Vendor')
        resp = client.get(f'/vendors/{vendor.id}')
        assert resp.status_code == 200
        assert b'DV002' in resp.data
        assert b'Net 30' in resp.data

    def test_detail_bills_tab_renders(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV003', name='Bills Tab Vendor')
        make_ap(db_session, vendor, main_branch, 'PB-BT-001')
        resp = client.get(f'/vendors/{vendor.id}?tab=bills')
        assert resp.status_code == 200
        assert b'PB-BT-001' in resp.data

    def test_detail_bills_status_filter(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV004', name='Filter Vendor')
        make_ap(db_session, vendor, main_branch, 'PB-POSTED', status='posted')
        make_ap(db_session, vendor, main_branch, 'PB-DRAFT', status='draft')
        resp = client.get(f'/vendors/{vendor.id}?tab=bills&status=draft')
        assert resp.status_code == 200
        assert b'PB-DRAFT' in resp.data
        assert b'PB-POSTED' not in resp.data

    def test_detail_bills_date_filter(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DV005', name='Date Filter Vendor')
        today = ph_now().date()
        b1 = make_ap(db_session, vendor, main_branch, 'PB-TODAY')
        b2 = make_ap(db_session, vendor, main_branch, 'PB-OLD')
        b2.ap_date = date(today.year - 1, 1, 1)
        db_session.commit()
        from_date = today.isoformat()
        resp = client.get(f'/vendors/{vendor.id}?tab=bills&date_from={from_date}')
        assert resp.status_code == 200
        assert b'PB-TODAY' in resp.data
        assert b'PB-OLD' not in resp.data

    def test_staff_can_view_detail(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch])
        db_session.commit()
        login(client, username='staff', password='staff123')
        vendor = make_vendor(db_session, code='DV006', name='Staff View Vendor')
        resp = client.get(f'/vendors/{vendor.id}')
        assert resp.status_code == 200
        assert b'Staff View Vendor' in resp.data


class TestVendorCrud:
    def test_create_vendor_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'NEW001',
            'name': 'New Test Vendor',
            'check_payee_name': 'New Test Vendor',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        vendor = Vendor.query.filter_by(code='NEW001').first()
        assert vendor is not None
        audit = AuditLog.query.filter_by(module='vendor', action='create',
                                         record_id=vendor.id).first()
        assert audit is not None

    def test_edit_vendor_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        vendor = make_vendor(db_session, code='ED001', name='Edit Me')
        resp = client.post(f'/vendors/{vendor.id}/edit', data={
            'code': 'ED001',
            'name': 'Edited Name',
            'check_payee_name': 'Edited Name',
            'payment_terms': 'Net 15',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(vendor)
        assert vendor.name == 'Edited Name'
        audit = AuditLog.query.filter_by(module='vendor', action='update',
                                         record_id=vendor.id).first()
        assert audit is not None

    def test_delete_vendor_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='DEL001', name='Delete Me')
        vid = vendor.id
        resp = client.post(f'/vendors/{vid}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert Vendor.query.get(vid) is None
        audit = AuditLog.query.filter_by(module='vendor', action='delete',
                                         record_id=vid).first()
        assert audit is not None

    def test_staff_cannot_delete(self, client, db_session, staff_user, main_branch):
        login(client, username='staff', password='staff123')
        vendor = make_vendor(db_session, code='STF002', name='Staff Delete Test')
        vid = vendor.id
        client.post(f'/vendors/{vid}/delete', follow_redirects=True)
        assert Vendor.query.get(vid) is not None


class TestVendorStaffPermissions:
    """Staff can create and edit vendors (Tier 1); delete remains Tier 2."""

    def _login(self, client, username, password):
        client.post('/login', data={'username': username, 'password': password},
                    follow_redirects=True)

    def test_staff_can_access_create_form(self, client, db_session, admin_user,
                                          staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'staff', 'staff123')
        resp = client.get('/vendors/create')
        assert resp.status_code == 200

    def test_viewer_blocked_from_create(self, client, db_session, admin_user,
                                        viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'viewer', 'viewer123')
        resp = client.get('/vendors/create', follow_redirects=True)
        assert resp.status_code == 200
        assert b'permission' in resp.data or b'Only' in resp.data

    def test_staff_can_access_edit_form(self, client, db_session, admin_user,
                                        staff_user, accountant_user, main_branch):
        from app.vendors.models import Vendor
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'accountant', 'accountant123')
        make_vat_category(db_session)
        client.post('/vendors/create', data={
            'code': 'V-PERM-TEST', 'name': 'Perm Test Co.',
            'payment_terms': 'Net 30', 'default_vat_category': 'V12DG', 'is_active': '1',
        }, follow_redirects=True)
        vendor = Vendor.query.filter_by(code='V-PERM-TEST').first()
        assert vendor is not None
        client.get('/logout')
        self._login(client, 'staff', 'staff123')
        resp = client.get(f'/vendors/{vendor.id}/edit')
        assert resp.status_code == 200

    def test_staff_still_blocked_from_delete(self, client, db_session, admin_user,
                                              staff_user, accountant_user, main_branch):
        from app.vendors.models import Vendor

        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        self._login(client, 'accountant', 'accountant123')
        make_vat_category(db_session)
        client.post('/vendors/create', data={
            'code': 'V-DEL-PERM', 'name': 'Del Perm Co.',
            'payment_terms': 'Net 30', 'default_vat_category': 'V12DG', 'is_active': '1',
        }, follow_redirects=True)
        vendor = Vendor.query.filter_by(code='V-DEL-PERM').first()
        client.get('/logout')
        self._login(client, 'staff', 'staff123')
        client.post(f'/vendors/{vendor.id}/delete', follow_redirects=True)
        assert Vendor.query.get(vendor.id) is not None


class TestVendorNoBirNotes:
    """The per-field BIR notes were removed once the fields were grouped into
    labelled sections. Guard against them being re-introduced."""

    NOTE_FRAGMENTS = [b'Required on BIR Form 2307',
                      b'Certificate of Registration',
                      b'Registered business address as printed']

    def test_create_form_has_no_bir_notes(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        for fragment in self.NOTE_FRAGMENTS:
            assert fragment not in resp.data


class TestVendorFormSections:
    """The vendor form fields are grouped into labelled sections. The sections
    render on the create/edit pages AND in the shared AP quick-add modal."""

    SECTION_TITLES = [b'Vendor Details', b'Tax Information',
                      b'Contact Information', b'Payment Information']

    def test_create_form_has_sections(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        for title in self.SECTION_TITLES:
            assert title in resp.data

    def test_edit_form_has_sections(self, client, db_session, admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session, code='SEC001', name='Section Vendor')
        resp = client.get(f'/vendors/{vendor.id}/edit')
        assert resp.status_code == 200
        for title in self.SECTION_TITLES:
            assert title in resp.data

    def test_quick_add_modal_has_sections(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        for title in self.SECTION_TITLES:
            assert title in resp.data

    def test_name_field_label_is_registered_name(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        assert b'>Registered Name<' in resp.data
        # The "Check Payee Name" twin label must be left untouched.
        assert b'>Check Payee Name<' in resp.data

    def test_vat_category_label_is_registration_type(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        assert b'>Registration Type<' in resp.data
        assert b'Default VAT Category' not in resp.data

    def test_customer_vat_label_is_registration_type(self, client, db_session, admin_user, main_branch):
        # The customer form now uses the same "Registration Type" label as the vendor form
        # (unified per design spec; both refer to the same SalesVATCategory picker).
        login(client)
        resp = client.get('/customers/create')
        assert resp.status_code == 200
        assert b'Registration Type' in resp.data
        assert b'Default VAT Category' not in resp.data

    def test_withholding_tax_section_label(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        assert b'>Withholding Tax</label>' in resp.data
        assert b'Default Withholding Tax' not in resp.data


class TestVendorWithholdingTaxPicker:
    """Withholding Tax is a searchable multi-select (Choices.js), not a flat
    checkbox grid — it must scale to many WT codes. Backend still reads the
    repeated `withholding_tax_ids` params, so submission is unchanged."""

    def _make_wt(self, db_session, code='WC999', name='Test WT', rate='5.00'):
        wt = WithholdingTax(code=code, name=name, rate=Decimal(rate), is_active=True)
        db_session.add(wt)
        db_session.commit()
        return wt

    def test_create_form_wt_is_searchable_multiselect(self, client, db_session, admin_user, main_branch):
        login(client)
        self._make_wt(db_session)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        assert b'vendor-wt-select" multiple' in resp.data
        assert b'name="withholding_tax_ids"' in resp.data
        # The old checkbox grid is gone.
        assert b'class="form-checkbox"' not in resp.data

    def test_edit_form_preselects_assigned_wt(self, client, db_session, admin_user, main_branch):
        login(client)
        wt = self._make_wt(db_session, code='WC777')
        vendor = make_vendor(db_session, code='WTV01', name='WT Vendor')
        vendor.withholding_taxes = [wt]
        db_session.commit()
        resp = client.get(f'/vendors/{vendor.id}/edit')
        assert resp.status_code == 200
        assert f'value="{wt.id}" selected>'.encode() in resp.data


class TestVendorListAnalyzeFixes:
    """Fixes from /analyze-page on /vendors: N+1 eager load, staff Edit
    affordance, export cleanup, and the create-button verb convention."""

    def _wt(self, db_session, code):
        wt = WithholdingTax(code=code, name=f'{code} name', rate=Decimal('5.00'), is_active=True)
        db_session.add(wt)
        db_session.commit()
        return wt

    def test_list_has_no_n_plus_one_on_withholding_taxes(self, client, db_session, admin_user, main_branch):
        login(client)
        wt = self._wt(db_session, 'WCN1')
        v1 = make_vendor(db_session, code='NV1', name='NV1')
        v1.withholding_taxes = [wt]
        db_session.commit()
        with _QueryCounter() as qc1:
            client.get('/vendors')
        one = qc1.count
        for code in ('NV2', 'NV3', 'NV4'):
            v = make_vendor(db_session, code=code, name=code)
            v.withholding_taxes = [wt]
            db_session.commit()
        with _QueryCounter() as qc4:
            client.get('/vendors')
        four = qc4.count
        # Eager loading → WHT fetch count is constant regardless of vendor count.
        assert four == one, f'N+1 detected: {one} queries for 1 vendor vs {four} for 4'

    def test_staff_sees_edit_button_not_delete(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        # Staff need the Vendors book permission to reach the list (deny-default).
        staff_user.set_book_permissions({'vendors': True})
        db_session.commit()
        make_vendor(db_session, code='SE01', name='Staff Edit Vendor')
        login(client, 'staff', 'staff123')
        resp = client.get('/vendors')
        assert resp.status_code == 200
        assert b'>Edit</a>' in resp.data          # staff may edit (view allows it)
        assert b'delete-modal-' not in resp.data  # delete stays accountant/admin

    def test_admin_sees_edit_and_delete(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vendor(db_session, code='AE01', name='Admin Edit Vendor')
        resp = client.get('/vendors')
        assert b'>Edit</a>' in resp.data
        assert b'delete-modal-' in resp.data

    def test_csv_export_still_works(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vendor(db_session, code='EX01', name='Export Vendor')
        resp = client.get('/vendors/export/csv')
        assert resp.status_code == 200
        assert b'EX01' in resp.data

    def test_excel_export_still_works(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vendor(db_session, code='EX02', name='Export Vendor 2')
        resp = client.get('/vendors/export/excel')
        assert resp.status_code == 200

    def test_create_launch_button_uses_create_verb(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vendor(db_session, code='CV01', name='Verb Vendor')
        resp = client.get('/vendors')
        assert b'Create Vendor' in resp.data
        assert b'Add Vendor' not in resp.data

    def test_create_form_submit_button_uses_create_verb(self, client, db_session, admin_user, main_branch):
        """The create-form submit button uses the master-data 'Create' verb, not 'Save'.

        (The page <title> already says 'Create Vendor', so the meaningful signal is
        the absence of the old 'Save Vendor' button label.)
        """
        login(client)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        assert b'Save Vendor' not in resp.data
        assert b'Create Vendor' in resp.data


def test_generate_next_vendor_code_is_numeric_safe_past_999(db_session):
    """Vendor code sequencing must be numeric, not lexicographic (twin of the
    customer C### bug). With V999 and V1000 present, the next code must be V1001;
    a lexicographic order_by(code.desc()) wrongly ranks 'V999' above 'V1000' and
    re-proposes the already-taken V1000.
    """
    from app.vendors.utils import generate_next_vendor_code

    db_session.add(Vendor(code='V999', name='Niner Supply'))
    db_session.add(Vendor(code='V1000', name='Kilo Supply'))
    db_session.commit()

    assert generate_next_vendor_code() == 'V1001'


class TestVendorListSearchPagination:
    """F006 (pagination + server-side search), F002 (no-results), F004 (export gate)."""

    def test_server_side_search_filters(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vendor(db_session, code='AAA001', name='Alpha Co')
        make_vendor(db_session, code='BBB001', name='Bravo Co')
        resp = client.get('/vendors?q=Alpha')
        assert resp.status_code == 200
        assert b'Alpha Co' in resp.data
        assert b'Bravo Co' not in resp.data

    def test_search_by_tin(self, client, db_session, admin_user, main_branch):
        login(client)
        v = make_vendor(db_session, code='TINV1', name='Tin Vendor')
        v.tin = '123-456-789-000'
        db_session.commit()
        resp = client.get('/vendors?q=456-789')
        assert resp.status_code == 200
        assert b'Tin Vendor' in resp.data

    def test_search_no_match_shows_message(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vendor(db_session, code='REAL1', name='Real Vendor')
        resp = client.get('/vendors?q=zzz-no-such-vendor')
        assert resp.status_code == 200
        assert b'Real Vendor' not in resp.data
        assert b'No vendors match' in resp.data

    def test_pagination_caps_page_size(self, client, db_session, admin_user, main_branch):
        login(client)
        for i in range(30):
            make_vendor(db_session, code=f'PG{i:03d}', name=f'Page Vendor {i:03d}')
        resp = client.get('/vendors')
        assert resp.status_code == 200
        # 25 per page → page 1 has PG000..PG024, not PG029
        assert b'PG000' in resp.data
        assert b'PG029' not in resp.data
        resp2 = client.get('/vendors?page=2')
        assert b'PG029' in resp2.data

    def test_viewer_blocked_from_csv_export(self, client, db_session, admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/vendors/export/csv')
        assert resp.status_code == 302  # staff_or_above_required redirects viewers

    def test_viewer_blocked_from_excel_export(self, client, db_session, admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/vendors/export/excel')
        assert resp.status_code == 302

