"""WorkOrderForm + document numbering (R-07 Discrete Track slice D2). Numbering
mirrors app.quotations.models.generate_quotation_number's exact contract:
company-wide, resets each PH calendar month."""
from flask_wtf import FlaskForm
from wtforms import SelectField, DecimalField, DateField
from wtforms.validators import DataRequired, Optional

from app.utils import ph_now
from app.utils.concurrency import RowVersionFormMixin


def generate_wo_number():
    from app.work_orders.models import WorkOrder
    today = ph_now().date()
    prefix = f'WO-{today.year:04d}-{today.month:02d}-'
    rows = (WorkOrder.query.filter(WorkOrder.wo_number.like(prefix + '%'))
            .with_entities(WorkOrder.wo_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f'{prefix}{(max(nums) + 1) if nums else 1:04d}'


class WorkOrderForm(RowVersionFormMixin, FlaskForm):
    bom_id = SelectField('Bill of Materials', coerce=int, validators=[DataRequired()])
    qty_to_produce = DecimalField('Quantity to Produce', places=4, validators=[DataRequired()])
    planned_start_date = DateField('Planned Start Date', validators=[Optional()])
    planned_end_date = DateField('Planned End Date', validators=[Optional()])
