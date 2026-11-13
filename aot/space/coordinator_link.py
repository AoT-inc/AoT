# coding=utf-8
"""시설 ↔ env_coordinator 연결 판정 (공간 도메인).

웹(`routes_geo_iec`)·트윈(`twin/discovery`)이 함께 쓴다. 트윈이 라우트 모듈을
import 하지 않게 여기로 옮겼다(아키텍처 3단계, `twin-no-routes`). 동작은 옮기기
전과 같다 — `CustomController.query` 는 호출하는 쪽의 앱 컨텍스트에서 돈다.
"""
import logging

logger = logging.getLogger(__name__)


def _function_facility_uuid(fn):
    """이 env_coordinator 가 붙은 시설 uuid → str|None.

    ⚠ **키가 둘이다.** `select_device` 옵션이 저장 시 `_device_id` 접미사를
      붙이므로 신규는 `geo_facility_id_device_id` 이고, 예전 값은
      `geo_facility_id` 다. 둘을 읽는 자리가 여럿이면 갈라지고, 갈라지면
      "붙었는데 안 붙은 것으로 보이는" 시설이 생긴다 — 읽는 곳은 여기 하나다.
    """
    import json as _json
    try:
        opts = _json.loads(fn.custom_options or '{}') or {}
    except (TypeError, ValueError):
        return None
    return (opts.get('geo_facility_id_device_id')
            or opts.get('geo_facility_id') or None)


def _function_belongs_to_facility(fn, facility_uuid):
    """fn(env_coordinator CustomController) 이 facility_uuid 에 연결된 것인지 확인.

    판정 기준은 `_function_facility_uuid` 하나다 — status/env_summary 공용.
    """
    return _function_facility_uuid(fn) == facility_uuid


def _find_facility_env_coordinator(facility_uuid):
    """facility 에 연결된 env_coordinator CustomController 를 역추적한다.

    복수면 활성 우선.
    """
    from aot.databases.models.controller import CustomController

    matched = []
    try:
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
        matched = [f for f in funcs if _function_belongs_to_facility(f, facility_uuid)]
    except Exception as exc:
        logger.warning('[env_coordinator lookup] %s', exc)
        return None
    if not matched:
        return None
    for f in matched:
        if f.is_activated:
            return f
    return matched[0]
