"""Journals — filtered list views over JournalEntry for each journal type."""
from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_required
from app import db
from app.journal_entries.models import JournalEntry
from datetime import datetime

journals_bp = Blueprint('journals', __name__, template_folder='templates')

VOUCHER_TYPES = ('reversal', 'adjustment', 'closing', 'opening', 'reclassification')


def _branch_id():
    return session.get('selected_branch_id')


def _date_defaults():
    year = datetime.now().year
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


@journals_bp.route('/journals/ap')
@login_required
def ap_journal():
    from app.purchase_bills.models import PurchaseBill
    branch_id = _branch_id()
    date_from, date_to = _date_defaults()

    if branch_id:
        query = JournalEntry.query.filter(
            JournalEntry.entry_type == 'purchase',
            JournalEntry.branch_id == branch_id
        )
    else:
        query = JournalEntry.query.filter_by(branch_id=-1)

    query = _apply_date_filter(query, date_from, date_to)
    entries = query.order_by(JournalEntry.entry_date.desc()).all()

    references = [e.reference for e in entries if e.reference]
    bills = PurchaseBill.query.filter(PurchaseBill.bill_number.in_(references)).all() if references else []
    bill_map = {b.bill_number: b for b in bills}

    return render_template('journals/ap_journal.html',
                           entries=entries,
                           bill_map=bill_map,
                           date_from=date_from,
                           date_to=date_to)


@journals_bp.route('/journals/voucher')
@login_required
def voucher():
    branch_id = _branch_id()
    date_from, date_to = _date_defaults()
    status_filter = request.args.get('status', 'all')

    if branch_id:
        query = JournalEntry.query.filter(
            JournalEntry.entry_type.in_(VOUCHER_TYPES),
            JournalEntry.branch_id == branch_id
        )
    else:
        query = JournalEntry.query.filter_by(branch_id=-1)

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
