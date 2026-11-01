# coding=utf-8
"""Open-Meteo 시간별 예보 파일의 소비처 연결 (설계안 PR 4, §4.5·§6).

시설에 `OPEN_METEO_HOURLY_FORECAST` 입력이 묶여 있으면 그 입력이 쓴 시간열 파일
(`forecast_<uuid>.json`)을 MPC 외기 곡선·피드포워드·시설 모달 기상 위험이 읽는다.
그 밖의 시설(김제처럼 바인딩이 없거나 다른 예보 입력만 묶인 곳)은 동작이 그대로다.

환경제어 세션 확정 규칙:
  E1 — 피드포워드는 경로 하나: 신선한 파일(예보 입력이 이 드라이버 하나뿐일 때) >
       바인딩 단일값 > forecast.json. 병행하지 않는다.
  E2 — 파일 경로에서 강수확률 억제는 POP ≥ 50 그리고 창 안 시간당 강수 최대 ≥ 0.5 mm/h.
       강수 값이 없으면 확률만으로 억제하지 않는다. 기상청 forecast.json 경로는 그대로.
  E3 — 파일은 `fetched_epoch` 기준 2 h 보다 낡으면 쓰지 않는다.
  E5 — MPC 곡선은 신선한 시설 파일 우선, 아니면 기존(forecast.json + 시간대 일치).
"""
import json
import logging
import time
from datetime import datetime, timedelta

import pytest
import pytz

from aot.functions.utils.env_control import forecast_feedforward as ff
from aot.functions.utils.env_control.forecast_feedforward import (
    FeedforwardSignal, build_feedforward_signal,
    build_feedforward_signal_from_forecast)
from aot.functions.utils.env_control.mpc_ext import kma_curve

KST = pytz.timezone('Asia/Seoul')
UUID_A = '11111111-2222-3333-4444-555555555555'
UUID_B = '66666666-7777-8888-9999-aaaaaaaaaaaa'
UUID_KMA = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'


@pytest.fixture(autouse=True)
def _clean():
    ff._clear_cache()
    from aot.aot_flask.geo import facility_sensors as fs
    from aot.aot_flask.geo import weather_hazards as wh
    fs._DRIVER_CACHE.clear()
    wh._CACHE.clear()
    yield
    ff._clear_cache()
    fs._DRIVER_CACHE.clear()
    wh._CACHE.clear()


