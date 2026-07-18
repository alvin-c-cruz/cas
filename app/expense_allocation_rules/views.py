"""Expense Allocation Rule master (Maintenance). One rule per P&L account (Phase 3b)."""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.accounts.models import Account
from app.expense_allocation_rules.models import ExpenseAllocationRule
from app.expense_allocation_rules.forms import ExpenseAllocationRuleForm
from app.audit.utils import log_create, log_update

expense_allocation_rules_bp = Blueprint('expense_allocation_rules', __name__,
                                        template_folder='templates')

# Revenue, Contra-Revenue, and Cost of Goods Sold are excluded -- they have their own
# dedicated distribution mechanism (revenue-by-line, standard-cost) and must never be
# configured via this master.
ALLOCATABLE_TYPES = ('Selling Expense', 'Administrative Expense', 'Other Income',
                     'Other Expense', 'Income Tax Expense')


def _populate_choices(form):
    accounts = (Account.query.filter(Account.is_active == True,
                                     Account.account_type.in_(ALLOCATABLE_TYPES))
                .order_by(Account.code).all())
    form.account_id.choices = [(str(a.id), f'{a.code} — {a.name}') for a in accounts]


@expense_allocation_rules_bp.route('/expense-allocation-rules')
@login_required
def list():
    rules = ExpenseAllocationRule.query.join(Account).order_by(Account.code).all()
    return render_template('expense_allocation_rules/list.html', rules=rules)


@expense_allocation_rules_bp.route('/expense-allocation-rules/create', methods=['GET', 'POST'])
@login_required
def create():
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to manage expense allocation rules.', 'error')
        return redirect(url_for('expense_allocation_rules.list'))
    form = ExpenseAllocationRuleForm()
    _populate_choices(form)
    if form.validate_on_submit():
        account_id = int(form.account_id.data)
        if ExpenseAllocationRule.query.filter_by(account_id=account_id).first():
            form.account_id.errors.append('This account already has an allocation rule — edit it instead.')
        else:
            r = ExpenseAllocationRule(account_id=account_id, basis=form.basis.data,
                                      created_by_id=current_user.id)
            db.session.add(r)
            db.session.commit()
            log_create('expense_allocation_rules', r.id, r.account.code, r.to_dict())
            flash('Expense allocation rule created.', 'success')
            return redirect(url_for('expense_allocation_rules.list'))
    return render_template('expense_allocation_rules/form.html', form=form,
                           title='Create Expense Allocation Rule', rule=None)


@expense_allocation_rules_bp.route('/expense-allocation-rules/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not (current_user.role == 'accountant' or current_user.has_full_access):
        flash('You do not have permission to manage expense allocation rules.', 'error')
        return redirect(url_for('expense_allocation_rules.list'))
    r = db.get_or_404(ExpenseAllocationRule, id)
    form = ExpenseAllocationRuleForm(obj=r)
    _populate_choices(form)
    if request.method == 'GET':
        form.account_id.data = str(r.account_id)
    if form.validate_on_submit():
        account_id = int(form.account_id.data)
        dup = ExpenseAllocationRule.query.filter(
            ExpenseAllocationRule.account_id == account_id,
            ExpenseAllocationRule.id != r.id).first()
        if dup:
            form.account_id.errors.append('This account already has an allocation rule — edit it instead.')
        else:
            old = r.to_dict()
            r.account_id = account_id
            r.basis = form.basis.data
            db.session.commit()
            log_update('expense_allocation_rules', r.id, r.account.code, old, r.to_dict())
            flash('Expense allocation rule updated.', 'success')
            return redirect(url_for('expense_allocation_rules.list'))
    return render_template('expense_allocation_rules/form.html', form=form,
                           title='Edit Expense Allocation Rule', rule=r)
