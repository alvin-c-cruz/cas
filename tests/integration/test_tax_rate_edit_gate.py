import pytest
from decimal import Decimal
from flask import url_for
from app import db
from app.accounts.models import Account
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.sales_vat_categories.models import (
    SalesVATCategory, SalesVATCategoryChangeRequest)
from app.withholding_tax.models import (
    WithholdingTax, WithholdingTaxChangeRequest)

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.post("/login", data={"username": username, "password": password},
                follow_redirects=True)


def _make_input_account(db_session, code="10599", name="Input VAT"):
    acct = Account(code=code, name=name, account_type="Asset",
                   normal_balance="Debit", is_active=True)
    db_session.add(acct)
    db_session.commit()
    return acct


def _make_vat(db_session, acct_id):
    vc = VATCategory(code="V12", name="Vatable 12%", description="std",
                     rate=Decimal("12.00"), is_active=True,
                     input_vat_account_id=acct_id)
    db_session.add(vc)
    db_session.commit()
    return vc


class TestVatRateEditForcesReview:
    def test_rate_change_by_lone_reviewer_goes_pending(self, client, db_session,
                                                       chief_accountant_user, main_branch):
        # chief is the ONLY active full-access user -> would normally auto-approve
        acct = _make_input_account(db_session)
        vc = _make_vat(db_session, acct.id)
        login(client, "chief", "chief123")
        client.post(url_for("vat_categories.edit", id=vc.id), data={
            "code": "V12", "name": "Vatable 12%", "description": "std",
            "rate": "2.00", "is_active": "1", "input_vat_account_id": str(acct.id),
            "request_reason": "correcting the rate",
        }, follow_redirects=True)
        db_session.refresh(vc)
        assert vc.rate == Decimal("12.00")  # not applied directly
        pending = VATCategoryChangeRequest.query.filter_by(
            vat_category_id=vc.id, status="pending").count()
        assert pending == 1

    def test_non_rate_change_by_lone_reviewer_auto_applies(self, client, db_session,
                                                           chief_accountant_user, main_branch):
        acct = _make_input_account(db_session)
        vc = _make_vat(db_session, acct.id)
        login(client, "chief", "chief123")
        client.post(url_for("vat_categories.edit", id=vc.id), data={
            "code": "V12", "name": "Vatable 12% (renamed)", "description": "std",
            "rate": "12.00", "is_active": "1", "input_vat_account_id": str(acct.id),
            "request_reason": "rename only",
        }, follow_redirects=True)
        db_session.refresh(vc)
        assert vc.name == "Vatable 12% (renamed)"
        pending = VATCategoryChangeRequest.query.filter_by(
            vat_category_id=vc.id, status="pending").count()
        assert pending == 0


def _make_output_account(db_session, code="20201", name="Output VAT"):
    acct = Account(code=code, name=name, account_type="Liability",
                   normal_balance="Credit", is_active=True)
    db_session.add(acct)
    db_session.commit()
    return acct


def _make_svat(db_session, acct_id):
    sc = SalesVATCategory(code="SV12", name="Sales Vatable 12%", description="std",
                          rate=Decimal("12.00"), transaction_nature="regular",
                          is_active=True, output_vat_account_id=acct_id)
    db_session.add(sc)
    db_session.commit()
    return sc


class TestSalesVatRateEditForcesReview:
    def test_rate_change_by_lone_reviewer_goes_pending(self, client, db_session,
                                                       chief_accountant_user, main_branch):
        acct = _make_output_account(db_session)
        sc = _make_svat(db_session, acct.id)
        login(client, "chief", "chief123")
        client.post(url_for("sales_vat_categories.edit", id=sc.id), data={
            "code": "SV12", "name": "Sales Vatable 12%", "description": "std",
            "rate": "2.00", "transaction_nature": "regular", "is_active": "1",
            "output_vat_account_id": str(acct.id), "request_reason": "fix rate",
        }, follow_redirects=True)
        db_session.refresh(sc)
        assert sc.rate == Decimal("12.00")
        assert SalesVATCategoryChangeRequest.query.filter_by(
            sales_vat_category_id=sc.id, status="pending").count() == 1


def _make_wht(db_session):
    wt = WithholdingTax(code="WC158", name="EWT 10%", sales_name="EWT 10%",
                        description="std", rate=Decimal("10.00"), is_active=True)
    db_session.add(wt)
    db_session.commit()
    return wt


class TestWhtRateEditForcesReview:
    def test_rate_change_by_lone_reviewer_goes_pending(self, client, db_session,
                                                       chief_accountant_user, main_branch):
        wt = _make_wht(db_session)
        login(client, "chief", "chief123")
        client.post(url_for("withholding_tax.edit", id=wt.id), data={
            "code": "WC158", "name": "EWT 10%", "sales_name": "EWT 10%",
            "description": "std", "rate": "2.00", "is_active": "1",
            "payable_account_id": "0", "receivable_account_id": "0",
            "request_reason": "fix rate",
        }, follow_redirects=True)
        db_session.refresh(wt)
        assert wt.rate == Decimal("10.00")
        assert WithholdingTaxChangeRequest.query.filter_by(
            withholding_tax_id=wt.id, status="pending").count() == 1
