"""Forms for Production Runs (R-07 Process Track slice P2)."""
from flask_wtf import FlaskForm
from wtforms import SelectField, DecimalField, DateField
from wtforms.validators import DataRequired, NumberRange, Optional

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


class ProductionRunPeriodForm(FlaskForm):
    """Period results the accountant reports at period end (R-07 P3).

    conversion_cost is entered manually -- see costing.py for why the arc spec's
    ExpenseAllocationRule reuse was not possible.
    """
    units_completed_and_transferred = DecimalField(
        'Units Completed & Transferred', places=4, validators=[Optional(), NumberRange(min=0)])
    units_ending_wip = DecimalField(
        'Units in Ending WIP', places=4, validators=[Optional(), NumberRange(min=0)])
    ending_wip_pct_complete = DecimalField(
        '% Complete (Ending WIP)', places=2,
        validators=[Optional(), NumberRange(min=0, max=100,
                                            message='Percent complete must be between 0 and 100.')])
    conversion_cost = DecimalField(
        'Conversion Cost (Labour + Overhead)', places=2,
        validators=[Optional(), NumberRange(min=0)])
