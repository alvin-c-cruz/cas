"""Payment terms are the same list everywhere, or they are a trap.

The six-choice list is hardcoded SEVEN times -- customers, vendors, sales
invoices, sales orders, quotations, purchase orders, accounts payable -- with no
shared constant between them. Nothing computes with the value (due_date is
entered separately, never derived), so a mismatch does not crash: it just lets a
customer carry a default term that the invoice raised for them cannot offer.

That is the failure this file exists to prevent, and it is why adding a term
means adding it in all seven places. Whoever gets tired of that should hoist the
list to one constant -- this test keeps passing either way, because it compares
the forms to each other rather than to a copy of the answer.
"""
import pytest

from app.accounts_payable.forms import AccountsPayableForm
from app.customers.forms import CustomerForm
from app.purchase_orders.forms import PurchaseOrderForm
from app.quotations.forms import QuotationForm
from app.sales_invoices.forms import SalesInvoiceForm
from app.sales_orders.forms import SalesOrderForm
from app.vendors.forms import VendorForm

pytestmark = [pytest.mark.unit]

#: Every form that offers a payment term. A form added later and NOT listed here
#: is invisible to this guard -- which is the same duplication problem one level
#: up, so `test_no_form_offers_payment_terms_unlisted` scans the source for it.
FORMS = {
    'customers': CustomerForm,
    'vendors': VendorForm,
    'sales_invoices': SalesInvoiceForm,
    'sales_orders': SalesOrderForm,
    'quotations': QuotationForm,
    'purchase_orders': PurchaseOrderForm,
    'accounts_payable': AccountsPayableForm,
}


def choices_of(form_cls):
    """The declared choices, read off the UnboundField without instantiating.

    Instantiating a WTForms form needs an app/request context and, for several
    of these, a populated database -- none of which this question depends on.
    """
    unbound = form_cls.payment_terms
    choices = unbound.kwargs.get('choices')
    return [c[0] for c in choices]


def test_every_listed_form_actually_declares_the_field():
    """GUARD ON THE GUARD. If a rename made `payment_terms` unreadable, the
    comparison below would compare empty lists and pass."""
    for name, cls in FORMS.items():
        vals = choices_of(cls)
        assert vals, '%s declares no payment_terms choices' % name
        assert len(vals) >= 5, '%s has a suspiciously short list: %s' % (name, vals)


def test_all_seven_forms_offer_the_same_terms():
    """THE GUARD. Compared against EACH OTHER, not against a copy of the list --
    a hardcoded expectation here would just be an eighth duplicate to drift."""
    baseline_name, baseline = next(iter(FORMS.items())), None
    ref_name = list(FORMS)[0]
    ref = choices_of(FORMS[ref_name])
    mismatched = {name: choices_of(cls) for name, cls in FORMS.items()
                  if choices_of(cls) != ref}
    assert not mismatched, (
        'These forms disagree with %s (%s): %s. A customer whose default term '
        'is missing from the invoice form has a default nobody can select.'
        % (ref_name, ref, mismatched))


@pytest.mark.parametrize('name', sorted(FORMS))
def test_net_90_is_offered(name):
    assert 'Net 90' in choices_of(FORMS[name])


@pytest.mark.parametrize('name', sorted(FORMS))
def test_the_existing_terms_survive(name):
    """CONTROL. Adding a term must not quietly drop one -- every value already
    stored in a client database has to stay selectable, or editing an old
    record silently rewrites its terms."""
    vals = choices_of(FORMS[name])
    for term in ('Net 15', 'Net 30', 'Net 45', 'Net 60',
                 'Cash on Delivery', 'Advance Payment'):
        assert term in vals, '%s no longer offers %r' % (name, term)


def test_no_form_offers_payment_terms_unlisted():
    """FORMS above is itself a hand-kept list. Scan the source so an eighth form
    added later fails here instead of drifting unseen."""
    import pathlib
    import re
    app_dir = pathlib.Path(__file__).resolve().parents[2] / 'app'
    found = set()
    for path in app_dir.rglob('forms.py'):
        if re.search(r'payment_terms\s*=\s*SelectField', path.read_text(encoding='utf-8')):
            found.add(path.parent.name)
    assert found, 'the source scan found no payment_terms forms at all'
    unlisted = found - set(FORMS)
    assert not unlisted, (
        'These modules declare a payment_terms SelectField but are not covered '
        'by this test: %s. Add them to FORMS -- an unchecked form is exactly '
        'how the lists drift apart.' % sorted(unlisted))
