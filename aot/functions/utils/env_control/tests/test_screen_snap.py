"""스크린(커튼·차광막) 0/100 결정은 기록 앞에서, 히스테리시스를 두고 (2026-09-26).

실측(영양 보온커튼 09-25~26): 기록·화면은 40 %·27.6 %·13.9 % 였는데 `_dispatch`
가 50 % 에서 잘라 장치에는 28시간 동안 0 만 나갔다.
"""
import types

from aot.functions.utils.env_control.dispatch_adapters import (
    snap_screen_commands, snap_screen_value,
)


def test_기록되는_값이_곧_전송값이다():
    profiles = [types.SimpleNamespace(actuator_id='cur', kind='curtain'),
                types.SimpleNamespace(actuator_id='win', kind='opening')]
    cmds = {'cur': {'value': 40.0, 'reason': 1}, 'win': {'value': 40.0, 'reason': 1}}
    snap_screen_commands(cmds, profiles, {'cur': 0.0, 'win': 0.0})
    assert cmds['cur']['value'] == 0.0          # 닫힌 커튼, 40 → 닫힌 채
    assert cmds['win']['value'] == 40.0         # 창은 건드리지 않는다


def test_경계_근처에서_끝과_끝을_오가지_않는다():
    """명령이 45~55 를 오가도 서 있는 쪽을 지킨다."""
    pos = 0.0
    for v in (45, 55, 48, 52, 58, 44):
        pos = snap_screen_value(v, pos)
    assert pos == 0.0
    pos = 100.0
    for v in (55, 45, 52, 48, 42, 56):
        pos = snap_screen_value(v, pos)
    assert pos == 100.0


def test_경계를_확실히_넘으면_움직인다():
    assert snap_screen_value(60.0, 0.0) == 100.0
    assert snap_screen_value(40.0, 100.0) == 0.0
    assert snap_screen_value(50.0, None) == 100.0   # 위치를 모르면 50 에서 자른다


# ── 부분 개도(Phase 6-1) ────────────────────────────────────────────────────
from aot.functions.utils.env_control.dispatch_adapters import (  # noqa: E402
    CURTAIN_STOPS, screen_partial_ok,
)
from aot.functions.utils.env_control.log_channels import (  # noqa: E402
    REASON_CURTAIN_GAP, REASON_CURTAIN_RAMP, REASON_PRIMARY,
)


def _cur(positional):
    return types.SimpleNamespace(actuator_id='cur', kind='curtain',
                                 capacity_meta={'screen_positional': positional})


def test_위치를_잡는_커튼의_틈은_그대로_간다():
    cmds = {'cur': {'value': 6.0, 'reason': REASON_CURTAIN_GAP}}
    snap_screen_commands(cmds, [_cur(True)], {'cur': 0.0})
    assert cmds['cur']['value'] == 6.0


def test_램프_정지점도_그대로다():
    cmds = {'cur': {'value': 30.0, 'reason': REASON_CURTAIN_RAMP}}
    snap_screen_commands(cmds, [_cur(True)], {'cur': 10.0})
    assert cmds['cur']['value'] == 30.0


def test_onoff_커튼은_틈이_있어도_0_100():
    cmds = {'cur': {'value': 6.0, 'reason': REASON_CURTAIN_GAP}}
    snap_screen_commands(cmds, [_cur(False)], {'cur': 0.0})
    assert cmds['cur']['value'] == 0.0


def test_PI_명령은_여전히_0_100():
    cmds = {'cur': {'value': 30.0, 'reason': REASON_PRIMARY}}
    snap_screen_commands(cmds, [_cur(True)], {'cur': 0.0})
    assert cmds['cur']['value'] == 0.0


def test_정지점이_아닌_값은_자른다():
    assert not screen_partial_ok(_cur(True), 7.0, REASON_CURTAIN_GAP)
    assert all(screen_partial_ok(_cur(True), s, REASON_CURTAIN_RAMP) for s in CURTAIN_STOPS)


def test_전송_안전망도_같은_예외를_쓴다():
    """기록값 = 전송값(29cd04b84) — `_dispatch` 의 50 % 자르기가 틈을 0 으로 만들면 안 된다."""
    import inspect
    from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin as hm
    src = inspect.getsource(hm.HelpersMixin._dispatch_commands)
    assert 'screen_partial_ok(profile, val, _reason)' in src


def test_로더가_부분_개도_가능을_가른다():
    import logging
    from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import (
        ProfileLoaderMixin)
    from aot.functions.utils.env_control.dispatch_adapters import (
        PairedAdapter, TimeProportionalAdapter, ValueAdapter)
    from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints

    def _p(aid, stroke):
        return ActuatorProfile(actuator_id=aid, kind='curtain',
                               cmd_constraints=CmdConstraints(full_stroke_sec=stroke))
    profs = [_p('paired', 240.0), _p('relay', 240.0), _p('nostroke', 0.0), _p('value', 90.0)]
    me = types.SimpleNamespace(
        _profiles=profs, logger=logging.getLogger('t'),
        _adapter_by_id={'paired': PairedAdapter(), 'relay': TimeProportionalAdapter(),
                        'nostroke': PairedAdapter(), 'value': ValueAdapter()})
    ProfileLoaderMixin._mark_screen_positional(me)
    got = {p.actuator_id: p.capacity_meta['screen_positional'] for p in profs}
    assert got == {'paired': True, 'relay': False, 'nostroke': False, 'value': True}
    assert profs[0].capacity_meta['screen_stroke_s'] == 240.0
