"""Budget Entry grid (R-09 Slice 1). See
docs/superpowers/specs/2026-07-19-budgeting-entry-r09-slice1-design.md.
"""
from decimal import Decimal

from flask import Blueprint, render_template, request, session
from flask_login import login_required

from app.utils import ph_now
from app.utils.authz import full_access_required
from app.budgeting.forms import BudgetGridForm
from app.budgeting.models import BudgetLine
from app.budgeting.utils import budget_account_rows, MONTH_NAMES

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
