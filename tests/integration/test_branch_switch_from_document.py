"""BRANCH-SWITCH B (owner, 22 Nov 2026): switching branch from a record's page lands on that module's list in the new
branch. Before, the switch redirected back to the document, whose require_same_branch() switched the session straight
back to the document's branch, so "You are now working in: EXTRA" was shown while the user stayed in CORP.
Work order: app-docs/bug-reports/2026-11-22-branch-switch-on-a-document-page.md."""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.branches.models import Branch
from app.utils.branch_scope import BRANCH_LIST_ENDPOINTS

pytestmark = [pytest.mark.integration]

#: Where each module's record pages land after a branch switch. Written out as URLs on purpose: the owner named a URL
#: ("the other Branch's Disbursement page .../cash-disbursements"), and a table derived from the code under test could
#: only agree with it.
EXPECTED_LIST = {
    'accounts_payable': '/accounts-payable',
    'cash_disbursements': '/cash-disbursements',
    'cash_receipts': '/cash-receipts',
    'delivery_receipts': '/delivery-receipts',
    'journal_entries': '/journal-entries',
    'payroll': '/payroll/runs',
    'purchase_orders': '/purchase-orders',
    'purchase_requests': '/purchase-requests',
    'quotations': '/quotations',
    'receiving_reports': '/receiving-reports',
    'sales_invoices': '/sales-invoices',
    'sales_orders': '/sales-orders',
    'work_orders': '/work-orders',
}
#: The two blueprints with a debit and a credit list each: a memo's page lands on its own list, the first segment of
#: its path (/credit-memos/5/print -> /credit-memos).
MEMO_BLUEPRINTS = ('sales_memos', 'purchase_memos')
MEMO_LISTS = {'/credit-memos', '/debit-notes', '/vendor-credit-memos', '/vendor-debit-memos'}
#: BRANCH-SWITCH-2 (owner, 22 Nov 2026: "A"). Five modules outside the guard load a record as "this id in the session's
#: branch, else 404", so a switch that returned to one of their record pages showed "not found". Petty cash has one
#: list, the funds; its vouchers and replenishments land there too.
EXPECTED_LIST_UNGUARDED = {
    'bank_accounts': '/bank-accounts/',
    'manufacturing_departments': '/manufacturing-departments',
    'petty_cash': '/petty-cash/funds',
    'production_runs': '/production-runs',
    'work_centers': '/work-centers',
}


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


def _record_pages(app):
    """Every GET route of the guarded modules that is about ONE record (it takes URL arguments), whatever the argument
    is called: (blueprint, path with 41 for each argument)."""
    pages = []
    for rule in app.url_map.iter_rules():
        bp = rule.endpoint.split('.')[0]
        if (bp in EXPECTED_LIST or bp in MEMO_BLUEPRINTS or bp in EXPECTED_LIST_UNGUARDED) \
                and 'GET' in rule.methods and rule.arguments:
            pages.append((bp, re.sub(r'<[^>]+>', '41', rule.rule)))
    return pages


def _expected(bp, path):
    if bp in MEMO_BLUEPRINTS:
        first = '/' + path.split('/')[1]
        assert first in MEMO_LISTS, path
        return first
    return EXPECTED_LIST[bp] if bp in EXPECTED_LIST else EXPECTED_LIST_UNGUARDED[bp]


def _switch(client, branch_id, next_path):
    return client.post('/select-branch', data={'branch_id': branch_id, 'next': next_path})


def test_the_table_names_every_guarded_module(app):
    """A module that starts guarding its branch must be added here, with its list."""
    assert set(EXPECTED_LIST) == set(BRANCH_LIST_ENDPOINTS)
    assert {bp for bp, _ in _record_pages(app)} == (set(EXPECTED_LIST) | set(MEMO_BLUEPRINTS)
                                                    | set(EXPECTED_LIST_UNGUARDED))


def test_the_second_table_names_every_module_that_answers_not_found_in_another_branch():
    """The five load a record with this exact lookup scoped to the session's branch. A sixth module that copies it must
    be added to SESSION_SCOPED_LIST_ENDPOINTS (and to the table above), or a branch switch from one of its record pages
    goes back to a page that is "not found" in the new branch."""
    import glob
    import io
    from app.utils.branch_scope import SESSION_SCOPED_LIST_ENDPOINTS
    needle = ".filter_by(id=id, branch_id=session.get('selected_branch_id'))"
    found = {path.replace('\\', '/').split('/')[1] for path in glob.glob('app/*/views.py')
             if needle in io.open(path, encoding='utf-8').read()}
    assert found == set(EXPECTED_LIST_UNGUARDED)
    assert set(SESSION_SCOPED_LIST_ENDPOINTS) == set(EXPECTED_LIST_UNGUARDED)


def test_switch_from_any_record_page_lands_on_its_modules_list(app, admin_in_main, two_branches):
    main, extra = two_branches
    wrong = []
    for bp, path in _record_pages(app):
        resp = _switch(admin_in_main, extra.id, path)
        got = resp.headers.get('Location', '')
        if resp.status_code != 302 or got != _expected(bp, path):
            wrong.append((path, resp.status_code, got, _expected(bp, path)))
        with admin_in_main.session_transaction() as s:
            assert s['selected_branch_id'] == extra.id
            s['selected_branch_id'] = main.id                 # back to MAIN for the next page
    assert not wrong, wrong


