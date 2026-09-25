"""A receipt against a PO that was BILLED FIRST can be approved, and is billed by that bill.

Live case, 2026-09-25: RR 00740 (ROTOPACK, PO 01134) was returned to draft on 21 Sep; on
22 Sep APV 00019 billed PO 01134 directly, which closes a PO (purchase_billing
._bill_purchase_sources). Approving the RR then said "01134 is closed and can no longer be
received against". Owner: "Approving the RR at this stage should be allowed."

Rules pinned here:
  * A PO closed BECAUSE A BILL IS LINKED to it (accounts_payable_id set) is receivable, up
    to its open quantity. A PO closed or cancelled any other way is not.
  * Approving such a receipt marks it BILLED to that same bill -- otherwise the approved
    RR would be offered for billing and the goods billed twice.
  * A receipt mixing a billed-first PO with an unbilled one (or with two different bills)
    is refused with a message: guessing either way risks a double or a missing bill.
  * No-PO lines on an auto-billed receipt ride along as billed, and the notice says so.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable
from app.purchase_billing import billable_rrs_for
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_receiving_reports_lifecycle import (_approved_po, _login,  # noqa: F401
                                                                rr_enabled)

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _bill(db_session, branch, vendor, number):
    today = date(2026, 9, 22)
    ap = AccountsPayable(ap_number=number, ap_date=today, due_date=today + timedelta(days=30),
                         payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, vendor_tin='', vendor_address='',
                         branch_id=branch.id, status='posted', subtotal=Decimal('100'),
                         vat_amount=Decimal('0'), total_before_wt=Decimal('100'),
                         withholding_tax_rate=Decimal('0'), withholding_tax_amount=Decimal('0'),
                         total_amount=Decimal('100'), amount_paid=Decimal('0'),
                         balance=Decimal('100'), payment_terms='Net 30')
    db_session.add(ap); db_session.commit()
    return ap


def _billed_first_po(db_session, branch, vendor, number, ap, qty=100):
    """What _bill_purchase_sources leaves behind when a PO is billed directly."""
    po = _approved_po(db_session, branch, vendor, qty=qty, number=number)
    po.status = 'closed'
    po.accounts_payable_id = ap.id
    db_session.commit()
    return po


def _rr(db_session, branch, vendor, lines, number='RR-BF-001'):
    """lines: [(po, qty)] for PO lines, or [(None, qty)] for a no-PO line."""
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 9, 21),
                         vendor_id=vendor.id, vendor_name=vendor.name, status='draft')
    for n, (po, qty) in enumerate(lines, start=1):
        if po is None:
            rr.line_items.append(ReceivingReportItem(line_number=n, received_quantity=Decimal(str(qty)),
                                                     no_po_reason='OVER RUNS'))
        else:
            rr.line_items.append(ReceivingReportItem(line_number=n,
                                                     purchase_order_item_id=po.line_items[0].id,
                                                     received_quantity=Decimal(str(qty))))
    db_session.add(rr); db_session.commit()
    return rr


def _approve(client, rr):
    return client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)


class TestApprovingAgainstABilledFirstPO:

    def test_it_is_approved_and_billed_to_that_bill(self, client, accountant_user, main_branch,
                                                    vl_vendor, db_session):
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-19')
        po = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-1134', ap)
        rr = _rr(db_session, main_branch, vl_vendor, [(po, 100)])
        _login(client, accountant_user, main_branch)

        resp = _approve(client, rr)

        db_session.refresh(rr)
        assert rr.status == 'billed', resp.data.decode()[:0] or rr.status
        assert rr.accounts_payable_id == ap.id
        assert rr.approved_by_id == accountant_user.id
        assert b'AP-BF-19' in resp.data, 'the notice must name the bill'
        db_session.refresh(po)
        assert (po.status, po.accounts_payable_id) == ('closed', ap.id), 'the PO is left as billed'

    def test_it_is_not_offered_for_billing_again(self, client, accountant_user, main_branch,
                                                 vl_vendor, db_session):
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-20')
        po = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-2', ap)
        rr = _rr(db_session, main_branch, vl_vendor, [(po, 40)])
        _login(client, accountant_user, main_branch)
        _approve(client, rr)
        assert rr.id not in [r['id'] for r in billable_rrs_for(main_branch.id, vl_vendor.id)]

    def test_the_open_quantity_still_caps_it(self, client, accountant_user, main_branch,
                                             vl_vendor, db_session):
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-21')
        po = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-3', ap, qty=100)
        rr = _rr(db_session, main_branch, vl_vendor, [(po, 150)])
        _login(client, accountant_user, main_branch)
        resp = _approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'draft'
        assert b'remain open' in resp.data

    def test_no_po_lines_ride_along_and_the_notice_says_so(self, client, accountant_user,
                                                           main_branch, vl_vendor, db_session):
        """RR 00740's shape: 40,000 against the PO plus a 12,100 overrun with no PO."""
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-22')
        po = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-4', ap, qty=40000)
        rr = _rr(db_session, main_branch, vl_vendor, [(po, 40000), (None, 12100)])
        _login(client, accountant_user, main_branch)
        resp = _approve(client, rr)
        db_session.refresh(rr)
        assert (rr.status, rr.accounts_payable_id) == ('billed', ap.id)
        assert b'no-PO line' in resp.data


