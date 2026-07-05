"""Task 8 — backup CLI commands are registered on the app.

The command logic (run_backup / verify_latest) is fully covered by the service
unit tests; this asserts the CLI wiring."""
import pytest

pytestmark = [pytest.mark.integration]


def test_cli_commands_registered(app):
    assert 'backup-run' in app.cli.commands
    assert 'backup-verify' in app.cli.commands
    assert 'backup-restore' in app.cli.commands
