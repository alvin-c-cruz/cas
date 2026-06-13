"""Journals — filtered list views over JournalEntry for each journal type."""
from flask import Blueprint, render_template, redirect, url_for, request, session, flash
from flask_login import login_required
from app import db
from app.journal_entries.models import JournalEntry
from app.utils import ph_now
from app.journals.ap_journal_data import resolve_period, build_columnar, build_ap_journal_xlsx
from datetime import datetime

journals_bp = Blueprint('journals', __name__, template_folder='templates')

VOUCHER_TYPES = ('reversal', 'adjustment', 'closing', 'opening', 'reclassification')


def _branch_id():
    return session.get('selected_branch_id')


def _date_defaults():
    year = ph_now().year
    return request.args.get('date_from', f'{year}-01-01'), request.args.get('date_to', f'{year}-12-31')


def _apply_date_filter(query, date_from, date_to):
    if date_from:
        try:
            query = query.filter(JournalEntry.entry_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(JournalEntry.entry_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass
    return query


def _gl_account_ids():
    """Return (ap_id, wt_id, input_vat_ids) for column grouping."""
    from app.accounts.models import Account
    from app.vat_categories.models import VATCategory
    ap = Account.query.filter_by(code='20101').first()
    wt = Account.query.filter_by(code='20301').first()
    vat_ids = {c.input_vat_account.id for c in VATCategory.query.all() if c.input_vat_account}
    return (ap.id if ap else None, wt.id if wt else None, vat_ids)


def _ap_journal_context(branch_id):
    """Build the columnar AP journal data for a branch + period from request.args."""
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'purchase',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    ap_id, wt_id, vat_ids = _gl_account_ids()
    matrix = build_columnar(posted, drafts, ap_id, wt_id, vat_ids)

    from app.purchase_bills.models import PurchaseBill
    refs = [e.reference for e in entries if e.reference]
    bills = PurchaseBill.query.filter(PurchaseBill.bill_number.in_(refs)).all() if refs else []
    bill_map = {b.bill_number: b for b in bills}
    return period, matrix, bill_map


def _entry_identity(entry, bill_map):
    """Return (no, invoice_no, vendor, particulars) for the left identifier columns."""
    bill = bill_map.get(entry.reference)
    return (
        entry.reference or '—',
        (bill.vendor_invoice_number if bill else '') or '',
        (bill.vendor_name if bill else '') or '—',
        (bill.notes if bill else '') or '',
    )


@journals_bp.route('/journals/ap')
@login_required
def ap_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    period, matrix, bill_map = _ap_journal_context(branch_id)
    return render_template('journals/ap_journal.html',
                           period=period, matrix=matrix, bill_map=bill_map)


@journals_bp.route('/journals/ap/export')
@login_required
def ap_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, bill_map = _ap_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or 'Company'

    if period['mode'] == 'month':
        filename = f"AP-Journal-{period['year']}-{period['month']:02d}.xlsx"
    else:
        filename = f"AP-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"

    return build_ap_journal_xlsx(
        columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
        period_label=period['label'], company_name=company_name,
        branch_name=branch_name, filename=filename,
        identity=lambda e: _entry_identity(e, bill_map))


@journals_bp.route('/journals/voucher')
@login_required
def voucher():
    branch_id = _branch_id()
    date_from, date_to = _date_defaults()
    status_filter = request.args.get('status', 'all')

    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    query = JournalEntry.query.filter(
        JournalEntry.entry_type.in_(VOUCHER_TYPES),
        JournalEntry.branch_id == branch_id
    )

    if status_filter != 'all':
        query = query.filter(JournalEntry.status == status_filter)
    query = _apply_date_filter(query, date_from, date_to)
    entries = query.order_by(JournalEntry.entry_date.desc()).all()

    return render_template('journals/voucher.html',
                           entries=entries,
                           date_from=date_from,
                           date_to=date_to,
                           status_filter=status_filter)


@journals_bp.route('/journals/cr')
@login_required
def cr_journal():
    return redirect(url_for('dashboard.under_development', feature='Cash Receipts Journal'))


@journals_bp.route('/journals/cd')
@login_required
def cd_journal():
    return redirect(url_for('dashboard.under_development', feature='Cash Disbursements Journal'))
