# coding=utf-8
"""멈춘 센서(frozen) 판정 — 시각은 새것인데 값이 한 점에 붙은 센서를 제어에서 뺀다.

고정하는 것:
  1. 창 — 낮·장치 이동 중엔 60분, 조용한 밤엔 3시간, CO2 는 2시간. 해상도 이내의 흔들림은
     "그대로" 이고, 서로 다른 시각의 표본이 `FROZEN_MIN_SAMPLES` 개는 와야 한다.
  2. 복귀 — 값이 해상도 밖으로 움직이면 곧바로 valid.
  3. 센서가 둘이면 멈춘 쪽만 평균에서 빠지고, 하나뿐이면 축이 비어 '측정 없음' 경로를 탄다.
  4. 같은 표본을 되읽는 느린 장치(시각 불변)는 멈춘 것이 아니다. 포화한 습도(100 %)도 아니다.
  5. 추적기를 안 넘기는 경로(화면)는 종전 그대로다.
  6. 전환은 한 번만 남는다(로그), 상태 코드 5, 건강 점검 라벨.
"""
from unittest.mock import MagicMock, patch

import pytest

import aot.aot_flask.geo.facility_sensors as fs
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)
from aot.functions.utils.env_control import sensor_status as SS


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(fs, '_freshness_by_device', lambda ids: {})


MIN = 60.0
HOUR = 3600.0
STEP = 10 * MIN          # 코디네이터 주기 10분


def _feed(tr, key, kind, values, *, t0=0.0, step=STEP, active=False, new_ts=True):
    """값 목록을 주기마다 한 번씩 먹인다. 마지막 판정과 끝 시각을 돌려준다."""
    out, t = False, t0
    for i, v in enumerate(values):
        t = t0 + i * step
        tr.begin(t, active)
        out = tr.observe(key, kind, v, (t - 10.0) if new_ts else 1.0)
    return out, t


def _first_frozen(tr, key, kind, *, active, value=30.7, step=STEP, limit=60 * HOUR):
    """같은 값을 먹여 처음 멈춤으로 판정되는 경과 시간(초)."""
    t = 0.0
    while t <= limit:
        tr.begin(t, active)
        if tr.observe(key, kind, value, t - 10.0):
            return t
        t += step
    return None


KEY = ('dev', 'mT')


# ─────────────────────────────────────────────────────────────────────────────
# 1. 창
# ─────────────────────────────────────────────────────────────────────────────

class TestWindows:

    def test_낮에는_60분_뒤에_멈춘_것으로_본다(self):
        t = _first_frozen(SS.FrozenTracker(), KEY, 'T', active=True)
        assert t == 60 * MIN

    def test_조용한_밤에는_3시간_뒤에_멈춘_것으로_본다(self):
        t = _first_frozen(SS.FrozenTracker(), KEY, 'T', active=False)
        assert t == 3 * HOUR

    def test_RH도_온도와_같은_창이다(self):
        assert _first_frozen(SS.FrozenTracker(), KEY, 'RH', active=True, value=70.3) == HOUR
        assert _first_frozen(SS.FrozenTracker(), KEY, 'RH', active=False, value=70.3) == 3 * HOUR

    def test_VPD는_독립으로_재지_않는다(self):
        """밤 포화 근처 VPD 는 몇 시간 안 움직인다 — 실측에서 정상 센서가 멈춘 것으로 잡혔다."""
        out, _t = _feed(SS.FrozenTracker(), KEY, 'VPD', [0.07] * 80, active=True)
        assert out is False
        assert 'VPD' not in SS.FROZEN_KINDS

    def test_CO2는_낮밤_없이_2시간(self):
        assert _first_frozen(SS.FrozenTracker(), KEY, 'CO2', active=True, value=800.0) == 2 * HOUR
        assert _first_frozen(SS.FrozenTracker(), KEY, 'CO2', active=False, value=800.0) == 2 * HOUR

    def test_낮밤이_섞이면_창이_비율로_쌓인다(self):
        """낮 30분(0.5) + 밤 90분(0.5) = 한 창 — 낮밤 경계에서 세기가 새로 시작되지 않는다."""
        tr = SS.FrozenTracker()
        t, frozen_at = 0.0, None
        while t <= 6 * HOUR:
            tr.begin(t, t <= 30 * MIN)
            if tr.observe(KEY, 'T', 30.7, t - 10.0):
                frozen_at = t
                break
            t += STEP
        assert frozen_at == 120 * MIN

    def test_창이_차기_전에는_멈춘_것이_아니다(self):
        tr = SS.FrozenTracker()
        out, _t = _feed(tr, KEY, 'T', [30.7] * 6, active=True)       # 50분
        assert out is False
        assert tr.frozen_keys == {}

    def test_조용한_밤_2시간은_멈춘_것이_아니다(self):
        out, _t = _feed(SS.FrozenTracker(), KEY, 'T', [18.0] * 13, active=False)   # 120분
        assert out is False

    def test_검사_대상이_아닌_물리량은_절대_멈추지_않는다(self):
        tr = SS.FrozenTracker()
        out, _t = _feed(tr, ('d', 'wind'), 'wind', [0.0] * 100, active=True)
        assert out is False
        out, _t = _feed(tr, ('d', 'light'), 'light', [0.0] * 100, active=True)
        assert out is False

    def test_창_상수는_단계가_조용할수록_길다(self):
        for k in SS.FROZEN_KINDS:
            w = SS.FROZEN_WINDOW_S[k]
            assert w[SS.LEVEL_DAY] <= w[SS.LEVEL_MOVED] <= w[SS.LEVEL_QUIET]
            assert k in SS.FROZEN_RESOLUTION

    def test_밤에_장치가_움직였으면_2시간이다(self):
        """60분은 실측 최장(온도 1.0시간)과 같아 오탐 여지가 있다 — 밤의 장치 이동은 낮보다 길다."""
        t = _first_frozen(SS.FrozenTracker(), KEY, 'T', active=SS.LEVEL_MOVED)
        assert t == 2 * HOUR

    def test_알_수_없는_단계는_조용한_밤으로_본다(self):
        tr = SS.FrozenTracker()
        tr.begin(0.0, 'whatever')
        assert tr.level == SS.LEVEL_QUIET


