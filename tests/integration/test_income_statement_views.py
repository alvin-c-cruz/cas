from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.utils import end_of_month, ph_now
from app.reports.views import _stmt_params

pytestmark = [pytest.mark.integration]


def test_stmt_params_defaults_to_month_end(app):
    with app.test_request_context('/reports/income-statement'):
        as_of, mtd_start, ytd_start, _branch = _stmt_params()
    assert as_of == end_of_month(ph_now().date())
    assert mtd_start == as_of.replace(day=1)
    assert ytd_start == as_of.replace(month=1, day=1)


def test_stmt_params_explicit_as_of(app):
    with app.test_request_context('/reports/income-statement?as_of=2026-06-30'):
        as_of, mtd_start, ytd_start, _branch = _stmt_params()
    assert (as_of, mtd_start, ytd_start) == (date(2026, 6, 30), date(2026, 6, 1), date(2026, 1, 1))


def test_stmt_params_legacy_end_date_coerced(app):
    with app.test_request_context('/reports/income-statement?end_date=2026-05-31'):
        as_of, mtd_start, ytd_start, _branch = _stmt_params()
    assert (as_of, mtd_start) == (date(2026, 5, 31), date(2026, 5, 1))


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _acct(code, name, atype, normal='Debit', parent=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent.id if parent else None)
    db.session.add(a)
    db.session.commit()
    return a


def _post(branch_id, debit_acct, credit_acct, amount, number):
    """Balanced posted JE: debit one account, credit the other."""
    amt = Decimal(str(amount))
    je = JournalEntry(entry_number=number, entry_date=date.today(), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=amt, total_credit=amt)
    db.session.add(je)
    db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=debit_acct.id,
                                    debit_amount=amt, credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=credit_acct.id,
                                    debit_amount=Decimal('0'), credit_amount=amt))
    db.session.commit()
    return je


def _seed_pl(branch_id):
    """Create accounts using the new type taxonomy and post P&L JEs.

    Revenue 100 (credit Revenue); AdminExp 40 (debit Admin Expense) -> net income +60.
    Returns (cash, revenue, expense) accounts.
    """
    cash = _acct('10101', 'Cash on Hand', 'Asset', 'Debit')
    revenue = _acct('40001', 'Sales Revenue', 'Revenue', 'Credit')
    expense = _acct('50301', 'Admin Office Supplies', 'Administrative Expense', 'Debit')
    _post(branch_id, cash, revenue, 100, 'IS-REV')
    _post(branch_id, expense, cash, 40, 'IS-EXP')
    return cash, revenue, expense


def test_income_statement_requires_login(client):
    resp = client.get('/reports/income-statement')
    assert resp.status_code in (302, 401)


def test_income_statement_no_longer_redirects(client, db_session, main_branch, admin_user):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 200
    assert b'Income Statement' in resp.data


def test_income_statement_admin_renders(client, db_session, main_branch, admin_user):
    cash, revenue, expense = _seed_pl(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    assert revenue.code.encode() in resp.data          # Revenue account code in markup
    assert expense.code.encode() in resp.data          # Expense account code in markup
    assert b'NET INCOME' in resp.data
    assert b'Gross Profit' in resp.data                # P&L subtotal
    assert b'Operating Income' in resp.data            # P&L subtotal
    assert b'Net Margin' in resp.data                  # net income line (positive revenue)


def test_income_statement_groups_selling_and_admin_under_operating_expenses(
        client, db_session, main_branch, admin_user):
    """Per spec, Selling + Administrative render under a single 'OPERATING
    EXPENSES' heading that precedes them and subtotals to Operating Income."""
    _seed_pl(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert 'OPERATING EXPENSES' in html
    # the umbrella heading comes before the Selling/Administrative sub-sections
    assert html.index('OPERATING EXPENSES') < html.index('Administrative Expenses')
    assert html.index('OPERATING EXPENSES') < html.index('Operating Income')   # subtotal after


def test_income_statement_deduction_section_total_parenthesized(
        client, db_session, main_branch, admin_user):
    """Deduction sections (sign -1: Contra-Revenue/COGS/expenses/tax) show their
    section-header total parenthesized so the sign reads correctly; revenue
    (sign +1) is shown plain. _seed_pl posts revenue 100 + admin expense 40."""
    _seed_pl(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert '(₱40.00)' in html        # admin-expense section total shown as a deduction
    assert '₱100.00' in html         # revenue section total shown plain (positive)


def test_income_statement_expander_caret_has_no_stoppropagation_onclick(
        client, db_session, main_branch, admin_user):
    """Regression guard (BUG-1): the caret button must NOT carry an inline
    onclick="event.stopPropagation()". That inline handler stops the click at
    the button so it never reaches the delegated expander handler in
    fs-drilldown.js — leaving expand/collapse completely non-functional. The
    drill-down handler already ignores caret clicks via closest('[data-fs-expand]'),
    so the inline onclick is both redundant and harmful."""
    group = _acct('40000', 'Sales', 'Revenue', 'Credit')
    child = _acct('40001', 'Sales - Goods', 'Revenue', 'Credit', parent=group)
    cash = _acct('10101', 'Cash on Hand', 'Asset', 'Debit')
    _post(main_branch.id, cash, child, 100, 'IS-GRP')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    assert b'data-fs-expand' in resp.data                       # a caret/expander rendered
    assert b'event.stopPropagation()' not in resp.data          # ...without the killer inline onclick


def test_income_statement_staff_without_grant_denied(client, db_session, main_branch, staff_user):
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 302


def test_income_statement_staff_with_grant_allowed(client, db_session, main_branch, staff_user):
    perms = staff_user.get_book_permissions()
    perms['income_statement'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch)
    db_session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 200


def test_income_statement_viewer_allowed(client, db_session, main_branch, viewer_user):
    viewer_user.branches.append(main_branch)
    db_session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement', follow_redirects=False)
    assert resp.status_code == 200


def test_income_statement_excel_export(client, db_session, main_branch, admin_user):
    _seed_pl(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement/export/excel')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_income_statement_print_renders(client, db_session, main_branch, admin_user):
    from app.settings import AppSettings
    AppSettings.set_setting('company_name', 'ACME Trading Corp')
    _seed_pl(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement/print')
    assert resp.status_code == 200
    assert b'Income Statement' in resp.data
    assert b'ACME Trading Corp' in resp.data


def test_income_statement_defaults_to_year_to_date(client, db_session, main_branch, admin_user):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    jan1 = f'{date.today().year}-01-01'
    assert f'value="{jan1}"'.encode() in resp.data           # start_date defaults to Jan 1


def test_is_page_shows_subtotal_and_drilldown_hooks(client, db_session, admin_user, main_branch):
    _seed_pl(main_branch.id)
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Net Income' in html
    assert 'data-account-id' in html        # drill-down hook present on lines
