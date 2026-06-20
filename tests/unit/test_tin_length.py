"""Customer/Vendor TIN field accepts up to 50 chars (legacy TINs run to ~28)."""
import pytest
from app.customers.forms import CustomerForm
from app.vendors.forms import VendorForm

pytestmark = [pytest.mark.unit]

# 27 chars — a real legacy-style TIN with an embedded annotation; exceeds the old 20-char cap.
LONG_TIN = '000-308-093-00000 (VATABLE)'


def _tin_errors(app, FormClass, tin):
    with app.test_request_context(method='POST', data={'tin': tin}):
        form = FormClass(meta={'csrf': False})
        form.validate()
        return list(form.tin.errors)


def test_customer_form_accepts_long_tin(app):
    assert _tin_errors(app, CustomerForm, LONG_TIN) == []


def test_vendor_form_accepts_long_tin(app):
    assert _tin_errors(app, VendorForm, LONG_TIN) == []
