"""An APV on Advance Payment terms posts without a vendor invoice.

Owner, 2026-09-24, on APV 40: it "should be processed with a check because its
advanced payment and therefore no invoice from vendor has been issued."

The post gate refuses a draft with VAT or withholding tax and no vendor invoice
number/date -- right for a bill, wrong for an advance, where the invoice arrives
AFTER the money. The APV form already carries Payment Terms = "Advance Payment";
that is the signal. Every other rule at post is unchanged, and a Net-30 draft
with tax and no invoice is still refused.
"""
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable
from tests.integration.test_accounts_payable_views import login, make_vendor, make_ap

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def _draft_with_tax(db_session, main_branch, number, terms, vat='120.00', wht='0.00'):
    vendor = make_vendor(db_session, code='ADV-' + number, name='Advance Vendor ' + number)
    ap = make_ap(db_session, vendor, main_branch, number, status='draft')
    ap.payment_terms = terms
    ap.vat_amount = Decimal(vat)
    ap.withholding_tax_amount = Decimal(wht)
    ap.vendor_invoice_number = None
    ap.vendor_invoice_date = None
    db_session.commit()
    return ap


def _post(client, main_branch, ap):
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    return client.post(f'/accounts-payable/{ap.id}/post', follow_redirects=True)


def test_a_bill_with_tax_and_no_invoice_is_still_refused(client, db_session, admin_user,
                                                         main_branch):
    """CONTROL: the gate the owner's case is an exception to."""
    ap = _draft_with_tax(db_session, main_branch, 'ADV-0001', 'Net 30')
    resp = _post(client, main_branch, ap)
    assert b'Vendor Invoice #' in resp.data
    assert db_session.get(AccountsPayable, ap.id).status == 'draft'


def test_an_advance_payment_with_vat_posts_without_an_invoice(client, db_session,
                                                              admin_user, main_branch):
    ap = _draft_with_tax(db_session, main_branch, 'ADV-0002', 'Advance Payment')
    resp = _post(client, main_branch, ap)
    assert b'Vendor Invoice #' not in resp.data
    assert db_session.get(AccountsPayable, ap.id).status == 'posted'


def test_an_advance_payment_with_withholding_posts_without_an_invoice(client, db_session,
                                                                      admin_user, main_branch):
    """WHT is withheld on payment, advance or not -- the gate must not read it as
    'there must be an invoice'."""
    # Posting a WHT amount books a WHT Payable leg, which needs the control account.
    from tests.integration.test_cdv_number_editable import setup_accounts
    setup_accounts(db_session)
    ap = _draft_with_tax(db_session, main_branch, 'ADV-0003', 'Advance Payment',
                         vat='0.00', wht='20.00')
    _post(client, main_branch, ap)
    assert db_session.get(AccountsPayable, ap.id).status == 'posted'
