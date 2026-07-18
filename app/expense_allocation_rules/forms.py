"""Form for the Expense Allocation Rule master (Phase 3b)."""
from flask_wtf import FlaskForm
from wtforms import SelectField
from wtforms.validators import DataRequired

BASIS_CHOICES = [
    ('revenue_share', 'Revenue Share'),
    ('gross_profit_share', 'Gross Profit Share'),
    ('units_sold', 'Units Sold'),
    ('equal', 'Equal Split'),
    ('none', 'None (Unallocated)'),
]


class ExpenseAllocationRuleForm(FlaskForm):
    account_id = SelectField('Account', validators=[DataRequired(message='Account is required.')])
    basis = SelectField('Allocation Basis', choices=BASIS_CHOICES,
                        validators=[DataRequired(message='Basis is required.')])
