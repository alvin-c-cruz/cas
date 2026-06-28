"""Assemble render-ready data for all six BIR books of accounts by REUSING the
existing pure data-builder functions. Reads models + calls builders; modifies
nothing under app/journals/ or the transaction modules."""
from app.journal_entries.models import JournalEntry
from app.accounts.models import Account
from app.journals.ap_journal_data import resolve_period, build_columnar
from app.journals.si_journal_data import build_columnar_si
from app.journals.cr_journal_data import build_columnar_cr
from app.journals.cd_journal_data import build_columnar_cd
from app.reports.financial import generate_general_ledger
from app.reports.general_journal_data import build_general_journal, VOUCHER_ENTRY_TYPES

BOOKS = [
    {'key': 'general_journal',    'title': 'General Journal',         'sheet': 'General Journal',         'view_endpoint': 'reports.general_journal'},
    {'key': 'general_ledger',     'title': 'General Ledger',          'sheet': 'General Ledger',          'view_endpoint': 'reports.general_ledger'},
    {'key': 'sales_journal',      'title': 'Sales Journal',           'sheet': 'Sales Journal',           'view_endpoint': 'journals.si_journal'},
    {'key': 'purchase_journal',   'title': 'Purchase Journal',        'sheet': 'Purchase Journal',        'view_endpoint': 'journals.ap_journal'},
    {'key': 'cash_receipts',      'title': 'Cash Receipts Book',      'sheet': 'Cash Receipts Book',      'view_endpoint': 'journals.cr_journal'},
    {'key': 'cash_disbursements', 'title': 'Cash Disbursements Book', 'sheet': 'Cash Disbursements Book', 'view_endpoint': 'journals.cd_journal'},
]


def _gj_entries(branch_id, period):
    """Fetch voucher-type journal entries for the General Journal."""
    return JournalEntry.query.filter(
        JournalEntry.entry_type.in_(VOUCHER_ENTRY_TYPES),
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date, JournalEntry.id).all()


def _ap_cd_account_ids():
    """Return (ap_id, wt_id, input_vat_ids) — mirrors _gl_account_ids() in journals/views.py."""
    from app.vat_categories.models import VATCategory
    ap = Account.query.filter_by(code='20101').first()
    wt = Account.query.filter_by(code='20301').first()
    vat_ids = {c.input_vat_account.id for c in VATCategory.query.all() if c.input_vat_account}
    return (ap.id if ap else None, wt.id if wt else None, vat_ids)


def _si_cr_account_ids():
    """Return (ar_id, wht_recv_id, output_vat_ids) — mirrors _si_gl_account_ids() in journals/views.py."""
    from app.sales_vat_categories.models import SalesVATCategory
    ar = Account.query.filter_by(code='10201').first()
    wht_recv = Account.query.filter_by(code='10212').first()
    vat_ids = {c.output_vat_account.id for c in SalesVATCategory.query.all() if c.output_vat_account}
    return (ar.id if ar else None, wht_recv.id if wht_recv else None, vat_ids)


def collect_books(branch_id, args):
    """Return {'period': <resolve_period dict>, 'books': {key: {title, kind, data}}}.

    Each columnar journal (SI/AP/CR/CD) is assembled by replicating the thin
    query + account-id grouping that journals/views.py uses, then calling the
    existing pure build_columnar* functions.
    """
    from app.utils import ph_now
    today = ph_now().date()   # PH time (CLAUDE.md: never naive datetime.now())
    period = resolve_period(args, today)
    df, dt = period['date_from'], period['date_to']

    books = {}

    # 1. General Journal (voucher-type entries only)
    books['general_journal'] = {
        'title': 'General Journal', 'kind': 'gj',
        'data': build_general_journal(_gj_entries(branch_id, period)),
    }

    # 2. General Ledger (all accounts, full period)
    books['general_ledger'] = {
        'title': 'General Ledger', 'kind': 'gl',
        'data': generate_general_ledger(df, dt, branch_id),
    }

    # 3-6. Columnar special journals
    _assemble_columnar(books, branch_id, df, dt)
    return {'period': period, 'books': books}


