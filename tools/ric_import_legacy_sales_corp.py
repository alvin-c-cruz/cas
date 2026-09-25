"""Re-create RIC's CORP sales invoices in CAS from the two legacy apps, through CAS's own views.

Spec: docs/design/2026-09-14-ric-corp-january-rebuild-design.md

Sources (SQLite copies downloaded from PythonAnywhere):
  * invoice app  (michellecaliwag): invoice + invoice_entry -> number, date, customer, PO, DR,
    salesman, product, quantity, unit price.            --invoice-db
  * accounting app (alvinltv):      sales + sales_entry  -> the entry's legs (Dr AR, Dr CWT,
    Cr Sales 41101/41201, Cr Output Tax) per invoice.   --accounting-db
  * operations app (rowell_indutrial_flask): delivery_receipt -> the DR list for check 1.

Every document goes through POST /sales-invoices/create then POST /sales-invoices/<id>/post via
the test client with an admin session on branch CORP. Products missing by EXACT legacy name are
created first through POST /products/create. Cancelled numbers become voided drafts. No raw SQL
writes anywhere.

Usage (from cas/, with the target company's .env / SQLALCHEMY_DATABASE_URI):
    python tools/ric_import_legacy_sales_corp.py --from 2026-01-01 --to 2026-01-31 --dry-run
    python tools/ric_import_legacy_sales_corp.py --from 2026-01-01 --to 2026-01-31
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / '.env')

LEGACY = Path(r'C:\envs\erp-workspace\clients\ric\legacy-apps')
DEFAULT_INVOICE_DB = LEGACY / 'sales_invoice' / 'instance' / 'data.db'
DEFAULT_ACCOUNTING_DB = LEGACY / 'accounting' / 'instance' / 'data.db'
DEFAULT_OPS_DB = LEGACY / 'rowell_indutrial_flask' / 'instance' / 'ric_data.db'

BRANCH_CODE = 'CORP'
NET_DAYS = 60
VAT_CATEGORY = 'V12'
WHT_CODE = 'WC158'
CANCELLED_CUSTOMER = 'CANCELLED'
CANCEL_REASON = 'Cancelled in legacy invoice series (invoice app)'
CUSTOMER_MAP = {  # legacy invoice-app name (trimmed) -> CAS customer name
    'DAVIES PAINTS PHILIPPINES': 'DAVIES PAINTS PHILIPPINES INC.',
}
SALES_ACCOUNT_BY_LEGACY = {'41101': '411001', '41201': '411005'}      # accounting Cr leg -> CAS
SALES_ACCOUNT_BY_CATEGORY = {'TINCAN': '411001', 'PLASTIC': '411005'}  # fallback when no entry
CATEGORY_BY_LEGACY = {'41101': 'TINCAN', '41201': 'PLASTIC'}
LEGACY_AR, LEGACY_CWT, LEGACY_OUTPUT = '11201', '12501', '22103-1'
SALESPERSON_MAP = {'CORAZON EMBALSADO': ('EMP-001',), 'EUGENE GO': ('EMP-0002',),
                   'JING HIPOLITO': ('EMP-0003',)}
NEW_EMPLOYEES = [{'employee_no': 'EMP-0003', 'first_name': 'JING', 'last_name': 'HIPOLITO'}]

CENT = Decimal('0.01')


def q2(x):
    return Decimal(str(x or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def digits(s):
    return re.sub(r'\D', '', str(s or '')).lstrip('0')


# ----------------------------------------------------------------------------- sources
def read_invoice_app(path, d_from, d_to):
    c = sqlite3.connect(path)
    cust = {r[0]: (r[1] or '').strip() for r in c.execute('select id, name from customer')}
    prod = {r[0]: (r[1] or '').strip() for r in c.execute('select id, name from product')}
    docs = []
    for iid, cid, num, dt, so, dr, sm in c.execute(
            'select id, customer_id, invoice_number, record_date, so_number, dr_number, sales_man '
            'from invoice where record_date >= ? and record_date < ? order by invoice_number',
            (d_from.isoformat(), (d_to + timedelta(days=1)).isoformat())):
        lines = [(prod[p], q2(q), q2(u)) for p, q, u in
                 c.execute('select product_id, quantity, unit_price from invoice_entry where invoice_id = ?', (iid,))]
        docs.append({'number': str(num).strip(), 'date': datetime.fromisoformat(str(dt)).date(),
                     'customer': cust.get(cid, ''), 'po': (so or '').strip(), 'dr': (dr or '').strip(),
                     'salesman': (sm or '').strip().upper(), 'lines': lines,
                     'gross': sum((q * u for _, q, u in lines), Decimal('0.00')).quantize(CENT)})
    return docs


def read_accounting_app(path, d_from, d_to):
    """{invoice number digits: {'ar','cwt','sales','output','sales_acct'}} from the CORP sales journal."""
    c = sqlite3.connect(path)
    acct = {r[0]: str(r[1]) for r in c.execute('select id, account_number from accounts')}
    out = {}
    for sid, num, dt in c.execute('select id, sales_number, record_date from sales where record_date >= ? and record_date < ?',
                                  (d_from.isoformat(), (d_to + timedelta(days=1)).isoformat())):
        legs = defaultdict(lambda: Decimal('0.00')); sales_acct = None
        for a, d, cr in c.execute('select account_id, debit, credit from sales_entry where sales_id = ?', (sid,)):
            code = acct.get(a, '?')
            if code.startswith('4'):
                legs['sales'] += q2(cr) - q2(d); sales_acct = code
            elif code == LEGACY_AR:
                legs['ar'] += q2(d) - q2(cr)
            elif code == LEGACY_CWT:
                legs['cwt'] += q2(d) - q2(cr)
            elif code.startswith('22103'):
                legs['output'] += q2(cr) - q2(d)
            else:
                legs['other'] += q2(d) - q2(cr)
        out[digits(num)] = {**legs, 'sales_acct': sales_acct, 'date': str(dt)[:10]}
    return out


def read_accounting_xlsx(path, d_from, d_to):
    """Same shape as read_accounting_app, from the app's 'Download Journal' export (Sales Journal):
    Date | Invoice No. | DR No. | Customer | Particulars | AR | CWT | OUTPUT TAX | SALES - Plastic | SALES - Tincan."""
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True).active
    hdr = None; out = {}
    for row in ws.iter_rows(values_only=True):
        if hdr is None:
            if row and row[0] == 'Date': hdr = [str(h or '').strip().upper() for h in row]
            continue
        if not row or not hasattr(row[0], 'year'): continue
        rec = dict(zip(hdr, row)); d = row[0].date() if hasattr(row[0], 'date') else row[0]
        if d < d_from or d > d_to: continue
        plastic, tincan = q2(rec.get('SALES - PLASTIC')), q2(rec.get('SALES - TINCAN'))
        out[digits(rec.get('INVOICE NO.'))] = {
            'ar': q2(rec.get('ACCOUNTS RECEIVABLE-TRADE')), 'cwt': q2(rec.get('CREDITABLE WITHHOLDING TAX')),
            'output': -q2(rec.get('OUTPUT TAX')), 'sales': -(plastic + tincan), 'other': Decimal('0.00'),
            'sales_acct': '41201' if plastic else ('41101' if tincan else None), 'date': d.isoformat(),
            'dr': digits(rec.get('DR NO.')), 'customer': (rec.get('CUSTOMER') or '').strip()}
    return out


def read_ops_app(path, d_from, d_to):
    c = sqlite3.connect(path)
    live, cancelled = set(), set()
    for n, canc in c.execute('select delivery_receipt_number, cancelled from delivery_receipt '
                             'where record_date >= ? and record_date < ?',
                             (d_from.isoformat(), (d_to + timedelta(days=1)).isoformat())):
        (cancelled if canc else live).add(digits(n))
    return live, cancelled


# ----------------------------------------------------------------------------- planning
def expected_legs(gross):
    """CAS's own arithmetic for a V12 + WC158 line set: net, VAT, CWT, AR."""
    net = (gross / Decimal('1.12')).quantize(CENT, rounding=ROUND_HALF_UP)
    vat = gross - net
    cwt = (net * Decimal('0.01')).quantize(CENT, rounding=ROUND_HALF_UP)
    return {'sales': net, 'output': vat, 'cwt': cwt, 'ar': gross - cwt}


