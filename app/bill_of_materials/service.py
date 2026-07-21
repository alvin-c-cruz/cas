"""R-07 Wave 0 shared spine: manufacturing-mode helpers + the
consumption/production interface contract the discrete (Work Order) and
process (Production Run) tracks will both call. The two functions' bodies
are deferred until R-03 slice 2 (stock movements/ledger) ships -- see
docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md."""
from decimal import Decimal
from app import db
from app.settings import AppSettings
from app.utils import ph_now
from app.posting.control_accounts import get_control_account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.stock_adjustments.service import post_movement

ZERO = Decimal('0.00')

MANUFACTURING_MODES = (
    ('discrete', 'Discrete (Job Order / Routing)'),
    ('process', 'Process (Batch / Equivalent Units)'),
)


def is_discrete_enabled():
    return AppSettings.get_setting('manufacturing_discrete_enabled', '0') == '1'


def is_process_enabled():
    return AppSettings.get_setting('manufacturing_process_enabled', '0') == '1'


def available_manufacturing_modes():
    """(value, label) choices for whichever mode(s) are enabled -- empty if neither."""
    modes = []
    if is_discrete_enabled():
        modes.append(MANUFACTURING_MODES[0])
    if is_process_enabled():
        modes.append(MANUFACTURING_MODES[1])
    return modes


def _new_je(entry_number, entry_date, description, reference, entry_type, branch_id, actor):
    je = JournalEntry(entry_number=entry_number, entry_date=entry_date, description=description,
                      reference=reference, entry_type=entry_type, branch_id=branch_id,
                      created_by_id=actor.id, status='posted', posted_by_id=actor.id,
                      posted_at=ph_now(), is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(je); db.session.flush()
    return je


def _add_line(je, n, account_id, description, debit, credit):
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=account_id,
                                    description=description, debit_amount=debit, credit_amount=credit))


def _source_document_type(source_document):
    from app.work_orders.models import WorkOrder
    if isinstance(source_document, WorkOrder):
        return 'work_order', source_document.wo_number
    raise ValueError(
        f'unsupported source_document type {type(source_document).__name__!r}')


def consume_materials(source_document, lines, actor):
    """Decrement component stock for each (component_line, quantity) pair
    consumed by *source_document* -- a WorkOrder today; ProductionRun, once
    R-07 Process Track P2 ships, will call this unchanged (dispatch is by
    isinstance, not a hardcoded WorkOrder assumption). No-op (no JE, no
    movements, no control accounts resolved) if every line's component is
    untracked. Fail-closed: wip/inventory resolved before any write, only
    when at least one line is tracked. Does NOT commit -- caller owns the
    transaction."""
    tracked = [(cl, qty) for cl, qty in lines
              if cl.component_product and cl.component_product.track_inventory]
    if not tracked:
        return

    source_document_type, reference = _source_document_type(source_document)
    description = f'Work Order {reference} material consumption'

    wip_account = get_control_account('wip')
    inv_account = get_control_account('inventory')

    je = _new_je(generate_entry_number(source_document.branch_id), ph_now().date(),
                 description, reference, 'manufacturing_consumption',
                 source_document.branch_id, actor)
    n = 1
    warnings = []
    for component_line, quantity in tracked:
        product = component_line.component_product
        mv, went_negative = post_movement(
            product, source_document.branch_id, 'material_issue', -Decimal(str(quantity)), None,
            source_document_type, source_document.id,
            f'{reference} material issue: {product.code}', actor, journal_entry_id=je.id)
        if went_negative:
            warnings.append(product.code)
        amount = (abs(Decimal(str(mv.quantity))) * Decimal(str(mv.unit_cost))).quantize(Decimal('0.01'))
        _add_line(je, n, wip_account.id, f'{product.code} to WIP', amount, ZERO); n += 1
        _add_line(je, n, inv_account.id, f'{product.code} consumed', ZERO, amount); n += 1

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'{reference} material consumption JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    source_document._negative_warnings = warnings   # transient, read by the caller for a flash


def produce_finished_goods(source_document, product_id, quantity, unit_cost, actor):
    """Increment finished-goods stock for *product_id* at *unit_cost*, produced
    by *source_document*. No-op if the product is untracked. Fail-closed:
    inventory/wip resolved before any write. The JE debit amount is read
    from the movement's OWN returned unit_cost, not the raw *unit_cost*
    parameter -- for a standard-costed product these can differ (2a-i's
    engine pins to Product.standard_cost regardless of what's passed); any
    gap becomes a separate variance posting the CALLER (D4) is responsible
    for, never silently absorbed here. Does NOT commit."""
    from app.products.models import Product
    product = db.session.get(Product, product_id)
    if not product or not product.track_inventory:
        return

    source_document_type, reference = _source_document_type(source_document)
    description = f'Work Order {reference} completion'

    inv_account = get_control_account('inventory')
    wip_account = get_control_account('wip')

    je = _new_je(generate_entry_number(source_document.branch_id), ph_now().date(),
                 description, reference, 'manufacturing_production',
                 source_document.branch_id, actor)
    mv, _went_negative = post_movement(
        product, source_document.branch_id, 'production', Decimal(str(quantity)), Decimal(str(unit_cost)),
        source_document_type, source_document.id, f'{reference} production: {product.code}',
        actor, journal_entry_id=je.id)
    amount = (Decimal(str(mv.quantity)) * Decimal(str(mv.unit_cost))).quantize(Decimal('0.01'))
    _add_line(je, 1, inv_account.id, f'{product.code} produced', amount, ZERO)
    _add_line(je, 2, wip_account.id, f'{product.code} relieved from WIP', ZERO, amount)

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'{reference} production JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
