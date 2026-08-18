"""Tests for .claude/guard.py -- the blast-radius mapping script.

Builds a real throwaway git repo per test: the whole point of --head is how it
interacts with real git refs, so a mocked test would prove nothing.
"""
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_CLAUDE = os.path.abspath(os.path.join(_HERE, ".."))
if _CLAUDE not in sys.path:
    sys.path.insert(0, _CLAUDE)

import guard


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo: main has base.txt; feat/x adds shared.css on top."""
    r = tmp_path / "repo"
    r.mkdir()
    _run(["git", "init", "-b", "main"], str(r))
    _run(["git", "config", "user.email", "t@t.test"], str(r))
    _run(["git", "config", "user.name", "T"], str(r))
    (r / "base.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "-A"], str(r))
    _run(["git", "commit", "-m", "base"], str(r))

    _run(["git", "checkout", "-b", "feat/x"], str(r))
    (r / "shared.css").write_text("body{}\n", encoding="utf-8")
    _run(["git", "add", "-A"], str(r))
    _run(["git", "commit", "-m", "add shared.css"], str(r))
    _run(["git", "checkout", "main"], str(r))

    monkeypatch.setattr(guard, "APP_ROOT", str(r))
    return r


def test_head_defaults_to_HEAD_and_sees_nothing_from_main(repo):
    """The v1 defect: with HEAD on main, the branch's files are invisible."""
    assert guard.changed_files("main") == []


def test_head_ref_sees_the_branch_files_without_checking_it_out(repo):
    """The fix: name the branch explicitly and its commits are in the diff."""
    files = guard.changed_files("main", "feat/x")
    assert "shared.css" in files


def test_head_ref_does_not_require_the_branch_to_be_checked_out(repo):
    on = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], str(repo)).stdout.strip()
    assert on == "main", "precondition: HEAD is on main, not the branch"
    assert "shared.css" in guard.changed_files("main", "feat/x")


