"""Per-client configuration, and the guard that keeps the importer off the wrong DB.

Entries are imported already POSTED, and CAS has no journal-entry edit route, so
writing into the wrong client's database has no in-app repair path. The target
filename is therefore asserted before anything is read, let alone written --
mirroring `scripts/ric_coa/import_coa.py::_assert_target_is_ric`, generalized.

Philgen is present but DISABLED: its live book carries the generic 146-account
manufacturing chart while its history uses 245 different codes, so its chart must
first be rebuilt from its legacy COA (the way RIC's was). Enabling it is then a
config change, not a rewrite.
"""
from dataclasses import dataclass
from pathlib import Path

from scripts.legacy_import.account_map import ACCOUNT_RECODES


class UnknownClientError(RuntimeError):
    """No such client slug."""


class ClientDisabledError(RuntimeError):
    """The client is configured but not yet safe to import."""


class WrongTargetError(RuntimeError):
    """The app is pointed at a database that is not this client's."""


@dataclass(frozen=True)
class ClientConfig:
    slug: str
    legacy_db: Path
    target_db_filename: str
    branch_codes: dict          # schema.CORP/EXTRA -> the client's Branch.code
    recodes: dict
    enabled: bool
    disabled_reason: str = ''


RIC = ClientConfig(
    slug='ric',
    legacy_db=Path(r'C:\envs\ric-workspace\legacy ric\accounting\instance\data.db'),
    target_db_filename='ric.db',
    branch_codes={'CORP': '00000', 'EXTRA': '00000-X'},
    recodes=ACCOUNT_RECODES,
    enabled=True,
)

PHILGEN = ClientConfig(
    slug='philgen',
    legacy_db=Path(r'C:\envs\legacy philgen\accounting_philgen\instance\data.db'),
    target_db_filename='philgen.db',
    branch_codes={},
    recodes={},
    enabled=False,
    disabled_reason=(
        'philgen: the live book carries the generic 146-account manufacturing '
        'chart, but its history uses 245 legacy codes. Rebuild and reconcile its '
        'COA from the legacy chart first (the RIC pattern), then enable.'
    ),
)

CLIENTS = {client.slug: client for client in (RIC, PHILGEN)}


def get_client(slug):
    try:
        client = CLIENTS[slug]
    except KeyError:
        known = ', '.join(sorted(CLIENTS))
        raise UnknownClientError(f'unknown client {slug!r}; known: {known}') from None
    if not client.enabled:
        raise ClientDisabledError(client.disabled_reason or f'{slug} is disabled')
    return client


def database_filename(uri):
    """Last path segment of a SQLAlchemy URI, tolerating both path separators."""
    tail = str(uri).rsplit('/', 1)[-1]
    return tail.rsplit('\\', 1)[-1]


def assert_target_database(uri, client):
    """Abort unless the app is pointed at exactly this client's database file."""
    name = database_filename(uri)
    if name != client.target_db_filename:
        raise WrongTargetError(
            f'SAFETY: target is not {client.target_db_filename} -> {uri}'
        )
