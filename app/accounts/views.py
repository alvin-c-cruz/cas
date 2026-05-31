from flask import Blueprint, render_template, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.accounts.models import Account
from app.accounts.forms import AccountForm

accounts_bp = Blueprint('accounts', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role for Chart of Accounts modifications."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can modify the Chart of Accounts.', 'error')
            return redirect(url_for('accounts.list_accounts'))
        return f(*args, **kwargs)
    return decorated_function

@accounts_bp.route('/')
@login_required
def list_accounts():
    """Chart of Accounts - List all accounts"""
    accounts = Account.query.order_by(Account.code).all()
    return render_template('accounts/list.html', accounts=accounts)

@accounts_bp.route('/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new account"""
    form = AccountForm()

    # Populate parent account choices
    all_accounts = Account.query.order_by(Account.code).all()
    form.populate_parent_choices(all_accounts)

    if form.validate_on_submit():
        # Check for duplicate account code
        existing_code = Account.query.filter_by(code=form.code.data).first()
        if existing_code:
            flash(f'Account code "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('accounts/form.html', form=form, account=None)

        # Check for duplicate account name
        existing_name = Account.query.filter_by(name=form.name.data).first()
        if existing_name:
            flash(f'Account name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('accounts/form.html', form=form, account=None)

        try:
            # Determine inherited fields based on parent
            account_type = form.account_type.data
            normal_balance = form.normal_balance.data
            classification = None

            if form.parent_id.data:
                # Child account - inherit from parent
                parent = Account.query.get(form.parent_id.data)
                if parent:
                    account_type = parent.account_type
                    normal_balance = parent.normal_balance
                    classification = parent.classification
            else:
                # Parent account - use form data
                classification = form.classification.data if form.classification.data else None

            account = Account(
                code=form.code.data,
                name=form.name.data,
                account_type=account_type,
                classification=classification,
                normal_balance=normal_balance,
                parent_id=form.parent_id.data,
                description=form.description.data
            )
            db.session.add(account)
            db.session.commit()
            flash('Account created successfully!', 'success')
            return redirect(url_for('accounts.list_accounts'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating account: {str(e)}', 'error')

    return render_template('accounts/form.html', form=form, account=None)

@accounts_bp.route('/<int:id>')
@login_required
def view(id):
    """View account details"""
    account = Account.query.get_or_404(id)
    return render_template('accounts/detail.html', account=account)

@accounts_bp.route('/<int:id>/json')
@login_required
def account_json(id):
    """Get account data as JSON"""
    account = Account.query.get_or_404(id)
    return jsonify({
        'id': account.id,
        'code': account.code,
        'name': account.name,
        'account_type': account.account_type,
        'classification': account.classification,
        'normal_balance': account.normal_balance,
        'parent_id': account.parent_id
    })

@accounts_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit existing account"""
    account = Account.query.get_or_404(id)
    form = AccountForm(obj=account)

    # Populate parent account choices (exclude current account)
    all_accounts = Account.query.filter(Account.id != id).order_by(Account.code).all()
    form.populate_parent_choices(all_accounts, exclude_id=id)

    if form.validate_on_submit():
        # Check for duplicate account code (excluding current account)
        existing_code = Account.query.filter_by(code=form.code.data).first()
        if existing_code and existing_code.id != id:
            flash(f'Account code "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('accounts/form.html', form=form, account=account)

        # Check for duplicate account name (excluding current account)
        existing_name = Account.query.filter_by(name=form.name.data).first()
        if existing_name and existing_name.id != id:
            flash(f'Account name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('accounts/form.html', form=form, account=account)

        try:
            # Update basic fields
            account.code = form.code.data
            account.name = form.name.data
            account.parent_id = form.parent_id.data
            account.description = form.description.data

            # Determine inherited fields based on parent
            if form.parent_id.data:
                # Child account - inherit account_type, normal_balance, and classification from parent
                parent = Account.query.get(form.parent_id.data)
                if parent:
                    account.account_type = parent.account_type
                    account.normal_balance = parent.normal_balance
                    account.classification = parent.classification
            else:
                # Parent account - use form data
                account.account_type = form.account_type.data
                account.normal_balance = form.normal_balance.data
                account.classification = form.classification.data if form.classification.data else None

            db.session.commit()
            flash('Account updated successfully!', 'success')
            return redirect(url_for('accounts.list_accounts'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating account: {str(e)}', 'error')

    return render_template('accounts/form.html', form=form, account=account)

@accounts_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete account"""
    try:
        account = Account.query.get_or_404(id)
        db.session.delete(account)
        db.session.commit()
        flash('Account deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting account: {str(e)}', 'error')

    return redirect(url_for('accounts.list_accounts'))
