"""Credit-memo lifecycle: post applies the AR reduction + posts the JE; void reverses both."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_vat_categories.models import SalesVATCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_memos.models import SalesMemo, SalesMemoItem
from app.sales_memos import service
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


@pytest.fixture(autouse=True)
def _module_cache_isolation():
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _acct(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, classification='General',
                normal_balance=nb)
    db.session.add(a)
    return a


def _setup(client, admin_user, main_branch, si_paid='0'):
    coa = {}
    for k, args in {
        'ar': ('10201', 'Accounts Receivable - Trade', 'Asset', 'Debit'),
        'wt': ('10212', 'Creditable Withholding Tax', 'Asset', 'Debit'),
        'outvat': ('20401', 'Output VAT', 'Liability', 'Credit'),
        'contra': ('40103', 'Sales Returns and Allowances', 'Income', 'Debit'),
        'cc': ('20301', 'Customer Credits', 'Liability', 'Credit'),
        'rev': ('40101', 'Sales - Goods', 'Income', 'Credit'),
    }.items():
        coa[k] = _acct(*args)
    db.session.commit()
    vat = SalesVATCategory(code='V12', name='VATABLE', rate=Decimal('12'),
                           output_vat_account_id=coa['outvat'].id, is_active=True)
    db.session.add(vat); db.session.commit()
    AppSettings.set_setting(service.SALES_RETURNS_KEY, '40103')
    AppSettings.set_setting(service.CUSTOMER_CREDITS_KEY, '20301')
    AppSettings.set_setting('module_enabled:credit_memos', '1')
    from app.utils.cache_helpers import clear_module_config_cache
    db.session.commit(); clear_module_config_cache()

    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    paid = Decimal(si_paid)
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-1',
                      invoice_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
                      customer_id=c.id, customer_name='Acme', notes='',
                      status=('partially_paid' if paid > 0 else 'posted'),
                      total_amount=Decimal('1120'), amount_paid=paid,
                      balance=Decimal('1120') - paid)
    li = SalesInvoiceItem(line_number=1, description='Widget', amount=Decimal('1120'),
                          vat_category='V12', vat_rate=Decimal('12'), account_id=coa['rev'].id)
    li.calculate_amounts(); si.line_items.append(li)
    db.session.add(si); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return si, li


def _draft_memo(main_branch, si, li, credit='560', destination='ar'):
    memo = SalesMemo(memo_type='credit', memo_number='CM-1', memo_date=date(2026, 7, 10),
                     branch_id=main_branch.id, sales_invoice_id=si.id,
                     original_invoice_number='SI-1', customer_id=si.customer_id,
                     customer_name='Acme', reason='return', destination=destination, status='draft')
    ml = SalesMemoItem(line_number=1, sales_invoice_item_id=li.id, amount=Decimal(credit),
                       vat_category='V12', vat_rate=Decimal('12'), account_id=li.account_id)
    ml.calculate_amounts(); memo.line_items.append(ml); memo.calculate_totals()
    db.session.add(memo); db.session.commit()
    return memo.id


def test_post_reduces_si_balance_and_posts_je(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    mid, sid = _draft_memo(main_branch, si, li, credit='560'), si.id
    resp = client.post(f'/credit-memos/{mid}/post', follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(SalesMemo, mid); inv = db.session.get(SalesInvoice, sid)
    assert memo.status == 'posted'
    assert memo.journal_entry_id is not None and memo.journal_entry.status == 'posted'
    assert inv.balance == Decimal('560.00')          # 1120 - 560
    assert inv.status == 'partially_paid'


def test_void_restores_si_balance_and_reverses_je(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    mid, sid = _draft_memo(main_branch, si, li, credit='560'), si.id
    client.post(f'/credit-memos/{mid}/post', follow_redirects=True)
    resp = client.post(f'/credit-memos/{mid}/void',
                       data={'void_reason': 'Wrong invoice picked'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(SalesMemo, mid); inv = db.session.get(SalesInvoice, sid)
    assert memo.status == 'voided'
    assert inv.balance == Decimal('1120.00') and inv.status == 'posted'
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(reference='CM-1', entry_type='reversal').first() is not None


def test_post_ar_over_credit_blocked(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch, si_paid='820')  # open balance 300
    mid, sid = _draft_memo(main_branch, si, li, credit='560'), si.id   # total 560 > 300
    client.post(f'/credit-memos/{mid}/post', follow_redirects=True)
    memo = db.session.get(SalesMemo, mid); inv = db.session.get(SalesInvoice, sid)
    assert memo.status == 'draft'                    # blocked, unchanged
    assert inv.balance == Decimal('300.00')


def test_cannot_post_twice(client, db_session, admin_user, main_branch):
    si, li = _setup(client, admin_user, main_branch)
    mid, sid = _draft_memo(main_branch, si, li, credit='560'), si.id
    client.post(f'/credit-memos/{mid}/post', follow_redirects=True)
    client.post(f'/credit-memos/{mid}/post', follow_redirects=True)   # second attempt
    inv = db.session.get(SalesInvoice, sid)
    assert inv.balance == Decimal('560.00')          # not reduced twice
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(reference='CM-1', entry_type='sale').count() == 1


def test_post_blocked_when_memo_date_in_closed_period(client, db_session, admin_user, main_branch):
    """A memo posts real GL, so a memo dated in a closed period must not post.

    This blueprint validated the period nowhere (create or post) before R3.
    """
    from app.periods.models import AccountingPeriod

    si, li = _setup(client, admin_user, main_branch)
    # memo_date is 2026-07-10 (see _draft_memo); close that month.
    db.session.add(AccountingPeriod(year=2026, month=7, status='closed'))
    db.session.commit()

    mid, sid = _draft_memo(main_branch, si, li, credit='560'), si.id
    resp = client.post(f'/credit-memos/{mid}/post', follow_redirects=True)
    assert resp.status_code == 200

    memo = db.session.get(SalesMemo, mid)
    inv = db.session.get(SalesInvoice, sid)
    assert memo.status == 'draft', 'a memo dated in a closed period must not post'
    assert memo.journal_entry_id is None
    assert inv.balance == Decimal('1120.00')          # SI untouched


def test_void_blocked_when_current_period_closed(client, db_session, admin_user, main_branch):
    """Void reverses via a JE dated TODAY, so a closed current month must block it."""
    from app.periods.models import AccountingPeriod
    from app.utils import ph_now

    si, li = _setup(client, admin_user, main_branch)
    mid, sid = _draft_memo(main_branch, si, li, credit='560'), si.id
    client.post(f'/credit-memos/{mid}/post', follow_redirects=True)

    now = ph_now()
    db.session.add(AccountingPeriod(year=now.year, month=now.month, status='closed'))
    db.session.commit()

    resp = client.post(f'/credit-memos/{mid}/void',
                       data={'void_reason': 'Wrong invoice picked'}, follow_redirects=True)
    assert resp.status_code == 200
    memo = db.session.get(SalesMemo, mid)
    inv = db.session.get(SalesInvoice, sid)
    assert memo.status == 'posted', 'void must be blocked while the current period is closed'
    assert inv.balance == Decimal('560.00'), 'SI balance unchanged (no reversal happened)'
