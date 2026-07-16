"""Action Items: draft documents + master-data approvals, role scoping.

Rules under test:
  - Drafts: staff see only their own; admin/accountant see all in the branch.
  - For Approval (change requests): admin/accountant only — staff never.
  - Viewer: no sidebar link AND the /action-items route is blocked.
"""
import json
from datetime import date

import pytest

from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.withholding_tax.models import WithholdingTaxChangeRequest

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='AIV01'):
    v = Vendor.query.filter_by(code=code).first()
    if not v:
        v = Vendor(code=code, name='AI Vendor', check_payee_name='AI Vendor',
                   is_active=True, payment_terms='Net 30')
        db_session.add(v)
        db_session.commit()
    return v


def make_draft_ap(db_session, branch, user, number, vendor):
    ap = AccountsPayable(
        ap_number=number, ap_date=date.today(), due_date=date.today(),
        vendor_id=vendor.id, vendor_name=vendor.name, branch_id=branch.id,
        status='draft', created_by_id=user.id,
    )
    db_session.add(ap)
    db_session.commit()
    return ap


def make_pending_wt_request(db_session, user, name):
    req = WithholdingTaxChangeRequest(
        action='create', status='pending',
        proposed_data=json.dumps({'code': 'WCX', 'name': name, 'rate': '5.00'}),
        requested_by_id=user.id,
    )
    db_session.add(req)
    db_session.commit()
    return req


class TestActionItemsDrafts:
    def test_admin_sees_all_branch_drafts(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        v = make_vendor(db_session)
        make_draft_ap(db_session, main_branch, admin_user, 'AP-ADMIN-1', v)
        make_draft_ap(db_session, main_branch, staff_user, 'AP-STAFF-1', v)
        login(client, 'admin', 'admin123')
        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert b'AP-ADMIN-1' in resp.data
        assert b'AP-STAFF-1' in resp.data   # admin sees colleagues' drafts too

    def test_staff_sees_only_own_drafts(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        v = make_vendor(db_session)
        make_draft_ap(db_session, main_branch, admin_user, 'AP-ADMIN-2', v)
        make_draft_ap(db_session, main_branch, staff_user, 'AP-STAFF-2', v)
        login(client, 'staff', 'staff123')
        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert b'AP-STAFF-2' in resp.data
        assert b'AP-ADMIN-2' not in resp.data


class TestActionItemsApprovals:
    def test_admin_sees_for_approval(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        make_pending_wt_request(db_session, admin_user, 'Approval Visible To Admin')
        login(client, 'admin', 'admin123')
        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert b'Approval Visible To Admin' in resp.data

    def test_staff_does_not_see_for_approval(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        make_pending_wt_request(db_session, admin_user, 'Approval Hidden From Staff')
        login(client, 'staff', 'staff123')
        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert b'Approval Hidden From Staff' not in resp.data
        assert b'For Approval' not in resp.data


class TestActionItemsViewer:
    def test_viewer_blocked_from_route(self, client, db_session, viewer_user, main_branch):
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/action-items')
        assert resp.status_code == 302
        assert '/action-items' not in resp.headers.get('Location', '')

    def test_viewer_nav_hides_action_items(self, client, db_session, viewer_user, main_branch):
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        assert b'Action Items' not in resp.data

    def test_staff_nav_shows_action_items(self, client, db_session, staff_user, main_branch):
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        assert b'Action Items' in resp.data


def make_pending_sales_vat_request(db_session, user, name):
    from app.sales_vat_categories.models import SalesVATCategoryChangeRequest
    req = SalesVATCategoryChangeRequest(
        action='create', status='pending',
        proposed_data=json.dumps({'code': 'SVCX', 'name': name}),
        requested_by_id=user.id,
    )
    db_session.add(req)
    db_session.commit()
    return req


class TestActionItemsSalesVATCategory:
    def test_admin_sees_pending_sales_vat_category_request(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        make_pending_sales_vat_request(db_session, admin_user, 'Sales VAT Approval Visible')
        login(client, 'admin', 'admin123')
        resp = client.get('/action-items')
        assert resp.status_code == 200
        assert b'Sales VAT Approval Visible' in resp.data

    def test_badge_count_includes_pending_sales_vat_category_request(self, client, db_session, admin_user, main_branch):
        from app.dashboard.action_items_service import count_action_items
        admin_user.add_branch(main_branch)
        db_session.commit()
        before = count_action_items(admin_user, main_branch.id)
        make_pending_sales_vat_request(db_session, admin_user, 'Sales VAT Badge Check')
        after = count_action_items(admin_user, main_branch.id)
        assert after == before + 1
