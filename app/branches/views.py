"""
Branch management views (Admin only)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.branches.models import Branch
from app.branches.forms import BranchForm
from app.users.models import User
from functools import wraps

branches_bp = Blueprint('branches', __name__, template_folder='templates')


def admin_only(f):
    """Decorator to require admin role for branch management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
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
            flash(f'Branch "{branch.name}" created successfully!', 'success')
            return redirect(url_for('branches.list_branches'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating branch: {str(e)}', 'error')

    # Set default for is_active checkbox
    if request.method == 'GET':
        form.is_active.data = True

    return render_template('branches/form.html', form=form, branch=None)


@branches_bp.route('/branches/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_only
def edit(id):
    """Edit branch."""
    branch = Branch.query.get_or_404(id)
    form = BranchForm(obj=branch)

    if form.validate_on_submit():
        # Check for duplicate code (excluding current branch)
        existing = Branch.query.filter(Branch.code == form.code.data, Branch.id != id).first()
        if existing:
            flash(f'Branch code "{form.code.data}" already exists.', 'error')
            return render_template('branches/form.html', form=form, branch=branch)

        try:
            branch.code = form.code.data
            branch.name = form.name.data
            branch.address = form.address.data
            branch.phone = form.phone.data
            branch.email = form.email.data
            branch.is_active = form.is_active.data
            db.session.commit()
            flash(f'Branch "{branch.name}" updated successfully!', 'success')
            return redirect(url_for('branches.list_branches'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating branch: {str(e)}', 'error')

    return render_template('branches/form.html', form=form, branch=branch)


@branches_bp.route('/branches/<int:id>/delete', methods=['POST'])
@login_required
@admin_only
def delete(id):
    """Delete branch."""
    branch = Branch.query.get_or_404(id)

    # Prevent deletion of main branch
    if branch.code == 'MAIN':
        flash('The Main Branch cannot be deleted.', 'error')
        return redirect(url_for('branches.list_branches'))

    # Check if branch has assigned users
    if branch.users.count() > 0:
        flash(f'Cannot delete branch "{branch.name}" because it has {branch.users.count()} assigned user(s). Please reassign users first.', 'error')
        return redirect(url_for('branches.list_branches'))

    try:
        branch_name = branch.name
        db.session.delete(branch)
        db.session.commit()
        flash(f'Branch "{branch_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting branch: {str(e)}', 'error')

    return redirect(url_for('branches.list_branches'))


@branches_bp.route('/branches/<int:id>/users')
@login_required
@admin_only
def branch_users(id):
    """View and manage users assigned to a branch."""
    branch = Branch.query.get_or_404(id)

    # Get users assigned to this branch
    assigned_users = branch.users.all()

    # Get users that can be assigned (accountant and staff only, not yet assigned)
    available_users = User.query.filter(
        User.role.in_(['accountant', 'staff']),
        User.branch_id == None
    ).order_by(User.full_name).all()

    return render_template('branches/users.html', branch=branch, assigned_users=assigned_users, available_users=available_users)


@branches_bp.route('/branches/<int:id>/assign-user/<int:user_id>', methods=['POST'])
@login_required
@admin_only
def assign_user(id, user_id):
    """Assign a user to a branch."""
    branch = Branch.query.get_or_404(id)
    user = User.query.get_or_404(user_id)

    # Only accountant and staff can be assigned to branches
    if user.role not in ['accountant', 'staff']:
        flash(f'Only Accountants and Staff can be assigned to branches.', 'error')
        return redirect(url_for('branches.branch_users', id=id))

    try:
        user.branch_id = branch.id
        db.session.commit()
        flash(f'{user.full_name} assigned to branch "{branch.name}" successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error assigning user: {str(e)}', 'error')

    return redirect(url_for('branches.branch_users', id=id))


@branches_bp.route('/branches/<int:id>/unassign-user/<int:user_id>', methods=['POST'])
@login_required
@admin_only
def unassign_user(id, user_id):
    """Unassign a user from a branch."""
    branch = Branch.query.get_or_404(id)
    user = User.query.get_or_404(user_id)

    try:
        user.branch_id = None
        db.session.commit()
        flash(f'{user.full_name} unassigned from branch "{branch.name}" successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error unassigning user: {str(e)}', 'error')

    return redirect(url_for('branches.branch_users', id=id))
