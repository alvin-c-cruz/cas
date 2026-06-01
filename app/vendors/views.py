"""
Vendor management views (Admin and Accountant only)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.vendors.models import Vendor
from app.vendors.forms import VendorForm

vendors_bp = Blueprint('vendors', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role for vendor management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can manage vendors.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@vendors_bp.route('/vendors')
@login_required
def list_vendors():
    """List all vendors"""
    vendors = Vendor.query.order_by(Vendor.code).all()
    return render_template('vendors/list.html', vendors=vendors)


@vendors_bp.route('/vendors/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new vendor"""
    form = VendorForm()

    if form.validate_on_submit():
        # Check for duplicate vendor code
        existing = Vendor.query.filter_by(code=form.code.data).first()
        if existing:
            flash(f'Vendor code "{form.code.data}" already exists.', 'error')
            return render_template('vendors/form.html', form=form, vendor=None)

        try:
            vendor = Vendor(
                code=form.code.data,
                name=form.name.data,
                contact_person=form.contact_person.data,
                phone=form.phone.data,
                tin=form.tin.data,
                payment_terms=form.payment_terms.data,
                default_vat=form.default_vat.data if form.default_vat.data else None,
                default_wt=form.default_wt.data if form.default_wt.data else None,
                address=form.address.data,
                email=form.email.data,
                is_active=form.is_active.data if form.is_active.data is not None else True
            )
            db.session.add(vendor)
            db.session.commit()
            flash(f'Vendor "{vendor.name}" created successfully!', 'success')
            return redirect(url_for('vendors.list_vendors'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating vendor: {str(e)}', 'error')

    # Set default for is_active checkbox
    if request.method == 'GET':
        form.is_active.data = True
        form.payment_terms.data = 'Net 30'

    return render_template('vendors/form.html', form=form, vendor=None)


@vendors_bp.route('/vendors/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit(id):
    """Edit vendor"""
    vendor = Vendor.query.get_or_404(id)
    form = VendorForm(obj=vendor)

    if form.validate_on_submit():
        # Check for duplicate code (excluding current vendor)
        existing = Vendor.query.filter(Vendor.code == form.code.data, Vendor.id != id).first()
        if existing:
            flash(f'Vendor code "{form.code.data}" already exists.', 'error')
            return render_template('vendors/form.html', form=form, vendor=vendor)

        try:
            vendor.code = form.code.data
            vendor.name = form.name.data
            vendor.contact_person = form.contact_person.data
            vendor.phone = form.phone.data
            vendor.tin = form.tin.data
            vendor.payment_terms = form.payment_terms.data
            vendor.default_vat = form.default_vat.data if form.default_vat.data else None
            vendor.default_wt = form.default_wt.data if form.default_wt.data else None
            vendor.address = form.address.data
            vendor.email = form.email.data
            vendor.is_active = form.is_active.data
            db.session.commit()
            flash(f'Vendor "{vendor.name}" updated successfully!', 'success')
            return redirect(url_for('vendors.list_vendors'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating vendor: {str(e)}', 'error')

    return render_template('vendors/form.html', form=form, vendor=vendor)


@vendors_bp.route('/vendors/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete vendor"""
    vendor = Vendor.query.get_or_404(id)

    try:
        vendor_name = vendor.name
        db.session.delete(vendor)
        db.session.commit()
        flash(f'Vendor "{vendor_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting vendor: {str(e)}', 'error')

    return redirect(url_for('vendors.list_vendors'))
