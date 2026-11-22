"""BUG-9 (owner, 22 Nov 2026): Previous / Next buttons on every record page of the 15 document modules.

Design A, his words: "The module's list in its default order, in the current branch, every status. Filters and searches
on the list are ignored. The button greys out at either end."

So the order under test is the LIST PAGE's own order: each walk below reads the record links off the rendered list and
steps Next from the top, and a written-out expected order sits beside it. Work order:
app-docs/bug-reports/2026-11-22-previous-next-on-document-pages.md."""
import inspect
import io
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.branches.models import Branch
from app.utils.branch_scope import BRANCH_LIST_ENDPOINTS

pytestmark = [pytest.mark.integration]

WIDE = 'date_from=2000-01-01&date_to=2100-12-31'


@pytest.fixture
def two_branches(main_branch):
    extra = Branch(code='EXTRA', name='Extra', is_active=True)
    db.session.add(extra); db.session.commit()
    return main_branch, extra


@pytest.fixture
def admin_in_main(client, admin_user, two_branches):
    main, _ = two_branches
    with client.session_transaction() as s:
        s['_user_id'] = str(admin_user.id); s['_fresh'] = True
        s['selected_branch_id'] = main.id
    return client


def _enable(*modules):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for m in modules:
        AppSettings.set_setting(f'module_enabled:{m}', '1')
    db.session.commit(); clear_module_config_cache()


def _list_order(client, list_url, prefix):
    """Record ids in the order the list page shows them (each record is linked more than once per row)."""
    html = client.get(list_url).data.decode('utf-8')
    ids = []
    for m in re.finditer(r'href="%s/(\d+)"' % re.escape(prefix), html):
        if int(m.group(1)) not in ids:
            ids.append(int(m.group(1)))
    return ids


def _nav(client, page):
    """(previous, next) as the record page offers them: a path, or 'greyed' for a disabled button, or None when the
    page shows no such button at all."""
    resp = client.get(page)
    assert resp.status_code == 200, (page, resp.status_code)
    html = resp.data.decode('utf-8')
    out = []
    for which in ('prev', 'next'):
        link = re.search(r'<a\b[^>]*\bdata-record-nav="%s"[^>]*\bhref="([^"]+)"' % which, html) \
            or re.search(r'<a\b[^>]*\bhref="([^"]+)"[^>]*\bdata-record-nav="%s"' % which, html)
        greyed = re.search(r'<button\b[^>]*\bdata-record-nav="%s"[^>]*\bdisabled\b' % which, html)
        out.append(link.group(1) if link else ('greyed' if greyed else None))
    return tuple(out)


def _walk(client, prefix, first_id, limit=20):
    """Follow Next from a record to the end; returns the ids visited and checks Previous mirrors Next on the way."""
    seen, current, came_from = [first_id], first_id, 'greyed'
    for _ in range(limit):
        prev, nxt = _nav(client, f'{prefix}/{current}')
        assert prev == came_from, (current, prev, came_from)
        if nxt == 'greyed':
            return seen
        assert nxt and nxt.startswith(prefix + '/'), (current, nxt)
        came_from, current = f'{prefix}/{current}', int(nxt.rsplit('/', 1)[1])
        seen.append(current)
    raise AssertionError('Next never ended: %s' % seen)


# --- cash disbursements: date desc, then id desc; every status; one branch ----------------------------------------

def _cdv(branch, number, day, status='draft'):
    from app.accounts.models import Account
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.vendors.models import Vendor
    vendor = Vendor.query.filter_by(code='V-NAV').first()
    if vendor is None:
        vendor = Vendor(code='V-NAV', name='Nav Vendor', check_payee_name='Nav Vendor', is_active=True)
        cash = Account(code='10101', name='Cash on Hand', account_type='Asset', normal_balance='debit', is_active=True)
        db.session.add_all([vendor, cash]); db.session.commit()
    cash = Account.query.filter_by(code='10101').first()
    cdv = CashDisbursementVoucher(branch_id=branch.id, cdv_number=number, cdv_date=day, vendor_id=vendor.id,
                                  vendor_name=vendor.name, payment_method='cash', cash_account_id=cash.id, notes='',
                                  status=status, total_amount=Decimal('0.00'))
    db.session.add(cdv); db.session.commit()
    return cdv


