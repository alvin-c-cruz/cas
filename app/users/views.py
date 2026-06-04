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

    from app.branches.models import Branch

    form = LoginForm()

    # Populate branch choices with active branches
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    if not branches:
        flash('No active branches available. Please contact the administrator.', 'error')
        return render_template('users/login.html', form=form, branches=branches)

    form.branch.choices = [(b.id, b.name) for b in branches]

    # If only one branch, auto-select it
    single_branch = len(branches) == 1
    if single_branch and request.method == 'GET':
        form.branch.data = branches[0].id

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        # Get IP address and user agent for audit trail
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')[:500]  # Limit to 500 chars

        if user is None or not user.check_password(form.password.data):
            # Log failed login attempt
            if user:
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
            return render_template('users/login.html', form=form, branches=branches)

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

            flash('Your account has been deactivated. Please contact the administrator.', 'error')
            return render_template('users/login.html', form=form, branches=branches)

        # Successful login
        try:
            # Update last login
            user.last_login = ph_now()

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

        # Store selected branch in session
        from flask import session
        selected_branch_id = form.branch.data
        session['selected_branch_id'] = selected_branch_id

        # Get branch name for welcome message
        selected_branch = Branch.query.get(selected_branch_id)
        branch_name = selected_branch.name if selected_branch else 'Unknown Branch'

        flash(f'Welcome back, {user.full_name}! Logged into {branch_name}.', 'success')

        # Redirect to next page or dashboard
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('dashboard.index'))

    return render_template('users/login.html', form=form, branches=branches)


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
    form = UserForm()

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
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'error')

    return render_template('users/form.html', form=form, user=None)


@users_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    """Edit existing user (admin only)."""
    user = User.query.get_or_404(id)

    # Prevent accountants from editing admin users
    if current_user.role == 'accountant' and user.role == 'admin':
        flash('You cannot edit administrator accounts.', 'error')
        return redirect(url_for('users.list_users'))

    form = UserForm(obj=user)

    if form.validate_on_submit():
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

            # Update password if provided
            password_changed = False
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

            db.session.commit()

            # Audit log
            new_values = model_to_dict(user, ['username', 'email', 'full_name', 'role', 'is_active'])
            notes = 'Password changed' if password_changed else None
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
            db.session.rollback()
            flash(f'Error changing password: {str(e)}', 'error')

    return render_template('users/change_password.html', form=form)
