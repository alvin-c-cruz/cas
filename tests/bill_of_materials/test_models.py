"""Unit tests for BillOfMaterial / BillOfMaterialLine (R-07 Wave 0)."""
from decimal import Decimal
import pytest
from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.products.models import Product

pytestmark = [pytest.mark.integration]


def _products(db_session, n=2):
    made = [Product(code=f'BOM-P{i}', name=f'Product {i}', is_active=True) for i in range(n)]
    db.session.add_all(made)
    db.session.commit()
    return made


def test_product_id_is_unique(db_session):
    out, comp = _products(db_session)
    db.session.add(BillOfMaterial(product_id=out.id, manufacturing_mode='discrete'))
    db.session.commit()
    db.session.add(BillOfMaterial(product_id=out.id, manufacturing_mode='process'))
    with pytest.raises(Exception):        # IntegrityError on the unique index
        db.session.commit()
    db.session.rollback()


def test_lines_cascade_delete_with_bom(db_session):
    out, comp = _products(db_session)
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2.5000')))
    db.session.add(bom)
    db.session.commit()
    line_id = bom.lines[0].id
    db.session.delete(bom)
    db.session.commit()
    assert db.session.get(BillOfMaterialLine, line_id) is None


def test_defaults(db_session):
    out, comp = _products(db_session)
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process')
    db.session.add(bom)
    db.session.commit()
    assert bom.is_active is True
    assert bom.row_version == 1
