"""P6 Task 5 -- charging abnormal loss out of WIP at close.

A third relieving leg joins the two P4 posts:

    1. conversion applied   Dr WIP            / Cr Labor Applied
    2. transfer             Dr Inventory      / Cr WIP
    3. abnormal loss        Dr Abnormal Loss  / Cr WIP      <- this slice

which turns P4's load-bearing invariant into a three-term one:

    ending WIP cost = pool - transferred - abnormal charged

**The abnormal leg is its own journal entry with its own entry_type**, not extra
lines on the transfer JE. Two reasons, both load-bearing:

  * a period can owe an abnormal charge while transferring NOTHING (everything
    started was lost or is still in process), and in that shape no transfer JE is
    created at all;
  * P5's report derives "transferred out" from the WIP CREDITS on
    manufacturing_production entries. Crediting WIP for abnormal loss under that
    same entry_type would silently inflate a figure that shipped -- the report
    would show spoilage as though it had been transferred to finished goods.

The new type is registered in BOTH VOUCHER_TYPES and VOUCHER_ENTRY_TYPES; a type
in neither is invisible to the General Journal and the Books of Accounts, which is
a BIR-compliance defect, not a cosmetic one.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.journal_entries.models import JournalEntry
from app.manufacturing_departments.models import ManufacturingDepartment
from app.posting.control_accounts import get_control_account
from app.production_runs.models import ProductionRun
from app.production_runs.service import close_run, issue_material, snapshot_materials
from app.products.models import Product
from app.stock_adjustments.service import post_movement

pytestmark = [pytest.mark.integration, pytest.mark.production_runs]

ABNORMAL = 'manufacturing_abnormal_loss'
_N = [0]


@pytest.fixture
def abnormal_loss_account(db_session, make_account):
    """Deliberately NOT folded into wo_control_accounts: the fail-closed test needs
    a fully-configured install that is missing this one account, which is exactly
    the state a real client is in the first time a run loses more than expected."""
    from app.settings import AppSettings
    make_account('7103')
    AppSettings.set_setting('abnormal_loss_account_code', '7103', updated_by='test')


def _setup(branch, actor, suffix, normal_loss_pct=None):
    comp = Product(code=f'AB-C-{suffix}', name='Fresh Mango', track_inventory=True,
                   costing_method='moving_average', standard_cost=Decimal('5.00'),
                   is_active=True)
    out = Product(code=f'AB-O-{suffix}', name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([comp, out]); db.session.commit()
    post_movement(comp, branch.id, 'opening', Decimal('10000'), Decimal('5.00'),
                  'stock_adjustment', 0, 'seed', actor)
    db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process',
                         normal_loss_pct=normal_loss_pct)
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=Decimal('2')))
    db.session.add(bom); db.session.commit()
    dept = ManufacturingDepartment(branch_id=branch.id, code=f'B{suffix}', name='Dehydration')
    db.session.add(dept); db.session.commit()
    return bom, dept, out


def _run(branch, actor, suffix, *, normal_loss_pct=None, completed='70', ending='20'):
    """1000.00 material + 450.00 conversion = P4's 1450.00 pool, so every figure
    below is comparable to the example that slice pinned."""
    bom, dept, out = _setup(branch, actor, suffix, normal_loss_pct)
    _N[0] += 1
    run = ProductionRun(run_number='AB%04d' % _N[0], bom_id=bom.id, department_id=dept.id,
                        branch_id=branch.id, period_start=date(2026, 8, 1),
                        period_end=date(2026, 8, 31), units_started=Decimal('100'),
                        conversion_cost=Decimal('450.00'),
                        units_completed_and_transferred=Decimal(completed),
                        units_ending_wip=Decimal(ending),
                        ending_wip_pct_complete=Decimal('50'))
    db.session.add(run); db.session.commit()
    snapshot_materials(run); db.session.commit()
    issue_material(run.materials[0], Decimal('200'), actor)   # 200 x 5.00 = 1000.00
    db.session.commit()
    return run


def _enable(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('bill_of_materials', 'production_runs'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()


def _login(client, user, branch):
    """selected_branch_id matters: the close route scopes by branch, so a session
    without one 404s before any of this slice's logic runs."""
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _account_balance(key):
    """Net Dr-Cr on a control account across every posted JE line."""
    acct = get_control_account(key)
    total = Decimal('0.00')
    for je in JournalEntry.query.all():
        for line in je.lines:
            if line.account_id == acct.id:
                total += (line.debit_amount or 0) - (line.credit_amount or 0)
    return total.quantize(Decimal('0.01'))


