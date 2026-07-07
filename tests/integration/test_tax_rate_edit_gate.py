import pytest
from decimal import Decimal
from flask import url_for
from app import db
from app.accounts.models import Account
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest

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
