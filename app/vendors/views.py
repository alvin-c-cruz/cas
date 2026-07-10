"""
Vendor management views (Admin and Accountant only)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from app import db
from app.utils import ph_now
from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
from app.vendors.forms import VendorForm
from app.vendors.utils import generate_next_vendor_code, populate_vat_category_choices
from app.audit.utils import log_create, log_update, log_delete, model_to_dict
from app.utils.export import export_to_excel, export_to_csv
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from datetime import datetime

vendors_bp = Blueprint('vendors', __name__, template_folder='templates')


def _wants_json():
    """True when the request is an AJAX/JSON call (modal quick-add)."""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role for vendor management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can manage vendors.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def staff_or_above_required(f):
    """Tier 1 vendor ops — staff, accountant, and admin allowed."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@vendors_bp.route('/vendors')
@login_required
def list_vendors():
    """List vendors with optional server-side search and pagination."""
    q = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int)
    query = Vendor.query.options(selectinload(Vendor.withholding_taxes))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Vendor.code.ilike(like),
            Vendor.name.ilike(like),
            Vendor.tin.ilike(like),
        ))
    pagination = query.order_by(Vendor.code).paginate(page=page, per_page=25, error_out=False)
    return render_template('vendors/list.html', vendors=pagination.items,
                           pagination=pagination, search_query=q)


def _payments_by_bill(ap_ids):
    """Map each bill (AP) id -> the posted CDVs that settled it, for the
    Paid-column popup. Returns {ap_id: [{'number','date','amount'}, ...]}.
    Only posted CDVs count toward amount_paid; draft/voided are excluded.
    """
    if not ap_ids:
        return {}
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
    rows = (
        CDVApLine.query
        .join(CashDisbursementVoucher, CDVApLine.cdv_id == CashDisbursementVoucher.id)
        .filter(CDVApLine.ap_id.in_(ap_ids),
                CashDisbursementVoucher.status == 'posted')
        .order_by(CashDisbursementVoucher.cdv_date, CashDisbursementVoucher.cdv_number)
        .all()
    )
    result = {}
    for line in rows:
        result.setdefault(line.ap_id, []).append({
            'number': line.cdv.cdv_number,
            'date': line.cdv.cdv_date.strftime('%d %b %Y'),
            'amount': float(line.amount_applied),
        })
    return result


