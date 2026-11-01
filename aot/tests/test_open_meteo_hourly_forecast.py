# coding=utf-8
"""OPEN_METEO_HOURLY_FORECAST — 몇 시간 뒤 예보 입력 (설계안 PR 1).

지키는 것
  ① 리드 정의: 순간값은 now+L 앞뒤 정시 보간, 칸 값은 ceil(now+L) 정시 행.
  ② 창 집계(0~window_h)와 결측 — 값이 없으면 쓰지 않는다(0.0 으로 채우지 않음).
  ③ 요청 파라미터(단위·UTC epoch·forecast_hours)와 429 공유(양방향).
  ④ 시간열 파일: 스키마, 원자적 쓰기, 디렉터리 자동 생성, 기존 소비처가 그대로 읽음.
  ⑤ 기존 OPEN_METEO_FORECAST 불변(스냅샷) · 강우 단위표 · model_input_drivers.

네트워크·DB·create_app 없음 — 고정 응답과 가짜 requests.get 만 쓴다.
"""
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import aot.inputs.open_meteo_hourly_forecast as hf
import aot.inputs.open_meteo_weather as live

# 2026-10-13 05:00:00 UTC (정시). 모든 보간 시험이 이 기준을 쓴다.
T0 = int(datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc).timestamp())
H = 3600
# 입력 id — 파일 이름에 들어가므로 uuid 형식이어야 한다(forecast_file_path 가 검사).
IN_UUID = '5f0c2a8e-3b1d-4c7a-9e2f-6a4b8d1c0e93'
FILE_NAME = 'forecast_%s.json' % IN_UUID


def _rows(start_off=-1, hours=50, **fn):
    """T0+off*H 행 — 변수별 값은 fn[var](off) 로 만든다."""
    rows = {}
    for off in range(start_off, start_off + hours):
        rows[T0 + off * H] = {var: f(off) for var, f in fn.items()
                              if f(off) is not None}
    return rows


# 기온 = 10+off(선형), 강수 = off(그 칸까지 1h 합), POP = 10*off, 풍속 = 2+off%3
_BASE = dict(
    temperature_2m=lambda o: 10.0 + o,
    relative_humidity_2m=lambda o: 50.0 + o,
    precipitation=lambda o: float(o),
    precipitation_probability=lambda o: 10.0 * o,
    wind_speed_10m=lambda o: 2.0 + (o % 3),
    cloud_cover=lambda o: 5.0 * o,
    shortwave_radiation=lambda o: 100.0 * o,
)

_CH = {  # 채널 번호 — 레이아웃 고정
    'T1': 0, 'RH1': 1, 'RN1': 2, 'POP1': 3, 'WS1': 4, 'CLD1': 5, 'SOL1': 6,
    'T3': 7, 'RN3': 9, 'T6': 14, 'RN6': 16, 'SOL6': 20,
    'TMAX': 21, 'TMIN': 22, 'RHMAX': 23, 'WSMAX': 24, 'RNMAX': 25,
    'POPMAX': 26, 'DUR': 27,
}


