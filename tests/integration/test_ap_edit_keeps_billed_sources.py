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
import pathlib
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts_payable.models import AccountsPayable
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
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


# ---------------------------------------------------------------------------
# Each LINE keeps its link to the PO/RR line it billed.
# ---------------------------------------------------------------------------

FORM_HTML = (pathlib.Path(__file__).resolve().parents[2] / 'app' / 'accounts_payable'
             / 'templates' / 'accounts_payable' / 'form.html')


def _rr(db_session, branch, po, received=60, number='RR-APEDIT-0001'):
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 11),
                         vendor_id=po.vendor_id, vendor_name=po.vendor_name, status='approved')
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    return rr


def _billed_line(expense, *, po_item_id=None, rr_item_id=None, qty=60, price=11):
    """One line as the PO/RR billing picker injects it (ap_po_billing.js injectLines)."""
    return {
        'description': 'Plastic pouch', 'amount': float(qty * price),
        'quantity': qty, 'unit_price': price,
        'vat_category': None, 'account_id': expense.id, 'wt_id': None, 'wt_rate': None,
        'source_po_item_id': po_item_id, 'source_rr_item_id': rr_item_id,
    }


def _lines_the_edit_page_loads(client, ap):
    """The `existingItems` the edit page hands its JavaScript -- the only line data
    the browser has when the user saves."""
    page = client.get(f'/accounts-payable/{ap.id}/edit').data.decode()
    m = re.search(r'const existingItems = (.*?);\n', page)
    assert m, 'the edit page no longer renders existingItems -- update this helper'
    return json.loads(m.group(1))


def _as_the_browser_posts(items):
    """form.html's submit handler, key for key: what the browser sends back for each
    loaded line. initItems() first maps unit_of_measure_id onto uom_id."""
    out = []
    for it in items:
        uom_id = it['uom_id'] if 'uom_id' in it else it.get('unit_of_measure_id')
        out.append({
            'description': it.get('description'),
            'amount': it.get('amount'),
            'product_id': it.get('product_id') or None,
            'quantity': it.get('quantity'),
            'uom_id': uom_id or None,
            'uom_text': it.get('uom_text') or '',
            'unit_price': it.get('unit_price'),
            'vat_category': it.get('vat_category'),
            'account_id': it.get('account_id'),
            'wt_id': it.get('wt_id'),
            'wt_rate': it.get('wt_rate'),
            'source_po_item_id': it.get('source_po_item_id') or None,
            'source_rr_item_id': it.get('source_rr_item_id') or None,
        })
    return out


