# -*- coding: utf-8 -*-
"""공통 어휘의 해석 — 설계 docs/design/mcp-domain-surface.md §3.

모델은 일상어로 말한다("토양수분", "rain"). 저장 이름은 드라이버가 정한 것
(`volumetric_water_content`, `length`)이라 일상어로는 못 찾는다 — 리허설 결함 3,
2026-10-14 벤치 f19(soil_moisture → 0건). 대응은 여기 **한 곳**에 둔다. 도구마다
따로 두면 갈라진다.

기간(`period`)도 같다 — 읽기는 정해진 상대 문법을 받고, 여기서 (시작, 끝) 날짜·시각으로
푼다. 쓰기의 절대 시각 확정은 안쪽 도구의 일이다(§3).
"""
from datetime import date, datetime, timedelta

#: 일상어 → 저장 이름 후보(앞의 것부터). 키는 소문자·공백 없이 비교한다.
MEASUREMENT_WORDS = {
    ('temperature', 'temp', '온도', '기온'): ('temperature',),
    ('humidity', 'rh', '습도'): ('humidity',),
    ('soil_moisture', 'soilmoisture', 'moisture', 'vwc', '토양수분', '토양습도',
     '수분'): ('volumetric_water_content',),
    ('vpd', '수증기압차', '포차'): ('vapor_pressure_deficit',),
    ('dewpoint', 'dew', '이슬점'): ('dewpoint',),
    ('rain', 'rainfall', 'precipitation', '비', '강수', '강수량', '강우', '강우량'):
        ('rain', 'precipitation', 'length'),
    ('wind', 'windspeed', 'wind_speed', '풍속'): ('speed',),
    ('wind_direction', 'winddirection', '풍향'): ('direction',),
    ('light', 'solar', 'radiation', 'sunlight', '일사', '일사량', '광량', '조도'):
        ('light', 'radiation'),
    ('pressure', '기압', '압력'): ('pressure',),
    ('co2', '이산화탄소', '탄산가스'): ('co2',),
    ('battery', '배터리', '전압'): ('electrical_potential', 'battery'),
    # 일본어·중국어 — 낱말만 더하면 된다(대조 로직은 언어를 모른다).
    ('温度', '気温', '气温'): ('temperature',),
    ('湿度',): ('humidity',),
    ('土壌水分', '土壤水分', '含水率'): ('volumetric_water_content',),
    ('雨', '降水', '降水量', '降雨'): ('rain', 'precipitation', 'length'),
    ('風速', '风速'): ('speed',),
    ('日射', '日照', '光照', '照度'): ('light', 'radiation'),
}


# ── 이름 대조의 언어 낱말(targets.py §2-1 낱말 대조) ─────────────────────────
#
# 대상 해석은 문법을 풀지 않는다. 물음에서 후보 이름·자리 이름이 나타나는 곳을 찾고,
# **남은 조각이 아래 낱말뿐일 때만** 그 후보로 본다. 그래서 언어를 늘리는 일은 이 표에
# 낱말을 더하는 것이지 해석 로직을 고치는 것이 아니다. 한국어 조사만 코드에 박아 두면
# 띄어쓰기가 없는 일본어·중국어("金堤のバルブ")나 붙여 쓴 말("김제의밸브")에서 낱말이
# 하나로 뭉쳐 그대로 실패한다(2026-10-14 사용자 지적).
#
# 언어와 무관한 길은 따로 있다 — `target` 에 경로("김제 > 밸브")를 실으면 이 표를
# 거치지 않는다. 이 표는 그것을 못 쓴 물음을 받아 주는 보조다.

#: 이어 주는 말 — 조사·전치사·'번' 같은 것. 홀로는 아무것도 가리키지 않는다.
GLUE_WORDS = frozenset({
    # 한국어
    '의', '에', '에서', '에서의', '에있는', '에는', '있는', '안', '안의', '속', '내',
    '번', '호', '및', '과', '와',
    # 일본어
    'の', 'に', 'にある', 'にいる', 'の中', '内', 'での', 'で', '番', '号', 'と',
    # 중국어
    '的', '里', '裡', '在', '中', '内的', '和',
    # 영어
    'in', 'at', 'of', 'on', 'the', 'inside', 'within', 'near', 'no', 'and',
})

#: 물음의 목적을 말할 뿐 대상이 아닌 말("김제 요약").
FILLER_WORDS = frozenset({
    '전체', '모든', '전부', '요약', '상태', '현황', '정보',
    '全体', '全部', '状況', '概要', '状態',
    '状态', '概况', '全部的',
    'all', 'summary', 'status', 'overview',
})

_DEVICE = ('input', 'output', 'device', 'function')

