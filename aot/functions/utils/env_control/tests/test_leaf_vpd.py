# coding=utf-8
"""잎 VPD 와 VPD 목표의 기준(공기/잎) — 식·목표 옮기기·엽온 판독·사이클 배선·화면 스냅숏.

  · 식: 잎–공기 VPD = svp(T_leaf) − RH·svp(T_air). 공기 RH 를 잎 포화압에 곱한 옛 계산
    (`auto_vpd`·`AoT_VPD`)은 잎이 찰 때 부풀고 따뜻할 때 줄었다.
  · 목표: 잎 기준이면 잰 엽온으로 공기 목표로 옮긴다. 엽온이 없거나 만료·멈춤·범위 밖·
    공기와 터무니없이 다르면 **그 사이클만** 공기 기준 — 고정 오프셋으로 어림하지 않는다.
  · 기본(공기 기준·엽온 미지정)은 종전과 완전히 같다: 읽기·기록·로그 없음.
"""
import logging

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import HelpersMixin
from aot.functions.utils.env_control import leaf_vpd as LV
from aot.functions.utils.env_control import psychro
from aot.functions.utils.env_control import sensor_status as SS
from aot.functions.utils.env_control.log_channels import (
    CH_LEAF_VPD, CH_LEAF_VPD_TARGET, CH_VPD_TARGET_BASIS)


# ─────────────────────────────────────────────────────────────────────────────
# 목표 기준 판정
# ─────────────────────────────────────────────────────────────────────────────

def _leaf(t, status=SS.VALID):
    return LV.LeafReading(t, status)


class TestResolve:
    def test_air_basis_is_unchanged(self):
        r = LV.resolve(0.9, 'air', 25.0, 70.0, _leaf(23.5))
        assert r.air_target == 0.9 and r.state == LV.TARGET_AIR and r.applied == 'air'
        assert r.leaf_vpd == pytest.approx(0.678, abs=0.002)      # 그래도 계산은 해 둔다

    def test_leaf_basis_translates(self):
        r = LV.resolve(0.8, 'leaf', 25.0, 70.0, _leaf(23.5))
        assert r.state == LV.TARGET_LEAF and r.applied == 'leaf'
        assert r.air_target == pytest.approx(
            0.8 + psychro.svp(25.0) - psychro.svp(23.5), rel=1e-12)
        assert r.target == 0.8 and not r.clamped

    @pytest.mark.parametrize('status', [SS.STALE, SS.MISSING, SS.FROZEN, SS.OUT_OF_RANGE,
                                        LV.LEAF_IMPLAUSIBLE, LV.LEAF_UNBOUND])
    def test_unusable_leaf_falls_back_to_air_for_the_cycle(self, status):
        r = LV.resolve(0.8, 'leaf', 25.0, 70.0, _leaf(None, status))
        assert r.state == LV.TARGET_LEAF_FALLBACK and r.applied == 'air'
        assert r.air_target == 0.8 and r.leaf_vpd is None and r.leaf_status == status

    def test_no_air_reading_falls_back(self):
        r = LV.resolve(0.8, 'leaf', None, 70.0, _leaf(23.5))
        assert r.state == LV.TARGET_LEAF_FALLBACK and r.air_target == 0.8

    def test_no_target_translates_nothing(self):
        r = LV.resolve(None, 'leaf', 25.0, 70.0, _leaf(23.5))
        assert r.state == LV.TARGET_LEAF and r.air_target is None and r.target is None

    def test_unreachable_leaf_target_is_floored(self):
        """잎이 공기보다 훨씬 따뜻하면 포화 공기에서도 목표를 넘는다 — 바닥에서 자른다."""
        r = LV.resolve(0.5, 'leaf', 30.0, 60.0, _leaf(36.0))
        assert r.clamped and r.air_target == LV.AIR_TARGET_MIN_KPA

    def test_unknown_basis_is_air(self):
        assert LV.normalise_basis('LEAF') == 'leaf'
        assert LV.normalise_basis('canopy') == 'air'
        assert LV.normalise_basis(None) == 'air'

    def test_classify_rejects_out_of_range_and_far_from_air(self):
        assert LV.classify_leaf(150.0, 25.0).status == SS.OUT_OF_RANGE
        assert LV.classify_leaf('x', 25.0).status == SS.OUT_OF_RANGE
        assert LV.classify_leaf(float('nan'), 25.0).status == SS.OUT_OF_RANGE
        assert LV.classify_leaf(36.0, 25.0).status == LV.LEAF_IMPLAUSIBLE
        ok = LV.classify_leaf(31.0, 25.0)
        assert ok.status == SS.VALID and ok.temp == 31.0

    def test_summary_is_json_shaped(self):
        s = LV.resolve(0.8, 'leaf', 25.0, 70.0, _leaf(23.5)).as_summary()
        assert s['state'] == 'leaf' and s['applied'] == 'leaf' and s['target'] == 0.8
        assert set(s) == {'basis', 'applied', 'state', 'target', 'air_target', 'leaf_vpd',
                          'leaf_temp', 'leaf_status', 'clamped'}


