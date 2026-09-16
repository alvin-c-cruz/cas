"""AP due-date floor: due date is computed from and floored at the Vendor
Invoice Date (the vendor's receipt date), falling back to the Voucher Date when
no Vendor Invoice Date is entered. Replaces the old floor-at-Voucher-Date rule.
"""
from datetime import date

import pytest

from app.accounts_payable.forms import AccountsPayableForm

pytestmark = [pytest.mark.accounts_payable, pytest.mark.unit]


def _form(app, *, ap_date, due_date, vendor_invoice_date):
    with app.test_request_context():
        form = AccountsPayableForm(formdata=None, meta={'csrf': False})
        form.vendor_id.choices = [(1, 'Test Vendor')]
        form.vendor_id.data = 1
        form.ap_number.data = 'AP-2026-09-0001'
        form.ap_date.data = ap_date
        form.due_date.data = due_date
        form.vendor_invoice_date.data = vendor_invoice_date
        form.notes.data = 'test'
        form.validate()
        return form


def test_due_on_or_after_invoice_date_is_valid_even_if_before_voucher(app):
    # Vendor invoiced 2026-09-01; voucher entered late on 2026-09-20;
    # Net 15 -> due 2026-09-16, which is BEFORE the voucher date. Must be allowed.
    form = _form(app, ap_date=date(2026, 9, 20), due_date=date(2026, 9, 16),
                 vendor_invoice_date=date(2026, 9, 1))
    assert 'due_date' not in form.errors


def test_due_before_invoice_date_is_invalid(app):
    form = _form(app, ap_date=date(2026, 9, 1), due_date=date(2026, 8, 20),
                 vendor_invoice_date=date(2026, 9, 1))
    assert 'due_date' in form.errors


def test_empty_invoice_date_floors_at_voucher_date(app):
    # No vendor invoice date -> floor falls back to the voucher date.
    bad = _form(app, ap_date=date(2026, 9, 10), due_date=date(2026, 9, 5),
                vendor_invoice_date=None)
    assert 'due_date' in bad.errors
    ok = _form(app, ap_date=date(2026, 9, 10), due_date=date(2026, 10, 10),
               vendor_invoice_date=None)
    assert 'due_date' not in ok.errors