def test_cdv_previous_next_follow_the_list_and_grey_out_at_the_ends(admin_in_main, two_branches):
    main, extra = two_branches
    a = _cdv(main, 'NAV-A', date(2026, 6, 10))
    b = _cdv(main, 'NAV-B', date(2026, 6, 20), status='cancelled')      # every status
    c = _cdv(main, 'NAV-C', date(2026, 6, 20))                          # same day as B: the later entry comes first
    d = _cdv(main, 'NAV-D', date(2026, 6, 5))
    other = _cdv(extra, 'NAV-X', date(2026, 6, 15))                      # another branch: never a neighbour
    expected = [c.id, b.id, a.id, d.id]

    assert _list_order(admin_in_main, f'/cash-disbursements?{WIDE}', '/cash-disbursements') == expected
    assert _walk(admin_in_main, '/cash-disbursements', c.id) == expected
    assert _nav(admin_in_main, f'/cash-disbursements/{c.id}') == ('greyed', f'/cash-disbursements/{b.id}')
    assert _nav(admin_in_main, f'/cash-disbursements/{d.id}') == (f'/cash-disbursements/{a.id}', 'greyed')
    assert other.id not in expected


def test_cdv_filters_and_search_on_the_list_do_not_narrow_previous_next(admin_in_main, two_branches):
    """The list's own default hides other months and can be filtered by status or searched; the buttons on a record page
    still step through every voucher of the branch."""
    main, _ = two_branches
    old = _cdv(main, 'NAV-OLD', date(2019, 1, 15), status='cancelled')
    new = _cdv(main, 'NAV-NEW', date(2026, 6, 20))
    # opened the way the list links it, and also with list-style arguments on the address
    for page in (f'/cash-disbursements/{new.id}', f'/cash-disbursements/{new.id}?status=posted&q=zzz'):
        assert _nav(admin_in_main, page) == ('greyed', f'/cash-disbursements/{old.id}')


def test_another_branchs_records_have_their_own_chain(admin_in_main, two_branches):
    main, extra = two_branches
    _cdv(main, 'NAV-M1', date(2026, 6, 1))
    x1 = _cdv(extra, 'NAV-X1', date(2026, 6, 2))
    x2 = _cdv(extra, 'NAV-X2', date(2026, 6, 3))
    # opening an EXTRA voucher follows the voucher's branch; its neighbours are EXTRA's only
    assert _nav(admin_in_main, f'/cash-disbursements/{x2.id}') == ('greyed', f'/cash-disbursements/{x1.id}')
    assert _nav(admin_in_main, f'/cash-disbursements/{x1.id}') == (f'/cash-disbursements/{x2.id}', 'greyed')


# --- purchase requisitions (the page the report was made on): date desc, then id desc -----------------------------

def test_pr_previous_next_follow_the_list(admin_in_main, two_branches):
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    _enable('purchase_requests')
    main, extra = two_branches

    def pr(branch, number, day, status='draft'):
        row = PurchaseRequest(branch_id=branch.id, pr_number=number, request_date=day, status=status, reason='Nav')
        row.line_items.append(PurchaseRequestItem(line_number=1, description='Cement', quantity=Decimal('10'),
                                                  uom_text='bag'))
        db.session.add(row); db.session.commit()
        return row
    a = pr(main, 'PR-NAV-A', date(2026, 7, 11))
    b = pr(main, 'PR-NAV-B', date(2026, 7, 30), status='approved')
    c = pr(main, 'PR-NAV-C', date(2026, 7, 11))
    pr(extra, 'PR-NAV-X', date(2026, 7, 20))
    expected = [b.id, c.id, a.id]

    assert _list_order(admin_in_main, '/purchase-requests', '/purchase-requests') == expected
    assert _walk(admin_in_main, '/purchase-requests', b.id) == expected


