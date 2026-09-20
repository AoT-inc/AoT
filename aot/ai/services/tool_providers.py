# coding=utf-8
"""내장 AI(aot.ai) 구현을 도구 계층의 프로바이더 레지스트리(aot/tools/providers.py)에
묶어 준다.

`aot/ai/__init__.py` 가 (직접이든, `aot.ai.*` 하위 모듈을 통해 간접이든)
import 될 때 `bind_all()` 을 호출한다 — 그래서 이 모듈 **밖**에서는
`aot.tools` 쪽이 `aot.ai.services.*` 를 직접 import 할 필요가 없다. 그 경계를
`tools-no-ai` 가드(aot/scripts/check_import_layers.py)가 지킨다.

여기서만 `aot.ai.services.*` 를 import 한다 — 그것도 각 어댑터 함수 **안에서
지연 import** 한다. `aot/ai/__init__.py` 가 모듈 로드 시점에 이 파일을
import 하므로, 여기서 최상위로 무거운 서비스 모듈들을 끌어오면 `aot.ai`
패키지를 import 하는 것만으로 서비스 계층 전체가 즉시 로드된다 — 순환
import 위험도 커지고, `aot.tools` 만 필요한 가벼운 스크립트(예: 이 파일이
없던 시절의 `check_import_layers.py`)까지 무거워진다. 지연 import 는 실제로
그 프로바이더가 **불릴 때만** 비용을 낸다.
"""
from aot.tools import providers


# ---------------------------------------------------------------------------
# spatial_hierarchy / device_zone_map — AIContextService
# ---------------------------------------------------------------------------

def _spatial_hierarchy(tier=None):
    from aot.ai.services.ai_context_service import AIContextService
    return AIContextService.get_spatial_hierarchy(tier)


def _device_zone_map():
    from aot.ai.services.ai_context_service import AIContextService
    return AIContextService.get_device_zone_map()


# ---------------------------------------------------------------------------
# job_scheduler — ai_scheduler_service (propose/approve) + 그 밑 APScheduler
# 인스턴스(get_job/remove_job로 트리거 재조정·제거)
# ---------------------------------------------------------------------------

class _JobScheduler:
    """schedule.py 가 실제로 쓰는 것만 — 서비스 전체를 감싸지 않는다."""

    @staticmethod
    def propose_job(*args, **kwargs):
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        return AISchedulerService.propose_job(*args, **kwargs)

    @staticmethod
    def approve_job(*args, **kwargs):
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        return AISchedulerService.approve_job(*args, **kwargs)

    @staticmethod
    def get_job(job_key):
        """등록된 APScheduler 트리거(Job) 또는 None. 호출자가 `.modify(...)`
        로 재조정할 수 있게 그대로 돌려준다(schedule.py::edit_schedule_tool)."""
        from aot.ai.services.ai_scheduler_service import get_scheduler
        return get_scheduler().get_job(job_key)

    @staticmethod
    def remove_job(job_key):
        from aot.ai.services.ai_scheduler_service import get_scheduler
        get_scheduler().remove_job(job_key)


_JOB_SCHEDULER = _JobScheduler()


# ---------------------------------------------------------------------------
# anomaly_summary — ai_summary_service + ai_anomaly_detector
# ---------------------------------------------------------------------------

def _anomaly_summary(scope_type, scope_id):
    """measurement.py::get_anomalies 가 필요로 하는 것만 한 dict 로 묶는다 —
    gather_scope_data/get_latest_summary/detect_anomalies 세 호출을 여기서
    끝내고, 호출부는 model 인스턴스(AISystemSummary)를 직접 만지지 않는다."""
    from aot.ai.services.ai_summary_service import AISummaryService
    from aot.ai.services.ai_anomaly_detector import AIAnomalyDetector

    current = AISummaryService.gather_scope_data(scope_type, scope_id)
    previous = AISummaryService.get_latest_summary(scope_type, scope_id)
    verdict = AIAnomalyDetector.detect_anomalies(current, previous) or {}
    return {
        "anomaly_detected": verdict.get('anomaly_detected', False),
        "alert_level": verdict.get('alert_level', 'none'),
        "anomalies": verdict.get('anomalies', []),
        "metrics": current.get('metrics', {}),
        "previous_version": (previous.version if previous is not None else None),
        "timestamp": current.get('timestamp'),
    }


# ---------------------------------------------------------------------------
# knowledge_search / knowledge_library_populated / knowledge_shelve
# ---------------------------------------------------------------------------

def _knowledge_search(query, top_k=3, tags=None):
    from aot.ai.services import knowledge_search as _ks
    return _ks.search_as_text(query, top_k=top_k, tags=tags)


def _knowledge_library_populated():
    from aot.ai.services import knowledge_search as _ks
    return _ks.library_is_populated()


