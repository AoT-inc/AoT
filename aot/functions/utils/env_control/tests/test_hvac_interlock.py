# coding=utf-8
"""
test_hvac_interlock.py — 냉·난방 가동 중 개구부 잠금 (hvac_interlock).

냉난방과 환기가 맞서면 에너지를 그대로 버린다. 환기 무익 게이트는 이 경우를
못 잡는다 — 환기가 목표 방향으로 '유효'하기 때문이다(도달 가능성 문제가
아니라 에너지 상충 문제). 그래서 별도 옵션이다.

가장 까다로운 부분은 판정 근거다. 사람이 벽 스위치로 켜는 냉방기는 앱이
전기적으로 아무것도 모른다. 온도 추론은 실측에서 기각됐다(모듈 주석 참조).
여기서는 (a) 근거가 있을 때만 잠그고 (b) 근거가 사라지면 반드시 풀리는지를
고정한다 — 후자가 안전 속성이다.
"""

from unittest.mock import MagicMock

from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)
from aot.functions.utils.env_control.coordinator import (
    REASON_NO_GRADIENT,
    REASON_PRIMARY,
    CoordinatorState,
    coordinate,
)
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.situation import assess, compute_vpd
from aot.functions.utils.env_control.types import TargetVar

from .conftest import make_ctx, make_opening_profile

# 습식 냉방이 25도/85% 로 붙잡은 실내 + 어제 09시 실외 실측.
# 실내 VPD 0.48 < 목표 0.78 이고 실외 VPD 1.27 이라 환기가 목표 방향으로
# '유효'하다 — 무익 게이트로는 절대 안 잡히는 조건이다.
INDOOR = dict(T_int=25.0, RH_int=85.0)
OUTDOOR = dict(T_ext=29.9, RH_ext=69.9)
VPD_TARGET, VPD_TOL = 0.78, 0.1


def _vent(aid='v1'):
    p = make_opening_profile(aid)
    p.effect_model = build_effect_model('opening', {})
    return p


def _cycle(profile, state, *, interlock=False, running=False, futility=True):
    vpd_int = compute_vpd(INDOOR['T_int'], INDOOR['RH_int'])
    ctx = make_ctx(VPD_int=vpd_int, **INDOOR, **OUTDOOR)
    target = {'vpd': TargetVar(value=VPD_TARGET, tolerance=VPD_TOL,
                               priority=1.2, unit='kPa')}
    report, _ = assess(target, dict(ctx['internal'], VPD=vpd_int),
                       ctx['external'], cycle_sec=600.0, now_ts=ctx['now_ts'])
    report.context['vent_futility_gate'] = futility
    report.context['hvac_interlock'] = interlock
    report.context['hvac_running'] = running
    cmds, state = coordinate(report, [profile], state)
    return cmds[profile.actuator_id], state


def _state(start=60.0, aid='v1'):
    st = CoordinatorState()
    st.integral[aid] = start
    st.prev_commands[aid] = start
    return st


class TestInterlockBehaviour:
    def test_futility_gate_alone_does_not_catch_this(self):
        """전제 확인 — 이 조건에서 무익 게이트는 발동하지 않는다."""
        cmd, _st = _cycle(_vent(), _state(), interlock=False, futility=True)
        assert cmd.reason == REASON_PRIMARY
        assert cmd.aperture > 50.0, '환기가 유효하므로 창은 열려 있어야 한다'

    def test_interlock_parks_vents_while_running(self):
        """냉난방 가동 중이면 개구부를 잠근다."""
        cmd, _st = _cycle(_vent(), _state(), interlock=True, running=True)
        assert cmd.reason == REASON_NO_GRADIENT
        assert cmd.aperture < 60.0

    def test_interlock_converges_closed(self):
        """여러 사이클에 걸쳐 닫힘으로 수렴한다."""
        p, st = _vent(), _state()
        traj = []
        for _ in range(15):
            cmd, st = _cycle(p, st, interlock=True, running=True)
            st.prev_commands['v1'] = cmd.aperture
            traj.append(cmd.aperture)
        assert traj[-1] == 0.0, f'닫힘 수렴 실패: {traj[-4:]}'

    def test_releases_immediately_when_hvac_stops(self):
        """가동이 멈추면 잠금이 풀리고 정상 제어로 돌아온다 — 안전 속성.

        신호 만료·수동 정지 어느 쪽이든 hvac_running 이 False 가 되는 순간
        개구부가 다시 제어 대상이 되어야 한다. 잠긴 채로 남으면 한여름 대낮에
        온실을 가두게 된다.
        """
        p, st = _vent(), _state()
        for _ in range(6):
            cmd, st = _cycle(p, st, interlock=True, running=True)
            st.prev_commands['v1'] = cmd.aperture
        assert cmd.aperture < 10.0

        cmd, st = _cycle(p, st, interlock=True, running=False)
        assert cmd.reason == REASON_PRIMARY, '가동 중지 후에도 잠긴 채로 남았다'

    def test_option_off_is_inert(self):
        """옵션이 꺼져 있으면 가동 중이어도 아무 영향이 없다."""
        on, _ = _cycle(_vent(), _state(), interlock=False, running=True)
        base, _ = _cycle(_vent(), _state(), interlock=False, running=False)
        assert on.aperture == base.aperture
        assert on.reason == REASON_PRIMARY


