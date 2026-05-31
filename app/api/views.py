"""
API endpoints for AJAX requests
"""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.settings import AppSettings

api_bp = Blueprint('api', __name__)


@api_bp.route('/environment', methods=['GET'])
@login_required
def get_environment():
    """Get current environment setting."""
    env = AppSettings.get_setting('environment', 'dev')
    return jsonify({'environment': env})


@api_bp.route('/environment', methods=['POST'])
@login_required
def set_environment():
    """Set environment setting (admin only)."""
    if current_user.role != 'admin':
        return jsonify({'error': 'Only administrators can change the environment'}), 403

    data = request.get_json()
    env = data.get('environment')

    if env not in ['dev', 'testing', 'live']:
        return jsonify({'error': 'Invalid environment'}), 400

    AppSettings.set_setting('environment', env, current_user.username)
    return jsonify({'environment': env, 'success': True})
