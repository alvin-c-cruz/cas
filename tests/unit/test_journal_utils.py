import pytest
from app import create_app, db
from app.journal_entries.utils import generate_jv_number
from app.journal_entries.models import JournalEntry
from app.branches.models import Branch
from app.users.models import User
import os
pytestmark = [pytest.mark.journal_entries, pytest.mark.unit]



@pytest.fixture(scope='function')
def app_ctx():
    os.environ['SECRET_KEY'] = 'test-secret-key'
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_generate_jv_number_first(app_ctx):
    """First JV for a branch uses sequence 0001."""
    with app_ctx.app_context():
        branch = Branch(name='Main', code='MAIN')
        db.session.add(branch)
        db.session.commit()
        result = generate_jv_number(branch.id)
        from app.utils import ph_now
        now = ph_now()
        expected_prefix = f'JV-{now.year}-{now.month:02d}-'
        assert result.startswith(expected_prefix)
        assert result.endswith('0001')


def test_generate_jv_number_increments(app_ctx):
    """Subsequent JVs increment the sequence."""
    with app_ctx.app_context():
        branch = Branch(name='Main', code='MAIN')
        user = User(username='acc', email='acc@test.com', full_name='A', role='accountant', is_active=True)
        user.set_password('pass')
        db.session.add_all([branch, user])
        db.session.commit()

        from app.utils import ph_now
        from datetime import date
        now = ph_now()
        existing = JournalEntry(
            entry_number=f'JV-{now.year}-{now.month:02d}-0001',
            entry_date=date.today(),
            description='Test',
            entry_type='adjustment',
            branch_id=branch.id,
            created_by_id=user.id,
            is_balanced=True,
            total_debit=0,
            total_credit=0,
            status='draft'
        )
        db.session.add(existing)
        db.session.commit()

        result = generate_jv_number(branch.id)
        assert result.endswith('0002')


def test_generate_jv_number_ignores_je_prefix(app_ctx):
    """Old JE-prefixed entries do not affect JV sequence."""
    with app_ctx.app_context():
        branch = Branch(name='Main', code='MAIN')
        user = User(username='acc', email='acc@test.com', full_name='A', role='accountant', is_active=True)
        user.set_password('pass')
        db.session.add_all([branch, user])
        db.session.commit()

        from datetime import date
        from app.utils import ph_now

        now = ph_now()
        old = JournalEntry(
            entry_number=f'JE-{now.year}-0099',
            entry_date=date.today(),
            description='Old style',
            entry_type='adjustment',
            branch_id=branch.id,
            created_by_id=user.id,
            is_balanced=True,
            total_debit=0,
            total_credit=0,
            status='draft'
        )
        db.session.add(old)
        db.session.commit()

        result = generate_jv_number(branch.id)
        assert result.endswith('0001')
