import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy import text
from app import db
from app.purchase_bills.models import PurchaseBill
from app.branches.models import Branch
from app.vendors.models import Vendor


def test_bill_without_notes_violates_not_null(db_session):
    """DB-level NOT NULL on notes must fire when NULL is inserted via raw SQL."""
    branch = Branch(name='Main', code='MAIN')
    db.session.add(branch)
    vendor = Vendor(code='V1', name='V', check_payee_name='V', is_active=True, payment_terms='Net 30')
    db.session.add(vendor)
    db.session.commit()

    # The ORM default='' means the ORM never sends NULL — test the DB constraint directly.
    with pytest.raises(Exception):  # IntegrityError: NOT NULL constraint failed
        db.session.execute(text(
            "INSERT INTO purchase_bills "
            "(bill_number, bill_date, due_date, vendor_id, vendor_name, total_amount, "
            "subtotal, vat_amount, total_before_wt, withholding_tax_rate, "
            "withholding_tax_amount, vat_override, wt_override, status, "
            "amount_paid, balance, created_at, updated_at, notes) "
            "VALUES ('AP-X-1','2026-06-01','2026-06-30',:vid,'V',100,"
            "0,0,0,0,0,0,0,'draft',0,0,'2026-06-01','2026-06-01', NULL)"
        ), {'vid': vendor.id})
        db.session.commit()
    db.session.rollback()


def test_bill_orm_default_notes_is_empty_string(db_session):
    """ORM default='' means omitting notes yields '' (not None) after flush."""
    branch = Branch(name='Main', code='MAIN')
    db.session.add(branch)
    vendor = Vendor(code='V1', name='V', check_payee_name='V', is_active=True, payment_terms='Net 30')
    db.session.add(vendor)
    db.session.commit()

    bill = PurchaseBill(
        branch_id=branch.id, bill_number='AP-X-2', bill_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30), vendor_id=vendor.id, vendor_name='V',
        total_amount=Decimal('100.00'))  # notes intentionally omitted
    db.session.add(bill)
    db.session.commit()

    assert bill.notes == '', f"Expected empty string, got {repr(bill.notes)}"
