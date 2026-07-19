# coding=utf-8
"""
mcp_server/tools/observe.py — P4-1: 읽기 전용 observe 도구 모음.

모든 도구는 read-only (permission='read').
FastMCP 서버에 @mcp.tool() 데코레이터로 등록된다.

도구 목록:
  list_facilities       — 시설 목록
  get_facility_state    — 시설 현재 환경값 (T, RH, VPD, CO₂, Light)
  get_sensor_history    — 센서 시계열 (1h/24h/7d)
  list_functions        — 활성 Function 목록·상태
  get_function_state    — env_coordinator 사이클 상태
  list_methods          — Method 목록 + 곡선 요약
  list_outputs          — 액추에이터 현재 명령값
  get_recent_events     — 최근 감사 로그
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _safe_query(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning('observe query failed: %s', exc)
        return default


def _fmt_ts(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


# ─────────────────────────────────────────────────────────────────────────────
# list_facilities
# ─────────────────────────────────────────────────────────────────────────────

def list_facilities() -> list[dict]:
    """등록된 GeoFacility 목록과 기본 메타 정보를 반환한다.

    Returns:
        List of dicts with keys: unique_id, name, facility_type, computed.
    """
    def _query():
        from aot.databases.models import GeoFacility
        rows = GeoFacility.query.all()
        return [
            {
                'unique_id':      r.unique_id,
                'name':           r.name,
                'facility_type':  getattr(r, 'facility_type', None),
                'computed':       r.computed or {},
            }
            for r in rows
        ]
    return _safe_query(_query, default=[])


# ─────────────────────────────────────────────────────────────────────────────
# get_facility_state
# ─────────────────────────────────────────────────────────────────────────────

def get_facility_state(facility_id: str) -> dict:
    """시설의 현재 환경 상태를 반환한다.

    Args:
        facility_id: GeoFacility.unique_id

    Returns:
        Dict with T_int, RH_int, VPD, CO2, Light, wind, rain,
        ext_context_age_sec, last_update_iso, sensors_health.
    """
    def _query():
        # ext_context_collector 공유 컨텍스트
        ext = {}
        try:
            from aot.functions.ext_context_collector import get_shared_context
            ext = get_shared_context() or {}
        except Exception:
            pass

        import time
        now = time.time()
        last_ext = ext.get('last_ext_ts', 0)
        age = now - last_ext if last_ext else None

        return {
            'facility_id':       facility_id,
            'T_int':             ext.get('T_int'),
            'RH_int':            ext.get('RH_int'),
            'VPD':               ext.get('VPD'),
            'CO2':               ext.get('CO2'),
            'Light':             ext.get('light'),
            'T_ext':             ext.get('T_ext'),
            'wind_speed':        ext.get('wind'),
            'wind_dir':          ext.get('wind_dir'),
            'rain':              ext.get('rain'),
            'ext_context_age_sec': round(age, 1) if age is not None else None,
            'sensors_health':    'ok' if (age is not None and age < 300) else 'stale',
            'last_update_iso':   _fmt_ts(
                __import__('datetime').datetime.utcfromtimestamp(last_ext)
                if last_ext else None),
        }

    return _safe_query(_query, default={'facility_id': facility_id, 'error': 'query failed'})


# ─────────────────────────────────────────────────────────────────────────────
# get_sensor_history
# ─────────────────────────────────────────────────────────────────────────────

def get_sensor_history(
    device_id: str,
    measurement_id: str,
    window: str = '1h',
) -> dict:
    """센서 시계열 데이터를 반환한다.

    Args:
        device_id:      Input device unique_id
        measurement_id: DeviceMeasurements unique_id
        window:         '1h' | '24h' | '7d'

    Returns:
        Dict with unit, data (list of [iso_timestamp, value]).
    """
    _WINDOWS = {'1h': 3600, '24h': 86400, '7d': 604800}
    seconds = _WINDOWS.get(window, 3600)

    def _query():
        from aot.utils.database import db_retrieve_table_daemon
        from aot.databases.models import DeviceMeasurements, Input
        import time

        dm = db_retrieve_table_daemon(
            DeviceMeasurements,
            unique_id=measurement_id)
        unit = getattr(dm, 'unit', '')

        # InfluxDB 조회 (utils/influx.py)
        try:
            from aot.utils.influxdb_tags import read_last_measurements
            readings = read_last_measurements(
                device_id, measurement_id,
                max_age=seconds, max_count=500)
        except Exception:
            readings = []

        return {
            'device_id':       device_id,
            'measurement_id':  measurement_id,
            'window':          window,
            'unit':            unit,
            'count':           len(readings),
            'data':            readings,  # [[iso_ts, value], ...]
        }

    return _safe_query(_query, default={
        'device_id': device_id, 'window': window, 'data': [], 'error': 'query failed'})


# ─────────────────────────────────────────────────────────────────────────────
# list_functions
# ─────────────────────────────────────────────────────────────────────────────

def list_functions() -> list[dict]:
    """활성화된 AoT Function 목록을 반환한다.

    Returns:
        List of dicts with unique_id, function_type, is_activated.
    """
    def _query():
        from aot.databases.models import CustomController
        rows = CustomController.query.all()
        return [
            {
                'unique_id':      r.unique_id,
                'name':           getattr(r, 'name', ''),
                'function_type':  getattr(r, 'device_type', ''),
                'is_activated':   getattr(r, 'is_activated', False),
            }
            for r in rows
        ]
    return _safe_query(_query, default=[])


# ─────────────────────────────────────────────────────────────────────────────
# get_function_state
# ─────────────────────────────────────────────────────────────────────────────

def get_function_state(function_id: str) -> dict:
    """env_coordinator 함수의 현재 런타임 상태를 반환한다.

    Args:
        function_id: CustomController.unique_id

    Returns:
        Dict with last_cycle_ts, integral, prev_commands, active_vars.
    """
    def _query():
        from aot.databases.models import FunctionRuntimeState
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        import json

        with session_scope(AOT_DB_PATH) as sess:
            row = sess.query(FunctionRuntimeState).filter(
                FunctionRuntimeState.function_id == function_id
            ).first()
            if row is None:
                return {'function_id': function_id, 'state': 'no_data'}
            result = {
                'function_id':   function_id,
                'last_cycle_ts': row.last_cycle_ts,
                'updated_at':    row.updated_at,
                'integral':      json.loads(row.integral_json or '{}'),
                'prev_commands': json.loads(row.prev_cmds_json or '{}'),
                'active_vars':   json.loads(row.active_vars_json or '{}'),
            }
            sess.expunge_all()
        return result

    return _safe_query(_query, default={'function_id': function_id, 'error': 'query failed'})


# ─────────────────────────────────────────────────────────────────────────────
# list_methods
# ─────────────────────────────────────────────────────────────────────────────

def list_methods(method_type: Optional[str] = None) -> list[dict]:
    """등록된 Method 목록을 반환한다.

    Args:
        method_type: 필터 (예: 'DailyMultiPoint'). None 이면 전체.

    Returns:
        List of dicts with unique_id, name, method_type, is_seed.
    """
    def _query():
        from aot.databases.models import Method
        q = Method.query
        if method_type:
            q = q.filter(Method.method_type == method_type)
        rows = q.all()
        return [
            {
                'unique_id':   r.unique_id,
                'name':        r.name,
                'method_type': r.method_type,
                'is_seed':     r.name.startswith('SEED:') if r.name else False,
            }
            for r in rows
        ]
    return _safe_query(_query, default=[])


# ─────────────────────────────────────────────────────────────────────────────
# list_outputs
# ─────────────────────────────────────────────────────────────────────────────

def list_outputs(facility_id: Optional[str] = None) -> list[dict]:
    """등록된 액추에이터 Output 목록과 현재 상태를 반환한다.

    Args:
        facility_id: 시설 ID (필터). None 이면 전체.

    Returns:
        List of dicts with unique_id, name, output_type, is_on, current_amplitude.
    """
    def _query():
        from aot.databases.models import Output
        rows = Output.query.all()
        result = []
        for r in rows:
            result.append({
                'unique_id':         r.unique_id,
                'name':              getattr(r, 'name', ''),
                'output_type':       getattr(r, 'output_type', ''),
                'interface':         getattr(r, 'interface', ''),
                'is_on':             getattr(r, 'is_on', None),
                'current_amplitude': getattr(r, 'current_amplitude', None),
            })
        return result

    return _safe_query(_query, default=[])


# ─────────────────────────────────────────────────────────────────────────────
# get_recent_events
# ─────────────────────────────────────────────────────────────────────────────

def get_recent_events(limit: int = 20, tool_name: Optional[str] = None) -> list[dict]:
    """최근 MCP 감사 로그 이벤트를 반환한다.

    Args:
        limit:     반환할 최대 행 수 (기본 20)
        tool_name: 특정 도구만 필터 (선택)

    Returns:
        List of audit log dicts.
    """
    from aot.mcp_server import audit
    return audit.get_recent(limit=limit, tool_name=tool_name)