# ─────────────────────────────────────────────────────────────────────────────
# 사이클 배선
# ─────────────────────────────────────────────────────────────────────────────

class _Host(CycleMixin, HelpersMixin):
    pass


def _host(**opts):
    c = _Host.__new__(_Host)
    c.unique_id = 'fn-leaf'
    c.logger = logging.getLogger('test_leaf_vpd')
    c._status_calls = []
    c._status_log = lambda level, msg, *a: c._status_calls.append((level, msg % a if a else msg))
    c.sensor_max_age = None
    c._reading = {'value': 23.5, 'any': True}
    c._leaf_unit_cache = {'m': 'C'}

    def _glm(dev, meas, max_age=None):
        if c._reading['value'] is None:
            return ((1.0, 20.0) if (max_age is None and c._reading['any'])
                    else (None, None))
        c._reading['ts'] = c._reading.get('ts', 0.0) + 60.0
        return (c._reading['ts'], c._reading['value'])
    c.get_last_measurement = _glm
    for k, v in opts.items():
        setattr(c, k, v)
    return c


def _bound(**kw):
    base = dict(leaf_temp_signal_device_id='dev', leaf_temp_signal_measurement_id='m')
    base.update(kw)
    return base


@pytest.fixture
def logs(monkeypatch):
    rec = []
    monkeypatch.setattr(cycle_mod, 'write_decision_log',
                        lambda uid, meas, ch, val: rec.append((meas, ch, val)))
    return rec


@pytest.fixture(autouse=True)
def _fresh_lookup(monkeypatch):
    from aot.utils import measurement_freshness as mf
    monkeypatch.setattr(mf, 'freshness_by_device', lambda ids: {})


_INT = {'T': 25.0, 'RH': 70.0}


