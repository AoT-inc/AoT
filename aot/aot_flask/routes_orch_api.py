# coding=utf-8
import logging
from flask import Blueprint, jsonify, request
import flask_login

from aot.databases.models.orch_task import OrchTask
from aot.databases.models.orch_workflow import OrchWorkflow
from aot.databases.models.orch_device import OrchDevice
from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

blueprint = Blueprint('routes_orch_api', __name__, url_prefix='/api/orch')

@blueprint.route('/tasks', methods=['GET', 'POST'])
@flask_login.login_required
def orch_tasks():
    if request.method == 'GET':
        tasks = OrchTask.query.all()
        return jsonify([t.to_dict() for t in tasks])
    
    elif request.method == 'POST':
        data = request.json
        try:
            new_task = OrchTask(
                task_type=data.get('task_type'),
                priority=data.get('priority', 5),
                workflow_id=data.get('workflow_id'),
                assigned_device_id=data.get('assigned_device_id'),
                params_json=data.get('params_json', '{}'),
                status=data.get('status', 'pending')
            )
            new_task.save()
            return jsonify(new_task.to_dict()), 201
        except Exception as e:
            logger.error(f"Error creating orch task: {e}")
            return jsonify({"error": str(e)}), 400

@blueprint.route('/devices', methods=['GET', 'POST'])
@flask_login.login_required
def orch_devices():
    if request.method == 'GET':
        devices = OrchDevice.query.all()
        return jsonify([d.to_dict() for d in devices])
    
    elif request.method == 'POST':
        data = request.json
        try:
            new_device = OrchDevice(
                name=data.get('name'),
                device_type=data.get('device_type', 'raspberry_pi'),
                capabilities=data.get('capabilities', '[]'),
                ip_address=data.get('ip_address'),
                status=data.get('status', 'offline')
            )
            new_device.save()
            return jsonify(new_device.to_dict()), 201
        except Exception as e:
            logger.error(f"Error creating orch device: {e}")
            return jsonify({"error": str(e)}), 400

@blueprint.route('/workflows', methods=['GET', 'POST'])
@flask_login.login_required
def orch_workflows():
    if request.method == 'GET':
        workflows = OrchWorkflow.query.all()
        return jsonify([w.to_dict() for w in workflows])
    
    elif request.method == 'POST':
        data = request.json
        try:
            new_workflow = OrchWorkflow(
                name=data.get('name'),
                description=data.get('description', ''),
                status=data.get('status', 'pending')
            )
            new_workflow.save()
            return jsonify(new_workflow.to_dict()), 201
        except Exception as e:
            logger.error(f"Error creating orch workflow: {e}")
            return jsonify({"error": str(e)}), 400