class TestLeadDefinition:
    def test_정시_정각이면_행_값_그대로(self):
        v = hf.channel_values(_rows(**_BASE), T0, 3)
        # 순간값: now+1h = 정시 → 그 행
        assert v[_CH['T1']] == 11.0 and v[_CH['T3']] == 13.0 and v[_CH['T6']] == 16.0
        # 칸 값: ceil(now+L) = 정시 행 자체
        assert v[_CH['RN1']] == 1.0 and v[_CH['RN3']] == 3.0 and v[_CH['RN6']] == 6.0
        assert v[_CH['POP1']] == 10.0 and v[_CH['SOL6']] == 600.0

    def test_정시_59분이면_순간값은_보간_칸_값은_다음_정시(self):
        now = T0 + 59 * 60
        v = hf.channel_values(_rows(**_BASE), now, 3)
        # now+1h = 05:59 + 1h = 06:59 → 기온은 06:00(16) 과 07:00(17) 사이 59/60
        assert v[_CH['T1']] == pytest.approx(10.0 + 1 + 59 / 60, abs=1e-3)
        # 칸 값은 06:59 를 포함하는 칸 = 07:00 행(off=2)
        assert v[_CH['RN1']] == 2.0
        assert v[_CH['T6']] == pytest.approx(10.0 + 6 + 59 / 60, abs=1e-3)
        assert v[_CH['RN6']] == 7.0

    def test_정시_1초_뒤도_칸_값은_다음_정시(self):
        v = hf.channel_values(_rows(**_BASE), T0 + 1, 3)
        assert v[_CH['RN1']] == 2.0           # ceil(06:00:01) = 07:00

    def test_UTC_자정_직전과_직후(self):
        mid = int(datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc).timestamp())
        rows = {}
        for off in range(-1, 12):
            ts = mid + off * H
            rows[ts] = {'temperature_2m': float(off), 'precipitation': float(off)}
        before = hf.channel_values(rows, mid - 30 * 60, 3)    # 23:30
        after = hf.channel_values(rows, mid + 30 * 60, 3)     # 00:30
        assert before[_CH['T1']] == pytest.approx(0.5)        # 00:30 보간
        assert before[_CH['RN1']] == 1.0                      # 00:30 을 포함하는 칸 = 01:00
        assert after[_CH['T1']] == pytest.approx(1.5)
        assert after[_CH['RN1']] == 2.0

    def test_이웃_행이_비면_순간값은_없다(self):
        rows = _rows(**_BASE)
        del rows[T0 + 2 * H]                  # 07:00 행 없음
        v = hf.channel_values(rows, T0 + 30 * 60, 3)
        # now+1h=06:30 은 06:00·07:00 사이 → 07:00 없음 → 기온 +1h 없음
        assert _CH['T1'] not in v
        # 칸 값 ceil(06:30)=07:00 도 없음
        assert _CH['RN1'] not in v
        assert _CH['T3'] in v                 # 다른 리드는 영향 없음

    def test_정의가_파일_메타와_코드_주석에_있다(self):
        assert 'lead_definition' in hf.build_forecast_file(
            _rows(**_BASE), T0, {})
        assert 'ceil(now+L)' in hf.__doc__ and '직선 보간' in hf.__doc__


class TestWindow:
    def test_창_안에서만_집계하고_지난_칸은_뺀다(self):
        rows = _rows(**_BASE)
        v = hf.channel_values(rows, T0 + 30 * 60, 3)          # 05:30, 창 05:30~08:30
        # 기온: now 보간 10.5, now+3h(08:30) 보간 13.5, 06~08시 행 11..13
        assert v[_CH['TMAX']] == pytest.approx(13.5)
        assert v[_CH['TMIN']] == pytest.approx(10.5)          # 05:00(10) 은 지난 시각
        # 시간당 강수: 05:00 행(이미 끝난 칸)은 뺀다.
        # 겹치는 칸: now < ts < now+W+3600 → 06:00..09:00 (off 1..4) → 최대 4
        assert v[_CH['RNMAX']] == 4.0
        assert v[_CH['POPMAX']] == 40.0
        assert v[_CH['DUR']] == 3.0

    def test_정각_창은_방금_끝난_칸을_넣지_않는다(self):
        v = hf.channel_values(_rows(**_BASE), T0, 3)
        # 칸: now < ts < now+3h+1h → off 1..3 (off 0 은 방금 끝난 칸, off 4 는 창 밖)
        # 정각이면 ts < end+3600 이므로 off 1..3 까지(4 는 경계 제외)
        assert v[_CH['RNMAX']] == 3.0
        assert v[_CH['TMIN']] == 10.0                         # now 정각 값은 포함
        assert v[_CH['TMAX']] == 13.0

    def test_window_h_가_길이를_바꾼다(self):
        v1 = hf.channel_values(_rows(**_BASE), T0, 1)
        v6 = hf.channel_values(_rows(**_BASE), T0, 6)
        assert v1[_CH['TMAX']] == 11.0 and v6[_CH['TMAX']] == 16.0
        assert v1[_CH['DUR']] == 1.0 and v6[_CH['DUR']] == 6.0

    def test_창_밖_값은_영향이_없다(self):
        rows = _rows(**_BASE)
        rows[T0 + 20 * H]['temperature_2m'] = 99.0
        rows[T0 - 1 * H]['temperature_2m'] = -99.0
        v = hf.channel_values(rows, T0 + 30 * 60, 3)
        assert v[_CH['TMAX']] < 50 and v[_CH['TMIN']] > -50