class TestCycleWiring:
    def test_default_does_nothing(self, logs):
        c = _host()
        c.get_last_measurement = lambda *a, **k: pytest.fail('읽지 않아야 한다')
        assert c._apply_vpd_target_basis(0.9, dict(_INT)) == 0.9
        assert logs == [] and c._status_calls == []
        assert c._last_vpd_target_basis is None

    def test_bound_air_basis_records_leaf_vpd_but_keeps_target(self, logs):
        c = _host(**_bound())
        assert c._apply_vpd_target_basis(0.9, dict(_INT)) == 0.9
        assert ('vpd_target_basis', CH_VPD_TARGET_BASIS, float(LV.TARGET_AIR)) in logs
        leaf = [v for m, ch, v in logs if ch == CH_LEAF_VPD]
        assert leaf and leaf[0] == pytest.approx(0.678, abs=0.002)
        assert not any(ch == CH_LEAF_VPD_TARGET for _m, ch, _v in logs)

    def test_leaf_basis_returns_translated_target_and_records_it(self, logs):
        c = _host(**_bound(vpd_target_basis='leaf'))
        out = c._apply_vpd_target_basis(0.8, dict(_INT))
        assert out == pytest.approx(0.8 + psychro.svp(25.0) - psychro.svp(23.5))
        assert ('leaf_vpd_target', CH_LEAF_VPD_TARGET, 0.8) in logs
        assert ('vpd_target_basis', CH_VPD_TARGET_BASIS, float(LV.TARGET_LEAF)) in logs
        assert c._status_calls and c._status_calls[0][0] == logging.INFO

    def test_stale_leaf_falls_back_and_announces_once(self, logs):
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._reading['value'] = None
        for _ in range(3):
            assert c._apply_vpd_target_basis(0.8, dict(_INT)) == 0.8
        assert c._last_vpd_target_basis.leaf_status == SS.STALE
        assert [lvl for lvl, _ in c._status_calls] == [logging.WARNING]
        assert [v for m, ch, v in logs if ch == CH_VPD_TARGET_BASIS] == \
            [float(LV.TARGET_LEAF_FALLBACK)] * 3

    def test_missing_leaf_is_missing_not_stale(self, logs):
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._reading.update(value=None, any=False)
        c._apply_vpd_target_basis(0.8, dict(_INT))
        assert c._last_vpd_target_basis.leaf_status == SS.MISSING

    def test_frozen_leaf_falls_back(self, logs):
        """시각은 새것인데 값이 몇 시간 한 점이면 멈춘 센서 — 옮기지 않는다."""
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._reading['value'] = 23.37
        tr = SS.tracker_of(c)
        out = None
        for i in range(40):
            tr.begin(1000.0 + i * 600.0, SS.LEVEL_QUIET)
            out = c._apply_vpd_target_basis(0.8, dict(_INT))
        assert c._last_vpd_target_basis.leaf_status == SS.FROZEN
        assert out == 0.8

    def test_implausible_leaf_falls_back(self, logs):
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._reading['value'] = 41.0                       # 기온 25 °C 와 16 °C 차이
        assert c._apply_vpd_target_basis(0.8, dict(_INT)) == 0.8
        assert c._last_vpd_target_basis.leaf_status == LV.LEAF_IMPLAUSIBLE

    def test_leaf_basis_without_a_sensor_warns_once(self, logs, caplog):
        c = _host(vpd_target_basis='leaf')
        with caplog.at_level(logging.ERROR, logger='test_leaf_vpd'):
            for _ in range(3):
                assert c._apply_vpd_target_basis(0.8, dict(_INT)) == 0.8
        assert sum('엽온 센서가 지정되지' in r.getMessage() for r in caplog.records) == 1
        assert c._last_vpd_target_basis.state == LV.TARGET_LEAF_FALLBACK

    def test_recovery_translates_again(self, logs):
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._reading['value'] = None
        c._apply_vpd_target_basis(0.8, dict(_INT))
        c._reading['value'] = 23.5
        out = c._apply_vpd_target_basis(0.8, dict(_INT))
        assert out > 0.8
        assert [lvl for lvl, _ in c._status_calls] == [logging.WARNING, logging.INFO]

    def test_leaf_jitter_is_smoothed(self, logs):
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._apply_vpd_target_basis(0.8, dict(_INT))
        c._reading['value'] = 23.8                        # 0.3 °C 흔들림 → EMA
        c._apply_vpd_target_basis(0.8, dict(_INT))
        assert c._last_vpd_target_basis.leaf_temp == pytest.approx(23.5 + 0.3 * 0.3)

    def test_fahrenheit_channel_is_converted(self, logs, monkeypatch):
        import aot.inputs.sensorutils as su
        monkeypatch.setattr(su, 'convert_from_x_to_y_unit',
                            lambda a, b, v: (v - 32.0) / 1.8 if (a, b) == ('F', 'C') else v)
        c = _host(**_bound(vpd_target_basis='leaf'))
        c._leaf_unit_cache = {'m': 'F'}
        c._reading['value'] = 74.3                        # 23.5 °C
        c._apply_vpd_target_basis(0.8, dict(_INT))
        assert c._last_vpd_target_basis.leaf_temp == pytest.approx(23.5, abs=1e-6)


def test_run_cycle_translates_before_decomposition():
    """목표를 옮기는 줄이 VPD 분해·목표 구성보다 **앞**이어야 한다."""
    import inspect
    src = inspect.getsource(CycleMixin._run_cycle)
    i = src.index('self._apply_vpd_target_basis(self._get_vpd_setpoint(), internal)')
    assert i < src.index('decompose_vpd_to_T_RH(')
    assert i < src.index('build_env_target(')


