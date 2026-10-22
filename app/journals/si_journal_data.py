"""Pure data layer for the columnar Sales Invoice (SI) Journal.

No Flask request access here — callers pass plain dicts/values so these
functions are unit-testable in isolation.
"""
from decimal import Decimal


from app.journals.legacy_xlsx import (build_legacy_journal_xlsx, journal_row,
                                      order_account_columns, posted_flag, text_date)

# resolve_period is shared — import from the AP data layer, do not copy
from app.journals.ap_journal_data import resolve_period  # noqa: F401


def _column_sort_key_si(account, ar_account_id, wht_receivable_id, output_vat_ids):
    """Order: AR (0), Output VAT (1, by code), WHT Receivable (2), others (3, by code)."""
    if account.id == ar_account_id:
        return (0, account.code)
    if account.id in output_vat_ids:
        return (1, account.code)
    if account.id == wht_receivable_id:
        return (2, account.code)
    return (3, account.code)


def _group_si(account_id, ar_account_id, wht_receivable_id, output_vat_ids):
    if account_id == ar_account_id:
        return 'ar'
    if account_id == wht_receivable_id:
        return 'wht_recv'
    if account_id in output_vat_ids:
        return 'output_vat'
    return 'revenue'


def build_columnar_si(posted_entries, draft_entries, ar_account_id,
                      wht_receivable_id, output_vat_ids, voided_invoices=None,
                      draft_amounts=False):
    """Pivot journal-entry lines into a columnar SI matrix.

    Columns are built only from POSTED entries' accounts, ordered:
    AR (debit, 0), Output VAT (credit, 1), WHT Receivable (debit, 2),
    then other/revenue accounts (credit, 3).
    Posted rows carry signed amounts (debit - credit) per account and
    contribute to per-column totals. Draft and voided rows are listed
    with a flag and no amounts, excluded from totals -- except that
    draft_amounts=True (the .xlsx download) pivots drafts like posted rows.

    Returns dict: columns, rows, totals, grand_total, balanced.
    """
    if voided_invoices is None:
        voided_invoices = []
    if output_vat_ids is None:
        output_vat_ids = set()

    accounts_by_id = {}
    totals = {}
    rows = []

    def pivot(je):
        cells = {}
        for line in je.lines.all():
            acct = line.account
            accounts_by_id[acct.id] = acct
            signed = (line.debit_amount or Decimal('0')) - (line.credit_amount or Decimal('0'))
            cells[acct.id] = cells.get(acct.id, Decimal('0')) + signed
            totals[acct.id] = totals.get(acct.id, Decimal('0')) + signed
        return cells

    for je in posted_entries:
        rows.append({'entry': je, 'cells': pivot(je), 'is_draft': False, 'is_voided': False})

    for je in draft_entries:
        cells = pivot(je) if draft_amounts else {}
        rows.append({'entry': je, 'cells': cells, 'is_draft': True, 'is_voided': False})

    for invoice in voided_invoices:
        rows.append({'invoice': invoice, 'entry': None, 'cells': {}, 'is_draft': False, 'is_voided': True})

    ordered = sorted(
        accounts_by_id.values(),
        key=lambda a: _column_sort_key_si(a, ar_account_id, wht_receivable_id, output_vat_ids),
    )
    columns = [{
        'account_id': a.id,
        'code': a.code,
        'name': a.name,
        'group': _group_si(a.id, ar_account_id, wht_receivable_id, output_vat_ids),
    } for a in ordered]

    def _row_sort_key(r):
        if r['is_voided']:
            return (r['invoice'].invoice_date, r['invoice'].invoice_number)
        return (r['entry'].entry_date, r['entry'].entry_number or '')

    rows.sort(key=_row_sort_key)

    grand_total = sum(totals.values(), Decimal('0'))
    return {
        'columns': columns,
        'rows': rows,
        'totals': totals,
        'grand_total': grand_total,
        'balanced': grand_total == Decimal('0'),
    }


def _fmt(value):
    """Render a signed Decimal: credits (negative) in parentheses, blanks for zero/None."""
    if value is None or value == Decimal('0'):
        return ''
    if value < 0:
        return f'({-value:,.2f})'
    return f'{value:,.2f}'


def build_si_journal_xlsx(columns, rows, date_from, date_to, company_name, branch_name,
                          filename, identity, first_account_ids=(), revenue_account_ids=()):
    """Build the SI Journal download in the legacy Sales Journal layout.

    identity(entry) -> (si_no, dr_numbers, customer, particulars)
    first_account_ids: the Cash & Bank and trade receivable accounts, first by code;
    revenue_account_ids: the sales accounts, last by code descending -- the legacy order.
    Voided invoices never reached the books: a marked row with no amounts.
    """
    out = []
    for r in rows:
        if r.get('is_voided'):
            inv = r['invoice']
            out.append(journal_row([text_date(inv.invoice_date), inv.invoice_number, None,
                                    inv.customer_name, '[VOIDED] ' + (inv.notes or '')], {},
                                   [posted_flag(False)]))
            continue
        no, drs, customer, particulars = identity(r['entry'])
        out.append(journal_row([text_date(r['entry'].entry_date), no, drs, customer, particulars],
                               r['cells'], [posted_flag(not r['is_draft'])]))
    return build_legacy_journal_xlsx(
        'SJ', 'Sales Journal', ('Date', 'No.', 'Invoice Number', 'Customer', 'Particulars'),
        order_account_columns(columns, first_ids=first_account_ids, last_ids=revenue_account_ids),
        [('Total', out)], date_from, date_to, company_name, branch_name, filename)
