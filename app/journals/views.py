"""Journals — filtered list views over JournalEntry for each journal type."""
from flask import Blueprint, render_template, redirect, url_for, request, session, flash
from flask_login import login_required
from app import db
from app.journal_entries.models import JournalEntry
from app.utils import ph_now
from app.journals.ap_journal_data import resolve_period, build_columnar, build_ap_journal_xlsx
from app.journals.cd_journal_data import build_columnar_cd
from app.journals.cr_journal_data import build_columnar_cr, build_cr_journal_xlsx
from app.journals.si_journal_data import build_columnar_si, build_si_journal_xlsx
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


def _si_gl_account_ids():
    """Return (ar_id, wht_recv_id, output_vat_ids) for SI column grouping."""
    from app.accounts.models import Account
    from app.vat_categories.models import VATCategory
    ar = Account.query.filter_by(code='10201').first()
    wht_recv = Account.query.filter_by(code='10212').first()
    vat_ids = {c.output_vat_account.id for c in VATCategory.query.all() if c.output_vat_account}
    return (ar.id if ar else None, wht_recv.id if wht_recv else None, vat_ids)


def _ap_journal_context(branch_id):
    """Build the columnar AP journal data for a branch + period from request.args."""
    from app.accounts_payable.models import AccountsPayable
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'purchase',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    voided_aps = AccountsPayable.query.filter(
        AccountsPayable.branch_id == branch_id,
        AccountsPayable.status == 'voided',
        AccountsPayable.ap_date >= period['date_from'],
        AccountsPayable.ap_date <= period['date_to'],
    ).order_by(AccountsPayable.ap_date, AccountsPayable.ap_number).all()

    ap_id, wt_id, vat_ids = _gl_account_ids()
    matrix = build_columnar(posted, drafts, ap_id, wt_id, vat_ids, voided_bills=voided_aps)

    refs = [e.reference for e in entries if e.reference]
    aps = AccountsPayable.query.filter(AccountsPayable.ap_number.in_(refs)).all() if refs else []
    ap_map = {a.ap_number: a for a in aps}
    return period, matrix, ap_map


def _entry_identity(entry, ap_map):
    """Return (no, invoice_no, vendor, particulars) for the left identifier columns."""
    ap = ap_map.get(entry.reference)
    return (
        entry.reference or '—',
        (ap.vendor_invoice_number if ap else '') or '',
        (ap.vendor_name if ap else '') or '—',
        (ap.notes if ap else '') or '',
    )


def _cd_journal_context(branch_id):
    """Build the columnar CD journal data for a branch + period from request.args."""
    from app.cash_disbursements.models import CashDisbursementVoucher
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'disbursement',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    refs = [e.reference for e in entries if e.reference]
    cdvs = CashDisbursementVoucher.query.filter(
        CashDisbursementVoucher.cdv_number.in_(refs)
    ).all() if refs else []
    cdv_map = {c.cdv_number: c for c in cdvs}
    cancelled_refs = {c.cdv_number for c in cdvs if c.status == 'cancelled'}

    ap_id, wt_id, vat_ids = _gl_account_ids()
    matrix = build_columnar_cd(posted, drafts, ap_id, wt_id, vat_ids,
                               cancelled_refs=cancelled_refs)
    return period, matrix, cdv_map


def _cd_entry_identity(entry, cdv_map):
    """Return (cd_no, check_no, vendor, particulars) for the left identifier columns."""
    cdv = cdv_map.get(entry.reference)
    return (
        entry.reference or '—',
        (cdv.check_number if cdv and cdv.check_number else '') or '',
        (cdv.vendor_name if cdv else '') or '—',
        (cdv.notes if cdv else '') or '',
    )


def _cr_gl_account_ids():
    """Return (ar_id, wht_recv_id, output_vat_ids) for CR column grouping."""
    from app.accounts.models import Account
    from app.vat_categories.models import VATCategory
    ar = Account.query.filter_by(code='10201').first()
    wht_recv = Account.query.filter_by(code='10212').first()
    vat_ids = {c.output_vat_account.id for c in VATCategory.query.all() if c.output_vat_account}
    return (ar.id if ar else None, wht_recv.id if wht_recv else None, vat_ids)


def _cr_journal_context(branch_id):
    """Build the columnar CR journal data for a branch + period from request.args."""
    from app.cash_receipts.models import CashReceiptVoucher
    from app.journals.ap_journal_data import resolve_period
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'receipt',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    refs = [e.reference for e in entries if e.reference]
    crvs = CashReceiptVoucher.query.filter(
        CashReceiptVoucher.crv_number.in_(refs)
    ).all() if refs else []
    crv_map = {c.crv_number: c for c in crvs}
    cancelled_refs = {c.crv_number for c in crvs if c.status == 'cancelled'}

    ar_id, wht_recv_id, vat_ids = _cr_gl_account_ids()
    matrix = build_columnar_cr(posted, drafts, ar_id, wht_recv_id, vat_ids,
                               cancelled_refs=cancelled_refs)
    return period, matrix, crv_map


