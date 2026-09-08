"""Product.code becomes optional, then invisible.

Owner, 2026-09-08: clients do not use the product code. Approach C was chosen
deliberately over deleting the column -- make it optional and hide it, so the 555
codes already recorded survive and the decision stays reversible.

The unique index is KEPT. SQLite permits multiple NULLs under a unique index, so
new products simply have no code while existing ones stay unique. Dropping the
index is the irreversible half and is not part of this change.

`name` is NOT made unique. That would be a second, irreversible decision smuggled
in beside a reversible one -- and the master legitimately allows two products to
share a name.
"""
import pytest

from app.products.models import Product

pytestmark = [pytest.mark.integration]


class TestTheColumn:

    def test_code_is_optional(self):
        assert Product.__table__.c.code.nullable is True

    def test_code_keeps_its_unique_index(self):
        """The reversible half of the change. Dropping this would let duplicate
        codes in among the 555 already recorded, which no later step could undo."""
        assert Product.__table__.c.code.unique is True

    def test_name_did_not_become_unique(self):
        """CONTROL. The owner asked for optional-and-hidden; a new NOT NULL or
        UNIQUE constraint elsewhere is not part of that."""
        assert not Product.__table__.c.name.unique

    def test_customer_code_is_untouched(self):
        """A different field -- the CUSTOMER's own SKU. Easy to catch in a sweep
        for the word 'code' and delete by accident."""
        assert 'customer_code' in {c.key for c in Product.__table__.columns}


class TestAProductCanExistWithoutACode:

    def test_it_saves(self, db_session):
        p = Product(code=None, name='CODELESS ITEM', is_active=True)
        db_session.add(p)
        db_session.commit()
        assert p.id is not None
        assert p.code is None

    def test_two_of_them_can_coexist(self, db_session):
        """THE reason the unique index is safe to keep: NULLs do not collide."""
        db_session.add(Product(code=None, name='CODELESS ONE', is_active=True))
        db_session.add(Product(code=None, name='CODELESS TWO', is_active=True))
        db_session.commit()
        assert Product.query.filter(Product.code.is_(None)).count() == 2

    def test_a_duplicate_REAL_code_is_still_refused(self, db_session):
        """CONTROL for the two tests above: making NULLs legal must not make
        duplicate codes legal. The 555 existing codes stay unique."""
        from sqlalchemy.exc import IntegrityError
        db_session.add(Product(code='RM-DUP-1', name='FIRST', is_active=True))
        db_session.commit()
        db_session.add(Product(code='RM-DUP-1', name='SECOND', is_active=True))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
