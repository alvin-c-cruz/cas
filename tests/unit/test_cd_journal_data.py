import io
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from openpyxl import load_workbook
import pytest

from app.journals.cd_journal_data import build_columnar_cd, build_cd_journal_xlsx
from app.journals.legacy_xlsx import period_range_label

pytestmark = [pytest.mark.journals, pytest.mark.unit]


def _mock_line(acct_id, code, name, debit, credit):
    line = MagicMock()
    acct = MagicMock()
    acct.id = acct_id
    acct.code = code
    acct.name = name
    line.account = acct
    line.debit_amount = Decimal(str(debit))
    line.credit_amount = Decimal(str(credit))
    return line


def _mock_entry(date_str, number, lines):
    je = MagicMock()
    je.entry_date = date.fromisoformat(date_str)
    je.entry_number = number
    je.reference = number
    je.lines.all.return_value = lines
    return je


# AP=1, WHT=2, VAT=3, Cash=10, Expense=20
AP_ID = 1
WHT_ID = 2
VAT_ID = 3
CASH_ID = 10
EXPENSE_ID = 20


def _standard_cdv_lines():
    """Dr Expense 10000, Dr Input VAT 1200, Cr WHT 200, Cr AP 0, Cr Cash 11000."""
    return [
        _mock_line(EXPENSE_ID, '60400', 'Rent Expense', 10000, 0),
        _mock_line(VAT_ID,     '10610', 'Input VAT',    1200,  0),
        _mock_line(WHT_ID,     '20301', 'WHT Payable',  0,     200),
        _mock_line(CASH_ID,    '10101', 'Cash on Hand', 0,     11000),
    ]


def test_build_columnar_cd_basic_pivot_and_balance():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    assert matrix['balanced'] is True
    assert matrix['grand_total'] == Decimal('0')
    assert len(matrix['rows']) == 1
    row = matrix['rows'][0]
    assert row['is_draft'] is False
    assert row['is_cancelled'] is False
    # Expense debit: signed = 10000 - 0 = +10000
    assert row['cells'][EXPENSE_ID] == Decimal('10000')
    # Cash credit: signed = 0 - 11000 = -11000
    assert row['cells'][CASH_ID] == Decimal('-11000')


def test_build_columnar_cd_column_ordering():
    """Column order: ap_applied(0), vat(1), expense(2), wht(3), cash(4)."""
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    groups = [c['group'] for c in matrix['columns']]
    # expense before wht and cash; vat before expense
    assert groups.index('vat') < groups.index('expense')
    assert groups.index('expense') < groups.index('wht')
    assert groups.index('wht') < groups.index('cash')


def test_build_columnar_cd_column_groups():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    by_id = {c['account_id']: c['group'] for c in matrix['columns']}
    assert by_id[VAT_ID]     == 'vat'
    assert by_id[EXPENSE_ID] == 'expense'
    assert by_id[WHT_ID]     == 'wht'
    assert by_id[CASH_ID]    == 'cash'


def test_build_columnar_cd_cancelled_ref_is_flagged():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
        cancelled_refs={'CD-2026-06-0001'},
    )
    assert matrix['rows'][0]['is_cancelled'] is True
    # Cancelled rows are still included in totals
    assert matrix['totals'][CASH_ID] == Decimal('-11000')


def test_build_columnar_cd_cancelled_ref_not_in_set_is_not_flagged():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
        cancelled_refs={'CD-2026-06-9999'},
    )
    assert matrix['rows'][0]['is_cancelled'] is False


def test_build_columnar_cd_draft_has_no_cells():
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    draft = _mock_entry('2026-06-02', 'CD-2026-06-0002', _standard_cdv_lines())
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[draft],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID},
    )
    draft_row = next(r for r in matrix['rows'] if r['is_draft'])
    assert draft_row['cells'] == {}


def test_build_columnar_cd_draft_amounts_pivots_draft_lines():
    """The download asks for draft amounts; a draft-only account still gets its column."""
    je = _mock_entry('2026-06-01', 'CD-2026-06-0001', _standard_cdv_lines())
    draft = _mock_entry('2026-06-02', 'CD-2026-06-0002', [
        _mock_line(30, '60500', 'Repairs', 500, 0),
        _mock_line(CASH_ID, '10101', 'Cash on Hand', 0, 500),
    ])
    matrix = build_columnar_cd(
        posted_entries=[je], draft_entries=[draft],
        ap_account_id=AP_ID, wt_account_id=WHT_ID,
        input_vat_account_ids={VAT_ID}, draft_amounts=True,
    )
    draft_row = next(r for r in matrix['rows'] if r['is_draft'])
    assert draft_row['cells'] == {30: Decimal('500'), CASH_ID: Decimal('-500')}
    assert 30 in {c['account_id'] for c in matrix['columns']}
    assert matrix['totals'][CASH_ID] == Decimal('-11500')


