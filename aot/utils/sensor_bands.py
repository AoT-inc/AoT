# coding=utf-8
"""측정 5단계 밴드 — 지도 라벨 색·구획 카드 적정 구간과 **같은 표**를 서버에서 읽는다.

정본은 화면 쪽 `static/js/common/aot-map-sensor-labels.js` 의 `DEFAULT_RANGES` 와
`bandScale()` 이다(설계 `docs/design/dataviz-primitives.md` 「환경 — 축은 밴드 색과 같은
표에서 온다」). stages 는 각 단계의 **상한**이라(`[s0..s4]`) 적정 구간은 밴드 3 = `s1~s2` 다.
출처는 시설의 `view_options.sensor_ranges`, 없으면 앱 기본값.

여기 숫자를 바꾸면 JS 쪽도 같이 바꿔야 한다 — `test_sensor_bands.py` 가 두 표를 견준다.
적정이라는 말이 성립하는 키(T·RH·VPD, JS `OK_BAND_KEYS`)만 다룬다 — 바람·기압·조도는
세기일 뿐이라 "적정 4–6 m/s" 를 그리면 바람 없는 날이 경고로 뜬다.
"""

#: JS `DEFAULT_RANGES` 의 T·RH·VPD (VPD 는 kPa).
DEFAULT_STAGES = {
    'T': (10, 18, 26, 34, 45),
    'RH': (40, 55, 70, 85, 100),
    'VPD': (0.4, 0.8, 1.2, 1.6, 3.0),
}

#: 밴드 키 → 게이지 쪽 측정 이름(`coordinator_plot.comfort_ranges_for_device` 와 같은 어휘).
MEASUREMENT_OF = {
    'T': 'temperature',
    'RH': 'relative_humidity',
    'VPD': 'vapor_pressure_deficit',
}


def _stages(custom, key):
    """`{key: [5]}`(옛 모양) 또는 `{key: {stages, colors}}` → 숫자 5개 | None."""
    raw = custom.get(key) if isinstance(custom, dict) else None
    if isinstance(raw, dict):
        raw = raw.get('stages')
    if not isinstance(raw, (list, tuple)):
        raw = DEFAULT_STAGES.get(key)
    if not raw or len(raw) < 5:
        return None
    try:
        out = [float(v) for v in raw[:5]]
    except (TypeError, ValueError):
        return None
    return out


def ok_bands(custom=None):
    """시설의 `sensor_ranges`(없으면 None) → `{measurement: (lo, hi)}` — 밴드 3 구간.

    잘못 저장된 키는 그 키만 앱 기본값으로 — JS `_resolveBand` 와 같은 관용이다(JS 는 숫자가
    아닌 단계가 있으면 축을 버리므로, 여기서도 숫자로 못 읽으면 그 키를 버린다)."""
    out = {}
    for key, meas in MEASUREMENT_OF.items():
        s = _stages(custom, key)
        if s is None:
            continue
        lo, hi = s[1], s[2]
        if hi > lo:
            out[meas] = (lo, hi)
    return out
