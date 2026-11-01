# coding=utf-8
"""지도 위젯 기상 표현용 레이어 역할(`ambient_role`).

기존 ``options.role``(base/overlay)은 지적도와 구름을 구분하지 못한다. 위젯이 레이어
위치·투명도를 역할로 정하도록 별도 키를 둔다. 값의 해석(위치·투명도 정책)은 프런트
``aot-map-ambient.js`` 가 맡고, 여기서는 이름 집합과 정규화만 정한다.
"""

# 프런트 aot-map-ambient.js 의 ROLES 와 같은 집합이다 (test_map_ambient.py 가 대조한다).
AMBIENT_ROLES = (
    'base',
    'ground.imagery',
    'ground.field',
    'ground.boundary',
    'weather.precip',
    'weather.cloud',
    'weather.field',
    'unknown',
)

AMBIENT_THEMES = ('dark',)

# 역할이 없는 레이어(unknown)를 zIndex 가 이 값 이상이면 도형·3D 모형 위로 본다.
# 값은 여기(서버)서 정하고 레이어 설정(options.ambient_above_z)으로 프런트에 내려보낸다 —
# 프런트 aot-map-ambient.js 에는 이 숫자가 없고, 받은 값만 읽는다. 각 gis-input 모듈은
# 자기 z_index 를 정하고, 필요하면 모듈 INPUT_INFORMATION / 채널 options / 사용자 옵션의
# ``ambient_above_z`` 로 자기 문턱을 따로 둘 수 있다. 서버 기본 z_index 는 1 이다.
AMBIENT_ABOVE_Z_DEFAULT = 10


# 타일 자체의 고유 알파(평균). 원천 타일이 반투명이면(OpenWeather 구름 평균 ≈ 0.38) 정책
# 불투명도를 이만큼 보정해야 의도한 만큼 보인다. 값은 각 gis-input 모듈이 정해
# 레이어 설정(options.ambient_tile_alpha)으로 내려보내고, 프런트는 받은 값만 읽는다.
# 모듈이 말하지 않으면 1(불투명 타일 취급 = 보정 없음). 너무 작으면 보정이 폭주하니 하한을 둔다.
AMBIENT_TILE_ALPHA_DEFAULT = 1.0
AMBIENT_TILE_ALPHA_MIN = 0.1

# 관측값 연출·기상 레이어 자동 켜기의 문턱 — **서버 한 곳**. weather_state 응답이 이 문턱으로
# 판정한 결과(auto_layers, fx.strong_wind)를 내려보내고, 프런트에는 이 숫자가 없다.
AMBIENT_WEATHER_THRESHOLDS = {
    'precip_mm_h': 0.1,        # 15분 강수 환산 ≥ → weather.precip 레이어 자동 켜기
    'cloud_pct': 60.0,         # 운량 ≥ → weather.cloud
    'wind_ms': 8.0,            # 풍속 ≥ → 바람(weather.field 중 wind 계열)
    'strong_wind_ms': 10.8,    # 풍속 ≥ → 바람 흐름선을 호박색으로 (보퍼트 6)
    'calm_ms': 0.3,            # 풍속 < → 고요(보퍼트 0) — 바람 칸이 방향 이름 대신 "고요"를 쓴다
    'lightning_near_km': 8.0,  # 가장 가까운 낙뢰 거리 ≤ → 위험 칸이 "심각"(거리를 모르면 "주의")
}


# 기상 값 표준 키와 단위 — 모든 출처(현장 장치·gis-input)가 이 키·단위로 맞춰 돌려준다.
# gis-input 모듈의 ``get_ambient_values`` 가 이 표를 따른다. 제공자별 환산은 각 모듈 py 안에서 한다.
AMBIENT_ITEM_UNITS = {
    'precip': 'mm/h',
    'wind_speed': 'm/s',
    'wind_dir': '°',
    'cloud': '%',
    'visibility': 'km',
    'temp': '°C',
    # 아래 셋은 선택 키다 — 제공하는 모듈만 채우고, 없으면 그 표현도 없다.
    'precip_type': '',          # 강수 종류 코드(AMBIENT_PRECIP_TYPES). 없으면 화면이 기온으로 눈·비를 짐작한다
    'lightning': 'count',       # 최근 낙뢰 수(집계 창은 모듈이 정한다). 1 이상이면 "낙뢰 있음"
    'lightning_km': 'km',       # 가장 가까운 낙뢰까지의 거리(선택)
}

# 강수 종류 코드 → 이름. 값은 정수 코드로 실어 보낸다(항목 값은 숫자만 받는다).
AMBIENT_PRECIP_TYPES = {1: 'rain', 2: 'snow', 3: 'sleet', 4: 'hail'}


def ambient_source_enabled(options):
    """gis-input 의 저장 옵션(dict)에서 "기상 데이터로 사용"(``use_for_ambient``, 기본 켬)을 읽는다."""
    v = (options or {}).get('use_for_ambient')
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() not in ('false', '0', 'off', 'no', '')
    return bool(v)


AMBIENT_MAX_AGE_RANGE = (10.0, 604800.0)     # 사용자가 gis-input 에 줄 수 있는 지연 문턱(초): 10초~7일


def ambient_max_age_override(options):
    """gis-input 저장 옵션의 ``ambient_max_age``(초) — 비었거나 범위 밖·숫자가 아니면 None(= 모듈 기본값)."""
    v = (options or {}).get('ambient_max_age')
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    lo, hi = AMBIENT_MAX_AGE_RANGE
    return f if f == f and lo <= f <= hi else None


