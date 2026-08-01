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