class TestMissingIsNotZero:
    def test_변수가_통째로_없으면_그_채널만_없다(self):
        base = dict(_BASE)
        del base['precipitation_probability']
        v = hf.channel_values(_rows(**base), T0, 3)
        assert _CH['POP1'] not in v and _CH['POPMAX'] not in v
        assert _CH['T1'] in v and _CH['RN1'] in v

    def test_None_값은_건너뛴다(self):
        rows = _rows(**_BASE)
        rows[T0 + 1 * H].pop('precipitation')
        v = hf.channel_values(rows, T0, 3)
        assert _CH['RN1'] not in v                           # 0.0 으로 채우지 않는다
        assert v[_CH['RNMAX']] == 3.0                        # 다른 칸으로 계산

    def test_rows_from_hourly_가_None_문자열_비정시를_거른다(self):
        rows = hf.rows_from_hourly({
            'time': [T0, T0 + H, T0 + H + 1, 'x', T0 + 2 * H],
            'temperature_2m': [1.0, None, 3.0, 4.0, float('nan')],
            'weather_code': [2, 3, 4, 5, 6]})
        assert rows[T0] == {'temperature_2m': 1.0, 'weather_code': 2.0}
        assert 'temperature_2m' not in rows[T0 + H]
        assert 'temperature_2m' not in rows[T0 + 2 * H]
        assert T0 + H + 1 not in rows

    def test_전부_비면_창_채널이_없고_길이만_남는다(self):
        v = hf.channel_values({}, T0, 3)
        assert set(v) == {_CH['DUR']}


class TestChannelLayout:
    def test_채널_수와_단위(self):
        md = hf.measurements_dict
        assert len(md) == 28 and sorted(md) == list(range(28))
        assert md[_CH['RN1']] == {'measurement': 'rain', 'unit': 'mm',
                                  'name': 'Rain (1h sum) +1h',
                                  'forecast_lead_h': 1, 'forecast_kind': 'cell'}
        assert md[_CH['RNMAX']]['unit'] == 'mm'
        assert md[_CH['DUR']]['measurement'] == 'duration_time'
        assert md[_CH['DUR']]['unit'] == 'h'

    def test_시간당_강수_최대_채널이_있다(self):
        assert hf.measurements_dict[_CH['RNMAX']]['name'] == 'Window Max Hourly Rain'

    def test_선언_단위가_API_단위와_맞는다(self):
        units = {'temperature_2m': 'C', 'relative_humidity_2m': 'percent',
                 'precipitation': 'mm', 'precipitation_probability': 'percent',
                 'wind_speed_10m': 'm_s', 'cloud_cover': 'percent',
                 'shortwave_radiation': 'W_m2'}
        for _m, unit, _n, var, _mode in hf._LEAD_SPECS:
            assert units[var] == unit

    def test_표식(self):
        assert hf.INPUT_INFORMATION['input_name_unique'] == 'OPEN_METEO_HOURLY_FORECAST'
        assert hf.INPUT_INFORMATION['data_origin'] == 'model'
        assert hf.INPUT_INFORMATION['data_time'] == 'forecast'
        assert hf.INPUT_INFORMATION['period'] == 1800


# ── 입력 인스턴스 ────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def _payload(rows=None):
    rows = rows or _rows(**_BASE)
    times = sorted(rows)
    hourly = {'time': times}
    for var in set(v for r in rows.values() for v in r):
        hourly[var] = [rows[t].get(var) for t in times]
    hourly['wind_direction_10m'] = [200.0] * len(times)
    hourly['weather_code'] = [2] * len(times)
    return {'latitude': 35.86, 'longitude': 126.88, 'elevation': 12.0,
            'hourly': hourly}


@pytest.fixture
def make_input(monkeypatch, tmp_path):
    """DB 없이 InputModule 을 만든다. 현재 시각을 T0+30분으로 고정하고 파일 위치를 tmp 로."""
    import aot.config as cfg
    monkeypatch.setattr(cfg, 'DATABASE_PATH', str(tmp_path))
    monkeypatch.setattr(hf, '_now', lambda: T0 + 30 * 60)
    monkeypatch.setattr(hf.time, 'sleep', lambda s: None)
    live._RATE_LIMITED_UNTIL.clear()

    def _make(enabled=None, **attrs):
        m = hf.InputModule(SimpleNamespace(unique_id=IN_UUID, latitude=35.86,
                                           longitude=126.88), testing=True)
        m.unique_id = IN_UUID
        m.latitude, m.longitude = 35.86, 126.88
        on = set(range(28)) if enabled is None else set(enabled)
        m.is_enabled = lambda ch: ch in on
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    yield _make
    live._RATE_LIMITED_UNTIL.clear()


