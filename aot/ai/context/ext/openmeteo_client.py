# coding=utf-8
"""
openmeteo_client.py — Open-Meteo: 전세계 기상·토양·증발산 (EXT-GL-02).

## 왜 붙였는가 — 실제로 비어 있던 세 자리

  1. **한국 밖에는 예보가 없었다.** `get_weather_forecast` 는 기상청 단기예보
     (forecast.json) 하나뿐이다. AoT 는 22개 언어로 나가는데, 한국 밖 설치는
     "곧 기온이 떨어지니 미리 보온하라" 같은 선제 조언을 아예 못 한다.
  2. **기상대가 없는 농가는 빈손이었다.** `get_weather` 는 외부 API 를 부르지
     않고 AoT 자신의 InfluxDB 센서만 읽는다(WEATHER_TOOL_ENTRY 주석 참조).
     기상 Input 을 안 꽂았으면 돌려줄 것이 없다.
  3. **토양 온도·수분과 기준증발산량 ET0 는 어느 경로로도 없었다.** 물리
     센서를 꽂은 곳만 알 수 있었고, 그나마 ET0 는 계산해 주는 곳이 없었다.

Open-Meteo 는 셋을 한 번에 메운다 — 전세계, 키 없이, 좌표만으로.

## 왜 농업 MCP 서버를 붙이지 않고 원본을 직접 불렀는가

조사한 농업 MCP 서버(etudelab/agri-weather-mcp 별 0개·커밋 6개,
AiAgentKarl/agriculture-mcp-server 별 1개)는 전부 **이 API 의 얇은 래퍼**다.
원본을 직접 부르면 그 저장소들의 수명에 의존하지 않고, 무엇보다 **내장 AI 와
MCP 클라이언트가 같은 것을 쓴다** — 외부 MCP 서버로 붙였다면 MCP 로 접속한
LLM 만 혜택을 봤을 것이다(내장 AI 는 MCP 클라이언트가 아니다).

## 라이선스 — 무료 엔드포인트는 비상업 전용이다

api.open-meteo.com 은 약관상 **비상업 이용 전용**이고(예시로 "구독·광고가 없는
개인/비영리 사이트", "개인 홈오토메이션" 을 든다), 자료는 CC BY 4.0 이라 출처를
표시해야 한다. 한도는 600회/분·5,000회/시·10,000회/일.

상업 농가는 유료 키를 받아 customer-api.open-meteo.com 을 쓴다. 그래서 키를
**선택 항목**으로 두고, 키가 있으면 상업 엔드포인트로 보낸다. AoT 가 어느
쪽인지 대신 판단하지 않는다 — 설치 운영자가 안다. 이 파일이 하는 일은 그
선택을 표현할 수단을 주는 것뿐이다.

## 응답 모양 — 열 배열을 행으로 뒤집는다

Open-Meteo 는 `{"hourly": {"time": [...], "temperature_2m": [...]}}` 처럼
**열 단위 배열**로 준다. 그대로 넘기면 모델이 인덱스를 맞춰 읽어야 하고 그건
틀린다. 여기서 행으로 전치하고, **단위를 키 이름에 박는다**
(`soil_moisture_3_to_9cm (m³/m³)`) — 수분 0.268 을 26.8% 로 읽는 사고가
단위 없이는 반드시 난다.
"""
import logging

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 20

_FORECAST_BASE = 'https://api.open-meteo.com/v1/forecast'
_ARCHIVE_BASE = 'https://archive-api.open-meteo.com/v1/archive'
# 유료 키가 있을 때만 쓴다. 경로는 같고 호스트만 다르다.
_COMMERCIAL_HOST = 'https://customer-api.open-meteo.com'
_FREE_HOST = 'https://api.open-meteo.com'
_ARCHIVE_FREE_HOST = 'https://archive-api.open-meteo.com'


