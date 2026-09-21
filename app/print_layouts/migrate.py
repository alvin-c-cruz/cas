"""Copy existing app_settings layouts into named_print_layouts rows.

Lives in app/ rather than inside the migration file so it is importable and
testable. The migration calls it; so does the verification tool.
"""
from app import db
from app.settings import AppSettings
from app.print_layouts.models import PrintLayout


def _branch_label(branch_id):
    from app.branches.models import Branch
    branch = Branch.query.get(branch_id) if branch_id else None
    return f'Default - {branch.name}' if branch is not None else 'Default'


def seed_from_app_settings(doc_type, key_prefix):
    """One is_default row per existing `<key_prefix>` / `<key_prefix>:<id>` setting.

    Payload copied RAW. Idempotent: a scope that already has any row is skipped, so
    re-running against a restored database cannot duplicate or overwrite.
    """
    rows = AppSettings.query.filter(
        db.or_(AppSettings.key == key_prefix,
               AppSettings.key.like(f'{key_prefix}:%'))).all()
    created = 0
    for setting in rows:
        suffix = setting.key[len(key_prefix):].lstrip(':')
        try:
            scope_id = int(suffix) if suffix else 0
        except ValueError:
            continue    # not a scope key -- leave it alone
        exists = PrintLayout.query.filter_by(doc_type=doc_type, scope_id=scope_id).first()
        if exists is not None:
            continue
        db.session.add(PrintLayout(
            doc_type=doc_type, scope_id=scope_id,
            name=_branch_label(scope_id), payload=setting.value, is_default=True))
        created += 1
    db.session.commit()
    return created
