"""
VAT Category views with approval workflow
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.vat_categories.forms import VATCategoryForm, VATCategoryChangeReviewForm
from app.users.models import User
from app.accounts.models import Account
from app.utils import ph_now
from app.audit.utils import log_audit, model_to_dict
from app.notifications.utils import create_notification
import json

vat_categories_bp = Blueprint('vat_categories', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can modify VAT categories.', 'error')
            return redirect(url_for('vat_categories.list_vat_categories'))
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


def _input_vat_account_choices():
    """Active leaf accounts for the Input Tax picker (groups are not postable)."""
    # Deliberate direct query: the cached get_active_accounts() helper is never
    # invalidated on account create/update/approve, so using it risks a stale picker.
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
    choices = [(0, '-- None (zero-rate) --')]
    choices += [(a.id, f'{a.code} : {a.name}') for a in accounts
                if a.id not in parent_ids]
    return choices


PENDING_SUBMITTED_MESSAGE = ('Change request submitted — pending review. '
                             'It will appear under Action Items until approved or rejected.')


def find_pending_request(vat_category_id=None, code=None):
    """
    Find an existing PENDING change request targeting the same record.

    For update/delete pass vat_category_id. For create pass the proposed code
    (pending create requests have no vat_category_id; the code lives in proposed_data).
    """
    pending = VATCategoryChangeRequest.query.filter_by(status='pending')
    if vat_category_id is not None:
        return pending.filter(VATCategoryChangeRequest.vat_category_id == vat_category_id).first()
    if code is not None:
        create_requests = pending.filter(
            VATCategoryChangeRequest.vat_category_id.is_(None),
            VATCategoryChangeRequest.action == 'create')
        for req in create_requests.all():
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            if proposed.get('code') == code:
                return req
    return None


def flash_duplicate_pending(existing_request):
    """Flash a consistent error message about an existing pending change request."""
    requested_by = existing_request.requested_by.username if existing_request.requested_by else 'unknown'
    requested_on = (existing_request.requested_at.strftime('%b %d, %Y')
                    if existing_request.requested_at else 'an earlier date')
    flash(f'A pending change request for this record already exists '
          f'(submitted by {requested_by} on {requested_on}). '
          f'It must be reviewed before another change can be submitted.', 'error')


@vat_categories_bp.route('/')
@login_required
def list_vat_categories():
    """List all VAT categories"""
    vat_categories = VATCategory.query.order_by(VATCategory.code).all()

    # Get pending change requests for display
    pending_requests = VATCategoryChangeRequest.query.filter_by(status='pending').all()

    # Record ids with an open pending change request (for "Pending change" row badges)
    pending_record_ids = {r.vat_category_id for r in pending_requests if r.vat_category_id}

    return render_template('vat_categories/list.html',
                         vat_categories=vat_categories,
                         pending_requests=pending_requests,
                         pending_record_ids=pending_record_ids)


@vat_categories_bp.route('/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new VAT category - submits for approval"""
    form = VATCategoryForm()
    form.input_vat_account_id.choices = _input_vat_account_choices()

    if form.validate_on_submit():
        # Check for duplicate code
        existing_code = VATCategory.query.filter_by(code=form.code.data).first()
        if existing_code:
            flash(f'VAT code "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=None)

        # Check for duplicate name
        existing_name = VATCategory.query.filter_by(name=form.name.data).first()
        if existing_name:
            flash(f'VAT name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=None)

        # Block duplicate pending requests for the same proposed code
        existing_request = find_pending_request(code=form.code.data)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('vat_categories.list_vat_categories'))

        try:
            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'input_vat_account_id': form.input_vat_account_id.data or None
            }

            # Check if auto-approval is allowed
            if can_auto_approve():
                # Create VAT category directly
                vat_category = VATCategory(
                    code=change_data['code'],
                    name=change_data['name'],
                    description=change_data['description'],
                    rate=change_data['rate'],
                    is_active=change_data['is_active'],
                    input_vat_account_id=change_data['input_vat_account_id'],
                    created_by_id=current_user.id,
                    updated_by_id=current_user.id
                )
                db.session.add(vat_category)
                db.session.flush()  # Get the ID before commit

                # Audit log for auto-approved creation
                log_audit(
                    module='vat_category',
                    action='create',
                    record_id=vat_category.id,
                    record_identifier=f'{vat_category.code} - {vat_category.name}',
                    new_values=change_data,
                    notes=f'Auto-approved (single accountant). Reason: {form.request_reason.data.strip()}'
                )

                db.session.commit()
                flash(f'VAT category "{vat_category.name}" has been created successfully.', 'success')
                return redirect(url_for('vat_categories.list_vat_categories'))
            else:
                # Create change request for approval
                change_request = VATCategoryChangeRequest(
                    action='create',
                    status='pending',
                    proposed_data=json.dumps(change_data),
                    requested_by_id=current_user.id,
                    requested_at=ph_now(),
                    request_reason=form.request_reason.data.strip()
                )
                db.session.add(change_request)
                db.session.flush()  # Get the ID before commit

                # Audit log for change request submission
                log_audit(
                    module='vat_category',
                    action='create',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
                    new_values=change_data,
                    notes=f'Pending approval. Reason: {change_request.request_reason}'
                )

                db.session.commit()
                flash(PENDING_SUBMITTED_MESSAGE, 'success')
                return redirect(url_for('vat_categories.list_vat_categories'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating VAT category", exc_info=True)
            log_exception(e, severity='ERROR', module='vat_categories.create')
            db.session.rollback()
            flash(f'Error creating VAT category: {str(e)}', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=None)

    return render_template('vat_categories/form.html', form=form, vat_category=None)


@vat_categories_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit VAT category - submits for approval"""
    vat_category = VATCategory.query.get_or_404(id)
    form = VATCategoryForm(obj=vat_category)
    form.input_vat_account_id.choices = _input_vat_account_choices()

    if form.validate_on_submit():
        # Check for duplicate code (excluding current)
        existing_code = VATCategory.query.filter(
            VATCategory.code == form.code.data,
            VATCategory.id != id
        ).first()
        if existing_code:
            flash(f'VAT code "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=vat_category)

        # Check for duplicate name (excluding current)
        existing_name = VATCategory.query.filter(
            VATCategory.name == form.name.data,
            VATCategory.id != id
        ).first()
        if existing_name:
            flash(f'VAT name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=vat_category)

        # Block duplicate pending requests for the same record
        existing_request = find_pending_request(vat_category_id=id)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('vat_categories.list_vat_categories'))

        try:
            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'input_vat_account_id': form.input_vat_account_id.data or None
            }

            # Check if auto-approval is allowed
            if can_auto_approve():
                # Capture old values before update
                old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])

                # Update VAT category directly
                vat_category.code = change_data['code']
                vat_category.name = change_data['name']
                vat_category.description = change_data['description']
                vat_category.rate = change_data['rate']
                vat_category.is_active = change_data['is_active']
                vat_category.input_vat_account_id = change_data['input_vat_account_id']
                vat_category.updated_by_id = current_user.id
                vat_category.updated_at = ph_now()

                # Audit log for auto-approved update
                log_audit(
                    module='vat_category',
                    action='update',
                    record_id=vat_category.id,
                    record_identifier=f'{vat_category.code} - {vat_category.name}',
                    old_values=old_values,
                    new_values=change_data,
                    notes=f'Auto-approved (single accountant). Reason: {form.request_reason.data.strip()}'
                )

                db.session.commit()
                flash(f'VAT category "{vat_category.name}" has been updated successfully.', 'success')
                return redirect(url_for('vat_categories.list_vat_categories'))
            else:
                # Create change request for approval
                change_request = VATCategoryChangeRequest(
                    action='update',
                    status='pending',
                    vat_category_id=vat_category.id,
                    proposed_data=json.dumps(change_data),
                    requested_by_id=current_user.id,
                    requested_at=ph_now(),
                    request_reason=form.request_reason.data.strip()
                )
                db.session.add(change_request)
                db.session.flush()  # Get the ID before commit

                # Audit log for update change request submission
                old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])
                log_audit(
                    module='vat_category',
                    action='update',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {vat_category.code} - {vat_category.name}',
                    old_values=old_values,
                    new_values=change_data,
                    notes=f'Pending approval. Reason: {change_request.request_reason}'
                )

                db.session.commit()
                flash(PENDING_SUBMITTED_MESSAGE, 'success')
                return redirect(url_for('vat_categories.list_vat_categories'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating VAT category", exc_info=True)
            log_exception(e, severity='ERROR', module='vat_categories.update')
            db.session.rollback()
            flash(f'Error updating VAT category: {str(e)}', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=vat_category)

    # Pre-fill form with existing data
    if request.method == 'GET':
        form.code.data = vat_category.code
        form.name.data = vat_category.name
        form.description.data = vat_category.description
        form.rate.data = vat_category.rate
        form.input_vat_account_id.data = vat_category.input_vat_account_id or 0
        form.is_active.data = '1' if vat_category.is_active else '0'

    return render_template('vat_categories/form.html', form=form, vat_category=vat_category)


@vat_categories_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete VAT category - submits for approval"""
    vat_category = VATCategory.query.get_or_404(id)

    # Reason for change is required (collected in the delete modal)
    request_reason = (request.form.get('request_reason') or '').strip()
    if not request_reason:
        flash('A reason for the change is required to submit a deletion request.', 'error')
        return redirect(url_for('vat_categories.list_vat_categories'))
    if len(request_reason) > 500:
        flash('Reason must be 500 characters or less.', 'error')
        return redirect(url_for('vat_categories.list_vat_categories'))

    # Block duplicate pending requests for the same record
    existing_request = find_pending_request(vat_category_id=id)
    if existing_request:
        flash_duplicate_pending(existing_request)
        return redirect(url_for('vat_categories.list_vat_categories'))

    try:
        # Check if auto-approval is allowed
        if can_auto_approve():
            # Capture values before delete
            old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])
            vat_identifier = f'{vat_category.code} - {vat_category.name}'
            vat_id = vat_category.id
            vat_name = vat_category.name

            # Delete VAT category directly
            db.session.delete(vat_category)

            # Audit log for auto-approved deletion
            log_audit(
                module='vat_category',
                action='delete',
                record_id=vat_id,
                record_identifier=vat_identifier,
                old_values=old_values,
                notes=f'Auto-approved (single accountant). Reason: {request_reason}'
            )

            db.session.commit()
            flash(f'VAT category "{vat_name}" has been deleted successfully.', 'success')
        else:
            # Create change request for approval
            change_request = VATCategoryChangeRequest(
                action='delete',
                status='pending',
                vat_category_id=vat_category.id,
                proposed_data=json.dumps({'name': vat_category.name, 'code': vat_category.code}),
                requested_by_id=current_user.id,
                requested_at=ph_now(),
                request_reason=request_reason
            )
            db.session.add(change_request)
            db.session.flush()  # Get the ID before commit

            # Audit log for delete change request submission
            old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])
            log_audit(
                module='vat_category',
                action='delete',
                record_id=change_request.id,
                record_identifier=f'Change Request: {vat_category.code} - {vat_category.name}',
                old_values=old_values,
                notes=f'Pending approval. Reason: {request_reason}'
            )

            db.session.commit()
            flash(PENDING_SUBMITTED_MESSAGE, 'success')

        return redirect(url_for('vat_categories.list_vat_categories'))

    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting VAT category", exc_info=True)
        log_exception(e, severity='ERROR', module='vat_categories.delete')
        db.session.rollback()
        flash(f'Error deleting VAT category: {str(e)}', 'error')
        return redirect(url_for('vat_categories.list_vat_categories'))


