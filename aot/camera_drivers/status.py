# coding=utf-8
"""camera_driver 행 → 화면용 상태 dict. 비밀(비밀번호·지문 전체·stok)을 담지 않는다."""

_MESSAGES = {
    # 상태 → (영문 키). 문구 번역은 화면(템플릿)이 한다.
    'unverified': 'unverified', 'ok': 'ok', 'failed': 'failed', 'locked': 'locked',
    'openapi_off': 'openapi_off', 'cert_changed': 'cert_changed',
}


def recent_events(session, camera_id, limit=5):
    """최근 이벤트 `limit`건(최신 먼저). 시각은 서버 수신 시각(UTC ISO) — 화면이 현지 시간으로 바꾼다."""
    from aot.databases.models import CameraEvent
    from aot.utils.timekit import iso_utc
    rows = session.query(CameraEvent).filter(CameraEvent.camera_id == camera_id).order_by(
        CameraEvent.id.desc()).limit(limit).all()
    return [{'kind': r.kind, 'enhanced': r.enhanced or '', 'dispatch_state': r.dispatch_state,
             'received_at': iso_utc(r.received_at_utc)} for r in rows]


def build_status(row, recent=None):
    if row is None:
        return {'configured': False}
    return {
        'events_enabled': bool(row.events_enabled),
        'event_kinds': row.event_kinds if isinstance(row.event_kinds, list) else None,
        'event_state': row.event_state or 'off',
        'event_state_at': (row.event_state_at.isoformat() + 'Z') if row.event_state_at else None,
        'event_note': row.event_note or '',
        'recent_events': recent or [],
        'configured': True,
        'auth_state': _MESSAGES.get(row.auth_state, 'unverified'),
        'auth_iface': row.auth_iface or '',
        'auth_code': row.auth_code,
        'host': row.host or '',
        'username': row.username or '',
        'has_password': bool(row.password_sealed),
        'live_profile': row.live_profile,
        'onvif_port': row.openapi_port,      # ONVIF 만 의미 있음(D6a)
        'tls_pin': (row.tls_pin_sha256 or '')[:16],
        'device_info': {k: v for k, v in (row.device_info or {}).items()
                        if k in ('model', 'swVer', 'alias', 'type')},
        'capabilities': row.capabilities or {},
        'capabilities_at': (row.capabilities_at.isoformat() + 'Z') if row.capabilities_at else None,
    }