#: 종류 낱말 → 가리키는 종류. 그릇(지도·대지·구역·시설)은 "그 안의 X" 로도 읽힌다.
KIND_WORDS = {
    ('지도', 'map', '地図', 'マップ', '地图'): ('map',),
    ('농장', 'farm', '農場', '农场'): ('map', 'site'),
    ('대지', 'site', '圃場', '敷地', '场地'): ('site',),
    ('구역', 'zone', '区域', 'ゾーン', '分区'): ('zone',),
    ('시설', 'facility', '施設', '设施'): ('facility',),
    ('구획', 'plot', '区画', '地块'): ('plot',),
    ('장치', '기기', 'device', 'devices', '装置', 'デバイス', '機器', '设备', '装置的'):
        _DEVICE,
    ('센서', 'sensor', 'sensors', 'センサー', 'センサ', '传感器'): ('input',),
    ('함수', 'function', 'functions', '関数', '函数'): ('function',),
}


def kind_words():
    """{낱말(소문자): {종류}}."""
    return {w.lower(): set(kinds) for words, kinds in KIND_WORDS.items() for w in words}


def measurement_words():
    """측정 일상어 전체(소문자·공백 없이)."""
    return {w.lower().replace(' ', '') for words in MEASUREMENT_WORDS for w in words}


def _key(word):
    return str(word or '').strip().lower().replace(' ', '').replace('-', '_')


def stored_names():
    from aot.databases.models import DeviceMeasurements
    try:
        return {m for (m,) in DeviceMeasurements.query.with_entities(
            DeviceMeasurements.measurement).distinct().all() if m}
    except Exception:                                       # noqa: BLE001
        return set()


def measurement(word, available=None):
    """일상어 → 이 설치에 있는 저장 이름 하나. 모르는 말이면 그대로(부분일치로 쓰인다)."""
    k = _key(word)
    if not k:
        return word
    available = stored_names() if available is None else available
    if k in {_key(a) for a in available}:
        return word                                         # 이미 저장 이름이다
    for words, names in MEASUREMENT_WORDS.items():
        if k in {_key(w) for w in words}:
            for n in names:
                if n in available:
                    return n
            return names[0]
    return word


