from flask import Blueprint, render_template, redirect, url_for, flash
from app import db
from app.accounts.models import Account
from app.accounts.forms import AccountForm

accounts_bp = Blueprint('accounts', __name__, template_folder='templates')

@accounts_bp.route('/')
def list_accounts():
    """Chart of Accounts - List all accounts"""
    accounts = Account.query.order_by(Account.code).all()
    return render_template('accounts/list.html', accounts=accounts)

@accounts_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create new account"""
    form = AccountForm()

    # Populate parent account choices
    all_accounts = Account.query.order_by(Account.code).all()
    form.populate_parent_choices(all_accounts)

    if form.validate_on_submit():
        try:
            account = Account(
                code=form.code.data,
                name=form.name.data,
                account_type=form.account_type.data,
                classification=form.classification.data if form.classification.data else None,
                normal_balance=form.normal_balance.data,
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
def view(id):
    """View account details"""
    account = Account.query.get_or_404(id)
    return render_template('accounts/detail.html', account=account)

@accounts_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit existing account"""
    account = Account.query.get_or_404(id)
    form = AccountForm(obj=account)

    # Populate parent account choices (exclude current account)
    all_accounts = Account.query.filter(Account.id != id).order_by(Account.code).all()
    form.populate_parent_choices(all_accounts, exclude_id=id)

    if form.validate_on_submit():
        try:
            form.populate_obj(account)
            # Handle empty classification
            if not account.classification:
                account.classification = None

            db.session.commit()
            flash('Account updated successfully!', 'success')
            return redirect(url_for('accounts.list_accounts'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating account: {str(e)}', 'error')

    return render_template('accounts/form.html', form=form, account=account)

@accounts_bp.route('/<int:id>/delete', methods=['POST'])
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
