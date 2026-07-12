"""
VAT Category views with approval workflow
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
from app.vat_categories.forms import VATCategoryForm, VATCategoryChangeReviewForm
from app.accounts.models import Account
from app.utils import ph_now
from app.audit.utils import log_audit, model_to_dict
from app.notifications.utils import create_notification
from app.utils.change_requests import process_create_change_request
from app.utils.admin_approval import (
    admin_required, sole_full_access_user_can_auto_approve,
    another_active_reviewer_exists, tax_edit_may_auto_approve, tax_rate_changed)
from app.utils.cache_helpers import clear_vat_cache
import json

vat_categories_bp = Blueprint('vat_categories', __name__, template_folder='templates')


def _vat_account_choices(placeholder='-- None --'):
    """Active leaf accounts for VAT pickers (groups are not postable).

    Deliberate direct query: the cached get_active_accounts() helper is never
    invalidated on account create/update/approve, so using it risks a stale picker.
    """
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
    choices = [(0, placeholder)]
    choices += [(a.id, f'{a.code} : {a.name}') for a in accounts if a.id not in parent_ids]
    return choices


def _input_vat_account_choices():
    return _vat_account_choices(placeholder='-- Select Input Tax Account --')


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
@admin_required('vat_categories.list_vat_categories', 'VAT Categories')
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
@admin_required('vat_categories.list_vat_categories', 'VAT Categories')
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
                'input_vat_account_id': form.input_vat_account_id.data or None,
                'transaction_nature': form.transaction_nature.data,
            }

            # Shared create flow (mirrors withholding_tax) — auto-approve or
            # pending change request, with audit + flash.
            auto_approve = sole_full_access_user_can_auto_approve()
            result = process_create_change_request(
                model_cls=VATCategory,
                cr_cls=VATCategoryChangeRequest,
                module='vat_category',
                noun='VAT category',
                change_data=change_data,
                auto_approve=auto_approve,
                list_endpoint='vat_categories.list_vat_categories',
                approved_note='Auto-approved (single admin)'
            )
            if auto_approve:
                clear_vat_cache()
            return result

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating VAT category", exc_info=True)
            log_exception(e, severity='ERROR', module='vat_categories.create')
            db.session.rollback()
            flash('An error occurred while creating the VAT category. Please try again.', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=None)

    return render_template('vat_categories/form.html', form=form, vat_category=None)


@vat_categories_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required('vat_categories.list_vat_categories', 'VAT Categories')
def edit(id):
    """Edit VAT category - submits for approval"""
    vat_category = db.get_or_404(VATCategory, id)
    form = VATCategoryForm(obj=vat_category, require_reason=True)
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
                'input_vat_account_id': form.input_vat_account_id.data or None,
                'transaction_nature': form.transaction_nature.data,
            }

            # Check if auto-approval is allowed. A rate change must never auto-apply,
            # even for a lone reviewer — it always routes to a second reviewer.
            if tax_edit_may_auto_approve(vat_category.rate, change_data['rate']):
                # Capture old values before update
                old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])

                # Update VAT category directly
                vat_category.code = change_data['code']
                vat_category.name = change_data['name']
                vat_category.description = change_data['description']
                vat_category.rate = change_data['rate']
                vat_category.is_active = change_data['is_active']
                vat_category.input_vat_account_id = change_data['input_vat_account_id']
                vat_category.transaction_nature = change_data['transaction_nature']
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
                    notes=f'Auto-approved (single admin). Reason: {form.request_reason.data.strip()}'
                )

                db.session.commit()
                clear_vat_cache()
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
                old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])
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
            flash('An error occurred while updating the VAT category. Please try again.', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=vat_category)

    # Pre-fill form with existing data
    if request.method == 'GET':
        form.code.data = vat_category.code
        form.name.data = vat_category.name
        form.description.data = vat_category.description
        form.rate.data = vat_category.rate
        form.input_vat_account_id.data = vat_category.input_vat_account_id or 0
        form.transaction_nature.data = vat_category.transaction_nature
        form.is_active.data = '1' if vat_category.is_active else '0'

    return render_template('vat_categories/form.html', form=form, vat_category=vat_category)


@vat_categories_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required('vat_categories.list_vat_categories', 'VAT Categories')
def delete(id):
    """Delete VAT category - submits for approval"""
    vat_category = db.get_or_404(VATCategory, id)

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
        if sole_full_access_user_can_auto_approve():
            # Capture values before delete
            old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])
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
                notes=f'Auto-approved (single admin). Reason: {request_reason}'
            )

            db.session.commit()
            clear_vat_cache()
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
            old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])
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
        flash('An error occurred while deleting the VAT category. Please try again.', 'error')
        return redirect(url_for('vat_categories.list_vat_categories'))


@vat_categories_bp.route('/change-requests')
@login_required
@admin_required('vat_categories.list_vat_categories', 'VAT Categories')
def change_requests():
    """View all change requests (pending, approved, rejected)"""
    all_requests = VATCategoryChangeRequest.query.order_by(VATCategoryChangeRequest.requested_at.desc()).all()

    # Parse JSON data for each request
    parsed = []
    for req in all_requests:
        proposed = json.loads(req.proposed_data) if req.proposed_data else {}
        parsed.append((req, proposed,
                       proposed.get('input_vat_account_id')))

    # Batch-load all referenced input VAT accounts in one query
    account_ids = {in_id for _, _, in_id in parsed if in_id}
    accounts_by_id = {}
    if account_ids:
        accounts_by_id = {
            account.id: account
            for account in Account.query.filter(Account.id.in_(account_ids)).all()
        }

    requests_with_data = []
    for req, proposed, proposed_input_id in parsed:
        req_dict = {
            'id': req.id,
            'action': req.action,
            'proposed_data': proposed,
            'input_vat_account': (accounts_by_id.get(proposed_input_id)
                                  if proposed_input_id else None),
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


@vat_categories_bp.route('/change-requests/<int:id>/withdraw', methods=['POST'])
@login_required
def withdraw_change_request(id):
    """Withdraw the requester's own still-pending change request.

    Not an approval shortcut: retracting your own unreviewed ask is the
    opposite of self-approving it. No admin_required gate beyond
    authentication -- the requester-only check happens here, and only the
    original requester may withdraw (mirrors the four-eyes intent without
    weakening the rate-change review gate, which this route never touches).
    """
    change_request = db.get_or_404(VATCategoryChangeRequest, id)

    if change_request.requested_by_id != current_user.id:
        flash('You can only withdraw your own pending request.', 'error')
        return redirect(url_for('vat_categories.change_requests'))

    if change_request.status != 'pending':
        flash('This request has already been processed.', 'error')
        return redirect(url_for('vat_categories.change_requests'))

    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
    record_identifier = (f'{change_request.vat_category.code} - {change_request.vat_category.name}'
                        if change_request.vat_category
                        else f"{proposed_data.get('code', 'N/A')} - {proposed_data.get('name', 'VAT Category')}")

    change_request.status = 'withdrawn'
    change_request.reviewed_by_id = current_user.id
    change_request.reviewed_at = ph_now()
    change_request.review_notes = 'Withdrawn by requester.'

    log_audit(
        module='vat_category',
        action='withdraw',
        record_id=change_request.id,
        record_identifier=record_identifier,
        notes='Withdrawn by requester.'
    )

    db.session.commit()
    flash('Change request withdrawn.', 'success')
    return redirect(url_for('vat_categories.change_requests'))


@vat_categories_bp.route('/change-requests/<int:id>/review', methods=['GET', 'POST'])
@login_required
@admin_required('vat_categories.list_vat_categories', 'VAT Categories')
def review_change_request(id):
    """Review and approve/reject a change request"""
    change_request = db.get_or_404(VATCategoryChangeRequest, id)

    # Cannot review own requests when another admin exists (four-eyes rule)
    if change_request.requested_by_id == current_user.id and another_active_reviewer_exists():
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

    # Rate-change gate: approving a tax-RATE change requires a review note; the
    # review screen shows the old -> new rate.
    old_rate = change_request.vat_category.rate if change_request.vat_category else None
    new_rate = proposed_data.get('rate')
    rate_changed = (change_request.action == 'update'
                    and tax_rate_changed(old_rate, new_rate))

    if form.validate_on_submit():
        try:
            action = form.action.data
            if action == 'approve' and rate_changed and not (form.review_notes.data or '').strip():
                flash('A review note is required to approve a change to a tax rate.', 'error')
                return redirect(url_for('vat_categories.review_change_request', id=change_request.id))
            change_request.status = 'approved' if action == 'approve' else 'rejected'
            change_request.reviewed_by_id = current_user.id
            change_request.reviewed_at = ph_now()
            change_request.review_notes = form.review_notes.data

            if action == 'approve':
                # Apply the changes
                proposed_data = json.loads(change_request.proposed_data)

                if change_request.action == 'create':
                    # Re-check uniqueness at approval time (TOCTOU): the code/name
                    # may have been taken since this request was submitted.
                    if VATCategory.query.filter_by(code=proposed_data['code']).first():
                        db.session.rollback()
                        flash(f'VAT code "{proposed_data["code"]}" already exists. '
                              f'This request cannot be approved.', 'error')
                        return redirect(url_for('vat_categories.change_requests'))
                    if VATCategory.query.filter_by(name=proposed_data['name']).first():
                        db.session.rollback()
                        flash(f'VAT name "{proposed_data["name"]}" already exists. '
                              f'This request cannot be approved.', 'error')
                        return redirect(url_for('vat_categories.change_requests'))

                    # Create new VAT category
                    vat_category = VATCategory(
                        code=proposed_data['code'],
                        name=proposed_data['name'],
                        description=proposed_data.get('description'),
                        rate=proposed_data['rate'],
                        is_active=proposed_data.get('is_active', True),
                        input_vat_account_id=proposed_data.get('input_vat_account_id'),
                        transaction_nature=proposed_data.get('transaction_nature'),
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
                        new_values=model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature']),
                        notes=f'Approved by {current_user.username}'
                    )

                    flash(f'VAT category "{vat_category.name}" has been created successfully.', 'success')

                elif change_request.action == 'update':
                    # Update existing VAT category
                    vat_category = change_request.vat_category
                    if vat_category:
                        # Capture old values before update
                        old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])

                        vat_category.code = proposed_data['code']
                        vat_category.name = proposed_data['name']
                        vat_category.description = proposed_data.get('description')
                        vat_category.rate = proposed_data['rate']
                        vat_category.is_active = proposed_data.get('is_active', True)
                        vat_category.input_vat_account_id = proposed_data.get('input_vat_account_id')
                        vat_category.transaction_nature = proposed_data.get('transaction_nature')
                        vat_category.updated_by_id = current_user.id
                        vat_category.updated_at = ph_now()

                        # Audit log for approved update
                        new_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])
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
                        old_values = model_to_dict(vat_category, ['code', 'name', 'description', 'rate', 'is_active', 'input_vat_account_id', 'transaction_nature'])
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
            if action == 'approve':
                clear_vat_cache()
            return redirect(url_for('vat_categories.change_requests'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error reviewing VAT category change request", exc_info=True)
            log_exception(e, severity='ERROR', module='vat_categories.review_change_request')
            db.session.rollback()
            flash('An error occurred while processing the change request. Please try again.', 'error')
            return render_template('vat_categories/review_change_request.html',
                                 change_request=change_request,
                                 proposed_data=proposed_data,
                                 proposed_account=proposed_account,
                                 form=form)

    return render_template('vat_categories/review_change_request.html',
                         change_request=change_request,
                         proposed_data=proposed_data,
                         proposed_account=proposed_account,
                         old_rate=old_rate, new_rate=new_rate,
                         rate_changed=rate_changed,
                         form=form)