# --- sales orders: date desc, then id desc -------------------------------------------------------------------------

def test_so_previous_next_follow_the_list(admin_in_main, two_branches):
    from app.customers.models import Customer
    from app.sales_orders.models import SalesOrder
    _enable('sales_orders')
    main, extra = two_branches
    cust = Customer(code='C-NAV', name='Nav Customer', is_active=True)
    db.session.add(cust); db.session.commit()

    def so(branch, number, day, status='confirmed'):
        row = SalesOrder(so_number=number, order_date=day, customer_id=cust.id, customer_name=cust.name,
                         branch_id=branch.id, status=status)
        db.session.add(row); db.session.commit()
        return row
    a = so(main, 'SO-NAV-A', date(2026, 3, 1), status='draft')
    b = so(main, 'SO-NAV-B', date(2026, 9, 1))
    c = so(main, 'SO-NAV-C', date(2026, 3, 1), status='cancelled')
    so(extra, 'SO-NAV-X', date(2026, 5, 1))
    expected = [b.id, c.id, a.id]

    assert _list_order(admin_in_main, f'/sales-orders?{WIDE}', '/sales-orders') == expected
    assert _walk(admin_in_main, '/sales-orders', b.id) == expected


# --- accounts payable: by voucher NUMBER, as a number, highest first -------------------------------------------------

def _ap(branch, number, day):
    from app.accounts_payable.models import AccountsPayable
    from app.vendors.models import Vendor
    vendor = Vendor.query.filter_by(code='V-APNAV').first()
    if vendor is None:
        vendor = Vendor(code='V-APNAV', name='AP Nav Vendor', is_active=True, payment_terms='Net 30')
        db.session.add(vendor); db.session.commit()
    row = AccountsPayable(ap_number=number, vendor_id=vendor.id, vendor_name=vendor.name, vendor_tin='',
                          vendor_address='', branch_id=branch.id, ap_date=day, due_date=day, status='draft',
                          subtotal=Decimal('100'), vat_amount=Decimal('0'), total_before_wt=Decimal('100'),
                          withholding_tax_rate=Decimal('0'), withholding_tax_amount=Decimal('0'),
                          total_amount=Decimal('100'), amount_paid=Decimal('0'), balance=Decimal('100'),
                          payment_terms='Net 30')
    db.session.add(row); db.session.commit()
    return row


def test_ap_previous_next_follow_the_number_order_of_the_list(admin_in_main, two_branches):
    main, _ = two_branches
    n100 = _ap(main, '00100', date(2026, 1, 5))  # the oldest date but the highest number: it leads the list
    n9 = _ap(main, '00009', date(2026, 8, 1))
    n10 = _ap(main, '00010', date(2026, 5, 1))
    expected = [n100.id, n10.id, n9.id]

    assert _list_order(admin_in_main, f'/accounts-payable?{WIDE}', '/accounts-payable') == expected
    assert _walk(admin_in_main, '/accounts-payable', n100.id) == expected


# --- journal vouchers: date desc, same-date in entry order; an entry that is not a voucher has no buttons -----------

def test_jv_previous_next_follow_the_voucher_list_and_other_entries_show_none(admin_in_main, two_branches):
    from app.journal_entries.models import JournalEntry
    main, _ = two_branches

    def je(number, day, entry_type='adjustment', status='posted'):
        row = JournalEntry(entry_number=number, entry_date=day, description=f'Nav {number}', entry_type=entry_type,
                           status=status, branch_id=main.id, total_debit=100, total_credit=100)
        db.session.add(row); db.session.commit()
        return row
    a = je('JV-NAV-A', date(2026, 4, 2))
    b = je('JV-NAV-B', date(2026, 4, 9), status='draft')
    c = je('JV-NAV-C', date(2026, 4, 9))
    system = je('SI-NAV-1', date(2026, 4, 5), entry_type='sales_invoice')      # another document's entry
    expected = [b.id, c.id, a.id]          # newest date first; B and C share a date and run in the order entered

    assert _list_order(admin_in_main, f'/journals/voucher?{WIDE}', '/journal-entries') == expected
    assert _walk(admin_in_main, '/journal-entries', b.id) == expected
    assert _nav(admin_in_main, f'/journal-entries/{system.id}') == (None, None)


