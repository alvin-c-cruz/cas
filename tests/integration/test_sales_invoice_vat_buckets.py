"""SI output-VAT bucketing, whole-invoice VAT-override allocation, and JE-reversal
content — bringing Sales Invoice integration depth to parity with AP
(test_accounts_payable_vat_buckets). Helper-level, matching the existing SI JE
tests in test_sales_invoices.py. Covers audit gaps 3b (buckets/override) and
3c (reversal mirrors the JE).
"""
from decimal import Decimal
from datetime import date

import pytest

from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_vat_categories.models import SalesVATCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_invoices import views as sv

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def _acct(db_session, code, name, typ, nb):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True)
        db_session.add(a)
        db_session.flush()
    return a


def _vat_cat(db_session, code, output_acct, rate=12):
    c = SalesVATCategory.query.filter_by(code=code).first()
    if not c:
        c = SalesVATCategory(code=code, name=f'VAT {code}', rate=Decimal(str(rate)),
                             transaction_nature='regular',
                             output_vat_account_id=output_acct.id)
        db_session.add(c)
        db_session.flush()
    return c


def _customer(db_session):
    c = Customer.query.filter_by(code='SIB01').first()
    if not c:
        c = Customer(code='SIB01', name='Bucket Customer', is_active=True)
        db_session.add(c)
        db_session.flush()
    return c


def _branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if not b:
        b = Branch(name='Main', code='MB', is_active=True)
        db_session.add(b)
        db_session.flush()
    return b


def _invoice(db_session, customer, branch, number, lines):
    inv = SalesInvoice(branch_id=branch.id, invoice_number=number,
                       invoice_date=date(2026, 6, 14), due_date=date(2026, 7, 14),
                       customer_id=customer.id, customer_name=customer.name,
                       notes='', status='draft', amount_paid=Decimal('0.00'))
    db_session.add(inv)
    db_session.flush()
    for i, ln in enumerate(lines, start=1):
        item = SalesInvoiceItem(
            invoice_id=inv.id, line_number=i, description=ln.get('description', 'Service'),
            amount=Decimal(str(ln['amount'])), vat_category=ln['vat_category'],
            vat_rate=Decimal(str(ln['vat_rate'])), account_id=ln['account_id'],
            wt_id=ln.get('wt_id'), wt_rate=Decimal(str(ln.get('wt_rate', 0))))
        item.calculate_amounts()
        db_session.add(item)
    db_session.flush()
    inv.calculate_totals()
    db_session.flush()
    return inv


def _net_by_code(je):
    """code -> sum(debit - credit) across the JE's lines."""
    out = {}
    for l in je.lines.all():
        out.setdefault(l.account.code, Decimal('0.00'))
        out[l.account.code] += l.debit_amount - l.credit_amount
    return out


# --------------------------------------------------------------------------
# 3b — output-VAT buckets + whole-invoice override allocation
# --------------------------------------------------------------------------