def plan(docs, entries, ops_live, ops_cancelled, cas):
    """Classify every doc: ('post', payload, expect) | ('void', payload) | ('skip', reason) | ('hold', reason)."""
    dr_users = Counter(digits(d['dr']) for d in docs if d['customer'] != CANCELLED_CUSTOMER)
    out = []
    for d in docs:
        n = d['number']
        if n in cas['existing']:
            out.append((n, 'skip', 'already in CAS', None)); continue
        if d['customer'] == CANCELLED_CUSTOMER:
            out.append((n, 'void', None, {
                'invoice_number': n, 'invoice_date': d['date'].isoformat(),
                'due_date': (d['date'] + timedelta(days=NET_DAYS)).isoformat(),
                'customer_id': str(cas['customers'][CANCELLED_CUSTOMER]), 'payment_terms': f'Net {NET_DAYS}',
                'reference': '', 'salesperson_id': '0', 'customer_po_number': '', 'customer_po_date': '',
                'ar_trade_account_id': '', 'creditable_wht_account_id': '',
                'notes': 'Cancelled in legacy invoice series',
                'line_items': json.dumps([{'description': '', 'amount': '0.01', 'vat_category': '', 'wt_id': '',
                                           'account_id': str(cas['accounts']['411001'])}]),
                'source_dr_ids': '[]'}))
            continue
        problems = []
        dr = digits(d['dr'])
        if not dr: problems.append('no DR number')
        elif dr in ops_cancelled: problems.append(f'DR {dr} is cancelled in the operations app')
        elif dr not in ops_live: problems.append(f'DR {dr} not in the operations app for this period')
        if dr_users[dr] > 1: problems.append(f'DR {dr} used by {dr_users[dr]} invoices')
        if not d['lines']: problems.append('no lines')
        for name, qty, price in d['lines']:
            if name not in cas['products'] and name not in cas['new_products']:
                problems.append(f'product not in CAS: {name!r}')
            if qty <= 0 or price <= 0: problems.append(f'qty/price not positive on {name!r}')
        cname = CUSTOMER_MAP.get(d['customer'], d['customer'])
        if cname not in cas['customers']: problems.append(f'customer not in CAS: {d["customer"]!r}')
        exp = expected_legs(d['gross'])
        e = entries.get(digits(n))
        if entries and e is None:
            problems.append('no entry in the accounting app')
        elif e is not None:
            for k in ('sales', 'output', 'cwt', 'ar'):
                if q2(e.get(k)) != exp[k]:
                    problems.append(f'accounting {k} {q2(e.get(k))} != CAS {exp[k]}')
            if q2(e.get('other')): problems.append(f'accounting entry has other legs {e["other"]}')
            if e['date'] != d['date'].isoformat(): problems.append(f'accounting date {e["date"]} != invoice {d["date"]}')
        sales_code = SALES_ACCOUNT_BY_LEGACY.get(e['sales_acct']) if e else None
        if sales_code is None:
            cats = {cas['product_category'].get(name) for name, _, _ in d['lines']}
            sales_code = SALES_ACCOUNT_BY_CATEGORY.get(cats.pop()) if len(cats) == 1 else None
        if sales_code is None: problems.append('cannot decide the sales account (no accounting entry, mixed/unknown product categories)')
        if problems:
            out.append((n, 'hold', '; '.join(problems), None)); continue
        sp_code = SALESPERSON_MAP.get(d['salesman'], (None,))[0]
        sp_id = cas['employees'].get(sp_code, 0) if sp_code else 0
        lines = [{'description': '', 'product_id': str(cas['products'].get(name) or cas['new_products'][name]),
                  'quantity': str(qty), 'unit_price': str(price), 'uom_id': str(cas['uom_pcs']), 'uom_text': 'PCS',
                  'amount': str((qty * price).quantize(CENT)), 'vat_category': VAT_CATEGORY,
                  'wt_id': str(cas['wht_id']), 'account_id': str(cas['accounts'][sales_code])}
                 for name, qty, price in d['lines']]
        payload = {
            'invoice_number': n, 'invoice_date': d['date'].isoformat(),
            'due_date': (d['date'] + timedelta(days=NET_DAYS)).isoformat(),
            'customer_id': str(cas['customers'][cname]), 'payment_terms': f'Net {NET_DAYS}',
            'reference': '', 'salesperson_id': str(sp_id), 'customer_po_number': d['po'][:50], 'customer_po_date': '',
            'ar_trade_account_id': '', 'creditable_wht_account_id': '',
            'notes': (f"Copied from legacy invoice {n} (michellecaliwag.pythonanywhere.com), "
                      f"{d['date'].strftime('%m/%d/%Y')}, {d['customer']}, DR {d['dr']}, salesman {d['salesman'] or 'OFFICE ACCOUNT'}"),
            'line_items': json.dumps(lines), 'source_dr_ids': '[]',
        }
        out.append((n, 'post', {'gross': d['gross'], 'sales_code': sales_code, **exp}, payload))
    return out


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='d_from', required=True, type=date.fromisoformat)
    ap.add_argument('--to', dest='d_to', required=True, type=date.fromisoformat)
    ap.add_argument('--invoice-db', default=str(DEFAULT_INVOICE_DB))
    ap.add_argument('--accounting-db', default=str(DEFAULT_ACCOUNTING_DB))
    ap.add_argument('--accounting-xlsx', default=None, help="the app's Sales Journal export; preferred over --accounting-db when given")
    ap.add_argument('--ops-db', default=str(DEFAULT_OPS_DB))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    from app import create_app, db
    from app.accounts.models import Account
    from app.branches.models import Branch
    from app.customers.models import Customer
    from app.employees.models import Employee
    from app.journal_entries.models import JournalEntryLine
    from app.product_categories.models import ProductCategory
    from app.products.models import Product
    from app.sales_invoices.models import SalesInvoice
    from app.units_of_measure.models import UnitOfMeasure
    from app.users.models import User
    from app.withholding_tax.models import WithholdingTax

    app = create_app(os.environ.get('FLASK_ENV', 'development'))
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False, SERVER_NAME='localhost')

    docs = read_invoice_app(args.invoice_db, args.d_from, args.d_to)
    entries = (read_accounting_xlsx(args.accounting_xlsx, args.d_from, args.d_to) if args.accounting_xlsx
               else read_accounting_app(args.accounting_db, args.d_from, args.d_to))
    ops_live, ops_cancelled = read_ops_app(args.ops_db, args.d_from, args.d_to)
    print(f"sources: invoice app {len(docs)} docs | accounting app {len(entries)} CORP entries in range"
          f"{' (NONE: accounting cross-check not verified)' if not entries else ''} | ops app {len(ops_live)} live + {len(ops_cancelled)} cancelled DRs")

    with app.app_context():
        print('database:', app.config['SQLALCHEMY_DATABASE_URI'])
        branch = Branch.query.filter_by(code=BRANCH_CODE).one()
        admin = User.query.filter_by(role='admin', is_active=True).order_by(User.id).first()
        cats = {c.code.upper(): c.id for c in ProductCategory.query.all()}
        cat_name = {v: k for k, v in cats.items()}
        products = {p.name.strip(): p.id for p in Product.query.all()}
        cas = {
            'existing': {n for (n,) in db.session.query(SalesInvoice.invoice_number).all()},
            'customers': {c.name: c.id for c in Customer.query.filter_by(is_active=True).all()},
            'accounts': {a.code: a.id for a in Account.query.filter_by(is_active=True).all()},
            'products': products, 'new_products': {},
            'product_category': {p.name.strip(): cat_name.get(p.category_id) for p in Product.query.all()},
            'employees': {e.employee_no: e.id for e in Employee.query.all()},
            'uom_pcs': UnitOfMeasure.query.filter_by(code='PCS').one().id,
            'wht_id': WithholdingTax.query.filter_by(code=WHT_CODE).one().id,
        }
        # products to create: exact legacy name absent; category from the accounting leg of the first invoice using it
        need = {}
        for d in docs:
            e = entries.get(digits(d['number']))
            cat = CATEGORY_BY_LEGACY.get(e['sales_acct']) if e else None
            for name, _, _ in d['lines']:
                if name and name not in products and name not in need:
                    need[name] = cat
        for name, cat in need.items():
            cas['new_products'][name] = -1                     # placeholder until created
            cas['product_category'][name] = cat
        missing_emps = [e for e in NEW_EMPLOYEES if e['employee_no'] not in cas['employees']]

        plans = plan(docs, entries, ops_live, ops_cancelled, cas)
        by = Counter(kind for _, kind, _, _ in plans)
        print(f"plan: post {by['post']} | void {by['void']} | hold {by['hold']} | skip {by['skip']}")
        for n, kind, info, _ in plans:
            if kind in ('hold', 'skip'): print(f'  {kind} {n}: {info}')
        nums = sorted(int(digits(d['number'])) for d in docs)
        gaps = [x for x in range(nums[0], nums[-1] + 1) if x not in set(nums)] if nums else []
        print(f'series {nums[0]}..{nums[-1]}; gaps: {gaps or "none"}')
        print(f"products to create ({len(need)}): " + ', '.join(f'{k} [{v or "category?"}]' for k, v in need.items()))
        print(f"employees to create: {[e['employee_no'] for e in missing_emps] or 'none'}")
        tot = sum((p['gross'] for _, k, p, _ in plans if k == 'post'), Decimal('0.00'))
        print(f"planned gross {tot:,.2f}; net {sum((p['sales'] for _, k, p, _ in plans if k == 'post'), Decimal('0.00')):,.2f}")
        if args.dry_run:
            print('dry run: nothing written'); return
        if any(v is None for v in need.values()):
            print('STOP: some new products have no category (no accounting entry to derive it). Provide the fresh accounting DB first.'); return

        client = app.test_client()
        with client.session_transaction() as s:
            s['_user_id'] = str(admin.id); s['_fresh'] = True; s['selected_branch_id'] = branch.id

        # employees
        for e in missing_emps:
            r = client.post('/employees/create', data={**e, 'branch_id': str(branch.id), 'is_salesperson': 'y',
                                                       'is_active': '1', 'employment_status': '', 'pay_basis': '',
                                                       'pay_frequency': '', 'qualified_dependents': '0', 'user_id': ''},
                            follow_redirects=False)
            emp = Employee.query.filter_by(employee_no=e['employee_no']).first()
            print(f"employee {e['employee_no']}: {'created' if emp else 'FAILED ' + str(r.status_code)}")
            if emp: cas['employees'][e['employee_no']] = emp.id
        # products
        for name, cat in need.items():
            r = client.post('/products/create', data={
                'name': name, 'customer_code': '', 'description': '', 'job_order_name': '',
                'default_unit_of_measure_id': str(cas['uom_pcs']), 'default_unit_price': '',
                'default_account_id': str(cas['accounts'][SALES_ACCOUNT_BY_CATEGORY[cat]]),
                'category_id': str(cats[cat]), 'standard_cost': '', 'costing_method': '', 'reorder_level': '',
                'is_active': '1'}, follow_redirects=False)
            p = Product.query.filter_by(name=name).first()
            print(f"product {name!r}: {'created id ' + str(p.id) if p else 'FAILED ' + str(r.status_code)}")
            if p: cas['new_products'][name] = p.id
        plans = plan(docs, entries, ops_live, ops_cancelled, cas)   # re-plan with real ids

        created, voided, failed = [], [], []
        for n, kind, info, payload in plans:
            if kind not in ('post', 'void'): continue
            r = client.post('/sales-invoices/create', data=payload, follow_redirects=False)
            loc = r.headers.get('Location', '')
            if r.status_code != 302 or loc.endswith('/create'):
                failed.append((n, f'create -> {r.status_code} {loc}')); continue
            inv = SalesInvoice.query.filter_by(invoice_number=n).one()
            if kind == 'void':
                r2 = client.post(f'/sales-invoices/{inv.id}/void', data={'void_reason': CANCEL_REASON}, follow_redirects=False)
                db.session.expire_all(); inv = db.session.get(SalesInvoice, inv.id)
                (voided if inv.status == 'voided' and inv.journal_entry_id is None else failed).append(
                    (n, 'voided' if inv.status == 'voided' else f'void -> {r2.status_code}, status {inv.status}'))
                continue
            r2 = client.post(f'/sales-invoices/{inv.id}/post', follow_redirects=False)
            db.session.expire_all(); inv = db.session.get(SalesInvoice, inv.id)
            je = inv.journal_entry
            # CAS books one revenue leg per line; compare legs AGGREGATED by account.
            agg = defaultdict(lambda: [Decimal('0.00'), Decimal('0.00')])
            for l in (JournalEntryLine.query.filter_by(entry_id=je.id) if je else []):
                agg[l.account.code][0] += q2(l.debit_amount); agg[l.account.code][1] += q2(l.credit_amount)
            legs = {(code, d, c) for code, (d, c) in agg.items()}
            expect = {('112001', info['ar'], Decimal('0.00')), ('129005', info['cwt'], Decimal('0.00')),
                      ('213005', Decimal('0.00'), info['output']), (info['sales_code'], Decimal('0.00'), info['sales'])}
            ok = (r2.status_code == 302 and inv.status == 'posted' and je is not None and je.status == 'posted'
                  and legs == expect and q2(inv.subtotal) == info['gross'])
            (created if ok else failed).append((n, f"SI {inv.id} {je.entry_number if je else '-'} gross {info['gross']:,.2f}" if ok
                                                else f'post -> {r2.status_code} status {inv.status} legs {sorted(legs)} expected {sorted(expect)}'))

        print(f'\nposted {len(created)} | voided {len(voided)} | failed {len(failed)}')
        for n, why in failed: print(f'  FAIL {n}: {why}')
        # run-level checks
        posted = SalesInvoice.query.filter(SalesInvoice.branch_id == branch.id, SalesInvoice.status == 'posted',
                                           SalesInvoice.invoice_date >= args.d_from, SalesInvoice.invoice_date <= args.d_to).all()
        tot_gross = sum((q2(i.subtotal) for i in posted), Decimal('0.00'))
        tot_vat = sum((q2(i.vat_amount) for i in posted), Decimal('0.00'))
        tot_wht = sum((q2(i.withholding_tax_amount) for i in posted), Decimal('0.00'))
        print(f'CAS CORP {args.d_from}..{args.d_to}: {len(posted)} posted, gross {tot_gross:,.2f}, VAT {tot_vat:,.2f}, WHT {tot_wht:,.2f}, AR {tot_gross - tot_wht:,.2f}')
        if entries:
            a_sales = sum((q2(e['sales']) for e in entries.values()), Decimal('0.00'))
            a_vat = sum((q2(e['output']) for e in entries.values()), Decimal('0.00'))
            a_cwt = sum((q2(e['cwt']) for e in entries.values()), Decimal('0.00'))
            print(f'accounting app: net {a_sales:,.2f}, VAT {a_vat:,.2f}, CWT {a_cwt:,.2f} -> '
                  f"{'TIES' if (a_sales + a_vat, a_vat, a_cwt) == (tot_gross, tot_vat, tot_wht) else 'DIFFERS'}")
        else:
            print('accounting tie-out: not verified (no entries in the accounting DB for this range)')


if __name__ == '__main__':
    main()
