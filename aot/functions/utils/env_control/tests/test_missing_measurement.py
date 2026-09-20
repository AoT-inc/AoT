# coding=utf-8
"""측정이 없으면 그 축은 제어에서 빠지고 장치는 **제자리**에 선다 (2026-09-20).

예전에는 `situation.assess` 가 없는 실내값을 0 으로 채웠다. 0 은 물리적으로
말이 되는 값이라 아무도 의심하지 않은 채 제어까지 흘러간다 — 실측 재현:

    실내 센서 없음, 실외 5 °C, 목표 22 °C / 60 %
      → 편차 온도 −22.0 · 습도 −60.0, 난방기·분무 근거 1(주작용)로 100 %

하드 임계(`temp_max`/`humid_max`)는 값이 None 이라 건너뛰므로 막지도 못한다.
그리고 이것은 센서를 안 단 시설만의 이야기가 아니다 — 실내 센서가 **만료**돼도
실외 풍속·일사가 `internal` 에 들어가 "센서 없음" 가드를 통과한다.

고친 뒤의 규칙 셋을 고정한다:
  1. 없는 측정은 None 이다 — 편차도, 그 편차를 근거로 한 모드도 서지 않는다.
  2. 효과 모델은 구동력 0 을 신고한다(없는 구배를 지어내지 않는다).
  3. 근거를 모두 잃은 장치는 **제자리**다(safe_default 로 수렴하지 않는다).
     감쇠는 "닫는다/걷는다" 는 결정인데, 여기서 해야 할 일은 아무것도 하지
     않는 것이다(`coordinator` 2.6 실외판과 같은 원칙).
"""
import pytest

from aot.functions.utils.env_control import coordinator as C
from aot.functions.utils.env_control import situation as S
from aot.functions.utils.env_control.authority import derive_authority
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.goal import build_env_target
from aot.functions.utils.env_control.log_channels import (
    REASON_NO_GRADIENT, REASON_NO_MEASUREMENT, REASON_PRIMARY,
)
from aot.functions.utils.env_control.types import ActuatorProfile

_EXT = {'T': 5.0, 'RH': 50.0, 'T_ext': 5.0, 'RH_ext': 50.0,
        'wind': 1.0, 'solar': 300.0}


def _profile(kind, aid, safe_default=0.0):
    return ActuatorProfile(actuator_id=aid, kind=kind,
                           effect_model=build_effect_model(kind, {}),
                           safe_default=safe_default)


def _assess(internal, profiles, external=None, co2=None):
    target = build_env_target(T_target=22.0, T_tol=1.0, T_pri=0.5,
                              RH_target=60.0, RH_tol=5.0, RH_pri=0.5,
                              CO2_target=co2 or 1000.0)
    if co2 is None:
        target.pop('co2', None)
    report, _ = S.assess(target, internal, external or _EXT, cycle_sec=60.0,
                         authority=derive_authority(profiles))
    return report


def _run(report, profiles, cycles=5, prev=None):
    state = C.CoordinatorState(prev_commands=dict(prev or {}))
    for _ in range(cycles):
        commands, state = C.coordinate(report, profiles, state)
    return commands, state


# ─────────────────────────────────────────────────────────────────────────────
# 1. 없는 측정은 None 이다
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingIsNotZero:

    def test_실내_센서가_없으면_0_이_아니라_None_이다(self):
        ctx = _assess({'wind': 1.0}, [_profile('heater', 'h1')]).context
        assert ctx['T_int'] is None
        assert ctx['RH_int'] is None

    def test_편차가_서지_않는다(self):
        report = _assess({'wind': 1.0}, [_profile('heater', 'h1')])
        assert report.deviation_native == {}

    def test_잴_수_없는_항목을_따로_알려_준다(self):
        """편차의 빈자리만으로는 '목표가 없다' 와 구분되지 않는다."""
        report = _assess({'T': 22.0}, [_profile('fogger', 'f1')])
        assert report.context['unmeasured'] == ['humidity']

    def test_없는_값으로_모드를_세우지_않는다(self):
        """0 °C 로 읽으면 '난방 중' 이라고 말하는데 아무 장치도 안 돈다."""
        report = _assess({'wind': 1.0}, [_profile('heater', 'h1')])
        assert 'heating' not in report.modes
        assert 'humidify' not in report.modes

    def test_측정이_있는_축은_그대로_돈다(self):
        report = _assess({'T': 26.0}, [_profile('opening', 'o1')])
        assert report.deviation_native['temperature'] == pytest.approx(4.0)
        assert 'humidity' not in report.deviation_native


# ─────────────────────────────────────────────────────────────────────────────
# 2. 효과 모델은 없는 구배를 지어내지 않는다
# ─────────────────────────────────────────────────────────────────────────────