def normalize_ambient_values(raw):
    """gis-input ``get_ambient_values`` 결과를 표준 모양으로 거른다.

    입력: ``{'values': {key: number}, 'at': epoch초|None}`` — 모르는 키·숫자가 아닌 값·불리언은 버린다.
    출력: 같은 모양(값이 하나도 없으면 None). 모듈이 어떤 값을 줘도 여기를 통과해야 응답에 실린다.
    """
    if not isinstance(raw, dict):
        return None
    vals = raw.get('values')
    if not isinstance(vals, dict):
        return None
    out = {}
    for key in AMBIENT_ITEM_UNITS:
        v = vals.get(key)
        if isinstance(v, bool) or v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float('inf'), float('-inf')):
            continue
        if key == 'precip_type':
            f = float(int(round(f)))
            if int(f) not in AMBIENT_PRECIP_TYPES:
                continue
        elif key in ('lightning', 'lightning_km') and f < 0:
            continue
        out[key] = f
    if not out:
        return None
    at = raw.get('at')
    if isinstance(at, bool) or not isinstance(at, (int, float)) or at != at or at <= 0:
        at = None
    res = {'values': out, 'at': float(at) if at is not None else None}
    # 예보를 주는 모듈은 신뢰도(0~1, 선택)를 함께 줄 수 있다 — 관측 값에는 없다.
    conf = normalize_confidence(raw.get('confidence')) if raw.get('confidence') is not None else None
    if conf is not None:
        res['confidence'] = conf
    return res


def normalize_ambient_tile_alpha(value):
    """(AMBIENT_TILE_ALPHA_MIN ~ 1] 로 정규화. 숫자가 아니거나 불리언이면 None."""
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float('inf'), float('-inf')) or v <= 0:
        return None
    return round(min(1.0, max(AMBIENT_TILE_ALPHA_MIN, v)), 3)


def normalize_ambient_role(value):
    """알려진 역할이면 그 문자열, 아니면 None. 빈 값·대소문자·공백을 흡수한다."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in AMBIENT_ROLES else None


def normalize_ambient_theme(value):
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in AMBIENT_THEMES else None


def normalize_ambient_above_z(value):
    """문턱(zIndex) 숫자로 정규화. 숫자가 아니거나 불리언이면 None."""
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float('inf'), float('-inf')):
        return None
    return int(v) if v == int(v) else v


# ── 시간 축(P3) 표준 ─────────────────────────────────────────────────────────
#
# 지도 위젯의 시간 슬라이더가 gis-input 에게 묻는 표준 메서드의 입출력 규격이다. 모든 시각은 epoch 초(UTC).
# 제공자 이름·지역·외부 API 는 각 gis 모듈 py 안에서만 안다 — 공통 코드(슬라이더 본체·weather_state)는
# 이 규격으로 돌려받은 값만 쓴다.
#
#   타일 레이어(time_enabled)      get_time_range() / get_time_steps() / get_time_params(t)
#   예보 값                       get_ambient_forecast_range() / get_ambient_forecast(lat, lng, t)
#   관측 이력 값                  get_ambient_history_range()  / get_ambient_history(lat, lng, t)

TIME_FRAMES_MAX = 400          # 한 레이어가 슬라이더에 올릴 수 있는 프레임 수 상한(예: 48 h × 10분 = 288)


def _epoch(value):
    """숫자(불리언 제외)·유한한 양수면 float, 아니면 None."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float('inf'), float('-inf')) and f > 0 else None


def normalize_time_range(raw):
    """``{'start': epoch초, 'end': epoch초}`` 로 거른다. 순서가 뒤집혔거나 숫자가 아니면 None."""
    if not isinstance(raw, dict):
        return None
    start, end = _epoch(raw.get('start')), _epoch(raw.get('end'))
    if start is None or end is None or end < start:
        return None
    return {'start': start, 'end': end}


def normalize_time_steps(raw, rng=None):
    """눈금 → 오름차순·중복 없는 epoch 초 목록. ``[…]`` 또는 ``{'every_s': n}`` (``rng`` 안에서 start + k·n).

    눈금이 없거나 이상하면 None. ``TIME_FRAMES_MAX`` 를 넘으면 앞쪽부터 자른다(과한 응답 방지).
    """
    steps = None
    if isinstance(raw, dict):
        every = _epoch(raw.get('every_s'))
        if every is not None and every >= 1.0 and rng:
            steps = []
            t = rng['start']
            while t <= rng['end'] + 1e-6 and len(steps) < TIME_FRAMES_MAX:
                steps.append(t)
                t += every
    elif isinstance(raw, (list, tuple)):
        steps = sorted({_epoch(v) for v in raw if _epoch(v) is not None})
    if not steps:
        return None
    return steps[:TIME_FRAMES_MAX]


def normalize_time_params(raw):
    """프레임 파라미터 → ``{자리표시자 이름: 문자열}``. 사전이 아니면 None(= 그 시각의 프레임 없음).

    이름은 URL 템플릿의 ``{이름}`` 자리와 같다(슬라이더는 이 쌍을 템플릿에 끼우기만 한다).
    """
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, v in raw.items():
        if isinstance(k, str) and k and isinstance(v, (str, int, float)) and not isinstance(v, bool):
            out[k] = str(v)
    return out


def normalize_forecast_range(raw):
    """예보·이력 범위 → ``{'start', 'end', 'step_s'}`` (epoch 초, 눈금 간격 초). 이상하면 None."""
    rng = normalize_time_range(raw)
    if not rng:
        return None
    step = _epoch(raw.get('step_s'))
    rng['step_s'] = step if step is not None and step >= 1.0 else 3600.0
    return rng


def normalize_confidence(value):
    """0~1 신뢰도. 숫자가 아니면 None."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(min(1.0, max(0.0, f)), 3)