def _cr_entry_identity(entry, crv_map):
    """Return (cr_no, check_no, customer, particulars) for the left identifier columns."""
    crv = crv_map.get(entry.reference)
    return (
        entry.reference or '—',
        (crv.check_number if crv and crv.check_number else '') or '',
        (crv.customer_name if crv else '') or '—',
        (crv.notes if crv else '') or '',
    )


def _si_journal_context(branch_id):
    from app.sales_invoices.models import SalesInvoice
    period = resolve_period(request.args, today=ph_now().date())

    entries = JournalEntry.query.filter(
        JournalEntry.entry_type == 'sale',
        JournalEntry.branch_id == branch_id,
        JournalEntry.entry_date >= period['date_from'],
        JournalEntry.entry_date <= period['date_to'],
    ).order_by(JournalEntry.entry_date).all()
    posted = [e for e in entries if e.status == 'posted']
    drafts = [e for e in entries if e.status == 'draft']

    voided_invoices = SalesInvoice.query.filter(
        SalesInvoice.branch_id == branch_id,
        SalesInvoice.status == 'voided',
        SalesInvoice.invoice_date >= period['date_from'],
        SalesInvoice.invoice_date <= period['date_to'],
    ).order_by(SalesInvoice.invoice_date, SalesInvoice.invoice_number).all()

    ar_id, wht_recv_id, vat_ids = _si_gl_account_ids()
    matrix = build_columnar_si(posted, drafts, ar_id, wht_recv_id, vat_ids,
                               voided_invoices=voided_invoices)

    refs = [e.reference for e in entries if e.reference]
    # No branch filter: invoice_number is UNIQUE and refs come from branch-filtered entries.
    invoices = SalesInvoice.query.filter(
        SalesInvoice.invoice_number.in_(refs)).all() if refs else []
    invoice_map = {inv.invoice_number: inv for inv in invoices}
    return period, matrix, invoice_map


def _si_entry_identity(entry, invoice_map):
    """Return (si_no, customer_po, customer_name, notes) for Excel/print identity."""
    inv = invoice_map.get(entry.reference)
    return (
        entry.reference or '—',
        (inv.customer_po_number if inv else '') or '',
        (inv.customer_name if inv else '') or '—',
        (inv.notes if inv else '') or '',
    )


@journals_bp.route('/journals/ap')
@login_required
def ap_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    period, matrix, ap_map = _ap_journal_context(branch_id)
    return render_template('journals/ap_journal.html',
                           period=period, matrix=matrix, ap_map=ap_map)


@journals_bp.route('/journals/ap/print')
@login_required
def ap_journal_print():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, ap_map = _ap_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''

    return render_template('journals/ap_journal_print.html',
                           period=period, matrix=matrix, ap_map=ap_map,
                           company_name=company_name, branch_name=branch_name,
                           printed_at=ph_now())


@journals_bp.route('/journals/ap/export')
@login_required
def ap_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, ap_map = _ap_journal_context(branch_id)

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
        identity=lambda e: _entry_identity(e, ap_map))


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


@journals_bp.route('/journals/voucher/print')
@login_required
def voucher_print():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.settings import AppSettings
    date_from, date_to = _date_defaults()
    status_filter = request.args.get('status', 'all')

    query = JournalEntry.query.filter(
        JournalEntry.entry_type.in_(VOUCHER_TYPES),
        JournalEntry.branch_id == branch_id
    )
    if status_filter != 'all':
        query = query.filter(JournalEntry.status == status_filter)
    query = _apply_date_filter(query, date_from, date_to)
    entries = query.order_by(JournalEntry.entry_date.asc()).all()

    company_name = AppSettings.get_setting('company_name') or ''
    return render_template('journals/voucher_print.html',
                           entries=entries,
                           date_from=date_from,
                           date_to=date_to,
                           status_filter=status_filter,
                           company_name=company_name,
                           printed_at=ph_now())


