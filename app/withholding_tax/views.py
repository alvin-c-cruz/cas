"""
Withholding Tax views with approval workflow
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.withholding_tax.models import WithholdingTax, WithholdingTaxChangeRequest
from app.withholding_tax.forms import WithholdingTaxForm, WithholdingTaxChangeReviewForm
from app.utils import ph_now
from app.audit.utils import log_audit, model_to_dict
from app.notifications.utils import create_notification
from app.utils.change_requests import process_create_change_request
from app.utils.admin_approval import (
    admin_required, sole_full_access_user_can_auto_approve,
    another_active_reviewer_exists, tax_edit_may_auto_approve, tax_rate_changed)
from app.utils.cache_helpers import clear_withholding_tax_cache
import json

withholding_tax_bp = Blueprint('withholding_tax', __name__, template_folder='templates')


def _wht_account_choices(placeholder='-- None --'):
    """Active leaf accounts for WHT GL pickers (groups are not postable)."""
    from app.accounts.models import Account
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
    choices = [(0, placeholder)]
    choices += [(a.id, f'{a.code} : {a.name}') for a in accounts if a.id not in parent_ids]
    return choices


PENDING_SUBMITTED_MESSAGE = ('Change request submitted — pending review. '
                             'It will appear under Action Items until approved or rejected.')


def find_pending_request(withholding_tax_id=None, code=None):
    """
    Find an existing PENDING change request targeting the same record.

    For update/delete pass withholding_tax_id. For create pass the proposed code
    (pending create requests have no withholding_tax_id; the code lives in proposed_data).
    """
    pending = WithholdingTaxChangeRequest.query.filter_by(status='pending')
    if withholding_tax_id is not None:
        return pending.filter(WithholdingTaxChangeRequest.withholding_tax_id == withholding_tax_id).first()
    if code is not None:
        create_requests = pending.filter(
            WithholdingTaxChangeRequest.withholding_tax_id.is_(None),
            WithholdingTaxChangeRequest.action == 'create')
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


@withholding_tax_bp.route('/')
@login_required
@admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')
def list_withholding_tax():
    """List all withholding tax"""
    withholding_tax = WithholdingTax.query.order_by(WithholdingTax.code).all()

    # Get pending change requests for display
    pending_requests = WithholdingTaxChangeRequest.query.filter_by(status='pending').all()

    # Record ids with an open pending change request (for "Pending change" row badges)
    pending_record_ids = {r.withholding_tax_id for r in pending_requests if r.withholding_tax_id}

    return render_template('withholding_tax/list.html',
                         withholding_tax=withholding_tax,
                         pending_requests=pending_requests,
                         pending_record_ids=pending_record_ids)


@withholding_tax_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')
def create():
    """Create new withholding tax - submits for approval"""
    form = WithholdingTaxForm()
    form.payable_account_id.choices = _wht_account_choices('-- No payable account --')
    form.receivable_account_id.choices = _wht_account_choices('-- No receivable account --')

    if form.validate_on_submit():
        # Check for duplicate code
        existing_code = WithholdingTax.query.filter_by(code=form.code.data).first()
        if existing_code:
            flash(f'ATC "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('withholding_tax/form.html', form=form, withholding_tax=None)

        # Check for duplicate name
        existing_name = WithholdingTax.query.filter_by(name=form.name.data).first()
        if existing_name:
            flash(f'Withholding tax name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('withholding_tax/form.html', form=form, withholding_tax=None)

        # Block duplicate pending requests for the same proposed code
        existing_request = find_pending_request(code=form.code.data)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('withholding_tax.list_withholding_tax'))

        try:
            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'sales_name': form.sales_name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'payable_account_id': form.payable_account_id.data or None,
                'receivable_account_id': form.receivable_account_id.data or None,
            }

            # Shared create flow (mirrors vat_categories) — auto-approve or
            # pending change request, with audit + flash.
            result = process_create_change_request(
                model_cls=WithholdingTax,
                cr_cls=WithholdingTaxChangeRequest,
                module='withholding_tax',
                noun='Withholding tax',
                change_data=change_data,
                auto_approve=sole_full_access_user_can_auto_approve(),
                list_endpoint='withholding_tax.list_withholding_tax',
                approved_note='Auto-approved (single admin)'
            )
            clear_withholding_tax_cache()
            return result

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating withholding tax", exc_info=True)
            log_exception(e, severity='ERROR', module='withholding_tax.create')
            db.session.rollback()
            flash('An error occurred while creating the withholding tax. Please try again.', 'error')
            return render_template('withholding_tax/form.html', form=form, withholding_tax=None)

    return render_template('withholding_tax/form.html', form=form, withholding_tax=None)


@withholding_tax_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')
def edit(id):
    """Edit withholding tax - submits for approval"""
    withholding_tax = db.get_or_404(WithholdingTax, id)
    form = WithholdingTaxForm(obj=withholding_tax, require_reason=True)
    form.payable_account_id.choices = _wht_account_choices('-- No payable account --')
    form.receivable_account_id.choices = _wht_account_choices('-- No receivable account --')

    if form.validate_on_submit():
        # Check for duplicate code (excluding current)
        existing_code = WithholdingTax.query.filter(
            WithholdingTax.code == form.code.data,
            WithholdingTax.id != id
        ).first()
        if existing_code:
            flash(f'ATC "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('withholding_tax/form.html', form=form, withholding_tax=withholding_tax)

        # Check for duplicate name (excluding current)
        existing_name = WithholdingTax.query.filter(
            WithholdingTax.name == form.name.data,
            WithholdingTax.id != id
        ).first()
        if existing_name:
            flash(f'Withholding tax name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('withholding_tax/form.html', form=form, withholding_tax=withholding_tax)

        # Block duplicate pending requests for the same record
        existing_request = find_pending_request(withholding_tax_id=id)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('withholding_tax.list_withholding_tax'))

        try:
            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'sales_name': form.sales_name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'payable_account_id': form.payable_account_id.data or None,
                'receivable_account_id': form.receivable_account_id.data or None,
            }

            # Check if auto-approval is allowed. A rate change must never auto-apply,
            # even for a lone reviewer — it always routes to a second reviewer.
            if tax_edit_may_auto_approve(withholding_tax.rate, change_data['rate']):
                # Capture old values before update
                old_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])

                # Update withholding tax directly
                withholding_tax.code = change_data['code']
                withholding_tax.name = change_data['name']
                withholding_tax.sales_name = change_data['sales_name']
                withholding_tax.description = change_data['description']
                withholding_tax.rate = change_data['rate']
                withholding_tax.is_active = change_data['is_active']
                withholding_tax.payable_account_id = change_data['payable_account_id']
                withholding_tax.receivable_account_id = change_data['receivable_account_id']
                withholding_tax.updated_by_id = current_user.id
                withholding_tax.updated_at = ph_now()

                # Audit log for auto-approved update
                log_audit(
                    module='withholding_tax',
                    action='update',
                    record_id=withholding_tax.id,
                    record_identifier=f'{withholding_tax.code} - {withholding_tax.name}',
                    old_values=old_values,
                    new_values=change_data,
                    notes=f'Auto-approved (single admin). Reason: {form.request_reason.data.strip()}'
                )

                db.session.commit()
                clear_withholding_tax_cache()
                flash(f'Withholding tax "{withholding_tax.name}" has been updated successfully.', 'success')
                return redirect(url_for('withholding_tax.list_withholding_tax'))
            else:
                # Create change request for approval
                change_request = WithholdingTaxChangeRequest(
                    action='update',
                    status='pending',
                    withholding_tax_id=withholding_tax.id,
                    proposed_data=json.dumps(change_data),
                    requested_by_id=current_user.id,
                    requested_at=ph_now(),
                    request_reason=form.request_reason.data.strip()
                )
                db.session.add(change_request)
                db.session.flush()  # Get the ID before commit

                # Audit log for update change request submission
                old_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])
                log_audit(
                    module='withholding_tax',
                    action='update',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {withholding_tax.code} - {withholding_tax.name}',
                    old_values=old_values,
                    new_values=change_data,
                    notes=f'Pending approval. Reason: {change_request.request_reason}'
                )

                db.session.commit()
                flash(PENDING_SUBMITTED_MESSAGE, 'success')
                return redirect(url_for('withholding_tax.list_withholding_tax'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating withholding tax", exc_info=True)
            log_exception(e, severity='ERROR', module='withholding_tax.update')
            db.session.rollback()
            flash('An error occurred while updating the withholding tax. Please try again.', 'error')
            return render_template('withholding_tax/form.html', form=form, withholding_tax=withholding_tax)

    # Pre-fill form with existing data
    if request.method == 'GET':
        form.code.data = withholding_tax.code
        form.name.data = withholding_tax.name
        form.sales_name.data = withholding_tax.sales_name
        form.description.data = withholding_tax.description
        form.rate.data = withholding_tax.rate
        form.is_active.data = '1' if withholding_tax.is_active else '0'
        form.payable_account_id.data = withholding_tax.payable_account_id or 0
        form.receivable_account_id.data = withholding_tax.receivable_account_id or 0

    return render_template('withholding_tax/form.html', form=form, withholding_tax=withholding_tax)


@withholding_tax_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')
def delete(id):
    """Delete withholding tax - submits for approval"""
    withholding_tax = db.get_or_404(WithholdingTax, id)

    # Reason for change is required (collected in the delete modal)
    request_reason = (request.form.get('request_reason') or '').strip()
    if not request_reason:
        flash('A reason for the change is required to submit a deletion request.', 'error')
        return redirect(url_for('withholding_tax.list_withholding_tax'))
    if len(request_reason) > 500:
        flash('Reason must be 500 characters or less.', 'error')
        return redirect(url_for('withholding_tax.list_withholding_tax'))

    # Block duplicate pending requests for the same record
    existing_request = find_pending_request(withholding_tax_id=id)
    if existing_request:
        flash_duplicate_pending(existing_request)
        return redirect(url_for('withholding_tax.list_withholding_tax'))

    try:
        # Check if auto-approval is allowed
        if sole_full_access_user_can_auto_approve():
            # Capture values before delete
            old_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])
            wt_identifier = f'{withholding_tax.code} - {withholding_tax.name}'
            wt_id = withholding_tax.id
            wt_name = withholding_tax.name

            # Delete withholding tax directly
            db.session.delete(withholding_tax)

            # Audit log for auto-approved deletion
            log_audit(
                module='withholding_tax',
                action='delete',
                record_id=wt_id,
                record_identifier=wt_identifier,
                old_values=old_values,
                notes=f'Auto-approved (single admin). Reason: {request_reason}'
            )

            db.session.commit()
            clear_withholding_tax_cache()
            flash(f'Withholding tax "{wt_name}" has been deleted successfully.', 'success')
        else:
            # Create change request for approval
            change_request = WithholdingTaxChangeRequest(
                action='delete',
                status='pending',
                withholding_tax_id=withholding_tax.id,
                proposed_data=json.dumps({'name': withholding_tax.name, 'code': withholding_tax.code}),
                requested_by_id=current_user.id,
                requested_at=ph_now(),
                request_reason=request_reason
            )
            db.session.add(change_request)
            db.session.flush()  # Get the ID before commit

            # Audit log for delete change request submission
            old_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])
            log_audit(
                module='withholding_tax',
                action='delete',
                record_id=change_request.id,
                record_identifier=f'Change Request: {withholding_tax.code} - {withholding_tax.name}',
                old_values=old_values,
                notes=f'Pending approval. Reason: {request_reason}'
            )

            db.session.commit()
            flash(PENDING_SUBMITTED_MESSAGE, 'success')

        return redirect(url_for('withholding_tax.list_withholding_tax'))

    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting withholding tax", exc_info=True)
        log_exception(e, severity='ERROR', module='withholding_tax.delete')
        db.session.rollback()
        flash('An error occurred while deleting the withholding tax. Please try again.', 'error')
        return redirect(url_for('withholding_tax.list_withholding_tax'))


@withholding_tax_bp.route('/change-requests')
@login_required
@admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')
def change_requests():
    """View all change requests (pending, approved, rejected)"""
    all_requests = WithholdingTaxChangeRequest.query.order_by(WithholdingTaxChangeRequest.requested_at.desc()).all()

    # Parse JSON data for each request
    import json
    requests_with_data = []
    for req in all_requests:
        req_dict = {
            'id': req.id,
            'action': req.action,
            'status': req.status,
            'withholding_tax': req.withholding_tax,
            'requested_by': req.requested_by,
            'requested_at': req.requested_at,
            'requested_by_id': req.requested_by_id,
            'request_reason': req.request_reason,
            'proposed_data': json.loads(req.proposed_data) if req.proposed_data else {}
        }
        requests_with_data.append(req_dict)

    return render_template('withholding_tax/change_requests.html', requests=requests_with_data)


@withholding_tax_bp.route('/change-requests/<int:id>/review', methods=['GET', 'POST'])
@login_required
@admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')
def review_change_request(id):
    """Review and approve/reject a change request"""
    change_request = db.get_or_404(WithholdingTaxChangeRequest, id)

    # Cannot review own requests when another admin exists (four-eyes rule)
    if change_request.requested_by_id == current_user.id and another_active_reviewer_exists():
        flash('You cannot review your own change request.', 'error')
        return redirect(url_for('withholding_tax.change_requests'))

    # Already reviewed
    if change_request.status != 'pending':
        flash('This change request has already been reviewed.', 'info')
        return redirect(url_for('withholding_tax.change_requests'))

    form = WithholdingTaxChangeReviewForm()

    # Rate-change gate: approving a tax-RATE change requires a review note; the
    # review screen shows the old -> new rate.
    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
    old_rate = change_request.withholding_tax.rate if change_request.withholding_tax else None
    new_rate = proposed_data.get('rate')
    rate_changed = (change_request.action == 'update'
                    and tax_rate_changed(old_rate, new_rate))

    if form.validate_on_submit():
        try:
            action = form.action.data
            if action == 'approve' and rate_changed and not (form.review_notes.data or '').strip():
                flash('A review note is required to approve a change to a tax rate.', 'error')
                return redirect(url_for('withholding_tax.review_change_request', id=change_request.id))
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
                    if WithholdingTax.query.filter_by(code=proposed_data['code']).first():
                        db.session.rollback()
                        flash(f'ATC "{proposed_data["code"]}" already exists. '
                              f'This request cannot be approved.', 'error')
                        return redirect(url_for('withholding_tax.change_requests'))
                    if WithholdingTax.query.filter_by(name=proposed_data['name']).first():
                        db.session.rollback()
                        flash(f'Withholding tax name "{proposed_data["name"]}" already exists. '
                              f'This request cannot be approved.', 'error')
                        return redirect(url_for('withholding_tax.change_requests'))

                    # Create new withholding tax
                    withholding_tax = WithholdingTax(
                        code=proposed_data['code'],
                        name=proposed_data['name'],
                        sales_name=proposed_data.get('sales_name'),
                        description=proposed_data.get('description'),
                        rate=proposed_data['rate'],
                        is_active=proposed_data.get('is_active', True),
                        payable_account_id=proposed_data.get('payable_account_id') or None,
                        receivable_account_id=proposed_data.get('receivable_account_id') or None,
                        created_by_id=change_request.requested_by_id,
                        updated_by_id=current_user.id
                    )
                    db.session.add(withholding_tax)
                    db.session.flush()  # Get the ID before commit

                    # Audit log for approved creation
                    log_audit(
                        module='withholding_tax',
                        action='create',
                        record_id=withholding_tax.id,
                        record_identifier=f'{withholding_tax.code} - {withholding_tax.name}',
                        new_values=model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id']),
                        notes=f'Approved by {current_user.username}'
                    )
                    clear_withholding_tax_cache()

                    flash(f'Withholding tax "{withholding_tax.name}" has been created successfully.', 'success')

                elif change_request.action == 'update':
                    # Update existing withholding tax
                    withholding_tax = change_request.withholding_tax
                    if withholding_tax:
                        # Capture old values before update
                        old_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])

                        withholding_tax.code = proposed_data['code']
                        withholding_tax.name = proposed_data['name']
                        withholding_tax.sales_name = proposed_data.get('sales_name')
                        withholding_tax.description = proposed_data.get('description')
                        withholding_tax.rate = proposed_data['rate']
                        withholding_tax.is_active = proposed_data.get('is_active', True)
                        withholding_tax.payable_account_id = proposed_data.get('payable_account_id') or None
                        withholding_tax.receivable_account_id = proposed_data.get('receivable_account_id') or None
                        withholding_tax.updated_by_id = current_user.id
                        withholding_tax.updated_at = ph_now()

                        # Audit log for approved update
                        new_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])
                        log_audit(
                            module='withholding_tax',
                            action='update',
                            record_id=withholding_tax.id,
                            record_identifier=f'{withholding_tax.code} - {withholding_tax.name}',
                            old_values=old_values,
                            new_values=new_values,
                            notes=f'Approved by {current_user.username}'
                        )
                        clear_withholding_tax_cache()

                        flash(f'Withholding tax "{withholding_tax.name}" has been updated successfully.', 'success')

                elif change_request.action == 'delete':
                    # Delete withholding tax
                    withholding_tax = change_request.withholding_tax
                    if withholding_tax:
                        # Capture values before delete
                        old_values = model_to_dict(withholding_tax, ['code', 'name', 'sales_name', 'description', 'rate', 'is_active', 'payable_account_id', 'receivable_account_id'])
                        wt_identifier = f'{withholding_tax.code} - {withholding_tax.name}'
                        wt_id = withholding_tax.id
                        wt_name = withholding_tax.name

                        db.session.delete(withholding_tax)

                        # Audit log for approved deletion
                        log_audit(
                            module='withholding_tax',
                            action='delete',
                            record_id=wt_id,
                            record_identifier=wt_identifier,
                            old_values=old_values,
                            notes=f'Approved by {current_user.username}'
                        )
                        clear_withholding_tax_cache()

                        flash(f'Withholding tax "{wt_name}" has been deleted successfully.', 'success')

            else:
                # Log rejection to audit
                proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                record_identifier = f"{proposed_data.get('code', 'N/A')} - {proposed_data.get('name', 'Withholding Tax')}"

                log_audit(
                    module='withholding_tax',
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
                        message=f'Your Withholding Tax change request "{proposed_data.get("name", "N/A")}" ({change_request.action}) has been approved by {current_user.full_name}.',
                        category='success',
                        related_type='withholding_tax_request',
                        related_id=change_request.id
                    )
                else:
                    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                    reason_text = f' Reason: {change_request.review_notes}' if change_request.review_notes else ''
                    create_notification(
                        user_id=change_request.requested_by_id,
                        title='Change Request Rejected',
                        message=f'Your Withholding Tax change request "{proposed_data.get("name", "N/A")}" ({change_request.action}) has been rejected by {current_user.full_name}.{reason_text}',
                        category='error',
                        related_type='withholding_tax_request',
                        related_id=change_request.id
                    )

            db.session.commit()
            return redirect(url_for('withholding_tax.change_requests'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error reviewing withholding tax change request", exc_info=True)
            log_exception(e, severity='ERROR', module='withholding_tax.review_change_request')
            db.session.rollback()
            flash('An error occurred while processing the change request. Please try again.', 'error')
            return render_template('withholding_tax/review_change_request.html',
                                 change_request=change_request,
                                 form=form)

    return render_template('withholding_tax/review_change_request.html',
                         change_request=change_request,
                         proposed_data=proposed_data,
                         old_rate=old_rate, new_rate=new_rate,
                         rate_changed=rate_changed,
                         form=form)
