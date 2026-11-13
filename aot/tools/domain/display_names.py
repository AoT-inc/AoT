# -*- coding: utf-8 -*-
"""측정 이름·단위의 표시용 이름표 — 응답에 `measurement_label` / `unit_label` 로 함께 싣는다.

응답의 `measurement`(`vapor_pressure_deficit`)와 `unit`(`percent`, `C`)은 저장 이름이라 기계가 읽는 값이다.
AI 가 그대로 베껴 사용자 카드에 "vapor_pressure_deficit 0.2 kPa" 로 쓰는 일이 있었다(온도·습도는 AI 가 알아서
번역한다). 사람이 읽는 이름은 서버가 같이 내린다. 기존 키는 그대로 두어 호환을 지킨다.

이름은 새로 짓지 않는다 — 정본은 `MEASUREMENTS` / `UNITS`(`config_devices_units.py`)이고, 일지가 이미 쓰는
`measurement_label` / `unit_label`(`geo/plot_journal/calc.py`)을 그대로 부른다. 필드 이름도 일지와 같다
(같은 개념에 도구마다 다른 이름을 두지 않는다). 다르면 실을 뿐이다: 라벨이 키와 같으면(`kPa`, `speed` 가 아닌 것)
생략한다 — 없으면 원래 값을 쓰면 된다.

토양은 맥락이 이름을 바꾼다 — 같은 `temperature` 도 흙에서는 "토양 온도", `volumetric_water_content` 는 "토양 수분"
(체적 수분 함량은 농부의 말이 아니다). 맥락은 부모 칸에서 온다(`medium: soil` 그룹, 개요의 `soil` 칸).
"""
from flask_babel import gettext

#: 이름표를 더하는 안쪽 도구 — 측정 이름·단위를 응답에 싣는 읽기. 도메인 표면(overview.place · measure.latest …)과 인앱 AI 가
#: 같은 도구를 지나므로 실행층 한 곳(`tool_execution._execute_tool`)에서 더한다.
TOOLS = frozenset({
    'get_place_overview', 'get_zone_sensor_summary', 'get_sensor_reading', 'get_sensor_detail',
    'get_device_measurements', 'get_device_freshness',
})

#: 흙에서만 바꿔 부르는 이름 — 이름 자체는 화면과 같은 번역 문구(`Soil Temperature`, `Soil Moisture`)다.
_SOIL_NAMES = {
    'temperature': 'Soil Temperature',
    'volumetric_water_content': 'Soil Moisture',
}

#: 응답이 사용자의 물음을 되비추는 칸 — 거기의 `measurement` 는 데이터가 아니라 물은 말이다.
_ECHO_KEYS = frozenset({'read_as', 'next', 'request', 'asked', 'arguments'})


def _say(text):
    try:
        return gettext(text)
    except Exception:                                       # noqa: BLE001 — 문맥이 없으면 원문
        return text


def names(measurement, unit=None, soil=False):
    """(측정 이름표, 단위 기호) — 키와 같거나 모르면 해당 칸은 None(실을 것이 없다)."""
    from aot.aot_flask.geo.plot_journal.calc import measurement_label, unit_label
    label = sym = None
    m = str(measurement or '')
    if m:
        if soil and m in _SOIL_NAMES:
            label = _say(_SOIL_NAMES[m])
        elif m == 'volumetric_water_content':
            label = _say(_SOIL_NAMES[m])        # 이 측정은 흙에서만 나온다
        else:
            label = measurement_label(m)
        if not label or label == m:
            label = None
    u = str(unit) if isinstance(unit, str) else ''
    if u:
        sym = unit_label(u)
        if not sym or sym == u:
            sym = None
    return label, sym


def _row(d, soil):
    """`measurement`(+`unit`)를 가진 한 칸에 이름표를 더한다."""
    m = d.get('measurement')
    if not isinstance(m, str) or not m:
        return False
    return _put(d, *names(m, d.get('unit'), soil))


def _put(d, label, sym):
    added = False
    if label and 'measurement_label' not in d:
        d['measurement_label'] = label
        added = True
    if sym and 'unit_label' not in d:
        d['unit_label'] = sym
        added = True
    return added


def _walk(node, soil=False):
    """고친 칸 수."""
    if isinstance(node, list):
        return sum(_walk(v, soil) for v in node)
    if not isinstance(node, dict):
        return 0
    soil = soil or node.get('medium') == 'soil'
    n = 1 if _row(node, soil) else 0
    return n + sum(_walk(v, soil) for k, v in node.items() if k not in _ECHO_KEYS)


def _sensor_block(block, soil=False):
    """개요 `sensors` — 측정 이름이 키이고 값이 `{avg, unit, n …}` 인 사전. `outdoor` / `soil` 은 같은 모양의 칸이다."""
    n = 0
    for key, row in block.items():
        if not isinstance(row, dict):
            continue
        if key in ('outdoor', 'soil') and 'avg' not in row:
            n += _sensor_block(row, soil or key == 'soil')
            continue
        n += _put(row, *names(key, row.get('unit'), soil))
    return n


def _name_maps(body):
    """농장 전체 한 줄 요약처럼 측정 이름이 키이고 단위가 따로(`units`) 있는 모양 — 이름표 사전을 곁에 둔다."""
    units = body.get('units')
    if not isinstance(units, dict) or not units or 'measurement_labels' in body:
        return False
    labels, syms = {}, {}
    for m, u in units.items():
        label, sym = names(m, u)
        if label:
            labels[m] = label
        if sym:
            syms[m] = sym
    if labels:
        body['measurement_labels'] = labels
    if syms:
        body['unit_labels'] = syms
    return bool(labels or syms)


def add_localised(app, user_id, body):
    """`add` 를 그 사용자의 언어로 돌린다 — MCP 컨테이너에는 요청 로케일이 없어 그냥 부르면 영어 이름표가 나온다."""
    from aot.tools.domain.server_card import in_user_locale
    return in_user_locale(app, user_id, lambda: add(body))


def add(body):
    """응답 본문(사전)을 제자리에서 고친다. 고쳤으면 True."""
    if not isinstance(body, dict) or body.get('status') == 'error':
        return False
    sensors = body.get('sensors')
    n = _sensor_block(sensors) if isinstance(sensors, dict) else 0
    n += 1 if _name_maps(body) else 0
    return (n + _walk(body)) > 0
