from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.users.models import User
from app.users.utils import get_accessible_branches
from app.users.module_access import MODULE_REGISTRY, all_permission_keys
from app.audit.utils import log_audit, log_update, model_to_dict
from app.branches.models import Branch
from app.staff_management.forms import StaffEditForm
from app.staff_management.scope import (
    manageable_users, assert_in_scope, merge_branches, merge_permissions,
    accountant_permission_keys,
)

staff_management_bp = Blueprint('staff_management', __name__,
                                template_folder='templates')


def accountant_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('accountant', 'chief_accountant'):
            flash('Staff Management is for accountants and chief accountants.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


@staff_management_bp.route('/staff-management')
@login_required
@accountant_required
def list_staff():
    users = manageable_users(current_user)
    return render_template('staff_management/list.html', users=users)


@staff_management_bp.route('/staff-management/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_required
def edit_staff(id):
    target = db.get_or_404(User, id)
    assert_in_scope(current_user, target)

    own_branches = get_accessible_branches(current_user)
    own_keys = accountant_permission_keys(current_user)
    # registry entries the accountant may toggle (their own held keys, non-optional)
    editable_mods = [m for m in MODULE_REGISTRY
                     if not m.get('optional') and m['key'] in own_keys]

    form = StaffEditForm(obj=target)
    form.branch_ids.choices = [(b.id, b.name) for b in own_branches]
    if request.method == 'GET':
        form.branch_ids.data = [b.id for b in own_branches if b.id in target.get_branch_ids()]

    if form.validate_on_submit():
        old_values = model_to_dict(target, ['username', 'role', 'is_active'])
        old_perms = target.get_book_permissions()
        old_branch_ids = set(target.get_branch_ids())

        target.role = form.role.data
        target.is_active = form.is_active.data

        final_branches = merge_branches(current_user, target, form.branch_ids.data)
        if not final_branches:
            flash('Assign at least one branch.', 'error')
            return render_template('staff_management/edit.html', form=form, target=target,
                                   editable_mods=editable_mods)
        target.set_branches(final_branches)

        submitted_keys = [k for k in all_permission_keys() if request.form.get('book_' + k) == '1']
        target.set_book_permissions(merge_permissions(current_user, target, submitted_keys))

        db.session.commit()

        log_update(module='user', record_id=target.id,
                   record_identifier=f'{target.username} ({target.full_name})',
                   old_values=old_values,
                   new_values=model_to_dict(target, ['username', 'role', 'is_active']))

        new_branch_ids = set(b.id for b in final_branches)
        if old_branch_ids != new_branch_ids:
            added = new_branch_ids - old_branch_ids
            removed = old_branch_ids - new_branch_ids
            added_names = [b.name for b in Branch.query.filter(Branch.id.in_(added)).all()] if added else []
            removed_names = [b.name for b in Branch.query.filter(Branch.id.in_(removed)).all()] if removed else []
            action = 'branch_changed' if added and removed else ('branch_assigned' if added else 'branch_removed')
            notes_parts = [f'Updated by accountant {current_user.username}']
            if added_names:
                notes_parts.append(f'Added: {", ".join(added_names)}')
            if removed_names:
                notes_parts.append(f'Removed: {", ".join(removed_names)}')
            log_audit(module='user', action=action,
                      record_id=target.id,
                      record_identifier=f'{target.username} ({target.full_name})',
                      old_values={'branch_ids': sorted(old_branch_ids)},
                      new_values={'branch_ids': sorted(new_branch_ids)},
                      notes='; '.join(notes_parts))

        new_perms = target.get_book_permissions()
        if old_perms != new_perms:
            perm_added = any(new_perms.get(k) and not old_perms.get(k) for k in new_perms)
            perm_removed = any(old_perms.get(k) and not new_perms.get(k) for k in old_perms)
            perm_action = ('permission_changed' if perm_added and perm_removed
                           else ('permission_granted' if perm_added else 'permission_revoked'))
            log_audit(module='user', action=perm_action,
                      record_id=target.id,
                      record_identifier=f'{target.username} ({target.full_name})',
                      old_values={'permissions': old_perms},
                      new_values={'permissions': new_perms},
                      notes=f'Updated by accountant {current_user.username}')

        flash(f'{target.username} has been updated.', 'success')
        return redirect(url_for('staff_management.list_staff'))

    return render_template('staff_management/edit.html', form=form, target=target,
                           editable_mods=editable_mods)


@staff_management_bp.route('/staff-management/<int:id>/toggle-active', methods=['POST'])
@login_required
@accountant_required
def toggle_active(id):
    target = db.get_or_404(User, id)
    assert_in_scope(current_user, target)
    target.is_active = not target.is_active
    db.session.commit()
    log_audit(module='user', action='status_changed', record_id=target.id,
              record_identifier=f'{target.username} ({target.full_name})',
              notes=f'Active set to {target.is_active} by accountant {current_user.username}')
    flash(f'{target.username} is now {"active" if target.is_active else "inactive"}.', 'success')
    return redirect(url_for('staff_management.list_staff'))
