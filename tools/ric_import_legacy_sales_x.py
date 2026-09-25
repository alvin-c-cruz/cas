"""Copy RIC's legacy "Sales Extra" journal into CAS as Sales Invoices, through the app's own views.

Source: the legacy accounting app's SQLite (alvinltv account, table sales_x + sales_entry_x).
Target: this CAS instance (whatever SQLALCHEMY_DATABASE_URI / .env points at), branch EXTRA.

Every document goes through the same two HTTP handlers the screen uses -- POST
/sales-invoices/create then POST /sales-invoices/<id>/post -- via Flask's test client with a
logged-in admin session, so numbering checks, line parsing, totals, the journal entry, audit
rows and validation are exactly what a hand entry produces. Nothing is written with raw SQL.

Rules (owner, 2026-09-13):
  * invoice_number  = legacy sales_number (e.g. 0013935); also stored in reference
  * invoice_date    = legacy record_date; due_date = +60 days; payment_terms = Net 60
  * one line per revenue leg, description blank, amount = the credit, no VAT, no WHT
  * notes           = the copy-source sentence (CAS requires particulars)
  * documents whose number already exists in CAS are skipped (idempotent re-runs)
  * anything that is not exactly Dr AR-Trade / Cr revenue is reported and skipped

Usage (from the cas/ directory, with the .env of the target company):
    python tools/ric_import_legacy_sales_x.py --from 2026-01-01 --to 2026-01-31 --dry-run
    python tools/ric_import_legacy_sales_x.py --from 2026-01-01 --to 2026-01-31
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / '.env')

LEGACY_DB = Path(r'C:\envs\erp-workspace\clients\ric\legacy-apps\accounting\instance\data.db')
LEGACY_AR = '11201'
EXTRA_BRANCH_CODE = 'EXTRA'
NET_DAYS = 60

# legacy customer_name -> CAS customer name (exact CAS spelling)
CUSTOMER_MAP = {
    'FH COLORS & COATINGS CORP.': 'FH COLORS & COATINGS CORP.',
    'VI-CHEM CORPORATION': 'VI - CHEM CORPORATION',
    'SYCWIN COATING AND WIRES INC': 'SYCWIN COATING & WIRES INC.',
    'MARCH RESOURCES': 'MARCH RESOURCES',
    'RJRL ENTERPRISE': 'RJRL ENTERPRISE',
}
# legacy revenue account_number -> CAS account code
ACCOUNT_MAP = {
    '41101': '411001',   # SALES - Tincan
    '41201': '411005',   # SALES - Plastic
    '41105': '411002',   # SALES RETURNS & ALLOWANCES - TINCAN
    '41205': '411006',   # SALES RETURNS & ALLOWANCES - PLASTIC
    '42101': '411009',   # SCRAP SALES-TINCAN
    '42102': '411010',   # SCRAP SALES-PLASTIC
}


def q2(x):
    return Decimal(str(x or 0)).quantize(Decimal('0.01'))


def read_legacy(date_from, date_to):
    """[{number, date, customer, legs:[(acct_no, title, debit, credit)]}] ordered by number."""
    c = sqlite3.connect(LEGACY_DB)
    acct = {r[0]: (str(r[1]), r[2]) for r in c.execute('select id, account_number, account_title from accounts')}
    cust = {r[0]: r[1] for r in c.execute('select id, customer_name from customers')}
    docs = []
    for sid, num, dt, cid in c.execute(
            'select id, sales_number, record_date, customer_id from sales_x '
            'where record_date >= ? and record_date < ? order by sales_number',
            (date_from.isoformat(), (date_to + timedelta(days=1)).isoformat())):
        legs = [(acct[a][0], acct[a][1], q2(d), q2(cr)) for a, d, cr in
                c.execute('select account_id, debit, credit from sales_entry_x where sales_x_id = ?', (sid,))]
        docs.append({'number': str(num).strip(), 'date': datetime.fromisoformat(str(dt)).date(),
                     'customer': cust.get(cid, f'#{cid}'), 'legs': legs})
    return docs


def plan_doc(doc, cas_customers, cas_accounts):
    """Return (form_payload, expected_legs) or raise ValueError with the reason to skip."""
    ar = [l for l in doc['legs'] if l[0] == LEGACY_AR]
    rev = [l for l in doc['legs'] if l[0].startswith('4')]
    other = [l for l in doc['legs'] if l not in ar and l not in rev]
    if other or len(ar) != 1 or not rev:
        raise ValueError(f"legs are not Dr AR / Cr revenue: {[(l[0], str(l[2]), str(l[3])) for l in doc['legs']]}")
    total = sum((l[3] - l[2] for l in rev), Decimal('0.00'))
    if total <= 0 or ar[0][2] != total:
        raise ValueError(f'AR debit {ar[0][2]} does not equal revenue {total}')
    cname = CUSTOMER_MAP.get(doc['customer'])
    if cname is None or cname not in cas_customers:
        raise ValueError(f"customer {doc['customer']!r} has no CAS mapping")
    lines = []
    for acct_no, title, d, cr in rev:
        code = ACCOUNT_MAP.get(acct_no)
        if code is None or code not in cas_accounts:
            raise ValueError(f'revenue account {acct_no} {title} has no CAS mapping')
        lines.append({'description': '', 'amount': str(cr - d), 'vat_category': '', 'wt_id': '',
                      'account_id': str(cas_accounts[code])})
    legs_text = ' / '.join(f'Cr {a} {t} {cr - d:,.2f}' for a, t, d, cr in rev)
    payload = {
        'invoice_number': doc['number'],
        'invoice_date': doc['date'].isoformat(),
        'due_date': (doc['date'] + timedelta(days=NET_DAYS)).isoformat(),
        'customer_id': str(cas_customers[cname]),
        'payment_terms': f'Net {NET_DAYS}',
        'reference': doc['number'],
        'salesperson_id': '0',
        'customer_po_number': '', 'customer_po_date': '',
        'ar_trade_account_id': '', 'creditable_wht_account_id': '',
        'notes': (f"Copied from legacy Sales Extra {doc['number']} (alvinltv.pythonanywhere.com), "
                  f"record date {doc['date'].strftime('%m/%d/%Y')}, {doc['customer']}, "
                  f"Dr {LEGACY_AR} AR-Trade / {legs_text}"),
        'line_items': json.dumps(lines),
        'source_dr_ids': '[]',
    }
    return payload, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='date_from', required=True, type=date.fromisoformat)
    ap.add_argument('--to', dest='date_to', required=True, type=date.fromisoformat)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    from app import create_app, db
    from app.branches.models import Branch
    from app.customers.models import Customer
    from app.accounts.models import Account
    from app.sales_invoices.models import SalesInvoice
    from app.users.models import User
    from app.journal_entries.models import JournalEntryLine

    app = create_app(os.environ.get('FLASK_ENV', 'development'))
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['RATELIMIT_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        print('database:', app.config['SQLALCHEMY_DATABASE_URI'])
        branch = Branch.query.filter_by(code=EXTRA_BRANCH_CODE).one()
        admin = User.query.filter_by(role='admin', is_active=True).order_by(User.id).first()
        cas_customers = {c.name: c.id for c in Customer.query.filter_by(is_active=True).all()}
        cas_accounts = {a.code: a.id for a in Account.query.filter_by(is_active=True).all()}
        existing = {n for (n,) in db.session.query(SalesInvoice.invoice_number).all()}

        docs = read_legacy(args.date_from, args.date_to)
        todo, skipped = [], []
        for doc in docs:
            if doc['number'] in existing:
                skipped.append((doc['number'], 'already in CAS'))
                continue
            try:
                todo.append((doc, *plan_doc(doc, cas_customers, cas_accounts)))
            except ValueError as exc:
                skipped.append((doc['number'], str(exc)))

        print(f"legacy docs {args.date_from}..{args.date_to}: {len(docs)}; to create: {len(todo)}; skipped: {len(skipped)}")
        for n, why in skipped:
            print(f'  skip {n}: {why}')
        planned_total = sum(t for _, _, t in todo)
        print(f'planned total (net): {planned_total:,.2f}')
        if args.dry_run:
            for doc, payload, total in todo[:5]:
                print('  e.g.', payload['invoice_number'], payload['invoice_date'], doc['customer'], f'{total:,.2f}')
            print('dry run: nothing written')
            return

        client = app.test_client()
        with client.session_transaction() as s:
            s['_user_id'] = str(admin.id)
            s['_fresh'] = True
            s['selected_branch_id'] = branch.id

        created, failed = [], []
        for doc, payload, total in todo:
            r = client.post('/sales-invoices/create', data=payload, follow_redirects=False)
            loc = r.headers.get('Location', '')
            if r.status_code != 302 or '/sales-invoices/' not in loc or loc.endswith('/create'):
                failed.append((doc['number'], f'create -> {r.status_code} {loc}'))
                continue
            inv = SalesInvoice.query.filter_by(invoice_number=doc['number']).one()
            r2 = client.post(f'/sales-invoices/{inv.id}/post', follow_redirects=False)
            db.session.expire_all()
            inv = db.session.get(SalesInvoice, inv.id)
            je = inv.journal_entry
            legs = {(l.account.code, q2(l.debit_amount), q2(l.credit_amount))
                    for l in JournalEntryLine.query.filter_by(entry_id=je.id).all()} if je else set()
            expect = {('112001', total, Decimal('0.00'))} | {
                (ACCOUNT_MAP[a], Decimal('0.00'), cr - d) for a, t, d, cr in doc['legs'] if a.startswith('4')}
            ok = (r2.status_code == 302 and inv.status == 'posted' and je is not None
                  and je.status == 'posted' and legs == expect and q2(inv.total_amount) == total
                  and q2(inv.vat_amount) == 0 and q2(inv.withholding_tax_amount) == 0)
            (created if ok else failed).append((doc['number'], f'SI id {inv.id}, {je.entry_number if je else "no JE"}, {total:,.2f}' if ok
                                                  else f'post -> {r2.status_code}, status {inv.status}, legs {legs}'))

        print(f'\ncreated+posted: {len(created)}  failed: {len(failed)}')
        for n, info in failed:
            print(f'  FAIL {n}: {info}')
        done_total = sum(q2(SalesInvoice.query.filter_by(invoice_number=n).one().total_amount) for n, _ in created)
        print(f'posted total (net): {done_total:,.2f}  vs planned {planned_total:,.2f}')


if __name__ == '__main__':
    main()
