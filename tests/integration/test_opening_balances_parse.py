"""The Opening Balances line parser must tolerate comma-formatted amounts, so the
UI can post '1,234.56' without any server change. Also pins leaf-only acceptance."""
import pytest
from decimal import Decimal
from werkzeug.datastructures import MultiDict

from app import db
from app.accounts.models import Account
from app.opening_balances.views import _parse_lines, OpeningLineError

pytestmark = [pytest.mark.integration, pytest.mark.opening_balances]


def _leaf_account():
    """A postable leaf: a top-level parent (group) with one child (leaf)."""
    parent = Account(code='10000', name='Assets Root', account_type='Asset', normal_balance='Debit', is_active=True)
    db.session.add(parent)
    db.session.flush()
    leaf = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   parent_id=parent.id, normal_balance='Debit', is_active=True)
    db.session.add(leaf)
    db.session.commit()
    return leaf


def test_parse_lines_strips_commas(db_session):
    leaf = _leaf_account()
    form = MultiDict([('account_id', str(leaf.id)), ('debit', '1,234.56'), ('credit', '')])
    rows = _parse_lines(form)
    assert rows == [{'account_id': leaf.id, 'debit': Decimal('1234.56'), 'credit': Decimal('0')}]


def test_parse_lines_rejects_both_filled(db_session):
    leaf = _leaf_account()
    form = MultiDict([('account_id', str(leaf.id)), ('debit', '100.00'), ('credit', '50.00')])
    with pytest.raises(OpeningLineError):
        _parse_lines(form)
