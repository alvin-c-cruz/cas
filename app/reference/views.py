"""Reference blueprint — read-only BIR/tax reference pages.

Static lookup material (no DB models). Currently hosts the Withholding Tax
Alphanumeric Tax Code (ATC) reference used by accountants when selecting the
correct WHT code/rate during transaction entry.
"""
from flask import Blueprint, render_template, flash, redirect, url_for
from flask_login import login_required, current_user

reference_bp = Blueprint('reference', __name__, template_folder='templates')


@reference_bp.route('/withholding-atc')
@login_required
def withholding_atc():
    """BIR Withholding Tax ATC reference (expanded + final, individual + corporate)."""
    if current_user.role not in ['admin', 'accountant']:
        flash('You do not have permission to view this page.', 'error')
        return redirect(url_for('dashboard.index'))
    return render_template('reference/atc_withholding.html')
