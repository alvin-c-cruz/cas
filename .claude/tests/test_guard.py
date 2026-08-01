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
