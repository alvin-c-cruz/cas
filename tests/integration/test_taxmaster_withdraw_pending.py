"""TDD for BUG-TAXMASTER-RATECHANGE-STUCK-SOLE-ADMIN.

A rate-change edit on VAT Categories / Sales VAT Categories / Withholding Tax
never auto-approves (app/utils/admin_approval.py::tax_edit_may_auto_approve),
even for a lone full-access reviewer -- intentional, must never be weakened
(memory `tax-rate-edit-review-gate`). But with exactly one full-access user,
the resulting pending change request has no possible reviewer: the requester
can't review their own request (change_requests.html's Review link is gated
`requested_by_id != current_user.id`) and nobody else exists. The standing
duplicate-pending guard (find_pending_request/flash_duplicate_pending) then
blocks ANY further edit to that record forever.

Fix: a requester-only "withdraw" action that retracts an unreviewed request
(status -> 'withdrawn'), which is NOT the same as approving it and does not
touch tax_edit_may_auto_approve/tax_rate_changed at all. Mirrors the same
test shape across all three sibling modules, per this project's sibling-drift
discipline (memory `feedback-grep-siblings-on-fix`).

Sits alongside test_tax_rate_review_gate.py, which pins the review-gate half
of this same feature area in the same one-file-per-three-modules shape.
"""
import json
from decimal import Decimal

import pytest
from flask import url_for

from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.sales_vat_categories.models import (
    SalesVATCategory, SalesVATCategoryChangeRequest)
from app.withholding_tax.models import (
    WithholdingTax, WithholdingTaxChangeRequest)

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.post("/login", data={"username": username, "password": password},
                follow_redirects=True)


# ---------------------------------------------------------------------------
# VAT Categories
# ---------------------------------------------------------------------------

def _vat_pending_cr(db_session, requester_id, old_rate="12.00", new_rate="12.00",
                    account_id=None):
    vc = VATCategory(code="V12", name="Vatable 12%", description="std",
                     rate=Decimal(old_rate), is_active=True,
                     transaction_nature="domestic_goods",
                     input_vat_account_id=account_id)
    db_session.add(vc)
    db_session.commit()
    cr = VATCategoryChangeRequest(
        action="update", status="pending", vat_category_id=vc.id,
        proposed_data=json.dumps({"code": "V12", "name": "Vatable 12%",
                                  "description": "std", "rate": float(new_rate),
                                  "transaction_nature": "domestic_goods",
                                  "is_active": True,
                                  "input_vat_account_id": account_id}),
        requested_by_id=requester_id,
        request_reason="testing",
    )
    db_session.add(cr)
    db_session.commit()
    return vc, cr