# 모든 오퍼레이션이 좌표를 요구한다. 소스 설정에 농장 좌표를 넣어 두면
# data_source_query_service.query() 가 기본값으로 채우므로, 모델이 매번
# 위경도를 적을 필요는 없다 — 다른 지점을 물을 때만 넘긴다.
OPERATIONS = {
    'forecast_daily': {
        'base': _FORECAST_BASE,
        'block': 'daily',
        'vars': ['temperature_2m_max', 'temperature_2m_min', 'precipitation_sum',
                 'precipitation_probability_max', 'et0_fao_evapotranspiration',
                 'shortwave_radiation_sum', 'wind_speed_10m_max'],
        'category': '예보',
        'label_ko': '일별 예보(최고·최저기온, 강수, ET0, 일사)',
        'params': ['latitude', 'longitude'],
        'optional': {'forecast_days': '7'},
    },
    'forecast_hourly': {
        'base': _FORECAST_BASE,
        'block': 'hourly',
        'vars': ['temperature_2m', 'relative_humidity_2m', 'dew_point_2m',
                 'vapour_pressure_deficit', 'precipitation', 'wind_speed_10m',
                 'shortwave_radiation'],
        'category': '예보',
        'label_ko': '시간별 예보(기온·습도·VPD·강수) — 선제 제어용',
        'params': ['latitude', 'longitude'],
        'optional': {'forecast_days': '2'},
        # 48시간을 시간마다 주면 48행이고, 조회 상한(25행)에 걸려 **오늘까지만**
        # 남는다 — "내일 아침 추워지나" 가 정확히 잘려 나가는 자리다. 3시간
        # 간격으로 솎으면 이틀치가 16행에 들어간다. 농업 조언에 필요한 것은
        # 시간 단위 해상도가 아니라 이틀치 추세다.
        'client_optional': {'step': '3'},
    },
    'soil': {
        'base': _FORECAST_BASE,
        'block': 'hourly',
        'vars': ['soil_temperature_0cm', 'soil_temperature_6cm',
                 'soil_temperature_18cm', 'soil_temperature_54cm',
                 'soil_moisture_0_to_1cm', 'soil_moisture_3_to_9cm',
                 'soil_moisture_9_to_27cm', 'soil_moisture_27_to_81cm'],
        'category': '토양',
        'label_ko': '토양 깊이별 온도·수분(0/6/18/54cm)',
        'params': ['latitude', 'longitude'],
        'optional': {'forecast_days': '2'},
        'client_optional': {'step': '3'},
    },
    'climate_history': {
        'base': _ARCHIVE_BASE,
        'block': 'daily',
        'vars': ['temperature_2m_max', 'temperature_2m_min', 'precipitation_sum',
                 'et0_fao_evapotranspiration'],
        'category': '기후',
        'label_ko': '과거 기후 — 기간을 월별로 집계',
        'params': ['latitude', 'longitude', 'start_date', 'end_date'],
        # 날짜 하나하나가 아니라 월별 집계로 돌려준다 — 아래 _aggregate_monthly
        # 의 이유 참조.
        'aggregate': 'monthly',
    },
}


def operations_for_preset(preset_key=None):
    return OPERATIONS


def _host_for(base, api_key):
    """유료 키가 있으면 상업 호스트로 보낸다(§라이선스)."""
    if not api_key:
        return base
    if base.startswith(_ARCHIVE_FREE_HOST):
        return base.replace(_ARCHIVE_FREE_HOST, _COMMERCIAL_HOST, 1)
    return base.replace(_FREE_HOST, _COMMERCIAL_HOST, 1)


def build_request(op_key, params, operations=None):
    """(url, query_dict) 를 만든다. 필수 파라미터가 비면 ValueError,
    모르는 오퍼레이션이면 KeyError — smartfarmkorea_client.build_url 과 같은
    오류 계약이라 호출부가 한 갈래로 처리한다."""
    operations = operations if operations is not None else OPERATIONS
    op = operations[op_key]

    missing = [p for p in op['params'] if not str(params.get(p, '') or '').strip()]
    if missing:
        raise ValueError("missing required param(s) for %s: %s" % (op_key, ', '.join(missing)))

    api_key = str(params.get('apikey', '') or '').strip()
    query = {
        'latitude': str(params['latitude']).strip(),
        'longitude': str(params['longitude']).strip(),
        op['block']: ','.join(op['vars']),
        # 현지 시각으로 돌려받는다. UTC 로 받으면 "내일 아침" 이 어긋난다.
        'timezone': 'auto',
    }
    for name, default in (op.get('optional') or {}).items():
        val = str(params.get(name, '') or '').strip() or default
        query[name] = val
    # client_optional 은 우리가 응답을 다듬을 때만 쓰는 값이다. 질의문자열에
    # 섞으면 Open-Meteo 가 모르는 파라미터로 400 을 돌려준다.
    for name in ('start_date', 'end_date'):
        if name in op['params']:
            query[name] = str(params[name]).strip()
    if api_key:
        query['apikey'] = api_key

    return _host_for(op['base'], api_key), query


def _rows_from_block(payload, block):
    """열 배열 → 행. 단위는 키 이름에 박는다(모듈 주석 §응답 모양)."""
    data = payload.get(block) or {}
    units = payload.get(block + '_units') or {}
    times = data.get('time') or []
    if not times:
        return []

    keys = [k for k in data.keys() if k != 'time']
    rows = []
    for i, t in enumerate(times):
        row = {'time': t}
        for k in keys:
            series = data.get(k) or []
            if i >= len(series):
                continue
            val = series[i]
            if val is None:
                continue
            unit = units.get(k)
            row[('%s (%s)' % (k, unit)) if unit else k] = val
        rows.append(row)
    return rows


