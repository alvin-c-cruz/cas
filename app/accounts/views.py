from flask import Blueprint, render_template, redirect, url_for, flash, jsonify, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.accounts.models import Account
from app.accounts.approval_models import AccountChangeRequest
from app.accounts.forms import AccountForm
from app.accounts.account_types import TYPES_NEEDING_CLASSIFICATION, DEFAULT_NORMAL_BALANCE, SUMMARY_CATEGORY
from app.users.models import User
from app.utils import ph_now
from app.utils.export import export_to_excel, export_to_csv
from app.audit.utils import log_audit
import json

accounts_bp = Blueprint('accounts', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role for Chart of Accounts modifications."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can modify the Chart of Accounts.', 'error')
            return redirect(url_for('accounts.list_accounts'))
        return f(*args, **kwargs)
    return decorated_function


def can_auto_approve():
    """
    Sole-accountant rule (owner decision 2026-06-12, B-011): admins are
    separate from accountants. The single active accountant auto-approves
    their own changes regardless of how many admins exist; admins never
    auto-approve and always go to pending.
    """
    if current_user.role != 'accountant':
        return False
    total_accountants = User.query.filter(
        User.role == 'accountant',
        User.is_active == True
    ).count()
    return total_accountants == 1


PENDING_SUBMITTED_MESSAGE = ('Change request submitted — pending review. '
                             'It will appear under Action Items until approved or rejected.')


def find_pending_request(account_id=None, code=None):
    """
    Find an existing PENDING change request targeting the same record.

    For update/delete pass account_id. For create pass the proposed code
    (pending create requests have no account_id; the code lives in change_data).
    """
    pending = AccountChangeRequest.query.filter_by(status='pending')
    if account_id is not None:
        return pending.filter(AccountChangeRequest.account_id == account_id).first()
    if code is not None:
        create_requests = pending.filter(
            AccountChangeRequest.account_id.is_(None),
            AccountChangeRequest.change_type == 'create')
        for req in create_requests.all():
            if req.get_change_data().get('code') == code:
                return req
    return None


def flash_duplicate_pending(existing_request):
    """Flash a consistent error message about an existing pending change request."""
    requested_on = (existing_request.requested_at.strftime('%b %d, %Y')
                    if existing_request.requested_at else 'an earlier date')
    flash(f'A pending change request for this record already exists '
          f'(submitted by {existing_request.requested_by} on {requested_on}). '
          f'It must be reviewed before another change can be submitted.', 'error')


@accounts_bp.route('/')
@login_required
def list_accounts():
    """Chart of Accounts - List all accounts"""
    accounts = Account.query.order_by(Account.code).all()

    id_to_account = {a.id: a for a in accounts}
    has_children = {a.parent_id for a in accounts if a.parent_id}

    # Display order is a pre-order DFS so every subtree is contiguous: each root
    # group, then its children (recursively), each level in code order. Because
    # legacy leaf codes interleave across groups, a flat code-sort would scatter
    # children away from their parent; DFS keeps the indentation honest.
    # `accounts` is already code-sorted, so roots and child lists keep code order.
    children_by_parent = {}
    roots = []
    for a in accounts:
        if a.parent_id and a.parent_id in id_to_account:
            children_by_parent.setdefault(a.parent_id, []).append(a)
        else:
            roots.append(a)  # top-level, or orphan whose parent is missing

    account_rows = []
    visited = set()

    def walk(node, depth):
        if node.id in visited:
            return  # guard against an accidental parent cycle
        visited.add(node.id)
        account_rows.append({
            'account': node,
            'depth': depth,
            # parent/group = top-level (no parent) OR has children
            'is_header': node.id in has_children or node.parent_id is None,
            # coarse bucket for the summary cards + filter tabs (COGS/Opex split)
            'summary_category': SUMMARY_CATEGORY.get(node.account_type, node.account_type),
        })
        for child in children_by_parent.get(node.id, []):
            walk(child, depth + 1)

    for r in roots:
        walk(r, 0)

    # Postable-account counts per summary bucket (for the summary cards)
    type_counts = {}
    for row in account_rows:
        if not row['is_header']:
            t = row['summary_category']
            type_counts[t] = type_counts.get(t, 0) + 1

    pending_requests = AccountChangeRequest.query.filter_by(status='pending').all()

    # Account ids with an open pending change request (for "Pending change" row badges)
    pending_account_ids = {r.account_id for r in pending_requests if r.account_id}

    return render_template('accounts/list.html',
                           account_rows=account_rows,
                           type_counts=type_counts,
                           pending_requests=pending_requests,
                           pending_account_ids=pending_account_ids)


# --- Chart of Accounts download (Excel + CSV) -----------------------------
ACCOUNT_FIELDS = ['code', 'name', 'account_type', 'classification',
                  'normal_balance', 'parent_code', 'parent_name', 'postable', 'status']
ACCOUNT_EXPORT_HEADERS = ['Code', 'Account Name', 'Type', 'Classification',
                          'Normal Balance', 'Parent Code', 'Parent Name', 'Postable', 'Status']


def _account_export_rows(accounts):
    """Build the export row dicts shared by the Excel and CSV routes.

    Hierarchy is derived (matches the COA list): an account is a non-postable
    group header if it is top-level (no parent) OR has children; otherwise it is
    a postable leaf.
    """
    by_id = {a.id: a for a in accounts}
    has_children = {a.parent_id for a in accounts if a.parent_id}
    rows = []
    for a in accounts:
        parent = by_id.get(a.parent_id)
        is_group = a.parent_id is None or a.id in has_children
        rows.append({
            'code': a.code,
            'name': a.name,
            'account_type': a.account_type,
            'classification': a.classification or '',
            'normal_balance': (a.normal_balance or '').capitalize(),
            'parent_code': parent.code if parent else '',
            'parent_name': parent.name if parent else '',
            'postable': 'No' if is_group else 'Yes',
            'status': 'Active' if a.is_active else 'Inactive',
        })
    return rows


@accounts_bp.route('/export/excel')
@login_required
def export_excel():
    """Download the Chart of Accounts as an Excel workbook."""
    accounts = Account.query.order_by(Account.code).all()
    data = _account_export_rows(accounts)
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(
        data=data,
        columns=ACCOUNT_FIELDS,
        headers=ACCOUNT_EXPORT_HEADERS,
        filename=f'chart_of_accounts_{timestamp}.xlsx',
        title='Chart of Accounts',
    )


@accounts_bp.route('/export/csv')
@login_required
def export_csv():
    """Download the Chart of Accounts as a CSV file."""
    accounts = Account.query.order_by(Account.code).all()
    data = _account_export_rows(accounts)
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(
        data=data,
        columns=ACCOUNT_FIELDS,
        headers=ACCOUNT_EXPORT_HEADERS,
        filename=f'chart_of_accounts_{timestamp}.csv',
    )


@accounts_bp.route('/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new account - submits for approval"""
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

        # Block duplicate pending requests for the same proposed account code
        existing_request = find_pending_request(code=form.code.data)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('accounts.list_accounts'))

        try:
            # Determine inherited fields based on parent
            account_type = form.account_type.data
            # Default normal_balance from account type when not explicitly supplied
            normal_balance = form.normal_balance.data or DEFAULT_NORMAL_BALANCE.get(account_type, 'debit')
            classification = None

            if form.parent_id.data:
                # Child account - inherit from parent
                parent = db.session.get(Account, form.parent_id.data)
                if parent:
                    account_type = parent.account_type
                    normal_balance = parent.normal_balance
                    classification = parent.classification
            else:
                # Parent account - use form data
                classification = form.classification.data if form.classification.data else None
                # Require classification for Asset and Liability types
                if account_type in TYPES_NEEDING_CLASSIFICATION and not classification:
                    flash('Classification (Current or Non-Current) is required for Asset and Liability accounts.', 'error')
                    return render_template('accounts/form.html', form=form, account=None)

            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'account_type': account_type,
                'classification': classification,
                'normal_balance': normal_balance,
                'parent_id': form.parent_id.data,
                'description': form.description.data
            }

            # Create change request (no reason needed when creating master data —
            # the reviewer judges the proposed data itself)
            change_request = AccountChangeRequest(
                change_type='create',
                change_data=json.dumps(change_data),
                requested_by=current_user.username,
                requested_at=ph_now(),
                status='pending',
                request_reason=None
            )

            # Check if can auto-approve
            if can_auto_approve():
                # Auto-approve and create account immediately
                account = Account(**change_data)
                db.session.add(account)

                change_request.status = 'approved'
                change_request.reviewed_by = current_user.username
                change_request.reviewed_at = ph_now()

                db.session.add(change_request)
                db.session.commit()

                # Audit log for change request submission and approval
                log_audit(
                    module='account',
                    action='create',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                    new_values=change_data,
                    notes='Auto-approved (single accountant)'
                )

                flash('Account created successfully! (Auto-approved - you are the only accountant)', 'success')
            else:
                # Save pending request
                db.session.add(change_request)
                db.session.commit()

                # Audit log for change request submission
                log_audit(
                    module='account',
                    action='create',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                    new_values=change_data,
                    notes='Pending approval.'
                )

                flash(PENDING_SUBMITTED_MESSAGE, 'success')

            return redirect(url_for('accounts.list_accounts'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating account request", exc_info=True)
            log_exception(e, severity='ERROR', module='accounts.create_request')
            db.session.rollback()
            flash(f'Error creating account request: {str(e)}', 'error')

    return render_template('accounts/form.html', form=form, account=None)


@accounts_bp.route('/<int:id>')
@login_required
def view(id):
    """View account details"""
    account = db.get_or_404(Account, id)
    return render_template('accounts/detail.html', account=account)


@accounts_bp.route('/<int:id>/json')
@login_required
def account_json(id):
    """Get account data as JSON"""
    account = db.get_or_404(Account, id)
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
    """Edit existing account - submits for approval"""
    account = db.get_or_404(Account, id)

    # Initialize form - on GET, populate from account; on POST, use form data
    if request.method == 'GET':
        form = AccountForm(obj=account, require_reason=True)
        # Debug: Print account values
        print(f"DEBUG - Account {account.code}: type={account.account_type}, balance={account.normal_balance}, class={account.classification}, parent={account.parent_id}")
        # Explicitly set SelectField values for GET requests
        form.account_type.data = account.account_type
        form.normal_balance.data = account.normal_balance
        form.classification.data = account.classification
        # Keep the field's coerced type (int/None) so WTForms marks the matching
        # option selected. Stringifying it broke the compare (coerce->int vs str),
        # leaving the dropdown on "None (Top Level)" and orphaning children on save.
        form.parent_id.data = account.parent_id
        # Debug: Print form data after setting
        print(f"DEBUG - Form data set: type={form.account_type.data}, balance={form.normal_balance.data}, class={form.classification.data}, parent={form.parent_id.data}")
    else:
        form = AccountForm(require_reason=True)

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

        # Block duplicate pending requests for the same account
        existing_request = find_pending_request(account_id=id)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('accounts.list_accounts'))

        try:
            # Determine inherited fields based on parent
            account_type = account.account_type
            normal_balance = account.normal_balance
            classification = account.classification

            if form.parent_id.data:
                # Child account - inherit from parent
                parent = db.session.get(Account, form.parent_id.data)
                if parent:
                    account_type = parent.account_type
                    normal_balance = parent.normal_balance
                    classification = parent.classification
            else:
                # Parent account - use form data
                account_type = form.account_type.data
                # Default normal_balance from account type when not explicitly supplied
                normal_balance = form.normal_balance.data or DEFAULT_NORMAL_BALANCE.get(account_type, account.normal_balance)
                classification = form.classification.data if form.classification.data else None
                # Require classification for Asset and Liability types
                if account_type in TYPES_NEEDING_CLASSIFICATION and not classification:
                    flash('Classification (Current or Non-Current) is required for Asset and Liability accounts.', 'error')
                    return render_template('accounts/form.html', form=form, account=account)

            # Prepare change data (only changed fields)
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'account_type': account_type,
                'classification': classification,
                'normal_balance': normal_balance,
                'parent_id': form.parent_id.data,
                'description': form.description.data
            }

            # Create change request
            change_request = AccountChangeRequest(
                change_type='update',
                account_id=id,
                change_data=json.dumps(change_data),
                requested_by=current_user.username,
                requested_at=ph_now(),
                status='pending',
                request_reason=form.request_reason.data.strip()
            )

            # Check if can auto-approve
            if can_auto_approve():
                # Capture old values for audit
                old_values = {
                    'code': account.code,
                    'name': account.name,
                    'account_type': account.account_type,
                    'classification': account.classification,
                    'normal_balance': account.normal_balance,
                    'parent_id': account.parent_id,
                    'description': account.description
                }

                # Auto-approve and update account immediately
                account.code = form.code.data
                account.name = form.name.data
                account.parent_id = form.parent_id.data
                account.description = form.description.data
                account.account_type = account_type
                account.normal_balance = normal_balance
                account.classification = classification

                change_request.status = 'approved'
                change_request.reviewed_by = current_user.username
                change_request.reviewed_at = ph_now()

                db.session.add(change_request)
                db.session.commit()

                # Audit log for change request submission and approval
                log_audit(
                    module='account',
                    action='update',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                    old_values=old_values,
                    new_values=change_data,
                    notes='Auto-approved (single accountant)'
                )

                flash('Account updated successfully! (Auto-approved - you are the only accountant)', 'success')
            else:
                # Save pending request
                db.session.add(change_request)
                db.session.commit()

                # Audit log for change request submission
                log_audit(
                    module='account',
                    action='update',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                    new_values=change_data,
                    notes=f'Pending approval. Reason: {change_request.request_reason}'
                )

                flash(PENDING_SUBMITTED_MESSAGE, 'success')

            return redirect(url_for('accounts.list_accounts'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating update request", exc_info=True)
            log_exception(e, severity='ERROR', module='accounts.update_request')
            db.session.rollback()
            flash(f'Error creating update request: {str(e)}', 'error')

    return render_template('accounts/form.html', form=form, account=account)


@accounts_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete account - submits for approval"""
    try:
        account = db.get_or_404(Account, id)

        # Reason for change is required (collected in the delete modal)
        request_reason = (request.form.get('request_reason') or '').strip()
        if not request_reason:
            flash('A reason for the change is required to submit a deletion request.', 'error')
            return redirect(url_for('accounts.list_accounts'))
        if len(request_reason) > 500:
            flash('Reason must be 500 characters or less.', 'error')
            return redirect(url_for('accounts.list_accounts'))

        # Block duplicate pending requests for the same account
        existing_request = find_pending_request(account_id=id)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('accounts.list_accounts'))

        # Store account data for audit trail
        change_data = {
            'code': account.code,
            'name': account.name,
            'account_type': account.account_type,
            'classification': account.classification,
            'normal_balance': account.normal_balance,
            'parent_id': account.parent_id,
            'description': account.description
        }

        # Create change request
        change_request = AccountChangeRequest(
            change_type='delete',
            account_id=id,
            change_data=json.dumps(change_data),
            requested_by=current_user.username,
            requested_at=ph_now(),
            status='pending',
            request_reason=request_reason
        )

        # Check if can auto-approve
        if can_auto_approve():
            # Auto-approve and delete account immediately
            db.session.delete(account)

            change_request.status = 'approved'
            change_request.reviewed_by = current_user.username
            change_request.reviewed_at = ph_now()

            db.session.add(change_request)
            db.session.commit()

            # Audit log for change request submission and approval
            log_audit(
                module='account',
                action='delete',
                record_id=change_request.id,
                record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                old_values=change_data,
                notes='Auto-approved (single accountant)'
            )

            flash('Account deleted successfully! (Auto-approved - you are the only accountant)', 'success')
        else:
            # Save pending request
            db.session.add(change_request)
            db.session.commit()

            # Audit log for change request submission
            log_audit(
                module='account',
                action='delete',
                record_id=change_request.id,
                record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                old_values=change_data,
                notes=f'Pending approval. Reason: {request_reason}'
            )

            flash(PENDING_SUBMITTED_MESSAGE, 'success')

    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error creating deletion request", exc_info=True)
        log_exception(e, severity='ERROR', module='accounts.delete_request')
        db.session.rollback()
        flash(f'Error creating deletion request: {str(e)}', 'error')

    return redirect(url_for('accounts.list_accounts'))


@accounts_bp.route('/pending-approvals')
@login_required
@accountant_or_admin_required
def pending_approvals():
    """View all pending approval requests"""
    pending_requests = AccountChangeRequest.query.filter_by(status='pending').order_by(AccountChangeRequest.requested_at.desc()).all()
    return render_template('accounts/pending_approvals.html', pending_requests=pending_requests)


@accounts_bp.route('/change-requests')
@login_required
@accountant_or_admin_required
def change_requests():
    """Request history: all account change requests with status, reviewer, and
    review notes — lets a requester see why a request was rejected."""
    all_requests = AccountChangeRequest.query.order_by(AccountChangeRequest.requested_at.desc()).all()
    return render_template('accounts/change_requests.html', requests=all_requests)


@accounts_bp.route('/approve/<int:request_id>', methods=['POST'])
@login_required
@accountant_or_admin_required
def approve_request(request_id):
    """Approve a pending change request"""
    try:
        change_request = db.get_or_404(AccountChangeRequest, request_id)

        # Check if user can approve this request
        if not change_request.can_be_approved_by(current_user.username):
            flash('You cannot approve your own request when there are other accountants available.', 'error')
            return redirect(url_for('accounts.pending_approvals'))

        if change_request.status != 'pending':
            flash('This request has already been processed.', 'error')
            return redirect(url_for('accounts.pending_approvals'))

        # Apply the change
        change_data = json.loads(change_request.change_data)
        old_values = None

        if change_request.change_type == 'create':
            # Re-check uniqueness at approval time (TOCTOU): the code/name may
            # have been taken since this request was submitted.
            if Account.query.filter_by(code=change_data.get('code')).first():
                flash(f'Account code "{change_data.get("code")}" already exists. '
                      f'This request cannot be approved.', 'error')
                return redirect(url_for('accounts.pending_approvals'))
            if Account.query.filter_by(name=change_data.get('name')).first():
                flash(f'Account name "{change_data.get("name")}" already exists. '
                      f'This request cannot be approved.', 'error')
                return redirect(url_for('accounts.pending_approvals'))

            # Create new account
            account = Account(**change_data)
            db.session.add(account)

        elif change_request.change_type == 'update':
            # Update existing account
            account = db.session.get(Account, change_request.account_id)
            if account:
                # Capture old values before update
                old_values = {
                    'code': account.code,
                    'name': account.name,
                    'account_type': account.account_type,
                    'classification': account.classification,
                    'normal_balance': account.normal_balance,
                    'parent_id': account.parent_id,
                    'description': account.description
                }
                for key, value in change_data.items():
                    setattr(account, key, value)
            else:
                flash('Account no longer exists.', 'error')
                return redirect(url_for('accounts.pending_approvals'))

        elif change_request.change_type == 'delete':
            # Delete account
            account = db.session.get(Account, change_request.account_id)
            if account:
                old_values = change_data  # Already contains account data
                db.session.delete(account)
            else:
                flash('Account already deleted.', 'warning')

        # Mark request as approved
        change_request.status = 'approved'
        change_request.reviewed_by = current_user.username
        change_request.reviewed_at = ph_now()

        db.session.commit()

        # Audit log for approval
        log_audit(
            module='account',
            action=change_request.change_type,
            record_id=change_request.id,
            record_identifier=f'Change Request: {change_data.get("code")} - {change_data.get("name")}',
            old_values=old_values,
            new_values=change_data if change_request.change_type != 'delete' else None,
            notes=f'Approved by {current_user.username}'
        )

        flash(f'Account {change_request.change_type} request approved successfully!', 'success')

    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error approving account change request", exc_info=True)
        log_exception(e, severity='ERROR', module='accounts.approve')
        db.session.rollback()
        flash(f'Error approving request: {str(e)}', 'error')

    return redirect(url_for('accounts.pending_approvals'))


@accounts_bp.route('/reject/<int:request_id>', methods=['POST'])
@login_required
@accountant_or_admin_required
def reject_request(request_id):
    """Reject a pending change request"""
    try:
        change_request = db.get_or_404(AccountChangeRequest, request_id)

        # Check if user can review this request
        if not change_request.can_be_approved_by(current_user.username):
            flash('You cannot reject your own request when there are other accountants available.', 'error')
            return redirect(url_for('accounts.pending_approvals'))

        if change_request.status != 'pending':
            flash('This request has already been processed.', 'error')
            return redirect(url_for('accounts.pending_approvals'))

        # Get rejection reason from form
        rejection_reason = request.form.get('rejection_reason', 'No reason provided')

        # Get change data for audit log
        change_data = json.loads(change_request.change_data)

        # Mark request as rejected
        change_request.status = 'rejected'
        change_request.reviewed_by = current_user.username
        change_request.reviewed_at = ph_now()
        change_request.rejection_reason = rejection_reason

        db.session.commit()

        # Audit log for rejection
        log_audit(
            module='account',
            action='reject',
            record_id=change_request.id,
            record_identifier=f'Change Request: {change_data.get("code")} - {change_data.get("name")}',
            old_values=change_data,
            notes=f'Rejected by {current_user.username}: {rejection_reason}'
        )

        flash(f'Account {change_request.change_type} request rejected.', 'warning')

    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error rejecting account change request", exc_info=True)
        log_exception(e, severity='ERROR', module='accounts.reject')
        db.session.rollback()
        flash(f'Error rejecting request: {str(e)}', 'error')

    return redirect(url_for('accounts.pending_approvals'))
