"""
Sales VAT Category views with admin-only access and approval workflow.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.sales_vat_categories.models import SalesVATCategory, SalesVATCategoryChangeRequest
from app.sales_vat_categories.forms import SalesVATCategoryForm, SalesVATCategoryChangeReviewForm
from app.accounts.models import Account
from app.utils import ph_now
from app.audit.utils import log_audit, model_to_dict
from app.notifications.utils import create_notification
from app.utils.change_requests import process_create_change_request
from app.utils.admin_approval import admin_required, sole_full_access_user_can_auto_approve, another_active_reviewer_exists
from app.utils.cache_helpers import clear_sales_vat_cache
import json

sales_vat_categories_bp = Blueprint('sales_vat_categories', __name__, template_folder='templates')


def _output_vat_account_choices():
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
    choices = [(0, '-- None (zero-rate) --')]
    choices += [(a.id, f'{a.code} : {a.name}') for a in accounts if a.id not in parent_ids]
    return choices


PENDING_SUBMITTED_MESSAGE = ('Change request submitted — pending review. '
                             'It will appear under Action Items until approved or rejected.')


def find_pending_request(sales_vat_category_id=None, code=None):
    pending = SalesVATCategoryChangeRequest.query.filter_by(status='pending')
    if sales_vat_category_id is not None:
        return pending.filter(
            SalesVATCategoryChangeRequest.sales_vat_category_id == sales_vat_category_id
        ).first()
    if code is not None:
        create_requests = pending.filter(
            SalesVATCategoryChangeRequest.sales_vat_category_id.is_(None),
            SalesVATCategoryChangeRequest.action == 'create')
        for req in create_requests.all():
            proposed = json.loads(req.proposed_data) if req.proposed_data else {}
            if proposed.get('code') == code:
                return req
    return None


def flash_duplicate_pending(existing_request):
    requested_by = existing_request.requested_by.username if existing_request.requested_by else 'unknown'
    requested_on = (existing_request.requested_at.strftime('%b %d, %Y')
                    if existing_request.requested_at else 'an earlier date')
    flash(f'A pending change request for this record already exists '
          f'(submitted by {requested_by} on {requested_on}). '
          f'It must be reviewed before another change can be submitted.', 'error')


@sales_vat_categories_bp.route('/')
@login_required
@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')
def list_sales_vat_categories():
    """List all Sales VAT categories"""
    sales_vat_categories = SalesVATCategory.query.order_by(SalesVATCategory.code).all()

    pending_requests = SalesVATCategoryChangeRequest.query.filter_by(status='pending').all()
    pending_record_ids = {r.sales_vat_category_id for r in pending_requests if r.sales_vat_category_id}

    return render_template('sales_vat_categories/list.html',
                           sales_vat_categories=sales_vat_categories,
                           pending_requests=pending_requests,
                           pending_record_ids=pending_record_ids)


@sales_vat_categories_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')
def create():
    """Create new Sales VAT category - submits for approval"""
    form = SalesVATCategoryForm()
    form.output_vat_account_id.choices = _output_vat_account_choices()

    if form.validate_on_submit():
        existing_code = SalesVATCategory.query.filter_by(code=form.code.data).first()
        if existing_code:
            flash(f'Sales VAT code "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=None)

        existing_name = SalesVATCategory.query.filter_by(name=form.name.data).first()
        if existing_name:
            flash(f'Sales VAT name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=None)

        existing_request = find_pending_request(code=form.code.data)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))

        try:
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'transaction_nature': form.transaction_nature.data,
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'output_vat_account_id': form.output_vat_account_id.data or None,
            }

            result = process_create_change_request(
                model_cls=SalesVATCategory,
                cr_cls=SalesVATCategoryChangeRequest,
                module='sales_vat_category',
                noun='Sales VAT category',
                change_data=change_data,
                auto_approve=sole_full_access_user_can_auto_approve(),
                list_endpoint='sales_vat_categories.list_sales_vat_categories',
                approved_note='Auto-approved (single admin)'
            )
            clear_sales_vat_cache()
            return result

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error('Error creating Sales VAT category', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_vat_categories.create')
            db.session.rollback()
            flash('An error occurred while creating the Sales VAT category. Please try again.', 'error')
            return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=None)

    return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=None)


@sales_vat_categories_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')
def edit(id):
    """Edit Sales VAT category - submits for approval"""
    sales_vat_category = db.get_or_404(SalesVATCategory, id)
    form = SalesVATCategoryForm(obj=sales_vat_category, require_reason=True)
    form.output_vat_account_id.choices = _output_vat_account_choices()

    if form.validate_on_submit():
        existing_code = SalesVATCategory.query.filter(
            SalesVATCategory.code == form.code.data,
            SalesVATCategory.id != id
        ).first()
        if existing_code:
            flash(f'Sales VAT code "{form.code.data}" already exists. Please use a different code.', 'error')
            return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=sales_vat_category)

        existing_name = SalesVATCategory.query.filter(
            SalesVATCategory.name == form.name.data,
            SalesVATCategory.id != id
        ).first()
        if existing_name:
            flash(f'Sales VAT name "{form.name.data}" already exists. Please use a different name.', 'error')
            return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=sales_vat_category)

        existing_request = find_pending_request(sales_vat_category_id=id)
        if existing_request:
            flash_duplicate_pending(existing_request)
            return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))

        try:
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'transaction_nature': form.transaction_nature.data,
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True,
                'output_vat_account_id': form.output_vat_account_id.data or None,
            }

            if sole_full_access_user_can_auto_approve():
                old_values = model_to_dict(sales_vat_category, [
                    'code', 'name', 'description', 'rate', 'transaction_nature',
                    'is_active', 'output_vat_account_id'
                ])

                sales_vat_category.code = change_data['code']
                sales_vat_category.name = change_data['name']
                sales_vat_category.description = change_data['description']
                sales_vat_category.rate = change_data['rate']
                sales_vat_category.transaction_nature = change_data['transaction_nature']
                sales_vat_category.is_active = change_data['is_active']
                sales_vat_category.output_vat_account_id = change_data['output_vat_account_id']
                sales_vat_category.updated_by_id = current_user.id
                sales_vat_category.updated_at = ph_now()

                log_audit(
                    module='sales_vat_category',
                    action='update',
                    record_id=sales_vat_category.id,
                    record_identifier=f'{sales_vat_category.code} - {sales_vat_category.name}',
                    old_values=old_values,
                    new_values=change_data,
                    notes=f'Auto-approved (single admin). Reason: {form.request_reason.data.strip()}'
                )

                db.session.commit()
                clear_sales_vat_cache()
                flash(f'Sales VAT category "{sales_vat_category.name}" has been updated successfully.', 'success')
                return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))
            else:
                change_request = SalesVATCategoryChangeRequest(
                    action='update',
                    status='pending',
                    sales_vat_category_id=sales_vat_category.id,
                    proposed_data=json.dumps(change_data),
                    requested_by_id=current_user.id,
                    requested_at=ph_now(),
                    request_reason=form.request_reason.data.strip()
                )
                db.session.add(change_request)
                db.session.flush()

                old_values = model_to_dict(sales_vat_category, [
                    'code', 'name', 'description', 'rate', 'transaction_nature',
                    'is_active', 'output_vat_account_id'
                ])
                log_audit(
                    module='sales_vat_category',
                    action='update',
                    record_id=change_request.id,
                    record_identifier=f'Change Request: {sales_vat_category.code} - {sales_vat_category.name}',
                    old_values=old_values,
                    new_values=change_data,
                    notes=f'Pending approval. Reason: {change_request.request_reason}'
                )

                db.session.commit()
                clear_sales_vat_cache()
                flash(PENDING_SUBMITTED_MESSAGE, 'success')
                return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error('Error updating Sales VAT category', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_vat_categories.update')
            db.session.rollback()
            flash('An error occurred while updating the Sales VAT category. Please try again.', 'error')
            return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=sales_vat_category)

    if request.method == 'GET':
        form.code.data = sales_vat_category.code
        form.name.data = sales_vat_category.name
        form.description.data = sales_vat_category.description
        form.rate.data = sales_vat_category.rate
        form.transaction_nature.data = sales_vat_category.transaction_nature
        form.output_vat_account_id.data = sales_vat_category.output_vat_account_id or 0
        form.is_active.data = '1' if sales_vat_category.is_active else '0'

    return render_template('sales_vat_categories/form.html', form=form, sales_vat_category=sales_vat_category)


@sales_vat_categories_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')
def delete(id):
    """Delete Sales VAT category - submits for approval"""
    sales_vat_category = db.get_or_404(SalesVATCategory, id)

    request_reason = (request.form.get('request_reason') or '').strip()
    if not request_reason:
        flash('A reason for the change is required to submit a deletion request.', 'error')
        return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))
    if len(request_reason) > 500:
        flash('Reason must be 500 characters or less.', 'error')
        return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))

    existing_request = find_pending_request(sales_vat_category_id=id)
    if existing_request:
        flash_duplicate_pending(existing_request)
        return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))

    try:
        if sole_full_access_user_can_auto_approve():
            old_values = model_to_dict(sales_vat_category, [
                'code', 'name', 'description', 'rate', 'transaction_nature',
                'is_active', 'output_vat_account_id'
            ])
            svc_identifier = f'{sales_vat_category.code} - {sales_vat_category.name}'
            svc_id = sales_vat_category.id
            svc_name = sales_vat_category.name

            db.session.delete(sales_vat_category)

            log_audit(
                module='sales_vat_category',
                action='delete',
                record_id=svc_id,
                record_identifier=svc_identifier,
                old_values=old_values,
                notes=f'Auto-approved (single admin). Reason: {request_reason}'
            )

            db.session.commit()
            clear_sales_vat_cache()
            flash(f'Sales VAT category "{svc_name}" has been deleted successfully.', 'success')
        else:
            change_request = SalesVATCategoryChangeRequest(
                action='delete',
                status='pending',
                sales_vat_category_id=sales_vat_category.id,
                proposed_data=json.dumps({'name': sales_vat_category.name, 'code': sales_vat_category.code}),
                requested_by_id=current_user.id,
                requested_at=ph_now(),
                request_reason=request_reason
            )
            db.session.add(change_request)
            db.session.flush()

            old_values = model_to_dict(sales_vat_category, [
                'code', 'name', 'description', 'rate', 'transaction_nature',
                'is_active', 'output_vat_account_id'
            ])
            log_audit(
                module='sales_vat_category',
                action='delete',
                record_id=change_request.id,
                record_identifier=f'Change Request: {sales_vat_category.code} - {sales_vat_category.name}',
                old_values=old_values,
                notes=f'Pending approval. Reason: {request_reason}'
            )

            db.session.commit()
            clear_sales_vat_cache()
            flash(PENDING_SUBMITTED_MESSAGE, 'success')

        return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))

    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error('Error deleting Sales VAT category', exc_info=True)
        log_exception(e, severity='ERROR', module='sales_vat_categories.delete')
        db.session.rollback()
        flash('An error occurred while deleting the Sales VAT category. Please try again.', 'error')
        return redirect(url_for('sales_vat_categories.list_sales_vat_categories'))


@sales_vat_categories_bp.route('/change-requests')
@login_required
@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')
def change_requests():
    """View all change requests (pending, approved, rejected)"""
    all_requests = SalesVATCategoryChangeRequest.query.order_by(
        SalesVATCategoryChangeRequest.requested_at.desc()
    ).all()

    parsed = []
    for req in all_requests:
        proposed = json.loads(req.proposed_data) if req.proposed_data else {}
        parsed.append((req, proposed, proposed.get('output_vat_account_id')))

    account_ids = {out_id for _, _, out_id in parsed if out_id}
    accounts_by_id = {}
    if account_ids:
        accounts_by_id = {
            account.id: account
            for account in Account.query.filter(Account.id.in_(account_ids)).all()
        }

    requests_with_data = []
    for req, proposed, proposed_output_id in parsed:
        req_dict = {
            'id': req.id,
            'action': req.action,
            'proposed_data': proposed,
            'output_vat_account': (accounts_by_id.get(proposed_output_id)
                                   if proposed_output_id else None),
            'requested_by_id': req.requested_by_id,
            'requested_by': req.requested_by,
            'requested_at': req.requested_at,
            'reviewed_by_id': req.reviewed_by_id,
            'reviewed_by': req.reviewed_by,
            'reviewed_at': req.reviewed_at,
            'status': req.status,
            'review_notes': req.review_notes,
            'request_reason': req.request_reason,
            'sales_vat_category_id': req.sales_vat_category_id,
            'sales_vat_category': req.sales_vat_category,
        }
        requests_with_data.append(req_dict)

    return render_template('sales_vat_categories/change_requests.html', requests=requests_with_data)


@sales_vat_categories_bp.route('/change-requests/<int:id>/review', methods=['GET', 'POST'])
@login_required
@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')
def review_change_request(id):
    """Review and approve/reject a change request"""
    change_request = db.get_or_404(SalesVATCategoryChangeRequest, id)

    if change_request.requested_by_id == current_user.id and another_active_reviewer_exists():
        flash('You cannot review your own change request.', 'error')
        return redirect(url_for('sales_vat_categories.change_requests'))

    if change_request.status != 'pending':
        flash('This change request has already been reviewed.', 'info')
        return redirect(url_for('sales_vat_categories.change_requests'))

    form = SalesVATCategoryChangeReviewForm()

    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
    proposed_output_account_id = proposed_data.get('output_vat_account_id')
    proposed_output_account = (db.session.get(Account, proposed_output_account_id)
                               if proposed_output_account_id else None)

    if form.validate_on_submit():
        try:
            action = form.action.data
            change_request.status = 'approved' if action == 'approve' else 'rejected'
            change_request.reviewed_by_id = current_user.id
            change_request.reviewed_at = ph_now()
            change_request.review_notes = form.review_notes.data

            if action == 'approve':
                proposed_data = json.loads(change_request.proposed_data)

                if change_request.action == 'create':
                    if SalesVATCategory.query.filter_by(code=proposed_data['code']).first():
                        db.session.rollback()
                        flash(f'Sales VAT code "{proposed_data["code"]}" already exists. '
                              f'This request cannot be approved.', 'error')
                        return redirect(url_for('sales_vat_categories.change_requests'))
                    if SalesVATCategory.query.filter_by(name=proposed_data['name']).first():
                        db.session.rollback()
                        flash(f'Sales VAT name "{proposed_data["name"]}" already exists. '
                              f'This request cannot be approved.', 'error')
                        return redirect(url_for('sales_vat_categories.change_requests'))

                    sales_vat_category = SalesVATCategory(
                        code=proposed_data['code'],
                        name=proposed_data['name'],
                        description=proposed_data.get('description'),
                        rate=proposed_data['rate'],
                        transaction_nature=proposed_data.get('transaction_nature', 'regular'),
                        is_active=proposed_data.get('is_active', True),
                        output_vat_account_id=proposed_data.get('output_vat_account_id'),
                        created_by_id=change_request.requested_by_id,
                        updated_by_id=current_user.id
                    )
                    db.session.add(sales_vat_category)
                    db.session.flush()

                    log_audit(
                        module='sales_vat_category',
                        action='create',
                        record_id=sales_vat_category.id,
                        record_identifier=f'{sales_vat_category.code} - {sales_vat_category.name}',
                        new_values=model_to_dict(sales_vat_category, [
                            'code', 'name', 'description', 'rate', 'transaction_nature',
                            'is_active', 'output_vat_account_id'
                        ]),
                        notes=f'Approved by {current_user.username}'
                    )

                    flash(f'Sales VAT category "{sales_vat_category.name}" has been created successfully.', 'success')

                elif change_request.action == 'update':
                    sales_vat_category = change_request.sales_vat_category
                    if sales_vat_category:
                        old_values = model_to_dict(sales_vat_category, [
                            'code', 'name', 'description', 'rate', 'transaction_nature',
                            'is_active', 'output_vat_account_id'
                        ])

                        sales_vat_category.code = proposed_data['code']
                        sales_vat_category.name = proposed_data['name']
                        sales_vat_category.description = proposed_data.get('description')
                        sales_vat_category.rate = proposed_data['rate']
                        sales_vat_category.transaction_nature = proposed_data.get('transaction_nature', 'regular')
                        sales_vat_category.is_active = proposed_data.get('is_active', True)
                        sales_vat_category.output_vat_account_id = proposed_data.get('output_vat_account_id')
                        sales_vat_category.updated_by_id = current_user.id
                        sales_vat_category.updated_at = ph_now()

                        new_values = model_to_dict(sales_vat_category, [
                            'code', 'name', 'description', 'rate', 'transaction_nature',
                            'is_active', 'output_vat_account_id'
                        ])
                        log_audit(
                            module='sales_vat_category',
                            action='update',
                            record_id=sales_vat_category.id,
                            record_identifier=f'{sales_vat_category.code} - {sales_vat_category.name}',
                            old_values=old_values,
                            new_values=new_values,
                            notes=f'Approved by {current_user.username}'
                        )

                        flash(f'Sales VAT category "{sales_vat_category.name}" has been updated successfully.', 'success')

                elif change_request.action == 'delete':
                    sales_vat_category = change_request.sales_vat_category
                    if sales_vat_category:
                        old_values = model_to_dict(sales_vat_category, [
                            'code', 'name', 'description', 'rate', 'transaction_nature',
                            'is_active', 'output_vat_account_id'
                        ])
                        svc_identifier = f'{sales_vat_category.code} - {sales_vat_category.name}'
                        svc_id = sales_vat_category.id
                        svc_name = sales_vat_category.name

                        db.session.delete(sales_vat_category)

                        log_audit(
                            module='sales_vat_category',
                            action='delete',
                            record_id=svc_id,
                            record_identifier=svc_identifier,
                            old_values=old_values,
                            notes=f'Approved by {current_user.username}'
                        )

                        flash(f'Sales VAT category "{svc_name}" has been deleted successfully.', 'success')

            else:
                proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                record_identifier = f"{proposed_data.get('code', 'N/A')} - {proposed_data.get('name', 'Sales VAT Category')}"

                log_audit(
                    module='sales_vat_category',
                    action='reject',
                    record_id=change_request.id,
                    record_identifier=record_identifier,
                    old_values=proposed_data,
                    notes=f'Rejected by {current_user.username}: {change_request.review_notes or "No reason provided"}'
                )

                flash('Change request has been rejected.', 'info')

            if change_request.requested_by_id:
                if action == 'approve':
                    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                    create_notification(
                        user_id=change_request.requested_by_id,
                        title='Change Request Approved',
                        message=f'Your Sales VAT Category change request "{proposed_data.get("name", "N/A")}" ({change_request.action}) has been approved by {current_user.full_name}.',
                        category='success',
                        related_type='sales_vat_category_request',
                        related_id=change_request.id
                    )
                else:
                    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}
                    reason_text = f' Reason: {change_request.review_notes}' if change_request.review_notes else ''
                    create_notification(
                        user_id=change_request.requested_by_id,
                        title='Change Request Rejected',
                        message=f'Your Sales VAT Category change request "{proposed_data.get("name", "N/A")}" ({change_request.action}) has been rejected by {current_user.full_name}.{reason_text}',
                        category='error',
                        related_type='sales_vat_category_request',
                        related_id=change_request.id
                    )

            db.session.commit()
            clear_sales_vat_cache()
            return redirect(url_for('sales_vat_categories.change_requests'))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error('Error reviewing Sales VAT category change request', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_vat_categories.review_change_request')
            db.session.rollback()
            flash('An error occurred while processing the change request. Please try again.', 'error')
            return render_template('sales_vat_categories/review_change_request.html',
                                   change_request=change_request,
                                   proposed_data=proposed_data,
                                   proposed_output_account=proposed_output_account,
                                   form=form)

    return render_template('sales_vat_categories/review_change_request.html',
                           change_request=change_request,
                           proposed_data=proposed_data,
                           proposed_output_account=proposed_output_account,
                           form=form)