@pytest.fixture
def fake_get(monkeypatch):
    calls = []
    queue = []

    def _get(url, params=None, timeout=None):
        calls.append({'url': url, 'params': dict(params), 'timeout': timeout})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(hf.requests, 'get', _get)
    _get.calls, _get.queue = calls, queue
    queue.append(_Resp(200, _payload()))
    return _get


class TestRequest:
    def test_파라미터(self, make_input, fake_get):
        make_input().get_measurement()
        p = fake_get.calls[0]['params']
        assert p['wind_speed_unit'] == 'ms'
        assert p['timezone'] == 'UTC' and p['timeformat'] == 'unixtime'
        assert p['forecast_hours'] == 49 and p['past_hours'] == 1
        assert p['temperature_unit'] == 'celsius' and p['precipitation_unit'] == 'mm'
        assert 'models' not in p                       # best_match 는 생략
        assert fake_get.calls[0]['url'] == live._FORECAST_URL

    def test_모델_선택과_상업_키(self, make_input, fake_get):
        make_input(model='kma_seamless', api_key='K').get_measurement()
        assert fake_get.calls[0]['params']['models'] == 'kma_seamless'
        assert fake_get.calls[0]['params']['apikey'] == 'K'
        assert fake_get.calls[0]['url'] == live._COMMERCIAL_URL

    def test_꺼진_채널의_변수는_빠지고_파일용_변수는_유지된다(self, make_input, fake_get):
        only_temp = [_CH['T1']]
        make_input(enabled=only_temp, write_file=False).get_measurement()
        assert fake_get.calls[0]['params']['hourly'] == 'temperature_2m'
        make_input(enabled=only_temp, write_file=True).get_measurement()
        asked = set(fake_get.calls[1]['params']['hourly'].split(','))
        assert asked == set(hf._FILE_VARS.values())

    def test_활성_채널도_파일도_없으면_묻지_않는다(self, make_input, fake_get):
        assert make_input(enabled=[], write_file=False).get_measurement() is None
        assert fake_get.calls == []

    def test_연결_오류는_한_번만_다시_시도한다(self, make_input, fake_get):
        import requests
        fake_get.queue[:] = [requests.ConnectTimeout('x'), _Resp(200, _payload())]
        m = make_input()
        assert m.get_measurement() is not None
        assert len(fake_get.calls) == 2

    def test_연결_오류가_반복되면_값을_쓰지_않는다(self, make_input, fake_get, tmp_path):
        import requests
        fake_get.queue[:] = [requests.ConnectionError('x')]
        m = make_input()
        assert m.get_measurement() is None
        assert len(fake_get.calls) == 2
        assert not (tmp_path / 'openmeteo').exists()


class TestValues:
    def test_채널_값이_return_dict_에_들어간다(self, make_input, fake_get):
        out = make_input().get_measurement()
        # now = 05:30: now+1h = 06:30 → 기온 (06:00=11, 07:00=12) 11.5
        assert out[_CH['T1']]['value'] == pytest.approx(11.5)
        assert out[_CH['RN1']]['value'] == 2.0
        assert out[_CH['DUR']]['value'] == 3.0

    def test_window_h_옵션(self, make_input, fake_get):
        out = make_input(window_h='6').get_measurement()
        assert out[_CH['DUR']]['value'] == 6.0
        out = make_input(window_h='99').get_measurement()      # 범위 밖 → 6 으로 자름
        assert out[_CH['DUR']]['value'] == 6.0
        out = make_input(window_h='abc').get_measurement()
        assert out[_CH['DUR']]['value'] == 3.0

    def test_꺼진_채널은_값이_없다(self, make_input, fake_get):
        out = make_input(enabled=[_CH['T1'], _CH['RNMAX']]).get_measurement()
        assert 'value' in out[_CH['T1']] and 'value' in out[_CH['RNMAX']]
        assert 'value' not in out[_CH['T3']]

    def test_좌표가_없으면_묻지_않는다(self, make_input, fake_get):
        m = make_input()
        m.latitude = None
        assert m.get_measurement() is None and fake_get.calls == []


