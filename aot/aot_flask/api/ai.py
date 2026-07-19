from flask_restx import Resource, fields
from aot.aot_flask.api import api, default_responses
from aot.config import AI_AGENT_ENABLED, LANGUAGES
from aot.databases.models import Input, Output, Function, CustomController, PID, Trigger, Conditional

ns_ai = api.namespace('ai', description='AI Agent operations', path='/v1/ai')

@ns_ai.route('/discovery')
class AIDiscovery(Resource):
    @ns_ai.doc(responses=default_responses)
    def get(self):
        """Discovers system entities for the AI agent"""
        if not AI_AGENT_ENABLED:
            return {'error': 'AI Agent feature is disabled'}, 403

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

        # 3. Functions/Controllers Discovery
        functions_data = []
        for f in Function.query.all():
            functions_data.append({'unique_id': f.unique_id, 'name': f.name, 'type': 'function', 'function_type': 'standard', 'status': 'active'})
        for f in CustomController.query.all():
            functions_data.append({'unique_id': f.unique_id, 'name': f.name, 'type': 'function', 'function_type': 'custom', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'})
        for f in PID.query.all():
            functions_data.append({'unique_id': f.unique_id, 'name': f.name, 'type': 'function', 'function_type': 'pid', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'})
        for f in Trigger.query.all():
            functions_data.append({'unique_id': f.unique_id, 'name': f.name, 'type': 'function', 'function_type': 'trigger', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'})
        for f in Conditional.query.all():
            functions_data.append({'unique_id': f.unique_id, 'name': f.name, 'type': 'function', 'function_type': 'conditional', 'status': 'active' if getattr(f, 'is_activated', False) else 'inactive'})

        return {
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
        }