class TestEffectModelsReportNoDrive:

    @pytest.mark.parametrize('kind', ['opening', 'curtain', 'exhaust_fan'])
    def test_실내를_모르면_구동력이_0_이다(self, kind):
        """실외 20 °C 대 실내 0 °C = 20 °C 구배를 지어내던 자리."""
        profile = _profile(kind, 'a1')
        env = {'T_ext': 20.0, 'RH_ext': 50.0, 'T_int': None, 'RH_int': None}
        for var, fn in profile.effect_model.items():
            assert fn(env, 100.0, profile).magnitude_native == 0.0, var

    def test_습도를_모르면_분무가_냉각을_주장하지_않는다(self):
        """모를 때 '가장 건조하다 = 최대 증발' 로 읽던 자리(증발 가능 비율)."""
        profile = _profile('fogger', 'f1')
        env = {'T_ext': 20.0, 'T_int': 26.0, 'RH_int': None, 'RH_ext': 50.0}
        for var, fn in profile.effect_model.items():
            assert fn(env, 100.0, profile).magnitude_native == 0.0, var


# ─────────────────────────────────────────────────────────────────────────────
# 3. 근거를 잃은 장치는 제자리 (사고 재현)
# ─────────────────────────────────────────────────────────────────────────────

class TestBlindActuatorsHold:

    def test_실내_센서가_없으면_난방기가_돌지_않는다(self):
        """사고 재현 — 예전에는 60 % 에서 시작해 100 % 까지 올라갔다."""
        profiles = [_profile('heater', 'h1')]
        commands, _ = _run(_assess({'wind': 1.0}, profiles), profiles)
        assert commands['h1'].value == 0.0
        assert commands['h1'].reason == REASON_NO_MEASUREMENT

    def test_습도_센서가_없으면_분무가_돌지_않는다(self):
        """사고 재현 — 예전에는 근거 1 로 100 % 였다(습도 −60 %)."""
        profiles = [_profile('fogger', 'f1')]
        commands, _ = _run(_assess({'T': 24.0}, profiles), profiles)
        assert commands['f1'].value == 0.0
        assert commands['f1'].reason == REASON_NO_MEASUREMENT

    def test_제자리다_안전_기본값이_아니다(self):
        """감쇠는 '닫는다' 는 결정이다 — 근거가 없을 때 할 일이 아니다.

        45 % 에 서 있던 개구부는 실내 센서를 잃어도 45 % 다. 무구배 완화
        경로로 떨어졌다면 safe_default(0) 쪽으로 내려갔을 것이다.
        """
        profiles = [_profile('opening', 'o1')]
        commands, _ = _run(_assess({'wind': 1.0}, profiles), profiles,
                           prev={'o1': 45.0})
        assert commands['o1'].value == pytest.approx(45.0)
        assert commands['o1'].reason == REASON_NO_MEASUREMENT

    def test_적분을_흔들지_않는다(self):
        """모르는 동안 '평형 개도 기억' 을 흔들면 센서가 돌아왔을 때
        엉뚱한 자리에서 출발한다."""
        profiles = [_profile('opening', 'o1')]
        report = _assess({'wind': 1.0}, profiles)
        state = C.CoordinatorState(prev_commands={'o1': 45.0},
                                   integral={'o1': 45.0})
        for _ in range(10):
            _, state = C.coordinate(report, profiles, state)
        assert state.integral['o1'] == pytest.approx(45.0)

    def test_잴_수_있는_축이_남아_있으면_계속_제어한다(self):
        """습도 센서 하나가 끊겼다고 개구부까지 멈추면 더위에 창이 잠긴다."""
        profiles = [_profile('opening', 'o1')]
        commands, _ = _run(_assess({'T': 28.0}, profiles), profiles)
        assert commands['o1'].reason == REASON_PRIMARY
        assert commands['o1'].value > 0.0

    def test_목표가_없어_쉬는_것과_구분한다(self):
        """15(무구배)와 21(잴 수 없음)은 처방이 다르다 — 뭉치면 센서가 끊긴
        사실이 화면에서 사라진다."""
        profiles = [_profile('heater', 'h1')]
        # 실내외가 같아 구배가 없는 정상 상황 — 21 이 아니라 15/1 계열이다.
        report = _assess({'T': 22.0, 'RH': 60.0}, profiles,
                         external=dict(_EXT, T=22.0, T_ext=22.0))
        commands, _ = _run(report, profiles)
        assert commands['h1'].reason != REASON_NO_MEASUREMENT

    def test_주입기는_있는데_CO2_센서가_없는_경우(self):
        profiles = [_profile('co2_injector', 'z1')]
        report = _assess({'T': 22.0, 'RH': 60.0}, profiles, co2=800)
        commands, _ = _run(report, profiles)
        assert commands['z1'].value == 0.0
        assert commands['z1'].reason == REASON_NO_MEASUREMENT


