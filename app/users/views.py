from urllib.parse import urlparse, urljoin
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from app.users.models import User
from app.users.forms import LoginForm, RegistrationForm, UserForm, ChangePasswordForm
from app.utils import ph_now
from app.audit.utils import log_audit, log_create, log_update, log_delete, model_to_dict


users_bp = Blueprint('users', __name__, template_folder='templates')


def admin_required(f):
    """Decorator to require admin or accountant role for user management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'accountant']:
            flash('You need administrator or accountant privileges to access User Management.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _is_safe_url(target):
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ('http', 'https') and ref.netloc == test.netloc


@users_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        # Check if account is locked (if user exists)
        if user and user.is_account_locked():
            # Log failed login due to account lockout
            log_audit(
                module='auth',
                action='login_failed',
                record_id=user.id,
                record_identifier=user.username,
                notes='Account locked due to multiple failed login attempts'
            )

            from datetime import datetime, timezone, timedelta
            lockout_time = user.account_locked_until
            if lockout_time:
                # Make lockout_time timezone-aware if it's naive (same fix as in models.py)
                if lockout_time.tzinfo is None:
                    PHT = timezone(timedelta(hours=8))
                    lockout_time = lockout_time.replace(tzinfo=PHT)

                minutes_remaining = int((lockout_time - ph_now()).total_seconds() / 60)
                flash(f'Your account is locked due to multiple failed login attempts. Please try again in {minutes_remaining} minutes or contact the administrator.', 'error')
            else:
                flash('Your account is locked. Please contact the administrator.', 'error')
            return render_template('users/login.html', form=form)

        if user is None or not user.check_password(form.password.data):
            # Log failed login attempt
            if user:
                # Increment failed attempts and check if account should be locked
                account_locked = user.increment_failed_attempts(max_attempts=5, lockout_minutes=15)

                # Persist lockout state immediately — do not rely on log_audit's commit
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                # Log failed login with invalid password
                log_audit(
                    module='auth',
                    action='account_locked' if account_locked else 'login_failed',
                    record_id=user.id,
                    record_identifier=user.username,
                    notes='Too many failed attempts - account locked' if account_locked else 'Invalid password'
                )

                if account_locked:
                    flash('Too many failed login attempts. Your account has been locked for 15 minutes.', 'error')
                else:
                    remaining_attempts = 5 - user.failed_login_attempts
                    if remaining_attempts <= 2:
                        flash(f'Invalid username or password. Warning: {remaining_attempts} attempts remaining before account lockout.', 'error')
                    else:
                        flash('Invalid username or password.', 'error')
            else:
                # Username not found - still log but without user_id
                log_audit(
                    module='auth',
                    action='login_failed',
                    record_id=None,
                    record_identifier=form.username.data,
                    notes='Invalid username'
                )

                flash('Invalid username or password.', 'error')

            return render_template('users/login.html', form=form)

        if not user.is_active:
            # Log failed login due to inactive account
            log_audit(
                module='auth',
                action='login_failed',
                record_id=user.id,
                record_identifier=user.username,
                notes='Account inactive'
            )

            # Differentiate between pending approval and deactivated account
            if user.last_login is None:
                # User has never logged in - account is pending approval
                flash('Your account is pending approval. Please wait for an administrator to activate your account.', 'error')
            else:
                # User has logged in before - account was deactivated
                flash('Your account has been deactivated. Please contact the administrator.', 'error')
            return render_template('users/login.html', form=form)

        # Successful login
        try:
            # Update last login
            user.last_login = ph_now()

            # Reset failed login attempts on successful login
            user.reset_failed_attempts()

            # Log successful login
            log_audit(
                module='auth',
                action='login_success',
                record_id=user.id,
                record_identifier=user.username,
                notes=f'Login successful. Remember me: {form.remember_me.data}',
                user_id=user.id  # fires before login_user(); current_user is still anonymous
            )

            db.session.commit()
        except:
            db.session.rollback()

        login_user(user, remember=form.remember_me.data)

        # Get all active branches
        from app.branches.models import Branch
        from flask import session

        active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

        # Filter branches based on user permissions
        # Admins and accountants see all branches
        # Other users see only their assigned branches
        if user.role in ['admin', 'accountant']:
            accessible_branches = active_branches
        else:
            user_branch_ids = {b.id for b in user.branches.all()}
            accessible_branches = [b for b in active_branches if b.id in user_branch_ids]

        if not accessible_branches:
            flash('No branches available. Please contact the administrator.', 'error')
            logout_user()
            return redirect(url_for('users.login'))

        # Auto-assign if only one branch accessible
        if len(accessible_branches) == 1:
            branch = accessible_branches[0]
            session['selected_branch_id'] = branch.id
            log_audit(
                module='auth',
                action='branch_selected',
                record_id=user.id,
                record_identifier=user.username,
                notes=f'Auto-selected branch: {branch.name} (ID: {branch.id}) — single accessible branch'
            )
            flash(f'Welcome back, {user.full_name}!', 'success')

            # Redirect to next page or dashboard (validated to prevent open redirect)
            next_page = request.args.get('next')
            if next_page and _is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('dashboard.index'))

        # Multiple branches - redirect to branch selection
        session['needs_branch_selection'] = True
        flash(f'Welcome back, {user.full_name}! Please select your branch.', 'info')
        return redirect(url_for('users.select_branch'))

    return render_template('users/login.html', form=form)


@users_bp.route('/select-branch', methods=['GET', 'POST'])
@login_required
def select_branch():
    """Branch selection page (for users with access to multiple branches)."""
    from app.branches.models import Branch
    from flask import session

    # Get the 'next' URL parameter (where to redirect after branch selection)
    _raw_next = request.args.get('next') or request.form.get('next')
    next_url = _raw_next if (_raw_next and _is_safe_url(_raw_next)) else url_for('dashboard.index')

    # Get accessible branches for current user
    active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    if current_user.role in ['admin', 'accountant']:
        accessible_branches = active_branches
    elif current_user.branches:
        # Filter user's assigned branches to only show active ones
        user_branch_ids = current_user.get_branch_ids()
        accessible_branches = [b for b in active_branches if b.id in user_branch_ids]
    else:
        accessible_branches = []

    # If only one branch, redirect directly
    if len(accessible_branches) == 1:
        session['selected_branch_id'] = accessible_branches[0].id
        session.pop('needs_branch_selection', None)
        return redirect(next_url)

    # If no branches, error
    if not accessible_branches:
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

        selected_branch = Branch.query.get(branch_id)

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
    from flask import session

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
def register():
    """User registration (public)."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            user = User(
                username=form.username.data,
                email=form.email.data,
                full_name=form.full_name.data,
                role='viewer',  # Default role for self-registration (view-only)
                is_active=False  # New registrations require admin approval
            )
            user.set_password(form.password.data)

            db.session.add(user)
            db.session.commit()

            # Mark the approved email as used
            from app.users.approved_emails import ApprovedEmail
            approved_email = ApprovedEmail.get_approved_email(form.email.data)
            if approved_email:
                approved_email.mark_as_used(user.id)

            # Log successful registration
            log_audit(
                module='user_registration',
                action='registration_success',
                record_id=user.id,
                record_identifier=f'{user.username} ({user.email})',
                notes='User registered successfully, pending admin approval'
            )

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
    """List all users (admin and accountant)."""
    # Accountants cannot see admin users
    if current_user.role == 'accountant':
        users = User.query.filter(User.role != 'admin').order_by(User.created_at.desc()).all()
    else:
        users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users/list.html', users=users)


