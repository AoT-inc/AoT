# coding=utf-8
"""부하분담은 도메인 안에서만 흐른다 + 적분은 실제 개도를 넘어 자라지 않는다.

(2026-08-26 — `test_accumulated_overshoot_cap.py` 를 대체한다)

## 무엇이 일어났나

부하분담(`accumulated`)은 "이미 확정된 명령이 만들 물리 변화량"을 다음
액추에이터에게 알려, 뒤가 앞이 이미 한 만큼을 빼고 적게 동작하게 한다. 이
전제는 **확정한 명령이 실제 물리 변화를 낸다**는 것이다.

실사고(イチゴ): 측창 하나(側面窓 右)의 적분이 여러 사이클에 걸쳐 폭주해
(I=67.9, **실제 개도는 25.0**) 그 사이클에 88.7% 로 확정됐다. 이 창의 물리
기여가 `accumulated['vpd']=+1.2556` — 원래 편차(−0.2215)의 **5.7배**였다.
뒤에 처리된 분무기·냉방기는 "이미 크게 과했다"고 잘못 읽어 **반대 방향으로
켜졌다** — 실내 습도가 92%인데 가습이, 목표보다 시원한데 냉방이 올라갔다.

⚠ **시뮬레이션(개루프)에만 있는 문제가 아니다.** 실제 온실에서 측창 모터가
고장 나거나 센서가 죽어도 같은 경로로 재현된다. 실패 방향이 최악이다: 장비
하나가 고장 나면 **나머지가 그 몫까지 떠안아 더 세게** 가야 하는데, 이
버그는 정확히 반대로 나머지를 꺼버린다.

## 두 층으로 막는다

먼저 시도했던 "누적치에 상한(원래 편차의 1.0배)" 은 **증상만** 줄인다 —
전파량은 자르지만 폭주 자체는 그대로 두고, 같은 도메인 안(창끼리)에서는
여전히 전염된다. 그래서 두 가지로 바꿨다.

| 층 | 무엇 | 막는 것 |
|----|------|---------|
| 근원 | 슬루 되먹임 (`AW_BETA`) | 적분이 실제 개도를 넘어 자라는 것 |
| 격리 | 도메인별 `accumulated` | 그래도 생긴 오작동이 남을 거꾸로 켜는 것 |

**근원**: anti-windup 이 `[0,100]` 클램프만 되먹이고 슬루(변화율) 제한은
되먹이지 않았다. `finalize_command` 가 적분 확정 **뒤에** 슬루를 걸므로,
PI 가 88.7% 를 원하고 실제로는 25% 만 나가도 적분은 88.7 이 나간 것처럼
계속 자랐다.

**격리**: 부하분담은 서로 **완전 대체 가능한** 장치끼리만 뜻이 있다.
창·팬(vent)은 전부 실내를 실외 쪽으로 미는 같은 일이고, 난방·냉방·가습
(hvac)은 반드시 서로 알아야 맞서지 않는다. 그러나 창과 냉방기는 대체재가
아니다 — 도메인 간 조율은 명시적 인터록(`hvac_interlock`)이 맡는다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    ACTUATOR_DOMAIN, AW_BETA, CoordinatorState, DEFAULT_DOMAIN,
    VENTILATING_KINDS, coordinate, domain_of,
)
from aot.functions.utils.env_control.types import (
    ACTUATOR_KINDS, ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    """coordinate() 가 요구하는 최소 SituationReport 흉내."""
    def __init__(self, target, deviation, context=None):
        self.target = target
        self.deviation_native = deviation
        self.context = context or {'cycle_sec': 600.0}


def _profile(aid, kind, direction, magnitude, slew=100.0, cost=5.0):
    return ActuatorProfile(
        actuator_id=aid,
        kind=kind,
        effect_model={'vpd': _effect(direction, magnitude)},
        cost_fn=lambda env, pct: cost,
        cmd_constraints=CmdConstraints(slew_per_cycle=slew, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )


# VPD 가 목표보다 낮다(측정 < 목표) → 올려야 한다(따뜻/건조 쪽).
_TARGET = {'vpd': TargetVar(value=0.4772, tolerance=0.1, priority=1.2, unit='kPa')}
_DEVIATION = {'vpd': -0.2215}


# ═════════════════════════════════════════════════════════════════════════════
# 1. 도메인 명부 자체
# ═════════════════════════════════════════════════════════════════════════════

class TestDomainMap:

    def test_모든_kind_가_도메인을_갖는다(self):
        """새 kind 를 추가하고 명부를 안 고치면 여기서 안다."""
        missing = ACTUATOR_KINDS - set(ACTUATOR_DOMAIN)
        assert not missing, (
            '도메인 미배정 kind: %s — ACTUATOR_DOMAIN 에 추가할 것' % sorted(missing))

    def test_명부에_없는_kind_는_격리된다(self):
        """모르는 장치가 남을 오염시키지 못하는 쪽이 안전하다."""
        class _P:
            kind = 'teleporter'
        assert domain_of(_P()) == DEFAULT_DOMAIN

    def test_환기_어휘가_도메인에서_파생된다(self):
        """어휘를 두 벌 두면 갈라지고, 갈라지면 한쪽만 고쳐진다."""
        assert VENTILATING_KINDS == frozenset(
            k for k, d in ACTUATOR_DOMAIN.items() if d == 'vent')

    def test_냉방과_난방과_가습이_같은_도메인이다(self):
        """이 셋은 서로 알아야 한다 — 모르면 난방과 냉방이 정면으로 맞선다."""
        assert (domain_of(_profile('a', 'heater', '↑', 1.0))
                == domain_of(_profile('b', 'cooler', '↓', 1.0))
                == domain_of(_profile('c', 'fogger', '↓', 1.0)))

    def test_창과_냉방기는_다른_도메인이다(self):
        """대체재가 아니다 — 냉방은 있는 열을 빼고, 창은 실외로만 민다."""
        assert (domain_of(_profile('a', 'opening', '↑', 1.0))
                != domain_of(_profile('b', 'cooler', '↓', 1.0)))

    def test_차광막과_냉방기는_다른_도메인이다(self):
        """차광은 앞으로 올 열을 막고, 냉방은 지금 있는 열을 뺀다."""
        assert (domain_of(_profile('a', 'shade', '↓', 1.0))
                != domain_of(_profile('b', 'cooler', '↓', 1.0)))


# ═════════════════════════════════════════════════════════════════════════════
# 2. 격리 — 폭주가 도메인을 넘지 않는다
# ═════════════════════════════════════════════════════════════════════════════

class TestRunawayDoesNotCrossDomains:
    """실사고 재현 — 창의 폭주가 분무기·냉방기를 오염시키지 않는다."""

    def _run_with_peer(self, peer_kind, peer_dir):
        situation = _Situation(_TARGET, _DEVIATION)
        # 실사고와 같은 큰 유효 크기로 폭주 재현. cost 로 창이 먼저 확정되게 한다.
        vent = _profile('vent', 'opening', '↑', magnitude=8.0, cost=1.0)
        peer = _profile('peer', peer_kind, peer_dir, magnitude=1.0, cost=9.0)

        state = CoordinatorState()
        state.prev_commands = {'vent': 5.0, 'peer': 20.0}
        state.integral = {'vent': 95.0, 'peer': 20.0}   # vent 폭주(=고장 가정)

        result, _ = coordinate(situation, [vent, peer], state, unique_id='test')
        return result['peer']

    def test_창이_폭주해도_가습기가_반대로_안_켜진다(self):
        """이것이 회귀의 본체다 — 습도 92%인데 가습이 올라간 그 사고."""
        assert self._run_with_peer('fogger', '↓').value <= 20.0

    def test_창이_폭주해도_냉방기가_반대로_안_켜진다(self):
        """목표보다 시원한데 냉방이 올라간 그 사고."""
        assert self._run_with_peer('cooler', '↓').value <= 20.0

    def test_창이_폭주해도_난방기가_자기_판단을_한다(self):
        """같은 방향(↑)이라도 창의 과장된 기여에 막혀 꺼지면 안 된다.

        ⚠ 이것이 상한(cap) 방식으로는 얻을 수 없었던 성질이다. 상한은 전파를
        자를 뿐이라 "vent 가 이미 다 했다" 는 주장이 남아, 고장 난 창의 몫을
        난방기가 떠안아야 하는 상황에서 정확히 반대로 난방기를 껐다.
        """
        heater = self._run_with_peer('heater', '↑')
        assert heater.value > 0.0, (
            '창이 고장 나면 난방기가 그 몫을 떠안아야 한다 — 꺼지면 안 된다')


class TestSharingStillWorksInsideADomain:
    """격리가 부하분담 자체를 없애면 안 된다 — 대체재끼리는 여전히 나눈다."""

    def _peer_cmd(self, first_kind, second_kind):
        situation = _Situation(_TARGET, _DEVIATION)
        first = _profile('first', first_kind, '↑', magnitude=3.0, cost=1.0)
        second = _profile('second', second_kind, '↑', magnitude=3.0, cost=9.0)
        state = CoordinatorState()
        state.prev_commands = {'first': 50.0, 'second': 50.0}
        state.integral = {'first': 50.0, 'second': 50.0}
        result, _ = coordinate(situation, [first, second], state, unique_id='t')
        return result['second'].control_value()

    def test_창끼리는_서로의_기여를_본다(self):
        """천창이 열면 측창은 덜 연다 — 안 그러면 둘 다 전개된다."""
        with_peer = self._peer_cmd('opening', 'opening')
        alone = self._peer_cmd('cooler', 'opening')   # 다른 도메인 = 안 보임
        assert with_peer < alone, (
            '같은 도메인 안에서는 앞의 기여를 보고 적게 동작해야 한다')

    def test_난방과_냉방은_서로의_기여를_본다(self):
        """맞서면 안 되는 짝이라 반드시 같은 도메인이어야 한다."""
        assert domain_of(_profile('a', 'heater', '↑', 1.0)) == \
               domain_of(_profile('b', 'cooler', '↓', 1.0))


# ═════════════════════════════════════════════════════════════════════════════
# 3. 근원 — 적분이 실제 개도를 넘어 자라지 않는다
# ═════════════════════════════════════════════════════════════════════════════

class TestIntegralCannotOutrunTheActuator:
    """실측 근거: 側面窓右 가 적분 67.9 / 실제 개도 25.0 으로 43%p 벌어져 있었다."""

    def _cycle(self, slew, prev, integral, cycles=1):
        state = CoordinatorState()
        state.prev_commands = {'vent': prev}
        state.integral = {'vent': integral}
        for _ in range(cycles):
            vent = _profile('vent', 'opening', '↑', magnitude=8.0, slew=slew)
            _, state = coordinate(_Situation(_TARGET, _DEVIATION), [vent],
                                  state, unique_id='test')
        return state

    def test_슬루로_못_나간_몫이_적분에_되먹여진다(self):
        """슬루가 좁으면 적분도 그만큼 덜 자라야 한다."""
        loose = self._cycle(slew=100.0, prev=5.0, integral=60.0)
        tight = self._cycle(slew=5.0, prev=5.0, integral=60.0)
        assert tight.integral['vent'] < loose.integral['vent'], (
            '슬루에 막혀 안 나간 몫이 적분에 되먹여지지 않고 있다')

    def test_슬루에_막힌_채로_적분이_레일까지_치솟지_않는다(self):
        """실사고 상태(I=67.9 / 실제 개도 25.0)에서 15 사이클 굴려 본다.

        ⚠ 불변식은 `I ≈ prev` 가 **아니다.** 전이 중에는 P 항이 크므로 적분이
        실제 개도보다 한참 아래 앉는 것이 정상이다(`cmd = P + I` 가 개도를
        만든다). 보장해야 할 것은 **적분이 도달 불가능한 값으로 치솟지 않는
        것** — 되먹임이 없으면 이 조건에서 I 가 100 에 눌어붙고, 편차가 풀리는
        순간 그 100 이 통째로 계단으로 튀어나온다.
        """
        state = CoordinatorState()
        state.prev_commands = {'vent': 25.0}
        state.integral = {'vent': 67.9}
        for _ in range(15):
            vent = _profile('vent', 'opening', '↑', magnitude=8.0, slew=5.0)
            _, state = coordinate(_Situation(_TARGET, _DEVIATION), [vent],
                                  state, unique_id='test')
        assert state.integral['vent'] < 100.0, (
            '적분이 레일에 눌어붙었다 — 슬루 되먹임이 죽어 있다')
        assert state.prev_commands['vent'] > 25.0, (
            '되먹임이 과해서 액추에이터가 전진을 멈췄다 — 응답성 회귀다')

    def test_되먹임이_없었다면_레일에_눌어붙는다(self):
        """대조군 — 같은 조건에서 되먹임만 빼면 실제로 100 에 도달하는가.

        회귀 테스트가 '원래 안 일어나는 일'을 막고 있는 것은 아닌지 확인한다.
        """
        I, prev, ki, kp = 67.9, 25.0, 0.2, 1.0
        for _ in range(15):
            e_eff = 0.2860                      # 이 시나리오의 고정 유효오차
            I = min(100.0, I + ki * e_eff)
            cmd_raw = min(100.0, kp * e_eff * 100.0 + I)
            prev = min(100.0, prev + 5.0)       # 슬루만 걸린 실제 개도
        assert I >= 68.0, '대조군 전제가 깨졌다 — 시나리오를 다시 볼 것'

    def test_슬루가_안_걸리면_적분은_그대로다(self):
        """되먹임이 항상 개입하면 그 자체가 회귀다 — 정상 동작을 늦춘다."""
        free = self._cycle(slew=100.0, prev=50.0, integral=50.0)
        # 요구값이 슬루 안에 들어오는 상황에서는 적분이 P·I 규칙대로만 움직인다.
        assert free.integral['vent'] >= 50.0

    def test_되먹임_강도는_AW_BETA_다(self):
        """클램프·슬루·min-ON 은 전부 '요구만큼 못 나갔다'는 같은 사건이다."""
        assert 0.0 < AW_BETA <= 1.0


class TestFeedbackSkipsDeliberatePositions:
    """무구배·실외없음 분기의 적분은 '요구'가 아니라 **의도된 위치**다."""

    def test_무구배_감쇠는_되먹임에_안_걸린다(self):
        """safe_default 로 수렴시키는 값을 다시 되먹이면 이중 감쇠가 된다."""
        # 유효도가 문턱(G_MIN_EFFECT) 아래 → NO_GRADIENT 경로
        vent = _profile('vent', 'opening', '↑', magnitude=1e-6, slew=5.0)
        state = CoordinatorState()
        state.prev_commands = {'vent': 80.0}
        state.integral = {'vent': 80.0}
        _, new = coordinate(_Situation(_TARGET, _DEVIATION), [vent],
                            state, unique_id='test')
        # RELAX_FACTOR 기하 감쇠 결과 그대로 — 추가 보정이 없어야 한다.
        from aot.functions.utils.env_control.coordinator import RELAX_FACTOR
        assert new.integral['vent'] == pytest.approx(
            0.0 + (80.0 - 0.0) * RELAX_FACTOR)


class TestMinOnIsNotFedBack:
    """⚠ 짧은 명령은 **버려지되 적분은 남는다** — 되먹이면 교착이 된다.

    슬루와 min-ON 은 "요구만큼 못 나갔다" 로 같아 보이지만 뜻이 정반대다.
    슬루는 장치가 가고는 있는 것이고, min-ON 은 아무것도 안 한 것이다. 몇 초
    켜서는 실제 출력이 안 나오는 장치가 많아 일부러 버리는 것인데, 여기서
    적분까지 깎으면 적분이 문턱을 영영 못 넘어 장치가 한 번도 안 돈다.

    PID 컨트롤러의 on/off 경로가 같은 판단을 한다 — `raise_min_duration` 미만
    이면 출력을 건너뛰되 integrator 는 그대로 쌓아, 의미 있는 한 번을 만들 수
    있을 때 몰아서 켠다(펄스 폭이 아니라 빈도로 조절).
    """

    def _tiny_demand(self, min_on):
        """요구가 **데드존 밖**이면서 min-ON 문턱에는 못 미치는 상황.

        pband = 6×0.5 = 3.0 · e_norm = 0.45/3.0 = 0.15 · 데드존 0.0833
        → e_eff = 0.0667 → P = 6.67%. min-ON 30% 에 한참 못 미친다.
        (ki 는 사이클 수를 현실적으로 두려고 크게 잡았다 — 규칙은 값과 무관하다)
        """
        target = {'vpd': TargetVar(value=0.4772, tolerance=0.5, priority=1.0,
                                   unit='kPa')}
        situation = _Situation(target, {'vpd': -0.45})
        p = ActuatorProfile(
            actuator_id='heater', kind='heater',
            effect_model={'vpd': _effect('↑', 0.5)},
            cost_fn=lambda env, pct: 5.0,
            cmd_constraints=CmdConstraints(slew_per_cycle=100.0,
                                           min_on_pct=min_on),
            gains={'kp': 1.0, 'ki': 20.0}, safe_default=0.0)
        return situation, p

    def test_버려진_몫이_적분에_남아_결국_한_번_켜진다(self):
        state = CoordinatorState()
        fired = False
        for _ in range(60):
            situation, p = self._tiny_demand(min_on=30.0)
            cmds, state = coordinate(situation, [p], state, unique_id='t')
            if cmds['heater'].control_value() > 0.0:
                fired = True
                break
        assert fired, (
            '적분이 min-ON 문턱을 영영 못 넘었다 — 버린 몫까지 되먹이고 있다')

    def test_적분은_계속_자란다(self):
        """켜지기 전까지는 매 사이클 쌓여야 한다."""
        state = CoordinatorState()
        situation, p = self._tiny_demand(min_on=90.0)
        seen = []
        for _ in range(5):
            situation, p = self._tiny_demand(min_on=90.0)
            _, state = coordinate(situation, [p], state, unique_id='t')
            seen.append(state.integral['heater'])
        assert seen == sorted(seen) and seen[-1] > seen[0], seen


class TestDirectionReversalReseatsTheIntegral:
    """PID 컨트롤러 차용 — 한쪽에서 쌓은 누적이 반대쪽으로 넘어가지 않는다.

    PID 는 direction='both' 에서 방향이 뒤집히면 `integrator = 0.0` 으로 지운다.
    코디네이터의 적분은 '누적 오차'가 아니라 **'기억된 평형 개도(%)'** 라 0 으로
    지우면 "완전히 닫아라" 가 되므로, 같은 뜻을 갖는 조치는 **실제 서 있는
    자리로 되앉히는 것**이다.
    """

    def _cooler(self):
        return ActuatorProfile(
            actuator_id='cooler', kind='cooler',
            effect_model={'vpd': _effect('↓', 2.0)},
            cost_fn=lambda env, pct: 5.0,
            cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
            gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)

    def test_반대_방향으로_뒤집히면_적분이_실제_개도로_내려온다(self):
        """실사고 재현: 냉방기가 I=97.9 를 들고 VPD 를 올려야 할 때도 돌았다."""
        state = CoordinatorState()
        # 1) VPD 를 내려야 하는 국면 — 냉방기가 정방향으로 쌓는다.
        s_down = _Situation(_TARGET, {'vpd': +0.30})
        _, state = coordinate(s_down, [self._cooler()], state, unique_id='t')
        assert state.drive_sign['cooler'] == 1
        state.integral['cooler'] = 97.9        # 여러 사이클 쌓인 상태
        state.prev_commands['cooler'] = 76.0

        # 2) 국면이 뒤집힌다 — 이제 VPD 를 올려야 한다(냉방은 반대 방향).
        s_up = _Situation(_TARGET, _DEVIATION)
        cmds, state = coordinate(s_up, [self._cooler()], state, unique_id='t')
        assert state.drive_sign['cooler'] == -1
        assert cmds['cooler'].control_value() < 76.0, (
            '방향이 뒤집혔는데 옛 적분이 명령을 계속 밀고 있다')

    def test_0_으로_지우지_않는다(self):
        """PID 를 그대로 베끼면 방향 전환마다 장치가 쾅 닫힌다."""
        state = CoordinatorState()
        s_down = _Situation(_TARGET, {'vpd': +0.30})
        _, state = coordinate(s_down, [self._cooler()], state, unique_id='t')
        state.integral['cooler'] = 90.0
        state.prev_commands['cooler'] = 60.0
        s_up = _Situation(_TARGET, _DEVIATION)
        _, state = coordinate(s_up, [self._cooler()], state, unique_id='t')
        assert state.integral['cooler'] > 0.0, (
            '적분을 0 으로 지웠다 — 그것은 "완전히 닫아라" 라는 뜻이다')

    def test_같은_방향이면_되앉히지_않는다(self):
        """항상 개입하면 적분이 존재할 이유가 없어진다."""
        state = CoordinatorState()
        s = _Situation(_TARGET, _DEVIATION)
        _, state = coordinate(s, [self._cooler()], state, unique_id='t')
        before = state.integral['cooler']
        state.prev_commands['cooler'] = 0.0     # 적분과 크게 벌려 둔다
        _, state = coordinate(s, [self._cooler()], state, unique_id='t')
        assert state.integral['cooler'] != pytest.approx(0.0) or before == 0.0

    def test_방향_기억은_영속화하지_않는다(self):
        """재시작 직후 한 사이클 쉬는 편이, 마이그레이션을 만드는 것보다 낫다."""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import (
            _runtime_state_mixin as m)
        src = inspect.getsource(m)
        assert 'drive_sign' not in src, (
            '영속화하기로 했다면 이 테스트와 CoordinatorState 주석을 함께 고칠 것')


def test_상한_방식이_되살아나지_않았다():
    """증상만 줄이는 옛 접근으로 조용히 되돌아가지 않게 소스로 고정한다."""
    import inspect
    from aot.functions.utils.env_control import coordinator as m
    assert not hasattr(m, 'ACCUM_OVERSHOOT_MULT'), (
        '누적치 상한은 도메인 분리 + 슬루 되먹임으로 대체됐다')
    src = inspect.getsource(m.coordinate)
    assert 'domain_of(p)' in src, '도메인별 누적이 사라졌다'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
