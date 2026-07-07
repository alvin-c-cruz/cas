import json
import pytest
from decimal import Decimal
from flask import url_for
from app import db
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.sales_vat_categories.models import (
    SalesVATCategory, SalesVATCategoryChangeRequest)
from app.withholding_tax.models import (
    WithholdingTax, WithholdingTaxChangeRequest)

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.post("/login", data={"username": username, "password": password},
                follow_redirects=True)


def _vat_with_pending_rate_change(db_session, requester_id):
    vc = VATCategory(code="V12", name="Vatable 12%", description="std",
                     rate=Decimal("12.00"), is_active=True)
    db_session.add(vc)
    db_session.commit()
    cr = VATCategoryChangeRequest(
        action="update", status="pending", vat_category_id=vc.id,
        proposed_data=json.dumps({"code": "V12", "name": "Vatable 12%",
                                  "description": "std", "rate": 2.00,
                                  "is_active": True, "input_vat_account_id": None}),
        requested_by_id=requester_id,
    )
    db_session.add(cr)
    db_session.commit()
    return vc, cr


class TestVatReviewGate:
    def test_approve_rate_change_without_note_is_rejected(self, client, db_session,
                                                          admin_user, accountant_user,
                                                          main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        client.post(url_for("vat_categories.review_change_request", id=cr.id),
                    data={"action": "approve", "review_notes": ""},
                    follow_redirects=True)
        db_session.refresh(vc)
        db_session.refresh(cr)
        assert vc.rate == Decimal("12.00")   # not applied
        assert cr.status == "pending"        # still pending

    def test_approve_rate_change_with_note_applies(self, client, db_session,
                                                   admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        client.post(url_for("vat_categories.review_change_request", id=cr.id),
                    data={"action": "approve",
                          "review_notes": "verified against BIR RMC"},
                    follow_redirects=True)
        db_session.refresh(vc)
        assert vc.rate == Decimal("2.00")    # applied

    def test_review_page_shows_rate_diff(self, client, db_session,
                                         admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        resp = client.get(url_for("vat_categories.review_change_request", id=cr.id))
        body = resp.data.decode()
        assert "12.00" in body and "2.00" in body


def _svat_with_pending_rate_change(db_session, requester_id):
    sc = SalesVATCategory(code="SV12", name="Sales Vatable 12%", description="std",
                          rate=Decimal("12.00"), transaction_nature="regular",
                          is_active=True)
    db_session.add(sc)
    db_session.commit()
    cr = SalesVATCategoryChangeRequest(
        action="update", status="pending", sales_vat_category_id=sc.id,
        proposed_data=json.dumps({"code": "SV12", "name": "Sales Vatable 12%",
                                  "description": "std", "rate": 2.00,
                                  "transaction_nature": "regular",
                                  "is_active": True, "output_vat_account_id": None}),
        requested_by_id=requester_id,
    )
    db_session.add(cr)
    db_session.commit()
    return sc, cr


class TestSalesVatReviewGate:
    def test_approve_rate_change_without_note_is_rejected(self, client, db_session,
                                                          admin_user, accountant_user,
                                                          main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        client.post(url_for("sales_vat_categories.review_change_request", id=cr.id),
                    data={"action": "approve", "review_notes": ""},
                    follow_redirects=True)
        db_session.refresh(sc)
        db_session.refresh(cr)
        assert sc.rate == Decimal("12.00")
        assert cr.status == "pending"

    def test_approve_rate_change_with_note_applies(self, client, db_session,
                                                   admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        client.post(url_for("sales_vat_categories.review_change_request", id=cr.id),
                    data={"action": "approve", "review_notes": "verified"},
                    follow_redirects=True)
        db_session.refresh(sc)
        assert sc.rate == Decimal("2.00")

    def test_review_page_shows_rate_diff(self, client, db_session,
                                         admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        resp = client.get(url_for("sales_vat_categories.review_change_request", id=cr.id))
        body = resp.data.decode()
        assert "12.00" in body and "2.00" in body


def _wht_with_pending_rate_change(db_session, requester_id):
    wt = WithholdingTax(code="WC158", name="EWT 10%", sales_name="EWT 10%",
                        description="std", rate=Decimal("10.00"), is_active=True)
    db_session.add(wt)
    db_session.commit()
    cr = WithholdingTaxChangeRequest(
        action="update", status="pending", withholding_tax_id=wt.id,
        proposed_data=json.dumps({"code": "WC158", "name": "EWT 10%",
                                  "sales_name": "EWT 10%", "description": "std",
                                  "rate": 2.00, "is_active": True,
                                  "payable_account_id": None,
                                  "receivable_account_id": None}),
        requested_by_id=requester_id,
    )
    db_session.add(cr)
    db_session.commit()
    return wt, cr


class TestWhtReviewGate:
    def test_approve_rate_change_without_note_is_rejected(self, client, db_session,
                                                          admin_user, accountant_user,
                                                          main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        client.post(url_for("withholding_tax.review_change_request", id=cr.id),
                    data={"action": "approve", "review_notes": ""},
                    follow_redirects=True)
        db_session.refresh(wt)
        db_session.refresh(cr)
        assert wt.rate == Decimal("10.00")
        assert cr.status == "pending"

    def test_approve_rate_change_with_note_applies(self, client, db_session,
                                                   admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        client.post(url_for("withholding_tax.review_change_request", id=cr.id),
                    data={"action": "approve", "review_notes": "verified"},
                    follow_redirects=True)
        db_session.refresh(wt)
        assert wt.rate == Decimal("2.00")

    def test_review_page_shows_rate_diff(self, client, db_session,
                                         admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_with_pending_rate_change(db_session, accountant_user.id)
        login(client, "admin", "admin123")
        resp = client.get(url_for("withholding_tax.review_change_request", id=cr.id))
        body = resp.data.decode()
        assert "10.00" in body and "2.00" in body
