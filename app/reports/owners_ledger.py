"""Owners' basis lens: re-point the VAT legs of posted journal lines to their related accounts.

Spec: docs/design/2026-09-13-owners-vat-inclusive-basis-design.md, section 1.

Rules, applied line by line to posted LedgerLines (closing entries are the caller's business):

  1. Output VAT on a sales document (SI / CRV / sales memo)  -> the document lines' income
     accounts, pro rata to each line's vat_amount.
  2. Input VAT on a purchase document (AP / CDV / purchase memo) -> the document lines'
     accounts, pro rata (expense usually; an asset for capital goods).
  3. Any line of a vat_settlement / vat_settlement_reversal entry -> dropped (all legs are VAT).
  4. A debit to VAT Payable outside a settlement (a remittance) -> VAT expense by product line,
     split by each category's output VAT in the last settled quarter on/before the payment date
     (else the payment's own quarter).
  5. Anything else on a VAT account -> left where it is and listed in RemapSummary.untraced.

Pure-read. Never raises for data it cannot handle: it keeps the line and records why.
"""
from collections import defaultdict, namedtuple
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.accounts.models import Account
from app.accounts.account_types import BASE_CATEGORY
from app.settings import AppSettings
from app.reports.ledger import ZERO

CENT = Decimal('0.01')
SALES_KINDS = ('si', 'crv', 'sales_memo')
PURCHASE_KINDS = ('ap', 'cdv', 'purchase_memo')

Untraced = namedtuple('Untraced', ['entry_number', 'entry_date', 'account_code', 'amount', 'reason'])


class RemapSummary:
    """What the lens moved, and what it left in place with a reason.

    Signs: moved_to_income is credit-positive (VAT now inside income); moved_to_expense and
    moved_to_balance_sheet are debit-positive; vat_expense_by_category debit-positive.
    net_income_effect = owners' net income - GAAP net income for the same lines."""

    def __init__(self):
        self.moved_to_income = ZERO
        self.moved_to_expense = ZERO
        self.moved_to_balance_sheet = ZERO
        self.vat_expense_by_category = {}
        self.settlement_entries_dropped = 0
        self.untraced = []

    @property
    def vat_expense_total(self):
        return sum(self.vat_expense_by_category.values(), ZERO)

    @property
    def untraced_total(self):
        return sum((u.amount for u in self.untraced), ZERO)

    @property
    def net_income_effect(self):
        return self.moved_to_income - self.moved_to_expense - self.vat_expense_total

    def as_dict(self):
        return {
            'moved_to_income': float(self.moved_to_income),
            'moved_to_expense': float(self.moved_to_expense),
            'moved_to_balance_sheet': float(self.moved_to_balance_sheet),
            'vat_expense_total': float(self.vat_expense_total),
            'vat_expense_by_category': {k: float(v) for k, v in self.vat_expense_by_category.items()},
            'settlement_entries_dropped': self.settlement_entries_dropped,
            'untraced_total': float(self.untraced_total),
            'untraced': [{'entry_number': u.entry_number, 'entry_date': u.entry_date,
                          'account_code': u.account_code, 'amount': float(u.amount),
                          'reason': u.reason} for u in self.untraced],
            'net_income_effect': float(self.net_income_effect),
        }