class TestRunningDetection:
    """_hvac_running — 근거가 있을 때만 True."""

    def _obj(self, **attrs):
        o = MagicMock()
        o._hvac_running = HelpersMixin._hvac_running.__get__(o)
        o._profiles = []
        o.logger = MagicMock()
        o.sensor_max_age = 1200
        o.hvac_interlock_signal_device_id = None
        o.hvac_interlock_signal_measurement_id = None
        o.hvac_interlock_on_value = 0.5
        for k, v in attrs.items():
            setattr(o, k, v)
        return o

    def test_no_evidence_means_not_running(self):
        """조율기가 명령하지도 않고 신호도 없으면 발동하지 않는다."""
        assert self._obj()._hvac_running({}) is False

    def test_commanded_hvac_counts(self):
        """조율기가 명령한 cooler/heater 는 그 자체가 근거다."""
        cooler = MagicMock()
        cooler.kind = 'cooler'
        cooler.actuator_id = 'c1'
        o = self._obj(_profiles=[cooler])
        assert o._hvac_running({'c1': 60.0}) is True
        assert o._hvac_running({'c1': 0.0}) is False

    def test_signal_threshold(self):
        """수동 조작 장치 — 지정한 측정값이 문턱을 넘으면 가동 중."""
        o = self._obj(hvac_interlock_signal_device_id='d',
                      hvac_interlock_signal_measurement_id='m',
                      hvac_interlock_on_value=50.0)
        o.get_last_measurement = MagicMock(return_value=[1000.0, 820.0])
        assert o._hvac_running({}) is True
        o.get_last_measurement = MagicMock(return_value=[1000.0, 3.0])
        assert o._hvac_running({}) is False, '대기전력이 가동으로 읽히면 안 된다'

    def test_onoff_contact_with_default_threshold(self):
        """보조접점 on/off 는 기본 문턱 0.5 로 그대로 동작한다."""
        o = self._obj(hvac_interlock_signal_device_id='d',
                      hvac_interlock_signal_measurement_id='m')
        o.get_last_measurement = MagicMock(return_value=[1000.0, 1.0])
        assert o._hvac_running({}) is True
        o.get_last_measurement = MagicMock(return_value=[1000.0, 0.0])
        assert o._hvac_running({}) is False

    def test_stale_signal_unlocks(self):
        """신호가 만료되면 '가동 아님'으로 본다 — 죽은 센서가 온실을 봉인하면 안 된다."""
        o = self._obj(hvac_interlock_signal_device_id='d',
                      hvac_interlock_signal_measurement_id='m')
        o.get_last_measurement = MagicMock(return_value=[None, None])
        assert o._hvac_running({}) is False
        assert o.logger.warning.called, '만료를 조용히 넘기면 안 된다'

    def test_read_failure_unlocks(self):
        """신호 조회 자체가 실패해도 잠그지 않는다."""
        o = self._obj(hvac_interlock_signal_device_id='d',
                      hvac_interlock_signal_measurement_id='m')
        o.get_last_measurement = MagicMock(side_effect=RuntimeError('boom'))
        assert o._hvac_running({}) is False
