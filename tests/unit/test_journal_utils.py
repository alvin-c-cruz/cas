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


def _mk_user():
    user = User(username='acc', email='acc@test.com', full_name='A',
                role='accountant', is_active=True)
    user.set_password('pass')
    return user


def _mk_je(number, branch_id, user_id):
    from datetime import date
    return JournalEntry(
        entry_number=number,
        entry_date=date.today(),
        description='Test',
        entry_type='adjustment',
        branch_id=branch_id,
        created_by_id=user_id,
        is_balanced=True,
        total_debit=0,
        total_credit=0,
        status='posted',
    )


def test_generate_jv_number_unique_across_branches(app_ctx):
    """JournalEntry.entry_number carries a GLOBAL unique index, so two branches
    in the same month must not both mint ...-0001. RIC has two active branches
    (CORP + EXTRA), so a per-branch sequence violates the index on the second
    branch's first voucher."""
    with app_ctx.app_context():
        corp = Branch(name='Corp', code='CORP')
        extra = Branch(name='Extra', code='EXTRA')
        user = _mk_user()
        db.session.add_all([corp, extra, user])
        db.session.commit()

        first = generate_jv_number(corp.id)
        db.session.add(_mk_je(first, corp.id, user.id))
        db.session.commit()

        second = generate_jv_number(extra.id)
        assert second != first, (
            f'both branches minted {first!r} -- violates the global unique index'
        )

        # Must persist without an IntegrityError.
        db.session.add(_mk_je(second, extra.id, user.id))
        db.session.commit()

        assert JournalEntry.query.count() == 2


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


# ── BUG-JE-NUMBER-PERBRANCH regression net ───────────────────────────────────
#
# `JournalEntry.entry_number` carries a GLOBAL unique index, but every generator
# used to scope its "find the latest" query PER BRANCH while putting no branch
# component in the number. The second active branch therefore recomputed the
# first one's number and violated the index.
#
# This was live: RIC has two active branches (CORP + EXTRA), and
# `year_end/service.py` loops every active branch when closing -- so year-end
# close and VAT settlement were already broken there, independent of any import.
# It survived because the tests above only ever exercise ONE branch.
#
# Pin every generator, not just the one that was reported.

def _two_branches():
    corp = Branch(name='Corp', code='CORP')
    extra = Branch(name='Extra', code='EXTRA')
    user = _mk_user()
    db.session.add_all([corp, extra, user])
    db.session.commit()
    return corp, extra, user


@pytest.mark.parametrize('generator_name', [
    'generate_jv_number',
    'generate_entry_number',
    'closing_entry_number',
    'settlement_entry_number',
])
def test_every_generator_is_unique_across_branches(app_ctx, generator_name):
    """No generator may mint the same entry_number for two branches."""
    from app.journal_entries import utils as je_utils
    from app.vat_settlement.service import settlement_entry_number
    from app.year_end.service import closing_entry_number

    callers = {
        'generate_jv_number': lambda b: je_utils.generate_jv_number(b),
        'generate_entry_number': lambda b: je_utils.generate_entry_number(b),
        'closing_entry_number': lambda b: closing_entry_number(b, 2026),
        'settlement_entry_number': lambda b: settlement_entry_number(2026, 3, b),
    }
    mint = callers[generator_name]

    with app_ctx.app_context():
        corp, extra, user = _two_branches()

        first = mint(corp.id)
        db.session.add(_mk_je(first, corp.id, user.id))
        db.session.commit()

        second = mint(extra.id)
        assert second != first, (
            f'{generator_name} minted {first!r} for both branches -- '
            'violates the global unique index on entry_number'
        )

        # And it must actually persist: the index is the real arbiter.
        db.session.add(_mk_je(second, extra.id, user.id))
        db.session.commit()
        assert JournalEntry.query.count() == 2


def test_year_end_close_numbers_do_not_collide_across_branches(app_ctx):
    """The concrete failure: year_end loops every active branch."""
    from app.year_end.service import closing_entry_number

    with app_ctx.app_context():
        corp, extra, user = _two_branches()

        minted = []
        for branch in (corp, extra):
            number = closing_entry_number(branch.id, 2025)
            db.session.add(_mk_je(number, branch.id, user.id))
            db.session.commit()      # would raise IntegrityError on the 2nd
            minted.append(number)

        assert minted == ['JV-2025-12-0001', 'JV-2025-12-0002']
        assert len(set(minted)) == 2
