# coding=utf-8
"""측창 법선의 좌표 규약 — **미러 보정은 없다**.

model +X → 지도 East. 추가 부호 반전이 없다.

## 한때는 있었다

"3D 미리보기에서 만든 것을 지도에 배치하면 X축이 미러된다" 는 실제 문제가
있었고, 그 보정으로 `_side_world_normal` 이 X 부호를 뒤집었다. 그 뒤 지도
렌더러의 변환이 정리되면서 미러가 사라졌는데 **보정만 남았다.**

남은 동안 풍향 가중치가 정확히 반대로 돌았다 — 실측(방위 11.5° · 5 m/s):
동풍에서 동쪽을 보는 측창이 0.2 로 깎이고 서쪽 창이 0.98 을 받았다. 정책
("windward 높게, leeward 낮게")과 정반대이고, 그 상태로 창을 여닫으면 풍압을
받는 쪽을 닫고 그늘진 쪽을 연다.

## ⚠ 부호는 코드로 판정할 수 없다

직사각형 시설은 미러해도 footprint 가 똑같아서, 좌우가 다른 내용물(측창)이
있어야만 드러난다. 지도 렌더러의 변환 행렬도, git 이력(스쿼시)도 근거가 못
된다 — **현장에서 만들어 보고 지도와 대조하는 것**만이 답한다.
2026-08-26 에 그렇게 확인했다: 일치한다(미러 없음).

바꿔야 할 날이 오면 `_world_normal_from_sn` **한 곳**만 고친다. 아래 일치·
대칭 검사는 부호와 무관하게 통과하고, 방향 검사만 뒤집으면 된다.
"""
import math

from aot.aot_flask.geo.facility_wind import (
    _side_world_normal, _world_normal_from_sn, wind_biased_opening,
)

ORI = 11.5   # イチゴ 실측 방위


def _side(aid, nx):
    return {'actuator_id': aid, 'face': None, 'surface_normal': [nx, 0, 0]}


class TestOneConvention:
    """같은 `surface_normal` 을 읽는 두 함수가 같은 답을 내야 한다."""

    def test_both_consumers_agree(self):
        for sn in ([1, 0, 0], [-1, 0, 0], [0, 0, 1], [0.6, 0, -0.8]):
            a = _side_world_normal({'surface_normal': sn}, ORI)
            b = _world_normal_from_sn(sn, ORI)
            assert a is not None and b is not None, sn
            assert math.isclose(a[0], b[0], abs_tol=1e-9), sn
            assert math.isclose(a[1], b[1], abs_tol=1e-9), sn

    def test_the_convention_lives_in_exactly_one_place(self):
        """부호를 두 곳에서 정하면 갈라진다 — 그게 이 결함의 모양이었다."""
        import inspect

        from aot.aot_flask.geo import facility_wind as fw
        side = inspect.getsource(fw._side_world_normal)
        code = side.split('"""', 2)[-1]      # 독스트링은 규칙을 설명한다 — 제외
        assert '-nx' not in code, (
            '풍향 가중치가 자기 부호를 따로 정하고 있다 — '
            '`_world_normal_from_sn` 하나에 맡길 것')
        assert '_world_normal_from_sn' in code, '정본을 거치지 않는다'


class TestDirectionMatchesTheField:
    """현장 확인된 방향 (2026-08-26): 미러 없음, model +X = 지도 East.

    ⚠ 이 검사만이 부호에 의존한다. 현장에서 다시 미러가 확인되면
      `_world_normal_from_sn` 한 곳을 고치고 여기 기대값을 뒤집는다.
    """

    def _w(self, wind_deg):
        return wind_biased_opening(
            [_side('R', 1.0), _side('L', -1.0)], wind_deg, ORI,
            wind_speed_ms=5.0)

    def test_east_wind_opens_the_east_facing_window(self):
        w = self._w(90.0)
        assert w['R'] > 0.9 and w['L'] < 0.3, (
            '동풍인데 동쪽(+X)을 보는 측창이 안 열린다 — 부호가 뒤집혔다')

    def test_west_wind_opens_the_west_facing_window(self):
        w = self._w(270.0)
        assert w['L'] > 0.9 and w['R'] < 0.3, (
            '서풍인데 서쪽(−X)을 보는 측창이 안 열린다 — 부호가 뒤집혔다')


class TestOppositeWallsStayOpposite:
    """마주 보는 두 벽의 법선은 어떤 규약에서도 정반대여야 한다.

    부호를 어느 쪽으로 정하든 이것은 참이다 — 미러는 둘을 함께 뒤집는다.
    한쪽만 뒤집히면 두 창이 같은 방향을 보게 되어, 어떤 바람에서도 둘 다
    풍상이거나 둘 다 풍하가 된다.
    """

    def test_normals_are_antiparallel(self):
        r = _side_world_normal({'surface_normal': [1, 0, 0]}, ORI)
        l = _side_world_normal({'surface_normal': [-1, 0, 0]}, ORI)
        assert math.isclose(r[0], -l[0], abs_tol=1e-9)
        assert math.isclose(r[1], -l[1], abs_tol=1e-9)

    def test_one_side_is_windward_the_other_leeward(self):
        for wind in (0.0, 45.0, 90.0, 180.0, 270.0):
            w = wind_biased_opening(
                [_side('R', 1.0), _side('L', -1.0)], wind, ORI,
                wind_speed_ms=5.0)
            assert w['R'] != w['L'], (
                '풍향 %.0f°: 두 측창이 같은 가중치다 — 마주 보는 벽인데 '
                '같은 방향을 본다는 뜻' % wind)


class TestWeightPolicy:
    """가중치 규칙 자체 — 부호와 무관하게 성립해야 한다."""

    def test_leeward_keeps_a_floor(self):
        """풍하도 완전히 닫지 않는다 — 배기 쪽이 막히면 환기가 서지 않는다."""
        w = wind_biased_opening(
            [_side('R', 1.0), _side('L', -1.0)], 90.0, ORI, wind_speed_ms=5.0)
        assert min(w.values()) >= 0.2

    def test_windward_reaches_full(self):
        """정면으로 받는 창은 깎지 않는다."""
        best = max(
            max(wind_biased_opening(
                [_side('R', 1.0), _side('L', -1.0)], wind, ORI,
                wind_speed_ms=5.0).values())
            for wind in range(0, 360, 15))
        assert best > 0.97

    def test_calm_wind_applies_no_bias(self):
        """풍압이 근거이므로 무풍이면 깎을 이유가 없다.

        기상 소스는 무풍일 때 풍향을 0.0(정북)으로 내보내는 일이 흔해서,
        이 가드가 없으면 북향이 아닌 측창이 영구히 leeward 로 갇힌다
        (2026-08-26 실측: 명령 24.6% 가 5.0% 로 나갔다).
        """
        w = wind_biased_opening(
            [_side('R', 1.0), _side('L', -1.0)], 0.0, ORI, wind_speed_ms=0.0)
        assert w['R'] == 1.0 and w['L'] == 1.0
