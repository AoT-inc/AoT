# coding=utf-8
"""
mcp_server/server.py — AoT FastMCP 서버 진입점.

실행:
  python -m aot.mcp_server.server          # stdio (Claude Desktop 연동)
  python -m aot.mcp_server.server --http   # HTTP SSE (개발/테스트)

환경 변수:
  AOT_MCP_WRITE_ENABLED=1   쓰기 도구 활성화 (기본 비활성)
  AOT_MCP_AGENT_ID          기본 에이전트 ID (기본 'claude')
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Flask 앱 컨텍스트 초기화 (DB 모델 접근에 필요) ─────────────────────────
def _init_flask_context():
    try:
        from aot import create_app
        app = create_app()
        ctx = app.app_context()
        ctx.push()
        logger.info('Flask app context pushed for MCP server')
        return ctx
    except Exception as exc:
        logger.warning('Flask context not available: %s', exc)
        return None

# ── FastMCP 초기화 ───────────────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            'FastMCP not installed. Run: pip install fastmcp>=3.2.0'
        ) from exc

from aot.mcp_server.manifest import get_manifest_json
from aot.mcp_server import safety as _safety
from aot.mcp_server.tools import observe, diagnose, control

_AGENT_ID = os.environ.get('AOT_MCP_AGENT_ID', 'claude')

# 쓰기 활성화 환경변수 확인
if os.environ.get('AOT_MCP_WRITE_ENABLED', '').strip() in ('1', 'true', 'yes'):
    _safety.set_write_enabled(True)
    logger.info('MCP write tools ENABLED via AOT_MCP_WRITE_ENABLED')

# FastMCP 인스턴스 생성
mcp = FastMCP(
    name='AoT Environment Control',
    instructions=get_manifest_json(),
)


# ─────────────────────────────────────────────────────────────────────────────
# Observe 도구 (read-only)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_facilities() -> list[dict]:
    """등록된 GeoFacility 목록을 반환한다."""
    return observe.list_facilities()


@mcp.tool()
def get_facility_state(facility_id: str) -> dict:
    """시설의 현재 환경 상태를 반환한다 (T, RH, VPD, CO₂, Light).

    Args:
        facility_id: GeoFacility.unique_id
    """
    return observe.get_facility_state(facility_id)


@mcp.tool()
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
    """
    return observe.get_sensor_history(device_id, measurement_id, window)


@mcp.tool()
def list_functions() -> list[dict]:
    """활성화된 AoT Function 목록을 반환한다."""
    return observe.list_functions()


@mcp.tool()
def get_function_state(function_id: str) -> dict:
    """env_coordinator 함수의 런타임 상태를 반환한다.

    Args:
        function_id: CustomController.unique_id
    """
    return observe.get_function_state(function_id)


@mcp.tool()
def list_methods(method_type: Optional[str] = None) -> list[dict]:
    """등록된 Method 목록을 반환한다.

    Args:
        method_type: 필터 ('DailyMultiPoint' 등). None 이면 전체.
    """
    return observe.list_methods(method_type)


@mcp.tool()
def list_outputs(facility_id: Optional[str] = None) -> list[dict]:
    """등록된 액추에이터 Output 목록과 현재 상태를 반환한다.

    Args:
        facility_id: 시설 ID (필터). None 이면 전체.
    """
    return observe.list_outputs(facility_id)


@mcp.tool()
def get_recent_events(limit: int = 20, tool_name: Optional[str] = None) -> list[dict]:
    """최근 MCP 감사 로그를 반환한다.

    Args:
        limit:     반환할 최대 행 수
        tool_name: 특정 도구만 필터 (선택)
    """
    return observe.get_recent_events(limit, tool_name)


# ─────────────────────────────────────────────────────────────────────────────
# Diagnose 도구 (read-only 분석)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def analyze_control_performance(
    function_id: str,
    window: str = '1h',
) -> dict:
    """env_coordinator 의 VPD 추종 성능을 분석한다 (RMSE, 진동, 포화율).

    Args:
        function_id: CustomController.unique_id
        window:      '1h' | '6h' | '24h'
    """
    return diagnose.analyze_control_performance(function_id, window)


@mcp.tool()
def detect_sensor_anomaly(
    device_id: str,
    measurement_id: str,
    window: str = '24h',
) -> dict:
    """센서 이상치·드리프트를 감지한다 (IQR + 선형 추세).

    Args:
        device_id:      Input device unique_id
        measurement_id: DeviceMeasurements unique_id
        window:         '1h' | '6h' | '24h'
    """
    return diagnose.detect_sensor_anomaly(device_id, measurement_id, window)


@mcp.tool()
def suggest_setpoint_adjustment(facility_id: str) -> dict:
    """현재 VPD 상태를 기반으로 setpoint 권장값을 제안한다 (적용 안 됨).

    Args:
        facility_id: GeoFacility.unique_id
    """
    return diagnose.suggest_setpoint_adjustment(facility_id)


