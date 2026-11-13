# coding=utf-8
"""trigger_camera_event 의 저장 검증과 화면 선택지 (설계 §5.4, §9.4).

저장 규칙: 카메라는 VIGI 드라이버가 설정된 것, `event_kinds` 는 비어 있으면 거절, 알 수 없는 종류도
거절(`cv.` 접두사는 향후 영상 분석용으로 허용), `period`(최소 재발화 간격, 초)는 0 이상 숫자.
"""
from flask_babel import gettext

from aot.camera_drivers import capabilities as C


def validate_camera_event_form(camera_id, kinds, period):
    """(오류 목록, 값 dict). 오류가 있으면 값은 비어 있다."""
    errors = []
    cid = (camera_id or '').strip()
    if not cid:
        errors.append(gettext('Camera must be set'))
    else:
        from aot.camera_drivers.event_hub import _scope
        from aot.databases.models import Camera, CameraDriver
        with _scope() as s:
            ok = (s.query(Camera.id).filter(Camera.unique_id == cid).first() is not None
                  and s.query(CameraDriver.camera_id).filter(CameraDriver.camera_id == cid).first()
                  is not None)
        if not ok:
            errors.append(gettext('Camera must be set'))
    kinds = [k for k in (kinds or []) if isinstance(k, str) and k]
    kinds = list(dict.fromkeys(kinds))       # 순서 유지 중복 제거
    if not kinds:
        errors.append(gettext('Select at least one event kind'))
    elif any(k not in C.EVENT_KINDS and not k.startswith(C.CV_PREFIX) for k in kinds):
        errors.append(gettext('Unsupported event kind'))
    try:
        p = float(period) if period not in (None, '') else 60.0
        if p < 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(gettext('Minimum re-fire interval must be 0 or more seconds'))
        p = None
    if errors:
        return errors, {}
    return [], {'camera_id': cid, 'kinds': kinds, 'period': p}


def camera_choices():
    """설정 화면용: VIGI 카메라(드라이버 설정된 것)와 이벤트 켬 여부·지원 종류."""
    from aot.camera_drivers.event_hub import _scope
    from aot.databases.models import Camera, CameraDriver
    out = []
    with _scope() as s:
        rows = s.query(Camera).filter(Camera.library == 'vigi').order_by(Camera.name).all()
        drivers = {d.camera_id: d for d in s.query(CameraDriver).all()}
        for cam in rows:
            d = drivers.get(cam.unique_id)
            if d is None:
                continue
            supported = (C.Capabilities.from_json(d.capabilities).event_kinds()
                         if d.capabilities else [])
            out.append({'unique_id': cam.unique_id, 'name': cam.name,
                        'events_enabled': bool(d.events_enabled), 'kinds': supported})
    return out
