"""Page-level document-chain resolvers for the Job Order Slips page (SO -> DR -> SI).

The Purchase Requests list answers "where have the goods got to?" with one query per
document type for the whole page (app/purchase_requests/allocation.py). These are the
sell-side twins. Rules under test, from docs/design/2026-09-12-job-order-chain-columns-design.md:

- a Delivery Receipt counts only when committed (a draft has delivered nothing);
- a Sales Invoice counts by the DR->SI link alone (cleared on void by _unbill_drs);
- one document feeding two lines/DRs/SIs of the same order shows ONCE;
- empty or None ids -> {}.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db

pytestmark = [pytest.mark.unit, pytest.mark.sales_orders]


def _so(branch, number='SO-CH-1'):
    from app.customers.models import Customer
    from app.sales_orders.models import SalesOrder
    cust = Customer.query.filter_by(code='CHN').first()
    if cust is None:
        cust = Customer(code='CHN', name='Chain Co', is_active=True)
        db.session.add(cust); db.session.commit()
    so = SalesOrder(so_number=number, order_date=date(2026, 9, 1), customer_id=cust.id,
                    customer_name=cust.name, branch_id=branch.id, status='confirmed')
    db.session.add(so); db.session.commit()
    return so


def _dr(so, number, status='delivered', invoice=None):
    from app.delivery_receipts.models import DeliveryReceipt
    dr = DeliveryReceipt(dr_number=number, delivery_date=date(2026, 9, 2), sales_order_id=so.id,
                         customer_id=so.customer_id, customer_name=so.customer_name,
                         branch_id=so.branch_id, status=status,
                         sales_invoice_id=invoice.id if invoice else None)
    db.session.add(dr); db.session.commit()
    return dr


def _si(so, number, status='posted'):
    from app.sales_invoices.models import SalesInvoice
    si = SalesInvoice(invoice_number=number, invoice_date=date(2026, 9, 3), due_date=date(2026, 10, 3),
                      customer_id=so.customer_id, customer_name=so.customer_name,
                      branch_id=so.branch_id, status=status, total_amount=Decimal('1120'))
    db.session.add(si); db.session.commit()
    return si


class TestDrLinks:

    def test_committed_dr_listed_draft_dr_not(self, db_session, main_branch):
        from app.sales_orders.chain_links import dr_links_for_so_ids
        so = _so(main_branch)
        _dr(so, '00002', status='delivered')
        _dr(so, '00001', status='draft')
        _dr(so, '00003', status='approved')
        links = dr_links_for_so_ids([so.id])
        assert [n for _id, n in links[so.id]] == ['00002', '00003']

    def test_no_dr_means_no_key(self, db_session, main_branch):
        from app.sales_orders.chain_links import dr_links_for_so_ids
        so = _so(main_branch)
        assert dr_links_for_so_ids([so.id]) == {}

    def test_empty_and_none_ids(self, db_session, main_branch):
        from app.sales_orders.chain_links import dr_links_for_so_ids
        assert dr_links_for_so_ids([]) == {}
        assert dr_links_for_so_ids(None) == {}
        assert dr_links_for_so_ids([None]) == {}


class TestSiLinks:

    def test_si_listed_once_dr_is_billed(self, db_session, main_branch):
        from app.sales_orders.chain_links import si_links_for_so_ids
        so = _so(main_branch)
        si = _si(so, 'SI-0001')
        _dr(so, '00001', status='billed', invoice=si)
        assert si_links_for_so_ids([so.id]) == {so.id: [(si.id, 'SI-0001')]}

    def test_unbilled_dr_has_no_si(self, db_session, main_branch):
        from app.sales_orders.chain_links import si_links_for_so_ids
        so = _so(main_branch)
        _dr(so, '00001', status='delivered')
        assert si_links_for_so_ids([so.id]) == {}

    def test_one_si_over_two_drs_listed_once(self, db_session, main_branch):
        from app.sales_orders.chain_links import si_links_for_so_ids
        so = _so(main_branch)
        si = _si(so, 'SI-0001')
        _dr(so, '00001', status='billed', invoice=si)
        _dr(so, '00002', status='billed', invoice=si)
        assert si_links_for_so_ids([so.id]) == {so.id: [(si.id, 'SI-0001')]}

    def test_si_link_gone_after_void_unlinks_dr(self, db_session, main_branch):
        """The app clears delivery_receipts.sales_invoice_id on SI void (_unbill_drs);
        the resolver trusts the link, so a cleared link means no SI."""
        from app.sales_orders.chain_links import si_links_for_so_ids
        so = _so(main_branch)
        si = _si(so, 'SI-0001')
        dr = _dr(so, '00001', status='billed', invoice=si)
        dr.sales_invoice_id = None; dr.status = 'delivered'
        si.status = 'voided'
        db.session.commit()
        assert si_links_for_so_ids([so.id]) == {}
