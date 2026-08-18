#!/usr/bin/env python
"""
Regression guard -- map changed files to the "done" modules that depend on them
(via .claude/regression-map.json) and, on demand, run those modules' e2e smoke as a
pre-push gate.

Project-agnostic: reads the regression map from THIS script's own dir, and runs git +
pytest against the CWD (the app repo). The same script is dropped into each project's
.claude/. The workspace /guard skill invokes it with the project's own interpreter.

Usage:
  python .claude/guard.py              # dry run: print affected modules + suggested pytest cmds
  python .claude/guard.py --run-e2e    # run the e2e gate for affected modules; exit != 0 on failure
  python .claude/guard.py --base main  # compare against a specific base branch
                                       # (default: auto-detect main/master)
  python .claude/guard.py --head feat/x  # diff a branch that is NOT checked out
                                         # (default: HEAD, the checked-out tree)

Changed files = (<base>)...<head>, where <head> defaults to HEAD.
When <head> is HEAD, uncommitted working-tree changes are folded in too; when an
explicit --head ref is given they are NOT (that dirt belongs to whatever is checked
out, not to the branch being asked about).
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(SCRIPT_DIR, 'regression-map.json')
APP_ROOT = os.getcwd()


def _git(args):
    return subprocess.run(['git', *args], cwd=APP_ROOT, capture_output=True, text=True)


def _ref_exists(ref):
    return _git(['rev-parse', '--verify', '--quiet', ref]).returncode == 0


def resolve_base(explicit):
    """First existing ref among the candidates. Explicit base wins; else auto-detect
    main/master so the guard works on either default-branch convention."""
    if explicit:
        candidates = [f'origin/{explicit}', explicit]
    else:
        candidates = ['origin/main', 'main', 'origin/master', 'master']
    for ref in candidates:
        if _ref_exists(ref):
            return ref
    return None  # no base ref found -- fall back to uncommitted-only diff


def changed_files(base_ref, head_ref='HEAD'):
    """Changed paths between base and head.

    head_ref defaults to HEAD (the checked-out tree). Pass an explicit ref -- e.g. the
    branch /ship is about to merge -- to diff a branch that is NOT checked out. This
    exists because /ship runs with HEAD on the default branch (its merge step requires
    that), so '<base>...HEAD' would diff the default branch against itself and see none
    of the branch's commits.
    """
    files = []
    if base_ref:
        res = _git(['diff', '--name-only', f'{base_ref}...{head_ref}'])
        if res.returncode == 0:
            files = [l.strip().replace('\\', '/') for l in res.stdout.splitlines() if l.strip()]
    # Uncommitted edits belong to the WORKING TREE, not to some other branch's ref --
    # include them only when we are actually guarding the checked-out tree.
    if head_ref == 'HEAD':
        un = _git(['diff', '--name-only', 'HEAD'])
        if un.returncode == 0:
            files += [l.strip().replace('\\', '/') for l in un.stdout.splitlines() if l.strip()]
    return sorted(set(files))


# UI-touching = a real-browser surface pytest's test client can't fully exercise.
# fnmatch '*' spans '/', so '*/templates/*' also matches 'app/<feature>/templates/x.html'.
UI_PATTERNS = (
    '*/templates/*',
    '*/static/*.js',
    '*/static/*.css',
    '*/views.py',
    '*/routes.py',
)


def ui_touching(files):
    """Subset of changed paths that touch a UI surface (templates / JS / CSS / route files)."""
    return [f for f in files if any(fnmatch.fnmatch(f, pat) for pat in UI_PATTERNS)]


def current_branch():
    res = _git(['rev-parse', '--abbrev-ref', 'HEAD'])
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else 'HEAD'


def affected_modules(files, mapping):
    blast = mapping.get('blast_radius', {})
    mods = set()
    for f in files:
        if f in blast:
            mods.update(blast[f])
    return mods


def registered_markers(app_root=None):
    """Marker names registered under [pytest] markers in pytest.ini.

    Parsed from the file rather than asked of pytest: the guard has to be able to
    say "nothing carries that marker" without paying for a full collection run.
    Returns an empty set when there is no pytest.ini -- callers must treat that
    as "registry unknown", not as "nothing is registered".
    """
    root = app_root or APP_ROOT
    path = os.path.join(root, 'pytest.ini')
    names = set()
    if not os.path.exists(path):
        return names
    in_block = False
    with open(path, encoding='utf-8') as fh:
        for raw in fh:
            line = raw.rstrip()
            if re.match(r'^\s*markers\s*=', line):
                in_block = True
                rest = line.split('=', 1)[1].strip()
                if rest:
                    names.add(rest.split(':', 1)[0].split('(', 1)[0].strip())
                continue
            if not in_block:
                continue
            if not line.strip():
                continue
            if not line[:1].isspace():
                break  # dedented -- the markers block ended
            entry = line.strip()
            if entry.startswith('#') or entry.startswith('['):
                continue
            names.add(entry.split(':', 1)[0].split('(', 1)[0].strip())
    return names


def marker_expr(mods, mapping, registered=None):
    """Build a -m expression for a set of module names.

    Returns (expression, modules-with-no-runnable-marker).

    A module's pytest marker is NOT always its name: the map's own `modules`
    table carries the translation (debit_memos' tests are marked credit_memos,
    sales_vat_categories' are marked sales_vat). Joining the MODULE names
    instead named a marker that no test carries -- silently selecting nothing
    before tests/conftest.py's -m guard existed, and a UsageError that runs
    ZERO tests, union and all, after it. 22 of 97 map keys were affected,
    including base.html, app/__init__.py and every app/posting/ file.
    """
    meta = mapping.get('modules', {})
    if registered is None:
        registered = registered_markers()
    markers, unrunnable = set(), set()
    for mod in mods:
        marker = meta.get(mod, {}).get('marker') or mod
        # An empty registry means pytest.ini could not be read -- filtering on it
        # would silently empty the expression, which is the failure this guards.
        if registered and marker not in registered:
            unrunnable.add(mod)
        else:
            markers.add(marker)
    return ' or '.join(sorted(markers)), sorted(unrunnable)


def _warn_unrunnable(unrunnable):
    print('[guard] WARNING: no registered pytest marker for: ' + ', '.join(unrunnable)
          + ' -- EXCLUDED below, so these modules are NOT covered by it. Register the '
            'marker in pytest.ini and apply it to their tests, or run them by path.')


def main():
    argv = sys.argv[1:]
    run_e2e = '--run-e2e' in argv
    explicit_base = None
    if '--base' in argv:
        explicit_base = argv[argv.index('--base') + 1]

    explicit_head = None
    if '--head' in argv:
        explicit_head = argv[argv.index('--head') + 1]

    # An EXPLICITLY provided ref that does not resolve must fail closed -- silently
    # guarding nothing and reporting a clean pass is indistinguishable from a real
    # verified-clean pass. Auto-detection (no --base given) is unaffected: it may
    # legitimately find nothing and fall back to uncommitted-only, unchanged below.
    if explicit_head is not None and not _ref_exists(explicit_head):
        print(f'[guard] ERROR: --head ref does not resolve: {explicit_head!r}')
        print('[guard] cannot verify changed files against an unresolvable ref -- refusing '
              'to report a clean pass.')
        return 1

    with open(MAP, encoding='utf-8') as fh:
        mapping = json.load(fh)

    # A stub map (empty blast_radius) can NEVER prove safety -- it is not a clean pass.
    is_stub = not mapping.get('blast_radius')

    base_ref = resolve_base(explicit_base)
    if explicit_base is not None and base_ref is None:
        print(f'[guard] ERROR: --base ref does not resolve: {explicit_base!r} '
              f'(tried origin/{explicit_base} and {explicit_base})')
        print('[guard] cannot verify changed files against an unresolvable ref -- refusing '
              'to report a clean pass.')
        return 1

    files = changed_files(base_ref, explicit_head or 'HEAD')
    mods = affected_modules(files, mapping)
    print(f'[guard] base={base_ref or "(none -- uncommitted only)"}')

    ui_hits = ui_touching(files)
    if ui_hits:
        print(f'[guard] UI-touching changes detected ({len(ui_hits)} file(s)) -- '
              f'run /ui-test <slug> --branch {explicit_head or current_branch()} before merging '
              f'(browser-only defects pass pytest + this guard).')

    if is_stub:
        # Distinguish "map unpopulated" from a genuine "nothing changed" green.
        print('[guard] STUB MAP: regression-map.json blast_radius is empty -- CANNOT CERTIFY. '
              'This is NOT a clean pass; populate the map to guard this project.')
        # Return 0 so a legitimate push is not blocked while the map is still being built,
        # but the message above makes the /guard skill report "cannot certify," not "safe."
        return 0

    if not mods:
        print('[guard] no high-blast-radius shared files changed -- nothing to guard.')
        return 0

    print('[guard] changed shared files affect modules:', ', '.join(sorted(mods)))
    e2e_mods = sorted(m for m in mods if mapping['modules'].get(m, {}).get('e2e'))

    registered = registered_markers()
    if not registered:
        print('[guard] WARNING: could not read pytest.ini markers -- cannot tell a real '
              'marker from a typo; the expressions below are unverified.')
    expr, unrunnable = marker_expr(mods, mapping, registered)

    if not run_e2e:
        if unrunnable:
            _warn_unrunnable(unrunnable)
        if expr:
            print(f'[guard] suggested: pytest -m "{expr}"')
        else:
            print('[guard] NO affected module has a runnable marker -- this guard CANNOT '
                  'certify the change. Run the affected modules by path.')
        if e2e_mods:
            e2e_expr, _ = marker_expr(e2e_mods, mapping, registered)
            if e2e_expr:
                print(f'[guard] e2e gate:  pytest -m "e2e and ({e2e_expr})"')
            else:
                print('[guard] (affected e2e suites have no runnable marker)')
        else:
            print('[guard] (no e2e suites for these modules yet)')
        return 0

    if not e2e_mods:
        print('[guard] no e2e suites for affected modules -- e2e gate passes by default.')
        return 0

    e2e_expr, e2e_unrunnable = marker_expr(e2e_mods, mapping, registered)
    if e2e_unrunnable:
        _warn_unrunnable(e2e_unrunnable)
    if not e2e_expr:
        # The gate was supposed to run and cannot. Passing here would report a
        # green e2e gate for a run that executed nothing.
        print('[guard] ERROR: affected e2e suites exist but none has a runnable marker -- '
              'refusing to report a passing e2e gate.')
        return 1

    marker = 'e2e and (' + e2e_expr + ')'
    print(f'[guard] running e2e gate: pytest -m "{marker}"')
    rc = subprocess.run(
        [sys.executable, '-m', 'pytest', '-m', marker, '-o', 'addopts=', '-q'],
        cwd=APP_ROOT,
    ).returncode
    if rc != 0:
        print('\n[guard] E2E REGRESSION DETECTED -- push blocked.')
        print('[guard] Fix the smoke failure, or set GUARD_SKIP=1 to override (not recommended).')
    else:
        print('[guard] e2e gate passed.')
    return rc


if __name__ == '__main__':
    sys.exit(main())
