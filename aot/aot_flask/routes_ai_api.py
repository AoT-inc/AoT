from flask import Blueprint, jsonify
from flask_login import login_required
from aot.databases.models import Input, Output, Function, CustomController, PID, Trigger, Conditional
from aot.config import AI_AGENT_ENABLED, LANGUAGES

blueprint = Blueprint('routes_ai_api', __name__)

@blueprint.route('/api/v1/ai/discovery', methods=['GET'])
@login_required
def ai_discovery():
    if not AI_AGENT_ENABLED:
        return jsonify({'error': 'AI Agent feature is disabled'}), 403

    # 1. Inputs Discovery
    inputs = Input.query.all()
    inputs_data = []
    for i in inputs:
        inputs_data.append({
            'unique_id': i.unique_id,
            'name': i.name,
            'type': 'input',
            'library': i.library,
            'status': 'active' if i.is_activated else 'inactive',
        })

    # 2. Outputs Discovery
    outputs = Output.query.all()
    outputs_data = []
    for o in outputs:
        outputs_data.append({
            'unique_id': o.unique_id,
            'name': o.name,
            'type': 'output',
            'library': o.library,
            'status': 'active' if o.is_activated else 'inactive',
        })

    # 3. Functions/Controllers Discovery (Integrated)
    functions_data = []
    
    # Standard Functions (Function model lacks is_activated in some contexts, using active as default)
    for f in Function.query.all():
        functions_data.append({
            'unique_id': f.unique_id, 'name': f.name, 'type': 'function',
            'function_type': 'standard', 'status': 'active'
        })
    
    # Custom Controllers
    for f in CustomController.query.all():
        functions_data.append({
            'unique_id': f.unique_id, 'name': f.name, 'type': 'function',
            'function_type': 'custom', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'
        })

    # PID Controllers
    for f in PID.query.all():
        functions_data.append({
            'unique_id': f.unique_id, 'name': f.name, 'type': 'function',
            'function_type': 'pid', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'
        })

    # Triggers
    for f in Trigger.query.all():
        functions_data.append({
            'unique_id': f.unique_id, 'name': f.name, 'type': 'function',
            'function_type': 'trigger', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'
        })

    # Conditionals
    for f in Conditional.query.all():
        functions_data.append({
            'unique_id': f.unique_id, 'name': f.name, 'type': 'function',
            'function_type': 'conditional', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'
        })

    return jsonify({
        'system_info': {
            'supported_languages': list(LANGUAGES.keys()),
            'current_agent_status': 'discovery_ready',
            'version': '1.0.0-ai-alpha'
        },
        'entities': {
            'inputs': inputs_data,
            'outputs': outputs_data,
            'functions': functions_data
        }
    })
