from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.users.models import User, LoginHistory
from app.users.forms import LoginForm, RegistrationForm, UserForm, ChangePasswordForm
from app.utils import ph_now
from app.audit.utils import log_create, log_update, log_delete, model_to_dict
from functools import wraps


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


@users_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        # Get IP address and user agent for audit trail
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')[:500]  # Limit to 500 chars

        # Check if account is locked (if user exists)
        if user and user.is_account_locked():
            # Log failed login due to account lockout
            login_record = LoginHistory(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                login_time=ph_now(),
                ip_address=ip_address,
                user_agent=user_agent,
                status='failed',
                failure_reason='Account locked due to multiple failed login attempts'
            )
            try:
                db.session.add(login_record)
                db.session.commit()
            except:
                db.session.rollback()

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

                login_record = LoginHistory(
                    user_id=user.id,
                    username=user.username,
                    full_name=user.full_name,
                    login_time=ph_now(),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status='failed',
                    failure_reason='Invalid password'
                )

                try:
                    db.session.add(login_record)
                    db.session.commit()
                except:
                    db.session.rollback()

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
                login_record = LoginHistory(
                    user_id=0,  # Placeholder for non-existent user
                    username=form.username.data,
                    full_name='Unknown',
                    login_time=ph_now(),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status='failed',
                    failure_reason='Invalid username'
                )
                try:
                    db.session.add(login_record)
                    db.session.commit()
                except:
                    db.session.rollback()

                flash('Invalid username or password.', 'error')

            return render_template('users/login.html', form=form)

        if not user.is_active:
            # Log failed login due to inactive account
            login_record = LoginHistory(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                login_time=ph_now(),
                ip_address=ip_address,
                user_agent=user_agent,
                status='failed',
                failure_reason='Account inactive'
            )
            try:
                db.session.add(login_record)
                db.session.commit()
            except:
                db.session.rollback()

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
            login_record = LoginHistory(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                login_time=ph_now(),
                ip_address=ip_address,
                user_agent=user_agent,
                status='success',
                failure_reason=None
            )
            db.session.add(login_record)
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
        # Other users see only their assigned branch
        if user.role in ['admin', 'accountant']:
            accessible_branches = active_branches
        elif user.branch_id:
            accessible_branches = [b for b in active_branches if b.id == user.branch_id]
        else:
            accessible_branches = []

        if not accessible_branches:
            flash('No branches available. Please contact the administrator.', 'error')
            logout_user()
            return redirect(url_for('users.login'))

        # Auto-assign if only one branch accessible
        if len(accessible_branches) == 1:
            session['selected_branch_id'] = accessible_branches[0].id
            flash(f'Welcome back, {user.full_name}!', 'success')

            # Redirect to next page or dashboard
            next_page = request.args.get('next')
            if next_page:
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

    # Get accessible branches for current user
    active_branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    if current_user.role in ['admin', 'accountant']:
        accessible_branches = active_branches
    elif current_user.branch_id:
        accessible_branches = [b for b in active_branches if b.id == current_user.branch_id]
    else:
        accessible_branches = []

    # If only one branch, redirect directly
    if len(accessible_branches) == 1:
        session['selected_branch_id'] = accessible_branches[0].id
        session.pop('needs_branch_selection', None)
        return redirect(url_for('dashboard.index'))

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
            return render_template('users/select_branch.html', branches=accessible_branches)

        # Set selected branch
        session['selected_branch_id'] = branch_id
        session.pop('needs_branch_selection', None)

        selected_branch = Branch.query.get(branch_id)
        flash(f'You are now working in: {selected_branch.name}', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('users/select_branch.html', branches=accessible_branches)


@users_bp.route('/login-history')
@login_required
@admin_required
def login_history():
    """View login history (admin and accountant only)."""
    # Get all login history, most recent first
    history = LoginHistory.query.order_by(LoginHistory.login_time.desc()).all()
    return render_template('users/login_history.html', history=history)


@users_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    from flask import session
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

    # Populate branch choices
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    form.branch_id.choices = [(0, '-- No Branch --')] + [(b.id, b.name) for b in branches]

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
                is_active=form.is_active.data,
                branch_id=form.branch_id.data if form.branch_id.data != 0 else None
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

            db.session.add(user)
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

    # Populate branch choices
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    form.branch_id.choices = [(0, '-- No Branch --')] + [(b.id, b.name) for b in branches]

    if form.validate_on_submit():
        # CRITICAL: Prevent admins from deactivating their own account
        if user.id == current_user.id and not form.is_active.data:
            flash('You cannot deactivate your own account.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # CRITICAL: Prevent admins from changing their own role
        if user.id == current_user.id and user.role != form.role.data:
            flash('You cannot change your own role.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # Check for duplicate username (excluding current user)
        existing_username = User.query.filter(User.username == form.username.data, User.id != id).first()
        if existing_username:
            flash(f'Username "{form.username.data}" already exists. Please use a different username.', 'error')
            return render_template('users/form.html', form=form, user=user)

        # Check for duplicate email (excluding current user)
        existing_email = User.query.filter(User.email == form.email.data, User.id != id).first()
        if existing_email:
            flash(f'Email "{form.email.data}" already exists. Please use a different email.', 'error')
            return render_template('users/form.html', form=form, user=user)

        try:
            # Capture old values before update
            old_values = model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])

            user.username = form.username.data
            user.email = form.email.data
            user.full_name = form.full_name.data
            user.role = form.role.data
            user.is_active = form.is_active.data
            user.branch_id = form.branch_id.data if form.branch_id.data != 0 else None

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

            # Audit log
            new_values = model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])
            notes = []
            if password_changed:
                notes.append('Password changed')
            if account_unlocked:
                notes.append('Account unlocked')
            notes = '; '.join(notes) if notes else None
            log_update(
                module='user',
                record_id=user.id,
                record_identifier=f'{user.username} ({user.full_name})',
                old_values=old_values,
                new_values=new_values,
                notes=notes
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

    try:
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
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting user", exc_info=True)
        log_exception(e, severity='ERROR', module='users.delete')
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'error')

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
