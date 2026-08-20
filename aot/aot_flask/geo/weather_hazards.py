# coding=utf-8
"""곧 닥칠 기상 위험 — **행동으로 이어지는 것만**.

시설이든 노지든 사람이 오늘 저녁에 무엇을 할지는 "지금 몇 도인가" 보다 "밤에
얼마나 떨어지는가" 가 정한다. 그 판단 재료를 화면이 주지 않으면 사람은 다른
앱을 열어야 한다.

## 제어가 쓰는 것과 **같은 예보**를 읽는다

`forecast.json`(기상청 단기예보) — env_coordinator 의 feedforward 와 AI 도구가
읽는 그 파일이다. 다른 소스를 새로 붙이면 "화면은 서리라는데 제어는 몰랐다" 가
된다.

## 낡은 예보로는 경고하지 않는다

발행 6시간이 지난 예보로 "오늘 밤 서리" 라고 말하면, 사람은 그 말을 믿고
행동한다. 실제로 발행시각이 수개월 지난 설치가 있었다(AI 도구가 그래서 stale 을
함께 반환한다). 낡았으면 **아무 경고도 내지 않고** 그 사실만 돌려준다.

## 임계값은 "판단이 갈리는 지점" 이다

정답이 아니라 **행동이 바뀌는 선**이다. 서리는 0℃가 아니라 2℃부터 본다(지면은
기온보다 낮게 떨어진다). 강풍은 기상특보 기준(14 m/s)보다 낮은 10 m/s부터 본다
— 창을 닫을지 판단하는 선이 그쯤이다.
"""
import logging
import time

logger = logging.getLogger(__name__)

# (종류, 심각도, 임계, 비교방향). 값은 KMA 단기예보 필드.
_RULES = (
    # 얼음: 판단이 아니라 피해다.
    ('freeze',     'severe', 'TMP',  0.0, 'le'),
    ('frost',      'warn',   'TMP',  2.0, 'le'),
    ('heat',       'severe', 'TMP', 35.0, 'ge'),
    ('heat',       'warn',   'TMP', 33.0, 'ge'),
    ('wind',       'severe', 'WSD', 14.0, 'ge'),
    ('wind',       'warn',   'WSD', 10.0, 'ge'),
    ('heavy_rain', 'severe', 'RN1', 10.0, 'ge'),
    ('rain',       'warn',   'RN1',  5.0, 'ge'),
    ('snow',       'warn',   'SNO',  1.0, 'ge'),
)

_UNITS = {'TMP': '°C', 'WSD': 'm/s', 'RN1': 'mm', 'SNO': 'cm'}

# 발행 후 이 시간이 지나면 경고하지 않는다(AI 도구와 같은 기준).
_STALE_HOURS = 6.0
_DEFAULT_WINDOW_H = 24


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def upcoming(hours=_DEFAULT_WINDOW_H):
    """앞으로 `hours` 시간 안의 기상 위험 → dict.

    반환:
      stale        bool   — 예보가 낡아 판정하지 않았다
      age_hours    float|None
      items        [{kind, severity, in_h, value, unit}]  — 종류마다 **가장 이른 것 하나**

    종류마다 하나만 내는 이유: "3시간 뒤 서리, 4시간 뒤 서리, 5시간 뒤 서리" 는
    같은 사실을 세 번 말하는 것이고, 사람이 할 일은 하나다.
    """
    from datetime import datetime

    out = {'stale': False, 'age_hours': None, 'items': []}
    try:
        from aot.functions.utils.env_control.forecast_feedforward import _load_forecast
        data = _load_forecast() or {}
    except Exception as exc:                                # noqa: BLE001
        logger.debug('[hazards] 예보 로드 실패: %s', exc)
        return out
    forecasts = data.get('forecasts') or {}
    if not forecasts:
        return out

    pub = data.get('pub_dt')
    if pub:
        try:
            age = (datetime.now()
                   - datetime.strptime(str(pub), '%Y%m%d%H%M')).total_seconds() / 3600.0
            out['age_hours'] = round(age, 1)
            if age > _STALE_HOURS:
                out['stale'] = True
                return out
        except ValueError:
            pass

    best = {}
    for key, row in forecasts.items():
        try:
            off = int(key)
        except (TypeError, ValueError):
            continue
        if off < 0 or off > hours or not isinstance(row, dict):
            continue
        for kind, severity, field, limit, how in _RULES:
            val = _num(row.get(field))
            if val is None:
                continue
            hit = (val <= limit) if how == 'le' else (val >= limit)
            if not hit:
                continue
            cur = best.get(kind)
            # 더 이른 것이 이긴다. 같은 시각이면 더 심한 쪽.
            if cur is None or off < cur['in_h'] or (
                    off == cur['in_h'] and severity == 'severe'):
                best[kind] = {'kind': kind, 'severity': severity, 'in_h': off,
                              'value': val, 'unit': _UNITS.get(field, '')}
    out['items'] = sorted(best.values(), key=lambda x: (x['in_h'], x['kind']))
    return out


_CACHE = {'ts': 0.0, 'val': None}
_CACHE_TTL = 300.0


def upcoming_cached(hours=_DEFAULT_WINDOW_H):
    """모달이 열릴 때마다 파일을 훑지 않도록 5분 캐시.

    예보는 시간 단위로 갱신되므로 5분 캐시가 판정을 바꾸지 않는다.
    """
    now = time.time()
    if _CACHE['val'] is not None and (now - _CACHE['ts']) < _CACHE_TTL:
        return _CACHE['val']
    val = upcoming(hours)
    _CACHE.update({'ts': now, 'val': val})
    return val
