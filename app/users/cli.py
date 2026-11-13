"""`flask reset-password <username>`: let a user back in when no other admin can (work order
2026-11-10-cli-admin-password-reset; owner, 10 Nov 2026: "Both"; "PW-2, No, keep the order").

Run from the server's app directory with its venv active. The new password is prompted twice with
hidden input and is never an argument, so it stays out of shell history. The change-password form's
rules apply. The lockout is cleared, the user must choose their own password at the next login, and
an audit row records it (action `password_reset`, "password_reset via CLI", the server user named).
"""
import getpass
from types import SimpleNamespace

import click
from flask.cli import with_appcontext


@click.command('reset-password')
@click.argument('username')
@with_appcontext
def reset_password_cmd(username):
    """Set a new password for USERNAME (prompted twice, hidden); they must change it at next login."""
    from wtforms.validators import ValidationError
    from app import db
    from app.audit.utils import log_audit
    from app.users.models import User
    from app.users.validators import PasswordPolicy

    user = User.query.filter_by(username=username).first()
    if user is None:
        raise click.ClickException(f'No user named {username!r}.')
    if not user.is_active:
        raise click.ClickException(f'User {username!r} is inactive; activate the account first.')

    password = click.prompt('New password', hide_input=True, confirmation_prompt=True)
    try:
        PasswordPolicy(min_length=12)(None, SimpleNamespace(data=password))
    except ValidationError as e:
        raise click.ClickException(f'Password refused: {e}')

    user.set_password(password)
    user.reset_failed_attempts()
    user.account_locked_until = None
    user.must_change_password = True
    db.session.commit()
    try:
        server_user = getpass.getuser()
    except Exception:
        server_user = 'unknown'
    log_audit(module='user', action='password_reset', record_id=user.id,
              record_identifier=f'{user.username} ({user.full_name})',
              notes=f'password_reset via CLI by server user {server_user}; must change at next login')
    click.echo(f'Password reset for {username}. They must choose their own at the next login.')