# ---------------------------------------------------------------------------
# The download copies the legacy RIC app's Disbursement Journal cell for cell
# (owner, 22 Oct 2026) -- an Excel template reads the row-5 account titles and
# the "Total" row. Spec: app-docs/superpowers/specs/2026-10-22-cd-journal-xlsx-layout-design.md
# ---------------------------------------------------------------------------

AMOUNT_FMT = '#,##0.00; (#,##0.00)'

# Deliberately expense first: the cash account must still come out first.
_COLUMNS = [
    {'account_id': EXPENSE_ID, 'code': '60400', 'name': 'Rent Expense', 'group': 'expense'},
    {'account_id': CASH_ID,    'code': '10101', 'name': 'Cash on Hand', 'group': 'cash'},
]


def _row(cells, is_draft=False, is_cancelled=False, number='CD-2026-06-0001'):
    return {'entry': _mock_entry('2026-06-01', number, []), 'cells': cells,
            'is_draft': is_draft, 'is_cancelled': is_cancelled}


def _sheet(app, rows, branch_name='Main Branch', columns=_COLUMNS,
           date_from=date(2026, 6, 1), date_to=date(2026, 6, 30)):
    with app.app_context():
        resp = build_cd_journal_xlsx(
            columns=columns, rows=rows, date_from=date_from, date_to=date_to,
            company_name='ABC Company', branch_name=branch_name,
            filename='CD-Journal-2026-06.xlsx',
            identity=lambda e: (e.entry_number, '000123', 'Vendor A', 'Rent\nfor June'),
            cash_account_ids={CASH_ID},
        )
    assert resp.headers['Content-Type'].startswith('application/vnd.openxmlformats')
    assert 'CD-Journal-2026-06.xlsx' in resp.headers['Content-Disposition']
    return load_workbook(io.BytesIO(resp.get_data())).active


def _style(side):
    return side.style if side is not None else None


def _thin_box(cell):
    b = cell.border
    return tuple(_style(s) for s in (b.left, b.right, b.top, b.bottom)) == ('thin',) * 4


_POSTED = _row({EXPENSE_ID: Decimal('10000'), CASH_ID: Decimal('-10000')})


def test_xlsx_title_rows(app):
    ws = _sheet(app, [_POSTED])
    assert ws.title == 'CDJ'
    assert ws['A1'].value == 'ABC Company'
    assert (ws['A1'].font.sz, ws['A1'].font.b) == (14, True)
    assert ws['A2'].value == 'Disbursement Journal - Main Branch'
    assert ws['A3'].value == 'From June 01 to 30, 2026'
    for ref in ('A2', 'A3'):
        assert (ws[ref].font.sz, ws[ref].font.b) == (10, True)
    assert all(c.value is None for c in ws[4])


def test_xlsx_a2_has_no_branch_suffix_for_a_single_branch(app):
    ws = _sheet(app, [_POSTED], branch_name=None)
    assert ws['A2'].value == 'Disbursement Journal'


def test_xlsx_account_titles_sit_in_row_5_cash_first(app):
    ws = _sheet(app, [_POSTED])
    assert [c.value for c in ws[5]] == ['Date', 'No.', 'Check Number', 'Vendor', 'Particulars',
                                        'Cash on Hand', 'Rent Expense', 'Posted']
    for c in ws[5]:
        assert (c.font.sz, c.font.b) == (10, True), c.coordinate
        assert (c.alignment.horizontal, c.alignment.wrap_text) == ('center', True), c.coordinate
        assert _thin_box(c), c.coordinate
    assert ws.row_dimensions[5].height is None