# ─────────────────────────────────────────────────────────────────────────────
# 2. 해상도·표본·복귀
# ─────────────────────────────────────────────────────────────────────────────

class TestCoarseResolution:
    """정수 눈금 센서 — 실측: 영양·김제 습도는 전부 정수이고 밤에 같은 정수가 4.5시간 이어졌다."""

    def test_정수만_내는_습도는_창이_3배다(self):
        assert _first_frozen(SS.FrozenTracker(), KEY, 'RH', active=True, value=70.0) == 3 * HOUR
        assert _first_frozen(SS.FrozenTracker(), KEY, 'RH', active=False, value=70.0) == 9 * HOUR

    def test_실측_정수_습도_밤_고원_4_5시간은_멈춘_것이_아니다(self):
        out, _t = _feed(SS.FrozenTracker(), KEY, 'RH', [94.0] * 28, active=False)   # 4.5시간
        assert out is False

    def test_정수_눈금_온도도_같다(self):
        assert _first_frozen(SS.FrozenTracker(), KEY, 'T', active=False, value=18.0) == 9 * HOUR

    def test_소수_값을_한_번이라도_낸_센서는_정밀_센서다(self):
        tr = SS.FrozenTracker()
        _feed(tr, KEY, 'T', [18.0, 18.0, 18.3, 18.0], active=True)       # 18.3 이 정밀임을 알린다
        out, _t = _feed(tr, KEY, 'T', [18.0] * 8, t0=4 * STEP, active=True)
        assert out is True                                               # 60분 창으로 잡힌다

    def test_정밀_센서는_정수_값에_걸려도_창이_그대로다(self):
        tr = SS.FrozenTracker()
        _feed(tr, KEY, 'RH', [70.3, 70.4, 70.0, 70.0, 70.0], active=True)
        out, _t = _feed(tr, KEY, 'RH', [70.0] * 8, t0=5 * STEP, active=True)
        assert out is True

    def test_CO2는_정수가_원래_눈금이라_배수를_안_쓴다(self):
        assert _first_frozen(SS.FrozenTracker(), KEY, 'CO2', active=False, value=800.0) == 2 * HOUR


