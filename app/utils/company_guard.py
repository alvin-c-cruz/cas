"""Refuse to serve one company's code session against another company's database.

Several companies run this same codebase, each on its own SQLite file
(instance/philgen.db, instance/ric.db, ...). Locally the file is chosen by
SQLALCHEMY_DATABASE_URI, and the only in-app tell of WHICH file is loaded is the
company name in the sidebar. That is easy to miss mid-test: a server restarted
from a terminal whose .env had been flipped to the other company would happily
serve the wrong books.

`company_mismatch(expected)` compares a short launcher-side label ('philgen',
'ric') against the `company_name` row stored inside the database, so the data
vouches for itself. It returns None when they agree and a human-readable reason
when they do not; the dev entrypoint turns a reason into a refusal to boot.

Deliberately NOT wired into production (wsgi.py): a PythonAnywhere account
serves exactly one database and needs no second opinion.
"""

# label -> substring that must appear (case-insensitively) in the stored
# company_name. Keep the substrings short and distinctive; a full legal name
# would break the moment Company Settings is edited for a typo.
COMPANY_MARKERS = {
    'philgen': 'philgen',
    'ric': 'rowell industrial',
}


def company_mismatch(expected):
    """Return None if the loaded DB belongs to `expected`, else a reason string.

    Must be called inside an application context. Any failure to read the
    setting (unmigrated DB, missing table) is reported as a mismatch rather than
    raised: a guard that crashes is a guard that gets disabled.
    """
    label = (expected or '').strip().lower()
    marker = COMPANY_MARKERS.get(label)
    if marker is None:
        return (f"Unknown company label '{expected}'. "
                f"Known labels: {', '.join(sorted(COMPANY_MARKERS))}.")

    try:
        from app.settings import AppSettings
        actual = AppSettings.get_setting('company_name')
    except Exception as exc:  # noqa: BLE001 - see docstring
        return f"Could not read company_name from the database ({exc.__class__.__name__}: {exc})."

    if actual and marker in actual.lower():
        return None

    shown = actual if actual else '(not set)'
    return (f"Expected company '{label}' but the database says company_name = "
            f"'{shown}'. Wrong SQLALCHEMY_DATABASE_URI for this session?")
