"""Voided CRVs in the Cash Receipts Journal (owner, 6 Nov 2026: "fix the CR journal too",
after bug report #5 on the CD journal). A CRV is voided only from draft and its JE is
deleted, so the journal, which lists JEs, never saw it. Listed like the AP, SI and CD
journals' voided rows: one marked row, no amounts, outside the totals."""
import io
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from openpyxl import load_workbook
import pytest

from app.journals.cr_journal_data import build_columnar_cr, build_cr_journal_xlsx

pytestmark = [pytest.mark.journals, pytest.mark.unit]

AR_ID, WHT_ID, VAT_ID, CASH_ID, SALES_ID = 1, 2, 3, 10, 40


def _line(acct_id, code, name, debit, credit):
    line = MagicMock()
    line.account = MagicMock(id=acct_id, code=code, name=name)
    line.account.name = name
    line.debit_amount = Decimal(str(debit))
    line.credit_amount = Decimal(str(credit))
    return line


def _entry(date_str, number):
    je = MagicMock()
    je.entry_date = date.fromisoformat(date_str)
    je.entry_number = number
    je.reference = number
    je.lines.all.return_value = [_line(CASH_ID, '10101', 'Cash on Hand', 1000, 0),
                                 _line(AR_ID, '11201', 'AR - Trade', 0, 1000)]
    return je


def _ar_line(line_number, invoice_number):
    line = MagicMock()
    line.line_number = line_number
    line.invoice_number = invoice_number
    return line


def _voided_crv(date_str, number, ar_lines=(), customer='Customer A', notes='Collection',
                check_number='0012345'):
    crv = MagicMock()
    crv.crv_date = date.fromisoformat(date_str)
    crv.crv_number = number
    crv.customer_name = customer
    crv.notes = notes
    crv.check_number = check_number
    crv.ar_lines = list(ar_lines)
    return crv


def _build(posted=(), drafts=(), voided=None):
    return build_columnar_cr(
        posted_entries=list(posted), draft_entries=list(drafts),
        ar_account_id=AR_ID, wt_account_id=WHT_ID, output_vat_account_ids={VAT_ID},
        voided_crvs=voided)


def test_voided_crv_is_listed_with_no_amounts_and_not_in_totals():
    voided = _voided_crv('2026-06-02', 'CR-V1')
    matrix = _build(posted=[_entry('2026-06-01', 'CR-1')], voided=[voided])
    row = next(r for r in matrix['rows'] if r['is_voided'])
    assert row['crv'] is voided
    assert (row['entry'], row['cells'], row['is_draft'], row['is_cancelled']) == (None, {}, False, False)
    assert matrix['totals'][CASH_ID] == Decimal('1000')
    assert matrix['balanced'] is True


def test_posted_and_draft_rows_are_not_voided():
    matrix = build_columnar_cr(
        posted_entries=[_entry('2026-06-01', 'CR-1')], draft_entries=[_entry('2026-06-02', 'CR-2')],
        ar_account_id=AR_ID, wt_account_id=WHT_ID, output_vat_account_ids={VAT_ID})
    assert [r['is_voided'] for r in matrix['rows']] == [False, False]


def test_voided_rows_sort_with_the_others_by_date():
    matrix = _build(posted=[_entry('2026-06-01', 'CR-1'), _entry('2026-06-09', 'CR-3')],
                    voided=[_voided_crv('2026-06-05', 'CR-V2')])
    order = [r['crv'].crv_number if r['is_voided'] else r['entry'].entry_number
             for r in matrix['rows']]
    assert order == ['CR-1', 'CR-V2', 'CR-3']


def test_voided_crv_adds_no_column():
    matrix = _build(voided=[_voided_crv('2026-06-02', 'CR-V1')])
    assert matrix['columns'] == []
    assert len(matrix['rows']) == 1


_COLUMNS = [{'account_id': CASH_ID, 'code': '10101', 'name': 'Cash on Hand', 'group': 'cash'},
            {'account_id': AR_ID, 'code': '11201', 'name': 'AR - Trade', 'group': 'ar_applied'}]


def _sheet(app, rows):
    with app.app_context():
        resp = build_cr_journal_xlsx(
            columns=_COLUMNS, rows=rows, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
            company_name='ABC Company', branch_name=None, filename='CR-Journal-2026-06.xlsx',
            identity=lambda e: (e.entry_number, 'SI-9', 'Customer B', 'Posted collection'),
            first_account_ids={CASH_ID, AR_ID})
    return load_workbook(io.BytesIO(resp.get_data())).active


def test_xlsx_voided_crv_row_keeps_its_invoices_and_has_no_amounts(app):
    posted = {'entry': _entry('2026-06-01', 'CR-1'), 'is_draft': False, 'is_cancelled': False,
              'is_voided': False, 'cells': {CASH_ID: Decimal('1000'), AR_ID: Decimal('-1000')}}
    crv = _voided_crv('2026-06-03', 'CR-V1',
                      ar_lines=[_ar_line(2, 'SI-0102'), _ar_line(1, 'SI-0101')])
    voided = {'crv': crv, 'entry': None, 'cells': {}, 'is_draft': False,
              'is_cancelled': False, 'is_voided': True}
    ws = _sheet(app, [posted, voided])
    assert [c.value for c in ws[7]] == ['03-Jun-2026', 'CR-V1', 'SI-0101/SI-0102', 'Customer A',
                                        '[VOIDED] Collection', None, None, 'No']
    assert ws['A9'].value == 'Total' and ws['F9'].value == '=SUM(F5:F8)'
    assert all(c.fill.fill_type is None for c in ws[7])
