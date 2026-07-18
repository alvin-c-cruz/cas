"""Cash & Bank register CRUD (R-04 slice 1). Branch-scoped label over one COA account."""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, jsonify
from flask_login import login_required, current_user

from app import db
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, model_to_dict
from app.bank_accounts.forms import BankAccountForm
from app.bank_accounts.models import BankAccount
from app.bank_accounts.service import cash_bank_leaf_account_choices

bank_accounts_bp = Blueprint('bank_accounts', __name__, template_folder='templates')

# Fields tracked in the audit log (account_id included though immutable -- it never
# actually diffs after creation, but keeping it here shows the GL link in create/edit
# snapshots).
_FIELDS = ['code', 'name', 'account_id', 'bank_name', 'account_number', 'account_type',
          'opening_balance', 'opening_date', 'is_active']


def staff_or_above_required(f):
    """Tier 1 bank-account ops -- staff, accountant, admin, chief accountant allowed."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _account_label(account_id):
    """'{code} — {name}' for the read-only GL account display on the edit form."""
    account = db.session.get(Account, account_id)
    return f'{account.code} — {account.name}' if account else str(account_id)


def _available_account_choices():
    """cash_bank_leaf_account_choices() minus accounts already claimed by a BankAccount
    (account_id is 1:1 and globally unique -- claims span all branches)."""
    choices = cash_bank_leaf_account_choices()
    claimed = {b.account_id for b in BankAccount.query.all()}
    return [(aid, label) for aid, label in choices if aid not in claimed]


@bank_accounts_bp.route('/bank-accounts/')
@login_required
def list_accounts():
    branch_id = session.get('selected_branch_id')
    accounts = (BankAccount.query.filter_by(branch_id=branch_id)
                .order_by(BankAccount.code).all())
    return render_template('bank_accounts/list.html', accounts=accounts)


@bank_accounts_bp.route('/bank-accounts/new', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def new_account():
    form = BankAccountForm()
    form.account_id.choices = _available_account_choices()

    if form.validate_on_submit():
        ba = BankAccount(
            branch_id=session.get('selected_branch_id'),
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            account_id=form.account_id.data,
            bank_name=form.bank_name.data,
            account_number=form.account_number.data,
            account_type=form.account_type.data,
            opening_balance=form.opening_balance.data or 0,
            opening_date=form.opening_date.data,
            created_by=current_user.username,
        )
        db.session.add(ba)
        db.session.commit()
        log_create('bank_accounts', ba.id, ba.code, model_to_dict(ba, _FIELDS))
        flash(f'Bank account "{ba.code}" created.', 'success')
        return redirect(url_for('bank_accounts.list_accounts'))

    return render_template('bank_accounts/form.html', form=form, bank_account=None)


@bank_accounts_bp.route('/bank-accounts/quick-add', methods=['POST'])
@login_required
@staff_or_above_required
def quick_add():
    """Inline create (JSON in/out), mirroring the vendor/customer/product quick-add
    endpoints -- so turning the module ON is never a hard setup gate, even before the
    OFF->ON seeder or a manual create has run."""
    form = BankAccountForm()
    form.account_id.choices = _available_account_choices()

    if form.validate_on_submit():
        ba = BankAccount(
            branch_id=session.get('selected_branch_id'),
            code=form.code.data.strip(),
            name=form.name.data.strip(),
            account_id=form.account_id.data,
            bank_name=form.bank_name.data,
            account_number=form.account_number.data,
            account_type=form.account_type.data,
            opening_balance=form.opening_balance.data or 0,
            opening_date=form.opening_date.data,
            created_by=current_user.username,
        )
        db.session.add(ba)
        db.session.commit()
        log_create('bank_accounts', ba.id, ba.code, model_to_dict(ba, _FIELDS))
        return jsonify(ok=True, bank_account={
            'id': ba.id,
            'account_id': ba.account_id,
            'label': f'{ba.code} - {ba.name}',
        })

    return jsonify(ok=False,
                   errors={f: errs[0] for f, errs in form.errors.items()}), 422


@bank_accounts_bp.route('/bank-accounts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit_account(id):
    ba = db.get_or_404(BankAccount, id)
    form = BankAccountForm(obj=ba)
    # account_id is immutable -- the template never renders it as an editable input,
    # so it is absent from the POST body and WTForms falls back to obj's value (the
    # `obj=ba` construction above). Choices only need to contain that one value so
    # validation (pre_validate against choices) still passes.
    form.account_id.choices = [(ba.account_id, _account_label(ba.account_id))]

    if request.method == 'GET':
        form.is_active.data = '1' if ba.is_active else '0'

    if form.validate_on_submit():
        old_values = model_to_dict(ba, _FIELDS)
        ba.code = form.code.data.strip()
        ba.name = form.name.data.strip()
        ba.bank_name = form.bank_name.data
        ba.account_number = form.account_number.data
        ba.account_type = form.account_type.data
        ba.opening_balance = form.opening_balance.data or 0
        ba.opening_date = form.opening_date.data
        ba.is_active = (form.is_active.data == '1')
        db.session.commit()
        log_update('bank_accounts', ba.id, ba.code, old_values, model_to_dict(ba, _FIELDS))
        flash(f'Bank account "{ba.code}" updated.', 'success')
        return redirect(url_for('bank_accounts.list_accounts'))

    return render_template('bank_accounts/form.html', form=form, bank_account=ba,
                           account_label=_account_label(ba.account_id))


@bank_accounts_bp.route('/bank-accounts/<int:id>/toggle-active', methods=['POST'])
@login_required
@staff_or_above_required
def toggle_active(id):
    """Quick Active/Inactive flip -- mirrors the shared status-toggle pattern
    (employees.toggle_status et al). Not wired to a list-row button per the approved
    mockup (status is set via the edit form's toggle); kept as its own endpoint since
    it's part of this module's declared interface for other callers."""
    ba = db.get_or_404(BankAccount, id)
    old_values = model_to_dict(ba, ['is_active'])
    ba.is_active = not ba.is_active
    db.session.commit()
    log_update('bank_accounts', ba.id, ba.code, old_values, model_to_dict(ba, ['is_active']))
    flash(f'Bank account "{ba.code}" is now {"active" if ba.is_active else "inactive"}.', 'success')
    return redirect(url_for('bank_accounts.list_accounts'))
