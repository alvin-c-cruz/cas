"""WTForms form definitions for the Product master."""
from flask_wtf import FlaskForm
from wtforms import (StringField, TextAreaField, SelectField, DecimalField,
                     BooleanField, SelectMultipleField)
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError
from app.products.models import COSTING_METHODS

_COSTING_METHOD_CHOICES = [('', '— None —')] + [(m, m.replace('_', ' ').title())
                                                 for m in COSTING_METHODS]


class ProductForm(FlaskForm):
    # prodcode_0001: the product's own `code` field was retired from this form (and the
    # screens that use it) -- the client does not use it. The column is still there
    # (nullable) so the 555 previously recorded codes survive; see Product.code.
    customer_code = StringField("Customer's Product Code", validators=[Optional(), Length(max=50)])
    name = StringField('Name', validators=[DataRequired(message='Name is required.'),
                                           Length(max=200)])
    description = TextAreaField('Description', validators=[Optional()])
    job_order_name = StringField('Job Order Name', validators=[Optional(), Length(max=200)])
    # choices populated in the view from active UOMs / accounts; '' = none
    default_unit_of_measure_id = SelectField('Default Unit of Measure',
                                             validators=[Optional()], default='')
    # Curated per-product allow-list for NO-PO receiving lines. Empty = any active
    # unit (opt-in). coerce=int; choices are active UOMs, populated in the view.
    allowed_unit_ids = SelectMultipleField('Allowed Units (no-PO receiving)',
                                           coerce=int, validators=[Optional()])
    default_unit_price = DecimalField('Default Unit Price (₱, VAT-inclusive)', places=2,
                                      validators=[Optional(), NumberRange(min=0)])
    # The unit the company keeps the stock in, and how many of it make one selling unit
    # (0.1 KG for a 100 g pack; 24 CANS for a box of 24): the SO and Job Order Slip show each
    # line in it under COMPANY INVENTORY (owner, 4-5 Nov 2026). Both or neither -- see
    # validate_inventory_unit_id. No Optional() on the unit: it would stop the chain on a
    # blank pick and the pairing check would never run. validate_choice=False because an edit
    # post that leaves the field out falls back to the product's stored value, and a stored
    # None is coerced to the text 'None', which is in no list -- the edit would be refused;
    # validate_inventory_unit_id checks the choice itself. places=None so the edit page shows
    # 24 / 0.1, not the column's 24.000000 (the view trims the stored value).
    inventory_unit_id = SelectField('Inventory Unit', default='', validate_choice=False)
    inventory_qty_per_unit = DecimalField('Inventory Qty per Unit', places=None,
                                          validators=[Optional(), NumberRange(min=0.000001,
                                              message='Inventory qty per unit must be more than zero.')])
    default_account_id = SelectField('Default Account', validators=[Optional()], default='')
    category_id = SelectField('Category', validators=[Optional()], default='')
    standard_cost = DecimalField('Standard Cost (₱)', places=2,
                                 validators=[Optional(), NumberRange(min=0)])
    track_inventory = BooleanField('Track Inventory')
    costing_method = SelectField('Costing Method', choices=_COSTING_METHOD_CHOICES,
                                 validators=[Optional()], default='')
    reorder_level = DecimalField('Reorder Level (Qty)', places=2,
                                 validators=[Optional(), NumberRange(min=0)])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])

    def __init__(self, *args, editing=None, **kwargs):
        """`editing` is the Product being edited (None on create), so the duplicate-name
        check can tell 'kept its own name' from 'took another product's name'."""
        super().__init__(*args, **kwargs)
        self._editing = editing

    def validate_name(self, field):
        """Refuse a name another product already has. Owner, 2026-09-25: BLOCK, no override.

        `EPSON LQ-310 DOT MATRIX PRINTER` was entered twice, 55 minutes apart, because
        nothing said it existed. Compared case-insensitively with whitespace collapsed,
        against active AND inactive products -- an inactive twin should be reactivated,
        not re-entered. On edit the check runs only when the name actually changes, so a
        duplicate that predates this rule stays editable without a forced rename.
        """
        wanted = normalize_product_name(field.data)
        if not wanted:
            return
        if self._editing is not None and normalize_product_name(self._editing.name) == wanted:
            return
        from app.products.models import Product
        q = Product.query.with_entities(Product.id, Product.name, Product.is_active)
        if self._editing is not None:
            q = q.filter(Product.id != self._editing.id)
        for _id, name, active in q:
            if normalize_product_name(name) == wanted:
                raise ValidationError(
                    f'A product named "{name}" already exists'
                    f'{" (inactive -- reactivate it instead)" if not active else ""}.')


    def validate_inventory_unit_id(self, field):
        """The unit and its quantity go together: a unit with no quantity converts nothing, a
        quantity with no unit has no meaning. Also the choice check WTForms is told to skip:
        blank, None and the coerced 'None' all mean no unit; anything else must be listed."""
        unit = '' if field.data in (None, '', 'None') else str(field.data)
        if unit and unit not in {str(value) for value, _label in (field.choices or [])}:
            raise ValidationError('Not a valid choice.')
        has_unit = bool(unit)
        has_qty = self.inventory_qty_per_unit.data is not None or bool(
            self.inventory_qty_per_unit.raw_data and self.inventory_qty_per_unit.raw_data[0].strip())
        if has_unit and not has_qty:
            raise ValidationError('Enter the Inventory Qty per Unit for this unit '
                                  '(how many of it make one selling unit).')
        if has_qty and not has_unit:
            raise ValidationError('Pick the Inventory Unit the quantity is counted in.')

    def validate_track_inventory(self, field):
        """When inventory tracking is on, a costing method + cost basis are required.
        When off, the other three fields are left alone -- no validation error, and no
        value is cleared (a product can be un-tracked while keeping stale prior values)."""
        if not field.data:
            return
        missing = []
        if not self.costing_method.data:
            missing.append('a costing method')
        if self.standard_cost.data is None:
            missing.append('a standard cost')
        if missing:
            raise ValidationError(
                f"{' and '.join(missing).capitalize()} required when Track Inventory is checked.")


def normalize_product_name(name):
    """Comparison form of a product name: case-folded, surrounding and repeated spaces collapsed."""
    return ' '.join((name or '').split()).casefold()