# ─────────────────────────────────────────────────────────────────────────────
# 4. 안전 게이트도 제자리다 (2026-09-20)
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyGateHoldsToo:
    """게이트가 뒤에서 덮어쓰면 코디네이터의 제자리가 무의미해진다.

    `SafetyPreGate` 는 실내 값을 잃으면 **전 액추에이터를 safe_default 로**
    강제하도록 쓰여 있었다(한여름에 실내 노드가 끊기면 창이 닫힌다는 뜻이다).
    그 코드가 한 번도 돌지 않은 이유는 호출자가 `last_int_ts` 에 매번
    `time.time()` 을 실어 보냈기 때문이고 — 즉 **고쳐서 되살리는 순간
    사고가 되는** 상태였다.
    """

    @staticmethod
    def _gate_env(T=None, RH=None, rain=0.0, wind=2.0, T_ext=20.0):
        return {
            'internal': {'T': T, 'RH': RH, 'T_max': T, 'T_min': T},
            'external': {'T': T_ext, 'RH': 50.0, 'wind': wind, 'rain': rain,
                         'solar': 300.0},
            'now_ts': 1767240000.0,
        }

    def _run(self, env, profiles=None):
        from aot.functions.utils.env_control.safety_gates import SafetyPreGate
        profiles = profiles or [_profile('opening', 'o1'),
                                _profile('curtain', 'c1', safe_default=100.0)]
        return SafetyPreGate().evaluate(env, profiles), profiles

    def test_실내_값을_잃으면_게이트가_그렇다고_말한다(self):
        from aot.functions.utils.env_control.log_channels import GATE_BIT_INT_EXP
        result, _ = self._run(self._gate_env())
        assert result.gate_mask & GATE_BIT_INT_EXP

    def test_그러나_아무것도_강제하지_않는다(self):
        result, _ = self._run(self._gate_env())
        assert result.forced_commands == {}

    def test_제어를_멈추지_않는다(self):
        """전체를 멈추면 잴 수 있는 축까지 함께 선다."""
        result, _ = self._run(self._gate_env())
        assert result.partial and not result.triggered

    def test_값이_돌아오면_곧바로_재개한다(self):
        """TTL 을 잡으면 값이 온 뒤에도 300초를 더 멈춘다."""
        from aot.functions.utils.env_control.safety_gates import SafetyPreGate
        gate = SafetyPreGate()
        profiles = [_profile('opening', 'o1')]
        gate.evaluate(self._gate_env(), profiles)
        back = gate.evaluate(self._gate_env(T=22.0, RH=60.0), profiles)
        assert back.gate_mask == 0 and not back.triggered

    def test_비상_판정은_모르면_서지_않는다(self):
        """비상 게이트는 전 장비를 한쪽으로 몬다 — 근거가 확실할 때만."""
        from aot.functions.utils.env_control.log_channels import (
            GATE_BIT_COLD, GATE_BIT_HEAT,
        )
        hot, _ = self._run(self._gate_env(T_ext=46.0))
        cold, _ = self._run(self._gate_env(T_ext=-10.0))
        assert not (hot.gate_mask & GATE_BIT_HEAT)
        assert not (cold.gate_mask & GATE_BIT_COLD)

    def test_실외로_판단할_수_있는_것은_그대로_막는다(self):
        """비는 실내를 몰라도 안다 — 창은 닫혀야 한다."""
        result, _ = self._run(self._gate_env(rain=5.0))
        assert result.triggered and not result.partial
        assert result.forced_commands['o1']['value'] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. 근거 코드가 갈라지지 않는다
# ─────────────────────────────────────────────────────────────────────────────

def test_근거_21_은_15_16_과_다른_번호다():
    from aot.functions.utils.env_control.log_channels import (
        REASON_NO_OUTDOOR_DATA,
    )
    assert len({REASON_NO_GRADIENT, REASON_NO_OUTDOOR_DATA,
                REASON_NO_MEASUREMENT}) == 3


def test_점검기가_근거_21_을_설명할_수_있다():
    """이름 없는 근거는 `코드 21` 로 찍히며 돈다 — 화면만 보고는 모른다.

    화면(`aot-map-popup.js` 의 `_REASON_TEXT`)은 `test_map_popup_labels` 가
    본다. 여기서 JS 를 읽지 않는 이유는 그 원본이 공개 저장소에 나가지 않기
    때문이다(`aot/scripts/publish/exclude.txt`).
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[4]
    health = (root / 'scripts' / 'check_env_coordinator_health.py'
              ).read_text(encoding='utf-8')
    assert 'LC.REASON_NO_MEASUREMENT' in health
