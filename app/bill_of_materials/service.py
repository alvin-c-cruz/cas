"""R-07 Wave 0 shared spine: manufacturing-mode helpers + the
consumption/production interface contract the discrete (Work Order) and
process (Production Run) tracks will both call. The two functions' bodies
are deferred until R-03 slice 2 (stock movements/ledger) ships -- see
docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md."""
from app.settings import AppSettings

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


def consume_materials(source_document, lines):
    """Decrement component stock for each BOM line consumed by *source_document*
    (a WorkOrder or ProductionRun). Contract defined here (R-07 Wave 0); the
    body is deferred to R-03 slice 2 (stock movements/ledger), which this
    function has no access to yet."""
    raise NotImplementedError(
        'consume_materials is a Wave 0 interface stub -- implement once R-03 '
        'slice 2 (stock movements/ledger) ships.')


def produce_finished_goods(source_document, product_id, quantity, unit_cost):
    """Increment finished-goods stock for *product_id* at *unit_cost*, produced
    by *source_document*. Same deferred-body contract as consume_materials."""
    raise NotImplementedError(
        'produce_finished_goods is a Wave 0 interface stub -- implement once '
        'R-03 slice 2 (stock movements/ledger) ships.')
