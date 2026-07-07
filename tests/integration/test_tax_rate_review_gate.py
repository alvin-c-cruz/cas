import json
import pytest
from decimal import Decimal
from flask import url_for
from app import db
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest

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
