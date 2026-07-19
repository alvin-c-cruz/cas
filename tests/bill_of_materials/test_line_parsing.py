"""BOM line-parsing tests (R-07 Wave 0) -- mirrors
app.quotations.views._parse_and_attach_quote_lines's contract."""
import json
from decimal import Decimal
import pytest
from app import db
from app.bill_of_materials.models import BillOfMaterial
from app.products.models import Product

pytestmark = [pytest.mark.integration]


def _products(db_session, n=2):
    made = [Product(code=f'BOML-P{i}', name=f'Product {i}', is_active=True) for i in range(n)]
    db.session.add_all(made)
    db.session.commit()
    return made


def test_parses_valid_lines(db_session):
    from app.bill_of_materials.forms import _parse_and_attach_bom_lines
    out, comp = _products(db_session)
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    db.session.add(bom)
    db.session.commit()
    lines_json = json.dumps([{'component_product_id': comp.id, 'quantity_per': '2.5000'}])
    _parse_and_attach_bom_lines(bom, lines_json)
    db.session.commit()
    assert len(bom.lines) == 1
    assert bom.lines[0].quantity_per == Decimal('2.5000')
    assert bom.lines[0].line_number == 1


def test_skips_blank_trailing_line(db_session):
    from app.bill_of_materials.forms import _parse_and_attach_bom_lines
    out, comp = _products(db_session)
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    db.session.add(bom)
    db.session.commit()
    lines_json = json.dumps([
        {'component_product_id': comp.id, 'quantity_per': '1.0000'},
        {'component_product_id': None, 'quantity_per': None},
    ])
    _parse_and_attach_bom_lines(bom, lines_json)
    assert len(bom.lines) == 1


def test_missing_component_product_raises(db_session):
    from app.bill_of_materials.forms import _parse_and_attach_bom_lines
    out, comp = _products(db_session)
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    db.session.add(bom)
    db.session.commit()
    lines_json = json.dumps([{'component_product_id': None, 'quantity_per': '3.0000'}])
    with pytest.raises(ValueError, match='component'):
        _parse_and_attach_bom_lines(bom, lines_json)