@journals_bp.route('/journals/voucher/export')
@login_required
def voucher_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from io import BytesIO
    import openpyxl
    from flask import send_file
    from app.settings import AppSettings

    date_from, date_to = _date_defaults()
    status_filter = request.args.get('status', 'all')

    query = JournalEntry.query.filter(
        JournalEntry.entry_type.in_(VOUCHER_TYPES),
        JournalEntry.branch_id == branch_id
    )
    if status_filter != 'all':
        query = query.filter(JournalEntry.status == status_filter)
    query = _apply_date_filter(query, date_from, date_to)
    entries = query.order_by(JournalEntry.entry_date.asc()).all()

    company_name = AppSettings.get_setting('company_name') or ''
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Journal Voucher'

    if company_name:
        ws.append([company_name])
    ws.append(['JOURNAL VOUCHER'])
    ws.append([f'{date_from} to {date_to}'])
    ws.append([])
    ws.append(['Date', 'JV #', 'Description', 'Amount', 'Status', 'Posted By'])

    for entry in entries:
        posted_by = (entry.posted_by.username if entry.posted_by
                     else (entry.created_by.username if entry.created_by else ''))
        ws.append([
            entry.entry_date.strftime('%Y-%m-%d'),
            entry.entry_number,
            entry.description or '',
            float(entry.total_debit),
            entry.status.title(),
            posted_by,
        ])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f'JV-{date_from}-{date_to}.xlsx'
    return send_file(bio, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@journals_bp.route('/journals/cr')
@login_required
def cr_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    period, matrix, crv_map = _cr_journal_context(branch_id)
    return render_template('journals/cr_journal.html',
                           period=period, matrix=matrix, crv_map=crv_map)


@journals_bp.route('/journals/cr/export')
@login_required
def cr_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.journals.ap_journal_data import resolve_period
    period, matrix, crv_map = _cr_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''

    if period['mode'] == 'month':
        filename = f"CR-Journal-{period['year']}-{period['month']:02d}.xlsx"
    else:
        filename = f"CR-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"

    return build_cr_journal_xlsx(
        columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
        period_label=period['label'], company_name=company_name,
        branch_name=branch_name, filename=filename,
        identity=lambda e: _cr_entry_identity(e, crv_map))


@journals_bp.route('/journals/cr/print')
@login_required
def cr_journal_print():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, crv_map = _cr_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''

    return render_template('journals/cr_journal_print.html',
                           period=period, matrix=matrix, crv_map=crv_map,
                           company_name=company_name, branch_name=branch_name,
                           printed_at=ph_now())


@journals_bp.route('/journals/cd')
@login_required
def cd_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    period, matrix, cdv_map = _cd_journal_context(branch_id)
    return render_template('journals/cd_journal.html',
                           period=period, matrix=matrix, cdv_map=cdv_map)


@journals_bp.route('/journals/cd/export')
@login_required
def cd_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.journals.cd_journal_data import build_cd_journal_xlsx
    period, matrix, cdv_map = _cd_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''

    if period['mode'] == 'month':
        filename = f"CD-Journal-{period['year']}-{period['month']:02d}.xlsx"
    else:
        filename = f"CD-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"

    return build_cd_journal_xlsx(
        columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
        period_label=period['label'], company_name=company_name,
        branch_name=branch_name, filename=filename,
        identity=lambda e: _cd_entry_identity(e, cdv_map))


@journals_bp.route('/journals/cd/print')
@login_required
def cd_journal_print():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))

    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, cdv_map = _cd_journal_context(branch_id)

    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''

    return render_template('journals/cd_journal_print.html',
                           period=period, matrix=matrix, cdv_map=cdv_map,
                           company_name=company_name, branch_name=branch_name,
                           printed_at=ph_now())


@journals_bp.route('/journals/si')
@login_required
def si_journal():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to view journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))
    period, matrix, invoice_map = _si_journal_context(branch_id)
    return render_template('journals/si_journal.html',
                           period=period, matrix=matrix, invoice_map=invoice_map)


@journals_bp.route('/journals/si/print')
@login_required
def si_journal_print():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))
    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, invoice_map = _si_journal_context(branch_id)
    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or ''
    return render_template('journals/si_journal_print.html',
                           period=period, matrix=matrix, invoice_map=invoice_map,
                           company_name=company_name, branch_name=branch_name,
                           printed_at=ph_now())


@journals_bp.route('/journals/si/export')
@login_required
def si_journal_export():
    branch_id = _branch_id()
    if not branch_id:
        flash('Please select a branch to export journal entries.', 'warning')
        return redirect(url_for('users.select_branch', next=request.url))
    from app.branches.models import Branch
    from app.settings import AppSettings
    period, matrix, invoice_map = _si_journal_context(branch_id)
    branch = db.session.get(Branch, branch_id)
    branch_count = Branch.query.count()
    branch_name = branch.name if (branch and branch_count > 1) else None
    company_name = AppSettings.get_setting('company_name') or 'Company'
    if period['mode'] == 'month':
        filename = f"SI-Journal-{period['year']}-{period['month']:02d}.xlsx"
    else:
        filename = f"SI-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"
    return build_si_journal_xlsx(
        columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
        period_label=period['label'], company_name=company_name,
        branch_name=branch_name, filename=filename,
        identity=lambda e: _si_entry_identity(e, invoice_map))
