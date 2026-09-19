# coding=utf-8
"""실외 컨텍스트 수집기 수리 (2026-09-19).

## 무엇이 고장이었나

1. `get_last_measurement` 는 **`[시각, 값]` 리스트**를 준다(없으면 `[None, None]`).
   수집기는 그것을 스칼라로 썼다 — 이슬점 센서가 없으면 이슬점 계산에서
   TypeError 로 **매 주기 죽어** 공유 컨텍스트가 영영 빈 채였고, 있으면 리스트가
   그대로 실외 온도로 실렸다.
2. 나이 판정용 `_get_last_ts` 가 `read_last_influxdb(장치, 측정)` 을 인자가 모자란
   채 불러 늘 예외 → now. **센서가 한 시간 끊겨도 "신선"** 이었다.
3. 늦은 값을 기본값(20 °C·60 %·바람 0·비 0)으로 바꿔 실측처럼 공유했다. 센서를
   **고르지 않은** 항목도 같은 기본값을 실측처럼 공유했다 — 센서가 하나도 없는
   수집기는 영원히 "20 °C·60 %" 를 냈다. 이제 둘 다 공유하지 않는다.
4. `sensor_max_age or 120.0` 숫자 폴백 — 정본(`measurement_freshness`)을 안 지났다.

2 때문에 안전 게이트의 EXT_EXP(당시: 개구부·차광막 0 강제)가 사실상 죽은
경로였다. **2 만 고쳤으면 정전 때 창 폐쇄가 조용히 살아났다** — 게이트 재정의
(`test_outdoor_unknown_consistency.py`)와 함께여야 하는 이유다.
"""
import time

import pytest

import aot.functions.ext_context_collector as ecc


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setattr(ecc, 'write_influxdb_value', lambda *a, **k: None)
    monkeypatch.setattr(ecc, '_shared_context', {})
    monkeypatch.setattr(ecc, '_shared_context_ts', 0.0)
    monkeypatch.setattr(ecc, '_shared_context_period', 0.0)
    monkeypatch.setattr(ecc._freshness, 'freshness_by_device', lambda ids: {})

    import logging
    f = ecc.CustomFunction.__new__(ecc.CustomFunction)
    f.logger, f.unique_id = logging.getLogger('test.collector'), 'c'
    f.update_period, f.sensor_max_age = 60.0, 0.0
    f.sensor_temperature, f.sensor_humidity = 'wx,t', 'wx,rh'
    f.sensor_wind, f.sensor_rain = 'wx,wind', 'wx,rain'
    f.sensor_solar = f.sensor_dewpoint = f.sensor_co2 = None
    f.readings = {'t': 25.0, 'rh': 70.0, 'wind': 2.0, 'rain': 0.0}
    f.windows = {}

    def _get(dev, meas, max_age=None):
        f.windows[meas] = max_age
        v = f.readings.get(meas)
        return [time.time() - 20, v] if v is not None else [None, None]

    f.get_last_measurement = _get
    return f


class TestUnpack:

    @pytest.mark.parametrize('raw, expected', [
        ([100.0, 25.0], (100.0, 25.0)),
        ([None, None], (None, None)),
        ([100.0, None], (None, None)),
        (None, (None, None)),
        ([], (None, None)),
        (7.0, (None, 7.0)),
        ([100.0, 'x'], (None, None)),
    ])
    def test_리스트를_시각과_값으로(self, raw, expected):
        assert ecc._unpack_last(raw) == expected