def test_uncommitted_edits_are_included_only_for_HEAD(repo):
    """An explicit --head names a REF; the working tree's dirt is not part of it."""
    (repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    _run(["git", "add", "-A"], str(repo))
    assert "dirty.txt" in guard.changed_files("main")
    assert "dirty.txt" not in guard.changed_files("main", "feat/x")


def _run_cli(args, cwd):
    """Invoke the real guard.py script as a subprocess -- exercises main()'s exit code,
    not just the library functions. Runs against this worktree's own (populated,
    non-stub) regression-map.json, since MAP is resolved relative to guard.py's own
    location regardless of cwd -- APP_ROOT (== cwd) is what varies per test."""
    script = os.path.join(_CLAUDE, "guard.py")
    return subprocess.run(
        [sys.executable, script, *args], cwd=cwd, capture_output=True, text=True
    )


def test_cli_bad_head_fails_closed(repo):
    """An explicit --head that does not resolve must exit non-zero, not report clean."""
    res = _run_cli(["--base", "main", "--head", "no/such/branch"], str(repo))
    assert res.returncode != 0, res.stdout + res.stderr
    assert "no/such/branch" in (res.stdout + res.stderr)


def test_cli_bad_explicit_base_fails_closed(repo):
    """An explicit --base that resolves neither as origin/<x> nor <x> must fail closed."""
    res = _run_cli(["--base", "nosuchbase", "--head", "main"], str(repo))
    assert res.returncode != 0, res.stdout + res.stderr
    assert "nosuchbase" in (res.stdout + res.stderr)


def test_cli_resolvable_refs_with_no_changes_exit_0(repo):
    """A genuinely resolvable ref pair with nothing changed is still a clean pass."""
    res = _run_cli(["--base", "main", "--head", "main"], str(repo))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "nothing to guard" in res.stdout


def test_cli_no_base_arg_auto_detect_still_falls_back_cleanly(repo):
    """Unchanged behavior: with NO --base passed, auto-detection may legitimately find
    no base ref and fall back to uncommitted-only -- this must stay a clean exit 0, not
    be tightened by this fix."""
    # repo fixture's HEAD is on 'main', which auto-detect WILL find -- so re-point it at
    # an orphan branch and delete 'main' to force auto-detect to genuinely find nothing.
    orphan = repo
    _run(["git", "checkout", "--orphan", "no-base-branch"], str(orphan))
    _run(["git", "rm", "-rf", "--cached", "."], str(orphan))
    (orphan / "only.txt").write_text("x\n", encoding="utf-8")
    _run(["git", "add", "-A"], str(orphan))
    _run(["git", "commit", "-m", "orphan root"], str(orphan))
    _run(["git", "branch", "-D", "main"], str(orphan))
    res = _run_cli([], str(orphan))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "none -- uncommitted only" in res.stdout


# --- marker translation ---------------------------------------------------
# The map's `modules` table exists to translate a module name to the pytest
# marker that actually selects its tests -- debit_memos' tests carry
# credit_memos, sales_vat_categories' carry sales_vat. guard.py joined the
# MODULE names instead, so 22 of 97 map keys (base.html and app/__init__.py
# among them) suggested a `-m` expression naming something no test carries.
# Since the tests/conftest.py -m guard landed, such an expression is a
# UsageError that runs ZERO tests -- the whole union, not just the bad member.
#
# These tests read the REAL regression-map.json and the REAL pytest.ini: the
# defect was a disagreement between those two files, which a fixture cannot
# reproduce (memory feedback-mock-only-tests-cannot-see-seams).
_REPO = os.path.abspath(os.path.join(_CLAUDE, ".."))
_REAL_MAP = json.load(open(os.path.join(_CLAUDE, "regression-map.json"), encoding="utf-8"))


def test_registered_markers_reads_pytest_ini_for_real():
    reg = guard.registered_markers(_REPO)
    assert "accounts_payable" in reg and "credit_memos" in reg and "e2e" in reg
    # debit_memos and sales_vat_categories are ALIASES by design -- they are map
    # module names that resolve to another module's marker, and are deliberately
    # never registered themselves. Unlike vat_settlement (which was simply an
    # unregistered real module, fixed 2026-08-18) these two stay unregistered,
    # so they are the durable examples to pin here.
    assert "debit_memos" not in reg
    assert "sales_vat_categories" not in reg
    assert "vat_settlement" in reg  # registered 2026-08-18; was the 5th hollow marker


def test_module_names_are_translated_to_their_registered_marker():
    expr, unrunnable = guard.marker_expr(["debit_memos", "sales_vat_categories"],
                                         _REAL_MAP, guard.registered_markers(_REPO))
    assert expr == "credit_memos or sales_vat"
    assert unrunnable == []


def test_a_module_whose_marker_is_unregistered_is_excluded_and_named():
    """Pins the BEHAVIOUR with a synthetic name, not whichever real module happens
    to be unregistered today. The first version of this test used vat_settlement and
    went RED the moment that module was repaired -- a test that fails when the codebase
    gets BETTER was pinning the defect instead of the rule."""
    expr, unrunnable = guard.marker_expr(["accounts_payable", "no_such_module_xyz"],
                                         _REAL_MAP, guard.registered_markers(_REPO))
    assert expr == "accounts_payable"
    assert unrunnable == ["no_such_module_xyz"]


def test_two_modules_sharing_one_marker_are_not_repeated():
    expr, _ = guard.marker_expr(["credit_memos", "debit_memos"],
                                _REAL_MAP, guard.registered_markers(_REPO))
    assert expr == "credit_memos"


def test_control_a_plain_registered_module_passes_through_untouched():
    """CONTROL: the translation must not disturb the majority case -- a module
    whose name IS its marker. Without this, a function that returned '' always
    would satisfy every assertion above."""
    expr, unrunnable = guard.marker_expr(["sales_invoices", "accounts_payable"],
                                         _REAL_MAP, guard.registered_markers(_REPO))
    assert expr == "accounts_payable or sales_invoices"
    assert unrunnable == []


def test_every_module_named_anywhere_in_the_real_map_yields_a_runnable_expression():
    """No map key may suggest a command that cannot run."""
    reg = guard.registered_markers(_REPO)
    broken = {}
    for key, deps in _REAL_MAP["blast_radius"].items():
        expr, unrunnable = guard.marker_expr(deps, _REAL_MAP, reg)
        bad = [m for m in expr.split(" or ") if m and m not in reg]
        if bad:
            broken[key] = bad
    assert broken == {}, broken


@pytest.mark.slow
def test_the_suggested_expression_for_base_html_really_collects_tests():
    """THE SEAM. Build the union the way /guard prints it for the highest
    blast-radius key in the map, then hand it to REAL pytest. Before the fix
    this exits 4 (UsageError) and runs nothing, while /guard reports the
    command as its blast-radius evidence."""
    reg = guard.registered_markers(_REPO)
    expr, _ = guard.marker_expr(_REAL_MAP["blast_radius"]["app/templates/base.html"],
                                _REAL_MAP, reg)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov",
         "-p", "no:cacheprovider", "-m", "(%s) and not e2e" % expr],
        cwd=_REPO, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 4, out          # 4 = UsageError
    assert "unregistered marker" not in out
    assert "tests collected" in out


def test_no_map_key_names_a_module_without_a_runnable_marker():
    """The standing invariant: every dependent in the map must be RUNNABLE.

    Its sibling above only asserts the expression that survives filtering is
    clean -- which stays green while marker_expr() quietly drops a module. That
    dropping is the right runtime behaviour (a loud partial run beats a dead
    one) but it must never become the steady state: a silently excluded module
    is a module nobody guards. This asserts the exclusion list is EMPTY.

    It caught vat_settlement, whose map note claimed it was forward-wired for an
    unmerged branch. app/vat_settlement/ has been shipped and deployed for weeks
    with 33 tests carrying no marker, so four keys covering the BIR-filings
    surface -- vat_categories/models.py, reports/{vat_lines,bir,vat_return}.py
    -- were guarded by a union that dropped the VAT-settlement engine.
    """
    reg = guard.registered_markers(_REPO)
    unrunnable = {}
    for key, deps in _REAL_MAP["blast_radius"].items():
        _, missing = guard.marker_expr(deps, _REAL_MAP, reg)
        if missing:
            unrunnable[key] = missing
    assert unrunnable == {}, (
        "map keys naming a module with no registered marker: %r -- register the "
        "marker in pytest.ini and apply it, do not drop the dependent" % unrunnable)
