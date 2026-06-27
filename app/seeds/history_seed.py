"""Historical APV + CDV demo-data generator (2021 -> present).

Builds documents and posts them through the real posting helpers so every
journal entry balances exactly like a hand-entered voucher. See
docs/superpowers/specs/2026-06-18-apv-cdv-history-seed-design.md.
"""
import calendar
import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.users.models import User

TWO = Decimal('0.01')


def _money(x):
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


# code, name, category, vat_code, wht_code, cadence, amount_min, amount_max, expense_code
VENDORS = [
    {'code': 'HV-RENT', 'name': 'Sunrise Realty Mgmt',  'category': 'rent',      'vat_code': 'VATABLE',    'wht_code': 'WC040', 'cadence': 'monthly',    'amount_min': 40000, 'amount_max': 50000, 'expense_code': '50220'},
    {'code': 'HV-POWR', 'name': 'MetroPower Electric',  'category': 'utilities', 'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'monthly',    'amount_min': 8000,  'amount_max': 13000, 'expense_code': '50221'},
    {'code': 'HV-WATR', 'name': 'ClearWater Utilities', 'category': 'utilities', 'vat_code': 'VAT-EXEMPT', 'wht_code': None,    'cadence': 'monthly',    'amount_min': 1500,  'amount_max': 4000,  'expense_code': '50222'},
    {'code': 'HV-TELE', 'name': 'GlobeLink Telecom',    'category': 'telecom',   'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'monthly',    'amount_min': 3000,  'amount_max': 6000,  'expense_code': '50223'},
    {'code': 'HV-SUP1', 'name': 'Mega Office Supplies', 'category': 'supplies',  'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'frequent',   'amount_min': 5000,  'amount_max': 20000, 'expense_code': '50230'},
    {'code': 'HV-SUP2', 'name': 'Capitol Stationers',   'category': 'supplies',  'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'frequent',   'amount_min': 3000,  'amount_max': 12000, 'expense_code': '50230'},
    {'code': 'HV-FUEL', 'name': 'FleetFuel Station',    'category': 'fuel',      'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'frequent',   'amount_min': 4000,  'amount_max': 15000, 'expense_code': '50281'},
    {'code': 'HV-COUR', 'name': 'QuickCourier Express', 'category': 'courier',   'vat_code': 'VATABLE',    'wht_code': 'WC070', 'cadence': 'frequent',   'amount_min': 1500,  'amount_max': 5000,  'expense_code': '50280'},
    {'code': 'HV-TECH', 'name': 'TechServe IT Solutions','category': 'it',       'vat_code': 'VATABLE',    'wht_code': 'WC060', 'cadence': 'occasional', 'amount_min': 15000, 'amount_max': 55000, 'expense_code': '50270'},
    {'code': 'HV-LAW',  'name': 'Bautista Law Office',  'category': 'legal',     'vat_code': 'VATABLE',    'wht_code': 'WC010', 'cadence': 'occasional', 'amount_min': 20000, 'amount_max': 60000, 'expense_code': '50241'},
    {'code': 'HV-FIX',  'name': 'FixIt Maintenance',    'category': 'repairs',   'vat_code': 'VATABLE',    'wht_code': 'WC060', 'cadence': 'occasional', 'amount_min': 5000,  'amount_max': 30000, 'expense_code': '50270'},
    {'code': 'HV-ADV',  'name': 'BrightAd Marketing',   'category': 'marketing', 'vat_code': 'VATABLE',    'wht_code': 'WC070', 'cadence': 'occasional', 'amount_min': 10000, 'amount_max': 45000, 'expense_code': '50290'},
]

_EXPENSE_CODES = sorted({v['expense_code'] for v in VENDORS})


def resolve_refs():
    """Resolve the GL accounts the seed posts against. Raises if any are missing."""
    def need(code):
        a = Account.query.filter_by(code=code).first()
        if a is None:
            raise RuntimeError(f"Required account {code} missing — run seed-db first.")
        return a

    refs = {
        'ap': need('20101'),
        'wt': need('20301'),
        'input_vat': need('10501'),
        'cash_on_hand': need('10101'),
        'cash_in_bank': need('10110'),
        'expense': {code: need(code) for code in _EXPENSE_CODES},
    }
    return refs


def next_doc_number(prefix, doc_date, counters):
    """Return PREFIX-YYYY-MM-NNNN, sequencing per (prefix, year, month)."""
    key = (prefix, doc_date.year, doc_date.month)
    counters[key] = counters.get(key, 0) + 1
    return f'{prefix}-{doc_date.year}-{doc_date.month:02d}-{counters[key]:04d}'


def ensure_accountant_user():
    u = User.query.filter_by(username='accountant').first()
    if u is None:
        u = User(username='accountant', email='accountant@cas.local',
                 full_name='Maria Accountant', role='accountant', is_active=True)
        u.set_password('cas-accountant')
        from app.users.module_access import default_all_permissions
        u.set_book_permissions(default_all_permissions())
        db.session.add(u)
        db.session.commit()
    return u


def ensure_vendors():
    from app.withholding_tax.models import WithholdingTax

    out = []
    for i, spec in enumerate(VENDORS):
        v = Vendor.query.filter_by(code=spec['code']).first()
        if v is None:
            v = Vendor(code=spec['code'], name=spec['name'],
                       tin=f"{100 + i}-000-000-000",
                       payment_terms='Net 30',
                       default_vat_category=spec['vat_code'],
                       is_active=True)
            db.session.add(v)
        # Assign the vendor's default withholding tax code(s) from the spec.
        # This drives the APV/CDV form's per-line WT dropdown via
        # /vendors/<id>/defaults; without it that dropdown shows only "None".
        # Set unconditionally so a re-run repairs existing vendors too.
        if spec['wht_code']:
            wt = WithholdingTax.query.filter_by(code=spec['wht_code']).first()
            v.withholding_taxes = [wt] if wt else []
        else:
            v.withholding_taxes = []
        out.append(v)
    db.session.commit()
    return out


def _vat_amount(line_total, vat_code):
    if vat_code == 'VATABLE':
        return _money(Decimal(line_total) * Decimal(12) / Decimal(112))
    return Decimal('0.00')


def build_apv(doc_date, vendor_spec, vendor_obj, refs, creator_id, poster_id,
              branch_id, counters, amount=None):
    """Create one posted APV (single line) + its balanced posted JE."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.accounts_payable.views import _post_ap_je
    from app.withholding_tax.models import WithholdingTax
    from app.utils import ph_now

    if amount is None:
        amount = (vendor_spec['amount_min'] + vendor_spec['amount_max']) / 2
    line_total = _money(amount)
    vat_amt = _vat_amount(line_total, vendor_spec['vat_code'])
    net_base = line_total - vat_amt

    wt = None
    wt_rate = Decimal('0.00')
    wt_amt = Decimal('0.00')
    if vendor_spec['wht_code']:
        wt = WithholdingTax.query.filter_by(code=vendor_spec['wht_code']).first()
        if wt:
            wt_rate = Decimal(str(wt.rate))
            wt_amt = _money(net_base * wt_rate / Decimal('100'))

    ap = AccountsPayable(
        branch_id=branch_id,
        ap_number=next_doc_number('AP', doc_date, counters),
        ap_date=doc_date,
        due_date=date.fromordinal(doc_date.toordinal() + 30),
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        vendor_invoice_number=f'INV-{doc_date.year}-{counters[("AP", doc_date.year, doc_date.month)]:04d}',
        payment_terms='Net 30',
        status='posted',
        amount_paid=Decimal('0.00'),
        created_by_id=creator_id,
        posted_by_id=poster_id,
        posted_at=ph_now(),
    )
    item = AccountsPayableItem(
        line_number=1,
        description=f'{vendor_spec["category"].title()} — {doc_date.strftime("%b %Y")}',
        amount=line_total,
        vat_category=vendor_spec['vat_code'],
        vat_rate=Decimal('12.00') if vendor_spec['vat_code'] == 'VATABLE' else Decimal('0.00'),
        line_total=line_total,
        vat_amount=vat_amt,
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=wt_rate,
        wt_amount=wt_amt,
    )
    ap.line_items.append(item)
    ap.calculate_totals()        # sets subtotal, vat_amount, withholding_tax_amount, total_amount, balance
    db.session.add(ap)
    db.session.flush()           # need ap.id before JE

    je = _post_ap_je(ap, poster_id)   # status='posted' -> JE posted
    ap.journal_entry_id = je.id
    db.session.commit()
    return ap


def _new_cdv(doc_date, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.utils import ph_now
    cash = refs['cash_in_bank'] if method == 'check' else refs['cash_on_hand']
    cdv = CashDisbursementVoucher(
        branch_id=branch_id,
        cdv_number=next_doc_number('CD', doc_date, counters),
        cdv_date=doc_date,
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        payment_method=method,
        cash_account_id=cash.id,
        notes='',
        status='posted',
        created_by_id=creator_id,
        posted_by_id=poster_id,
        posted_at=ph_now(),
    )
    if method == 'check':
        cdv.check_number = f'{doc_date.year}{doc_date.month:02d}{counters[("CD", doc_date.year, doc_date.month)]:04d}'
        cdv.check_date = doc_date
        cdv.check_bank = 'BPI'
    return cdv


def build_cdv_paying(doc_date, apvs, apply_fractions, refs, creator_id, poster_id,
                     branch_id, counters, method='check'):
    from app.cash_disbursements.models import CDVApLine
    from app.cash_disbursements.views import _post_cdv_je, _apply_ap_payments
    vendor_obj = apvs[0].vendor
    cdv = _new_cdv(doc_date, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method)
    for i, ap in enumerate(apvs):
        frac = apply_fractions[i]
        applied = _money(Decimal(str(ap.balance)) * frac)
        cdv.ap_lines.append(CDVApLine(
            line_number=i + 1,
            ap_id=ap.id,
            ap_number=ap.ap_number,
            original_balance=ap.balance,
            amount_applied=applied,
        ))
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, poster_id)
    cdv.journal_entry_id = je.id
    _apply_ap_payments(cdv)
    db.session.commit()
    return cdv


def build_cdv_expense(doc_date, vendor_spec, vendor_obj, refs, creator_id, poster_id,
                      branch_id, counters, method='cash', amount=None):
    from app.cash_disbursements.models import CDVExpenseLine
    from app.cash_disbursements.views import _post_cdv_je
    from app.withholding_tax.models import WithholdingTax

    if amount is None:
        amount = (vendor_spec['amount_min'] + vendor_spec['amount_max']) / 2
    line_total = _money(amount)
    vat_amt = _vat_amount(line_total, vendor_spec['vat_code'])
    net_base = line_total - vat_amt
    wt = WithholdingTax.query.filter_by(code=vendor_spec['wht_code']).first() if vendor_spec['wht_code'] else None
    wt_rate = Decimal(str(wt.rate)) if wt else Decimal('0.00')
    wt_amt = _money(net_base * wt_rate / Decimal('100')) if wt else Decimal('0.00')

    cdv = _new_cdv(doc_date, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method)
    cdv.expense_lines.append(CDVExpenseLine(
        line_number=1,
        description=f'{vendor_spec["category"].title()} — {doc_date.strftime("%b %Y")}',
        amount=line_total,
        vat_category=vendor_spec['vat_code'],
        vat_rate=Decimal('12.00') if vendor_spec['vat_code'] == 'VATABLE' else Decimal('0.00'),
        line_total=line_total,
        vat_amount=vat_amt,
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=wt_rate,
        wt_amount=wt_amt,
    ))
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, poster_id)
    cdv.journal_entry_id = je.id
    db.session.commit()
    return cdv


def _month_iter(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _clamp_day(year, month, day, end):
    last = calendar.monthrange(year, month)[1]
    d = date(year, month, min(day, last))
    return min(d, end)


def generate_history(branch_id, admin_id, *, start=date(2021, 1, 1),
                     end=None, rng_seed=20210101):
    if end is None:
        from app.utils import ph_now
        end = ph_now().date()
    rng = random.Random(rng_seed)
    refs = resolve_refs()
    acct = ensure_accountant_user()
    vendors = ensure_vendors()
    vmap = {v['code']: vendors[i] for i, v in enumerate(VENDORS)}
    counters = {}

    summary = {'apv': 0, 'cdv': 0, 'paid': 0, 'partially_paid': 0,
               'outstanding': 0, 'draft': 0, 'voided': 0, 'unbalanced': 0}

    monthly = [v for v in VENDORS if v['cadence'] == 'monthly']
    frequent = [v for v in VENDORS if v['cadence'] == 'frequent']
    occasional = [v for v in VENDORS if v['cadence'] == 'occasional']

    # "recent window" = last 12 months before end; those APVs get the aging spread.
    recent_cutoff = date(end.year - 1, end.month, 1)

    for (y, m) in _month_iter(start, end):
        month_apvs = []   # (ap, vendor_spec) posted this month, candidates for payment

        # recurring monthly vendors: one bill near a fixed day
        for spec in monthly:
            d = _clamp_day(y, m, rng.randint(2, 8), end)
            amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
            ap = build_apv(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                           branch_id, counters, amount=amt)
            summary['apv'] += 1
            month_apvs.append((ap, spec))

        # frequent vendors: 2-3 bills/month each
        for spec in frequent:
            for _ in range(rng.randint(2, 3)):
                d = _clamp_day(y, m, rng.randint(1, 28), end)
                amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
                ap = build_apv(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                               branch_id, counters, amount=amt)
                summary['apv'] += 1
                month_apvs.append((ap, spec))

        # occasional vendors: 0-1 bill/month each
        for spec in occasional:
            if rng.random() < 0.6:
                d = _clamp_day(y, m, rng.randint(1, 28), end)
                amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
                ap = build_apv(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                               branch_id, counters, amount=amt)
                summary['apv'] += 1
                month_apvs.append((ap, spec))

        # Payment / aging decisions per APV
        for ap, spec in month_apvs:
            in_recent = ap.ap_date >= recent_cutoff
            roll = rng.random()
            if in_recent and roll < 0.25:
                # leave outstanding (no CDV) -> aging bucket
                summary['outstanding'] += 1
                continue
            if in_recent and roll < 0.40:
                frac = Decimal('0.5')
            else:
                frac = Decimal('1.0')
            lag = rng.randint(15, 45)
            pay_date = date.fromordinal(ap.ap_date.toordinal() + lag)
            if pay_date <= end:
                method = 'check' if rng.random() < 0.6 else 'cash'
                build_cdv_paying(pay_date, [ap], [frac], refs, acct.id,
                                 admin_id, branch_id, counters, method=method)
                summary['cdv'] += 1
                if ap.status == 'paid':
                    summary['paid'] += 1
                elif ap.status == 'partially_paid':
                    summary['partially_paid'] += 1
                    summary['outstanding'] += 1   # remaining balance still ages
            else:
                summary['outstanding'] += 1

        # ~3 direct-expense CDVs per month (Section B)
        for _ in range(rng.randint(2, 4)):
            spec = rng.choice(frequent + occasional)
            d = _clamp_day(y, m, rng.randint(1, 28), end)
            amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
            method = 'cash' if rng.random() < 0.5 else 'check'
            build_cdv_expense(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                              branch_id, counters, method=method, amount=amt)
            summary['cdv'] += 1

    # 2026-only status-variety tail: a few drafts + a couple voided
    _seed_tail(refs, acct, admin_id, branch_id, counters, summary, end)

    # integrity check: count any unbalanced posted JE
    summary['unbalanced'] = _count_unbalanced_jes()
    return summary


def _seed_tail(refs, acct, admin_id, branch_id, counters, summary, end):
    """A handful of draft + voided APVs for status variety, relative to end."""
    spec = next(v for v in VENDORS if v['code'] == 'HV-SUP2')
    vobj = Vendor.query.filter_by(code='HV-SUP2').first()
    for i in range(3):
        d = _clamp_day(end.year, end.month, 10 + i, end)
        ap = _build_draft_apv(d, spec, vobj, refs, acct.id, branch_id, counters)
        summary['apv'] += 1
        summary['draft'] += 1
    vy, vm = end.year, end.month - 1
    if vm == 0:
        vy, vm = end.year - 1, 12
    for i in range(2):
        d = _clamp_day(vy, vm, 5 + i, end)
        _build_voided_apv(d, spec, vobj, refs, acct.id, admin_id, branch_id, counters)
        summary['apv'] += 1
        summary['voided'] += 1


def _build_draft_apv(doc_date, spec, vobj, refs, creator_id, branch_id, counters):
    """A draft APV: built like build_apv but status stays 'draft' (no posted JE promotion)."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.accounts_payable.views import _post_ap_je
    amt = _money((spec['amount_min'] + spec['amount_max']) / 2)
    vat_amt = _vat_amount(amt, spec['vat_code'])
    ap = AccountsPayable(
        branch_id=branch_id, ap_number=next_doc_number('AP', doc_date, counters),
        ap_date=doc_date, due_date=date.fromordinal(doc_date.toordinal() + 30),
        vendor_id=vobj.id, vendor_name=vobj.name, vendor_tin=vobj.tin,
        payment_terms='Net 30', status='draft', amount_paid=Decimal('0.00'),
        created_by_id=creator_id,
    )
    ap.line_items.append(AccountsPayableItem(
        line_number=1, description='Draft bill', amount=amt,
        vat_category=spec['vat_code'], vat_rate=Decimal('12.00'),
        line_total=amt, vat_amount=vat_amt,
        account_id=refs['expense'][spec['expense_code']].id,
        wt_rate=Decimal('0.00'), wt_amount=Decimal('0.00'),
    ))
    ap.calculate_totals()
    db.session.add(ap)
    db.session.flush()
    je = _post_ap_je(ap, creator_id)   # status='draft' -> JE created as draft
    ap.journal_entry_id = je.id
    db.session.commit()
    return ap


def _build_voided_apv(doc_date, spec, vobj, refs, creator_id, poster_id, branch_id, counters):
    ap = _build_draft_apv(doc_date, spec, vobj, refs, creator_id, branch_id, counters)
    from app.utils import ph_now
    # void deletes the JE (mirror the void view's effect on GL)
    if ap.journal_entry_id:
        from app.journal_entries.models import JournalEntry as _JE
        je = db.session.get(_JE, ap.journal_entry_id)
        ap.journal_entry_id = None
        ap.journal_entry = None
        if je:
            db.session.delete(je)
    ap.status = 'voided'
    ap.voided_at = ph_now()
    ap.voided_by_id = poster_id
    ap.void_reason = 'Seed demo voided document'
    db.session.commit()
    return ap


def _count_unbalanced_jes():
    from app.journal_entries.models import JournalEntry
    bad = 0
    for je in JournalEntry.query.filter_by(status='posted').all():
        d = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        c = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        if d != c:
            bad += 1
    return bad


def run_seed_history(reset=True, branch_id=None, start=date(2021, 1, 1),
                     end=None):
    """Reset (optional) + ensure base + generate history. Returns the summary dict."""
    if end is None:
        from app.utils import ph_now
        end = ph_now().date()
    from app.branches.models import Branch
    from app.users.models import User

    if reset:
        # Reuse the project's base seed path so COA/VAT/WHT/admin/branch/settings
        # are created exactly as `seed-db` does. Confirmed: app/seeds/seed_data.py
        # exposes seed_all(), which seeds admin (admin/admin123), Main branch,
        # the 173-account COA, VAT categories, WHT codes, and app settings.
        from app.seeds import seed_data
        db.drop_all()
        db.create_all()
        seed_data.seed_all()

    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        raise RuntimeError("admin user missing — base seed did not run.")
    if branch_id is None:
        branch = Branch.query.filter_by(code='MAIN').first() or Branch.query.first()
        if branch is None:
            raise RuntimeError("No branch found after base seed.")
        branch_id = branch.id

    summary = generate_history(branch_id, admin.id, start=start, end=end)
    return summary
