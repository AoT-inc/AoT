# coding=utf-8
"""
Tab Management Routes
Provides REST API endpoints for tab operations across all pages.
"""
import logging
import flask_login
from flask import Blueprint, request, jsonify, url_for, redirect
from aot.services.tab_service import TabService
from aot.aot_flask.utils import utils_general
from aot.aot_flask.routes_static import inject_variables

logger = logging.getLogger('aot.aot_flask.routes_tab')

blueprint = Blueprint('routes_tab',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.route('/tab/create', methods=['POST'])
@flask_login.login_required
def create_tab():
    """
    Create a new tab for a page type.

    POST body (JSON):
        page_type: str - Type of page ('dashboard', 'input', 'output', 'function')
        name: str (optional) - Custom name for the tab

    Returns:
        JSON: {
            'success': bool,
            'message': str,
            'tab_id': str,
            'tab_name': str,
            'position': int,
            'redirect_url': str
        }
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({
            'success': False,
            'message': 'Permission denied'
        }), 403

    try:
        data = request.get_json()
        logger.info(f"[create_tab] Received request data: {data}")
        
        page_type = data.get('page_type')
        name = data.get('name')

        if not page_type:
            return jsonify({
                'success': False,
                'message': 'page_type is required'
            }), 400

        if page_type not in ['dashboard', 'input', 'output', 'function']:
            return jsonify({
                'success': False,
                'message': f'Invalid page_type: {page_type}'
            }), 400

        logger.info(f"[create_tab] Creating new tab for page_type={page_type}, name={name}")
        
        # Create tab using service
        new_tab = TabService.create_tab(page_type, name)

        if not new_tab:
            return jsonify({
                'success': False,
                'message': 'Failed to create tab'
            }), 500

        logger.info(f"[create_tab] Created tab: {new_tab.name} (id={new_tab.unique_id})")
        
        # Determine redirect URL
        endpoint_map = {
            'dashboard': 'routes_dashboard.page_dashboard',
            'input': 'routes_input.page_input',
            'output': 'routes_output.page_output',
            'function': 'routes_function.page_function'
        }

        # Dashboard uses dashboard_id parameter, others use tab_id
        if page_type == 'dashboard':
            redirect_url = url_for(
                endpoint_map.get(page_type, 'routes_general.home'),
                dashboard_id=new_tab.unique_id
            )
        else:
            redirect_url = url_for(
                endpoint_map.get(page_type, 'routes_general.home'),
                tab_id=new_tab.unique_id
            )

        logger.info(f"[create_tab] Redirect URL: {redirect_url}")
        
        return jsonify({
            'success': True,
            'message': 'Tab created successfully',
            'tab_id': new_tab.unique_id,
            'tab_name': new_tab.name,
            'position': new_tab.position,
            'redirect_url': redirect_url
        }), 200

    except Exception as e:
        logger.error(f"Error creating tab: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'Error creating tab: {str(e)}'
        }), 500


@blueprint.route('/tab/rename', methods=['POST'])
@flask_login.login_required
def rename_tab():
    """
    Rename an existing tab.

    POST body (JSON):
        tab_id: str - Tab unique_id
        name: str - New name for the tab

    Returns:
        JSON: {
            'success': bool,
            'message': str
        }
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({
            'success': False,
            'message': 'Permission denied'
        }), 403

    try:
        data = request.get_json()
        tab_id = data.get('tab_id')
        new_name = data.get('name')

        if not tab_id or not new_name:
            return jsonify({
                'success': False,
                'message': 'tab_id and name are required'
            }), 400

        if not new_name.strip():
            return jsonify({
                'success': False,
                'message': 'Tab name cannot be empty'
            }), 400

        success = TabService.rename_tab(tab_id, new_name)

        if success:
            return jsonify({
                'success': True,
                'message': 'Tab renamed successfully'
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to rename tab'
            }), 500

    except Exception as e:
        logger.error(f"Error renaming tab: {e}")
        return jsonify({
            'success': False,
            'message': f'Error renaming tab: {str(e)}'
        }), 500


@blueprint.route('/tab/duplicate', methods=['POST'])
@flask_login.login_required
def duplicate_tab():
    """
    Duplicate a tab and all its entries.

    POST body (JSON):
        tab_id: str - Source tab unique_id

    Returns:
        JSON: {
            'success': bool,
            'message': str,
            'new_tab_id': str,
            'new_tab_name': str,
            'redirect_url': str
        }
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({
            'success': False,
            'message': 'Permission denied'
        }), 403

    try:
        data = request.get_json()
        tab_id = data.get('tab_id')

        if not tab_id:
            return jsonify({
                'success': False,
                'message': 'tab_id is required'
            }), 400

        # Get source tab to determine page type
        source_tab = TabService.get_tab_by_id(tab_id)
        if not source_tab:
            return jsonify({
                'success': False,
                'message': 'Source tab not found'
            }), 404

        # Duplicate tab
        new_tab = TabService.duplicate_tab(tab_id)

        if not new_tab:
            return jsonify({
                'success': False,
                'message': 'Failed to duplicate tab'
            }), 500

        # Determine redirect URL
        endpoint_map = {
            'dashboard': 'routes_dashboard.page_dashboard',
            'input': 'routes_input.page_input',
            'output': 'routes_output.page_output',
            'function': 'routes_function.page_function'
        }

        # Dashboard uses dashboard_id parameter, others use tab_id
        if new_tab.page_type == 'dashboard':
            redirect_url = url_for(
                endpoint_map.get(new_tab.page_type, 'routes_general.home'),
                dashboard_id=new_tab.unique_id
            )
        else:
            redirect_url = url_for(
                endpoint_map.get(new_tab.page_type, 'routes_general.home'),
                tab_id=new_tab.unique_id
            )

        return jsonify({
            'success': True,
            'message': 'Tab duplicated successfully',
            'new_tab_id': new_tab.unique_id,
            'new_tab_name': new_tab.name,
            'redirect_url': redirect_url
        }), 200

    except Exception as e:
        logger.error(f"Error duplicating tab: {e}")
        return jsonify({
            'success': False,
            'message': f'Error duplicating tab: {str(e)}'
        }), 500


@blueprint.route('/tab/<tab_id>', methods=['DELETE'])
@flask_login.login_required
def delete_tab(tab_id):
    """
    Delete a tab and its associated entries.

    Args:
        tab_id: Tab unique_id (URL parameter)

    Returns:
        JSON: {
            'success': bool,
            'message': str,
            'redirect_tab_id': str,
            'redirect_url': str
        }
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({
            'success': False,
            'message': 'Permission denied'
        }), 403

    try:
        # Get tab to determine page type before deletion
        tab = TabService.get_tab_by_id(tab_id)
        page_type = tab.page_type if tab else None

        # Delete tab
        result = TabService.delete_tab(tab_id)

        if result['success'] and result['redirect_tab_id']:
            # Determine redirect URL
            endpoint_map = {
                'dashboard': 'routes_dashboard.page_dashboard',
                'input': 'routes_input.page_input',
                'output': 'routes_output.page_output',
                'function': 'routes_function.page_function'
            }
            
            # Dashboard uses dashboard_id parameter, others use tab_id
            if page_type == 'dashboard':
                result['redirect_url'] = url_for(
                    endpoint_map.get(page_type, 'routes_general.home'),
                    dashboard_id=result['redirect_tab_id']
                )
            else:
                result['redirect_url'] = url_for(
                    endpoint_map.get(page_type, 'routes_general.home'),
                    tab_id=result['redirect_tab_id']
                )

        return jsonify(result), 200 if result['success'] else 400

    except Exception as e:
        logger.error(f"Error deleting tab: {e}")
        return jsonify({
            'success': False,
            'message': f'Error deleting tab: {str(e)}',
            'redirect_tab_id': None
        }), 500


@blueprint.route('/tab/save_order', methods=['POST'])
@flask_login.login_required
def save_tab_order():
    """
    Save the new order of tabs after drag-and-drop reordering.

    POST body (JSON):
        tab_ids: list - Array of tab unique_ids in new order

    Returns:
        JSON: {
            'success': bool,
            'message': str
        }
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({
            'success': False,
            'message': 'Permission denied'
        }), 403

    try:
        data = request.get_json()
        tab_ids = data.get('tab_ids', [])

        if not tab_ids or not isinstance(tab_ids, list):
            return jsonify({
                'success': False,
                'message': 'tab_ids array is required'
            }), 400

        success = TabService.reorder_tabs(tab_ids)

        if success:
            return jsonify({
                'success': True,
                'message': 'Tab order saved successfully'
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to save tab order'
            }), 500

    except Exception as e:
        logger.error(f"Error saving tab order: {e}")
        return jsonify({
            'success': False,
            'message': f'Error saving tab order: {str(e)}'
        }), 500
