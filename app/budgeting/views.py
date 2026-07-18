"""Budget Entry grid (R-09 Slice 1). See
docs/superpowers/specs/2026-07-19-budgeting-entry-r09-slice1-design.md.
"""
from decimal import Decimal

from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.audit.utils import log_audit
from app.branches.models import Branch
from app.utils import ph_now
from app.utils.authz import full_access_required
from app.budgeting.forms import BudgetGridForm
from app.budgeting.models import BudgetLine
from app.budgeting.utils import budget_account_rows, budget_eligible_account_ids, to_decimal, MONTH_NAMES

budgeting_bp = Blueprint('budgeting', __name__, template_folder='templates')


def _branch_id():
    return session.get('selected_branch_id')


def _current_fiscal_year():
    return ph_now().year


@budgeting_bp.route('/budgeting')
@login_required
@full_access_required
def grid():
    branch_id = _branch_id()
    try:
        fiscal_year = int(request.args.get('fiscal_year', _current_fiscal_year()))
    except (TypeError, ValueError):
        fiscal_year = _current_fiscal_year()

    rows = budget_account_rows()
    existing = {(bl.account_id, bl.month): bl.amount for bl in BudgetLine.query.filter_by(
        branch_id=branch_id, fiscal_year=fiscal_year).all()}

    grid_rows = []
    for row in rows:
        entry = dict(row)
        if not row['is_header']:
            amounts = [existing.get((row['account'].id, m)) for m in range(1, 13)]
            entry['amounts'] = amounts
            entry['annual_total'] = sum((a for a in amounts if a is not None), Decimal('0'))
        grid_rows.append(entry)

    return render_template('budgeting/grid.html', grid_rows=grid_rows,
                           fiscal_year=fiscal_year, month_names=MONTH_NAMES,
                           form=BudgetGridForm(fiscal_year=fiscal_year))


class BudgetLineError(Exception):
    pass


def _parse_grid_cells(form, eligible_ids):
    """Parse amount_<account_id>_<month> fields into {(account_id, month): Decimal}.
    Skips blank/zero cells. Raises BudgetLineError on a negative amount or an
    ineligible account id -- the grid itself only ever renders eligible accounts,
    so an ineligible id here means a tampered request."""
    cells = {}
    for key, raw in form.items():
        if not key.startswith('amount_'):
            continue
        parts = key.split('_')
        if len(parts) != 3:
            continue
        try:
            account_id = int(parts[1])
            month = int(parts[2])
        except ValueError:
            continue
        if month < 1 or month > 12:
            continue
        amount = to_decimal(raw)
        if amount == 0:
            continue
        if amount < 0:
            raise BudgetLineError('Budget amounts cannot be negative.')
        if account_id not in eligible_ids:
            raise BudgetLineError(
                'Each budget line must use a valid, postable Revenue/Expense account.')
        cells[(account_id, month)] = amount
    return cells


@budgeting_bp.route('/budgeting/save', methods=['POST'])
@login_required
@full_access_required
def save():
    branch_id = _branch_id()
    form = BudgetGridForm()
    if not form.validate_on_submit():
        flash('Invalid fiscal year.', 'error')
        return redirect(url_for('budgeting.grid'))
    fiscal_year = form.fiscal_year.data

    eligible_ids = budget_eligible_account_ids()
    try:
        cells = _parse_grid_cells(request.form, eligible_ids)
    except BudgetLineError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('budgeting.grid', fiscal_year=fiscal_year))

    existing = {(bl.account_id, bl.month): bl for bl in BudgetLine.query.filter(
        BudgetLine.branch_id == branch_id, BudgetLine.fiscal_year == fiscal_year,
        BudgetLine.account_id.in_(eligible_ids)).all()}

    created = updated = deleted = 0
    for key, bl in list(existing.items()):
        if key not in cells:
            db.session.delete(bl)
            deleted += 1

    for (account_id, month), amount in cells.items():
        bl = existing.get((account_id, month))
        if bl:
            if bl.amount != amount:
                bl.amount = amount
                bl.updated_by_id = current_user.id
                updated += 1
        else:
            db.session.add(BudgetLine(
                branch_id=branch_id, account_id=account_id, fiscal_year=fiscal_year,
                month=month, amount=amount, updated_by_id=current_user.id))
            created += 1

    db.session.commit()

    branch = db.session.get(Branch, branch_id)
    log_audit(module='budgeting', action='update', record_id=branch_id,
              record_identifier=f'{branch.name if branch else branch_id} — FY{fiscal_year} Budget',
              new_values={'fiscal_year': fiscal_year, 'lines_saved': len(cells)},
              notes=f'{created} created, {updated} updated, {deleted} removed.')
    flash('Budget saved.', 'success')
    return redirect(url_for('budgeting.grid', fiscal_year=fiscal_year))
