#!/usr/bin/env python
"""
CAS regression guard — map changed files to the "done" modules that depend on them
(via .claude/regression-map.json) and, on demand, run those modules' e2e smoke as a
pre-push gate.

Usage:
  python .claude/guard.py              # dry run: print affected modules + suggested pytest cmds
  python .claude/guard.py --run-e2e    # run the e2e gate for affected modules; exit != 0 on failure
  python .claude/guard.py --base main  # compare against a different base branch (default: main)

Changed files = (origin/<base> or <base>)...HEAD  PLUS uncommitted working-tree changes.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, '.claude', 'regression-map.json')


def _git(args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)


def changed_files(base):
    files = []
    for ref in (f'origin/{base}', base):
        res = _git(['diff', '--name-only', f'{ref}...HEAD'])
        if res.returncode == 0:
            files = [l.strip().replace('\\', '/') for l in res.stdout.splitlines() if l.strip()]
            break
    # include uncommitted edits too (so a dirty tree is guarded before commit)
    un = _git(['diff', '--name-only', 'HEAD'])
    if un.returncode == 0:
        files += [l.strip().replace('\\', '/') for l in un.stdout.splitlines() if l.strip()]
    return sorted(set(files))


def affected_modules(files, mapping):
    blast = mapping['blast_radius']
    mods = set()
    for f in files:
        if f in blast:
            mods.update(blast[f])
    return mods


def main():
    argv = sys.argv[1:]
    run_e2e = '--run-e2e' in argv
    base = 'main'
    if '--base' in argv:
        base = argv[argv.index('--base') + 1]

    with open(MAP, encoding='utf-8') as fh:
        mapping = json.load(fh)

    files = changed_files(base)
    mods = affected_modules(files, mapping)

    if not mods:
        print('[guard] no high-blast-radius shared files changed — nothing to guard.')
        return 0

    print('[guard] changed shared files affect modules:', ', '.join(sorted(mods)))
    e2e_mods = sorted(m for m in mods if mapping['modules'].get(m, {}).get('e2e'))

    if not run_e2e:
        print(f'[guard] suggested: pytest -m "{" or ".join(sorted(mods))}"')
        if e2e_mods:
            print(f'[guard] e2e gate:  pytest -m "e2e and ({" or ".join(e2e_mods)})"')
        else:
            print('[guard] (no e2e suites for these modules yet)')
        return 0

    if not e2e_mods:
        print('[guard] no e2e suites for affected modules — e2e gate passes by default.')
        return 0

    marker = 'e2e and (' + ' or '.join(e2e_mods) + ')'
    print(f'[guard] running e2e gate: pytest -m "{marker}"')
    rc = subprocess.run(
        [sys.executable, '-m', 'pytest', '-m', marker, '-o', 'addopts=', '-q'],
        cwd=ROOT,
    ).returncode
    if rc != 0:
        print('\n[guard] E2E REGRESSION DETECTED — push blocked.')
        print('[guard] Fix the smoke failure, or set GUARD_SKIP=1 to override (not recommended).')
    else:
        print('[guard] e2e gate passed.')
    return rc


if __name__ == '__main__':
    sys.exit(main())
