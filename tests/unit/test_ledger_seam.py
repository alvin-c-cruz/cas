"""period_balances()/ledger_lines() on the GAAP basis must equal the per-account SQL the
reports ran before the seam existed: posted only, optional branch, optional date bounds,
optional closing-entry exclusion."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports import ledger as L

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]


def _acct(code, atype, normal):
    a = Account(code=code, name=f'A{code}', account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _post(branch_id, debit_acct, credit_acct, amount, number, on, entry_type='adjustment', status='posted'):
    amt = Decimal(str(amount))
    je = JournalEntry(entry_number=number, entry_date=on, description='d', reference=number,
                      entry_type=entry_type, branch_id=branch_id, status=status,
                      is_balanced=True, total_debit=amt, total_credit=amt)
    db.session.add(je); db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=debit_acct.id,
                                    debit_amount=amt, credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=credit_acct.id,
                                    debit_amount=Decimal('0'), credit_amount=amt))
    db.session.commit()
    return je


@pytest.fixture
def books(db_session, main_branch, branch_manila):
    cash = _acct('10101', 'Asset', 'Debit')
    sales = _acct('40001', 'Revenue', 'Credit')
    re_ = _acct('30201', 'Equity', 'Credit')
    _post(main_branch.id, cash, sales, 100, 'J1', date(2026, 1, 10))
    _post(main_branch.id, cash, sales, 50, 'J2', date(2026, 2, 5))
    _post(main_branch.id, sales, re_, 150, 'J3', date(2026, 2, 28), entry_type='closing')
    _post(main_branch.id, cash, sales, 999, 'J4', date(2026, 2, 6), status='draft')
    _post(branch_manila.id, cash, sales, 7, 'J5', date(2026, 2, 7))
    return {'cash': cash, 'sales': sales, 're': re_, 'main': main_branch.id, 'manila': branch_manila.id}


def test_balances_posted_only_branch_scoped(books):
    b = L.period_balances(None, date(2026, 12, 31), books['main'])
    assert b[books['cash'].id] == (Decimal('150.00'), Decimal('0.00'))
    assert b[books['sales'].id] == (Decimal('150.00'), Decimal('150.00'))   # closing debit included
    assert books['re'].id in b


def test_balances_exclude_closing_and_bound_by_dates(books):
    b = L.period_balances(date(2026, 2, 1), date(2026, 2, 28), books['main'], exclude_closing=True)
    assert b[books['sales'].id] == (Decimal('0.00'), Decimal('50.00'))
    assert books['re'].id not in b


def test_balances_all_branches_when_branch_none(books):
    b = L.period_balances(None, None, None)
    assert b[books['cash'].id][0] == Decimal('157.00')


def test_ledger_lines_ordered_and_filterable(books):
    lines = L.ledger_lines(date(2026, 1, 1), date(2026, 12, 31), books['main'], account_id=books['sales'].id)
    assert [l.entry_number for l in lines] == ['J1', 'J2', 'J3']
    assert lines[0].credit == Decimal('100.00') and lines[0].debit == Decimal('0.00')
    assert lines[0].moved_from_account_id is None
    assert lines[0].description == 'd'                    # falls back to entry description
    assert lines[0].display_number == 'J1'


from app.reports.owners_ledger import RemapSummary
from app.sales_vat_categories.models import SalesVATCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem


@pytest.fixture
def vat_books(db_session, main_branch, vl_customer):
    ar = _acct('112001', 'Asset', 'Debit')
    sales = _acct('411001', 'Revenue', 'Credit')
    output = _acct('213005', 'Liability', 'Credit')
    db.session.add(SalesVATCategory(code='V12', name='V', rate=Decimal('12.00'),
                                    transaction_nature='regular', output_vat_account_id=output.id))
    db.session.commit()
    je = JournalEntry(entry_number='J1', entry_date=date(2026, 3, 10), description='d', reference='J1',
                      entry_type='sale', branch_id=main_branch.id, status='posted', is_balanced=True,
                      total_debit=Decimal('112'), total_credit=Decimal('112'))
    db.session.add(je); db.session.flush()
    db.session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=ar.id, debit_amount=Decimal('112'), credit_amount=0),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=sales.id, debit_amount=0, credit_amount=Decimal('100')),
        JournalEntryLine(entry_id=je.id, line_number=3, account_id=output.id, debit_amount=0, credit_amount=Decimal('12'))])
    inv = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1', invoice_date=date(2026, 3, 10),
                       due_date=date(2026, 3, 10), customer_id=vl_customer.id, customer_name=vl_customer.name,
                       customer_tin=vl_customer.tin, status='posted', journal_entry_id=je.id)
    inv.line_items.append(SalesInvoiceItem(line_number=1, description='x', amount=Decimal('112'),
                                           vat_rate=Decimal('12'), vat_category='V12', vat_nature='regular',
                                           line_total=Decimal('112'), vat_amount=Decimal('12'), account_id=sales.id))
    db.session.add(inv); db.session.commit()
    return {'sales': sales, 'output': output, 'main': main_branch.id}


def test_owners_balances_fold_output_vat_into_sales(vat_books):
    b = L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
    assert b[vat_books['sales'].id] == (Decimal('0.00'), Decimal('112.00'))
    assert vat_books['output'].id not in b
    s = L.owners_summary(None, None, vat_books['main'])
    assert isinstance(s, RemapSummary) and s.moved_to_income == Decimal('12.00')


def test_owners_lines_annotate_moved_from(vat_books):
    lines = L.ledger_lines(None, None, vat_books['main'], reporting_basis=L.OWNERS, account_id=vat_books['sales'].id)
    assert [(l.credit, l.moved_from_account_id) for l in lines] == \
        [(Decimal('100.00'), None), (Decimal('12.00'), vat_books['output'].id)]


def test_owners_result_is_cached_within_a_request_only(app, vat_books, monkeypatch):
    import app.reports.owners_ledger as O
    calls = {'n': 0}
    real = O.remap
    def counting(lines):
        calls['n'] += 1
        return real(lines)
    monkeypatch.setattr(O, 'remap', counting)
    L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
    L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
    assert calls['n'] == 2                                  # no request -> no cache
    with app.test_request_context('/reports/income-statement'):
        from flask import g
        g._ledger_cache = {}
        L.period_balances(None, None, vat_books['main'], reporting_basis=L.OWNERS)
        L.ledger_lines(None, None, vat_books['main'], reporting_basis=L.OWNERS)
        L.owners_summary(None, None, vat_books['main'])
    assert calls['n'] == 3                                  # one remap for the three reads
