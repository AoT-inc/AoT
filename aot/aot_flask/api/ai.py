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
                # Input 의 드라이버 식별자는 `device` 다(`library` 는 Camera
                # 모델에만 있다). 예전 코드가 `i.library` 를 읽어 입력이 하나라도
                # 있으면 이 엔드포인트가 통째로 500 이었다 — 2026-09-17 E2E
                # 라우트 스모크가 처음 잡았다.
                'library': i.device,
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
                # Output 의 드라이버 식별자는 `output_type` 이다. 그리고 Output
                # 에는 `is_activated` 자체가 없다 — 출력의 실제 on/off 는 채널
                # 상태이고 데몬만 안다. 여기서는 설정 존재 여부까지만 말한다.
                'library': o.output_type,
                'status': 'configured',
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