@mcp.tool()
def compare_periods(
    device_id: str,
    measurement_id: str,
    period_a_hours_ago: int = 48,
    period_b_hours_ago: int = 24,
    window_hours: int = 24,
) -> dict:
    """두 기간의 센서 통계를 비교한다.

    Args:
        device_id:            센서 device unique_id
        measurement_id:       측정값 unique_id
        period_a_hours_ago:   A 기간 시작점 (현재로부터 N시간 전)
        period_b_hours_ago:   B 기간 시작점
        window_hours:         각 기간의 길이 (시간)
    """
    return diagnose.compare_periods(
        device_id, measurement_id,
        period_a_hours_ago, period_b_hours_ago, window_hours)


# ─────────────────────────────────────────────────────────────────────────────
# Control 도구 (write — 사용자 승인 필요)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def set_vpd_target(
    function_id: str,
    value: float,
    reason: str = '',
) -> dict:
    """VPD 목표값을 변경한다. 사용자 승인 필요.

    허용 범위: 0.3 ~ 2.5 kPa | 1회 변화량: ≤ 0.5 kPa | 시간당 최대 5회.

    Args:
        function_id: CustomController.unique_id
        value:       새 VPD 목표 (kPa)
        reason:      변경 이유 (감사 로그에 기록)
    """
    return control.set_vpd_target(function_id, value, reason, _AGENT_ID)


@mcp.tool()
def update_method_point(
    method_id: str,
    point_index: int,
    new_value: float,
    reason: str = '',
) -> dict:
    """DailyMultiPoint 곡선의 제어점 값을 변경한다. 사용자 승인 필요.

    허용 범위: 0.0 ~ 3.0 kPa | 1회 변화량: ≤ 0.3 kPa | 시간당 최대 10회.
    시드 프리셋(SEED:*)은 수정 불가 — 복제 후 편집하세요.

    Args:
        method_id:    Method.unique_id
        point_index:  제어점 인덱스 (0-based)
        new_value:    새 VPD 값 (kPa)
        reason:       변경 이유
    """
    return control.update_method_point(method_id, point_index, new_value, reason, _AGENT_ID)


@mcp.tool()
def request_manual_lock(
    function_id: str,
    duration_minutes: int = 30,
    reason: str = '',
) -> dict:
    """AI 자동제어를 일시 정지 요청한다. 사용자 승인 필요.

    Args:
        function_id:       CustomController.unique_id
        duration_minutes:  잠금 기간 (1 ~ 120분)
        reason:            정지 이유
    """
    return control.request_manual_lock(function_id, duration_minutes, reason, _AGENT_ID)


@mcp.tool()
def acknowledge_alert(
    alert_id: str,
    note: str = '',
) -> dict:
    """시스템 경보를 확인 처리한다. 사용자 승인 필요.

    Args:
        alert_id: NotificationLog.unique_id
        note:     확인 메모
    """
    return control.acknowledge_alert(alert_id, note, _AGENT_ID)


@mcp.tool()
def confirm_action(token_id: str, user_id: str = 'user') -> dict:
    """대기 중인 쓰기 작업을 승인한다.

    Args:
        token_id: 쓰기 도구가 반환한 token_id
        user_id:  승인 사용자 ID
    """
    return control.confirm_action(token_id, user_id)


@mcp.tool()
def reject_action(token_id: str, user_id: str = 'user') -> dict:
    """대기 중인 쓰기 작업을 거부한다.

    Args:
        token_id: 쓰기 도구가 반환한 token_id
        user_id:  거부 사용자 ID
    """
    return control.reject_action(token_id, user_id)


@mcp.tool()
def get_pending_actions() -> list[dict]:
    """승인 대기 중인 쓰기 작업 목록을 반환한다."""
    return _safety.get_pending_confirmations()


@mcp.tool()
def get_system_manifest() -> dict:
    """AoT 시스템 매니페스트 (도메인 지식 + 정책 + 워크플로)를 반환한다."""
    from aot.mcp_server.manifest import get_manifest
    return get_manifest()


# ─────────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import sys
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    parser = argparse.ArgumentParser(description='AoT MCP Server')
    parser.add_argument('--http', action='store_true',
                        help='HTTP SSE 모드로 실행 (기본: stdio)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5050)
    parser.add_argument('--write', action='store_true',
                        help='쓰기 도구 활성화 (기본 비활성)')
    args = parser.parse_args()

    if args.write:
        _safety.set_write_enabled(True)
        logger.info('Write tools ENABLED via --write flag')

    _init_flask_context()

    if args.http:
        logger.info('Starting AoT MCP server in HTTP mode on %s:%d', args.host, args.port)
        mcp.run(transport='sse', host=args.host, port=args.port)
    else:
        logger.info('Starting AoT MCP server in stdio mode')
        mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
