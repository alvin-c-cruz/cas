from urllib.parse import urlparse, urljoin
from functools import wraps
from datetime import timezone, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, limiter
from app.branches.models import Branch
from app.users.models import User
from app.users.forms import LoginForm, RegistrationForm, UserForm, ChangePasswordForm
from app.utils import ph_now
from app.audit.utils import log_audit, log_create, log_update, log_delete, model_to_dict
from app.notifications.utils import create_notification


users_bp = Blueprint('users', __name__, template_folder='templates')

# A throwaway hash compared against when the submitted username matches no user,
# so the unknown-user path spends the same time hashing as the wrong-password
# path and cannot be distinguished by response timing (BUG-SEC-06).
_DUMMY_PASSWORD_HASH = generate_password_hash('cas-login-timing-equalizer')


def admin_required(f):
    """Decorator to require admin role for user management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('You need administrator privileges to access User Management.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _is_safe_url(target):
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ('http', 'https') and ref.netloc == test.netloc


def _check_login_guards(user, form):
    """Run pre-auth checks: locked account, bad credentials, inactive account.

    Returns a rendered response if a guard fired, or None if all checks pass.
    """
    if user and user.is_account_locked():
        log_audit(module='auth', action='login_failed', record_id=user.id,
                  record_identifier=user.username,
                  notes='Account locked due to multiple failed login attempts')
        lockout_time = user.account_locked_until
        if lockout_time:
            if lockout_time.tzinfo is None:
                PHT = timezone(timedelta(hours=8))
                lockout_time = lockout_time.replace(tzinfo=PHT)
            minutes_remaining = int((lockout_time - ph_now()).total_seconds() / 60)
            flash(f'Your account is locked due to multiple failed login attempts. '
                  f'Please try again in {minutes_remaining} minutes or contact the administrator.',
                  'error')
        else:
            flash('Your account is locked. Please contact the administrator.', 'error')
        return render_template('users/login.html', form=form), 401

    # Always run a password-hash comparison, even when the username matched no
    # user, so the unknown-user and wrong-password paths take the same time and
    # cannot be told apart by response timing (BUG-SEC-06).
    if user is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, form.password.data)
        password_ok = False
    else:
        password_ok = user.check_password(form.password.data)

    if not password_ok:
        if user:
            account_locked = user.increment_failed_attempts(max_attempts=5, lockout_minutes=15)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            log_audit(module='auth',
                      action='account_locked' if account_locked else 'login_failed',
                      record_id=user.id, record_identifier=user.username,
                      notes='Too many failed attempts - account locked' if account_locked else 'Invalid password')
            if account_locked:
                flash('Too many failed login attempts. Your account has been locked for 15 minutes.', 'error')
            else:
                # Uniform message for every bad-credential outcome — never reveal
                # whether the username exists or how many attempts remain, which
                # would let an attacker enumerate valid usernames (BUG-SEC-04).
                flash('Invalid username or password.', 'error')
        else:
            log_audit(module='auth', action='login_failed', record_id=None,
                      record_identifier=form.username.data, notes='Invalid username')
            flash('Invalid username or password.', 'error')
        return render_template('users/login.html', form=form), 401

    if not user.is_active:
        log_audit(module='auth', action='login_failed', record_id=user.id,
                  record_identifier=user.username, notes='Account inactive')
        if user.last_login is None:
            flash('Your account is pending approval. Please wait for an administrator to activate your account.', 'error')
        else:
            flash('Your account has been deactivated. Please contact the administrator.', 'error')
        return render_template('users/login.html', form=form), 401

    return None


def _post_login_redirect(user, form):
    """Persist successful login state and redirect to branch or dashboard."""
    try:
        user.last_login = ph_now()
        user.reset_failed_attempts()
        log_audit(module='auth', action='login_success', record_id=user.id,
                  record_identifier=user.username,
                  notes=f'Login successful. Remember me: {form.remember_me.data}',
                  user_id=user.id)
        db.session.commit()
    except Exception:
        db.session.rollback()

    from app.users.utils import get_accessible_branches
    accessible_branches = get_accessible_branches(user)

    if not accessible_branches:
        flash('No branches available. Please contact the administrator.', 'error')
        logout_user()
        return redirect(url_for('users.login'))

    if len(accessible_branches) == 1:
        branch = accessible_branches[0]
        session['selected_branch_id'] = branch.id
        # Skip the audit entry when the company has a single branch — the
        # auto-selection isn't a real choice and just clutters the log.
        if Branch.query.filter_by(is_active=True).count() > 1:
            log_audit(module='auth', action='branch_selected', record_id=user.id,
                      record_identifier=user.username,
                      notes=f'Auto-selected branch: {branch.name} (ID: {branch.id}) — single accessible branch')
        flash(f'Welcome back, {user.full_name}!', 'success')
        next_page = request.args.get('next')
        if next_page and _is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for('dashboard.index'))

    session['needs_branch_selection'] = True
    flash(f'Welcome back, {user.full_name}! Please select your branch.', 'info')
    next_page = request.args.get('next')
    if next_page and _is_safe_url(next_page):
        return redirect(url_for('users.select_branch', next=next_page))
    return redirect(url_for('users.select_branch'))


@users_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 50 per hour', methods=['POST'])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()

    if form.validate_on_submit():
        # Case-insensitive, whitespace-trimmed lookup so 'Admin', 'admin' and
        # ' admin ' all resolve to the same account — otherwise case/space
        # variants create distinct rows and bypass the lockout counter
        # (BUG-SEC-05).
        username = form.username.data.strip()
        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        guard_response = _check_login_guards(user, form)
        if guard_response is not None:
            return guard_response
        login_user(user, remember=form.remember_me.data)
        return _post_login_redirect(user, form)

    return render_template('users/login.html', form=form)


@users_bp.route('/select-branch', methods=['GET', 'POST'])
@login_required
def select_branch():
    """Branch selection page (for users with access to multiple branches)."""
    # Get the 'next' URL parameter (where to redirect after branch selection)
    _raw_next = request.args.get('next') or request.form.get('next')
    next_url = _raw_next if (_raw_next and _is_safe_url(_raw_next)) else url_for('dashboard.index')

    # Get accessible branches for current user
    from app.users.utils import get_accessible_branches
    accessible_branches = get_accessible_branches(current_user)

    # If only one branch, redirect directly
    if len(accessible_branches) == 1:
        session['selected_branch_id'] = accessible_branches[0].id
        session.pop('needs_branch_selection', None)
        return redirect(next_url)

    # If no branches, error
    if not accessible_branches:
        log_audit(
            module='auth',
            action='logout',
            record_id=current_user.id,
            record_identifier=current_user.username,
            notes='Forced logout: no accessible branches'
        )
        flash('No branches available. Please contact the administrator.', 'error')
        logout_user()
        return redirect(url_for('users.login'))

    # Handle branch selection
    if request.method == 'POST':
        branch_id = request.form.get('branch_id', type=int)

        # Verify user has access to selected branch
        branch_ids = [b.id for b in accessible_branches]
        if branch_id not in branch_ids:
            flash('You do not have access to that branch.', 'error')
            return render_template('users/select_branch.html', branches=accessible_branches, next_url=next_url)

        # Set selected branch
        session['selected_branch_id'] = branch_id
        session.pop('needs_branch_selection', None)

        selected_branch = next(b for b in accessible_branches if b.id == branch_id)

        # Log branch selection
        log_audit(
            module='auth',
            action='branch_selected',
            record_id=current_user.id,
            record_identifier=current_user.username,
            notes=f'Selected branch: {selected_branch.name} (ID: {branch_id})'
        )

        flash(f'You are now working in: {selected_branch.name}', 'success')
        return redirect(next_url)

    return render_template('users/select_branch.html', branches=accessible_branches, next_url=next_url)


@users_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    # Log logout before clearing session
    selected_branch = session.get('selected_branch_id')
    log_audit(
        module='auth',
        action='logout',
        record_id=current_user.id,
        record_identifier=current_user.username,
        notes=f'Logout from branch ID: {selected_branch}' if selected_branch else 'Logout'
    )

    # Clear all flash messages and branch selection before logging out
    session.pop('_flashes', None)
    session.pop('selected_branch_id', None)
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('users.login'))


@users_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 50 per hour', methods=['POST'])
def register():
    """User registration (public)."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            from app.users.approved_emails import ApprovedEmail
            approved_email = ApprovedEmail.get_approved_email(form.email.data)

            # Feature B: a role-stamped approved email creates the user *active* with
            # the delegated role + branch(es). A legacy row (role=None) falls back to
            # the original behavior — a view-only account pending admin activation.
            delegated = approved_email is not None and approved_email.role

            user = User(
                username=form.username.data,
                email=form.email.data,
                full_name=form.full_name.data,
                role=approved_email.role if delegated else 'viewer',
                is_active=True if delegated else False
            )
            user.set_password(form.password.data)

            db.session.add(user)
            db.session.flush()  # get user.id before assigning branches

            if delegated:
                user.set_branches(list(approved_email.branches))
                # Apply any admin-stamped module permissions ({} = configure later)
                user.set_book_permissions(approved_email.get_book_permissions())

            db.session.commit()

            # Mark the approved email as used
            if approved_email:
                approved_email.mark_as_used(user.id)

            # Log successful registration
            log_audit(
                module='user_registration',
                action='registration_success',
                record_id=user.id,
                record_identifier=f'{user.username} ({user.email})',
                notes=(f'User registered as {user.role} (active)'
                       if delegated else
                       'User registered successfully, pending admin approval')
            )

            if delegated:
                flash('Registration successful! Your account is active — you can log in now.', 'success')
            else:
                flash('Registration successful! Your account is pending admin approval. You will be able to log in once your account is activated.', 'success')
            return redirect(url_for('users.login'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error during user registration", exc_info=True)
            log_exception(e, severity='ERROR', module='users.register')
            db.session.rollback()
            flash(f'An error occurred during registration: {str(e)}', 'error')

    return render_template('users/register.html', form=form)


@users_bp.route('/users')
@login_required
@admin_required
def list_users():
    """List all users (admin only)."""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users/list.html', users=users)


# NOTE: Admin user creation has been removed by design — users are onboarded
# via self-registration (/register, gated by the ApprovedEmail whitelist), not
# created by an admin. Admins still promote roles and assign branches via
# edit_user below. There is intentionally no /users/create route.


@users_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    """Edit existing user (admin only)."""

    user = db.get_or_404(User, id)

    form = UserForm(obj=user)

    # Populate branch choices for multi-select
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    form.branch_ids.choices = [(b.id, b.name) for b in branches]

    # Pre-populate selected branches for GET request
    if request.method == 'GET':
        form.branch_ids.data = user.get_branch_ids()

    if form.validate_on_submit():
        # CRITICAL: Prevent admins from deactivating their own account
        if user.id == current_user.id and not form.is_active.data:
            flash('You cannot deactivate your own account.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # CRITICAL: Prevent admins from changing their own role
        if user.id == current_user.id and user.role != form.role.data:
            flash('You cannot change your own role.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # CRITICAL: Prevent username changes (username is immutable after account creation)
        if user.username != form.username.data:
            flash('Username cannot be changed after account creation.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # CRITICAL: Prevent email changes (email is immutable after account creation)
        if user.email != form.email.data:
            flash('Email cannot be changed after account creation.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # Check for duplicate email (excluding current user)
        existing_email = User.query.filter(User.email == form.email.data, User.id != id).first()
        if existing_email:
            flash(f'Email "{form.email.data}" already exists. Please use a different email.', 'error')
            return render_template('users/form.html', form=form, user=user)

        try:
            # Capture old values before update
            old_values = model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])
            old_branch_ids = sorted(user.get_branch_ids())
            old_book_permissions = user.get_book_permissions()

            # Username is immutable - do not update it
            # user.username = form.username.data  # REMOVED - username cannot be changed
            # Email is immutable - do not update it
            # user.email = form.email.data  # REMOVED - email cannot be changed
            user.full_name = form.full_name.data
            user.role = form.role.data
            user.is_active = form.is_active.data

            # Update branch assignments
            new_branch_ids = sorted(form.branch_ids.data) if form.branch_ids.data else []
            if form.branch_ids.data:
                selected_branches = Branch.query.filter(Branch.id.in_(form.branch_ids.data)).all()
                user.set_branches(selected_branches)
            else:
                user.set_branches([])  # Clear all branches if none selected

            # Update password if provided
            password_changed = False
            account_unlocked = False
            if form.password.data:
                user.set_password(form.password.data)
                password_changed = True

            # Update book permissions from form (driven by the module registry)
            from app.users.module_access import MODULE_REGISTRY
            book_permissions = {
                m['key']: request.form.get('book_' + m['key']) == '1'
                for m in MODULE_REGISTRY if not m.get('optional')
            }
            user.set_book_permissions(book_permissions)

            # Handle account unlock if checkbox is checked
            unlock_account = request.form.get('unlock_account') == '1'
            if unlock_account and user.is_account_locked():
                user.reset_failed_attempts()
                account_unlocked = True

            db.session.commit()

            # Audit log - Basic user info update
            new_values = model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])
            log_update(
                module='user',
                record_id=user.id,
                record_identifier=f'{user.username} ({user.full_name})',
                old_values=old_values,
                new_values=new_values
            )

            # Audit log - Branch assignment changes
            if old_branch_ids != new_branch_ids:
                branch_names = [b.name for b in Branch.query.filter(Branch.id.in_(new_branch_ids)).all()]
                log_audit(
                    module='user',
                    action='branch_assigned' if len(new_branch_ids) > len(old_branch_ids) else 'branch_removed',
                    record_id=user.id,
                    record_identifier=f'{user.username} ({user.full_name})',
                    old_values={'branch_ids': old_branch_ids},
                    new_values={'branch_ids': new_branch_ids},
                    notes=f'Branches: {", ".join(branch_names) if branch_names else "None"}'
                )

            # Audit log - Book permission changes. Compare effective values:
            # a user with no stored permissions reads as {} which must equal
            # the form's explicit all-False dict, not differ from it.
            old_effective = {k: bool(old_book_permissions.get(k)) for k in book_permissions}
            if old_effective != book_permissions:
                granted = any(book_permissions[k] and not old_effective[k] for k in book_permissions)
                log_audit(
                    module='user',
                    action='permission_granted' if granted else 'permission_revoked',
                    record_id=user.id,
                    record_identifier=f'{user.username} ({user.full_name})',
                    old_values={'permissions': old_effective},
                    new_values={'permissions': book_permissions},
                    notes='Book permissions updated'
                )

            # Audit log - Password change
            if password_changed:
                action = 'password_reset' if current_user.id != user.id else 'password_changed'
                notes = f'Password reset by admin: {current_user.username}' if action == 'password_reset' else 'User changed own password'
                log_audit(
                    module='user',
                    action=action,
                    record_id=user.id,
                    record_identifier=f'{user.username} ({user.full_name})',
                    notes=notes
                )

            # Audit log - Account unlock
            if account_unlocked:
                log_audit(
                    module='user',
                    action='account_unlocked',
                    record_id=user.id,
                    record_identifier=f'{user.username} ({user.full_name})',
                    notes=f'Account manually unlocked by admin: {current_user.username}'
                )

            flash(f'User "{user.username}" updated successfully!', 'success')
            return redirect(url_for('users.list_users'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating user", exc_info=True)
            log_exception(e, severity='ERROR', module='users.update')
            db.session.rollback()
            flash(f'Error updating user: {str(e)}', 'error')

    # Clear password fields on GET request
    if request.method == 'GET':
        form.password.data = ''
        form.confirm_password.data = ''

    return render_template('users/form.html', form=form, user=user)


@users_bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    """Delete user (admin only)."""
    # Only administrators can delete users
    if current_user.role != 'admin':
        flash('Only Administrators can delete users.', 'error')
        return redirect(url_for('users.list_users'))

    user = db.get_or_404(User, id)

    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('users.list_users'))

    # Block deletion if user has NOT-NULL foreign key references
    from app.accounts_payable.models import AccountsPayableAttachment
    attachment_count = AccountsPayableAttachment.query.filter_by(uploaded_by_id=user.id).count()
    if attachment_count > 0:
        flash(f'Cannot delete user "{user.username}": {attachment_count} purchase bill attachment(s) uploaded by this user exist.', 'error')
        return redirect(url_for('users.list_users'))

    # TEMPORARILY DISABLED ERROR HANDLING FOR DEBUGGING - See full stack trace
    # try:
    # Capture values before delete
    old_values = model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])
    user_identifier = f'{user.username} ({user.full_name})'
    user_id = user.id
    username = user.username

    db.session.delete(user)
    db.session.commit()

    # Audit log
    log_delete(
        module='user',
        record_id=user_id,
        record_identifier=user_identifier,
        old_values=old_values
    )

    flash(f'User "{username}" deleted successfully.', 'success')
    # except Exception as e:
    #     from flask import current_app
    #     from app.errors.utils import log_exception
    #     current_app.logger.error(f"Error deleting user", exc_info=True)
    #     log_exception(e, severity='ERROR', module='users.delete')
    #     db.session.rollback()
    #     flash(f'Error deleting user: {str(e)}', 'error')

    return redirect(url_for('users.list_users'))


@users_bp.route('/profile')
@login_required
def profile():
    """View current user profile."""
    return render_template('users/profile.html', user=current_user)


@users_bp.route('/profile/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change current user password."""
    form = ChangePasswordForm()

    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'error')
            return render_template('users/change_password.html', form=form)

        try:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('users.profile'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error changing password", exc_info=True)
            log_exception(e, severity='CRITICAL', module='users.change_password')
            db.session.rollback()
            flash(f'Error changing password: {str(e)}', 'error')

    return render_template('users/change_password.html', form=form)


# ============================================================
# APPROVED EMAILS MANAGEMENT (Admin Only)
# ============================================================

@users_bp.route('/approved-emails')
@login_required
def list_approved_emails():
    """List all approved emails for registration (admin full access; accountant read-only)."""
    if current_user.role not in ('admin', 'accountant'):
        flash('You do not have permission to view this page.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.users.approved_emails import ApprovedEmail

    # Get all approved emails, ordered by pending first, then by date desc
    approved_emails = ApprovedEmail.query.order_by(
        ApprovedEmail.is_used.asc(),
        ApprovedEmail.approved_at.desc()
    ).all()

    pending = [e for e in approved_emails if e.status == 'pending']

    return render_template('users/approved_emails_list.html',
                           approved_emails=approved_emails,
                           pending=pending)


@users_bp.route('/approved-emails/add', methods=['GET', 'POST'])
@login_required
def add_approved_email():
    """Add a new approved email for registration.

    Admin → immediately approved (carries role + branches + permissions).
    Accountant → creates a pending request for admin approval; but when the company
    setting ``accountant_email_self_approval`` is ON, a staff/viewer request is
    approved immediately (an accountant-position request still goes pending).
    """
    if current_user.role not in ('admin', 'accountant'):
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.users.forms import ApprovedEmailForm
    from app.users.approved_emails import ApprovedEmail
    from app.users.utils import get_accessible_branches

    form = ApprovedEmailForm()

    # Scope the branch pool to the approver: admin → all active; accountant → their
    # assigned branches. Setting choices here is the in-scope enforcement — WTForms
    # rejects any submitted branch id that is not an allowed choice.
    allowed_branches = get_accessible_branches(current_user)
    form.branch_ids.choices = [(b.id, b.name) for b in allowed_branches]
    single_branch = allowed_branches[0] if len(allowed_branches) == 1 else None

    # Permission-grid scope: admin may grant any module; an accountant may grant only
    # the modules they themselves hold (subset delegation, same rule as Staff Management).
    from app.users.module_access import all_permission_keys, MODULE_REGISTRY
    if current_user.role == 'admin':
        editable_keys = set(all_permission_keys())
    else:
        from app.staff_management.scope import accountant_permission_keys
        editable_keys = accountant_permission_keys(current_user)
    editable_mods = [m for m in MODULE_REGISTRY if m['key'] in editable_keys]

    if form.validate_on_submit():
        # Resolve the branch assignment. A single-branch approver need not pick —
        # their one branch is auto-assigned; otherwise at least one must be chosen.
        if single_branch is not None:
            selected_ids = [single_branch.id]
        else:
            selected_ids = form.branch_ids.data or []
        if not selected_ids:
            flash('Assign at least one branch for this registration.', 'error')
            return render_template('users/approved_email_form.html', form=form,
                                   single_branch=single_branch, editable_mods=editable_mods)

        branches = Branch.query.filter(Branch.id.in_(selected_ids)).all()
        branch_names = ', '.join(b.name for b in branches)
        position = form.position.data
        position_label = dict(form.position.choices).get(position, position)

        # Permissions to stamp on the approved email — restricted to what the approver
        # may grant (a forged book_* outside editable_keys is dropped server-side).
        book_perms = {k: request.form.get('book_' + k) == '1' for k in editable_keys}

        try:
            if current_user.role == 'admin':
                # Admin direct-add → immediately approved
                approved_email = ApprovedEmail(
                    email=form.email.data.lower(),
                    status='approved',
                    role=position,
                    approved_by_user_id=current_user.id,
                    notes=form.notes.data
                )
                approved_email.branches = branches
                approved_email.set_book_permissions(book_perms)
                db.session.add(approved_email)
                db.session.commit()

                log_audit(
                    module='approved_email',
                    action='create',
                    record_id=approved_email.id,
                    record_identifier=approved_email.email,
                    new_values={'email': approved_email.email, 'role': position,
                                'branch_ids': selected_ids, 'notes': approved_email.notes},
                    notes=f'Email pre-approved for registration as {position_label} ({branch_names})'
                )

                flash(f'Email "{form.email.data}" has been approved for registration '
                      f'as {position_label}.', 'success')
            else:
                from app.users.utils import accountant_self_approval_enabled
                self_approve = (accountant_self_approval_enabled()
                                and position in ('staff', 'viewer'))

                if self_approve:
                    # Company policy lets accountants self-approve staff/viewer registrations.
                    approved_email = ApprovedEmail(
                        email=form.email.data.lower(),
                        status='approved',
                        role=position,
                        approved_by_user_id=current_user.id,
                        reviewed_at=ph_now(),
                        notes=form.notes.data
                    )
                    approved_email.branches = branches
                    approved_email.set_book_permissions(book_perms)
                    db.session.add(approved_email)
                    db.session.commit()

                    # FYI (not an action item) notification to all active admins
                    admins = User.query.filter_by(role='admin', is_active=True).all()
                    for admin in admins:
                        create_notification(
                            user_id=admin.id,
                            title='Email self-approved',
                            message=(f'{current_user.full_name} self-approved '
                                     f'{approved_email.email} as {position_label} ({branch_names})'),
                            category='info',
                            related_type='approved_email',
                            related_id=approved_email.id,
                        )

                    log_audit(
                        module='approved_email',
                        action='create',
                        record_id=approved_email.id,
                        record_identifier=approved_email.email,
                        new_values={'email': approved_email.email, 'role': position,
                                    'branch_ids': selected_ids, 'notes': approved_email.notes},
                        notes=(f'Self-approved by accountant {current_user.username} '
                               f'as {position_label} ({branch_names})')
                    )

                    flash(f'Email "{form.email.data}" has been approved for registration '
                          f'as {position_label}.', 'success')
                else:
                    # Accountant → pending, notify admins (unchanged behavior)
                    approved_email = ApprovedEmail(
                        email=form.email.data.lower(),
                        status='pending',
                        role=position,
                        requested_by_user_id=current_user.id,
                        notes=form.notes.data
                    )
                    approved_email.branches = branches
                    approved_email.set_book_permissions(book_perms)
                    db.session.add(approved_email)
                    db.session.commit()

                    admins = User.query.filter_by(role='admin', is_active=True).all()
                    for admin in admins:
                        create_notification(
                            user_id=admin.id,
                            title='Approved-email request',
                            message=(f'{current_user.full_name} requested approval for '
                                     f'{approved_email.email} as {position_label} ({branch_names})'),
                            category='info',
                            related_type='approved_email',
                            related_id=approved_email.id,
                        )

                    log_audit(
                        module='approved_email',
                        action='request',
                        record_id=approved_email.id,
                        record_identifier=approved_email.email,
                        new_values={'email': approved_email.email, 'role': position,
                                    'branch_ids': selected_ids, 'notes': approved_email.notes},
                        notes=(f'Submitted by {current_user.username} for admin approval '
                               f'as {position_label} ({branch_names})')
                    )

                    flash('Email request submitted for admin approval.', 'success')

            return redirect(url_for('users.list_approved_emails'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error adding approved email", exc_info=True)
            log_exception(e, severity='ERROR', module='users.add_approved_email')
            db.session.rollback()
            flash(f'Error adding approved email: {str(e)}', 'error')

    return render_template('users/approved_email_form.html', form=form,
                           single_branch=single_branch, editable_mods=editable_mods)


@users_bp.route('/approved-emails/<int:id>/approve', methods=['POST'])
@login_required
def approve_approved_email(id):
    """Approve a pending approved-email request (admin only)."""
    if current_user.role != 'admin':
        flash('Only administrators can approve email requests.', 'error')
        return redirect(url_for('users.list_approved_emails'))

    from app.users.approved_emails import ApprovedEmail
    ae = db.get_or_404(ApprovedEmail, id)

    if ae.status != 'pending':
        flash('This request is not pending and cannot be approved.', 'error')
        return redirect(url_for('users.list_approved_emails'))

    ae.approve(current_user.id)

    # Notify the requester (if any)
    if ae.requested_by_user_id:
        create_notification(
            user_id=ae.requested_by_user_id,
            title='Email approval approved',
            message=f'Your request for {ae.email} has been approved.',
            category='success',
            related_type='approved_email',
            related_id=ae.id,
        )

    log_audit(
        module='approved_email',
        action='approve',
        record_id=ae.id,
        record_identifier=ae.email,
        notes=f'Approved by {current_user.username}'
    )

    flash(f'Email "{ae.email}" has been approved for registration.', 'success')
    return redirect(url_for('users.list_approved_emails'))


@users_bp.route('/approved-emails/<int:id>/reject', methods=['POST'])
@login_required
def reject_approved_email(id):
    """Reject a pending approved-email request (admin only)."""
    if current_user.role != 'admin':
        flash('Only administrators can reject email requests.', 'error')
        return redirect(url_for('users.list_approved_emails'))

    from app.users.approved_emails import ApprovedEmail
    from app.users.forms import RejectReasonForm

    ae = db.get_or_404(ApprovedEmail, id)

    if ae.status != 'pending':
        flash('This request is not pending and cannot be rejected.', 'error')
        return redirect(url_for('users.list_approved_emails'))

    reason = request.form.get('reason', '').strip()
    ae.reject(current_user.id, reason)

    # Notify the requester (if any)
    if ae.requested_by_user_id:
        create_notification(
            user_id=ae.requested_by_user_id,
            title='Email approval rejected',
            message=f'Your request for {ae.email} has been rejected.' + (f' Reason: {reason}' if reason else ''),
            category='error',
            related_type='approved_email',
            related_id=ae.id,
        )

    log_audit(
        module='approved_email',
        action='reject',
        record_id=ae.id,
        record_identifier=ae.email,
        notes=f'Rejected by {current_user.username}' + (f': {reason}' if reason else '')
    )

    flash(f'Email "{ae.email}" request has been rejected.', 'info')
    return redirect(url_for('users.list_approved_emails'))


@users_bp.route('/approved-emails/<int:id>/delete', methods=['POST'])
@login_required
def delete_approved_email(id):
    """Delete an approved email (admin only)."""
    if current_user.role != 'admin':
        flash('Only administrators can manage approved emails.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.users.approved_emails import ApprovedEmail

    try:
        approved_email = db.get_or_404(ApprovedEmail, id)

        # Don't allow deleting already used emails
        if approved_email.is_used:
            flash('Cannot delete an approved email that has already been used for registration.', 'error')
            return redirect(url_for('users.list_approved_emails'))

        email_address = approved_email.email
        old_values = {'email': approved_email.email, 'notes': approved_email.notes}
        db.session.delete(approved_email)
        db.session.commit()

        log_audit(
            module='approved_email',
            action='delete',
            record_id=id,
            record_identifier=email_address,
            old_values=old_values,
            notes='Approved email removed before use'
        )

        flash(f'Approved email "{email_address}" has been removed.', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting approved email", exc_info=True)
        log_exception(e, severity='ERROR', module='users.delete_approved_email')
        db.session.rollback()
        flash(f'Error deleting approved email: {str(e)}', 'error')

    return redirect(url_for('users.list_approved_emails'))
