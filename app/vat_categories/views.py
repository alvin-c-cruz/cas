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
from app.utils import ph_now
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
    Check if current user can auto-approve their own changes.
    Returns True if there's only one accountant/admin in the system.
    """
    total_accountants = User.query.filter(
        User.role.in_(['accountant', 'admin']),
        User.is_active == True
    ).count()
    return total_accountants == 1


@vat_categories_bp.route('/')
@login_required
def list_vat_categories():
    """List all VAT categories"""
    vat_categories = VATCategory.query.order_by(VATCategory.code).all()

    # Get pending change requests for display
    pending_requests = VATCategoryChangeRequest.query.filter_by(status='pending').all()

    return render_template('vat_categories/list.html',
                         vat_categories=vat_categories,
                         pending_requests=pending_requests)


@vat_categories_bp.route('/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new VAT category - submits for approval"""
    form = VATCategoryForm()

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

        try:
            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True
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
                    created_by_id=current_user.id,
                    updated_by_id=current_user.id
                )
                db.session.add(vat_category)
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
                    requested_at=ph_now()
                )
                db.session.add(change_request)
                db.session.commit()
                flash(f'VAT category creation request for "{change_data["name"]}" has been submitted for approval.', 'info')
                return redirect(url_for('vat_categories.list_vat_categories'))

        except Exception as e:
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

        try:
            # Prepare change data
            change_data = {
                'code': form.code.data,
                'name': form.name.data,
                'description': form.description.data,
                'rate': float(form.rate.data),
                'is_active': bool(int(form.is_active.data)) if form.is_active.data else True
            }

            # Check if auto-approval is allowed
            if can_auto_approve():
                # Update VAT category directly
                vat_category.code = change_data['code']
                vat_category.name = change_data['name']
                vat_category.description = change_data['description']
                vat_category.rate = change_data['rate']
                vat_category.is_active = change_data['is_active']
                vat_category.updated_by_id = current_user.id
                vat_category.updated_at = ph_now()
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
                    requested_at=ph_now()
                )
                db.session.add(change_request)
                db.session.commit()
                flash(f'VAT category update request for "{vat_category.name}" has been submitted for approval.', 'info')
                return redirect(url_for('vat_categories.list_vat_categories'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating VAT category: {str(e)}', 'error')
            return render_template('vat_categories/form.html', form=form, vat_category=vat_category)

    # Pre-fill form with existing data
    if request.method == 'GET':
        form.code.data = vat_category.code
        form.name.data = vat_category.name
        form.description.data = vat_category.description
        form.rate.data = vat_category.rate
        form.is_active.data = '1' if vat_category.is_active else '0'

    return render_template('vat_categories/form.html', form=form, vat_category=vat_category)


@vat_categories_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete VAT category - submits for approval"""
    vat_category = VATCategory.query.get_or_404(id)

    try:
        # Check if auto-approval is allowed
        if can_auto_approve():
            # Delete VAT category directly
            db.session.delete(vat_category)
            db.session.commit()
            flash(f'VAT category "{vat_category.name}" has been deleted successfully.', 'success')
        else:
            # Create change request for approval
            change_request = VATCategoryChangeRequest(
                action='delete',
                status='pending',
                vat_category_id=vat_category.id,
                proposed_data=json.dumps({'name': vat_category.name, 'code': vat_category.code}),
                requested_by_id=current_user.id,
                requested_at=ph_now()
            )
            db.session.add(change_request)
            db.session.commit()
            flash(f'VAT category deletion request for "{vat_category.name}" has been submitted for approval.', 'info')

        return redirect(url_for('vat_categories.list_vat_categories'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting VAT category: {str(e)}', 'error')
        return redirect(url_for('vat_categories.list_vat_categories'))


@vat_categories_bp.route('/change-requests')
@login_required
@accountant_or_admin_required
def change_requests():
    """View all pending change requests"""
    pending_requests = VATCategoryChangeRequest.query.filter_by(status='pending').order_by(VATCategoryChangeRequest.requested_at.desc()).all()
    return render_template('vat_categories/change_requests.html', requests=pending_requests)


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
                        created_by_id=change_request.requested_by_id,
                        updated_by_id=current_user.id
                    )
                    db.session.add(vat_category)
                    flash(f'VAT category "{vat_category.name}" has been created successfully.', 'success')

                elif change_request.action == 'update':
                    # Update existing VAT category
                    vat_category = change_request.vat_category
                    if vat_category:
                        vat_category.code = proposed_data['code']
                        vat_category.name = proposed_data['name']
                        vat_category.description = proposed_data.get('description')
                        vat_category.rate = proposed_data['rate']
                        vat_category.is_active = proposed_data.get('is_active', True)
                        vat_category.updated_by_id = current_user.id
                        vat_category.updated_at = ph_now()
                        flash(f'VAT category "{vat_category.name}" has been updated successfully.', 'success')

                elif change_request.action == 'delete':
                    # Delete VAT category
                    vat_category = change_request.vat_category
                    if vat_category:
                        vat_name = vat_category.name
                        db.session.delete(vat_category)
                        flash(f'VAT category "{vat_name}" has been deleted successfully.', 'success')

            else:
                flash('Change request has been rejected.', 'info')

            db.session.commit()
            return redirect(url_for('vat_categories.change_requests'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error processing change request: {str(e)}', 'error')
            return render_template('vat_categories/review_change_request.html',
                                 change_request=change_request,
                                 form=form)

    # Parse proposed data for display
    proposed_data = json.loads(change_request.proposed_data) if change_request.proposed_data else {}

    return render_template('vat_categories/review_change_request.html',
                         change_request=change_request,
                         proposed_data=proposed_data,
                         form=form)
