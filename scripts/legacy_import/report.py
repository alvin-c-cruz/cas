"""The import report.

ASCII-only: PowerShell 5.1 reads a BOM-less script as cp1252, and this text goes
straight to the console.

Nothing is silently dropped. Every header skipped for having no lines, every
duplicated document number, and the petty-cash count (a book CAS has no module
for) is stated -- a silent cap reads as "covered everything" when it did not.
"""
from decimal import Decimal

RULE = '-' * 78


def _money(value):
    return f'{value:,.2f}'


def render(client, per_book, skipped, duplicates, master, grand, tie_issues, committed):
    out = []
    add = out.append

    add(RULE)
    add(f'LEGACY GL REPLAY -- client: {client.slug}')
    add(f'source: {client.legacy_db}')
    add(RULE)

    add('')
    add('Documents by book')
    add(f'  {"book":22s} {"prefix":6s} {"branch":6s} {"imported":>9s} {"lines":>7s} {"skipped":>8s}')
    total_docs = total_lines = total_skipped = 0
    for row in per_book:
        add(f'  {row["book"]:22s} {row["prefix"]:6s} {row["branch"]:6s} '
            f'{row["documents"]:9d} {row["lines"]:7d} {row["skipped"]:8d}')
        total_docs += row['documents']
        total_lines += row['lines']
        total_skipped += row['skipped']
    add(f'  {"TOTAL":22s} {"":6s} {"":6s} {total_docs:9d} {total_lines:7d} {total_skipped:8d}')

    add('')
    add('Skipped headers (zero entry lines -- an empty journal entry carries no information)')
    add(f'  {total_skipped} header(s) skipped')
    for book, ids in sorted(skipped.items()):
        if ids:
            shown = ', '.join(str(i) for i in ids[:10])
            more = f' ... +{len(ids) - 10} more' if len(ids) > 10 else ''
            add(f'  {book}: {len(ids)} -- legacy ids {shown}{more}')

    add('')
    add('Duplicate document numbers in the SOURCE (data-quality defects in the client book)')
    if not duplicates:
        add('  none')
    else:
        add(f'  {len(duplicates)} number(s) used more than once; the later legacy id is suffixed')
        for (prefix, number), ids in sorted(duplicates.items()):
            add(f'  {prefix}-{number}: legacy ids {ids}')

    add('')
    add('Master data')
    add(f'  customers: {master.customers_created} created, {master.customers_existing} already present')
    add(f'  vendors  : {master.vendors_created} created, {master.vendors_existing} already present')

    add('')
    add('Trial balance')
    debit, credit = grand
    add(f'  debits : {_money(debit)}')
    add(f'  credits: {_money(credit)}')
    add(f'  balanced: {"YES" if debit == credit else "NO"}')

    add('')
    add('Tie-out (legacy books vs CAS, per account and per account-month)')
    if not tie_issues:
        add('  PASS -- every account and every period ties exactly')
    else:
        from scripts.legacy_import.tieout import format_issues
        add(f'  FAIL -- {len(tie_issues)} discrepancy(ies)')
        add(format_issues(tie_issues))

    add('')
    add(RULE)
    add('COMMITTED' if committed else 'DRY RUN -- nothing written. Re-run with --commit.')
    add(RULE)
    return '\n'.join(out)


def petty_cash_note(per_book):
    for row in per_book:
        if row['book'] == 'petty_cash' and row['documents']:
            return (f'NOTE: {row["documents"]} petty-cash documents were replayed as journal '
                    f'vouchers -- CAS has no petty-cash module.')
    return None