class TestWhatIsStillRefused:

    def test_a_cancelled_po(self, client, accountant_user, main_branch, vl_vendor, db_session):
        po = _approved_po(db_session, main_branch, vl_vendor, number='PO-BF-CXL')
        po.status = 'cancelled'; db_session.commit()
        rr = _rr(db_session, main_branch, vl_vendor, [(po, 10)])
        _login(client, accountant_user, main_branch)
        resp = _approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'draft' and b'can no longer be received against' in resp.data

    def test_a_closed_po_with_no_bill(self, client, accountant_user, main_branch, vl_vendor,
                                      db_session):
        """Closed WITHOUT a linked bill is not 'billed first' -- still refused."""
        po = _approved_po(db_session, main_branch, vl_vendor, number='PO-BF-CLS')
        po.status = 'closed'; db_session.commit()
        rr = _rr(db_session, main_branch, vl_vendor, [(po, 10)])
        _login(client, accountant_user, main_branch)
        resp = _approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'draft' and b'can no longer be received against' in resp.data

    def test_mixing_a_billed_first_po_with_an_unbilled_one(self, client, accountant_user,
                                                           main_branch, vl_vendor, db_session):
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-23')
        billed = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-MIX1', ap)
        open_po = _approved_po(db_session, main_branch, vl_vendor, number='PO-BF-MIX2')
        rr = _rr(db_session, main_branch, vl_vendor, [(billed, 10), (open_po, 10)])
        _login(client, accountant_user, main_branch)
        resp = _approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'draft'
        assert b'separate' in resp.data and b'PO-BF-MIX1' in resp.data

    def test_two_billed_first_pos_with_different_bills(self, client, accountant_user,
                                                       main_branch, vl_vendor, db_session):
        a = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-TWO1',
                             _bill(db_session, main_branch, vl_vendor, 'AP-BF-24'))
        b = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-TWO2',
                             _bill(db_session, main_branch, vl_vendor, 'AP-BF-25'))
        rr = _rr(db_session, main_branch, vl_vendor, [(a, 10), (b, 10)])
        _login(client, accountant_user, main_branch)
        resp = _approve(client, rr)
        db_session.refresh(rr)
        assert rr.status == 'draft' and b'separate' in resp.data


class TestThePickerAndButtonAgree:

    def test_the_rr_picker_offers_a_billed_first_po(self, client, accountant_user, main_branch,
                                                    vl_vendor, db_session):
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-26')
        po = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-PICK', ap)
        _login(client, accountant_user, main_branch)
        lines = client.get(f'/receiving-reports/open-lines?vendor_id={vl_vendor.id}').get_json()['lines']
        assert po.id in [ln['po_id'] for ln in lines]

    def test_the_po_shows_the_receive_button(self, client, accountant_user, main_branch,
                                             vl_vendor, db_session):
        ap = _bill(db_session, main_branch, vl_vendor, 'AP-BF-27')
        po = _billed_first_po(db_session, main_branch, vl_vendor, 'PO-BF-BTN', ap)
        _login(client, accountant_user, main_branch)
        body = client.get(f'/purchase-orders/{po.id}').get_data(as_text=True)
        assert f'/receiving-reports/create?po_id={po.id}' in body