def test_the_owners_case_a_cdv_page_to_the_other_branchs_cdv_list(admin_in_main, two_branches):
    """Alvin, 22 Nov 2026: "the user will be redirected to the other Branch's Disbursement page". The path is posted as
    the sidebar posts it (request.full_path, with its trailing '?')."""
    _, extra = two_branches
    resp = admin_in_main.post('/select-branch', data={'branch_id': extra.id, 'next': '/cash-disbursements/289?'},
                              follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/cash-disbursements'
    assert b'You are now working in: Extra' in resp.data
    assert b'<div class="branch-name-sidebar">Extra</div>' in resp.data      # the banner and the sidebar agree
    with admin_in_main.session_transaction() as s:
        assert s['selected_branch_id'] == extra.id


def test_a_stale_tab_still_lands_on_the_list(admin_in_main, two_branches):
    """The branch was already switched in another tab: the session says EXTRA while this page still shows a MAIN
    document and offers EXTRA in its menu. Going back to the document would flip the session to MAIN again."""
    _, extra = two_branches
    with admin_in_main.session_transaction() as s:
        s['selected_branch_id'] = extra.id
    resp = _switch(admin_in_main, extra.id, '/cash-disbursements/41')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/cash-disbursements'


def test_the_sign_in_branch_picker_keeps_a_deep_link(client, admin_user, two_branches):
    """No branch chosen yet (just signed in, sent to the picker on the way to a document): the user asked for that
    document, so the picker still sends them on to it."""
    _, extra = two_branches
    with client.session_transaction() as s:
        s['_user_id'] = str(admin_user.id); s['_fresh'] = True
        s['needs_branch_selection'] = True
    resp = client.post('/select-branch', data={'branch_id': extra.id, 'next': '/cash-disbursements/41'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/cash-disbursements/41')


def test_switch_from_a_list_page_returns_to_that_list(admin_in_main, two_branches):
    _, extra = two_branches
    resp = _switch(admin_in_main, extra.id, '/cash-disbursements?status=all')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/cash-disbursements?status=all')


def test_switch_from_a_page_that_is_no_record_is_unchanged(admin_in_main, two_branches):
    _, extra = two_branches
    for path in ('/dashboard', '/cash-disbursements/create', '/customers/41'):
        resp = _switch(admin_in_main, extra.id, path)
        assert resp.headers['Location'].endswith(path), path
        with admin_in_main.session_transaction() as s:
            s['selected_branch_id'] = two_branches[0].id


def test_end_to_end_a_module_that_used_to_answer_not_found(admin_in_main, two_branches):
    """BRANCH-SWITCH-2 on a real record: a manufacturing department of MAIN. Its edit page opens in MAIN and is "not
    found" in any other branch, which is where the switch used to send the user back to."""
    from app.manufacturing_departments.models import ManufacturingDepartment
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:manufacturing_departments', '1'); db.session.commit()
    clear_module_config_cache()
    main, extra = two_branches
    dept = ManufacturingDepartment(branch_id=main.id, code='MIX', name='Mixing', is_active=True)
    db.session.add(dept); db.session.commit()
    page = f'/manufacturing-departments/{dept.id}/edit'
    assert admin_in_main.get(page).status_code == 200                       # it opens in its own branch

    resp = admin_in_main.post('/select-branch', data={'branch_id': extra.id, 'next': page + '?'},
                              follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/manufacturing-departments'
    assert b'You are now working in: Extra' in resp.data
    assert b'<div class="branch-name-sidebar">Extra</div>' in resp.data
    assert admin_in_main.get(page).status_code == 404                       # the record itself stays MAIN's alone
    clear_module_config_cache()


def test_end_to_end_a_real_sales_order(app, admin_in_main, two_branches, db_session):
    """On a real document, where returning to it WOULD flip the session back: the user ends in the new branch, on the
    list, and stays there."""
    from app.customers.models import Customer
    from app.products.models import Product
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1'); db.session.commit()
    clear_module_config_cache()
    main, extra = two_branches
    c = Customer(code='BSW', name='Switcher Co', is_active=True)
    p = Product(code='BSW-P', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-BSW-1', order_date=date(2026, 11, 2), customer_id=c.id, customer_name=c.name,
                    branch_id=main.id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('1'),
                                        unit_price=Decimal('1'), amount=Decimal('1')))
    db.session.add(so); db.session.commit()

    resp = admin_in_main.post('/select-branch', data={'branch_id': extra.id, 'next': f'/sales-orders/{so.id}'},
                              follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == '/sales-orders'
    assert b'You are now working in: Extra' in resp.data
    assert b'<div class="branch-name-sidebar">Extra</div>' in resp.data
    with admin_in_main.session_transaction() as s:
        assert s['selected_branch_id'] == extra.id
    clear_module_config_cache()