class TestRateLimitIsShared:
    def test_같은_dict_객체다(self):
        assert hf._RATE_LIMITED_UNTIL is live._RATE_LIMITED_UNTIL
        assert hf._rate_limit_until is live._rate_limit_until

    def test_기존_드라이버가_건_대기가_새_드라이버를_멈춘다(self, make_input, fake_get):
        live._RATE_LIMITED_UNTIL['api.open-meteo.com'] = hf._now() + 600
        assert make_input().get_measurement() is None
        assert fake_get.calls == []

    def test_새_드라이버의_429_가_기존_드라이버를_멈춘다(self, make_input, fake_get, monkeypatch):
        fake_get.queue[:] = [_Resp(429, {'reason': 'Hourly API request limit exceeded'})]
        assert make_input().get_measurement() is None
        until = live._RATE_LIMITED_UNTIL['api.open-meteo.com']
        assert until > hf._now()
        # 기존 드라이버는 같은 dict 를 보고 요청 없이 돌아온다(고정한 가짜 시각이 실제
        # 시각보다 과거라 대기 시각만 실제 시계 기준으로 늘린다).
        live._RATE_LIMITED_UNTIL['api.open-meteo.com'] = time.time() + 600
        called = []
        monkeypatch.setattr(live.requests, 'get',
                            lambda *a, **k: called.append(1))
        old = live.InputModule(SimpleNamespace(unique_id='x', latitude=1.0,
                                               longitude=1.0), testing=True)
        old.latitude, old.longitude = 1.0, 1.0
        old.is_enabled = lambda ch: True
        old.get_measurement()
        assert called == []

    def test_429_는_다시_시도하지_않는다(self, make_input, fake_get):
        fake_get.queue[:] = [_Resp(429, {'reason': 'Minutely API request limit exceeded'})]
        make_input().get_measurement()
        assert len(fake_get.calls) == 1


# ── 시간열 파일 ───────────────────────────────────────────────────────────────

class TestFile:
    def _written(self, make_input, fake_get, tmp_path):
        make_input().get_measurement()
        path = tmp_path / 'openmeteo' / FILE_NAME
        assert path.exists()
        return json.loads(path.read_text(encoding='utf-8'))

    def test_위치와_자동_디렉터리_생성(self, make_input, fake_get, tmp_path):
        assert not (tmp_path / 'openmeteo').exists()
        self._written(make_input, fake_get, tmp_path)
        assert hf.forecast_file_path(IN_UUID) == str(
            tmp_path / 'openmeteo' / FILE_NAME)
        assert 'static' not in hf.forecast_file_path(IN_UUID)

    def test_스키마(self, make_input, fake_get, tmp_path):
        d = self._written(make_input, fake_get, tmp_path)
        assert d['source'] == 'open_meteo' and d['kind'] == 'forecast'
        assert d['input_uuid'] == IN_UUID and d['tz'] == 'UTC'
        assert d['now'] == '202610130500'                  # UTC 정시
        assert d['pub_dt'] == '202610130530' and d['pub_kind'] == 'fetched'
        assert d['fetched_epoch'] == T0 + 30 * 60          # 필수
        assert d['grid_latitude'] == 35.86 and d['model'] == 'best_match'
        assert isinstance(d['lead_definition'], dict)
        assert set(d['forecasts']) == {str(i) for i in range(0, 49)}
        row = d['forecasts']['2']
        assert row['epoch'] == T0 + 2 * H
        assert row['TMP'] == 12.0 and row['REH'] == 52 and row['RN1'] == 2.0
        assert row['POP'] == 20 and row['CLD'] == 10 and row['SOL'] == 200.0
        assert row['VEC'] == 200 and row['WMO'] == 2 and 'WSD' in row
        assert d['units']['RN1'] == 'mm' and d['units']['TMP'] == 'C'

    def test_결측은_키를_넣지_않는다(self, make_input, fake_get, tmp_path):
        rows = _rows(**{k: v for k, v in _BASE.items()
                        if k != 'precipitation_probability'})
        fake_get.queue[:] = [_Resp(200, _payload(rows))]
        d = self._written(make_input, fake_get, tmp_path)
        assert 'POP' not in d['forecasts']['1']

    def test_원자적_쓰기_임시_파일이_남지_않는다(self, make_input, fake_get, tmp_path):
        self._written(make_input, fake_get, tmp_path)
        assert sorted(os.listdir(tmp_path / 'openmeteo')) == [FILE_NAME]

    def test_쓰다_실패하면_기존_파일이_그대로다(self, tmp_path, monkeypatch):
        path = tmp_path / 'd' / 'forecast_a.json'
        hf.write_forecast_file(str(path), {'v': 1})

        def boom(*a, **k):
            raise OSError('disk full')
        monkeypatch.setattr(hf.json, 'dump', boom)
        with pytest.raises(OSError):
            hf.write_forecast_file(str(path), {'v': 2})
        assert json.loads(path.read_text()) == {'v': 1}
        assert os.listdir(tmp_path / 'd') == ['forecast_a.json']

    def test_rename_으로_교체한다(self, tmp_path, monkeypatch):
        seen = []
        real = os.replace
        monkeypatch.setattr(hf.os, 'replace',
                            lambda a, b: (seen.append((a, b)), real(a, b))[1])
        hf.write_forecast_file(str(tmp_path / 'x' / 'f.json'), {'a': 1})
        assert len(seen) == 1 and seen[0][0] != seen[0][1]
        assert os.path.dirname(seen[0][0]) == os.path.dirname(seen[0][1])

    def test_파일_실패가_채널_값을_막지_않는다(self, make_input, fake_get, monkeypatch):
        monkeypatch.setattr(hf, 'write_forecast_file',
                            lambda *a, **k: (_ for _ in ()).throw(OSError('x')))
        out = make_input().get_measurement()
        assert out[_CH['T1']]['value'] == pytest.approx(11.5)

    def test_write_file_끄면_파일이_없다(self, make_input, fake_get, tmp_path):
        make_input(write_file=False).get_measurement()
        assert not (tmp_path / 'openmeteo').exists()

    def test_실패한_수집은_마지막_성공본을_남긴다(self, make_input, fake_get, tmp_path):
        make_input().get_measurement()
        first = (tmp_path / 'openmeteo' / FILE_NAME).read_text()
        import requests
        fake_get.queue[:] = [requests.ConnectionError('x')]
        make_input().get_measurement()
        assert (tmp_path / 'openmeteo' / FILE_NAME).read_text() == first


