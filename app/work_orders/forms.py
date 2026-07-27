"""WorkOrderForm + document numbering (R-07 Discrete Track slice D2). Numbering
mirrors app.sales_invoices.views.generate_invoice_number's exact contract: plain
continuous 5-digit sequence, company-wide, no prefix, no reset."""
from flask_wtf import FlaskForm
from wtforms import SelectField, DecimalField, DateField
from wtforms.validators import DataRequired, Optional

from app.utils.concurrency import RowVersionFormMixin


def generate_wo_number():
    """Each WO gets the next number after the highest existing purely-numeric
    wo_number. Legacy prefixed numbers (e.g. the old 'WO-2026-07-0030' format)
    are ignored."""
    from app.work_orders.models import WorkOrder
    rows = WorkOrder.query.with_entities(WorkOrder.wo_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    next_num = (max(nums) + 1) if nums else 1
    return f'{next_num:05d}'


class WorkOrderForm(RowVersionFormMixin, FlaskForm):
    bom_id = SelectField('Bill of Materials', coerce=int, validators=[DataRequired()])
    qty_to_produce = DecimalField('Quantity to Produce', places=4, validators=[DataRequired()])
    planned_start_date = DateField('Planned Start Date', validators=[Optional()])
    planned_end_date = DateField('Planned End Date', validators=[Optional()])