@vat_categories_bp.route('/change-requests')
@login_required
@accountant_or_admin_required
def change_requests():
    """View all change requests (pending, approved, rejected)"""
    all_requests = VATCategoryChangeRequest.query.order_by(VATCategoryChangeRequest.requested_at.desc()).all()

    # Parse JSON data for each request
    parsed = []
    for req in all_requests:
        proposed = json.loads(req.proposed_data) if req.proposed_data else {}
        parsed.append((req, proposed, proposed.get('input_vat_account_id')))

    # Batch-load all referenced input VAT accounts in one query
    account_ids = {acct_id for _, _, acct_id in parsed if acct_id}
    accounts_by_id = {}
    if account_ids:
        accounts_by_id = {
            account.id: account
            for account in Account.query.filter(Account.id.in_(account_ids)).all()
        }

    requests_with_data = []
    for req, proposed, proposed_account_id in parsed:
        req_dict = {
            'id': req.id,
            'action': req.action,
            'proposed_data': proposed,
            'input_vat_account': (accounts_by_id.get(proposed_account_id)
                                  if proposed_account_id else None),
            'requested_by_id': req.requested_by_id,
            'requested_by': req.requested_by,
            'requested_at': req.requested_at,
            'reviewed_by_id': req.reviewed_by_id,
            'reviewed_by': req.reviewed_by,
            'reviewed_at': req.reviewed_at,
            'status': req.status,
            'review_notes': req.review_notes,
            'request_reason': req.request_reason,
            'vat_category_id': req.vat_category_id,
            'vat_category': req.vat_category
        }
        requests_with_data.append(req_dict)

    return render_template('vat_categories/change_requests.html', requests=requests_with_data)


