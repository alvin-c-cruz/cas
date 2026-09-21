"""A draft bill may not walk away from the Purchase Order it already billed.

THE INCIDENT THIS PINS (philgen, 2026-09-11, found 2026-09-21)
--------------------------------------------------------------
APV 00013 was created for ROTOPACK and billed ROTOPACK's PO 01134, which set that
order to 'closed' and linked it to the voucher. Forty-four minutes later the SAME
draft voucher was edited and its payee changed to JOHNSON HARDWARE. Billing runs
only on create (`app/accounts_payable/views.py`, `_bill_purchase_sources`) and
unbilling only on cancel/void, so the edit released nothing: ROTOPACK's order stayed
closed, pointing at what became JOHNSON's posted bill. A 'closed' PO is outside
RECEIVABLE_PO_STATUSES and outside billable_pos_for, so for ten days nobody could
receive or bill against a PHP 212,000 order, and the PO's own audit trail said
nothing -- billing mutates status without logging.

The create path has always guarded this (`po.vendor_id != ap.vendor_id` ->
"no longer billable"). The edit path never re-ran it. These tests are that guard's
missing half.
"""
import json
from datetime import date

import pytest

from app import db
from app.accounts_payable.models import AccountsPayable
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def two_vendors_and_account(db_session):
    """Two vendors and a postable expense account, plus the control accounts the
    AP create path resolves through (never hardcoded -- see CLAUDE.md)."""
    from tests.conftest import assign_control_accounts
    from app.accounts.models import Account
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Test Expense AP-EDIT', 'Expense', 'Debit'),
    ]:
        db_session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db_session.commit()
    rotopack = Vendor(code='V-ROTO', name='ROTOPACK MANUFACTURING CORPORATION',
                      tin='111-111-111-00000', is_active=True)
    johnson = Vendor(code='V-JOHN', name='JOHNSON HARDWARE AND CONSTRUCTION SUPPLY INC.',
                     tin='222-222-222-00000', is_active=True)
    db_session.add_all([rotopack, johnson]); db_session.commit()
    assign_control_accounts(db_session)
    expense = Account.query.filter_by(code='69903').first()
    return rotopack, johnson, expense


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po(db_session, branch, vendor, number='PO-APEDIT-0001'):
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Plastic pouch',
                                           quantity=100, unit_price=10, amount=1000))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _form_data(vendor, expense, **over):
    data = {
        'ap_number': 'AP-EDIT-0001',
        'ap_date': date(2026, 7, 11).isoformat(),
        'due_date': date(2026, 8, 11).isoformat(),
        'vendor_id': vendor.id,
        'payee': f'vendor:{vendor.id}',
        'vendor_invoice_number': 'INV-EDIT-1',
        'payment_terms': 'Net 30',
        'notes': 'Billed from a purchase order',
        'line_items': json.dumps([{
            'description': 'Plastic pouch', 'amount': 1000.0,
            'vat_category': None, 'account_id': expense.id,
            'wt_id': None, 'wt_rate': None,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    data.update(over)
    return data


def _edit(client, ap, vendor, expense, **over):
    """POST the edit form. `row_version` is read from the RAW body by
    submitted_version() and fails closed, so an edit test that omits it never
    reaches the save at all -- it silently re-renders and every assertion below
    passes or fails for the wrong reason."""
    return client.post(f'/accounts-payable/{ap.id}/edit',
                       data=_form_data(vendor, expense, row_version=str(ap.row_version),
                                       **over),
                       follow_redirects=True)


def _create_bill_against(client, vendor, expense, po):
    """Create a draft AP that bills *po* -- the legitimate first half of the incident."""
    return client.post('/accounts-payable/create',
                       data=_form_data(vendor, expense, source_po_ids=json.dumps([po.id])),
                       follow_redirects=True)


class TestADraftBillCannotAbandonWhatItBilled:

    def test_changing_the_payee_is_refused_while_a_po_is_billed(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        """The incident, reproduced: bill ROTOPACK's PO, then try to become JOHNSON's bill."""
        rotopack, johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, rotopack)
        _create_bill_against(client, rotopack, expense, po)

        ap = AccountsPayable.query.one()
        db.session.refresh(po)
        assert (po.status, po.accounts_payable_id) == ('closed', ap.id), \
            'setup failed: the bill did not actually bill the PO'

        resp = _edit(client, ap, johnson, expense, payee=f'vendor:{johnson.id}',
                     vendor_id=johnson.id)

        db.session.refresh(ap); db.session.refresh(po)
        assert ap.vendor_id == rotopack.id, 'the bill changed vendor despite billing a PO'
        assert po.status == 'closed' and po.accounts_payable_id == ap.id, \
            'the PO was left orphaned -- closed against a bill that is no longer its own'
        body = resp.data.decode()
        assert po.po_number in body, \
            'the refusal must name the order standing in the way, or nobody can act on it'

    def test_editing_anything_else_still_saves(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        """CONTROL. The guard must catch a PAYEE change, not freeze the whole voucher:
        a draft bill with a PO attached is still an ordinary editable draft."""
        rotopack, _johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, rotopack)
        _create_bill_against(client, rotopack, expense, po)
        ap = AccountsPayable.query.one()

        _edit(client, ap, rotopack, expense, notes='Edited particulars')

        db.session.refresh(ap)
        assert ap.notes == 'Edited particulars'
        assert ap.vendor_id == rotopack.id

    def test_a_bill_with_nothing_billed_may_change_payee_freely(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        """CONTROL. Most bills are typed in by hand with no PO behind them; the guard
        must not touch those -- it exists only to protect a real link."""
        rotopack, johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        client.post('/accounts-payable/create', data=_form_data(rotopack, expense),
                    follow_redirects=True)
        ap = AccountsPayable.query.one()
        assert PurchaseOrder.query.filter_by(accounts_payable_id=ap.id).count() == 0

        _edit(client, ap, johnson, expense, payee=f'vendor:{johnson.id}',
              vendor_id=johnson.id)

        db.session.refresh(ap)
        assert ap.vendor_id == johnson.id, \
            'a bill with no billed source must still be freely re-pointed'