def _sample(rows, step):
    """n행마다 하나씩. 마지막 행은 항상 남긴다 — 기간의 끝을 잘라 버리면
    "모레까지 비" 가 "내일까지 비" 로 바뀐다."""
    try:
        step = max(1, int(step))
    except (TypeError, ValueError):
        step = 1
    if step == 1 or len(rows) <= 2:
        return rows
    out = rows[::step]
    if rows[-1] not in out:
        out.append(rows[-1])
    return out


def _aggregate_monthly(rows):
    """일별 행을 월별로 접는다.

    과거 기후를 **날짜별로** 돌려주면 한 해가 365행이고, 조회 상한(25행)에
    걸려 앞 25일만 남는다. 그러면 모델은 9월 상순만 보고 "9월은 이렇다" 고
    말한다 — 잘렸다는 표시가 있어도 그 표시가 답을 고쳐 주지는 않는다.

    실제 물음은 "작년 이맘때 어땠나", "여기 서리가 언제 오나" 이고 그건 월별
    집계로 답이 된다. 평균만이 아니라 **최저기온의 최저값과 영하일수**를 함께
    내는 이유는, 월평균 최저기온이 영상이어도 서리는 내리기 때문이다.
    """
    buckets = {}
    order = []
    for row in rows:
        month = str(row.get('time', ''))[:7]
        if len(month) != 7:
            continue
        if month not in buckets:
            buckets[month] = {'tmax': [], 'tmin': [], 'precip': [], 'et0': []}
            order.append(month)
        b = buckets[month]
        for key, slot in (('temperature_2m_max', 'tmax'), ('temperature_2m_min', 'tmin'),
                          ('precipitation_sum', 'precip'), ('et0_fao_evapotranspiration', 'et0')):
            for k, v in row.items():
                if k.split(' (')[0] == key and isinstance(v, (int, float)):
                    b[slot].append(v)
                    break

    def _avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    out = []
    for month in order:
        b = buckets[month]
        rec = {'month': month, 'days': len(b['tmax'])}
        if b['tmax']:
            rec['mean_tmax (°C)'] = _avg(b['tmax'])
            rec['max_tmax (°C)'] = round(max(b['tmax']), 1)
        if b['tmin']:
            rec['mean_tmin (°C)'] = _avg(b['tmin'])
            # 서리 판단은 평균이 아니라 이 두 값으로 한다.
            rec['min_tmin (°C)'] = round(min(b['tmin']), 1)
            rec['days_below_0C'] = sum(1 for v in b['tmin'] if v < 0)
        if b['precip']:
            rec['precip_total (mm)'] = round(sum(b['precip']), 1)
        if b['et0']:
            rec['et0_total (mm)'] = round(sum(b['et0']), 1)
        out.append(rec)
    return out


def fetch_operation(op_key, params, operations=None):
    """한 오퍼레이션을 조회한다. (records, error) 를 돌려주고 절대 raise 하지
    않는다 — smartfarmkorea_client.fetch_operation 과 같은 계약이라
    data_source_query_service 가 두 소스 계열을 한 갈래로 다룬다.

    첫 행은 **어느 격자가 답했는지**다(grid_latitude/elevation_m). Open-Meteo
    는 요청 좌표에서 가장 가까운 격자점으로 답하므로, 산지에서는 표고가 수백
    미터 어긋날 수 있다. 그걸 감추면 모델이 산 위 농장에 평지 기온을 그대로
    적용한다.
    """
    operations = operations if operations is not None else OPERATIONS
    try:
        url, query = build_request(op_key, params, operations=operations)
    except (KeyError, ValueError) as e:
        return None, str(e)

    try:
        resp = requests.get(url, params=query, timeout=_REQUEST_TIMEOUT)
        # 오류도 JSON 으로 이유를 준다(400 + {"reason": "..."}) — 그 이유가
        # 상태코드보다 훨씬 쓸모 있으므로 raise_for_status 보다 먼저 읽는다.
        try:
            payload = resp.json()
        except ValueError:
            resp.raise_for_status()
            return None, "%s returned non-JSON response" % op_key
        if isinstance(payload, dict) and payload.get('error'):
            return None, "%s: %s" % (op_key, payload.get('reason') or 'request rejected')
        resp.raise_for_status()
    except requests.RequestException as e:
        return None, "%s request failed: %s" % (op_key, e)

    op = operations[op_key]
    rows = _rows_from_block(payload, op['block'])
    if op.get('aggregate') == 'monthly':
        rows = _aggregate_monthly(rows)
    elif op.get('client_optional', {}).get('step'):
        rows = _sample(rows, str(params.get('step', '') or '').strip()
                       or op['client_optional']['step'])

    head = {
        'grid_latitude': payload.get('latitude'),
        'grid_longitude': payload.get('longitude'),
        'elevation_m': payload.get('elevation'),
        'timezone': payload.get('timezone'),
    }
    return [head] + rows, None