@vendors_bp.route('/vendors/<int:id>')
@login_required
def detail(id):
    vendor = db.get_or_404(Vendor, id)
    tab = request.args.get('tab', 'overview')
    total_bills = AccountsPayable.query.filter_by(vendor_id=id).count()

    if tab == 'bills':
        page = request.args.get('page', 1, type=int)
        date_from_str = request.args.get('date_from', '')
        date_to_str = request.args.get('date_to', '')
        status_filter = request.args.get('status', 'all')

        from datetime import date as date_type
        query = AccountsPayable.query.filter_by(vendor_id=id)
        if date_from_str:
            try:
                query = query.filter(AccountsPayable.ap_date >= date_type.fromisoformat(date_from_str))
            except ValueError:
                pass
        if date_to_str:
            try:
                query = query.filter(AccountsPayable.ap_date <= date_type.fromisoformat(date_to_str))
            except ValueError:
                pass
        if status_filter and status_filter != 'all':
            query = query.filter(AccountsPayable.status == status_filter)

        pagination = query.order_by(AccountsPayable.ap_date.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        payments = _payments_by_bill([ap.id for ap in pagination.items])
        return render_template(
            'vendors/detail.html',
            vendor=vendor,
            tab='bills',
            total_bills=total_bills,
            pagination=pagination,
            payments=payments,
            date_from=date_from_str,
            date_to=date_to_str,
            status_filter=status_filter,
        )
    else:
        from app.vendors.utils import compute_ap_aging, compute_wht_ytd
        aging = compute_ap_aging(vendor.id)
        wht_ytd = compute_wht_ytd(vendor.id)
        return render_template(
            'vendors/detail.html',
            vendor=vendor,
            tab='overview',
            total_bills=total_bills,
            aging=aging,
            wht_ytd=wht_ytd,
        )


@vendors_bp.route('/vendors/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    """Create new vendor"""
    form = VendorForm()
    populate_vat_category_choices(form)

    if form.validate_on_submit():
        # Check for duplicate vendor code
        existing = Vendor.query.filter_by(code=form.code.data).first()
        if existing:
            if _wants_json():
                return jsonify(ok=False, errors={'code': f'Vendor code "{form.code.data}" already exists.'}), 422
            flash(f'Vendor code "{form.code.data}" already exists.', 'error')
            return render_template('vendors/form.html', form=form, vendor=None)

        # Check for duplicate vendor name (case-insensitive, warn-but-allow)
        _dup_name = Vendor.query.filter(
            func.lower(Vendor.name) == form.name.data.strip().lower()
        ).first()

        try:
            vendor = Vendor(
                code=form.code.data,
                name=form.name.data,
                contact_person=form.contact_person.data,
                phone=form.phone.data,
                email=form.email.data,
                tin=form.tin.data,
                payment_terms=form.payment_terms.data,
                address=form.address.data,
                check_payee_name=form.check_payee_name.data,
                postal_code=form.postal_code.data,
                default_vat_category=form.default_vat_category.data if form.default_vat_category.data else None,
                is_active=bool(int(form.is_active.data)) if form.is_active.data else True
            )

            # Handle dynamic withholding taxes
            withholding_tax_ids = request.form.getlist('withholding_tax_ids')
            if withholding_tax_ids:
                selected_wts = WithholdingTax.query.filter(WithholdingTax.id.in_(withholding_tax_ids)).all()
                vendor.withholding_taxes = selected_wts

            db.session.add(vendor)
            db.session.commit()

            # Audit log
            log_create(
                module='vendor',
                record_id=vendor.id,
                record_identifier=f'{vendor.code} - {vendor.name}',
                new_values=model_to_dict(vendor, ['code', 'name', 'contact_person', 'phone', 'email', 'tin', 'payment_terms', 'address', 'check_payee_name', 'postal_code', 'default_vat_category', 'is_active'])
            )

            if _wants_json():
                return jsonify(ok=True, vendor={
                    'id': vendor.id,
                    'label': f'{vendor.code} - {vendor.name}',
                })
            if _dup_name:
                flash(f"A vendor named '{vendor.name}' already exists.", 'warning')
            flash(f'Vendor "{vendor.name}" created successfully!', 'success')
            return redirect(url_for('vendors.list_vendors'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating vendor", exc_info=True)
            log_exception(e, severity='ERROR', module='vendors.create')
            db.session.rollback()
            flash(f'Error creating vendor: {str(e)}', 'error')

    if request.method == 'POST' and _wants_json():
        return jsonify(ok=False, errors={f: errs[0] for f, errs in form.errors.items()}), 422

    # Set defaults for new vendor
    if request.method == 'GET':
        form.code.data = generate_next_vendor_code()  # Auto-generate vendor code
        form.is_active.data = '1'  # Active by default
        form.payment_terms.data = 'Net 30'

    # Get active withholding taxes for the form
    withholding_taxes = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()

    return render_template('vendors/form.html', form=form, vendor=None, withholding_taxes=withholding_taxes)


@vendors_bp.route('/vendors/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    """Edit vendor"""
    vendor = db.get_or_404(Vendor, id)
    form = VendorForm(obj=vendor)
    populate_vat_category_choices(form)

    if form.validate_on_submit():
        # Check for duplicate code (excluding current vendor)
        existing = Vendor.query.filter(Vendor.code == form.code.data, Vendor.id != id).first()
        if existing:
            flash(f'Vendor code "{form.code.data}" already exists.', 'error')
            return render_template('vendors/form.html', form=form, vendor=vendor)

        # Check for duplicate vendor name (case-insensitive, warn-but-allow, self-excluded)
        _dup_name = Vendor.query.filter(
            func.lower(Vendor.name) == form.name.data.strip().lower(),
            Vendor.id != id
        ).first()

        try:
            # Capture old values before update
            old_values = model_to_dict(vendor, ['code', 'name', 'contact_person', 'phone', 'email', 'tin', 'payment_terms', 'address', 'check_payee_name', 'postal_code', 'default_vat_category', 'is_active'])

            vendor.code = form.code.data
            vendor.name = form.name.data
            vendor.contact_person = form.contact_person.data
            vendor.phone = form.phone.data
            vendor.email = form.email.data
            vendor.tin = form.tin.data
            vendor.payment_terms = form.payment_terms.data
            vendor.address = form.address.data
            vendor.check_payee_name = form.check_payee_name.data
            vendor.postal_code = form.postal_code.data
            vendor.default_vat_category = form.default_vat_category.data if form.default_vat_category.data else None
            vendor.is_active = bool(int(form.is_active.data))

            # Handle dynamic withholding taxes
            withholding_tax_ids = request.form.getlist('withholding_tax_ids')
            selected_wts = WithholdingTax.query.filter(WithholdingTax.id.in_(withholding_tax_ids)).all() if withholding_tax_ids else []
            vendor.withholding_taxes = selected_wts

            db.session.commit()

            # Audit log
            new_values = model_to_dict(vendor, ['code', 'name', 'contact_person', 'phone', 'email', 'tin', 'payment_terms', 'address', 'check_payee_name', 'postal_code', 'default_vat_category', 'is_active'])
            log_update(
                module='vendor',
                record_id=vendor.id,
                record_identifier=f'{vendor.code} - {vendor.name}',
                old_values=old_values,
                new_values=new_values
            )

            if _dup_name:
                flash(f"A vendor named '{vendor.name}' already exists.", 'warning')
            flash(f'Vendor "{vendor.name}" updated successfully!', 'success')
            return redirect(url_for('vendors.list_vendors'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating vendor", exc_info=True)
            log_exception(e, severity='ERROR', module='vendors.update')
            db.session.rollback()
            flash(f'Error updating vendor: {str(e)}', 'error')

    # Pre-populate form on GET request
    if request.method == 'GET':
        form.code.data = vendor.code
        form.name.data = vendor.name
        form.contact_person.data = vendor.contact_person
        form.phone.data = vendor.phone
        form.email.data = vendor.email
        form.tin.data = vendor.tin
        form.payment_terms.data = vendor.payment_terms
        form.address.data = vendor.address
        form.check_payee_name.data = vendor.check_payee_name
        form.postal_code.data = vendor.postal_code
        form.default_vat_category.data = vendor.default_vat_category
        form.is_active.data = '1' if vendor.is_active else '0'

    # Get active withholding taxes for the form
    withholding_taxes = WithholdingTax.query.filter_by(is_active=True).order_by(WithholdingTax.code).all()

    # Get selected withholding taxes for this vendor (using the new relationship if available)
    selected_wt_ids = []
    if hasattr(vendor, 'withholding_taxes'):
        selected_wt_ids = [wt.id for wt in vendor.withholding_taxes]

    return render_template('vendors/form.html', form=form, vendor=vendor,
                         withholding_taxes=withholding_taxes, selected_wt_ids=selected_wt_ids)


@vendors_bp.route('/vendors/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete vendor"""
    vendor = db.get_or_404(Vendor, id)

    bill_count = AccountsPayable.query.filter_by(vendor_id=vendor.id).count()
    from app.cash_disbursements.models import CashDisbursementVoucher
    cdv_count = CashDisbursementVoucher.query.filter_by(vendor_id=vendor.id).count()
    if bill_count or cdv_count:
        parts = []
        if bill_count:
            parts.append(f'{bill_count} purchase bill(s)')
        if cdv_count:
            parts.append(f'{cdv_count} cash disbursement(s)')
        flash(f'Cannot delete vendor "{vendor.name}": it is referenced by '
              f'{" and ".join(parts)}. Set it inactive instead.', 'error')
        return redirect(url_for('vendors.list_vendors'))

    try:
        # Capture values before delete
        old_values = model_to_dict(vendor, ['code', 'name', 'contact_person', 'phone', 'email', 'tin', 'payment_terms', 'address', 'check_payee_name', 'postal_code', 'default_vat_category', 'is_active'])
        vendor_identifier = f'{vendor.code} - {vendor.name}'
        vendor_id = vendor.id
        vendor_name = vendor.name

        db.session.delete(vendor)
        db.session.commit()

        # Audit log
        log_delete(
            module='vendor',
            record_id=vendor_id,
            record_identifier=vendor_identifier,
            old_values=old_values
        )

        flash(f'Vendor "{vendor_name}" deleted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting vendor", exc_info=True)
        log_exception(e, severity='ERROR', module='vendors.delete')
        db.session.rollback()
        flash(f'Error deleting vendor: {str(e)}', 'error')

    return redirect(url_for('vendors.list_vendors'))


_VENDOR_EXPORT_COLUMNS = ['code', 'name', 'contact_person', 'phone', 'email', 'tin',
                          'payment_terms', 'address', 'postal_code', 'check_payee_name',
                          'default_vat_category', 'withholding_taxes_str', 'is_active']

_VENDOR_EXPORT_HEADERS = ['Vendor Code', 'Vendor Name', 'Contact Person', 'Phone', 'Email',
                          'TIN', 'Payment Terms', 'Address', 'Postal Code', 'Check Payee Name',
                          'VAT Category', 'Withholding Taxes', 'Active']


def _vendor_export_rows():
    """Vendor master as a list of export-ready dicts (WHTs eager-loaded)."""
    vendors = (Vendor.query
               .options(selectinload(Vendor.withholding_taxes))
               .order_by(Vendor.code)
               .all())
    rows = []
    for vendor in vendors:
        wt_codes = ', '.join(wt.code for wt in vendor.withholding_taxes) if vendor.withholding_taxes else ''
        rows.append({
            'code': vendor.code,
            'name': vendor.name,
            'contact_person': vendor.contact_person or '',
            'phone': vendor.phone or '',
            'email': vendor.email or '',
            'tin': vendor.tin or '',
            'payment_terms': vendor.payment_terms or '',
            'address': vendor.address or '',
            'postal_code': vendor.postal_code or '',
            'check_payee_name': vendor.check_payee_name or '',
            'default_vat_category': vendor.default_vat_category or '',
            'withholding_taxes_str': wt_codes,
            'is_active': 'Yes' if vendor.is_active else 'No',
        })
    return rows


@vendors_bp.route('/vendors/export/excel')
@login_required
@staff_or_above_required
def export_excel():
    """Export vendors to Excel"""
    filename = f"vendors_{ph_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return export_to_excel(
        data=_vendor_export_rows(),
        columns=_VENDOR_EXPORT_COLUMNS,
        headers=_VENDOR_EXPORT_HEADERS,
        filename=filename,
        title='Vendor List'
    )


@vendors_bp.route('/vendors/export/csv')
@login_required
@staff_or_above_required
def export_csv_route():
    """Export vendors to CSV"""
    filename = f"vendors_{ph_now().strftime('%Y%m%d_%H%M%S')}.csv"
    return export_to_csv(
        data=_vendor_export_rows(),
        columns=_VENDOR_EXPORT_COLUMNS,
        headers=_VENDOR_EXPORT_HEADERS,
        filename=filename
    )


@vendors_bp.route('/vendors/<int:id>/defaults')
@login_required
def vendor_defaults(id):
    """Return vendor's WHT codes and default VAT category for AJAX."""
    vendor = db.get_or_404(Vendor, id)
    last_item = (
        AccountsPayableItem.query
        .join(AccountsPayable)
        .filter(AccountsPayable.vendor_id == id, AccountsPayable.status != 'voided')
        .order_by(AccountsPayable.created_at.desc(), AccountsPayableItem.line_number.asc())
        .first()
    )

    # Cash-disbursement defaults: the cash/bank account and direct-expense account this
    # vendor used on their most recent POSTED CDV — so the CDV form can pre-fill both
    # (defaults only; the user can still override).
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    last_cdv = (
        CashDisbursementVoucher.query
        .filter_by(vendor_id=id, status='posted')
        .order_by(CashDisbursementVoucher.cdv_date.desc(), CashDisbursementVoucher.id.desc())
        .first()
    )
    last_exp_line = (
        CDVExpenseLine.query
        .join(CashDisbursementVoucher)
        .filter(CashDisbursementVoucher.vendor_id == id,
                CashDisbursementVoucher.status == 'posted',
                CDVExpenseLine.account_id.isnot(None))
        .order_by(CashDisbursementVoucher.cdv_date.desc(), CashDisbursementVoucher.id.desc(),
                  CDVExpenseLine.line_number.asc())
        .first()
    )

    return jsonify({
        'withholding_taxes': [
            {
                'id': wt.id,
                'code': wt.code,
                'name': wt.name,
                'rate': float(wt.rate),
            }
            for wt in vendor.withholding_taxes
            if wt.is_active
        ],
        'default_vat_category': vendor.default_vat_category,
        'payment_terms': vendor.payment_terms or 'Net 30',
        'last_account_id': last_item.account_id if last_item else None,
        'last_cash_account_id': last_cdv.cash_account_id if last_cdv else None,
        'last_expense_account_id': last_exp_line.account_id if last_exp_line else None,
    })
