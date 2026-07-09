"""Quotation views -- a product-priced pre-sale offer; front of the O2C chain
(Quotation -> SO -> DR -> SI). Operational only: posts NO journal entry.
Mirrors sales_orders.views with a header vat_treatment and a validity-period lifecycle."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app)
from flask_login import login_required, current_user

from app import db
from app.quotations.models import Quotation, QuotationItem, generate_quotation_number
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now

quotations_bp = Blueprint('quotations', __name__, template_folder='templates')

VALID_QUOTATION_STATUSES = {'draft', 'sent', 'accepted', 'rejected', 'cancelled'}


# -- routes --------------------------------------------------------------------

@quotations_bp.route('/quotations')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    query = Quotation.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_QUOTATION_STATUSES:
        query = query.filter_by(status=status_filter)
    quotes = query.order_by(Quotation.quotation_date.desc(), Quotation.id.desc()).all()
    return render_template('quotations/list.html', quotes=quotes,
                           status_filter=status_filter)