# --- memos: a blueprint with two lists; a memo steps through the list of its own kind --------------------------------

def test_vendor_memo_previous_next_stay_within_the_memos_own_list(admin_in_main, two_branches):
    from app.purchase_memos.models import PurchaseMemo
    from app.users.module_access import module_key_for_endpoint
    # the debit and the credit memo are two optional modules of one blueprint
    _enable(*{module_key_for_endpoint('purchase_memos.debit_list'),
              module_key_for_endpoint('purchase_memos.credit_view')} - {None})
    main, _ = two_branches
    bill = _ap(main, '00500', date(2026, 2, 1))

    def memo(kind, number, day):
        row = PurchaseMemo(branch_id=main.id, memo_type=kind, memo_number=number, memo_date=day,
                           accounts_payable_id=bill.id, original_ap_number=bill.ap_number, vendor_id=bill.vendor_id,
                           vendor_name=bill.vendor_name, reason='Nav test', notes='', status='draft')
        db.session.add(row); db.session.commit()
        return row
    d1 = memo('debit', 'VDM-NAV-1', date(2026, 2, 1))
    c1 = memo('credit', 'VCM-NAV-1', date(2026, 2, 5))
    d2 = memo('debit', 'VDM-NAV-2', date(2026, 2, 9))

    assert _list_order(admin_in_main, '/vendor-debit-memos', '/vendor-debit-memos') == [d2.id, d1.id]
    assert _walk(admin_in_main, '/vendor-debit-memos', d2.id) == [d2.id, d1.id]
    assert _nav(admin_in_main, f'/vendor-credit-memos/{c1.id}') == ('greyed', 'greyed')


# --- every one of the 15 modules is wired, and wired to its own list's order ------------------------------------------

#: module -> (record-page template, the variable that holds the record, the list's ORDER BY as SQL)
WIRING = {
    'accounts_payable': ('accounts_payable/detail.html', 'ap',
                         'CAST(accounts_payable.ap_number AS INTEGER) DESC, accounts_payable.id DESC'),
    'cash_disbursements': ('cash_disbursements/detail.html', 'cdv',
                           'cash_disbursement_vouchers.cdv_date DESC, cash_disbursement_vouchers.id DESC'),
    'cash_receipts': ('cash_receipts/detail.html', 'crv',
                      'cash_receipt_vouchers.crv_date DESC, cash_receipt_vouchers.id DESC'),
    'delivery_receipts': ('delivery_receipts/detail.html', 'dr',
                          'delivery_receipts.delivery_date DESC, delivery_receipts.id DESC'),
    'journal_entries': ('journal_entries/detail.html', 'entry',
                        'journal_entries.entry_date DESC, journal_entries.id ASC'),
    'payroll': ('payroll/detail.html', 'run', 'payroll_runs.id DESC'),
    'purchase_memos': ('purchase_memos/detail.html', 'memo',
                       'purchase_memos.memo_date DESC, purchase_memos.id DESC'),
    'purchase_orders': ('purchase_orders/detail.html', 'po',
                        'purchase_orders.order_date DESC, purchase_orders.id DESC'),
    'purchase_requests': ('purchase_requests/detail.html', 'pr',
                          'purchase_requests.request_date DESC, purchase_requests.id DESC'),
    'quotations': ('quotations/detail.html', 'quote', 'quotations.quotation_date DESC, quotations.id DESC'),
    'receiving_reports': ('receiving_reports/detail.html', 'rr',
                          'receiving_reports.receipt_date DESC, receiving_reports.id DESC'),
    'sales_invoices': ('sales_invoices/detail.html', 'invoice',
                       'sales_invoices.invoice_date DESC, sales_invoices.id DESC'),
    'sales_memos': ('sales_memos/detail.html', 'memo', 'sales_memos.memo_date DESC, sales_memos.id DESC'),
    'sales_orders': ('sales_orders/detail.html', 'so', 'sales_orders.order_date DESC, sales_orders.id DESC'),
    'work_orders': ('work_orders/view.html', 'wo', 'work_orders.id DESC'),
}


