"""Find functions where `current_app` is used on a line before a local
`from flask import current_app` in the same function (UnboundLocalError trap)."""
import ast
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent / 'app'
hits = []

for py in root.rglob('*.py'):
    tree = ast.parse(py.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        import_lines = [n.lineno for n in ast.walk(node)
                        if isinstance(n, ast.ImportFrom) and n.module == 'flask'
                        and any(a.name == 'current_app' for a in n.names)]
        if not import_lines:
            continue
        first_import = min(import_lines)
        uses_before = [n.lineno for n in ast.walk(node)
                       if isinstance(n, ast.Name) and n.id == 'current_app'
                       and n.lineno < first_import]
        if uses_before:
            hits.append(f'{py.relative_to(root.parent)}:{node.lineno} {node.name}() '
                        f'uses current_app at line(s) {uses_before} before local import at {first_import}')

print('\n'.join(hits) if hits else 'No shadowing bugs found.')