class TestVatCategoryWithdraw:
    def test_requester_can_withdraw_own_pending_request(
            self, client, db_session, admin_user, main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "withdrawn"
        assert b"withdrawn" in resp.data.lower() or b"Withdrawn" in resp.data

    def test_withdrawal_clears_duplicate_pending_guard(
            self, client, db_session, admin_user, main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        login(client, "admin", "admin123")

        # Withdraw the stuck request.
        client.post(url_for("vat_categories.withdraw_change_request", id=cr.id),
                    follow_redirects=True)
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

        # A fresh, non-rate edit to the SAME record must now be accepted
        # (sole full-access reviewer + unchanged rate -> auto-applies) instead
        # of being blocked by find_pending_request.
        resp = client.post(
            url_for("vat_categories.edit", id=vc.id),
            data={
                "code": "V12", "name": "Vatable 12%",
                "description": "updated description",
                "rate": "12.00",
                "transaction_nature": "domestic_goods",
                "input_vat_account_id": str(cash_account.id),
                "is_active": "1",
                "request_reason": "routine edit",
            },
            follow_redirects=True)

        assert resp.status_code == 200
        assert b"already exists" not in resp.data
        assert b"updated successfully" in resp.data
        db_session.refresh(vc)
        assert vc.description == "updated description"

    def test_non_requester_cannot_withdraw_others_request(
            self, client, db_session, admin_user, chief_accountant_user,
            main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        login(client, "chief", "chief123")

        resp = client.post(
            url_for("vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "pending"
        assert b"own" in resp.data.lower()

    def test_withdrawing_already_processed_request_is_refused(
            self, client, db_session, admin_user, main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        vc, cr = _vat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        cr.status = "approved"
        db_session.commit()
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "approved"
        assert b"already been processed" in resp.data

    def test_rate_change_stuck_scenario_is_withdrawable(
            self, client, db_session, admin_user, main_branch, cash_account):
        """The exact repro from the bug report: sole full-access user submits
        a rate-change edit (stays pending -- gate untouched), then withdraws
        it themselves, clearing the block."""
        vc = VATCategory(code="V12", name="Vatable 12%", description="std",
                         rate=Decimal("12.00"), is_active=True,
                         transaction_nature="domestic_goods",
                         input_vat_account_id=cash_account.id)
        db_session.add(vc)
        db_session.commit()
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, "admin", "admin123")

        # Submit a RATE-CHANGE edit as the sole full-access user.
        resp = client.post(
            url_for("vat_categories.edit", id=vc.id),
            data={
                "code": "V12", "name": "Vatable 12%", "description": "std",
                "rate": "10.00",  # changed from 12.00
                "transaction_nature": "domestic_goods",
                "input_vat_account_id": str(cash_account.id),
                "is_active": "1",
                "request_reason": "rate correction",
            },
            follow_redirects=True)
        assert resp.status_code == 200

        db_session.refresh(vc)
        assert vc.rate == Decimal("12.00")  # NOT auto-applied -- gate untouched
        cr = VATCategoryChangeRequest.query.filter_by(
            vat_category_id=vc.id, status="pending").first()
        assert cr is not None
        assert cr.status == "pending"

        # Withdraw the now-stuck request as the same requester.
        resp = client.post(
            url_for("vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

        # A fresh (non-rate) edit is no longer blocked.
        resp = client.post(
            url_for("vat_categories.edit", id=vc.id),
            data={
                "code": "V12", "name": "Vatable 12%",
                "description": "unblocked now",
                "rate": "12.00",
                "transaction_nature": "domestic_goods",
                "input_vat_account_id": str(cash_account.id),
                "is_active": "1",
                "request_reason": "routine edit",
            },
            follow_redirects=True)
        assert resp.status_code == 200
        assert b"already exists" not in resp.data
        assert b"updated successfully" in resp.data


# ---------------------------------------------------------------------------
# Sales VAT Categories
# ---------------------------------------------------------------------------

def _svat_pending_cr(db_session, requester_id, old_rate="12.00", new_rate="12.00",
                     account_id=None):
    sc = SalesVATCategory(code="SV12", name="Sales Vatable 12%", description="std",
                          rate=Decimal(old_rate), transaction_nature="regular",
                          is_active=True, output_vat_account_id=account_id)
    db_session.add(sc)
    db_session.commit()
    cr = SalesVATCategoryChangeRequest(
        action="update", status="pending", sales_vat_category_id=sc.id,
        proposed_data=json.dumps({"code": "SV12", "name": "Sales Vatable 12%",
                                  "description": "std", "rate": float(new_rate),
                                  "transaction_nature": "regular",
                                  "is_active": True,
                                  "output_vat_account_id": account_id}),
        requested_by_id=requester_id,
        request_reason="testing",
    )
    db_session.add(cr)
    db_session.commit()
    return sc, cr


class TestSalesVatCategoryWithdraw:
    def test_requester_can_withdraw_own_pending_request(
            self, client, db_session, admin_user, main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("sales_vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

    def test_withdrawal_clears_duplicate_pending_guard(
            self, client, db_session, admin_user, main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        login(client, "admin", "admin123")

        client.post(url_for("sales_vat_categories.withdraw_change_request", id=cr.id),
                    follow_redirects=True)
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

        resp = client.post(
            url_for("sales_vat_categories.edit", id=sc.id),
            data={
                "code": "SV12", "name": "Sales Vatable 12%",
                "description": "updated description",
                "rate": "12.00",
                "transaction_nature": "regular",
                "output_vat_account_id": str(cash_account.id),
                "is_active": "1",
                "request_reason": "routine edit",
            },
            follow_redirects=True)

        assert resp.status_code == 200
        assert b"already exists" not in resp.data
        assert b"updated successfully" in resp.data
        db_session.refresh(sc)
        assert sc.description == "updated description"

    def test_non_requester_cannot_withdraw_others_request(
            self, client, db_session, admin_user, chief_accountant_user,
            main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        login(client, "chief", "chief123")

        resp = client.post(
            url_for("sales_vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "pending"
        assert b"own" in resp.data.lower()

    def test_withdrawing_already_processed_request_is_refused(
            self, client, db_session, admin_user, main_branch, cash_account):
        admin_user.add_branch(main_branch)
        db_session.commit()
        sc, cr = _svat_pending_cr(db_session, admin_user.id, account_id=cash_account.id)
        cr.status = "rejected"
        db_session.commit()
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("sales_vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "rejected"
        assert b"already been processed" in resp.data

    def test_rate_change_stuck_scenario_is_withdrawable(
            self, client, db_session, admin_user, main_branch, cash_account):
        sc = SalesVATCategory(code="SV12", name="Sales Vatable 12%", description="std",
                              rate=Decimal("12.00"), transaction_nature="regular",
                              is_active=True, output_vat_account_id=cash_account.id)
        db_session.add(sc)
        db_session.commit()
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("sales_vat_categories.edit", id=sc.id),
            data={
                "code": "SV12", "name": "Sales Vatable 12%", "description": "std",
                "rate": "10.00",
                "transaction_nature": "regular",
                "output_vat_account_id": str(cash_account.id),
                "is_active": "1",
                "request_reason": "rate correction",
            },
            follow_redirects=True)
        assert resp.status_code == 200

        db_session.refresh(sc)
        assert sc.rate == Decimal("12.00")
        cr = SalesVATCategoryChangeRequest.query.filter_by(
            sales_vat_category_id=sc.id, status="pending").first()
        assert cr is not None

        resp = client.post(
            url_for("sales_vat_categories.withdraw_change_request", id=cr.id),
            follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

        resp = client.post(
            url_for("sales_vat_categories.edit", id=sc.id),
            data={
                "code": "SV12", "name": "Sales Vatable 12%",
                "description": "unblocked now",
                "rate": "12.00",
                "transaction_nature": "regular",
                "output_vat_account_id": str(cash_account.id),
                "is_active": "1",
                "request_reason": "routine edit",
            },
            follow_redirects=True)
        assert resp.status_code == 200
        assert b"already exists" not in resp.data
        assert b"updated successfully" in resp.data


# ---------------------------------------------------------------------------
# Withholding Tax
# ---------------------------------------------------------------------------

def _wht_pending_cr(db_session, requester_id, old_rate="10.00", new_rate="10.00"):
    wt = WithholdingTax(code="WC158", name="EWT 10%", sales_name="EWT 10%",
                        description="std", rate=Decimal(old_rate), is_active=True)
    db_session.add(wt)
    db_session.commit()
    cr = WithholdingTaxChangeRequest(
        action="update", status="pending", withholding_tax_id=wt.id,
        proposed_data=json.dumps({"code": "WC158", "name": "EWT 10%",
                                  "sales_name": "EWT 10%", "description": "std",
                                  "rate": float(new_rate), "tax_type": "expanded",
                                  "is_active": True,
                                  "payable_account_id": None,
                                  "receivable_account_id": None}),
        requested_by_id=requester_id,
        request_reason="testing",
    )
    db_session.add(cr)
    db_session.commit()
    return wt, cr


class TestWithholdingTaxWithdraw:
    def test_requester_can_withdraw_own_pending_request(
            self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_pending_cr(db_session, admin_user.id)
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("withholding_tax.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

    def test_withdrawal_clears_duplicate_pending_guard(
            self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_pending_cr(db_session, admin_user.id)
        login(client, "admin", "admin123")

        client.post(url_for("withholding_tax.withdraw_change_request", id=cr.id),
                    follow_redirects=True)
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

        resp = client.post(
            url_for("withholding_tax.edit", id=wt.id),
            data={
                "code": "WC158", "name": "EWT 10%", "sales_name": "EWT 10%",
                "description": "updated description",
                "rate": "10.00", "tax_type": "expanded",
                "payable_account_id": "0", "receivable_account_id": "0",
                "is_active": "1",
                "request_reason": "routine edit",
            },
            follow_redirects=True)

        assert resp.status_code == 200
        assert b"already exists" not in resp.data
        assert b"updated successfully" in resp.data
        db_session.refresh(wt)
        assert wt.description == "updated description"

    def test_non_requester_cannot_withdraw_others_request(
            self, client, db_session, admin_user, chief_accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_pending_cr(db_session, admin_user.id)
        login(client, "chief", "chief123")

        resp = client.post(
            url_for("withholding_tax.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "pending"
        assert b"own" in resp.data.lower()

    def test_withdrawing_already_processed_request_is_refused(
            self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        wt, cr = _wht_pending_cr(db_session, admin_user.id)
        cr.status = "approved"
        db_session.commit()
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("withholding_tax.withdraw_change_request", id=cr.id),
            follow_redirects=True)

        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "approved"
        assert b"already been processed" in resp.data

    def test_rate_change_stuck_scenario_is_withdrawable(
            self, client, db_session, admin_user, main_branch):
        wt = WithholdingTax(code="WC158", name="EWT 10%", sales_name="EWT 10%",
                            description="std", rate=Decimal("10.00"), is_active=True)
        db_session.add(wt)
        db_session.commit()
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, "admin", "admin123")

        resp = client.post(
            url_for("withholding_tax.edit", id=wt.id),
            data={
                "code": "WC158", "name": "EWT 10%", "sales_name": "EWT 10%",
                "description": "std",
                "rate": "5.00",  # changed from 10.00
                "tax_type": "expanded",
                "payable_account_id": "0", "receivable_account_id": "0",
                "is_active": "1",
                "request_reason": "rate correction",
            },
            follow_redirects=True)
        assert resp.status_code == 200

        db_session.refresh(wt)
        assert wt.rate == Decimal("10.00")  # NOT auto-applied
        cr = WithholdingTaxChangeRequest.query.filter_by(
            withholding_tax_id=wt.id, status="pending").first()
        assert cr is not None

        resp = client.post(
            url_for("withholding_tax.withdraw_change_request", id=cr.id),
            follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(cr)
        assert cr.status == "withdrawn"

        resp = client.post(
            url_for("withholding_tax.edit", id=wt.id),
            data={
                "code": "WC158", "name": "EWT 10%", "sales_name": "EWT 10%",
                "description": "unblocked now",
                "rate": "10.00",
                "tax_type": "expanded",
                "payable_account_id": "0", "receivable_account_id": "0",
                "is_active": "1",
                "request_reason": "routine edit",
            },
            follow_redirects=True)
        assert resp.status_code == 200
        assert b"already exists" not in resp.data
        assert b"updated successfully" in resp.data
