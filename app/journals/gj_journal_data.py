"""Pure data layer for the columnar General Journal download (the journal vouchers).

No Flask request access here -- callers pass plain values.
"""
import calendar
from decimal import Decimal

from app.journals.legacy_xlsx import (build_legacy_journal_xlsx, journal_row, posted_flag,
                                      text_date)

# Statuses whose lines are in the books. A cancelled voucher is a soft void with no
# reversal entry; a reversed one stays posted beside the reversal that undoes it.
_IN_THE_BOOKS = ('posted', 'reversed')
_MARKER = {'cancelled': '[CANCELLED] ', 'reversed': '[REVERSED] '}


def build_columnar_gj(entries):
    """Pivot journal-voucher lines: one row per entry, a column per account used, by code.

    entries: the vouchers to list (posted, draft, reversed, cancelled), in display order.
    Drafts carry their amounts; a cancelled voucher's row carries none.
    Returns dict: columns, rows.
    """
    accounts_by_id = {}
    rows = []
    for je in entries:
        cells = {}
        if je.status != 'cancelled':
            for line in je.lines.all():
                acct = line.account
                accounts_by_id[acct.id] = acct
                signed = (line.debit_amount or Decimal('0')) - (line.credit_amount or Decimal('0'))
                cells[acct.id] = cells.get(acct.id, Decimal('0')) + signed
        rows.append({'entry': je, 'cells': cells})
    columns = [{'account_id': a.id, 'code': a.code, 'name': a.name}
               for a in sorted(accounts_by_id.values(), key=lambda a: a.code)]
    return {'columns': columns, 'rows': rows}


def build_gj_journal_xlsx(columns, rows, date_from, date_to, company_name, branch_name, filename):
    """Build the General Journal download in the legacy layout: one block per month, each
    totalled on a row labelled with the month's name, which the RIC Working Paper looks up.

    Months run in date order. (The legacy app ran January to December and merged a range's
    two Decembers; CAS keeps each year's month apart.)
    """
    blocks = []
    for r in rows:
        e = r['entry']
        month = calendar.month_name[e.entry_date.month]
        if not blocks or blocks[-1][0] != (e.entry_date.year, e.entry_date.month):
            blocks.append(((e.entry_date.year, e.entry_date.month), month, []))
        particulars = _MARKER.get(e.status, '') + (e.description or '')
        blocks[-1][2].append(journal_row([text_date(e.entry_date), e.entry_number, particulars],
                                         r['cells'], [posted_flag(e.status in _IN_THE_BOOKS), month]))
    if not blocks:
        blocks.append((None, calendar.month_name[date_from.month], []))
    return build_legacy_journal_xlsx(
        'GJ', 'General Journal', ('Date', 'No.', 'Particulars'), columns,
        [(label, out) for _, label, out in blocks], date_from, date_to, company_name,
        branch_name, filename, trailing_labels=('Posted', 'Month'))
