"""The -m expression guard in tests/conftest.py, exercised against REAL pytest.

`--strict-markers` validates markers APPLIED to tests, never a `-m` EXPRESSION.
Four module markers (purchase_orders, purchase_requests, receiving_reports,
control_accounts) sat in .claude/regression-map.json for weeks while none was
registered, so every /guard union silently ran a smaller suite than it claimed.

These tests drive the pytest CLI in a subprocess on purpose. A mock-only test
would prove the hook's branching and observe nothing about what pytest actually
does with a `-m` string -- which is the entire seam being guarded (memory
`feedback-mock-only-tests-cannot-see-seams`).

Both directions are asserted: the guard must FIRE on an unregistered name, and
must NOT fire on the legitimate expressions this repo actually runs -- a guard
with no control test cannot tell "correctly silent" from "dead"
(memory `feedback-guard-reads-a-field-nothing-writes`).
"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]

USAGE_ERROR = 4  # pytest's ExitCode.USAGE_ERROR
NO_TESTS_COLLECTED = 5  # pytest's ExitCode.NO_TESTS_COLLECTED


# A one-file scope for the tests that only care whether the guard fires. The guard
# runs at collection regardless of scope, and collecting one file instead of 5704
# items keeps this suite ~3x cheaper. The population tests below must NOT use it --
# they need the whole suite in scope to see a marker's real count.
NARROW = 'tests/unit/test_purchase_order_summary.py'


def _collect(markexpr, scope=None):
    """Run `pytest --collect-only -m <markexpr>` for real; return (rc, output)."""
    argv = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '--no-cov',
            '-p', 'no:cacheprovider', '-m', markexpr]
    if scope:
        argv.append(scope)
    proc = subprocess.run(argv, cwd=str(REPO_ROOT), capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def test_unregistered_marker_in_m_expression_is_a_usage_error():
    rc, out = _collect('no_such_marker_xyz', NARROW)
    assert rc == USAGE_ERROR, out
    assert 'no_such_marker_xyz' in out
    assert 'unregistered marker' in out


def test_a_typo_hiding_inside_a_valid_union_still_fails():
    """The dangerous shape: the other members collect tests, so pytest exits 0."""
    rc, out = _collect('(accounts_payable or purchse_orders) and not e2e', NARROW)
    assert rc == USAGE_ERROR, out
    assert 'purchse_orders' in out
    assert 'accounts_payable' not in out.split('unregistered marker(s):')[1][:80]


@pytest.mark.parametrize('expr', [
    'not e2e',
    'e2e',
    '(purchase_orders or purchase_requests or receiving_reports or '
    'control_accounts) and not e2e',
    'accounts_payable and not slow',
])
def test_legitimate_expressions_are_not_blocked(expr):
    """CONTROL: composition, negation and every registered name must pass through."""
    rc, out = _collect(expr, NARROW)
    assert rc != USAGE_ERROR, out
    assert 'unregistered marker' not in out


@pytest.mark.parametrize('marker', [
    'purchase_orders', 'purchase_requests', 'receiving_reports',
    'control_accounts',
    # payroll joined the map 2026-08-18 as preprinted_texts.py's 11th consumer;
    # it is registered and applied in the same commit, so pin it here too.
    'payroll',
])
def test_repaired_module_markers_select_a_non_empty_suite(marker):
    """A registered-but-EMPTY marker is what this branch existed to fix.

    The guard above cannot see this case (the name IS registered), so pin the
    population directly: `no tests collected` for a module with test files means
    the marker went hollow again.
    """
    rc, out = _collect('%s and not e2e' % marker)
    assert rc != NO_TESTS_COLLECTED, out
    assert 'no tests collected' not in out