def test_xlsx_data_row_cells(app):
    ws = _sheet(app, [_POSTED])
    a, b, c, d, e, f, g, h = ws[6]
    assert a.value == '01-Jun-2026'                       # text date, kept (owner)
    assert (a.alignment.horizontal, a.alignment.vertical, a.number_format) == ('center', 'top', 'yyyy-mmm-dd')
    for cell in (b, c):
        assert (cell.alignment.horizontal, cell.alignment.vertical) == ('center', 'top')
    assert (b.value, c.value, d.value) == ('CD-2026-06-0001', '000123', 'Vendor A')
    assert e.value == 'Rent\nfor June'
    for cell in (d, e):
        assert (cell.alignment.horizontal, cell.alignment.vertical, cell.alignment.wrap_text) == ('left', 'top', True)
    assert (f.value, g.value) == (-10000, 10000)
    for cell in (f, g):
        assert (cell.alignment.horizontal, cell.alignment.vertical, cell.number_format) == ('right', 'top', AMOUNT_FMT)
    assert h.value == 'Yes'
    assert (h.alignment.horizontal, h.alignment.vertical, h.alignment.wrap_text) == ('center', 'center', True)
    for cell in ws[6]:
        assert (cell.font.sz, cell.font.b) == (10, False), cell.coordinate
        assert _thin_box(cell), cell.coordinate
        assert cell.fill.fill_type is None, cell.coordinate


def test_xlsx_total_row(app):
    ws = _sheet(app, [_POSTED])
    assert all(c.value is None for c in ws[7])            # one empty row
    assert ws['A8'].value == 'Total'
    assert (ws['A8'].font.sz, ws['A8'].font.b) == (10, True)
    assert _style(ws['A8'].border.bottom) is None
    assert [ws[f'{col}8'].value for col in 'BCDE'] == [None] * 4
    assert ws['F8'].value == '=SUM(F5:F7)'
    assert ws['G8'].value == '=SUM(G5:G7)'
    assert ws['H8'].value is None                         # no total under Posted
    for ref in ('F8', 'G8'):
        cell = ws[ref]
        assert (cell.font.sz, cell.font.b) == (10, False)
        assert (cell.alignment.horizontal, cell.number_format) == ('right', AMOUNT_FMT)
        assert tuple(_style(s) for s in (cell.border.bottom, cell.border.left, cell.border.top)) == ('double', None, None)
    labels = [c.coordinate for row in ws.iter_rows() for c in row if c.value == 'Total']
    assert labels == ['A8']


def test_xlsx_column_widths_and_no_sheet_extras(app):
    ws = _sheet(app, [_POSTED])
    widths = {col: ws.column_dimensions[col].width for col in 'ABCDEFGH'}
    assert widths == {'A': 12, 'B': 10, 'C': 12, 'D': 20, 'E': 25, 'F': 14, 'G': 14, 'H': 7}
    assert ws.freeze_panes is None
    assert not ws.merged_cells.ranges


def test_xlsx_draft_row_carries_amounts_and_posted_no(app):
    draft = _row({EXPENSE_ID: Decimal('500'), CASH_ID: Decimal('-500')}, is_draft=True,
                 number='CD-2026-06-0002')
    ws = _sheet(app, [_POSTED, draft])
    row = ws[7]
    assert row[1].value == 'CD-2026-06-0002'
    assert row[4].value == 'Rent\nfor June'               # no [DRAFT] prefix
    assert (row[5].value, row[6].value, row[7].value) == (-500, 500, 'No')
    assert all(c.fill.fill_type is None for c in row)
    assert ws['A9'].value == 'Total' and ws['F9'].value == '=SUM(F5:F8)'


def test_xlsx_cancelled_row_is_marked_but_not_filled(app):
    ws = _sheet(app, [_row({CASH_ID: Decimal('-10000')}, is_cancelled=True)])
    row = ws[6]
    assert row[4].value == '[CANCELLED] Rent\nfor June'
    assert row[7].value == 'Yes'
    assert all(c.fill.fill_type is None for c in row)


@pytest.mark.parametrize('date_from, date_to, label', [
    (date(2026, 9, 1), date(2026, 9, 30), 'From September 01 to 30, 2026'),
    (date(2026, 9, 1), date(2026, 10, 31), 'From September 01 to October 31, 2026'),
    (date(2025, 12, 1), date(2026, 1, 31), 'From December 01, 2025 to January 31, 2026'),
    (date(2026, 9, 1), date(2026, 9, 1), 'For September 01, 2026'),
])
def test_period_range_label_words_the_range_as_alvinltv_does(date_from, date_to, label):
    assert period_range_label(date_from, date_to) == label