@vat_categories_bp.route('/change-requests/<int:id>/review', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def review_change_request(id):
    """Review and approve/reject a change request"""
    change_request = VATCategoryChangeRequest.query.get_or_404(id)

    # Cannot review own requests
    if change_request.requested_by_id == current_user.id:
        flash('You cannot review your own change request.', 'error')
        return redirect(url_for('vat_categories.change_requests'))

    # Already reviewed
    if change_request.status != 'pending':
        flash('This change request has already been reviewed.', 'info')
        return redirect(url_for('vat_categories.change_requests'))

    form = VATCategoryChangeReviewForm()

    # Parse proposed data and resolve the proposed Input Tax account for display
    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
    proposed_account_id = proposed_data.get('input_vat_account_id')
    proposed_account = db.session.get(Account, proposed_account_id) if proposed_account_id else None

    if form.validate_on_submit():
        try:
            action = form.action.data
            change_request.status = 'approved' if action == 'approve' else 'rejected'
            change_request.reviewed_by_id = current_user.id
            change_request.reviewed_at = ph_now()
            change_request.review_notes = form.review_notes.data

            if action == 'approve':
                # Apply the changes
                proposed_data = json.loads(change_request.proposed_data)

                if change_request.action == 'create':
                    # Create new VAT category
                    vat_category = VATCategory(
                        code=proposed_data['code'],
                        name=proposed_data['name'],
                        description=proposed_data.get('description'),
                        rate=proposed_data['rate'],
                        is_active=proposed_data.get('is_active', True),
                        input_vat_account_id=proposed_data.get('input_vat_account_id'),
                        created_by_id=change_request.requested_by_id,
                        updated_by_id=current_user.id
                    )
                    db.session.add(vat_category)
                    db.session.flush()  # Get the ID before commit

                    # Audit log for approved creation
                    log_audit(
                        module='vat_category',
                        action='create',
                        record_id=vat_category.id,
                        record_identifier=f'{vat_category.code} - {vat_category.name}',
                        new_values=model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id']),
                        notes=f'Approved by {current_user.username}'
                    )

                    flash(f'VAT category "{vat_category.name}" has been created successfully.', 'success')

                elif change_request.action == 'update':
                    # Update existing VAT category
                    vat_category = change_request.vat_category
                    if vat_category:
                        # Capture old values before update
                        old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])

                        vat_category.code = proposed_data['code']
                        vat_category.name = proposed_data['name']
                        vat_category.description = proposed_data.get('description')
                        vat_category.rate = proposed_data['rate']
                        vat_category.is_active = proposed_data.get('is_active', True)
                        vat_category.input_vat_account_id = proposed_data.get('input_vat_account_id')
                        vat_category.updated_by_id = current_user.id
                        vat_category.updated_at = ph_now()

                        # Audit log for approved update
                        new_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])
                        log_audit(
                            module='vat_category',
                            action='update',
                            record_id=vat_category.id,
                            record_identifier=f'{vat_category.code} - {vat_category.name}',
                            old_values=old_values,
                            new_values=new_values,
                            notes=f'Approved by {current_user.username}'
                        )

                        flash(f'VAT category "{vat_category.name}" has been updated successfully.', 'success')

                elif change_request.action == 'delete':
                    # Delete VAT category
                    vat_category = change_request.vat_category
                    if vat_category:
                        # Capture values before delete
                        old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id'])
                        vat_identifier = f'{vat_category.code} - {vat_category.name}'
                        vat_id = vat_category.id
                        vat_name = vat_category.name

                        db.session.delete(vat_category)

                        # Audit log for approved deletion
                        log_audit(
                            module='vat_category',
                            action='delete',
                            record_id=vat_id,
                            record_identifier=vat_identifier,
                            old_values=old_values,
                            notes=f'Approved by {current_user.username}'
                        )

                        flash(f'VAT category "{vat_name}" has been deleted successfully.', 'success')

            else:
                # Log rejection to audit
                proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                record_identifier = f"{proposed_data.get('code', 'N/A')} - {proposed_data.get('name', 'VAT Category')}"

                log_audit(
                    module='vat_category',
                    action='reject',
                    record_id=change_request.id,
                    record_identifier=record_identifier,
                    old_values=proposed_data,
                    notes=f'Rejected by {current_user.username}: {change_request.review_notes or "No reason provided"}'
                )

                flash('Change request has been rejected.', 'info')

            # Notify the requester about the outcome
            if change_request.requested_by_id:
                if action == 'approve':
                    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                    create_notification(
                        user_id=change_request.requested_by_id,
                        title='Change Request Approved',
                        message=f'Your VAT Category change request "{proposed_data.get("name", "N/A")}" ({change_request.action}) has been approved by {current_user.full_name}.',
                        category='success',
                        related_type='vat_category_request',
                        related_id=change_request.id
                    )
                else:
                    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                    reason_text = f' Reason: {change_request.review_notes}' if change_request.review_notes else ''
                    create_notification(
                        user_id=change_request.requested_by_id,
                        title='Change Request Rejected',
                        message=f'Your VAT Category change request "{proposed_data.get("name", "N/A")}" ({change_request.action}) has been rejected by {current_user.full_name}.{reason_text}',
                        category='error',
                        related_type='vat_category_request',
                        related_id=change_request.id
                    )

            db.session.commit()
            return redirect(url_for('vat_categories.change_requests'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error reviewing VAT category change request", exc_info=True)
            log_exception(e, severity='ERROR', module='vat_categories.review_change_request')
            db.session.rollback()
            flash(f'Error processing change request: {str(e)}', 'error')
            return render_template('vat_categories/review_change_request.html',
                                 change_request=change_request,
                                 proposed_data=proposed_data,
                                 proposed_account=proposed_account,
                                 form=form)

    return render_template('vat_categories/review_change_request.html',
                         change_request=change_request,
                         proposed_data=proposed_data,
                         proposed_account=proposed_account,
                         form=form)
