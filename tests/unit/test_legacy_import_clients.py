"""Client configuration and the fail-closed target-database guard.

The importer writes 19k posted journal entries that CAS has no edit route for, so
the single most important safety property is that it can never write into the
wrong client's database.
"""
import pytest

from scripts.legacy_import.clients import (
    CLIENTS,
    ClientDisabledError,
    UnknownClientError,
    WrongTargetError,
    assert_target_database,
    get_client,
)

pytestmark = [pytest.mark.unit, pytest.mark.legacy_import]


def test_ric_is_enabled_and_philgen_is_a_disabled_stub():
    assert get_client('ric').enabled is True
    assert CLIENTS['philgen'].enabled is False


def test_disabled_client_refuses_to_load():
    """Philgen's live chart is the generic 146-account manufacturing COA, not its
    own 245-account legacy chart, so its history has nowhere to land yet."""
    with pytest.raises(ClientDisabledError, match='philgen'):
        get_client('philgen')


def test_unknown_client_refuses_to_load():
    with pytest.raises(UnknownClientError):
        get_client('acme')


@pytest.mark.parametrize('uri', [
    'sqlite:///C:/home/ricbooks1968/cas/instance/ric.db',
    'sqlite:////home/ricbooks1968/cas/instance/ric.db',
    r'sqlite:///C:\scratch\ric.db',
])
def test_matching_target_is_accepted(uri):
    assert_target_database(uri, get_client('ric'))


@pytest.mark.parametrize('uri', [
    'sqlite:///instance/philgen.db',
    'sqlite:///instance/cas.db',
    'sqlite:///instance/alvin.db',
    'sqlite:///instance/ric_backup.db',   # near-miss
    'sqlite:///instance/RIC.DB',          # case must match exactly
])
def test_wrong_target_aborts(uri):
    with pytest.raises(WrongTargetError):
        assert_target_database(uri, get_client('ric'))


def test_in_memory_target_aborts():
    """Guards against a test/dev app context sneaking through."""
    with pytest.raises(WrongTargetError):
        assert_target_database('sqlite:///:memory:', get_client('ric'))


def test_ric_config_points_at_the_legacy_accounting_db():
    ric = get_client('ric')
    assert ric.target_db_filename == 'ric.db'
    assert ric.legacy_db.name == 'data.db'
    assert 'ric-workspace' in str(ric.legacy_db)
