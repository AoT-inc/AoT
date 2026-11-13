# coding=utf-8
"""측정 키 → 사람이 읽는 이름 (아키텍처 4c-1, `docs/design/space-domain-package.md`).

지도 위젯(`aot.aot_flask.geo.widget.maps`)에 있던 함수를 그대로 옮겼다. 장치 소속
후보 목록(`device_membership`)도 같은 이름을 쓰는데, 위젯 모듈은 웹·AI 에 깊게 닿아
공간 도메인으로 옮기지 않는다. 그래서 순수 계산인 이 함수만 아래로 내리고,
위젯은 이것을 다시 가져간다.
"""


def _measurement_display_name(measurement_key):
    """측정 키 → 사람이 읽는 이름. 모르는 키면 `None`(호출부가 폴백한다).

    정본은 `MEASUREMENTS`(`config_devices_units.py`) 하나다 — 화면마다 자기
    이름표를 들면 같은 값이 자리마다 다른 이름으로 보인다.

    ⚠ `MEASUREMENTS` 의 이름은 `lazy_gettext` 객체다. **참/거짓으로 평가하지
      말 것** — 그 순간 `__len__` → `str()` 이 불려 번역이 강제되고, 요청
      컨텍스트가 없으면 거기서 예외가 난다. `is None` 으로만 본다.
    """
    if not measurement_key:
        return None
    try:
        from aot.config_devices_units import MEASUREMENTS
        entry = MEASUREMENTS.get(str(measurement_key))
        if entry is None:
            return None
        name = entry.get('name')
        if name is None:
            return None
        return str(name) or None
    except Exception:
        # 이름을 못 얻는 것이 지도를 못 그릴 이유는 아니다 — 호출부가
        # 원문 키로 폴백한다.
        return None
