"""A purchase order's status says how it finished (GCD-5).

Owner, 13 Nov 2026: "it should show Paid if closed by CV, and Received if closed by RR"; letters
"GCD-5.1 A, 5.2 B, 5.3 A, 5.4 A". The label is derived on every read from the PO's committed
receipts (approved or billed RRs); the stored status and every status rule are unchanged.

First match wins:
  1 draft / cancelled -> as stored         2 stored closed (APV billed the PO itself) -> Closed
  3 no committed receipt -> as stored       4 some received, not fully -> Partly received
  5 fully received, every receipt settled by a CDV -> Paid
  6 fully received, every receipt finished, some by APV and some by CDV -> Closed
  7 fully received, anything else (all by APV, or one not yet billed or paid) -> Received
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.purchase_orders.progress import progress_key, progress_keys, receipts_for
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_receiving_reports_lifecycle import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


# ------------------------------------------------------------------- builders

def _po(db_session, branch, vendor, qtys=(5,), number='01115', status='approved'):
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 5, 4),
                       vendor_id=vendor.id, vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive')
    for i, q in enumerate(qtys, start=1):
        po.line_items.append(PurchaseOrderItem(line_number=i, description=f'Line {i}',
                                               quantity=Decimal(str(q)), unit_price=Decimal('10'),
                                               amount=Decimal(str(q * 10))))
    po.calculate_totals()
    db_session.add(po)
    db_session.commit()
    return po


def _rr(db_session, branch, vendor, lines, number='00685', status='approved'):
    """*lines*: [(po_item, qty), ...] -- one receipt may draw on several orders."""
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 29),
                         vendor_id=vendor.id, vendor_name=vendor.name, status=status)
    for i, (item, qty) in enumerate(lines, start=1):
        rr.line_items.append(ReceivingReportItem(line_number=i, purchase_order_item_id=item.id,
                                                 received_quantity=Decimal(str(qty))))
    db_session.add(rr)
    db_session.commit()
    return rr


def _cdv(db_session, branch, vendor, cash_account, number='1197E'):
    cdv = CashDisbursementVoucher(branch_id=branch.id, cdv_number=number,
                                  cdv_date=date(2026, 6, 19), payee_type='vendor',
                                  payee_id=vendor.id, vendor_id=vendor.id,
                                  vendor_name=vendor.name, cash_account_id=cash_account.id,
                                  status='posted')
    db_session.add(cdv)
    db_session.commit()
    return cdv


def _ap(db_session, branch, vendor, number='00031'):
    ap = AccountsPayable(ap_number=number, ap_date=date(2026, 8, 1), due_date=date(2026, 8, 31),
                         vendor_id=vendor.id, vendor_name=vendor.name, branch_id=branch.id,
                         status='posted')
    db_session.add(ap)
    db_session.commit()
    return ap


def _text(body):
    """The page as a reader sees it: tags gone, whitespace collapsed."""
    return ' '.join(re.sub(r'<[^>]+>', ' ', body).split())


def _paid_by_cdv(db_session, rr, cdv):
    rr.status, rr.settled_cdv_id = 'billed', cdv.id
    db_session.commit()


def _billed_by_ap(db_session, rr, ap):
    rr.status, rr.accounts_payable_id = 'billed', ap.id
    db_session.commit()


# ------------------------------------------------------------------- the rule table

class TestTheLabel:

    @pytest.mark.parametrize('stored', ['draft', 'cancelled'])
    def test_rule_1_draft_and_cancelled_read_as_stored(self, stored, db_session, main_branch,
                                                       vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, status=stored)
        assert progress_key(po) == stored

    def test_rule_2_a_po_billed_by_apv_itself_reads_closed(self, db_session, main_branch,
                                                           vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, status='closed')
        assert progress_key(po) == 'closed'

    @pytest.mark.parametrize('stored', ['submitted', 'approved'])
    def test_rule_3_nothing_received_reads_as_stored(self, stored, db_session, main_branch,
                                                     vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, status=stored)
        assert progress_key(po) == stored

    @pytest.mark.parametrize('rr_status', ['draft', 'submitted', 'cancelled'])
    def test_rule_3_a_receipt_not_yet_approved_does_not_count(self, rr_status, db_session,
                                                               main_branch, vl_vendor):
        po = _po(db_session, main_branch, vl_vendor)
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)], status=rr_status)
        assert progress_key(po) == 'approved'

    def test_rule_4_some_received_reads_partly_received(self, db_session, main_branch, vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)])
        assert progress_key(po) == 'partly_received'

    def test_rule_4_one_line_open_is_still_partly_received(self, db_session, main_branch,
                                                           vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5, 2))
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        assert progress_key(po) == 'partly_received'

    def test_rule_4_wins_even_when_the_receipt_is_paid(self, db_session, main_branch, vl_vendor,
                                                       cash_account):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)])
        _paid_by_cdv(db_session, rr, _cdv(db_session, main_branch, vl_vendor, cash_account))
        assert progress_key(po) == 'partly_received'

    def test_a_submitted_po_can_be_received_too(self, db_session, main_branch, vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, status='submitted')
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        assert progress_key(po) == 'received'

    def test_rule_5_every_receipt_paid_by_cdv_reads_paid(self, db_session, main_branch, vl_vendor,
                                                         cash_account):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        _paid_by_cdv(db_session, rr, _cdv(db_session, main_branch, vl_vendor, cash_account))
        assert progress_key(po) == 'paid'

    def test_rule_5_two_receipts_both_paid_by_cdv(self, db_session, main_branch, vl_vendor,
                                                  cash_account):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        a = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 2)], number='00701')
        b = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)], number='00702')
        _paid_by_cdv(db_session, a, _cdv(db_session, main_branch, vl_vendor, cash_account, '1801'))
        _paid_by_cdv(db_session, b, _cdv(db_session, main_branch, vl_vendor, cash_account, '1802'))
        assert progress_key(po) == 'paid'

    def test_rule_6_finished_by_apv_and_cdv_reads_closed(self, db_session, main_branch, vl_vendor,
                                                         cash_account):
        """5.3 A: Closed once all are billed or paid; Paid only when all are by CDV."""
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        a = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 2)], number='00701')
        b = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)], number='00702')
        _paid_by_cdv(db_session, a, _cdv(db_session, main_branch, vl_vendor, cash_account))
        _billed_by_ap(db_session, b, _ap(db_session, main_branch, vl_vendor))
        assert progress_key(po) == 'closed'

    def test_rule_7_fully_received_and_unbilled_reads_received(self, db_session, main_branch,
                                                               vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        assert progress_key(po) == 'received'

    def test_rule_7_every_receipt_billed_by_apv_reads_received(self, db_session, main_branch,
                                                               vl_vendor):
        """5.2 B: a goods PO billed wholly through AP reads Received, not Closed."""
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        _billed_by_ap(db_session, rr, _ap(db_session, main_branch, vl_vendor))
        assert progress_key(po) == 'received'

    def test_rule_7_one_paid_one_not_yet_billed_reads_received(self, db_session, main_branch,
                                                               vl_vendor, cash_account):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        a = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 2)], number='00701')
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)], number='00702')
        _paid_by_cdv(db_session, a, _cdv(db_session, main_branch, vl_vendor, cash_account))
        assert progress_key(po) == 'received'

    def test_over_receipt_still_counts_as_fully_received(self, db_session, main_branch,
                                                         vl_vendor):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 6)])
        assert progress_key(po) == 'received'

    def test_one_receipt_paying_two_orders_makes_both_paid(self, db_session, main_branch,
                                                           vl_vendor, cash_account):
        a = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='01115')
        b = _po(db_session, main_branch, vl_vendor, qtys=(2,), number='01116')
        rr = _rr(db_session, main_branch, vl_vendor, [(a.line_items[0], 5), (b.line_items[0], 2)])
        _paid_by_cdv(db_session, rr, _cdv(db_session, main_branch, vl_vendor, cash_account))
        assert (progress_key(a), progress_key(b)) == ('paid', 'paid')

    def test_the_stored_status_is_never_written(self, db_session, main_branch, vl_vendor,
                                                cash_account):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        _paid_by_cdv(db_session, rr, _cdv(db_session, main_branch, vl_vendor, cash_account))
        progress_key(po)
        progress_keys([po])
        db_session.expire_all()
        assert db_session.get(PurchaseOrder, po.id).status == 'approved'

    def test_the_bulk_reading_agrees_with_one_at_a_time(self, db_session, main_branch, vl_vendor,
                                                        cash_account):
        pos = [_po(db_session, main_branch, vl_vendor, status='draft', number='A1'),
               _po(db_session, main_branch, vl_vendor, status='closed', number='A2'),
               _po(db_session, main_branch, vl_vendor, number='A3'),
               _po(db_session, main_branch, vl_vendor, qtys=(5,), number='A4'),
               _po(db_session, main_branch, vl_vendor, qtys=(5,), number='A5'),
               _po(db_session, main_branch, vl_vendor, qtys=(5,), number='A6')]
        _rr(db_session, main_branch, vl_vendor, [(pos[3].line_items[0], 1)], number='R4')
        _rr(db_session, main_branch, vl_vendor, [(pos[4].line_items[0], 5)], number='R5')
        r6 = _rr(db_session, main_branch, vl_vendor, [(pos[5].line_items[0], 5)], number='R6')
        _paid_by_cdv(db_session, r6, _cdv(db_session, main_branch, vl_vendor, cash_account))

        bulk = progress_keys(pos)

        assert bulk == {po.id: progress_key(po) for po in pos}
        assert [bulk[po.id] for po in pos] == ['draft', 'closed', 'approved', 'partly_received',
                                               'received', 'paid']


class TestReceiptsFor:

    def test_each_committed_receipt_says_how_it_finished(self, db_session, main_branch, vl_vendor,
                                                         cash_account):
        po = _po(db_session, main_branch, vl_vendor, qtys=(9,))
        a = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 2)], number='00701')
        b = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)], number='00702')
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 4)], number='00703')
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 1)], number='00704',
            status='submitted')
        _paid_by_cdv(db_session, a, _cdv(db_session, main_branch, vl_vendor, cash_account))
        _billed_by_ap(db_session, b, _ap(db_session, main_branch, vl_vendor))

        rows = [(r['rr'].rr_number, r['finished_by'], r['document']) for r in receipts_for(po)]

        assert rows == [('00701', 'cdv', '1197E'), ('00702', 'apv', '00031'),
                        ('00703', None, None)]


# ------------------------------------------------------------------- the screens

class TestScreens:

    def test_the_detail_page_shows_paid_and_the_receipt_that_paid(
            self, client, accountant_user, main_branch, vl_vendor, cash_account, db_session):
        """GET-render check: the label and the receipt line are on the page itself."""
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        _paid_by_cdv(db_session, rr, _cdv(db_session, main_branch, vl_vendor, cash_account))
        _login(client, accountant_user, main_branch)

        body = client.get(f'/purchase-orders/{po.id}').data.decode('utf-8')

        assert 'data-po-progress="paid"' in body
        assert '>Paid<' in body
        assert 'RR 00685' in _text(body) and 'paid by CDV 1197E' in _text(body)

    def test_the_detail_page_names_an_apv_and_an_unbilled_receipt(
            self, client, accountant_user, main_branch, vl_vendor, db_session):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,))
        a = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 2)], number='00701')
        _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 3)], number='00702')
        _billed_by_ap(db_session, a, _ap(db_session, main_branch, vl_vendor))
        _login(client, accountant_user, main_branch)

        body = client.get(f'/purchase-orders/{po.id}').data.decode('utf-8')

        assert 'data-po-progress="received"' in body
        assert 'billed by APV 00031' in _text(body)
        assert 'not yet billed' in _text(body)

    def test_no_receipts_card_when_nothing_was_received(
            self, client, accountant_user, main_branch, vl_vendor, db_session):
        po = _po(db_session, main_branch, vl_vendor)
        _login(client, accountant_user, main_branch)

        body = client.get(f'/purchase-orders/{po.id}').data.decode('utf-8')

        assert 'data-po-progress="approved"' in body
        assert 'data-po-receipts' not in body

    def test_the_list_shows_each_label(self, client, accountant_user, main_branch, vl_vendor,
                                       cash_account, db_session):
        paid = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-PAID')
        received = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-RECV')
        partly = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-PART')
        r1 = _rr(db_session, main_branch, vl_vendor, [(paid.line_items[0], 5)], number='R1')
        _rr(db_session, main_branch, vl_vendor, [(received.line_items[0], 5)], number='R2')
        _rr(db_session, main_branch, vl_vendor, [(partly.line_items[0], 1)], number='R3')
        _paid_by_cdv(db_session, r1, _cdv(db_session, main_branch, vl_vendor, cash_account))
        _login(client, accountant_user, main_branch)

        body = client.get('/purchase-orders').data.decode('utf-8')

        for po, key in ((paid, 'paid'), (received, 'received'), (partly, 'partly_received')):
            assert f'data-po-id="{po.id}" data-po-progress="{key}"' in body
        assert '>Paid<' in body and '>Received<' in body and '>Partly received<' in body

    def test_the_status_filter_offers_and_applies_the_labels(
            self, client, accountant_user, main_branch, vl_vendor, cash_account, db_session):
        paid = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-PAID')
        received = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-RECV')
        idle = _po(db_session, main_branch, vl_vendor, number='PO-IDLE')
        r1 = _rr(db_session, main_branch, vl_vendor, [(paid.line_items[0], 5)], number='R1')
        _rr(db_session, main_branch, vl_vendor, [(received.line_items[0], 5)], number='R2')
        _paid_by_cdv(db_session, r1, _cdv(db_session, main_branch, vl_vendor, cash_account))
        _login(client, accountant_user, main_branch)

        page = client.get('/purchase-orders').data.decode('utf-8')
        for value in ('submitted', 'partly_received', 'received', 'paid'):
            assert f'<option value="{value}"' in page

        def shown(status):
            body = client.get(f'/purchase-orders?status={status}').data.decode('utf-8')
            return {n for n in ('PO-PAID', 'PO-RECV', 'PO-IDLE') if n in body}

        assert shown('paid') == {'PO-PAID'}
        assert shown('received') == {'PO-RECV'}
        assert shown('approved') == {'PO-IDLE'}
        assert shown('all') == {'PO-PAID', 'PO-RECV', 'PO-IDLE'}
        assert idle  # keeps the builder's PO referenced

    def test_an_old_partially_received_link_still_filters(
            self, client, accountant_user, main_branch, vl_vendor, db_session):
        partly = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-PART')
        _po(db_session, main_branch, vl_vendor, number='PO-IDLE')
        _rr(db_session, main_branch, vl_vendor, [(partly.line_items[0], 1)], number='R3')
        _login(client, accountant_user, main_branch)

        body = client.get('/purchase-orders?status=partially_received').data.decode('utf-8')

        assert 'PO-PART' in body and 'PO-IDLE' not in body

    def test_the_csv_export_carries_the_label(self, client, accountant_user, main_branch,
                                              vl_vendor, cash_account, db_session):
        po = _po(db_session, main_branch, vl_vendor, qtys=(5,), number='PO-PAID')
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 5)])
        _paid_by_cdv(db_session, rr, _cdv(db_session, main_branch, vl_vendor, cash_account))
        _login(client, accountant_user, main_branch)

        body = client.get('/purchase-orders/export/csv?status=paid').data.decode('utf-8')

        row = next(line for line in body.splitlines() if 'PO-PAID' in line)
        assert row.rstrip().endswith('Paid')

    def test_po_01115_reads_paid_once_its_receipt_is_settled_by_the_cdv(
            self, client, admin_user, main_branch, vl_vendor, cash_account, db_session):
        """The owner's case end to end, through the real settle route."""
        po = _po(db_session, main_branch, vl_vendor, qtys=(1,))
        rr = _rr(db_session, main_branch, vl_vendor, [(po.line_items[0], 1)], number='00685-C')
        _cdv(db_session, main_branch, vl_vendor, cash_account)
        _login(client, admin_user, main_branch)
        assert progress_key(po) == 'received'

        resp = client.post(f'/receiving-reports/{rr.id}/settle',
                           data={'cdv_number': '1197E',
                                 'settle_reason': 'Paid ahead by legacy EXTRA CV 1197'},
                           follow_redirects=True)
        assert resp.status_code == 200

        body = client.get(f'/purchase-orders/{po.id}').data.decode('utf-8')
        assert 'data-po-progress="paid"' in body
        assert 'RR 00685-C' in _text(body) and 'paid by CDV 1197E' in _text(body)