class TestOutputVatBuckets:
    def test_two_categories_two_output_vat_lines(self, db_session, accountant_user):
        customer, branch = _customer(db_session), _branch(db_session)
        _acct(db_session, '10201', 'AR - Trade', 'Asset', 'debit')
        rev = _acct(db_session, '40001', 'Service Revenue', 'Income', 'credit')
        ovg = _acct(db_session, '20201', 'Output VAT - Goods', 'Liability', 'credit')
        ovs = _acct(db_session, '20202', 'Output VAT - Services', 'Liability', 'credit')
        _vat_cat(db_session, 'SVG', ovg)
        _vat_cat(db_session, 'SVS', ovs)
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)

        # 2240 incl @12% -> VAT 240 ; 1120 incl @12% -> VAT 120
        inv = _invoice(db_session, customer, branch, 'SI-BKT-01', [
            {'amount': 2240, 'vat_category': 'SVG', 'vat_rate': 12, 'account_id': rev.id},
            {'amount': 1120, 'vat_category': 'SVS', 'vat_rate': 12, 'account_id': rev.id},
        ])
        je = sv._post_invoice_je(inv, accountant_user.id)
        db_session.flush()

        net = _net_by_code(je)
        # output VAT is credited -> appears negative in (debit - credit)
        assert net['20201'] == Decimal('-240.00')
        assert net['20202'] == Decimal('-120.00')
        assert je.is_balanced

    def test_override_difference_lands_on_largest_bucket(self, db_session, accountant_user):
        customer, branch = _customer(db_session), _branch(db_session)
        rev = _acct(db_session, '40001', 'Service Revenue', 'Income', 'credit')
        ovg = _acct(db_session, '20201', 'Output VAT - Goods', 'Liability', 'credit')
        ovs = _acct(db_session, '20202', 'Output VAT - Services', 'Liability', 'credit')
        _vat_cat(db_session, 'SVG', ovg)
        _vat_cat(db_session, 'SVS', ovs)

        inv = _invoice(db_session, customer, branch, 'SI-BKT-02', [
            {'amount': 2240, 'vat_category': 'SVG', 'vat_rate': 12, 'account_id': rev.id},
            {'amount': 1120, 'vat_category': 'SVS', 'vat_rate': 12, 'account_id': rev.id},
        ])
        # computed VAT 240 + 120 = 360; override the whole-invoice VAT to 361
        inv.vat_amount = Decimal('361.00')
        db_session.flush()

        buckets = {acct.code: amt for acct, amt in sv._output_vat_buckets(inv)}
        assert buckets['20201'] == Decimal('241.00')  # +1 lands on the largest bucket
        assert buckets['20202'] == Decimal('120.00')

    def test_override_far_below_computed_raises(self, db_session, accountant_user):
        customer, branch = _customer(db_session), _branch(db_session)
        rev = _acct(db_session, '40001', 'Service Revenue', 'Income', 'credit')
        ovg = _acct(db_session, '20201', 'Output VAT - Goods', 'Liability', 'credit')
        ovs = _acct(db_session, '20202', 'Output VAT - Services', 'Liability', 'credit')
        _vat_cat(db_session, 'SVG', ovg)
        _vat_cat(db_session, 'SVS', ovs)

        inv = _invoice(db_session, customer, branch, 'SI-BKT-03', [
            {'amount': 2240, 'vat_category': 'SVG', 'vat_rate': 12, 'account_id': rev.id},
            {'amount': 1120, 'vat_category': 'SVS', 'vat_rate': 12, 'account_id': rev.id},
        ])
        # computed 360; override 100 -> diff -260 drives the 240 bucket to -20
        inv.vat_amount = Decimal('100.00')
        db_session.flush()

        with pytest.raises(ValueError, match='too far below'):
            sv._output_vat_buckets(inv)


# --------------------------------------------------------------------------
# 3c — reversal JE mirrors the stored JE
# --------------------------------------------------------------------------

class TestReversalMirrorsJE:
    def test_reversal_negates_every_line_and_balances(self, db_session, accountant_user):
        from app.withholding_tax.models import WithholdingTax
        customer, branch = _customer(db_session), _branch(db_session)
        _acct(db_session, '10201', 'AR - Trade', 'Asset', 'debit')
        _acct(db_session, '10212', 'Creditable WHT Receivable', 'Asset', 'debit')
        ov = _acct(db_session, '20201', 'Output VAT', 'Liability', 'credit')
        rev = _acct(db_session, '40001', 'Service Revenue', 'Income', 'credit')
        _vat_cat(db_session, 'SV12', ov)
        wt = WithholdingTax.query.filter_by(code='WC010').first()
        if not wt:
            wt = WithholdingTax(code='WC010', name='EWT 10%', rate=Decimal('10.00'), is_active=True)
            db_session.add(wt)
            db_session.flush()
        from tests.conftest import assign_control_accounts
        assign_control_accounts(db_session)

        inv = _invoice(db_session, customer, branch, 'SI-REV-01', [
            {'amount': 11200, 'vat_category': 'SV12', 'vat_rate': 12,
             'account_id': rev.id, 'wt_id': wt.id, 'wt_rate': 10},
        ])
        je = sv._post_invoice_je(inv, accountant_user.id)
        db_session.flush()
        inv.journal_entry_id = je.id
        inv.journal_entry = je
        db_session.flush()
        original = _net_by_code(je)

        rev_je = sv._create_reversal_je(inv, date(2026, 6, 30), accountant_user.id)
        db_session.flush()

        assert rev_je.is_balanced
        assert rev_je.entry_type == 'reversal'
        reversed_net = _net_by_code(rev_je)
        # same accounts, each net exactly negated (every debit↔credit swapped)
        assert set(reversed_net) == set(original)
        for code, amt in original.items():
            assert reversed_net[code] == -amt, f'{code}: {reversed_net[code]} != {-amt}'

    def test_reversal_without_stored_je_raises(self, db_session, accountant_user):
        customer, branch = _customer(db_session), _branch(db_session)
        inv = SalesInvoice(branch_id=branch.id, invoice_number='SI-REV-02',
                           invoice_date=date(2026, 6, 14), due_date=date(2026, 7, 14),
                           customer_id=customer.id, customer_name=customer.name,
                           notes='', status='draft', amount_paid=Decimal('0.00'))
        db_session.add(inv)
        db_session.flush()  # no journal entry attached

        with pytest.raises(ValueError, match='no stored journal entry'):
            sv._create_reversal_je(inv, date(2026, 6, 30), accountant_user.id)
