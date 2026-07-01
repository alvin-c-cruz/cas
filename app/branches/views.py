"""
Branch management views (Admin only)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.branches.models import Branch
from app.branches.forms import BranchForm
from app.users.models import User
from app.audit.utils import log_create, log_update, log_delete, log_audit, model_to_dict
from functools import wraps

branches_bp = Blueprint('branches', __name__, template_folder='templates')


def admin_only(f):
    """Decorator to require admin role for branch management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Only administrators can access Branch Management.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@branches_bp.route('/branches')
@login_required
@admin_only
def list_branches():
    """List all branches."""
    branches = Branch.query.order_by(Branch.code).all()
    return render_template('branches/list.html', branches=branches)


@branches_bp.route('/branches/create', methods=['GET', 'POST'])
@login_required
@admin_only
def create():
    """Create new branch."""
    form = BranchForm()

    if form.validate_on_submit():
        # Check for duplicate code
        existing = Branch.query.filter_by(code=form.code.data).first()
        if existing:
            flash(f'Branch code "{form.code.data}" already exists.', 'error')
            return render_template('branches/form.html', form=form, branch=None)

        try:
            branch = Branch(
                code=form.code.data,
                name=form.name.data,
                address=form.address.data,
                phone=form.phone.data,
                email=form.email.data,
                is_active=form.is_active.data if form.is_active.data is not None else True
            )
            db.session.add(branch)
            db.session.commit()

            # Audit log for branch creation
            log_create(
                module='branch',
                record_id=branch.id,
                record_identifier=f'{branch.code} - {branch.name}',
                new_values=model_to_dict(branch, ['code', 'name', 'address', 'phone', 'email', 'is_active'])
            )

            flash(f'Branch "{branch.name}" created successfully!', 'success')
            return redirect(url_for('branches.list_branches'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating branch", exc_info=True)
            log_exception(e, severity='ERROR', module='branches.create')
            db.session.rollback()
            flash('An error occurred while creating the branch. Please try again.', 'error')

    # Set default for is_active checkbox
    if request.method == 'GET':
        form.is_active.data = True

    return render_template('branches/form.html', form=form, branch=None)


@branches_bp.route('/branches/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_only
def edit(id):
    """Edit branch."""
    branch = db.get_or_404(Branch, id)
    form = BranchForm(obj=branch)

    if form.validate_on_submit():
        # Check for duplicate code (excluding current branch)
        existing = Branch.query.filter(Branch.code == form.code.data, Branch.id != id).first()
        if existing:
            flash(f'Branch code "{form.code.data}" already exists.', 'error')
            return render_template('branches/form.html', form=form, branch=branch)

        try:
            # Capture old values before update
            old_values = model_to_dict(branch, ['code', 'name', 'address', 'phone', 'email', 'is_active'])

            # Update branch
            branch.code = form.code.data
            branch.name = form.name.data
            branch.address = form.address.data
            branch.phone = form.phone.data
            branch.email = form.email.data
            branch.is_active = form.is_active.data
            db.session.commit()

            # Audit log for branch update
            new_values = model_to_dict(branch, ['code', 'name', 'address', 'phone', 'email', 'is_active'])
            log_update(
                module='branch',
                record_id=branch.id,
                record_identifier=f'{branch.code} - {branch.name}',
                old_values=old_values,
                new_values=new_values
            )

            flash(f'Branch "{branch.name}" updated successfully!', 'success')
            return redirect(url_for('branches.list_branches'))
        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error updating branch", exc_info=True)
            log_exception(e, severity='ERROR', module='branches.update')
            db.session.rollback()
            flash('An error occurred while updating the branch. Please try again.', 'error')

    return render_template('branches/form.html', form=form, branch=branch)


@branches_bp.route('/branches/<int:id>/delete', methods=['POST'])
@login_required
@admin_only
def delete(id):
    """Delete branch."""
    branch = db.get_or_404(Branch, id)

    # Prevent deletion of main branch
    if branch.code == 'MAIN':
        flash('The Main Branch cannot be deleted.', 'error')
        return redirect(url_for('branches.list_branches'))

    # Check if branch has assigned users
    if branch.users.count() > 0:
        flash(f'Cannot delete branch "{branch.name}" because it has {branch.users.count()} assigned user(s). Please reassign users first.', 'error')
        return redirect(url_for('branches.list_branches'))

    # TEMPORARILY DISABLED ERROR HANDLING FOR DEBUGGING - See full stack trace
    # try:
    branch_name = branch.name

    # Capture branch data before deletion
    old_values = model_to_dict(branch, ['code', 'name', 'address', 'phone', 'email', 'is_active'])
    branch_id = branch.id
    branch_identifier = f'{branch.code} - {branch.name}'

    db.session.delete(branch)
    db.session.commit()

    # Audit log for branch deletion
    log_delete(
        module='branch',
        record_id=branch_id,
        record_identifier=branch_identifier,
        old_values=old_values
    )

    flash(f'Branch "{branch_name}" deleted successfully!', 'success')
    # except Exception as e:
    #     from flask import current_app
    #     from app.errors.utils import log_exception
    #     current_app.logger.error(f"Error deleting branch", exc_info=True)
    #     log_exception(e, severity='ERROR', module='branches.delete')
    #     db.session.rollback()
    #     flash(f'Error deleting branch: {str(e)}', 'error')

    return redirect(url_for('branches.list_branches'))


@branches_bp.route('/branches/<int:id>/users')
@login_required
@admin_only
def branch_users(id):
    """View and manage users assigned to a branch."""
    branch = db.get_or_404(Branch, id)

    # Get users assigned to this branch
    assigned_users = branch.users.all()

    # Users that can be assigned: non-admins (admins automatically have access
    # to all branches) not already assigned to THIS branch. Users may belong to
    # several branches, so assignment elsewhere does not exclude them here.
    assigned_ids = [u.id for u in assigned_users]
    available_users = User.query.filter(
        User.role.in_(['accountant', 'staff', 'viewer']),
        User.is_active == True,
        ~User.id.in_(assigned_ids)
    ).order_by(User.full_name).all()

    return render_template('branches/users.html', branch=branch, assigned_users=assigned_users, available_users=available_users)


@branches_bp.route('/branches/<int:id>/assign-user/<int:user_id>', methods=['POST'])
@login_required
@admin_only
def assign_user(id, user_id):
    """Assign a user to a branch."""
    branch = db.get_or_404(Branch, id)
    user = db.get_or_404(User, user_id)

    # Admins and Chief Accountants automatically have access to all branches and cannot be assigned
    if user.has_full_access:
        flash('This user automatically has access to all branches and cannot be assigned.', 'error')
        return redirect(url_for('branches.branch_users', id=id))

    try:
        old_branch_ids = user.get_branch_ids()
        user.add_branch(branch)
        db.session.commit()

        # Audit log for user assignment
        log_audit(
            module='branch',
            action='assign_user',
            record_id=branch.id,
            record_identifier=f'{branch.code} - {branch.name}',
            old_values={'user_id': user.id, 'branch_ids': old_branch_ids},
            new_values={'user_id': user.id, 'user_name': user.full_name,
                        'branch_ids': user.get_branch_ids()},
            notes=f'Assigned user: {user.full_name}'
        )

        flash(f'{user.full_name} assigned to branch "{branch.name}" successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error assigning user to branch", exc_info=True)
        log_exception(e, severity='ERROR', module='branches.assign_user')
        db.session.rollback()
        flash('An error occurred while assigning the user. Please try again.', 'error')

    return redirect(url_for('branches.branch_users', id=id))


@branches_bp.route('/branches/<int:id>/unassign-user/<int:user_id>', methods=['POST'])
@login_required
@admin_only
def unassign_user(id, user_id):
    """Unassign a user from a branch."""
    branch = db.get_or_404(Branch, id)
    user = db.get_or_404(User, user_id)

    try:
        old_branch_ids = user.get_branch_ids()
        user.remove_branch(branch)
        db.session.commit()

        # Audit log for user unassignment
        log_audit(
            module='branch',
            action='unassign_user',
            record_id=branch.id,
            record_identifier=f'{branch.code} - {branch.name}',
            old_values={'user_id': user.id, 'user_name': user.full_name,
                        'branch_ids': old_branch_ids},
            new_values={'user_id': user.id, 'branch_ids': user.get_branch_ids()},
            notes=f'Unassigned user: {user.full_name}'
        )

        flash(f'{user.full_name} unassigned from branch "{branch.name}" successfully!', 'success')
        if not user.get_branch_ids():
            flash(f'{user.full_name} now has no branch assignments and cannot log in until reassigned.', 'warning')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error unassigning user from branch", exc_info=True)
        log_exception(e, severity='ERROR', module='branches.unassign_user')
        db.session.rollback()
        flash('An error occurred while unassigning the user. Please try again.', 'error')

    return redirect(url_for('branches.branch_users', id=id))
