"""Find functions where a name is used on a line before a local
`from <module> import <name>` in the same function (UnboundLocalError trap).

Checks the import/name pairs in WATCHED below (B-015 class of bug).
"""
import ast
import pathlib

WATCHED = [
    ('flask', 'current_app'),
    ('app.audit.utils', 'log_audit'),
]

root = pathlib.Path(__file__).resolve().parent.parent / 'app'
hits = []

for py in root.rglob('*.py'):
    tree = ast.parse(py.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for module, name in WATCHED:
            import_lines = [n.lineno for n in ast.walk(node)
                            if isinstance(n, ast.ImportFrom) and n.module == module
                            and any(a.name == name for a in n.names)]
            if not import_lines:
                continue
            first_import = min(import_lines)
            uses_before = [n.lineno for n in ast.walk(node)
                           if isinstance(n, ast.Name) and n.id == name
                           and n.lineno < first_import]
            if uses_before:
                hits.append(f'{py.relative_to(root.parent)}:{node.lineno} {node.name}() '
                            f'uses {name} at line(s) {uses_before} before local import at {first_import}')

print('\n'.join(hits) if hits else 'No shadowing bugs found.')
