# coding=utf-8
"""
mcp_server/manifest.py — P4-2: AI 에이전트용 시스템 매니페스트 동적 생성.

MCP 서버 시작 시 / 도구 호출 시 AI 에이전트에게 제공되는
AoT 시스템 컨텍스트 + 정책 + 안전 경계 정보.
"""

from __future__ import annotations

import json
import importlib.metadata


def get_manifest() -> dict:
    """AoT 환경제어 MCP 매니페스트 반환."""
    try:
        aot_version = importlib.metadata.version('aot')
    except Exception:
        aot_version = 'dev'

    return {
        'system': 'AoT - AI-based Greenhouse Environment Control',
        'version': aot_version,
        'description': (
            'AoT integrates multi-layer environment control (VPD-primary, '
            'temperature/humidity guide ranges, CO₂, light) with facility GIS, '
            'automated actuator coordination, and time-based Method setpoints. '
            'AI agents may observe, diagnose, and — with user confirmation — '
            'adjust control parameters.'
        ),
        'language': 'ko/en',
        'domain_knowledge': {
            'primary_target': 'VPD (Vapor Pressure Deficit, kPa)',
            'guide_variables': ['temperature (°C)', 'humidity (%)'],
            'secondary_targets': ['CO₂ (ppm)', 'light (W/m² or µmol/m²/s)'],
            'safety_ranges': {
                'VPD':         '0.0 ~ 3.0 kPa',
                'temperature': '5 ~ 40 °C',
                'humidity':    '20 ~ 95 %',
                'CO2':         '400 ~ 2000 ppm',
            },
            'actuator_kinds': [
                'opening (vent)', 'cooler', 'heater', 'fogger',
                'co2_injector', 'shade', 'curtain', 'lighting',
                'circulation_fan', 'exhaust_fan', 'intake_fan',
            ],
            'control_layers': {
                'L1': 'EnvTarget — VPD/CO₂ setpoint from static value or Method curve',
                'L2': 'SituationReport — assess deviation, limiting factor, trend',
                'L3': 'Coordinator — PI + slew + anti-windup per actuator',
            },
            'method_types': [
                'Daily', 'DailySine', 'DailyBezier',
                'Duration', 'Cascade', 'DailyMultiPoint (P3-5)',
            ],
        },
        'capabilities': [
            'observe: read sensors, facility state, actuator commands',
            'diagnose: analyse control performance, detect anomalies',
            'suggest: recommend setpoint adjustments (not applied automatically)',
            'control (confirmation required): update Method points, VPD target',
        ],
        'policies': {
            'write_default': 'OFF — user must explicitly enable write mode',
            'write_requires_confirmation': True,
            'confirmation_ttl_sec': 60,
            'max_write_calls_per_hour': {
                'set_vpd_target': 5,
                'update_method_point': 10,
                'request_manual_lock': 3,
            },
            'forbidden': [
                'disable safety gates (rain/wind/temperature)',
                'delete or overwrite seed Method presets (is_seed=True)',
                'force actuator to exceed hardware limits',
                'bypass user confirmation for write operations',
            ],
            'seed_presets': (
                'Crop seed presets (SEED:*) are read-only. '
                'Duplicate a preset before editing.'
            ),
        },
        'best_practices': [
            'Start with observe tools before diagnosing.',
            'Change only one parameter at a time; wait one cycle (60s) for response.',
            'When suggesting setpoint changes, provide a reason.',
            'VPD changes > 0.3 kPa/call are blocked — make gradual adjustments.',
            'Always check limiting_factor before recommending actuator changes.',
            'If sensors are stale (ext_context expired), report to user first.',
        ],
        'workflow': {
            'anomaly_response': [
                '1. list_facilities → get_facility_state',
                '2. analyze_control_performance',
                '3. detect_sensor_anomaly (if data quality suspect)',
                '4. suggest_setpoint_adjustment',
                '5. Present suggestion to user, await approval',
                '6. set_vpd_target or update_method_point (confirmation required)',
            ],
        },
        'docs_uri': 'aot://docs/ai_guide.ko.md',
    }


def get_manifest_json() -> str:
    return json.dumps(get_manifest(), ensure_ascii=False, indent=2)
