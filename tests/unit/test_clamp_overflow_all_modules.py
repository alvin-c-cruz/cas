"""Every `_clamp` in the app must survive an infinite coordinate.

`json.loads('1e999')` is `float('inf')` -- valid JSON that Python's own reader
produces -- and `round(inf)` raises **OverflowError**, which is neither of the
two exception types the original `_clamp` caught. No `save_layout` wraps the
call in a try/except, so an authenticated POST carrying `1e999` was a 500.

`app/common/preprinted_base.py` was fixed when it was written (and pinned by
tests/unit/test_preprinted_base.py). The **ten** other copies were not: the
shared `preprinted_texts._clamp` that every pre-printed document's `texts` go
through, plus one private clone in each of nine per-document layout modules.
Fixing only the one named in the bug report would have left nine live.

Parametrised over the modules themselves rather than re-testing one function,
because the defect is that the copies DRIFTED -- a test bound to a single copy
is exactly what let nine of them stay broken (memory
`feedback-grep-siblings-on-fix`).
"""
import importlib
import json

import pytest

pytestmark = [pytest.mark.unit]

# Every module that defines its own `_clamp`. Kept as an explicit list so a NEW
# clone has to be added here consciously -- see test_no_unlisted_clamp_exists.
CLAMP_MODULES = [
    'app.common.preprinted_base',
    'app.common.preprinted_texts',
    'app.accounts_payable.preprinted_layout',
    'app.cash_disbursements.check_layout',
    'app.cash_disbursements.preprinted_layout',
    'app.cash_receipts.preprinted_layout',
    'app.delivery_receipts.preprinted_layout',
    'app.journal_entries.preprinted_layout',
    'app.payroll.preprinted_layout',
    'app.sales_invoices.preprinted_layout',
    'app.sales_orders.preprinted_layout',
]

INF = json.loads('1e999')       # exactly what a real JSON payload delivers
NEG_INF = json.loads('-1e999')


@pytest.mark.parametrize('modname', CLAMP_MODULES)
@pytest.mark.parametrize('value', [INF, NEG_INF, '1e999', '-1e999'])
def test_clamp_falls_back_on_an_infinite_value(modname, value):
    clamp = importlib.import_module(modname)._clamp
    assert clamp(value, 0, 500, 42) == 42


@pytest.mark.parametrize('modname', CLAMP_MODULES)
def test_control_clamp_still_clamps_and_still_rejects_the_old_junk(modname):
    """CONTROL: widening the except clause must not turn `_clamp` into a
    pass-through. Without this, `return fallback` unconditionally would satisfy
    every assertion above."""
    clamp = importlib.import_module(modname)._clamp
    assert clamp(250, 0, 500, 42) == 250        # in range -- untouched
    assert clamp(-5000, 0, 500, 42) == 0        # clamped UP to lo
    assert clamp(99999, 0, 500, 42) == 500      # clamped DOWN to hi
    assert clamp('12.7', 0, 500, 42) == 13      # numeric string still coerced
    assert clamp(None, 0, 500, 42) == 42        # TypeError -- still caught
    assert clamp('abc', 0, 500, 42) == 42       # ValueError -- still caught
    assert clamp(json.loads('NaN'), 0, 500, 42) == 42   # ValueError, still caught


def test_no_unlisted_clamp_exists():
    """The list above must stay exhaustive, or a new clone escapes this suite."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / 'app'
    found = set()
    for py in root.rglob('*.py'):
        if 'def _clamp(' in py.read_text(encoding='utf-8'):
            rel = py.relative_to(root.parent).with_suffix('')
            found.add(rel.as_posix().replace('/', '.'))
    assert found == set(CLAMP_MODULES), (
        'unlisted _clamp copies: %r' % sorted(found - set(CLAMP_MODULES)))
