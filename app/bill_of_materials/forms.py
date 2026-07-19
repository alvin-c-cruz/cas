"""BillOfMaterialForm + the hidden-JSON line-parsing helper. Mirrors
app.quotations.views._parse_and_attach_quote_lines's shape (json.loads a
hidden 'lines' field, skip a blank trailing row, require the identifying
FK per line)."""
import json
from decimal import Decimal, InvalidOperation

from flask_wtf import FlaskForm
from wtforms import SelectField
from wtforms.validators import DataRequired

from app.bill_of_materials.models import BillOfMaterialLine
from app.utils.concurrency import RowVersionFormMixin


class BillOfMaterialForm(RowVersionFormMixin, FlaskForm):
    product_id = SelectField('Product (output)', coerce=int, validators=[DataRequired()])
    manufacturing_mode = SelectField('Manufacturing Mode', validators=[DataRequired()])


def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, '', 'null') else None
    except (InvalidOperation, TypeError):
        return None


def _int(v):
    try:
        return int(v) if v and str(v).strip() not in ('', 'null') else None
    except (ValueError, TypeError):
        return None


def _parse_and_attach_bom_lines(bom, lines_json):
    """Parse the hidden-JSON line array and attach BillOfMaterialLine rows to *bom*."""
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        component_product_id = _int(d.get('component_product_id'))
        quantity_per = _dec(d.get('quantity_per'))
        is_empty = component_product_id is None and quantity_per is None
        if is_empty:
            continue  # skip a blank trailing line
        if component_product_id is None:
            raise ValueError(f'Line {idx}: select a component product.')
        if quantity_per is None or quantity_per <= 0:
            raise ValueError(f'Line {idx}: quantity per must be greater than zero.')
        kept += 1
        bom.lines.append(BillOfMaterialLine(
            line_number=kept,
            component_product_id=component_product_id,
            quantity_per=quantity_per,
            uom_id=_int(d.get('uom_id')),
        ))