class TestResolutionAndSamples:

    def test_해상도_이내의_흔들림은_그대로로_본다(self):
        vals = [30.70, 30.72, 30.69, 30.74, 30.70, 30.74, 30.71, 30.70]   # 모두 ±0.05 이내
        out, _t = _feed(SS.FrozenTracker(), KEY, 'T', vals + [30.7] * 4, active=True)
        assert out is True

    def test_해상도를_넘는_움직임은_센기를_처음부터_다시_한다(self):
        tr = SS.FrozenTracker()
        _feed(tr, KEY, 'T', [30.7] * 6, active=True)                 # 50분 쌓임
        out, _t = _feed(tr, KEY, 'T', [30.9] + [30.9] * 3, t0=6 * STEP, active=True)
        assert out is False                                          # 새 기준점에서 다시

    def test_천천히_흘러도_기준점에서_해상도를_넘으면_센기가_리셋된다(self):
        vals = [30.0 + 0.04 * i for i in range(20)]    # 매번 0.04 — 기준점에서는 곧 멀어진다
        out, _t = _feed(SS.FrozenTracker(), KEY, 'T', vals, active=True)
        assert out is False

    def test_같은_표본을_되읽는_느린_장치는_멈춘_것이_아니다(self):
        """40분 주기 노드를 10분마다 읽는다 — 시각이 안 변하는 사이클은 표본이 아니다.

        3시간(창)이 찼어도 서로 다른 표본이 5개뿐이면 판정하지 않는다."""
        tr = SS.FrozenTracker()
        out = False
        for i in range(19):                              # 0~3시간
            tr.begin(i * STEP, False)
            out = tr.observe(KEY, 'T', 21.3, 1000.0 + 2400.0 * (i // 4))
        assert out is False
        # 시각이 영영 같으면(표본 1개) 시간이 아무리 흘러도 판정하지 않는다
        tr2 = SS.FrozenTracker()
        for i in range(60):
            tr2.begin(i * STEP, False)
            out2 = tr2.observe(KEY, 'T', 21.3, 1000.0)
        assert out2 is False

    def test_표본이_충분하면_느린_장치도_판정한다(self):
        tr = SS.FrozenTracker()
        out = False
        for i in range(40):
            t = i * STEP
            tr.begin(t, False)
            out = tr.observe(KEY, 'T', 21.3, 1000.0 + 1800.0 * (i // 3))   # 30분마다 새 표본
        assert out is True

    def test_포화한_습도는_멈춘_것이_아니다(self):
        out, _t = _feed(SS.FrozenTracker(), KEY, 'RH', [100.0] * 60, active=False)
        assert out is False
        out, _t = _feed(SS.FrozenTracker(), KEY, 'RH', [99.6] * 60, active=False)
        assert out is False

    def test_멈춘_뒤_값이_바뀌면_곧바로_복귀한다(self):
        tr = SS.FrozenTracker()
        out, t = _feed(tr, KEY, 'T', [30.7] * 8, active=True)
        assert out is True
        assert KEY in tr.frozen_keys
        tr.begin(t + STEP, True)
        assert tr.observe(KEY, 'T', 31.4, t + STEP - 10.0) is False
        assert tr.frozen_keys == {}

    def test_복귀한_뒤_다시_멈추면_창을_처음부터_채운다(self):
        tr = SS.FrozenTracker()
        _feed(tr, KEY, 'T', [30.7] * 8, active=True)
        _feed(tr, KEY, 'T', [33.0] * 3, t0=8 * STEP, active=True)
        out, _t = _feed(tr, KEY, 'T', [33.0] * 2, t0=11 * STEP, active=True)   # 새로 40분
        assert out is False

    def test_이미_멈춘_센서는_관측_공백_뒤에도_같은_값이면_멈춘_채다(self):
        tr = SS.FrozenTracker()
        out, t = _feed(tr, KEY, 'T', [30.7] * 8, active=True)
        assert out is True
        tr.begin(t + 5 * HOUR, False)
        assert tr.observe(KEY, 'T', 30.7, t + 5 * HOUR - 10.0) is True

    def test_멈추기_전의_긴_관측_공백은_처음부터_다시_센다(self):
        """코디네이터가 꺼져 있던 사이 값이 움직였는지 모른다 — 쌓인 것을 버린다."""
        tr = SS.FrozenTracker()
        _feed(tr, KEY, 'T', [30.7] * 6, active=True)
        tr.begin(5 * STEP + 2 * HOUR, True)
        assert tr.observe(KEY, 'T', 30.7, 5 * STEP + 2 * HOUR - 10.0) is False
        out, _t = _feed(tr, KEY, 'T', [30.7] * 5, t0=5 * STEP + 2 * HOUR + STEP, active=True)
        assert out is False                                          # 50분밖에 안 쌓였다

    def test_센서마다_따로_센다(self):
        tr = SS.FrozenTracker()
        t = 0.0
        a = b = False
        for i in range(10):
            t = i * STEP
            tr.begin(t, True)
            a = tr.observe(('d', 'a'), 'T', 30.7, t - 10)
            b = tr.observe(('d', 'b'), 'T', 22.0 + 0.3 * i, t - 10)
        assert a is True and b is False

    def test_숫자가_아닌_값은_판정하지_않는다(self):
        tr = SS.FrozenTracker()
        assert tr.observe(KEY, 'T', None, 1.0) is False
        assert tr.observe(KEY, 'T', float('nan'), 1.0) is False
        assert tr.observe(KEY, 'T', 'x', 1.0) is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. 낮·장치 이동 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestActivity:

    class _Coord:
        pass

    def _coord(self, solar=None, moved=None):
        c = self._Coord()
        c._ext_cache = MagicMock(values={'solar': solar} if solar is not None else {})
        if moved is not None:
            c._dispatch_moved = moved
        return c

    def test_일사가_100을_넘으면_낮이다(self):
        assert SS.frozen_activity(self._coord(solar=150.0), 1000.0) == SS.LEVEL_DAY
        assert SS.frozen_activity(self._coord(solar=100.0), 1000.0) == SS.LEVEL_QUIET
        assert SS.frozen_activity(self._coord(solar=5.0), 1000.0) == SS.LEVEL_QUIET

    def test_인자로_준_일사가_캐시보다_먼저다(self):
        c = self._coord(solar=0.0)
        assert SS.frozen_activity(c, 1000.0, solar=400.0) == SS.LEVEL_DAY

    def test_최근_장치가_움직였으면_moved(self):
        now = 10_000.0
        assert SS.frozen_activity(self._coord(moved={'a': now - 600}), now) == SS.LEVEL_MOVED
        assert SS.frozen_activity(self._coord(moved={'a': now - 3600}), now) == SS.LEVEL_QUIET

    def test_낮이면_장치_이동보다_낮이_앞이다(self):
        c = self._coord(solar=300.0, moved={'a': 9_900.0})
        assert SS.frozen_activity(c, 10_000.0) == SS.LEVEL_DAY

    def test_아무것도_모르면_조용한_밤이다(self):
        c = self._Coord()
        assert SS.frozen_activity(c, 1000.0) == SS.LEVEL_QUIET

    def test_MagicMock_코디네이터에도_터지지_않는다(self):
        assert SS.frozen_activity(MagicMock(), 1000.0) in (
            SS.LEVEL_DAY, SS.LEVEL_MOVED, SS.LEVEL_QUIET)
        tr = SS.tracker_of(MagicMock())
        assert isinstance(tr, SS.FrozenTracker)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 읽기 경로 — 평균에서 빠진다
# ─────────────────────────────────────────────────────────────────────────────

def _sensor(uuid, mid, mtype):
    return {'fitting_id': 'fit-' + mid, 'name': mtype, 'position': None,
            'sensor_role': 'indoor', 'measurement_type': mtype,
            'input_uuid': uuid, 'measurement_id': mid,
            'input_name': None, 'input_device': None}


class _Clock:
    """읽기 함수가 돌려줄 값·시각을 사이클마다 정한다."""

    def __init__(self):
        self.t = 0.0
        self.values = {}
        self.fixed_ts = {}

    def glm(self, device_id, measurement_id, max_age=None):
        if measurement_id not in self.values:
            return [None, None]
        return [self.fixed_ts.get(measurement_id, self.t - 10.0), self.values[measurement_id]]


def _run_spatial(sensors, clock, tr, cycles, step=STEP, active=True, update=None, **kw):
    """사이클을 돌린다. update(i, clock) 이 사이클마다 값을 갱신한다. 마지막 결과를 돌려준다."""
    out = None
    for i in range(cycles):
        clock.t = i * step
        if update:
            update(i, clock)
        tr.begin(clock.t, active)
        with patch('aot.utils.influx.get_last_measurement', side_effect=clock.glm):
            out = fs.compute_spatial_internal(sensors, max_age=300, frozen=tr,
                                              with_status=True, **kw)
    return out


T2 = [_sensor('d1', 'm1', 'temperature'), _sensor('d2', 'm2', 'temperature')]
T1 = [_sensor('d1', 'm1', 'temperature')]


class TestSpatialPath:

    def test_멈춘_센서는_평균에서_빠지고_나머지가_이어간다(self):
        clock = _Clock()
        tr = SS.FrozenTracker()

        def upd(i, c):
            c.values['m1'] = 30.7                        # 멈춤
            c.values['m2'] = 40.0 + 0.5 * i              # 살아 있음 — 실제 온실은 뜨거워진다
        sp = _run_spatial(T2, clock, tr, 10, update=upd)
        assert sp['T'] == pytest.approx(44.5)             # m2 의 마지막 값만
        st = sp['status']['T']
        assert st['counts'] == {SS.VALID: 1, SS.FROZEN: 1}
        assert st['status'] == SS.VALID                   # 축은 쓸 수 있는 것 중 최선
        assert sp['detail'][0]['status']['T'] == SS.FROZEN
        assert sp['rejected_count'] == 0                  # 이상치(MAD)로 세지 않는다

    def test_센서가_하나뿐이면_축이_비고_frozen_이다(self):
        clock = _Clock()

        def upd(i, c):
            c.values['m1'] = 30.7
        sp = _run_spatial(T1, clock, SS.FrozenTracker(), 10, update=upd)
        assert sp['T'] is None
        assert sp['status']['T']['status'] == SS.FROZEN
        assert sp['T_max'] is None

    def test_멈춤_전에는_정상_센서와_똑같다(self):
        clock = _Clock()

        def upd(i, c):
            c.values['m1'] = 30.7
        sp = _run_spatial(T1, clock, SS.FrozenTracker(), 5, update=upd)    # 40분
        assert sp['T'] == 30.7
        assert sp['status']['T']['status'] == SS.VALID

    def test_값이_움직이면_곧바로_돌아온다(self):
        clock = _Clock()
        tr = SS.FrozenTracker()

        def freeze(i, c):
            c.values['m1'] = 30.7
        sp = _run_spatial(T1, clock, tr, 10, update=freeze)
        assert sp['T'] is None

        def move(i, c):
            c.values['m1'] = 45.0
        clock.t = 10 * STEP
        sp = _run_spatial(T1, clock, tr, 1, update=move)
        assert sp['T'] == 45.0
        assert sp['status']['T']['status'] == SS.VALID

    def test_추적기를_안_넘기면_멈춘_값도_종전처럼_쓴다(self):
        """화면 경로는 상태를 갖지 않는다 — 종전 동작 그대로."""
        clock = _Clock()
        clock.values['m1'] = 30.7
        for i in range(30):
            clock.t = i * STEP
            with patch('aot.utils.influx.get_last_measurement', side_effect=clock.glm):
                sp = fs.compute_spatial_internal(T1, max_age=300)
        assert sp['T'] == 30.7

    def test_멈춘_장치의_VPD도_빠져서_장치_VPD_폴백이_멈춘_값을_되살리지_못한다(self):
        sensors = [_sensor('d1', 'mT', 'temperature'), _sensor('d1', 'mRH', 'humidity'),
                   _sensor('d1', 'mV', 'vpd')]
        clock = _Clock()

        def upd(i, c):
            c.values.update({'mT': 30.57, 'mRH': 62.57, 'mV': 1.337})
        sp = _run_spatial(sensors, clock, SS.FrozenTracker(), 10, update=upd)
        assert sp['T'] is None and sp['RH'] is None
        assert sp['VPD_device'] is None and sp['VPD'] is None
        assert sp['status']['VPD']['status'] == SS.FROZEN

    def test_다른_장치의_VPD는_영향이_없다(self):
        sensors = [_sensor('d1', 'mT', 'temperature'), _sensor('d2', 'mV', 'vpd')]
        clock = _Clock()

        def upd(i, c):
            c.values.update({'mT': 30.57, 'mV': 1.0 + 0.01 * i})
        sp = _run_spatial(sensors, clock, SS.FrozenTracker(), 10, update=upd)
        assert sp['T'] is None
        assert sp['VPD_device'] == pytest.approx(1.09)

    def test_장치가_회복하면_VPD도_돌아온다(self):
        sensors = [_sensor('d1', 'mT', 'temperature'), _sensor('d1', 'mV', 'vpd')]
        clock = _Clock()
        tr = SS.FrozenTracker()

        def freeze(i, c):
            c.values.update({'mT': 30.57, 'mV': 1.337})
        _run_spatial(sensors, clock, tr, 10, update=freeze)

        def move(i, c):
            c.values.update({'mT': 41.0, 'mV': 2.5})
        clock.t = 10 * STEP
        sp = _run_spatial(sensors, clock, tr, 2, update=move)
        assert sp['T'] == 41.0 and sp['VPD_device'] == 2.5

    def test_RH와_CO2도_센다(self):
        sensors = [_sensor('d1', 'mRH', 'humidity'), _sensor('d1', 'mCO2', 'co2')]
        clock = _Clock()

        def upd(i, c):
            c.values['mRH'] = 55.3
            c.values['mCO2'] = 600.0
        sp = _run_spatial(sensors, clock, SS.FrozenTracker(), 14, update=upd)   # 130분
        assert sp['RH'] is None and sp['status']['RH']['status'] == SS.FROZEN
        assert sp['CO2'] is None and sp['status']['CO2']['status'] == SS.FROZEN

    def test_일사_광량은_멈춰도_본다(self):
        sensors = [_sensor('d1', 'mL', 'light')]
        clock = _Clock()

        def upd(i, c):
            c.values['mL'] = 0.0
        sp = _run_spatial(sensors, clock, SS.FrozenTracker(), 60, update=upd)
        assert sp['light'] == 0.0

    def test_시각이_안_변하는_센서는_멈춤이_아니라_만료의_몫이다(self):
        clock = _Clock()
        clock.fixed_ts['m1'] = 5.0

        def upd(i, c):
            c.values['m1'] = 30.7
        sp = _run_spatial(T1, clock, SS.FrozenTracker(), 40, update=upd, step=STEP)
        # 표본이 하나뿐이라 멈춤 판정이 서지 않는다(만료는 max_age 가 가른다)
        assert SS.FROZEN not in sp['status']['T']['counts']


class TestOutdoorPath:

    OUT = [dict(_sensor('o1', 'oT', 'temperature'), sensor_role='outdoor'),
           dict(_sensor('o1', 'oRH', 'humidity'), sensor_role='outdoor')]

    def test_실외_T_RH도_멈추면_축이_frozen(self):
        clock = _Clock()
        tr = SS.FrozenTracker()
        od = None
        for i in range(10):
            clock.t = i * STEP
            clock.values.update({'oT': 12.3, 'oRH': 80.4})
            tr.begin(clock.t, True)
            with patch('aot.utils.influx.get_last_measurement', side_effect=clock.glm):
                od = fs.read_outdoor_sensors(self.OUT, max_age=300, with_status=True,
                                             frozen=tr)
        assert od['T_ext'] is None and od['RH_ext'] is None
        assert od['status']['T_ext']['status'] == SS.FROZEN
        assert od['status']['RH_ext']['status'] == SS.FROZEN

    def test_움직이는_실외는_영향이_없다(self):
        clock = _Clock()
        tr = SS.FrozenTracker()
        od = None
        for i in range(30):
            clock.t = i * STEP
            clock.values.update({'oT': 12.0 + 0.2 * i, 'oRH': 80.0 - 0.5 * i})
            tr.begin(clock.t, False)
            with patch('aot.utils.influx.get_last_measurement', side_effect=clock.glm):
                od = fs.read_outdoor_sensors(self.OUT, max_age=300, with_status=True,
                                             frozen=tr)
        assert od['T_ext'] is not None
        assert od['status']['T_ext']['status'] == SS.VALID


class TestRoleFallbackDoesNotResurrect:

    def test_역할_폴백도_멈춘_센서의_값을_되살리지_않는다(self):
        bindings = [{'role': 'indoor_temp', 'device_id': 'd1', 'measurement_id': 'm1'}]
        clock = _Clock()
        tr = SS.FrozenTracker()
        out = None
        for i in range(10):
            clock.t = i * STEP
            clock.values['m1'] = 30.7
            tr.begin(clock.t, True)
            with patch.object(fs, 'get_last_measurement', side_effect=clock.glm):
                out = fs.read_facility_sensors(bindings, max_age=300, frozen=tr)
        assert out['indoor']['temp_c'] is None
        assert out['sensors'][0]['degraded_reason'] == SS.FROZEN


# ─────────────────────────────────────────────────────────────────────────────
# 5. 코디네이터 흐름 — 축 상태·로그
# ─────────────────────────────────────────────────────────────────────────────

def _coordinator(sensors):
    obj = MagicMock()
    obj._collect_internal = HelpersMixin._collect_internal.__get__(obj)
    obj._sensors_resolved = sensors
    obj._sensors_resolved_outdoor = []
    obj.logger = MagicMock()
    obj.debug_logging = False
    obj._vpd_ema = None
    obj._t_ema = None
    obj._rh_ema = None
    obj._frozen_tracker = None
    obj._ext_cache = MagicMock(values={'solar': 600.0})      # 낮
    return obj


class TestCoordinatorFlow:

    def _cycle(self, obj, clock, i, values):
        clock.t = i * STEP
        clock.values.update(values)
        with patch('time.time', return_value=clock.t), \
                patch('aot.utils.influx.get_last_measurement', side_effect=clock.glm):
            return obj._collect_internal(300.0)

    def test_멈춘_실내_온도가_빠져_측정_없음_경로로_간다(self):
        obj = _coordinator(T1 + [_sensor('d3', 'mRH', 'humidity')])
        clock = _Clock()
        res = None
        for i in range(10):
            res = self._cycle(obj, clock, i, {'m1': 30.7, 'mRH': 60.0 - 0.3 * i})
        assert 'T' not in res                       # 센서가 하나뿐이니 축이 빈다
        assert 'RH' in res
        assert obj._indoor_status['T']['status'] == SS.FROZEN
        assert obj._indoor_status['RH']['status'] == SS.VALID

    def test_전환은_한_번만_로그에_남는다(self):
        obj = _coordinator(T1)
        clock = _Clock()
        for i in range(14):
            self._cycle(obj, clock, i, {'m1': 30.7})
        msgs = [c.args[0] for c in obj.logger.error.call_args_list]
        assert sum('멈췄습니다' in m for m in msgs) == 1
        # 값이 돌아오면 회복도 한 번
        for i in range(14, 17):
            self._cycle(obj, clock, i, {'m1': 40.0 + i})
        msgs = [c.args[0] for c in obj.logger.error.call_args_list]
        assert sum('다시 움직입니다' in m for m in msgs) == 1
        assert sum('멈췄습니다' in m for m in msgs) == 1

    def test_정상_센서는_아무것도_남기지_않는다(self):
        obj = _coordinator(T1)
        clock = _Clock()
        for i in range(30):
            res = self._cycle(obj, clock, i, {'m1': 22.0 + 0.3 * i})
        assert res['T_raw'] == pytest.approx(22.0 + 0.3 * 29)
        obj.logger.error.assert_not_called()

    def test_밤에는_창이_길어_같은_시간에_아직_멈춤이_아니다(self):
        obj = _coordinator(T1)
        obj._ext_cache = MagicMock(values={'solar': 0.0})        # 밤
        clock = _Clock()
        for i in range(10):                                       # 90분
            res = self._cycle(obj, clock, i, {'m1': 18.3})
        assert 'T' in res
        assert obj._indoor_status['T']['status'] == SS.VALID


# ─────────────────────────────────────────────────────────────────────────────
# 6. 상태 코드·건강 점검
# ─────────────────────────────────────────────────────────────────────────────

class TestCodes:

    def test_frozen_의_코드는_5이고_기존_코드는_그대로다(self):
        assert SS.STATUS_CODES[SS.FROZEN] == 5
        assert [SS.STATUS_CODES[s] for s in (SS.VALID, SS.STALE, SS.MISSING,
                                             SS.OUTLIER, SS.OUT_OF_RANGE)] == [0, 1, 2, 3, 4]

    def test_축_요약의_인코딩(self):
        assert SS.encode(SS.summarize([SS.FROZEN])) == 5
        assert SS.encode(SS.summarize([SS.FROZEN, SS.VALID])) == 0     # 최선

    def test_frozen_은_missing_보다_낫고_out_of_range_보다_앞이다(self):
        assert SS.best_status([SS.MISSING, SS.FROZEN]) == SS.FROZEN
        assert SS.best_status([SS.OUT_OF_RANGE, SS.FROZEN]) == SS.FROZEN
        assert SS.best_status([SS.OUTLIER, SS.FROZEN]) == SS.OUTLIER

    def test_로그_채널_인코딩이_모든_상태를_덮는다(self):
        assert set(SS.STATUS_ORDER) == set(SS.STATUS_CODES)