def test_the_table_names_all_15_modules():
    assert set(WIRING) == set(BRANCH_LIST_ENDPOINTS) | {'sales_memos', 'purchase_memos'}
    assert len(WIRING) == 15


def test_every_module_is_wired_to_its_own_lists_order(app):
    from app.common.record_nav import SPECS, order_sql
    assert set(SPECS) == set(WIRING)
    for module, (template, variable, order) in WIRING.items():
        assert order_sql(module) == order, module
        source = io.open(f'app/{module}/templates/{template}', encoding='utf-8').read()
        include = "{%% with nav_module='%s', nav_record=%s %%}{%% include '_record_nav.html' %%}{%% endwith %%}" % (
            module, variable)
        assert source.count(include) == 1, (module, 'the record page must include the buttons once')


def test_each_list_view_still_sorts_the_way_previous_next_assumes(app):
    """If a list's default order is ever changed, this points at app/common/record_nav.py: the buttons must follow."""
    from app.journals.views import voucher
    from app.purchase_memos.views import _list_impl as purchase_memo_list
    from app.sales_memos.views import _list_impl as sales_memo_list
    expects = {
        'accounts_payable.list_ap': ['db.cast(AccountsPayable.ap_number, db.Integer).desc()', 'AccountsPayable.id.desc()'],
        'cash_disbursements.list_cdvs': ['CashDisbursementVoucher.cdv_date.desc()', 'CashDisbursementVoucher.id.desc()'],
        'cash_receipts.list_crvs': ['CashReceiptVoucher.crv_date.desc()', 'CashReceiptVoucher.id.desc()'],
        'delivery_receipts.list': ['DeliveryReceipt.delivery_date.desc()', 'DeliveryReceipt.id.desc()'],
        'payroll.register': ['PayrollRun.id.desc()'],
        'purchase_orders.list_po': ['PurchaseOrder.order_date.desc()', 'PurchaseOrder.id.desc()'],
        'purchase_requests.list_pr': ['PurchaseRequest.request_date.desc()', 'PurchaseRequest.id.desc()'],
        'quotations.list': ['Quotation.quotation_date.desc()', 'Quotation.id.desc()'],
        'receiving_reports.list_rr': ['ReceivingReport.receipt_date.desc()', 'ReceivingReport.id.desc()'],
        'sales_invoices.list_invoices': ['SalesInvoice.invoice_date.desc()', 'SalesInvoice.id.desc()'],
        'sales_orders.list': ['SalesOrder.order_date.desc()', 'SalesOrder.id.desc()'],
        'work_orders.list': ['WorkOrder.id.desc()'],
    }
    sources = {ep: inspect.getsource(inspect.unwrap(app.view_functions[ep])) for ep in expects}
    sources['journals.voucher'] = inspect.getsource(inspect.unwrap(voucher))
    expects['journals.voucher'] = ['JournalEntry.entry_date.desc()', 'JournalEntry.id.asc()']
    sources['sales_memos'] = inspect.getsource(sales_memo_list)
    expects['sales_memos'] = ['SalesMemo.memo_date.desc()', 'SalesMemo.id.desc()']
    sources['purchase_memos'] = inspect.getsource(purchase_memo_list)
    expects['purchase_memos'] = ['PurchaseMemo.memo_date.desc()', 'PurchaseMemo.id.desc()']
    assert len(expects) == 15
    for name, parts in expects.items():
        for part in parts:
            assert part in sources[name], (name, part)


def test_no_buttons_for_anything_that_is_not_a_saved_record_of_the_15(app):
    from jinja2 import Undefined
    from app.common.record_nav import record_nav
    with app.test_request_context():
        assert record_nav('customers', object()) is None          # not one of the 15 modules
        assert record_nav('sales_orders', None) is None
        assert record_nav('sales_orders', object()) is None        # nothing saved
        assert record_nav('sales_orders', Undefined()) is None     # a template that passed no record