def period(text, today=None):
    """기간 문법 → (시작 date, 끝 date) — 둘 다 포함. 못 읽으면 None.

    'today' · 'yesterday' · 'tomorrow' · 'this_week' · 'next_7d' · 'YYYY-MM-DD' ·
    'FROM/TO'(날짜). '24h'·'7d' 같은 지난 기간은 (today-N, today).
    """
    t = str(text or '').strip().lower()
    if not t:
        return None
    today = today or date.today()
    if t in ('today', 'now', '오늘'):
        return today, today
    if t in ('yesterday', '어제'):
        d = today - timedelta(days=1)
        return d, d
    if t in ('tomorrow', '내일'):
        d = today + timedelta(days=1)
        return d, d
    if t in ('this_week', 'week', '이번주', '이번 주'):
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if t.startswith('next_') and t.endswith('d') and t[5:-1].isdigit():
        return today, today + timedelta(days=int(t[5:-1]))
    if t[:-1].isdigit() and t[-1] in 'hd':
        n = int(t[:-1])
        days = n if t[-1] == 'd' else max(1, (n + 23) // 24)
        return today - timedelta(days=days), today
    parts = [p.strip() for p in t.split('/')] if '/' in t else [t]
    try:
        ds = [datetime.fromisoformat(p).date() for p in parts if p]
    except ValueError:
        return None
    if len(ds) == 1:
        return ds[0], ds[0]
    if len(ds) == 2:
        return min(ds), max(ds)
    return None


#: 안쪽 도구가 기간을 받는 모양(registry `Op.period_form`). 공통 낱말 `period` 를 안쪽
#: 인자로 **그대로** 넘기면 안 된다 — 안쪽 인자는 도구마다 모양이 다르다(지난 기간
#: '24h' · 정수 일수 · daily|weekly|monthly · 예보의 시작+시간 수). 2026-10-14 웹 시험:
#: 예보에 hours='tomorrow' 가 그대로 넘어가 "내일" 이 지금부터 24시간이 됐다.
PERIOD_FORMS = ('lookback', 'days', 'span', 'forecast', 'range')

_FORECAST_MAX_HOURS = 336


def period_to(form, text, today=None, now=None):
    """기간 낱말 → 안쪽 인자 값들.

    돌려주는 것: (값 dict, 사람이 읽을 설명). 값 dict 의 키는 역할이다 —
    'value'(인자 하나) 또는 'start'·'hours'(예보). 빈 dict 는 "안쪽 기본값을 쓴다".
    못 읽거나 그 모양으로 나타낼 수 없으면 ValueError(이유).
    """
    t = str(text or '').strip().lower()
    today = today or date.today()
    now = now or datetime.now()
    if form not in PERIOD_FORMS:
        raise ValueError("unknown period form %r" % form)
    if form == 'forecast':
        return _forecast_window(t, today)
    if form == 'range':
        return _date_range(t, today)
    if t in ('', 'now', '지금'):
        return {}, "latest"
    rng = period(t, today=today)
    if rng is None:
        raise ValueError("period not understood")
    start, end = rng
    if start > today:
        raise ValueError("this reads the past — a future period does not fit")
    end = min(end, today)             # '이번 주' 는 오늘까지
    # 지난 기간은 "지금까지 거슬러 N" 으로만 나타낼 수 있다 — 시작일부터 지금까지.
    days = (today - start).days + 1
    if form == 'span':
        return ({'value': 'daily' if days <= 1 else ('weekly' if days <= 7 else 'monthly')},
                "%s to %s" % (start.isoformat(), today.isoformat()))
    if form == 'days':
        return {'value': days}, "%d day(s) back to today" % days
    # lookback — 오늘만이면 자정부터의 시간, 아니면 일수.
    if t[:-1].isdigit() and t[-1] in 'hd':
        return {'value': t}, "last %s" % t
    if days <= 1:
        hours = max(1, now.hour + (1 if now.minute or now.second else 0))
        return {'value': '%dh' % hours}, "since local midnight"
    return {'value': '%dd' % days}, "%s to now" % start.isoformat()


_STAMP = r'\d{4}-\d{2}-\d{2}(?:[t ]\d{2}:\d{2}(?::\d{2})?)?'


def _timed_range(t):
    """'2026-10-28T12:00/2026-10-28T14:00' — 시각이 든 FROM/TO 는 그 시각 그대로 안쪽에 넘긴다.
    날짜로만 풀면 시간대를 물어도 하루 전체가 읽힌다(2026-10-28 점검). 시각이 없으면 None."""
    import re
    m = re.fullmatch(r'(%s)\s*/\s*(%s)?' % (_STAMP, _STAMP), t)
    if not m or not any(re.search(r'[t ]\d{2}:', g or '') for g in m.groups()):
        return None
    return '/'.join((g or '').replace(' ', 'T').replace('t', 'T') for g in m.groups())


def _date_range(t, today):
    """지난 구간 — 날짜가 있으면 start/end(그날 포함), '24h'·'7d' 는 지금까지 거슬러.
    지난주와 이번 주를 나란히 보려면 FROM/TO 를 두 번 준다(2026-10-14 사용자 시험)."""
    if t in ('', 'now', '지금'):
        return {}, "latest"
    if t[:-1].isdigit() and t[-1] in 'hd':
        return {'value': t}, "last %s" % t
    timed = _timed_range(t)
    if timed:
        return {'value': timed}, "%s (clock times kept)" % timed
    rng = period(t, today=today)
    if rng is None:
        raise ValueError("period not understood")
    start, end = rng
    if start > today:
        raise ValueError("this reads the past — a future period does not fit")
    if end >= today:
        return {'value': '%s/' % start.isoformat()}, "%s to now" % start.isoformat()
    return ({'value': '%s/%s' % (start.isoformat(), end.isoformat())},
            "%s to %s (both days included)" % (start.isoformat(), end.isoformat()))


def _forecast_window(t, today):
    if t in ('', 'now', '지금'):
        return {}, "from now (default length)"
    if t[:-1].isdigit() and t[-1] in 'hd':
        n = int(t[:-1]) * (24 if t[-1] == 'd' else 1)
        return {'hours': min(n, _FORECAST_MAX_HOURS)}, "next %s" % t
    if t.startswith('next_') and t.endswith('d') and t[5:-1].isdigit():
        n = int(t[5:-1]) * 24
        return {'hours': min(n, _FORECAST_MAX_HOURS)}, "next %s days" % t[5:-1]
    rng = period(t, today=today)
    if rng is None:
        raise ValueError("period not understood")
    start, end = rng
    if end < today:
        raise ValueError("a forecast is for today or later — this period is past")
    start = max(start, today)
    hours = min(((end - start).days + 1) * 24, _FORECAST_MAX_HOURS)
    word = 'today' if start == today else start.isoformat()
    return {'start': word, 'hours': hours}, "%s to %s" % (start.isoformat(), end.isoformat())


def in_period(value, rng):
    """'2026-10-14T09:00:00+09:00' 같은 값이 (시작, 끝) 날짜 안인가 — 값 자체의 현지 날짜로."""
    if not rng or not value:
        return False
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
    except ValueError:
        try:
            d = date.fromisoformat(str(value)[:10])
        except ValueError:
            return False
    return rng[0] <= d <= rng[1]