def _assemble_columnar(books, branch_id, df, dt):
    """Fill the four columnar journal books by mirroring journals/views.py assembly."""

    # ── Sales Journal ────────────────────────────────────────────────────────
    # Mirrors _si_journal_context() in journals/views.py
    from app.sales_invoices.models import SalesInvoice

    si_entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'sale',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= df,
        JournalEntry.entry_date <= dt,
    ).order_by(JournalEntry.entry_date).all()
    si_posted = [e for e in si_entries if e.status == 'posted']
    si_drafts = [e for e in si_entries if e.status == 'draft']

    voided_invoices = SalesInvoice.query.filter(
        SalesInvoice.branch_id == branch_id,
        SalesInvoice.status == 'voided',
        SalesInvoice.invoice_date >= df,
        SalesInvoice.invoice_date <= dt,
    ).order_by(SalesInvoice.invoice_date, SalesInvoice.invoice_number).all()

    ar_id, wht_recv_id, output_vat_ids = _si_cr_account_ids()
    books['sales_journal'] = {
        'title': 'Sales Journal', 'kind': 'columnar',
        'data': build_columnar_si(si_posted, si_drafts, ar_id, wht_recv_id, output_vat_ids,
                                  voided_invoices=voided_invoices),
    }

    # ── Purchase Journal ──────────────────────────────────────────────────────
    # Mirrors _ap_journal_context() in journals/views.py
    from app.accounts_payable.models import AccountsPayable

    ap_entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'purchase',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= df,
        JournalEntry.entry_date <= dt,
    ).order_by(JournalEntry.entry_date).all()
    ap_posted = [e for e in ap_entries if e.status == 'posted']
    ap_drafts = [e for e in ap_entries if e.status == 'draft']

    voided_aps = AccountsPayable.query.filter(
        AccountsPayable.branch_id == branch_id,
        AccountsPayable.status == 'voided',
        AccountsPayable.ap_date >= df,
        AccountsPayable.ap_date <= dt,
    ).order_by(AccountsPayable.ap_date, AccountsPayable.ap_number).all()

    ap_id, wt_id, input_vat_ids = _ap_cd_account_ids()
    books['purchase_journal'] = {
        'title': 'Purchase Journal', 'kind': 'columnar',
        'data': build_columnar(ap_posted, ap_drafts, ap_id, wt_id, input_vat_ids,
                               voided_bills=voided_aps),
    }

    # ── Cash Receipts Book ────────────────────────────────────────────────────
    # Mirrors _cr_journal_context() in journals/views.py
    from app.cash_receipts.models import CashReceiptVoucher

    cr_entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'receipt',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= df,
        JournalEntry.entry_date <= dt,
    ).order_by(JournalEntry.entry_date).all()
    cr_posted = [e for e in cr_entries if e.status == 'posted']
    cr_drafts = [e for e in cr_entries if e.status == 'draft']

    cr_refs = [e.reference for e in cr_entries if e.reference]
    crvs = CashReceiptVoucher.query.filter(
        CashReceiptVoucher.crv_number.in_(cr_refs)
    ).all() if cr_refs else []
    cr_cancelled = {c.crv_number for c in crvs if c.status == 'cancelled'}

    cr_ar_id, cr_wht_id, cr_vat_ids = _si_cr_account_ids()
    books['cash_receipts'] = {
        'title': 'Cash Receipts Book', 'kind': 'columnar',
        'data': build_columnar_cr(cr_posted, cr_drafts, cr_ar_id, cr_wht_id, cr_vat_ids,
                                  cancelled_refs=cr_cancelled),
    }

    # ── Cash Disbursements Book ───────────────────────────────────────────────
    # Mirrors _cd_journal_context() in journals/views.py
    from app.cash_disbursements.models import CashDisbursementVoucher

    cd_entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'disbursement',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= df,
        JournalEntry.entry_date <= dt,
    ).order_by(JournalEntry.entry_date).all()
    cd_posted = [e for e in cd_entries if e.status == 'posted']
    cd_drafts = [e for e in cd_entries if e.status == 'draft']

    cd_refs = [e.reference for e in cd_entries if e.reference]
    cdvs = CashDisbursementVoucher.query.filter(
        CashDisbursementVoucher.cdv_number.in_(cd_refs)
    ).all() if cd_refs else []
    cd_cancelled = {c.cdv_number for c in cdvs if c.status == 'cancelled'}

    cd_ap_id, cd_wt_id, cd_vat_ids = _ap_cd_account_ids()
    books['cash_disbursements'] = {
        'title': 'Cash Disbursements Book', 'kind': 'columnar',
        'data': build_columnar_cd(cd_posted, cd_drafts, cd_ap_id, cd_wt_id, cd_vat_ids,
                                  cancelled_refs=cd_cancelled),
    }
