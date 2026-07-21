"""SI print / detail: qty & uom blank on amount-only lines, shown on itemized
lines (Product+UoM Activation / R-01, Task 3).

The additive line UI lets one invoice mix an itemized line (qty x unit_price) with
an amount-only line (free-text + amount, no qty). The print/detail templates must
render the qty/uom for the itemized line and leave them blank (the em-dash
placeholder, never 0.00 / 1) for the amount-only line — which the shared
`qty_fmt(blank)` filter + `uom_text or dash` fallback already do. This locks that.
"""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.settings import AppSettings

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


@pytest.fixture
def modules_on(db_session):
    # units_of_measure only -- NOT products: this test's lines are free-text
    # descriptions (no product_id), matching the description+qty/uom pattern
    # (e.g. a client without a product catalog). Turning products on too would
    # switch the column to Product-name (blank for these lines) instead of
    # Description, hiding the very text these tests assert on.
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _build_mixed_invoice(db_session, branch):
    cust = Customer(code='PPC1', name='Print Customer', is_active=True)
    rev = Account(code='40101', name='Service Revenue', account_type='Income',
                  normal_balance='credit', is_active=True)
    db_session.add_all([cust, rev]); db_session.commit()

    inv = SalesInvoice(
        branch_id=branch.id, invoice_number='SI-PP-0001', invoice_date=date.today(),
        due_date=date.today(), customer_id=cust.id, customer_name=cust.name, notes='',
        status='posted', subtotal=Decimal('5200.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('5200.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('5200.00'), amount_paid=Decimal('0.00'),
        balance=Decimal('5200.00'),
    )
    db_session.add(inv); db_session.flush()

    itemized = SalesInvoiceItem(
        invoice_id=inv.id, line_number=1, description='ITEMIZED-WIDGET',
        quantity=Decimal('2'), unit_price=Decimal('100.00'), uom_text='kg',
        amount=Decimal('200.00'), vat_rate=Decimal('0.00'), account_id=rev.id)
    itemized.calculate_amounts()
    amount_only = SalesInvoiceItem(
        invoice_id=inv.id, line_number=2, description='AMOUNTONLY-ELECTRICITY',
        quantity=None, unit_price=None, uom_text=None,
        amount=Decimal('5000.00'), vat_rate=Decimal('0.00'), account_id=rev.id)
    amount_only.calculate_amounts()
    db_session.add_all([itemized, amount_only]); db_session.commit()
    return inv


def test_si_print_blanks_qty_uom_on_amount_only(client, db_session, accountant_user, main_branch, modules_on):
    inv = _build_mixed_invoice(db_session, main_branch)
    _login(client, accountant_user, main_branch)
    resp = client.get(f'/sales-invoices/{inv.id}/print')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    # Both lines present.
    assert 'ITEMIZED-WIDGET' in html
    assert 'AMOUNTONLY-ELECTRICITY' in html
    # Itemized line shows its qty + uom.
    assert '2.0000' in html
    assert 'kg' in html
    # The amount-only line must NOT introduce a fabricated qty of 0 / 1.
    # (qty_fmt returns the em-dash blank for a None quantity.)
    assert '—' in html  # em-dash placeholder rendered for the amount-only qty/uom


def test_si_detail_blanks_qty_uom_on_amount_only(client, db_session, accountant_user, main_branch, modules_on):
    inv = _build_mixed_invoice(db_session, main_branch)
    _login(client, accountant_user, main_branch)
    resp = client.get(f'/sales-invoices/{inv.id}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert 'ITEMIZED-WIDGET' in html
    assert 'AMOUNTONLY-ELECTRICITY' in html
    assert '2.0000' in html
    assert 'kg' in html
