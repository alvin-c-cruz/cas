"""Forms for Production Runs (R-07 Process Track slice P2)."""
from flask_wtf import FlaskForm
from wtforms import SelectField, DecimalField, DateField
from wtforms.validators import DataRequired, NumberRange

from app.utils.concurrency import RowVersionFormMixin


def generate_run_number():
    """Next number after the highest existing purely-numeric run_number, zero-padded.
    Mirrors generate_wo_number()."""
    from app.production_runs.models import ProductionRun
    rows = ProductionRun.query.with_entities(ProductionRun.run_number).all()
    nums = [int(r[0]) for r in rows if r[0] and r[0].isdigit()]
    return f'{(max(nums) + 1) if nums else 1:05d}'


class ProductionRunForm(RowVersionFormMixin, FlaskForm):
    bom_id = SelectField('Bill of Materials', coerce=int, validators=[DataRequired()])
    department_id = SelectField('Department', coerce=int, validators=[DataRequired()])
    units_started = DecimalField('Units Started', places=4,
                                 validators=[DataRequired(),
                                             NumberRange(min=0.0001,
                                                         message='Units started must be greater than zero.')])
    period_start = DateField('Period Start', validators=[DataRequired()])
    period_end = DateField('Period End', validators=[DataRequired()])