def _knowledge_shelve(**kwargs):
    from aot.ai.services.knowledge_shelve_service import shelve_knowledge
    return shelve_knowledge(**kwargs)


# ---------------------------------------------------------------------------
# domain_module — domain_context_loader
# ---------------------------------------------------------------------------

def _domain_module(facility_id):
    from aot.ai.services.domain_context_loader import DomainContextLoader
    return DomainContextLoader.load_active_module(facility_id)


# ---------------------------------------------------------------------------
# source_sync — context_source_service
# ---------------------------------------------------------------------------

def _source_sync(source_id):
    from aot.ai.services.context_source_service import sync_source
    return sync_source(source_id)


# ---------------------------------------------------------------------------
# tool_access_allowed / mcp_active_server_ids — mcp_bridge_service
# ---------------------------------------------------------------------------

def _tool_access_allowed(agent_id, server_id, tool_name):
    from aot.ai.services.mcp_bridge_service import MCPBridgeService
    return MCPBridgeService._check_tool_access(agent_id, server_id, tool_name)


def _mcp_active_server_ids():
    from aot.ai.services.mcp_bridge_service import MCPBridgeService
    return {s.unique_id for s in MCPBridgeService.get_active_servers()}


# ---------------------------------------------------------------------------
# reverse_lookup — user_string_translator
# ---------------------------------------------------------------------------

def _reverse_lookup(text):
    from aot.ai.services.user_string_translator import reverse_lookup
    return reverse_lookup(text)


# ---------------------------------------------------------------------------
# action_service — ai_action_service (aot_native_tool_engine 이 쓰는 것만)
# ---------------------------------------------------------------------------

class _ActionService:
    @staticmethod
    def execute_action(action_type, target_id=None, params=None, _approved=False):
        from aot.ai.services.ai_action_service import AIActionService
        return AIActionService.execute_action(
            action_type, target_id, params, _approved=_approved)


_ACTION_SERVICE = _ActionService()


# ---------------------------------------------------------------------------
# data_source_query — data_source_query_service (record.py/measurement.py 가
# 쓰는 것만: describe_all + query. 내부 전용 _sources() 는 감싸지 않는다 —
# measurement.py 의 _forecast_fallback_hint 는 describe_all() 로 바꿔 쓴다.)
# ---------------------------------------------------------------------------

class _DataSourceQuery:
    @staticmethod
    def describe_all():
        from aot.ai.services import data_source_query_service as dsq
        return dsq.describe_all()

    @staticmethod
    def query(source_id, operation, params=None, limit=5, columns=None):
        from aot.ai.services import data_source_query_service as dsq
        return dsq.query(source_id, operation, params=params, limit=limit,
                         columns=columns)


_DATA_SOURCE_QUERY = _DataSourceQuery()


# ---------------------------------------------------------------------------
# smartfarmkorea — aot.ai.context.ext.smartfarmkorea_client
# ---------------------------------------------------------------------------

class _SmartfarmKorea:
    @staticmethod
    def operations_for_preset(preset_key):
        from aot.ai.context.ext.smartfarmkorea_client import operations_for_preset
        return operations_for_preset(preset_key)

    @staticmethod
    def resolve_farms(api_key, operations=None):
        from aot.ai.context.ext.smartfarmkorea_client import resolve_farms
        return resolve_farms(api_key, operations=operations)

    @staticmethod
    def resolve_seasons(api_key, user_id, operations=None):
        from aot.ai.context.ext.smartfarmkorea_client import resolve_seasons
        return resolve_seasons(api_key, user_id, operations=operations)


_SMARTFARMKOREA = _SmartfarmKorea()


def bind_all():
    """모든 프로바이더를 등록한다. 여러 번 불러도 안전하다(마지막 호출이
    이기며, 등록되는 값 자체는 매번 동일하다) — `aot.ai` 를 여러 경로로
    반복 import 해도, 테스트가 재바인딩을 확인하려고 다시 불러도 된다."""
    providers.register('spatial_hierarchy', _spatial_hierarchy)
    providers.register('device_zone_map', _device_zone_map)
    providers.register('job_scheduler', _JOB_SCHEDULER)
    providers.register('anomaly_summary', _anomaly_summary)
    providers.register('knowledge_search', _knowledge_search)
    providers.register('knowledge_library_populated', _knowledge_library_populated)
    providers.register('knowledge_shelve', _knowledge_shelve)
    providers.register('domain_module', _domain_module)
    providers.register('source_sync', _source_sync)
    providers.register('tool_access_allowed', _tool_access_allowed)
    providers.register('mcp_active_server_ids', _mcp_active_server_ids)
    providers.register('reverse_lookup', _reverse_lookup)
    providers.register('action_service', _ACTION_SERVICE)
    providers.register('data_source_query', _DATA_SOURCE_QUERY)
    providers.register('smartfarmkorea', _SMARTFARMKOREA)
