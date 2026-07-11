from decimal import Decimal
from datetime import date
import pytest
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_invoices.views import _post_invoice_je
from tests.conftest import assign_control_accounts


def _acct(db_session, code, name, atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Asset', normal_balance=nb)
    db_session.add(a); db_session.commit()
    return a


def _make_invoice(db_session, main_branch, revenue_id, wht=Decimal('0.00')):
    customer = Customer(code='SICA1', name='Cust', is_active=True)
    db_session.add(customer); db_session.commit()
    inv = SalesInvoice(
        branch_id=main_branch.id, invoice_number='SI-CA-1',
        invoice_date=date(2026, 2, 15), due_date=date(2026, 3, 17),
        customer_id=customer.id, customer_name='Cust', status='draft',
        withholding_tax_amount=wht,
    )
    inv.line_items.append(SalesInvoiceItem(
        line_number=1, description='svc', amount=Decimal('11200.00'),
        vat_rate=Decimal('0.00'), vat_category='V0', vat_nature='regular',
        line_total=Decimal('11200.00'), vat_amount=Decimal('0.00'),
        account_id=revenue_id))
    inv.subtotal = Decimal('11200.00'); inv.vat_amount = Decimal('0.00')
    inv.total_amount = Decimal('11200.00') - wht
    db_session.add(inv); db_session.flush()
    return inv


class TestSIControlAccounts:
    def test_posts_on_nonlegacy_coa(self, db_session, admin_user, main_branch):
        # Non-legacy 4-digit chart: AR = 1210 (not 10201)
        ar = _acct(db_session, '1210', 'AR - Trade')
        rev = _acct(db_session, '4001', 'Sales', 'Income', 'Credit')
        assign_control_accounts(db_session, ar='1210')  # only AR needed here
        inv = _make_invoice(db_session, main_branch, rev.id)
        je = _post_invoice_je(inv, admin_user.id)
        db_session.commit()
        ar_leg = next(l for l in je.lines if l.account_id == ar.id)
        # AR leg ties to the document header total (posted-je-leg-vs-source-header)
        assert ar_leg.debit_amount == inv.total_amount

    def test_unassigned_ar_blocks_with_friendly_error(self, db_session, admin_user, main_branch):
        rev = _acct(db_session, '4001', 'Sales', 'Income', 'Credit')
        inv = _make_invoice(db_session, main_branch, rev.id)
        from app.posting.control_accounts import ControlAccountError
        with pytest.raises(ControlAccountError) as exc:
            _post_invoice_je(inv, admin_user.id)
        assert 'Accounts Receivable control account' in str(exc.value)
