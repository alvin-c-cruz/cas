from datetime import date, datetime
from decimal import Decimal
from app.journals.ap_journal_data import resolve_period, _fmt


def test_resolve_period_defaults_to_given_month():
    p = resolve_period({}, today=date(2026, 6, 13))
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)
    assert p['date_to'] == date(2026, 6, 30)
    assert p['label'] == 'For the month of June 2026'


def test_resolve_period_explicit_month():
    p = resolve_period({'mode': 'month', 'year': '2026', 'month': '2'}, today=date(2026, 6, 13))
    assert p['date_from'] == date(2026, 2, 1)
    assert p['date_to'] == date(2026, 2, 28)  # 2026 not a leap year
    assert p['label'] == 'For the month of February 2026'


def test_resolve_period_custom_range():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-01-15', 'date_to': '2026-03-10'},
        today=date(2026, 6, 13),
    )
    assert p['mode'] == 'custom'
    assert p['date_from'] == date(2026, 1, 15)
    assert p['date_to'] == date(2026, 3, 10)
    assert p['label'] == 'From January 15, 2026 to March 10, 2026'  # no leading zero on day


def test_resolve_period_custom_with_bad_dates_falls_back_to_month():
    p = resolve_period({'mode': 'custom', 'date_from': 'bad', 'date_to': ''}, today=date(2026, 6, 13))
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)


def test_resolve_period_custom_label_no_leading_zero():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-03-05', 'date_to': '2026-03-09'},
        today=date(2026, 6, 13),
    )
    assert p['label'] == 'From March 5, 2026 to March 9, 2026'


def test_resolve_period_custom_inverted_falls_back_to_month():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-06-30', 'date_to': '2026-01-01'},
        today=date(2026, 6, 13),
    )
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)


def test__fmt():
    assert _fmt(None) == ''
    assert _fmt(Decimal('0')) == ''
    assert _fmt(Decimal('5000')) == '5,000.00'
    assert _fmt(Decimal('-5000')) == '(5,000.00)'
    assert _fmt(Decimal('-0.01')) == '(0.01)'


import io
from openpyxl import load_workbook
from app.journals.ap_journal_data import build_ap_journal_xlsx


def _fake_entry(date_str, number, invoice, vendor, notes):
    class E: pass
    e = E()
    e.entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    e.reference = number
    e._invoice = invoice
    e._vendor = vendor
    e._notes = notes
    return e


def test_build_ap_journal_xlsx_has_headers_and_total_row(app):
    columns = [
        {'account_id': 1, 'code': '20101', 'name': 'Accounts Payable - Trade', 'group': 'ap'},
        {'account_id': 2, 'code': '60400', 'name': 'Rent Expense', 'group': 'other'},
    ]
    rows = [{
        'entry': _fake_entry('2026-06-01', 'AP-2026-06-0001', 'SI-1', 'Vendor A', 'Rent'),
        'cells': {1: Decimal('-5000'), 2: Decimal('5000')},
        'is_draft': False,
    }]
    totals = {1: Decimal('-5000'), 2: Decimal('5000')}
    with app.app_context():
        resp = build_ap_journal_xlsx(
            columns=columns, rows=rows, totals=totals,
            period_label='For the month of June 2026',
            company_name='ABC Company', branch_name='Main Branch',
            filename='AP-Journal-2026-06.xlsx',
            identity=lambda e: (e.reference, e._invoice, e._vendor, e._notes))
    assert resp.headers['Content-Type'].startswith('application/vnd.openxmlformats')
    assert 'AP-Journal-2026-06.xlsx' in resp.headers['Content-Disposition']

    wb = load_workbook(io.BytesIO(resp.get_data()))
    ws = wb.active
    all_text = ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert 'Accounts Payable Journal' in all_text
    assert 'Accounts Payable - Trade' in all_text
    assert 'Rent Expense' in all_text
    assert 'TOTAL' in all_text

    fixed = ['Date', 'No.', 'Invoice No.', 'Vendor', 'Particulars']
    header = fixed + [c['name'] for c in columns]

    # verify parenthesised credit and positive debit in data row
    # header is row 5 (rows 1-4 are company header, journal title, period, blank)
    # data row is row 6
    data_row = [ws.cell(row=6, column=i).value for i in range(1, len(header) + 1)]
    assert '(5,000.00)' in data_row   # AP column (credit → negative → parenthesised)
    assert '5,000.00' in data_row      # Rent Expense column (debit → positive)

    # TOTAL row is row 7
    total_row = [ws.cell(row=7, column=i).value for i in range(1, len(header) + 1)]
    assert total_row[0] == 'TOTAL'
    assert '(5,000.00)' in total_row
    assert '5,000.00' in total_row
