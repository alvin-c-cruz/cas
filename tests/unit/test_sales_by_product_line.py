"""Unit tests for the Sales by Product Line generator."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem
from app.reports.product_line import generate_sales_by_product_line

D = lambda v: Decimal(str(v))


def _customer():
    c = Customer(code='C1', name='Acme')
    db.session.add(c)
    db.session.flush()
    return c


def _category(code, name):
    cat = ProductCategory(code=code, name=name, is_active=True)
    db.session.add(cat)
    db.session.flush()
    return cat


def _product(code, category=None):
    p = Product(code=code, name=code, category_id=(category.id if category else None))
    db.session.add(p)
    db.session.flush()
    return p


def _invoice(customer, when, branch_id=None, status='posted', number='SI-1'):
    inv = SalesInvoice(invoice_number=number, invoice_date=when, due_date=when,
                       customer_id=customer.id, customer_name=customer.name,
                       branch_id=branch_id, status=status)
    db.session.add(inv)
    db.session.flush()
    return inv


def _si_line(inv, product, line_total, vat_amount, n=1):
    li = SalesInvoiceItem(invoice_id=inv.id, line_number=n, description='x',
                          product_id=(product.id if product else None),
                          line_total=D(line_total), vat_amount=D(vat_amount))
    db.session.add(li)
    db.session.flush()
    return li


def _memo(inv, si_line, customer, when, memo_type, product, line_total, vat_amount,
          branch_id=None, status='posted', number='CM-1'):
    m = SalesMemo(memo_type=memo_type, memo_number=number, memo_date=when,
                  sales_invoice_id=inv.id, original_invoice_number=inv.invoice_number,
                  customer_id=customer.id, customer_name=customer.name,
                  reason='return', status=status, branch_id=branch_id)
    db.session.add(m)
    db.session.flush()
    mi = SalesMemoItem(sales_memo_id=m.id, line_number=1,
                       sales_invoice_item_id=si_line.id,
                       product_id=(product.id if product else None),
                       line_total=D(line_total), vat_amount=D(vat_amount))
    db.session.add(mi)
    db.session.flush()
    return m


@pytest.mark.unit
class TestSalesByProductLine:
    def test_single_category_net_of_vat(self, db_session):
        cust = _customer()
        bev = _category('BEV', 'Beverages')
        cola = _product('COLA', bev)
        inv = _invoice(cust, date(2026, 5, 10))
        _si_line(inv, cola, line_total=112, vat_amount=12)   # net 100
        out = generate_sales_by_product_line(date(2026, 5, 1), date(2026, 5, 31))
        assert out['rows'] == [{'category_id': bev.id, 'code': 'BEV',
                                'name': 'Beverages', 'net': 100.0}]
        assert out['unassigned'] == 0.0
        assert out['total'] == 100.0

    def test_multi_category_and_percent_source(self, db_session):
        cust = _customer()
        bev = _category('BEV', 'Beverages')
        snk = _category('SNK', 'Snacks')
        inv = _invoice(cust, date(2026, 5, 10))
        _si_line(inv, _product('COLA', bev), 112, 12, n=1)   # 100
        _si_line(inv, _product('CHIP', snk), 56, 6, n=2)     # 50
        out = generate_sales_by_product_line(date(2026, 5, 1), date(2026, 5, 31))
        totals = {r['code']: r['net'] for r in out['rows']}
        assert totals == {'BEV': 100.0, 'SNK': 50.0}
        assert out['total'] == 150.0

    def test_credit_memo_reduces_and_debit_adds(self, db_session):
        cust = _customer()
        bev = _category('BEV', 'Beverages')
        cola = _product('COLA', bev)
        inv = _invoice(cust, date(2026, 5, 10))
        line = _si_line(inv, cola, 112, 12)                  # +100
        _memo(inv, line, cust, date(2026, 5, 12), 'credit', cola, 22.4, 2.4, number='CM-1')  # -20
        _memo(inv, line, cust, date(2026, 5, 15), 'debit', cola, 11.2, 1.2, number='DM-1')   # +10
        out = generate_sales_by_product_line(date(2026, 5, 1), date(2026, 5, 31))
        assert {r['code']: r['net'] for r in out['rows']} == {'BEV': 90.0}

    def test_untagged_product_and_no_product_go_unassigned(self, db_session):
        cust = _customer()
        inv = _invoice(cust, date(2026, 5, 10))
        _si_line(inv, _product('NOCAT', None), 112, 12, n=1)  # product, no category
        _si_line(inv, None, 56, 6, n=2)                       # no product at all
        out = generate_sales_by_product_line(date(2026, 5, 1), date(2026, 5, 31))
        assert out['rows'] == []
        assert out['unassigned'] == 150.0
        assert out['total'] == 150.0

    def test_only_posted_and_date_and_branch_filters(self, db_session):
        cust = _customer()
        bev = _category('BEV', 'Beverages')
        cola = _product('COLA', bev)
        # draft, branch 1, in-range date — excluded ONLY by the status filter
        _si_line(_invoice(cust, date(2026, 5, 10), branch_id=1, status='draft', number='D1'), cola, 112, 12)
        # posted, branch 1, out-of-range date — excluded ONLY by the date filter
        _si_line(_invoice(cust, date(2026, 4, 10), branch_id=1, number='O1'), cola, 112, 12)
        # posted, in-range date, other branch — excluded ONLY by the branch filter
        _si_line(_invoice(cust, date(2026, 5, 10), branch_id=2, number='B2'), cola, 112, 12)
        # in scope, branch 1
        _si_line(_invoice(cust, date(2026, 5, 10), branch_id=1, number='OK'), cola, 112, 12)
        out = generate_sales_by_product_line(date(2026, 5, 1), date(2026, 5, 31), branch_id=1)
        assert out['total'] == 100.0

    def test_memo_status_and_date_filters(self, db_session):
        cust = _customer()
        bev = _category('BEV', 'Beverages')
        cola = _product('COLA', bev)
        inv = _invoice(cust, date(2026, 5, 10), branch_id=1, number='SI-1')
        line = _si_line(inv, cola, 112, 12)  # +100
        # posted, in-range credit memo, branch 1 — included (-20)
        _memo(inv, line, cust, date(2026, 5, 12), 'credit', cola, 22.4, 2.4,
              branch_id=1, status='posted', number='CM-OK')
        # draft credit memo, branch 1, in-range date — excluded ONLY by the status filter
        _memo(inv, line, cust, date(2026, 5, 13), 'credit', cola, 33.6, 3.6,
              branch_id=1, status='draft', number='CM-DRAFT')
        # posted credit memo, branch 1, out-of-range date — excluded ONLY by the date filter
        _memo(inv, line, cust, date(2026, 4, 15), 'credit', cola, 44.8, 4.8,
              branch_id=1, status='posted', number='CM-OOR')
        out = generate_sales_by_product_line(date(2026, 5, 1), date(2026, 5, 31), branch_id=1)
        assert out['total'] == 80.0
