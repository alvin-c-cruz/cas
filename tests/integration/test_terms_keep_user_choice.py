"""A1 (22 Nov 2026, Philgen SO-DR trial; owner: "fix A1 tonight if it fits"): a Payment Terms the user chose is never
replaced by the customer's (or vendor's) default.

Choosing the customer applied its default terms every time, even over a term the user had already picked. The dimmed
header blocks the mouse until a customer is chosen, but not the keyboard, so a term could be set first and was then
silently replaced: the trial saved Net 60 for a chosen Net 90 (Hilas's default) and Net 30 for a chosen Net 60
(W.L. Food's). The Sales Order's default salesperson was applied the same way. The Sales Invoice and AP forms also left
the due date at the default's when the user changed the terms.

The browser tests are in tests/e2e/test_terms_keep_user_choice_smoke.py; these check each form's script.
Work order: app-docs/bug-reports/2026-11-22-so-payment-terms-saves-wrong-value.md.
"""
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

FORMS = [
    ('sales_orders/templates/sales_orders/form.html', 'applyCustomerTerms'),
    ('sales_invoices/templates/sales_invoices/form.html', 'applyCustomerTerms'),
    ('quotations/templates/quotations/form.html', 'applyCustomerTerms'),
    ('accounts_payable/templates/accounts_payable/form.html', 'applyVendorTerms'),
]


def _src(app, rel):
    return (Path(app.root_path) / rel).read_text(encoding='utf-8')


def _function(src, name):
    start = src.index(f'function {name}(')
    return src[start:src.index('\n}\n', start)]


@pytest.mark.parametrize('rel, apply', FORMS)
def test_a_default_never_replaces_a_term_the_user_chose(app, rel, apply):
    src = _src(app, rel)
    assert 'let termsChosenByUser = false;' in src, rel
    body = _function(src, apply)
    assert body.index('if (termsChosenByUser)') < body.index('setChoiceByValue'), rel
    # Only the user's own change marks it: Choices' setChoiceByValue fires no change event.
    listener = src[src.index("ptSel.addEventListener('change', function () {"):]
    assert 'termsChosenByUser = true;' in listener[:listener.index('});')], rel


@pytest.mark.parametrize('rel', [FORMS[1][0], FORMS[3][0]])
def test_the_due_date_follows_the_terms_the_user_chose(app, rel):
    src = _src(app, rel)
    listener = src[src.index("ptSel.addEventListener('change', function () {"):]
    assert 'recomputeDueDate();' in listener[:listener.index('});')], rel


def test_the_customers_default_salesperson_never_replaces_the_one_chosen(app):
    src = _src(app, FORMS[0][0])
    assert 'let salespersonChosenByUser = false;' in src
    assert 'data.default_salesperson_id != null && !salespersonChosenByUser' in src
    listener = src[src.index("spInput.addEventListener('change', function () {"):]
    assert 'salespersonChosenByUser = true;' in listener[:listener.index('});')]
