"""
The AP voucher no longer offers a Reference/PO Number input.

Measured before removing it: across every client database held locally, **0 of
309** AP vouchers had a reference set (0 of 343 sales invoices too, though SI is
deliberately left alone for now). PhilGen and RIC both confirmed they will not
use it. The PO number reaches the voucher through the Notes (Particulars) text,
which the PO/RR pull now writes automatically.

REMOVED: the input, its form field, and the two view assignments.
KEPT: the `reference` COLUMN, `to_dict()`, and the detail page's existing
`{% if ap.reference %}` block -- so a value that already exists still displays
and nothing in history or exports changes shape. Re-adding it is one line.

The load-bearing test is `test_editing_does_not_wipe...`. Dropping the input
WITHOUT also dropping `ap.reference = form.reference.data` would have been
silently destructive: the edit POST no longer carries the field, so the view
would write an empty value over a reference that was already there -- turning
"stop collecting this" into "delete what we already collected".

Both of that test's preconditions bit during authoring, and both made it pass
while proving nothing: a missing `payment_terms` (DataRequired) failed form
validation, and a stale `row_version` tripped the optimistic-lock guard. Hence
the explicit assertion that the edit actually took.
"""
import json

import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]

EXISTING_REF = 'PO-00981'
EDITED_NOTES = 'PAYMENT FOR THE PURCHASE OF CHLORINE, FOAMKLIN'


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _books(db_session):
    """The COA + control accounts an AP create actually needs.

    Lifted from test_accounts_payable_views.py::_setup -- without the control
    accounts the create route re-renders instead of saving, which quietly made
    the edit test below a no-op.
    """
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Purchases', 'Expense', 'Debit'),
    ]:
        db_session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db_session.commit()
    db_session.add(VATCategory(
        code='V12DG', name='Input Tax Domestic Goods', rate=12.00, is_active=True,
        input_vat_account_id=Account.query.filter_by(code='10502').first().id))
    vendor = Vendor(code='V900', name='Reference Test Vendor',
                    check_payee_name='Reference Test Vendor', is_active=True)
    db_session.add(vendor)
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return vendor, Account.query.filter_by(code='69903').first()


def _ap(vendor, branch, user, reference=None):
    ap = AccountsPayable(
        ap_number='AP-REF-0001', ap_date=date(2026, 8, 19), due_date=date(2026, 9, 18),
        vendor_id=vendor.id, vendor_name=vendor.name, branch_id=branch.id,
        notes='PAYMENT FOR THE PURCHASE OF CHLORINE', reference=reference,
        status='draft', created_by_id=user.id, total_amount=Decimal('0'),
    )
    db.session.add(ap)
    db.session.commit()
    return ap


def _create_through_the_route(client, vendor, account):
    """Create the voucher the way the app does.

    Building it straight from the model left it in a shape the edit route
    rejected, which made the wipe test a no-op. Mirrors the payload of the
    known-passing edits in test_accounts_payable_views.py.
    """
    return client.post('/accounts-payable/create', data={
        'ap_number': 'APV-REF-1', 'ap_date': date(2026, 8, 19).isoformat(),
        'due_date': date(2026, 9, 18).isoformat(), 'vendor_id': vendor.id,
        'vendor_invoice_number': 'INV-REF-1', 'payment_terms': 'Net 30',
        'notes': 'PAYMENT FOR THE PURCHASE OF CHLORINE',
        'line_items': json.dumps([{'description': 'CHLORINE', 'amount': 1000.0,
                                   'vat_category': None, 'account_id': account.id,
                                   'wt_id': None, 'wt_rate': None}]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    })


def _edit_payload(ap, vendor, account):
    """An edit POST shaped as the browser now sends it -- with no `reference`."""
    return {
        'ap_number': ap.ap_number,
        'ap_date': ap.ap_date.isoformat(),
        'due_date': ap.due_date.isoformat(),
        'vendor_id': vendor.id,
        'vendor_invoice_number': ap.vendor_invoice_number or 'INV-REF-1',
        'payment_terms': 'Net 30',
        'notes': EDITED_NOTES,
        'row_version': ap.row_version,
        'line_items': json.dumps([{'description': 'CHLORINE', 'amount': 1000.0,
                                   'vat_category': None, 'account_id': account.id,
                                   'wt_id': None, 'wt_rate': None}]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }


def test_the_create_form_no_longer_offers_a_reference_input(client, db_session,
                                                            main_branch, accountant_user):
    _login(client, accountant_user, main_branch)

    body = client.get('/accounts-payable/create').data.decode()

    assert 'name="reference"' not in body
    assert 'Reference/PO Number' not in body, \
        'the label is still rendered even though the input is gone'


def test_the_rest_of_the_form_still_renders(client, db_session, main_branch,
                                            accountant_user):
    """CONTROL: removing one field must not take out its neighbours.

    Save behaviour is already covered by the existing accounts_payable suite,
    which creates vouchers through this same route -- if the removal broke
    creation, those go red.
    """
    _login(client, accountant_user, main_branch)

    body = client.get('/accounts-payable/create').data.decode()

    for still_there in ('name="ap_number"', 'name="notes"', 'name="payment_terms"',
                        'name="vendor_invoice_number"', 'id="payee"'):
        assert still_there in body, '%s disappeared with the reference field' % still_there


def test_editing_does_not_wipe_a_reference_that_already_exists(client, db_session,
                                                              main_branch, accountant_user):
    """The whole point of keeping the column."""
    vendor, account = _books(db_session)
    _login(client, accountant_user, main_branch)
    assert _create_through_the_route(client, vendor, account).status_code == 302,         'the voucher did not save, so nothing below is exercising an edit'

    ap = AccountsPayable.query.filter_by(ap_number='APV-REF-1').first()
    ap.reference = EXISTING_REF          # a value recorded before the field went away
    db.session.commit()

    client.post('/accounts-payable/%s/edit' % ap.id,
                data=_edit_payload(ap, vendor, account), follow_redirects=True)

    db.session.expire_all()
    saved = db.session.get(AccountsPayable, ap.id)
    assert saved.notes == EDITED_NOTES,         'the edit never went through, so this test proves nothing about reference'
    assert saved.reference == EXISTING_REF,         'editing the voucher erased a reference recorded before the field was removed'


def test_the_detail_page_still_shows_a_reference_that_exists(client, db_session,
                                                             main_branch, accountant_user):
    """Kept data stays visible -- otherwise removal would hide history."""
    vendor, _ = _books(db_session)
    ap = _ap(vendor, main_branch, accountant_user, reference=EXISTING_REF)
    _login(client, accountant_user, main_branch)

    body = client.get('/accounts-payable/%s' % ap.id).data.decode()

    assert EXISTING_REF in body


def test_the_column_and_to_dict_are_untouched(db_session, main_branch, accountant_user):
    """Nothing downstream changes shape: exports still see the key."""
    vendor, _ = _books(db_session)
    ap = _ap(vendor, main_branch, accountant_user, reference=EXISTING_REF)

    assert ap.to_dict()['reference'] == EXISTING_REF