class TestPublish:

    def test_이슬점_센서가_없어도_죽지_않고_계산한다(self, collector):
        collector._collect_and_publish()
        ctx = ecc.get_shared_context()
        assert ctx['T_ext'] == 25.0 and isinstance(ctx['T_ext'], float)
        assert ctx['dewpoint'] == pytest.approx(ecc._calc_dewpoint(25.0, 70.0))

    def test_늦은_센서는_기본값이_아니라_None(self, collector):
        collector.readings.update(t=None, rh=None, rain=None)
        collector._collect_and_publish()
        ctx = ecc.get_shared_context()
        assert ctx['T_ext'] is None, '늦은 값을 20 °C 로 지어내면 실측처럼 보인다'
        assert ctx['RH_ext'] is None
        assert ctx['rain'] is None, '"비 안 옴" 을 지어내면 게이트가 끊긴 줄 모른다'
        assert ctx['dewpoint'] is None

    def test_고르지_않은_항목은_공유하지_않는다(self, collector):
        collector.sensor_temperature = collector.sensor_wind = None
        collector.sensor_rain = None
        collector._collect_and_publish()
        ctx = ecc.get_shared_context()
        assert ctx['T_ext'] is None, '20 °C 를 채우면 제어가 실측으로 읽는다'
        assert ctx['wind'] is None
        assert ctx['rain'] is None
        assert ctx['CO2_ext'] is None, '400 은 제어가 스스로 가정한다(situation.py)'
        assert ctx['RH_ext'] == 70.0, '고른 센서는 그대로'

    def test_옛_기본값_옵션은_없고_남은_값도_안_쓴다(self, collector):
        ids = {o['id'] for o in ecc.FUNCTION_INFORMATION['custom_options']}
        assert not ids & {'default_T_ext', 'default_RH_ext', 'default_wind'}
        # 업그레이드 전 DB 에 남은 값이 속성으로 붙어 있어도 쓰지 않는다
        collector.default_T_ext, collector.default_wind = 20.0, 0.0
        collector.sensor_temperature = collector.sensor_wind = None
        collector._collect_and_publish()
        ctx = ecc.get_shared_context()
        assert ctx['T_ext'] is None and ctx['wind'] is None

    def test_센서가_하나도_없으면_실외를_모르는_것으로_끝난다(self, collector):
        """수정 전: 센서 0개 수집기가 20 °C·60 % 를 '신선한 실측' 으로 영원히 냈다.

        끝단까지 본다 — 코디네이터가 그 공유값을 읽어 실외를 **지어낸 것**으로
        판정해야(fallback `_ext_synthetic`) 개구부가 제자리에 선다(2.6).
        """
        import logging
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
            CycleMixin)
        from aot.functions.utils.env_control.ext_context_fallback import (
            ExtContextCache, build_fallback_context)

        for k in ('sensor_temperature', 'sensor_humidity', 'sensor_wind', 'sensor_rain'):
            setattr(collector, k, None)
        collector._collect_and_publish()
        ctx = ecc.get_shared_context()
        assert all(v is None for k, v in ctx.items() if k != 'last_ext_ts')
        assert not ctx['last_ext_ts'], '온습도를 한 번도 못 받았다 — 신선이 아니다'

        class _Stub:
            logger = logging.getLogger('test.coord')
            _sensors_resolved_outdoor = []
            _ext_cache = ExtContextCache()

        external, _ = CycleMixin._collect_external_context(_Stub(), None)
        assert 'T_ext' not in external and 'T' not in external
        stale = (time.time() - external.get('last_ext_ts', 0.0)) > 300
        assert stale
        fb = build_fallback_context(_Stub._ext_cache, {'T': 25.0, 'RH': 80.0})
        assert fb['_ext_synthetic'] is True

    def test_온습도가_끊기면_last_ext_ts_는_옛_시각을_지킨다(self, collector):
        collector._collect_and_publish()
        first = ecc.get_shared_context()['last_ext_ts']
        collector.readings.update(t=None, rh=None)
        collector._collect_and_publish()
        assert ecc.get_shared_context()['last_ext_ts'] == first, (
            'now 로 덮으면 끊긴 온습도를 영영 신선으로 읽는다(수리 전 결함)')


class TestFreshnessGoesThroughTheOneRule:
    """판정은 `effective_max_age` — 장치값 > 요청 > 주기 파생 > 하한."""

    def test_장치값이_요청을_이긴다(self, collector, monkeypatch):
        monkeypatch.setattr(ecc._freshness, 'freshness_by_device',
                            lambda ids: {'wx': (60.0, 900)})
        collector.sensor_max_age = 120.0
        collector._collect_and_publish()
        assert collector.windows['t'] == 900

    def test_미지정이면_주기로_정한다(self, collector, monkeypatch):
        monkeypatch.setattr(ecc._freshness, 'freshness_by_device',
                            lambda ids: {'wx': (400.0, None)})
        collector.sensor_max_age = 0.0          # 0 = 안 정했다
        collector._collect_and_publish()
        assert collector.windows['t'] == 800

    def test_아무것도_모르면_하한(self, collector):
        collector._collect_and_publish()
        assert collector.windows['t'] == 300

    def test_옵션_기본값이_숫자가_아니다(self):
        opt = next(o for o in ecc.FUNCTION_INFORMATION['custom_options']
                   if o['id'] == 'sensor_max_age')
        assert not opt['default_value'], (
            '120 으로 되돌리면 기상청 300초·OpenWeather 600초 센서가 전부 만료된다')


class TestSharedContextAge:

    def test_한_번도_안_냈으면_지금_것이_아니다(self, collector):
        assert not ecc.shared_context_is_current()

    def test_수집기가_멈추면_지금_것이_아니게_된다(self, collector):
        collector._collect_and_publish()
        now = time.time()
        assert ecc.shared_context_is_current(now)
        assert ecc.shared_context_is_current(now + 290)
        assert not ecc.shared_context_is_current(now + 310), (
            '주기 60초 × 2 < 하한 300초 — 300초를 넘으면 멈춘 것이다')

    def test_코디네이터는_멈춘_공유값을_쓰지_않는다(self, collector, monkeypatch):
        import logging
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
            CycleMixin)
        from aot.functions.utils.env_control.ext_context_fallback import (
            ExtContextCache)

        collector.readings['rain'] = 3.0
        collector._collect_and_publish()

        class _Stub:
            logger = logging.getLogger('test.coord')
            _sensors_resolved_outdoor = []
            _ext_cache = ExtContextCache()

        external, _ = CycleMixin._collect_external_context(_Stub(), None)
        assert external.get('rain') == 3.0
        monkeypatch.setattr(ecc, '_shared_context_ts', time.time() - 3600)
        external, _ = CycleMixin._collect_external_context(_Stub(), None)
        assert 'rain' not in external, (
            '멈춘 수집기의 마지막 값을 쓰면 강우를 잃은 사실이 게이트에 안 닿는다')

    def test_값_없음은_키째_빠진다(self, collector):
        import logging
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
            CycleMixin)
        from aot.functions.utils.env_control.ext_context_fallback import (
            ExtContextCache)

        collector.readings['rain'] = None
        collector._collect_and_publish()

        class _Stub:
            logger = logging.getLogger('test.coord')
            _sensors_resolved_outdoor = []
            _ext_cache = ExtContextCache()

        external, _ = CycleMixin._collect_external_context(_Stub(), None)
        assert 'rain' not in external
        assert None not in external.values()