@users_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    """Create new user (admin only)."""
    from app.branches.models import Branch

    form = UserForm()

    # Populate branch choices for multi-select
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    form.branch_ids.choices = [(b.id, b.name) for b in branches]

    if form.validate_on_submit():
        # Check for duplicate username
        existing_username = User.query.filter_by(username=form.username.data).first()
        if existing_username:
            flash(f'Username "{form.username.data}" already exists. Please use a different username.', 'error')
            return render_template('users/form.html', form=form, user=None)

        # Check for duplicate email
        existing_email = User.query.filter_by(email=form.email.data).first()
        if existing_email:
            flash(f'Email "{form.email.data}" already exists. Please use a different email.', 'error')
            return render_template('users/form.html', form=form, user=None)

        try:
            user = User(
                username=form.username.data,
                email=form.email.data,
                full_name=form.full_name.data,
                role=form.role.data,
                is_active=form.is_active.data
            )

            # Set password if provided
            if form.password.data:
                user.set_password(form.password.data)
            else:
                flash('Password is required for new users.', 'error')
                return render_template('users/form.html', form=form, user=None)

            # Set book permissions from form
            book_permissions = {
                'journal_entries': request.form.get('book_journal_entries') == '1',
                'accounts_receivable': request.form.get('book_accounts_receivable') == '1',
                'collections': request.form.get('book_collections') == '1',
                'accounts_payable': request.form.get('book_accounts_payable') == '1',
                'payments': request.form.get('book_payments') == '1'
            }
            user.set_book_permissions(book_permissions)

            # Add user first to get an ID
            db.session.add(user)
            db.session.flush()  # Flush to get the user ID before adding branches

            # Assign branches
            if form.branch_ids.data:
                selected_branches = Branch.query.filter(Branch.id.in_(form.branch_ids.data)).all()
                user.set_branches(selected_branches)

            db.session.commit()

            # Audit log
            log_create(
                module='user',
                record_id=user.id,
                record_identifier=f'{user.username} ({user.full_name})',
                new_values=model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])
            )

            flash(f'User "{user.username}" created successfully!', 'success')
            return redirect(url_for('users.list_users'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating user", exc_info=True)
            log_exception(e, severity='ERROR', module='users.create')
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'error')

    return render_template('users/form.html', form=form, user=None)


@users_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    """Edit existing user (admin only)."""
    from app.branches.models import Branch

    user = User.query.get_or_404(id)

    # Prevent accountants from editing admin users
    if current_user.role == 'accountant' and user.role == 'admin':
        flash('You cannot edit administrator accounts.', 'error')
        return redirect(url_for('users.list_users'))

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

            # Update book permissions from form
            book_permissions = {
                'journal_entries': request.form.get('book_journal_entries') == '1',
                'accounts_receivable': request.form.get('book_accounts_receivable') == '1',
                'collections': request.form.get('book_collections') == '1',
                'accounts_payable': request.form.get('book_accounts_payable') == '1',
                'payments': request.form.get('book_payments') == '1'
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

    user = User.query.get_or_404(id)

    # Prevent deleting yourself
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('users.list_users'))

    # Block deletion if user has NOT-NULL foreign key references
    from app.purchase_bills.models import PurchaseBillAttachment
    attachment_count = PurchaseBillAttachment.query.filter_by(uploaded_by_id=user.id).count()
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
@admin_required
def list_approved_emails():
    """List all approved emails for registration (admin only)."""
    if current_user.role != 'admin':
        flash('Only administrators can manage approved emails.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.users.approved_emails import ApprovedEmail

    # Get all approved emails, ordered by status (available first, then used)
    approved_emails = ApprovedEmail.query.order_by(
        ApprovedEmail.is_used.asc(),
        ApprovedEmail.approved_at.desc()
    ).all()

    return render_template('users/approved_emails_list.html', approved_emails=approved_emails)


@users_bp.route('/approved-emails/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_approved_email():
    """Add a new approved email for registration (admin only)."""
    if current_user.role != 'admin':
        flash('Only administrators can manage approved emails.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.users.forms import ApprovedEmailForm
    from app.users.approved_emails import ApprovedEmail

    form = ApprovedEmailForm()

    if form.validate_on_submit():
        try:
            approved_email = ApprovedEmail(
                email=form.email.data.lower(),
                approved_by_user_id=current_user.id,
                notes=form.notes.data
            )

            db.session.add(approved_email)
            db.session.commit()

            log_audit(
                module='approved_email',
                action='create',
                record_id=approved_email.id,
                record_identifier=approved_email.email,
                new_values={'email': approved_email.email, 'notes': approved_email.notes},
                notes='Email pre-approved for registration'
            )

            flash(f'Email "{form.email.data}" has been approved for registration.', 'success')
            return redirect(url_for('users.list_approved_emails'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error adding approved email", exc_info=True)
            log_exception(e, severity='ERROR', module='users.add_approved_email')
            db.session.rollback()
            flash(f'Error adding approved email: {str(e)}', 'error')

    return render_template('users/approved_email_form.html', form=form)


@users_bp.route('/approved-emails/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_approved_email(id):
    """Delete an approved email (admin only)."""
    if current_user.role != 'admin':
        flash('Only administrators can manage approved emails.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.users.approved_emails import ApprovedEmail

    try:
        approved_email = ApprovedEmail.query.get_or_404(id)

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