# ─────────────────────────────────────────────────────────────────────────────
# 화면 스냅숏
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshot:
    def test_default_marks_air_and_adds_no_leaf(self):
        c = _host()
        c._last_vpd_target_basis = None
        snap = {'indoor': {'temp_c': 25.0, 'humidity_pct': 70.0}}
        c._annotate_snapshot_vpd_basis(snap)
        assert snap['indoor']['vpd_target_basis'] == 'air'
        assert snap['indoor']['vpd_target_on'] == 'air'
        assert 'vpd_leaf_kpa' not in snap['indoor']

    def test_measured_leaf_is_added_from_the_snapshot_air(self):
        c = _host()
        c._last_vpd_target_basis = LV.resolve(0.8, 'leaf', 25.2, 69.0, _leaf(23.5))
        c._last_vpd_basis_ts = 1000.0
        snap = {'ts': 1010.0, 'indoor': {'temp_c': 25.0, 'humidity_pct': 70.0}}
        c._annotate_snapshot_vpd_basis(snap)
        ind = snap['indoor']
        assert ind['vpd_target_on'] == 'leaf' and ind['leaf_temp_c'] == 23.5
        assert ind['vpd_leaf_kpa'] == pytest.approx(psychro.leaf_vpd(23.5, 25.0, 70.0), abs=1e-3)

    def test_a_stale_judgement_is_not_shown_as_current(self):
        """게이트로 판정을 건너뛴 사이클이 이어지면 옛 잎 VPD 를 지금 것처럼 싣지 않는다."""
        c = _host(update_period=60.0)
        c._last_vpd_target_basis = LV.resolve(0.8, 'leaf', 25.0, 70.0, _leaf(23.5))
        c._last_vpd_basis_ts = 1000.0
        snap = {'ts': 1000.0 + 301.0, 'indoor': {'temp_c': 25.0, 'humidity_pct': 70.0}}
        c._annotate_snapshot_vpd_basis(snap)
        assert snap['indoor']['vpd_target_on'] == 'air'
        assert 'vpd_leaf_kpa' not in snap['indoor']

    def test_fallback_marks_the_target_on_air(self):
        c = _host()
        c._last_vpd_target_basis = LV.resolve(0.8, 'leaf', 25.0, 70.0,
                                              _leaf(None, SS.STALE))
        c._last_vpd_basis_ts = 1000.0
        snap = {'ts': 1010.0, 'indoor': {'temp_c': 25.0, 'humidity_pct': 70.0}}
        c._annotate_snapshot_vpd_basis(snap)
        assert snap['indoor']['vpd_target_basis'] == 'leaf'
        assert snap['indoor']['vpd_target_on'] == 'air'
        assert 'vpd_leaf_kpa' not in snap['indoor']


def test_channels_are_new_and_outside_the_sensor_status_block():
    from aot.functions.utils.env_control import log_channels as LC
    taken = {LC.CH_HEAT_PROTECT_TIER, LC.CH_HEAT_PROTECT_FLAGS, LC.CH_VPD_SOURCE,
             LC.CH_VPD_DEVICE_DIFF, LC.CH_WATER_SUPPLY, LC.CH_ACTUATOR_SUSPECT,
             LC.CH_GREYBOX_KPI_PASSED}
    mine = (CH_VPD_TARGET_BASIS, CH_LEAF_VPD, CH_LEAF_VPD_TARGET)
    assert mine == (94, 95, 96)
    assert not set(mine) & taken
    assert all(not 80 <= ch <= 91 for ch in mine)



# ─────────────────────────────────────────────────────────────────────────────
# AI 가 읽는 VPD 현황 — 공기는 늘, 잎은 잰 엽온이 있을 때만
# ─────────────────────────────────────────────────────────────────────────────

class TestReadoutFromSummary:
    def test_air_only_when_no_leaf_signal(self):
        out = LV.readout_from_summary({'photo': {'vpd': 0.874}, 'vpd_target': None})
        assert out == {'air_kpa': 0.87}

    def test_no_vpd_at_all_is_none(self):
        assert LV.readout_from_summary({'photo': {}}) is None
        assert LV.readout_from_summary(None) is None

    def test_measured_leaf_is_added_and_never_estimated(self):
        r = LV.resolve(0.8, 'air', 25.0, 70.0, _leaf(23.5))
        out = LV.readout_from_summary({'photo': {'vpd': 0.95}, 'vpd_target': r.as_summary()})
        assert out['air_kpa'] == 0.95
        assert out['leaf_kpa'] == pytest.approx(0.68, abs=0.01)
        assert out['leaf_temp_c'] == 23.5
        assert out['target_basis'] == 'air' and out['target_applied'] == 'air'
        assert 'target_kpa' not in out                 # 공기 기준이면 목표 변환 정보는 없다

    def test_leaf_basis_carries_both_targets(self):
        r = LV.resolve(0.8, 'leaf', 25.0, 70.0, _leaf(23.5))
        out = LV.readout_from_summary({'photo': {'vpd': 0.95}, 'vpd_target': r.as_summary()})
        assert out['target_basis'] == 'leaf' and out['target_applied'] == 'leaf'
        assert out['target_kpa'] == 0.8
        assert out['air_target_kpa'] == pytest.approx(r.air_target, abs=0.006)

    def test_leaf_basis_without_usable_leaf_temp_has_no_leaf_vpd(self):
        r = LV.resolve(0.8, 'leaf', 25.0, 70.0, _leaf(None, SS.STALE))
        out = LV.readout_from_summary({'photo': {'vpd': 0.95}, 'vpd_target': r.as_summary()})
        assert 'leaf_kpa' not in out and 'leaf_temp_c' not in out
        assert out['target_basis'] == 'leaf' and out['target_applied'] == 'air'