class TestExistingConsumersReadTheFile:
    """제약 3 — 소비처 코드는 그대로, 새 파일을 그대로 읽는다."""

    @pytest.fixture
    def fc(self, make_input, fake_get, tmp_path):
        from aot.functions.utils.env_control import forecast_feedforward as ff
        ff._clear_cache()
        make_input().get_measurement()
        path = str(tmp_path / 'openmeteo' / FILE_NAME)
        yield ff, path, json.load(open(path, encoding='utf-8'))
        ff._clear_cache()

    def test_forecast_rows_ahead(self, fc):
        ff, _path, data = fc
        rows = ff.forecast_rows_ahead(data, 3, T0 + 30 * 60)
        # now=05:30 → 05:00 행(ahead -0.5)부터 08:00(2.5)까지, 09:00(3.5) 제외
        assert [round(a, 1) for a, _r in rows] == [-0.5, 0.5, 1.5, 2.5]
        assert [r['TMP'] for _a, r in rows] == [10.0, 11.0, 12.0, 13.0]

    def test_forecast_epoch(self, fc):
        ff, _p, data = fc
        assert ff.forecast_epoch(data['now'], data['tz']) == T0

    def test_kma_curve(self, fc):
        from aot.functions.utils.env_control.mpc_ext import kma_curve
        _ff, _p, data = fc
        curve = kma_curve(data, T0 + 30 * 60)
        assert curve is not None and curve[0] == (T0, 10.0, 50.0)
        assert curve[3][0] == T0 + 3 * H and curve[3][1] == 13.0
        # 6 시간 넘게 낡으면 쓰지 않는다(수신 시각 기준)
        assert kma_curve(data, T0 + 30 * 60 + 7 * H) is None

    def test_build_feedforward_signal_경로_인자(self, fc):
        ff, path, _d = fc
        sig = ff.build_feedforward_signal(
            T_int=20.0, RH_int=60.0, lookahead_h=3.0, forecast_path=path,
            now_epoch=T0 + 30 * 60)
        assert sig.valid
        # 창 기온 최고 13 < 20+3 이고 최저 10 < 20-3 → 저온 예보(난방 선행)
        assert sig.T_bias > 0 and '저온' in sig.reason

    def test_weather_hazards_규칙_키로_읽힌다(self, make_input, fake_get, tmp_path,
                                               monkeypatch):
        """서리: TMP<=2 가 있는 파일 — 규칙표의 키(TMP/WSD/RN1)가 맞아야 잡힌다."""
        from aot.aot_flask.geo import weather_hazards as wh
        from aot.functions.utils.env_control import forecast_feedforward as ff
        now = time.time()
        rows = {}
        anchor = int(now // H) * H
        for off in range(0, 12):
            rows[anchor + off * H] = {
                'temperature_2m': 1.0 if off == 2 else 9.0,
                'wind_speed_10m': 11.0 if off == 3 else 2.0,
                'precipitation': 12.0 if off == 4 else 0.0}
        data = hf.build_forecast_file(rows, now, {})
        monkeypatch.setattr(ff, '_load_forecast', lambda path=None: data)
        out = wh.upcoming(24)
        kinds = {i['kind'] for i in out['items']}
        assert {'frost', 'wind', 'heavy_rain'} <= kinds
        assert out['stale'] is False
        # 수신이 끊긴 지 6 시간이 넘으면 판정하지 않는다
        old = hf.build_forecast_file(rows, now - 7 * H, {})
        monkeypatch.setattr(ff, '_load_forecast', lambda path=None: old)
        assert wh.upcoming(24)['stale'] is True


# ── 단위표·모델 표식·기존 드라이버 불변 ─────────────────────────────────────────

class TestRegistrationAndGates:
    def test_강수_단위표(self):
        from aot.utils.inputs import _RAIN_ACCUM_BY_DRIVER, rain_unit_scale
        assert _RAIN_ACCUM_BY_DRIVER['OPEN_METEO_HOURLY_FORECAST'] == {'mm': 3600}
        factor, kind = rain_unit_scale(
            'mm', driver='OPEN_METEO_HOURLY_FORECAST', model=True)
        assert factor == 1.0 and kind == 'rate'

    def test_model_input_drivers_에_포함된다(self):
        from aot.utils.inputs import model_input_drivers
        assert 'OPEN_METEO_HOURLY_FORECAST' in model_input_drivers()

    def test_입력_목록에_자동_등록된다(self):
        from aot.utils.inputs import parse_input_information
        info = parse_input_information()
        assert 'OPEN_METEO_HOURLY_FORECAST' in info
        assert len(info['OPEN_METEO_HOURLY_FORECAST']['measurements_dict']) == 28

    def test_다른_드라이버_단위표_항목_불변(self):
        from aot.utils.inputs import _RAIN_ACCUM_BY_DRIVER as t
        assert t['KMA_weather_500'] == {'mm': 900}
        assert t['OPEN_METEO_FORECAST'] == {'mm': 3600}
        assert t['KMA_forecast'] == {'mm': 3600}
        assert t['NASA_POWER_DAILY'] == {'mm': 86400}


class TestLiveDriverUnchanged:
    """제약 2 — OPEN_METEO_FORECAST 의 채널·단위·행 선택은 이 PR 에서 불변."""

    def test_채널_스냅샷(self):
        assert live.measurements_dict == {
            0: {'measurement': 'temperature', 'unit': 'C'},
            1: {'measurement': 'humidity', 'unit': 'percent'},
            2: {'measurement': 'light', 'unit': 'W_m2', 'name': 'Solar'},
            3: {'measurement': 'speed', 'unit': 'm_s', 'name': 'Wind'},
            4: {'measurement': 'direction', 'unit': 'bearing', 'name': 'Wind'},
            5: {'measurement': 'rain', 'unit': 'mm'},
            6: {'measurement': 'vapor_pressure_deficit', 'unit': 'kPa'},
            7: {'measurement': 'dewpoint', 'unit': 'C'},
        }

    def test_변수_표식_URL(self):
        assert live._HOURLY_VARS == {
            0: 'temperature_2m', 1: 'relative_humidity_2m',
            2: 'shortwave_radiation', 3: 'wind_speed_10m',
            4: 'wind_direction_10m', 5: 'precipitation',
            6: 'vapour_pressure_deficit', 7: 'dew_point_2m'}
        assert live.INPUT_INFORMATION['data_origin'] == 'model'
        assert live.INPUT_INFORMATION['input_name_unique'] == 'OPEN_METEO_FORECAST'
        assert 'data_time' not in live.INPUT_INFORMATION
        assert live._FORECAST_URL == 'https://api.open-meteo.com/v1/forecast'
        assert live._COMMERCIAL_URL == \
            'https://customer-api.open-meteo.com/v1/forecast'

    def test_행_선택은_지나온_마지막_정시(self):
        times = ['2026-08-25T10:00', '2026-08-25T11:00', '2026-08-25T12:00']
        at = datetime(2026, 8, 25, 11, 59, tzinfo=timezone.utc)
        assert live.InputModule._pick_row(times, at) == 1

    def test_실시간_드라이버는_예보_표식이나_파일을_갖지_않는다(self):
        assert not hasattr(live, 'write_forecast_file')

    def test_채널_이름이_겹치지_않는다(self):
        """두 드라이버는 이름으로 갈린다 — 같은 unique 이름이면 하나가 가려진다."""
        assert hf.INPUT_INFORMATION['input_name_unique'] != \
            live.INPUT_INFORMATION['input_name_unique']


class TestReviewFollowUps:
    """PR 1 검토 참고 사항 — 정상 응답의 채널·파일 동작은 바꾸지 않는다."""

    @pytest.mark.parametrize('body', [[1, 2, 3], 'oops', 42])
    def test_JSON_이_객체가_아니면_값을_쓰지_않는다(self, make_input, fake_get,
                                                tmp_path, body):
        fake_get.queue[:] = [_Resp(200, body)]
        m = make_input()
        assert m.get_measurement() is None                 # 예외로 죽지 않는다
        assert not (tmp_path / 'openmeteo').exists()

    @pytest.mark.parametrize('hourly', [[1, 2], 'x', {'time': 'abc'},
                                        {'time': {'a': 1}}])
    def test_hourly_모양이_다르면_행이_없다(self, hourly):
        assert hf.rows_from_hourly(hourly) == {}

    def test_hourly_모양이_다르면_조회도_값을_쓰지_않는다(self, make_input, fake_get):
        fake_get.queue[:] = [_Resp(200, {'hourly': [1, 2]})]
        assert make_input().get_measurement() is None

    @pytest.mark.parametrize('bad', [None, '', 'uuid-1', '../etc/passwd',
                                     '5f0c2a8e-3b1d-4c7a-9e2f-6a4b8d1c0e93/..',
                                     123])
    def test_파일_경로는_uuid_만_받는다(self, bad):
        with pytest.raises(ValueError):
            hf.forecast_file_path(bad)

    def test_uuid_가_아니면_파일만_건너뛰고_채널은_쓴다(self, make_input, fake_get,
                                                  tmp_path):
        m = make_input()
        m.unique_id = 'not-a-uuid'
        out = m.get_measurement()
        assert out is not None and out[_CH['T1']].get('value') is not None
        assert not (tmp_path / 'openmeteo').exists()

    def test_창_일부_결측은_값은_그대로_빠진_칸을_센다(self):
        """집계 값은 PR 1 정의 그대로(남은 칸) — 빠진 칸 수만 따로 알린다."""
        rows = _rows(**_BASE)
        rows[T0 + 2 * H].pop('precipitation')              # 창 안 칸 하나
        rows[T0 + 2 * H].pop('temperature_2m')             # 창 안 정시 행 하나
        now = T0 + 30 * 60
        v = hf.channel_values(rows, now, 3)
        assert v[_CH['RNMAX']] == 4.0                      # 값은 바뀌지 않는다
        gaps = hf.window_gaps(rows, now, 3)
        assert gaps[_CH['RNMAX']] == 1
        # 07:00 기온이 비면 그 행 + now+1h·… 보간 아닌 창 끝(08:30)은 무관,
        # now(05:30) 보간도 무관 → 정시 행 하나만 빠짐
        assert gaps[_CH['TMAX']] == 1 and gaps[_CH['TMIN']] == 1
        assert _CH['POPMAX'] not in gaps

    def test_완전한_창은_빠진_칸이_없다(self):
        for now in (T0, T0 + 1, T0 + 30 * 60, T0 + 59 * 60):
            for w in (1, 3, 6):
                assert hf.window_gaps(_rows(**_BASE), now, w) == {}, (now, w)

    def test_결측_창은_경고_로그를_남긴다(self, make_input, fake_get, caplog):
        rows = _rows(**_BASE)
        rows[T0 + 2 * H].pop('precipitation')
        fake_get.queue[:] = [_Resp(200, _payload(rows))]
        m = make_input()
        import logging
        m.logger = logging.getLogger('test.hf')
        with caplog.at_level(logging.WARNING, logger='test.hf'):
            out = m.get_measurement()
        assert out[_CH['RNMAX']].get('value') == 4.0
        assert '창 집계 일부 결측' in caplog.text