def _om_file(now, rows, fetched_ago_s=600.0):
    """새 드라이버가 쓰는 모양 그대로 — `build_forecast_file` 로 만든다.

    rows: {몇 시간 뒤(정시, 지금이 든 칸=0): {var: 값}}. 변수 이름은 Open-Meteo 것.
    """
    from aot.inputs.open_meteo_hourly_forecast import build_forecast_file
    fetched = now - fetched_ago_s
    anchor = int(fetched // 3600) * 3600
    table = {anchor + h * 3600: dict(v) for h, v in rows.items()}
    return build_forecast_file(table, fetched, {'input_uuid': UUID_A})


def _write(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')
    return str(path)


def _kma_file(written, rows, tz='Asia/Seoul'):
    stamp = written.strftime('%Y%m%d%H%M')
    return {'tz': tz, 'now': stamp, 'pub_dt': stamp,
            'forecasts': {str(k): v for k, v in rows.items()}}


NOW = KST.localize(datetime(2026, 10, 13, 14, 20)).timestamp()


def _drivers(monkeypatch, table):
    """입력 id → 드라이버 (DB 대신)."""
    import aot.utils.inputs as ui
    monkeypatch.setattr(ui, '_input_devices',
                        lambda ids: [(i, table[i]) for i in ids if i in table])


def _binding(iid, mtype='forecast_temperature', mid='m1'):
    return {'measurement_type': mtype, 'input_uuid': iid, 'measurement_id': mid,
            'name': mtype}


# ─────────────────────────────────────────────────────────────────────────────
# _load_forecast — 경로별 캐시, 기본 경로 불변
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadForecastPerPath:
    def test_두_경로가_서로_다른_내용을_돌려준다(self, tmp_path):
        a = _write(tmp_path / 'a.json', {'tag': 'a', 'forecasts': {'0': {}}})
        b = _write(tmp_path / 'b.json', {'tag': 'b', 'forecasts': {'0': {}}})
        assert ff._load_forecast(a)['tag'] == 'a'
        # 예전에는 여기서 a 캐시를 돌려받았다.
        assert ff._load_forecast(b)['tag'] == 'b'
        assert ff._load_forecast(a)['tag'] == 'a'

    def test_기본_경로는_PATH_JSON_의_forecast_json(self, tmp_path, monkeypatch):
        import aot.config
        monkeypatch.setattr(aot.config, 'PATH_JSON', str(tmp_path))
        _write(tmp_path / 'forecast.json', {'tag': 'kma'})
        other = _write(tmp_path / 'other.json', {'tag': 'other'})
        assert ff._load_forecast(other)['tag'] == 'other'
        assert ff._load_forecast()['tag'] == 'kma'
        assert ff._load_forecast(None)['tag'] == 'kma'

    def test_캐시는_15분_유지되고_clear_cache_로_비운다(self, tmp_path):
        p = tmp_path / 'a.json'
        _write(p, {'v': 1})
        assert ff._load_forecast(str(p))['v'] == 1
        _write(p, {'v': 2})
        assert ff._load_forecast(str(p))['v'] == 1        # 캐시
        ff._clear_cache()
        assert ff._load_forecast(str(p))['v'] == 2

    def test_없는_파일은_빈_dict_이고_기억하지_않는다(self, tmp_path):
        p = tmp_path / 'late.json'
        assert ff._load_forecast(str(p)) == {}
        _write(p, {'v': 1})
        assert ff._load_forecast(str(p))['v'] == 1

    def test_기존_import_경로가_그대로다(self):
        from aot.functions.utils.env_control.forecast_feedforward import (  # noqa: F401
            _clear_cache, _load_forecast, forecast_epoch, forecast_rows_ahead,
            build_feedforward_signal, build_feedforward_signal_from_forecast,
            apply_feedforward, FeedforwardSignal)
        from aot.functions.utils.env_control.mpc_ext import kma_curve as kc  # noqa: F401
        from aot.aot_flask.geo.weather_hazards import upcoming, upcoming_cached  # noqa: F401
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (  # noqa: F401
            CycleMixin)
        import inspect
        assert list(inspect.signature(ff._load_forecast).parameters) == ['forecast_path']
        assert inspect.signature(upcoming).parameters['forecast_path'].default is None


# ─────────────────────────────────────────────────────────────────────────────
# 신선도 (E3)
# ─────────────────────────────────────────────────────────────────────────────

class TestFreshness:
    def test_2시간_이내면_쓴다(self, tmp_path):
        p = _write(tmp_path / 'f.json', _om_file(NOW, {0: {'temperature_2m': 20}}, 7000))
        assert ff.load_fresh_facility_forecast(p, NOW) is not None

    def test_2시간이_넘으면_쓰지_않는다(self, tmp_path):
        p = _write(tmp_path / 'f.json', _om_file(NOW, {0: {'temperature_2m': 20}}, 7300))
        assert ff.load_fresh_facility_forecast(p, NOW) is None

    def test_수신_시각이_없거나_파일이_없으면_쓰지_않는다(self, tmp_path):
        d = _om_file(NOW, {0: {'temperature_2m': 20}})
        d.pop('fetched_epoch')
        assert ff.load_fresh_facility_forecast(_write(tmp_path / 'f.json', d), NOW) is None
        assert ff.load_fresh_facility_forecast(str(tmp_path / 'none.json'), NOW) is None
        assert ff.load_fresh_facility_forecast(None, NOW) is None

    def test_수신_시각이_미래면_쓰지_않는다(self, tmp_path):
        p = _write(tmp_path / 'f.json', _om_file(NOW, {0: {'temperature_2m': 20}}, -3600))
        assert ff.load_fresh_facility_forecast(p, NOW) is None


# ─────────────────────────────────────────────────────────────────────────────
# 강수확률 AND 규칙 (E2)
# ─────────────────────────────────────────────────────────────────────────────

class TestRainAndRule:
    def _sig(self, tmp_path, rows, rain_min=ff.FACILITY_RAIN_MM_H_MIN):
        base = {'temperature_2m': 22.0, 'relative_humidity_2m': 60.0,
                'wind_speed_10m': 2.0}
        p = _write(tmp_path / 'f.json',
                   _om_file(NOW, {h: dict(base, **v) for h, v in rows.items()}))
        return build_feedforward_signal(T_int=22.0, RH_int=60.0, lookahead_h=3.0,
                                        forecast_path=p, now_epoch=NOW,
                                        rain_mm_h_min=rain_min)

    def test_확률과_강수_둘_다_넘으면_억제(self, tmp_path):
        s = self._sig(tmp_path, {1: {'precipitation_probability': 80, 'precipitation': 0.2},
                                 2: {'precipitation_probability': 40, 'precipitation': 0.6}})
        assert s.valid and s.rain_expected and s.wind_inhibit

    def test_강수가_0_5_미만이면_확률만으로_억제하지_않는다(self, tmp_path):
        s = self._sig(tmp_path, {1: {'precipitation_probability': 90, 'precipitation': 0.4},
                                 2: {'precipitation_probability': 90, 'precipitation': 0.0}})
        assert s.valid and not s.rain_expected and not s.wind_inhibit

    def test_강수_값이_없으면_확률만으로_억제하지_않는다(self, tmp_path):
        s = self._sig(tmp_path, {1: {'precipitation_probability': 90},
                                 2: {'precipitation_probability': 90}})
        assert s.valid and not s.rain_expected and not s.wind_inhibit

    def test_확률이_50_미만이면_강수가_있어도_억제하지_않는다(self, tmp_path):
        s = self._sig(tmp_path, {1: {'precipitation_probability': 30, 'precipitation': 2.0}})
        assert not s.rain_expected

    def test_기상청_경로는_예전처럼_확률만으로_억제한다(self, tmp_path):
        """rain_mm_h_min 을 주지 않는 forecast.json 경로는 바뀌지 않는다."""
        written = datetime.fromtimestamp(NOW, KST).replace(minute=0, tzinfo=None)
        p = _write(tmp_path / 'forecast.json',
                   _kma_file(written, {k: {'TMP': 22.0, 'REH': 60.0, 'POP': 60}
                                       for k in range(6)}))
        s = build_feedforward_signal(T_int=22.0, RH_int=60.0, lookahead_h=3.0,
                                     forecast_path=p, now_epoch=NOW)
        assert s.rain_expected and s.wind_inhibit
        assert s.reason == '강우 확률 60%'

    def test_강풍은_강수와_무관하게_그대로(self, tmp_path):
        s = self._sig(tmp_path, {1: {'wind_speed_10m': 15.0, 'precipitation_probability': 90}})
        assert s.wind_inhibit and not s.rain_expected


# ─────────────────────────────────────────────────────────────────────────────
# 시설 → 파일 해석
# ─────────────────────────────────────────────────────────────────────────────

class TestForecastFileFor:
    def test_시간별_예보_입력의_파일(self, monkeypatch, tmp_path):
        import aot.config
        from aot.aot_flask.geo.facility_sensors import forecast_file_for
        monkeypatch.setattr(aot.config, 'DATABASE_PATH', str(tmp_path))
        _drivers(monkeypatch, {UUID_A: 'OPEN_METEO_HOURLY_FORECAST',
                               UUID_KMA: 'KMA_forecast'})
        got = forecast_file_for([_binding(UUID_KMA), _binding(UUID_A, mid='m2')])
        assert got == str(tmp_path / 'openmeteo' / f'forecast_{UUID_A}.json')

    def test_드라이버가_다르면_없다(self, monkeypatch):
        from aot.aot_flask.geo.facility_sensors import forecast_file_for
        _drivers(monkeypatch, {UUID_KMA: 'KMA_forecast',
                               UUID_B: 'OPEN_METEO_FORECAST'})     # 실시간 드라이버
        assert forecast_file_for([_binding(UUID_KMA), _binding(UUID_B)]) is None
        assert forecast_file_for([]) is None
        assert forecast_file_for(None) is None

    def test_sole_은_예보_입력이_그_하나뿐일_때만(self, monkeypatch):
        from aot.aot_flask.geo.facility_sensors import forecast_file_for
        _drivers(monkeypatch, {UUID_A: 'OPEN_METEO_HOURLY_FORECAST',
                               UUID_KMA: 'KMA_forecast'})
        same = [_binding(UUID_A, 'forecast_temperature', 'm1'),
                _binding(UUID_A, 'forecast_humidity', 'm2')]
        assert forecast_file_for(same, sole=True) is not None
        mixed = same + [_binding(UUID_KMA)]
        assert forecast_file_for(mixed, sole=True) is None
        assert forecast_file_for(mixed) is not None

    def test_uuid_형식이_아니면_없다(self, monkeypatch):
        from aot.aot_flask.geo.facility_sensors import forecast_file_for
        bad = '../../etc/passwd'
        _drivers(monkeypatch, {bad: 'OPEN_METEO_HOURLY_FORECAST'})
        assert forecast_file_for([_binding(bad)]) is None

    def test_드라이버_조회가_실패하면_없다(self, monkeypatch):
        import aot.utils.inputs as ui
        from aot.aot_flask.geo.facility_sensors import forecast_file_for
        monkeypatch.setattr(ui, '_input_devices', lambda ids: None)
        assert forecast_file_for([_binding(UUID_A)]) is None


# ─────────────────────────────────────────────────────────────────────────────
# 코디네이터 — 피드포워드 경로 하나 (E1)
# ─────────────────────────────────────────────────────────────────────────────

def _coord(bindings=None, fac_tz=None, enabled=True):
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
    c = CycleMixin.__new__(CycleMixin)
    c.unique_id = 'x'
    c.logger = logging.getLogger('test_openmeteo_forecast_consumers')
    c._get_facility_tz = lambda: fac_tz
    c.gate_wind_threshold = 12.0
    c.forecast_lookahead_h = 3.0
    c.forecast_feedforward_enabled = enabled
    if bindings is not None:
        c._sensors_forecast = bindings
    return c


@pytest.fixture
def om_setup(monkeypatch, tmp_path):
    """DATABASE_PATH=tmp, UUID_A=시간별 예보 드라이버, 파일 쓰기 도우미."""
    import aot.config
    monkeypatch.setattr(aot.config, 'DATABASE_PATH', str(tmp_path))
    monkeypatch.setattr(aot.config, 'PATH_JSON', str(tmp_path / 'static'))
    _drivers(monkeypatch, {UUID_A: 'OPEN_METEO_HOURLY_FORECAST',
                           UUID_KMA: 'KMA_forecast'})
    (tmp_path / 'openmeteo').mkdir()
    (tmp_path / 'static').mkdir()

    def write(data):
        return _write(tmp_path / 'openmeteo' / f'forecast_{UUID_A}.json', data)
    return write


class TestFeedforwardPath:
    def _cold_file(self, fetched_ago_s=600.0):
        # 지금 22 °C 실내, 앞으로 3 h 안에 15 °C 까지 내려간다(창 최저). +3h 값은 21.
        temps = {0: 21.0, 1: 15.0, 2: 18.0, 3: 21.0, 4: 21.0}
        return _om_file(time.time(), {h: {'temperature_2m': t, 'relative_humidity_2m': 60}
                                      for h, t in temps.items()}, fetched_ago_s)

    def test_신선한_파일이면_창_판정이고_바인딩은_읽지_않는다(self, om_setup, monkeypatch):
        om_setup(self._cold_file())
        import aot.aot_flask.geo.facility_sensors as fs
        monkeypatch.setattr(fs, 'read_forecast_sensors',
                            lambda *a, **k: pytest.fail('바인딩 경로를 병행했다'))
        c = _coord([_binding(UUID_A)])
        sig = c._forecast_feedforward_signal(22.0, 60.0)
        assert sig.valid and sig.lookahead_h == 3.0
        assert sig.T_bias > 0, sig.reason      # 창 최저 15 → 난방 선행

    def test_파일이_낡으면_바인딩_단일값(self, om_setup, monkeypatch):
        om_setup(self._cold_file(fetched_ago_s=3 * 3600))
        import aot.aot_flask.geo.facility_sensors as fs
        monkeypatch.setattr(fs, 'read_forecast_sensors',
                            lambda b, *a, **k: {'T': 21.0, 'valid_count': 1, 'total_count': 1})
        sig = _coord([_binding(UUID_A)])._forecast_feedforward_signal(22.0, 60.0)
        assert sig.valid and sig.lookahead_h == 0.0 and sig.T_bias == 0.0

    def test_파일이_없으면_바인딩_단일값(self, om_setup, monkeypatch):
        import aot.aot_flask.geo.facility_sensors as fs
        monkeypatch.setattr(fs, 'read_forecast_sensors',
                            lambda b, *a, **k: {'T': 30.0, 'valid_count': 1, 'total_count': 1})
        sig = _coord([_binding(UUID_A)])._forecast_feedforward_signal(22.0, 60.0)
        assert sig.lookahead_h == 0.0 and sig.T_bias < 0

    def test_다른_예보_입력이_섞이면_바인딩_단일값(self, om_setup, monkeypatch):
        om_setup(self._cold_file())
        import aot.aot_flask.geo.facility_sensors as fs
        seen = []
        monkeypatch.setattr(fs, 'read_forecast_sensors',
                            lambda b, *a, **k: seen.append(b) or {'valid_count': 0})
        b = [_binding(UUID_A), _binding(UUID_KMA, 'forecast_humidity')]
        sig = _coord(b)._forecast_feedforward_signal(22.0, 60.0)
        assert seen == [b] and not sig.valid

    def test_바인딩이_없으면_forecast_json(self, om_setup, monkeypatch, tmp_path):
        written = datetime.now(KST).replace(minute=0, second=0, microsecond=0, tzinfo=None)
        _write(tmp_path / 'static' / 'forecast.json',
               _kma_file(written, {k: {'TMP': 35.0, 'REH': 60.0} for k in range(6)}))
        sig = _coord([])._forecast_feedforward_signal(22.0, 60.0)
        assert sig.valid and sig.lookahead_h == 3.0 and sig.T_bias < 0

    def test_바인딩_단일값_결과는_예전_함수와_같다(self, om_setup, monkeypatch):
        """김제처럼 다른 드라이버만 묶인 시설 — PR 전 코드가 부르던 그 함수와 같은 결과."""
        import aot.aot_flask.geo.facility_sensors as fs
        fc = {'T': 26.5, 'RH': 90.0, 'wind': 13.0, 'pop': 70.0,
              'valid_count': 4, 'total_count': 4}
        monkeypatch.setattr(fs, 'read_forecast_sensors', lambda b, *a, **k: dict(fc))
        got = _coord([_binding(UUID_KMA)])._forecast_feedforward_signal(22.0, 60.0)
        want = build_feedforward_signal_from_forecast(
            forecast=dict(fc), T_int=22.0, RH_int=60.0, wind_threshold=12.0)
        assert got == want

    def test_꺼져_있으면_아무것도_읽지_않는다(self, om_setup, monkeypatch):
        """세 현장 모두 forecast_feedforward_enabled=False — 신호는 빈 것 그대로."""
        om_setup(self._cold_file())
        monkeypatch.setattr(ff, '_load_forecast', lambda *a, **k: pytest.fail('읽었다'))
        c = _coord([_binding(UUID_A)], enabled=False)
        env_target, internal = {}, {}
        c._apply_forecast_feedforward(env_target, internal, 22.0, 60.0,
                                      guide=(10.0, 35.0, 40.0, 90.0))
        assert c._last_ff_signal == FeedforwardSignal()
        assert env_target == {} and internal == {}


# ─────────────────────────────────────────────────────────────────────────────
# 코디네이터 — MPC 외기 곡선 (E5)
# ─────────────────────────────────────────────────────────────────────────────

class TestMpcCurve:
    def _seoul_file(self, now):
        written = datetime.fromtimestamp(now, KST).replace(minute=0, tzinfo=None)
        return _kma_file(written, {k: {'TMP': 20.0 + k, 'REH': 60.0} for k in range(6)})

    def _om(self, now, fetched_ago_s=600.0):
        return _om_file(now, {h: {'temperature_2m': 10.0 + h, 'relative_humidity_2m': 70}
                              for h in range(0, 8)}, fetched_ago_s)

    def test_구마모토_시간대가_달라도_시설_파일이_있으면_곡선(self, om_setup, monkeypatch):
        now = time.time()
        monkeypatch.setattr(ff, '_load_forecast', self._wrap_default(self._seoul_file(now)))
        om_setup(self._om(now))
        tokyo = pytz.timezone('Asia/Tokyo')
        c = _coord([_binding(UUID_A)], fac_tz=tokyo)
        curve = c._mpc_forecast_curve(now, kma_curve)
        assert curve and curve[0][1] == 10.0           # 시설 파일(서울 파일은 20 부터)
        # 바인딩이 없으면 예전대로 — 시간대가 달라 곡선 없음.
        assert _coord(None, fac_tz=tokyo)._mpc_forecast_curve(now, kma_curve) is None

    def test_시설_파일이_낡으면_기존_로직(self, om_setup, monkeypatch):
        now = time.time()
        monkeypatch.setattr(ff, '_load_forecast', self._wrap_default(self._seoul_file(now)))
        om_setup(self._om(now, fetched_ago_s=2.5 * 3600))
        assert _coord([_binding(UUID_A)], fac_tz=pytz.timezone('Asia/Tokyo'))\
            ._mpc_forecast_curve(now, kma_curve) is None
        curve = _coord([_binding(UUID_A)], fac_tz=KST)._mpc_forecast_curve(now, kma_curve)
        assert curve and curve[0][1] == 20.0           # 서울 forecast.json

    def test_한국_시설도_신선한_시설_파일이_우선(self, om_setup, monkeypatch):
        now = time.time()
        monkeypatch.setattr(ff, '_load_forecast', self._wrap_default(self._seoul_file(now)))
        om_setup(self._om(now))
        curve = _coord([_binding(UUID_A)], fac_tz=KST)._mpc_forecast_curve(now, kma_curve)
        assert curve[0][1] == 10.0

    def test_김제처럼_바인딩이_없으면_예전과_같다(self, monkeypatch):
        now = time.time()
        data = self._seoul_file(now)
        monkeypatch.setattr(ff, '_load_forecast', self._wrap_default(data))
        assert _coord(None, fac_tz=KST)._mpc_forecast_curve(now, kma_curve) == \
            kma_curve(data, now)
        assert _coord([], fac_tz=KST)._mpc_forecast_curve(now, kma_curve) == \
            kma_curve(data, now)

    def test_다른_드라이버만_묶이면_예전과_같다(self, om_setup, monkeypatch):
        now = time.time()
        data = self._seoul_file(now)
        monkeypatch.setattr(ff, '_load_forecast', self._wrap_default(data))
        assert _coord([_binding(UUID_KMA)], fac_tz=KST)._mpc_forecast_curve(
            now, kma_curve) == kma_curve(data, now)

    @staticmethod
    def _wrap_default(default_data):
        real = ff._load_forecast

        def load(forecast_path=None):
            return default_data if forecast_path is None else real(forecast_path)
        return load


# ─────────────────────────────────────────────────────────────────────────────
# 기상 위험 — forecast_path
# ─────────────────────────────────────────────────────────────────────────────

class TestHazards:
    def test_시설_파일로_판정한다(self, tmp_path):
        from aot.aot_flask.geo import weather_hazards as wh
        now = time.time()
        p = _write(tmp_path / 'f.json',
                   _om_file(now, {h: {'temperature_2m': 1.0 if h == 4 else 10.0}
                                  for h in range(0, 10)}))
        out = wh.upcoming(24, forecast_path=p)
        assert not out['stale']
        assert [i['kind'] for i in out['items']] == ['frost']

    def test_시설_파일이_2시간_넘으면_낡음(self, tmp_path):
        from aot.aot_flask.geo import weather_hazards as wh
        now = time.time()
        p = _write(tmp_path / 'f.json',
                   _om_file(now, {h: {'temperature_2m': -3.0} for h in range(0, 10)},
                            fetched_ago_s=2.5 * 3600))
        out = wh.upcoming(24, forecast_path=p)
        assert out['stale'] and out['items'] == []

    def test_기본은_forecast_json_그대로(self, tmp_path, monkeypatch):
        import aot.config
        from aot.aot_flask.geo import weather_hazards as wh
        monkeypatch.setattr(aot.config, 'PATH_JSON', str(tmp_path))
        # 발표 3시간 전 — 기상청 기준(6 h)으로는 신선하다.
        wall = datetime.now(KST).replace(tzinfo=None)
        d = _kma_file(wall, {3: {'TMP': -1.0}})
        d['pub_dt'] = (wall - timedelta(hours=3)).strftime('%Y%m%d%H%M')
        _write(tmp_path / 'forecast.json', d)
        out = wh.upcoming()
        assert not out['stale'] and out['items'][0]['kind'] == 'freeze'

    def test_캐시는_파일별(self, tmp_path, monkeypatch):
        from aot.aot_flask.geo import weather_hazards as wh
        calls = []
        monkeypatch.setattr(wh, 'upcoming',
                            lambda hours=24, forecast_path=None:
                            calls.append(forecast_path) or {'p': forecast_path})
        assert wh.upcoming_cached()['p'] is None
        assert wh.upcoming_cached(forecast_path='/x')['p'] == '/x'
        assert wh.upcoming_cached(forecast_path='/x')['p'] == '/x'
        assert wh.upcoming_cached()['p'] is None
        assert calls == [None, '/x']

    def test_시설_모달은_신선한_시설_파일만(self, om_setup):
        from aot.aot_flask.geo.facility_sensors import fresh_forecast_file_for
        assert fresh_forecast_file_for([_binding(UUID_A)]) is None      # 파일 없음
        p = om_setup(_om_file(time.time(), {0: {'temperature_2m': 10.0}}))
        assert fresh_forecast_file_for([_binding(UUID_A)]) == p
        ff._clear_cache()
        om_setup(_om_file(time.time(), {0: {'temperature_2m': 10.0}}, 3 * 3600))
        assert fresh_forecast_file_for([_binding(UUID_A)]) is None


def test_시설_모달_라우트가_시설_파일을_넘긴다():
    """`_build_facility_overview` 가 hazards 에 시설 파일 경로를 싣는다(정적 확인 —
    라우트 실행은 Flask 앱이 필요하다)."""
    import inspect
    from aot.aot_flask import routes_geo_iec
    src = inspect.getsource(routes_geo_iec._build_facility_overview)
    assert 'fresh_forecast_file_for(row.weather_bindings)' in src
    assert 'upcoming_cached(forecast_path=hazard_path)' in src