class TestTheAbnormalChargeIsPosted:
    """3% of 100 started = 3 allowed, 10 lost -> 7 abnormal.
    EU = 70 + (20 x 50%) + 7 = 87, so 1450.00 / 87 = 16.67 and 7 x 16.67 = 116.69."""

    def test_dr_abnormal_loss_cr_wip_for_units_times_cost_per_eu(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        run = _run(main_branch, accountant_user, 'A', normal_loss_pct=Decimal('3.00'))
        close_run(run, accountant_user)
        db.session.commit()
        je = JournalEntry.query.filter_by(entry_type=ABNORMAL,
                                          reference=run.run_number).one()
        assert je.is_balanced
        wip = get_control_account('wip')
        loss = get_control_account('abnormal_loss')
        dr_loss = sum((l.debit_amount or 0) for l in je.lines if l.account_id == loss.id)
        cr_wip = sum((l.credit_amount or 0) for l in je.lines if l.account_id == wip.id)
        assert dr_loss == Decimal('116.69')
        assert cr_wip == Decimal('116.69')

    def test_the_expense_lands_in_the_period_not_in_inventory(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """The whole economic point. 7 units' worth of cost becomes an expense
        instead of riding into finished goods on the 70 good units, so the transfer
        debits Inventory 70 x 16.67 = 1166.90 rather than carrying the spoilage in.

        Read off the transfer JE, not the Inventory account's net balance: this run
        also CREDITED Inventory 1000.00 when it issued material, and netting the two
        would measure the wrong thing."""
        run = _run(main_branch, accountant_user, 'B', normal_loss_pct=Decimal('3.00'))
        close_run(run, accountant_user)
        db.session.commit()
        assert _account_balance('abnormal_loss') == Decimal('116.69')
        transfer = JournalEntry.query.filter_by(
            entry_type='manufacturing_production', reference=run.run_number).one()
        inv = get_control_account('inventory')
        dr_inv = sum((l.debit_amount or 0) for l in transfer.lines if l.account_id == inv.id)
        assert dr_inv == Decimal('1166.90')

    def test_ending_wip_cost_subtracts_the_abnormal_charge(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """1450.00 - 1166.90 transferred - 116.69 charged out = 166.41. P4's
        two-term plug would have carried 283.10 forward, so the successor period
        would inherit a loss that had already been expensed."""
        run = _run(main_branch, accountant_user, 'C', normal_loss_pct=Decimal('3.00'))
        close_run(run, accountant_user)
        db.session.commit()
        assert run.ending_wip_cost == Decimal('166.41')
        assert run.ending_wip_cost != Decimal('283.10')

    def test_wip_ties_to_the_gl_across_all_THREE_relieving_legs(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """P4's invariant, extended rather than replaced. 1000.00 material in,
        450.00 conversion in, 1166.90 transferred out, 116.69 charged out."""
        run = _run(main_branch, accountant_user, 'D', normal_loss_pct=Decimal('3.00'))
        assert _account_balance('wip') == Decimal('1000.00'), 'only material before close'
        close_run(run, accountant_user)
        db.session.commit()
        assert _account_balance('wip') == Decimal('166.41')
        assert _account_balance('wip') == run.ending_wip_cost, \
            'ledger and carried figure must still agree with a third leg in play'


class TestTheChargeIsSkippedWhenNothingIsAbnormal:
    def test_no_abnormal_je_when_no_expectation_is_set(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """The backward-compatibility guarantee at the POSTING layer. A NULL
        percentage absorbs the same 10 lost units, so nothing is charged out and P4's
        two-leg close is what actually happens."""
        run = _run(main_branch, accountant_user, 'E')
        close_run(run, accountant_user)
        db.session.commit()
        assert JournalEntry.query.filter_by(entry_type=ABNORMAL).count() == 0
        assert _account_balance('abnormal_loss') == Decimal('0.00')

    def test_no_abnormal_je_when_the_loss_is_within_the_allowance(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """2 lost against a 3-unit allowance. A zero-value JE would BALANCE (0 = 0),
        so is_balanced could never catch one -- it has to be skipped outright, the
        same rule the conversion leg follows."""
        run = _run(main_branch, accountant_user, 'F', normal_loss_pct=Decimal('3.00'),
                   completed='78')
        close_run(run, accountant_user)
        db.session.commit()
        assert JournalEntry.query.filter_by(entry_type=ABNORMAL).count() == 0

    def test_a_run_that_ties_exactly_charges_nothing(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        run = _run(main_branch, accountant_user, 'G', normal_loss_pct=Decimal('3.00'),
                   completed='80')
        close_run(run, accountant_user)
        db.session.commit()
        assert JournalEntry.query.filter_by(entry_type=ABNORMAL).count() == 0
        assert run.ending_wip_cost == Decimal('161.20'), "P4's own figure, unmoved"


class TestFailClosed:
    def test_close_REFUSES_when_the_abnormal_loss_account_is_unassigned(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """No abnormal_loss_account fixture here. Every other control account is
        assigned, so this is the state a real client hits the first time a run loses
        more than expected -- and posting the charge somewhere else, or silently
        skipping it, would leave expensed value sitting in WIP forever."""
        run = _run(main_branch, accountant_user, 'H', normal_loss_pct=Decimal('3.00'))
        with pytest.raises(ValueError):
            close_run(run, accountant_user)
        assert run.status == 'open', 'a refused close must not mark the run closed'

    def test_an_unassigned_account_does_NOT_block_a_run_with_nothing_abnormal(
            self, db_session, main_branch, accountant_user, wo_control_accounts):
        """Fail closed on the charge, not on the module. An install that has never
        set an expectation must keep closing periods exactly as it did in P4 --
        demanding an account it will never post to is the labor_applied deadlock
        again, one layer down."""
        run = _run(main_branch, accountant_user, 'I', completed='80')
        close_run(run, accountant_user)
        db.session.commit()
        assert run.status == 'closed'
        assert run.ending_wip_cost == Decimal('161.20')


class TestAPeriodThatTransfersNothing:
    def test_abnormal_loss_is_charged_even_with_no_transfer_je(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """Nothing completed, 20 still in process, 80 lost against a 0% expectation.
        No transfer JE exists at all, which is why the abnormal charge cannot be
        extra lines on one: EU = 0 + 10 + 80 = 90, 1450.00 / 90 = 16.11, and
        80 x 16.11 = 1288.80 leaves 161.20 in WIP."""
        run = _run(main_branch, accountant_user, 'J', normal_loss_pct=Decimal('0.00'),
                   completed='0', ending='20')
        close_run(run, accountant_user)
        db.session.commit()
        assert JournalEntry.query.filter_by(
            entry_type='manufacturing_production', reference=run.run_number).count() == 0
        je = JournalEntry.query.filter_by(entry_type=ABNORMAL,
                                          reference=run.run_number).one()
        assert je.is_balanced
        assert _account_balance('abnormal_loss') == Decimal('1288.80')
        assert run.ending_wip_cost == Decimal('161.20')
        assert _account_balance('wip') == run.ending_wip_cost


class TestTheConfirmScreenPromisesWhatTheLedgerRecords:
    """P5 split preview_close() out of the close route precisely so the screen could
    not promise a number the ledger then contradicted -- but nothing ever ASSERTED
    the equality, and P6's third leg is exactly the change that breaks it: the
    remainder shown was pool - transferred, while the run now carries
    pool - transferred - abnormal. A comment is not a guard, so here is the guard.
    """

    def test_the_previewed_remainder_equals_the_ending_wip_actually_written(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        from app.production_runs.service import preview_close
        run = _run(main_branch, accountant_user, 'K', normal_loss_pct=Decimal('3.00'))
        _costing, preview = preview_close(run)
        promised = preview['remaining_in_wip']
        close_run(run, accountant_user)
        db.session.commit()
        assert promised == run.ending_wip_cost
        assert promised == Decimal('166.41'), 'and both are the three-term figure'

    def test_the_preview_names_the_abnormal_charge_it_subtracts(
            self, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """A correct remainder is not enough. Without the charge on the screen the
        accountant sees 1450.00 in, 1166.90 transferred, 166.41 left -- and 116.69
        simply missing, which reads as an arithmetic error rather than an expense."""
        from app.production_runs.service import preview_close
        run = _run(main_branch, accountant_user, 'L', normal_loss_pct=Decimal('3.00'))
        _costing, preview = preview_close(run)
        assert preview['abnormal_loss_units'] == Decimal('7.0000')
        assert preview['abnormal_loss_cost'] == Decimal('116.69')

    def test_the_confirm_screen_renders_the_abnormal_charge(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """Rendered, not merely returned -- the preview dict reaching the template is
        a separate claim from the template using it."""
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'M', normal_loss_pct=Decimal('3.00'))
        _login(client, accountant_user, main_branch)
        r = client.get(f'/production-runs/{run.id}/close')
        assert r.status_code == 200
        assert b'116.69' in r.data, 'the charge itself'
        assert b'Abnormal loss' in r.data, 'labelled, not a bare number'
        assert b'166.41' in r.data, 'and the remainder net of it'

    def test_the_confirm_screen_stays_silent_when_nothing_is_abnormal(
            self, client, db_session, main_branch, accountant_user, wo_control_accounts,
            abnormal_loss_account):
        """P4's screen, unchanged, for the install that never set an expectation."""
        _enable(db_session)
        run = _run(main_branch, accountant_user, 'N', completed='80')
        _login(client, accountant_user, main_branch)
        r = client.get(f'/production-runs/{run.id}/close')
        assert r.status_code == 200
        assert b'Abnormal loss' not in r.data
        assert b'161.20' in r.data


def test_the_new_entry_type_is_registered_in_BOTH_voucher_registries():
    """The Bank-Transfers failure, guarded. An entry_type missing from either tuple
    is invisible to the General Journal / Books of Accounts -- the posting is in the
    ledger but absent from a BIR-required book, which is a compliance defect rather
    than a display bug. Two separate tuples in two separate modules, so registering
    one and forgetting the other is the natural mistake."""
    from app.journals.views import VOUCHER_TYPES
    from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES
    assert ABNORMAL in VOUCHER_TYPES
    assert ABNORMAL in VOUCHER_ENTRY_TYPES
