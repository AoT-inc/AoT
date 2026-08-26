# coding=utf-8
"""천창(ridge)과 측창(side)은 **물리가 다르다**.

`kind` 는 둘 다 `'opening'` 이라 제어기에게는 구분이 없었다. 그래서 셋이 늘
같은 값으로 움직였고(2026-08-26 실측: 側面窓 右/左·天窓 모두 80%),
"측창은 닫고 천창으로 열기를 뺀다" 는 온실 운영의 기본 전략을 표현할 수단이
없었다.

    ridge(천창)  실내가 더울 때 **부력**으로 뜨거운 공기를 위로 뱉는다.
                 실외가 더 더우면 부력이 역전돼 유입이 적다.
    side(측창)   외기를 **직접** 들인다. 실외가 더 더우면 그대로 가온이다.

⚠ **지붕 과열층은 모델에 없다.** 실제로는 지붕 밑 공기가 실내 평균보다 뜨거워
  실외가 더 더워도 천창이 열을 뺄 수 있지만, 그 층의 온도는 측정하지 않는다.
  없는 측정을 상수로 지어내면 그 값이 틀렸을 때 근거 없이 창을 여는 제어가
  된다. 여기서 주는 것은 **방향에 따른 유효도 차이**뿐이고, 그것은 부력의
  부호만으로 말할 수 있다.
"""

from aot.functions.utils.env_control.effect_functions import (
    build_effect_model, opening_humid_effect, opening_temp_effect,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _p(form):
    return ActuatorProfile(actuator_id='v', kind='opening', vent_form=form,
                           area_m2=10.0)


def _env(t_int, t_ext, rh_int=60.0, rh_ext=50.0):
    return {'T_int': t_int, 'T_ext': t_ext,
            'RH_int': rh_int, 'RH_ext': rh_ext, 'wind': 0.0}


class TestIndoorHotter:
    """실내가 더 더울 때 — 부력이 천창을 돕는다."""

    def test_ridge_beats_side_at_the_same_area(self):
        env = _env(t_int=35.0, t_ext=28.0)
        ridge = opening_temp_effect(env, 100.0, _p('ridge'))
        side  = opening_temp_effect(env, 100.0, _p('side'))

        assert ridge.direction == side.direction == '↓', '둘 다 냉각이다'
        assert ridge.magnitude_native > side.magnitude_native, (
            '같은 면적이면 천창이 더 뺀다 — 부력이 돕는다')


class TestOutdoorHotter:
    """실외가 더 더울 때 — 부력이 역전돼 천창의 유입이 적다.

    이 조합이 2026-08-26 실측 상황이다(실내 32.6 · 실외 35.1 · 일사 439W/m²).
    """

    def test_side_heats_more_than_ridge(self):
        env = _env(t_int=32.6, t_ext=35.1)
        ridge = opening_temp_effect(env, 100.0, _p('ridge'))
        side  = opening_temp_effect(env, 100.0, _p('side'))

        assert ridge.direction == side.direction == '↑', '둘 다 가온이다'
        assert side.magnitude_native > ridge.magnitude_native, (
            '더운 외기를 직접 들이는 측창이 더 데운다 — 제어기가 측창을 '
            '먼저 닫을 근거가 여기서 나온다')

    def test_ridge_is_penalised_not_zeroed(self):
        """0 으로 만들지 않는다 — 유입이 **적다**는 것이지 없다는 것이 아니다."""
        env = _env(t_int=32.6, t_ext=35.1)
        assert opening_temp_effect(env, 100.0, _p('ridge')).magnitude_native > 0.0


class TestHumidityFollowsTheSameAir:
    """수분도 같은 공기 교환을 탄다.

    온도만 보정하면 같은 개구부가 열은 적게, 수분은 그대로 옮기는 모순된
    모델이 된다 — 그 모순은 VPD 유도 효과에서 엉뚱한 부호로 나타난다.
    """

    def test_ridge_moves_less_moisture_when_outdoor_is_hotter(self):
        env = _env(t_int=32.6, t_ext=35.1, rh_int=60.0, rh_ext=52.0)
        ridge = opening_humid_effect(env, 100.0, _p('ridge'))
        side  = opening_humid_effect(env, 100.0, _p('side'))

        assert side.magnitude_native > ridge.magnitude_native


class TestUnknownFormKeepsOldBehaviour:
    """형태를 모르면 **예전과 똑같이** 동작한다.

    없는 정보를 지어내지 않는다 — 시설 편집기에서 종류를 안 정한 개구부가
    업그레이드만으로 조용히 다르게 움직이면 안 된다.
    """

    def test_none_form_matches_side(self):
        env = _env(t_int=35.0, t_ext=28.0)
        unknown = opening_temp_effect(env, 100.0, _p(None))
        side    = opening_temp_effect(env, 100.0, _p('side'))

        assert unknown.magnitude_native == side.magnitude_native

    def test_a_profile_without_the_field_does_not_crash(self):
        class _Old:
            kind = 'opening'
            area_m2 = 10.0
        env = _env(t_int=35.0, t_ext=28.0)
        assert opening_temp_effect(env, 100.0, _Old()).magnitude_native > 0.0


def test_the_derived_vpd_effect_sees_the_difference():
    """VPD 는 T·RH 에서 연쇄법칙으로 유도된다 — 형태 보정이 거기까지 간다.

    이 모달의 제어 중심이 VPD 이므로, 여기까지 닿지 않으면 구분이 실제 명령을
    바꾸지 못한다.
    """
    env = _env(t_int=32.6, t_ext=35.1, rh_int=60.0, rh_ext=52.0)
    model = build_effect_model('opening', {})
    ridge = model['vpd'](env, 100.0, _p('ridge'))
    side  = model['vpd'](env, 100.0, _p('side'))

    assert side.magnitude_native != ridge.magnitude_native, (
        '형태 구분이 VPD 까지 닿지 않는다 — 제어 중심이 VPD 라 명령이 안 바뀐다')
