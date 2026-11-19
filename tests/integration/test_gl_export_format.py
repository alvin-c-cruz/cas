"""The General Ledger Excel export in the owner's layout, with numbers as numbers (GLX A, owner 14 Nov 2026).

Work order 2026-11-09-recommendation-gl-export-format, from Alvin's own edit of an export (213001, October 2026):
company name, account, "General Ledger", the period, then Date / Source / Particulars / Debit / Credit / Balance, an
Opening balance row, and a running balance that is a live formula (=F7+D8-E8 ...). Two fixes on top of his file:
- amounts were written as TEXT (utils/export.format_value sent floats through str()), so a SUM skipped them;
- his closing row was =F25+D26-E26, which counts the period's debits and credits twice; the closing balance is the
  last running balance.
Balance stays debit-positive (a credit balance is negative), which is what he asked: "if yes, it should be negative".
"""
import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app.settings import AppSettings
from app.utils.export import format_value
from tests.integration.test_general_ledger_views import _login, _post_je, _select_branch

pytestmark = [pytest.mark.integration]

URL = '/reports/general-ledger/export/excel?start_date=2026-10-01&end_date=2026-10-31'


def _sheet(client, query=''):
    resp = client.get(URL + query)
    assert resp.status_code == 200
    return openpyxl.load_workbook(io.BytesIO(resp.data)).active


def _setup(client, db_session, main_branch, admin_user, cash_account, revenue_account):
    AppSettings.set_setting('company_name', 'PHILGEN PACIFIC FOOD PRODUCTS CORPORATION')
    _post_je(main_branch.id, cash_account, revenue_account, date(2026, 9, 30), 'JE-OPEN')   # before: opening
    _post_je(main_branch.id, cash_account, revenue_account, date(2026, 10, 6), 'JE-OCT-1')
    _post_je(main_branch.id, cash_account, revenue_account, date(2026, 10, 9), 'JE-OCT-2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)


class TestNumbersAreNumbers:

    @pytest.mark.parametrize('value', [62.5, 0.0, 12375.59, 3, -1.25])
    def test_numbers_stay_numbers(self, value):
        assert format_value(value) == value and not isinstance(format_value(value), str)

    def test_the_rest_is_unchanged(self):
        assert format_value(True) == 'Yes' and format_value(False) == 'No'
        assert format_value(Decimal('1.50')) == 1.5
        assert format_value(None) == ''
        assert format_value(date(2026, 10, 6)) == '2026-10-06'
        assert format_value('AP 00037') == 'AP 00037'


class TestOneAccount:

    def test_the_owners_layout(self, client, db_session, main_branch, admin_user, cash_account, revenue_account):
        _setup(client, db_session, main_branch, admin_user, cash_account, revenue_account)
        ws = _sheet(client, f'&account_id={cash_account.id}')
        assert ws['A1'].value == 'PHILGEN PACIFIC FOOD PRODUCTS CORPORATION' and ws['A1'].font.b
        assert ws['A2'].value == f'{cash_account.code} - {cash_account.name}'
        assert ws['A3'].value == 'General Ledger' and ws['A3'].font.b
        assert ws['A4'].value == 'From October 1 to 31, 2026'
        assert [ws.cell(6, c).value for c in range(1, 7)] == ['Date', 'Source', 'Particulars', 'Debit', 'Credit',
                                                              'Balance']
        assert ws['C7'].value == 'Opening balance' and ws['F7'].value == 100 and isinstance(ws['F7'].value, (int, float))

    def test_entries_have_numbers_and_a_live_running_balance(self, client, db_session, main_branch, admin_user,
                                                             cash_account, revenue_account):
        _setup(client, db_session, main_branch, admin_user, cash_account, revenue_account)
        ws = _sheet(client, f'&account_id={cash_account.id}')
        assert ws['A8'].value.date() == date(2026, 10, 6) if hasattr(ws['A8'].value, 'date') else False
        assert ws['D8'].value == 100 and not isinstance(ws['D8'].value, str)
        assert ws['F8'].value == '=F7+D8-E8'
        assert ws['F9'].value == '=F8+D9-E9'
        assert ws['D8'].number_format == ws['F8'].number_format and '#,##0.00' in ws['D8'].number_format

    def test_the_closing_row_does_not_count_the_period_twice(self, client, db_session, main_branch, admin_user,
                                                             cash_account, revenue_account):
        _setup(client, db_session, main_branch, admin_user, cash_account, revenue_account)
        ws = _sheet(client, f'&account_id={cash_account.id}')
        assert ws['C10'].value == 'Closing balance'
        assert ws['D10'].value == '=SUM(D8:D9)' and ws['E10'].value == '=SUM(E8:E9)'
        assert ws['F10'].value == '=F9'

    def test_an_account_with_no_entries_closes_on_its_opening(self, client, db_session, main_branch, admin_user,
                                                               cash_account, revenue_account):
        AppSettings.set_setting('company_name', 'X CORP')
        _post_je(main_branch.id, cash_account, revenue_account, date(2026, 9, 30), 'JE-OPEN')
        _login(client, admin_user); _select_branch(client, main_branch.id)
        ws = _sheet(client, f'&account_id={cash_account.id}')
        assert ws['C8'].value == 'Closing balance' and ws['F8'].value == '=F7'


class TestSeveralAccounts:

    def test_one_block_per_account(self, client, db_session, main_branch, admin_user, cash_account,
                                   revenue_account):
        _setup(client, db_session, main_branch, admin_user, cash_account, revenue_account)
        ws = _sheet(client)
        assert ws['A1'].value == 'PHILGEN PACIFIC FOOD PRODUCTS CORPORATION'
        assert ws['A2'].value == 'General Ledger' and ws['A3'].value == 'From October 1 to 31, 2026'
        col_a = [ws.cell(r, 1).value for r in range(1, ws.max_row + 1)]
        col_c = [ws.cell(r, 3).value for r in range(1, ws.max_row + 1)]
        assert f'{cash_account.code} - {cash_account.name}' in col_a
        assert f'{revenue_account.code} - {revenue_account.name}' in col_a
        assert col_a.count('Date') == 2 and col_c.count('Closing balance') == 2
        # the revenue block's running balance refers to its OWN rows
        rev_header = col_a.index(f'{revenue_account.code} - {revenue_account.name}') + 1   # 1-based row
        first_line = rev_header + 3
        assert ws.cell(first_line, 6).value == f'=F{first_line - 1}+D{first_line}-E{first_line}'

    def test_a_cross_month_period_says_both_dates(self, client, db_session, main_branch, admin_user, cash_account,
                                                  revenue_account):
        _setup(client, db_session, main_branch, admin_user, cash_account, revenue_account)
        resp = client.get('/reports/general-ledger/export/excel?start_date=2026-10-01&end_date=2026-11-15'
                          f'&account_id={cash_account.id}')
        ws = openpyxl.load_workbook(io.BytesIO(resp.data)).active
        assert ws['A4'].value == 'From October 1, 2026 to November 15, 2026'