class TestAnEditKeepsEachLineLinkedToItsSource:
    """THE INCIDENT (philgen, 2 Nov 2026): APV 00054 was created by billing RR 00768,
    both lines linked to their RR (and PO) lines. Nine minutes later the owner opened
    the edit form only to change the invoice and due dates, and saved. Both lines came
    back with source_rr_item_id / source_po_item_id NULL and the variance snapshot
    gone, while the RR still said 'billed' to that voucher. APV 00053 likewise.

    The edit page serialises the lines through AccountsPayableItem.to_dict(), which
    did not carry the link fields; the form posts back only what it loaded, and edit()
    rebuilds every line from that post. So ANY save unlinked EVERY line.

    These tests take the lines from the rendered edit page and post them back the way
    the browser does -- a hand-written POST carrying the ids would pass while the real
    form kept failing."""

    def test_rr_billed_lines_keep_their_links_when_only_a_date_changes(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        rotopack, _johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, rotopack)
        rr = _rr(db_session, main_branch, po, received=60)
        rr_item_id, po_item_id = rr.line_items[0].id, po.line_items[0].id
        client.post('/accounts-payable/create', data=_form_data(
            rotopack, expense, source_rr_ids=json.dumps([rr.id]),
            line_items=json.dumps([_billed_line(expense, rr_item_id=rr_item_id)])),
            follow_redirects=True)
        ap = AccountsPayable.query.one()
        line = ap.line_items[0]
        assert (line.source_rr_item_id, line.source_po_item_id) == (rr_item_id, po_item_id), \
            'setup failed: the bill was not created linked to the RR line'

        posted = _as_the_browser_posts(_lines_the_edit_page_loads(client, ap))
        _edit(client, ap, rotopack, expense, due_date=date(2026, 9, 11).isoformat(),
              line_items=json.dumps(posted))

        db.session.expire_all()
        ap = db.session.get(AccountsPayable, ap.id)
        assert ap.due_date == date(2026, 9, 11), 'setup failed: the edit did not save'
        line = ap.line_items[0]
        assert line.source_rr_item_id == rr_item_id, 'the edit unlinked the line from its RR line'
        assert line.source_po_item_id == po_item_id, 'the edit unlinked the line from its PO line'
        assert line.matched_unit_price == Decimal('10.00')
        assert line.matched_quantity == Decimal('60.0000')
        assert line.price_variance == Decimal('1.00'), 'the variance snapshot was lost'
        rr = db.session.get(ReceivingReport, rr.id)
        assert (rr.status, rr.accounts_payable_id) == ('billed', ap.id)

    def test_po_billed_lines_keep_their_link_when_only_a_date_changes(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        rotopack, _johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, rotopack)
        po_item_id = po.line_items[0].id
        client.post('/accounts-payable/create', data=_form_data(
            rotopack, expense, source_po_ids=json.dumps([po.id]),
            line_items=json.dumps([_billed_line(expense, po_item_id=po_item_id,
                                                 qty=80, price=10)])),
            follow_redirects=True)
        ap = AccountsPayable.query.one()
        assert ap.line_items[0].source_po_item_id == po_item_id, 'setup failed'

        posted = _as_the_browser_posts(_lines_the_edit_page_loads(client, ap))
        _edit(client, ap, rotopack, expense, due_date=date(2026, 9, 11).isoformat(),
              line_items=json.dumps(posted))

        db.session.expire_all()
        ap = db.session.get(AccountsPayable, ap.id)
        assert ap.due_date == date(2026, 9, 11), 'setup failed: the edit did not save'
        line = ap.line_items[0]
        assert line.source_po_item_id == po_item_id, 'the edit unlinked the line from its PO line'
        assert line.source_rr_item_id is None
        assert line.matched_unit_price == Decimal('10.00')
        assert line.matched_quantity == Decimal('100.0000')
        assert line.quantity_variance == Decimal('-20.0000')

    def test_the_edit_page_carries_the_variance_snapshot(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        """checkVariance() in form.html reads matched_unit_price / matched_quantity off
        the loaded line; without them the 'Ordered @ ...' note never shows on the edit
        page, even for a line that is still linked."""
        rotopack, _johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, rotopack)
        rr = _rr(db_session, main_branch, po, received=60)
        client.post('/accounts-payable/create', data=_form_data(
            rotopack, expense, source_rr_ids=json.dumps([rr.id]),
            line_items=json.dumps([_billed_line(expense, rr_item_id=rr.line_items[0].id)])),
            follow_redirects=True)
        ap = AccountsPayable.query.one()

        loaded = _lines_the_edit_page_loads(client, ap)[0]
        assert loaded.get('source_rr_item_id') == rr.line_items[0].id
        assert loaded.get('source_po_item_id') == po.line_items[0].id
        assert loaded.get('matched_unit_price') == 10.0
        assert loaded.get('matched_quantity') == 60.0

    def test_a_line_added_in_the_edit_form_saves_unlinked(
            self, client, db_session, admin_user, main_branch, two_vendors_and_account):
        """CONTROL. A line typed in by hand on the edit form has no source; it must not
        borrow one, and the billed line beside it must keep its own."""
        rotopack, _johnson, expense = two_vendors_and_account
        _login(client, admin_user, main_branch)
        po = _po(db_session, main_branch, rotopack)
        rr = _rr(db_session, main_branch, po, received=60)
        rr_item_id = rr.line_items[0].id
        client.post('/accounts-payable/create', data=_form_data(
            rotopack, expense, source_rr_ids=json.dumps([rr.id]),
            line_items=json.dumps([_billed_line(expense, rr_item_id=rr_item_id)])),
            follow_redirects=True)
        ap = AccountsPayable.query.one()

        posted = _as_the_browser_posts(_lines_the_edit_page_loads(client, ap))
        posted += _as_the_browser_posts([{'description': 'Freight', 'amount': 150.0,
                                          'account_id': expense.id}])
        _edit(client, ap, rotopack, expense, line_items=json.dumps(posted))

        db.session.expire_all()
        lines = sorted(db.session.get(AccountsPayable, ap.id).line_items,
                       key=lambda l: l.line_number)
        assert len(lines) == 2, 'setup failed: the edit did not save the added line'
        assert lines[0].source_rr_item_id == rr_item_id
        assert (lines[1].source_po_item_id, lines[1].source_rr_item_id) == (None, None)
        assert (lines[1].matched_unit_price, lines[1].matched_quantity) == (None, None)

    def test_the_form_still_posts_the_source_ids_back(self):
        """Keeps _as_the_browser_posts honest: if the submit handler stops sending the
        ids, the round-trip tests above would be testing a form that no longer exists."""
        text = FORM_HTML.read_text(encoding='utf-8')
        start = text.index("getElementById('billForm').addEventListener('submit'")
        handler = text[start:text.index('});', start)]
        assert 'source_po_item_id: item.source_po_item_id || null' in handler
        assert 'source_rr_item_id: item.source_rr_item_id || null' in handler
