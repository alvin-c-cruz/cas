"""
Notifications views
"""
from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user
from app import db
from app.notifications.models import Notification
from app.notifications.utils import mark_as_read
from app.utils import ph_now

notifications_bp = Blueprint('notifications', __name__, template_folder='templates')


@notifications_bp.route('/')
@login_required
def list_notifications():
    """List all notifications for current user"""
    # Get filter from query params (default to 'all')
    filter_type = request.args.get('filter', 'all')

    query = Notification.query.filter_by(user_id=current_user.id)

    if filter_type == 'unread':
        query = query.filter_by(is_read=False)
    elif filter_type == 'read':
        query = query.filter_by(is_read=True)

    notifications = query.order_by(Notification.created_at.desc()).all()

    return render_template('notifications/list.html',
                         notifications=notifications,
                         filter_type=filter_type)


@notifications_bp.route('/<int:id>/mark-read', methods=['POST'])
@login_required
def mark_read(id):
    """Mark a notification as read"""
    notification = db.get_or_404(Notification, id)

    # Security check - can only mark own notifications as read
    if notification.user_id != current_user.id:
        return redirect(url_for('notifications.list_notifications'))

    mark_as_read(id)

    return redirect(url_for('notifications.list_notifications'))


@notifications_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    """Mark all notifications as read for current user"""
    notifications = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).all()

    for notification in notifications:
        notification.is_read = True
        notification.read_at = ph_now()

    db.session.commit()

    return redirect(url_for('notifications.list_notifications'))