def _q(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def distribute(total, weights):
    """Split `total` across keys pro rata to positive weights; the centavo rounding
    difference lands on the largest weight (first one on ties). {} when nothing to split."""
    total = _q(total)
    positive = {k: Decimal(w) for k, w in weights.items() if w and Decimal(w) > 0}
    if not positive or total == 0:
        return {}
    wsum = sum(positive.values())
    out = {k: _q(total * w / wsum) for k, w in positive.items()}
    diff = total - sum(out.values(), ZERO)
    if diff:
        largest = max(positive, key=lambda k: positive[k])
        out[largest] += diff
    return out


def _account_id_for_setting(key):
    code = AppSettings.get_setting(key)
    if not code:
        return None
    a = Account.query.filter_by(code=code).first()
    return a.id if a else None


def _vat_account_ids():
    from app.vat_settlement.service import input_account_ids, output_account_ids
    return (set(output_account_ids()), set(input_account_ids()),
            _account_id_for_setting('vat_payable_account_code'),
            _account_id_for_setting('input_vat_carryover_account_code'))


def _chunks(seq, n=500):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _source_docs(entry_ids):
    """{journal_entry_id: (kind, [(line_account_id, vat_amount), ...])} for the six
    document types, loaded in bulk. Drafts never carry a journal_entry_id, so no status
    filter is needed."""
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_receipts.models import CashReceiptVoucher
    from app.purchase_memos.models import PurchaseMemo
    from app.sales_invoices.models import SalesInvoice
    from app.sales_memos.models import SalesMemo
    specs = (('si', SalesInvoice, 'line_items'), ('crv', CashReceiptVoucher, 'revenue_lines'),
             ('sales_memo', SalesMemo, 'line_items'), ('ap', AccountsPayable, 'line_items'),
             ('cdv', CashDisbursementVoucher, 'expense_lines'),
             ('purchase_memo', PurchaseMemo, 'line_items'))
    out = {}
    for ids in _chunks(entry_ids):
        for kind, model, attr in specs:
            for doc in model.query.filter(model.journal_entry_id.in_(ids)).all():
                out[doc.journal_entry_id] = (
                    kind, [(li.account_id, Decimal(str(li.vat_amount or 0))) for li in getattr(doc, attr)])
    return out


def _remittance_shares(entry_date):
    """{category_id_or_None: output VAT} in the window rule 4 prescribes for a payment on
    entry_date: the most recently settled quarter on/before that date, else its own quarter."""
    from datetime import datetime, time, timedelta
    from sqlalchemy import func
    from app.products.models import Product
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.vat_settlement.models import VatSettlement
    from app.vat_settlement.service import quarter_bounds
    cutoff = datetime.combine(entry_date + timedelta(days=1), time.min)
    settled = (VatSettlement.query.filter(VatSettlement.status == 'settled',
                                          VatSettlement.settled_at < cutoff)
               .order_by(VatSettlement.settled_at.desc()).first())
    if settled:
        year, quarter = settled.fiscal_year, settled.quarter
    else:
        year, quarter = entry_date.year, (entry_date.month - 1) // 3 + 1
    qs, qe = quarter_bounds(year, quarter)
    rows = db.session.query(
        Product.category_id, func.coalesce(func.sum(SalesInvoiceItem.vat_amount), 0),
    ).select_from(SalesInvoiceItem).join(
        SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id
    ).outerjoin(Product, SalesInvoiceItem.product_id == Product.id).filter(
        SalesInvoice.status.in_(('posted', 'partially_paid', 'paid')),
        SalesInvoice.invoice_date >= qs, SalesInvoice.invoice_date <= qe,
    ).group_by(Product.category_id).all()
    return {cid: Decimal(str(v)) for cid, v in rows if Decimal(str(v)) > 0}


class _Lens:
    def __init__(self, lines):
        self.output_ids, self.input_ids, self.payable_id, self.carry_id = _vat_account_ids()
        self.vat_ids = self.output_ids | self.input_ids | {i for i in (self.payable_id, self.carry_id) if i}
        self.summary = RemapSummary()
        self.accounts = {a.id: a for a in Account.query.all()}
        wanted = {l.entry_id for l in lines} | {l.reversed_entry_id for l in lines if l.reversed_entry_id}
        self.docs = _source_docs(wanted) if self.vat_ids else {}
        self.dropped_entries = set()

        from app.reports.basis import vat_expense_account_map
        from app.product_categories.models import ProductCategory
        self.vat_expense = {cid: (a.id if a else None) for cid, a in vat_expense_account_map().items()}
        self.category_names = {c.id: c.name for c in ProductCategory.query.all()}
        self._shares_cache = {}

    # -- helpers -------------------------------------------------------------------------
    def _doc_for(self, ln):
        d = self.docs.get(ln.entry_id)
        if d is None and ln.reversed_entry_id:
            d = self.docs.get(ln.reversed_entry_id)   # a reversal follows its original's document
        return d

    def _keep(self, ln, reason, amount=None):
        """Leave (part of) a line on its VAT account and record why."""
        amt = (ln.debit - ln.credit) if amount is None else amount
        self.summary.untraced.append(Untraced(
            ln.entry_number, ln.entry_date, self.accounts[ln.account_id].code, abs(amt), reason))
        if amount is None:
            return ln
        return ln._replace(debit=max(amt, ZERO), credit=max(-amt, ZERO))

    def _moved(self, ln, target_id, amt):
        return ln._replace(account_id=target_id, debit=max(amt, ZERO), credit=max(-amt, ZERO),
                           moved_from_account_id=ln.account_id)

    def _spread(self, ln, doc_lines):
        """Rules 1 and 2: pro rata over the document lines' vat_amount, keyed by their account."""
        weights = defaultdict(lambda: ZERO)
        for acct_id, vat in doc_lines:
            if vat > 0:
                weights[acct_id] += vat          # acct_id may be None -> that share stays flagged
        shares = distribute(ln.debit - ln.credit, weights)
        if not shares:
            return [self._keep(ln, 'no_vat_on_document_lines')]
        out = []
        for acct_id, amt in shares.items():
            if acct_id is None or acct_id not in self.accounts:
                out.append(self._keep(ln, 'no_line_account', amt))
                continue
            out.append(self._moved(ln, acct_id, amt))
            base = BASE_CATEGORY.get(self.accounts[acct_id].account_type)
            if base == 'Revenue':
                self.summary.moved_to_income += -amt
            elif base == 'Expense':
                self.summary.moved_to_expense += amt
            else:
                self.summary.moved_to_balance_sheet += amt
        return out

    def _remit(self, ln):
        """Rule 4: a VAT remittance becomes VAT expense by product line."""
        if ln.entry_date not in self._shares_cache:
            self._shares_cache[ln.entry_date] = _remittance_shares(ln.entry_date)
        parts = distribute(ln.debit - ln.credit, self._shares_cache[ln.entry_date])
        if not parts:
            return [self._keep(ln, 'no_output_vat_in_window')]
        out = []
        for cid, amt in parts.items():
            if cid is None:
                out.append(self._keep(ln, 'uncategorized_sales', amt))
                continue
            target = self.vat_expense.get(cid)
            if not target:
                out.append(self._keep(ln, f'unmapped_category:{self.category_names.get(cid, cid)}', amt))
                continue
            out.append(self._moved(ln, target, amt))
            self.summary.vat_expense_by_category[cid] = self.summary.vat_expense_by_category.get(cid, ZERO) + amt
        return out

    # -- the rule table ------------------------------------------------------------------
    def vat_line(self, ln):
        doc = self._doc_for(ln)
        if ln.account_id in self.output_ids:
            if doc and doc[0] in SALES_KINDS:
                return self._spread(ln, doc[1])
            return [self._keep(ln, 'no_source_document')]
        if ln.account_id in self.input_ids:
            if doc and doc[0] in PURCHASE_KINDS:
                return self._spread(ln, doc[1])
            return [self._keep(ln, 'no_source_document')]
        if ln.account_id == self.payable_id and (ln.debit > ln.credit or ln.reversed_entry_id):
            if doc is None or doc[0] == 'cdv':
                return self._remit(ln)
            return [self._keep(ln, 'no_source_document')]
        return [self._keep(ln, 'manual_entry')]

    def run(self, lines):
        from app.vat_settlement.service import SETTLEMENT_TYPES
        out = []
        for ln in lines:
            if ln.entry_type in SETTLEMENT_TYPES:
                if ln.entry_id not in self.dropped_entries:
                    self.dropped_entries.add(ln.entry_id)
                    self.summary.settlement_entries_dropped += 1
                continue
            if ln.account_id not in self.vat_ids:
                out.append(ln)
                continue
            out.extend(self.vat_line(ln))
        return out


def remap(lines):
    """(remapped LedgerLines in input order, RemapSummary). Lines on non-VAT accounts pass
    through untouched; with no VAT accounts configured everything passes through."""
    lens = _Lens(lines)
    if not lens.vat_ids:
        return list(lines), lens.summary
    return lens.run(lines), lens.summary
