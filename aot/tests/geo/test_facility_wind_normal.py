# coding=utf-8
"""측창·박공 법선의 좌표 규약 — **지도가 그리는 대로**.

`_world_normal_from_sn` 은 지도가 시설을 그리는 식(지도 라벨 모듈의 `_toLngLat`,
`facility_bays._rect_ring`)을 (동, 북) 평면에 옮겨 적은 것이다:
model +X = 동, model +Z = 남, orientation_deg 가 늘면 +X 가 동 → 북 으로 돈다.

## 이력

- "3D 미리보기에서 만든 것을 지도에 배치하면 X축이 미러된다" 는 실제 문제가
  있었고, 그 보정으로 `_side_world_normal` 이 X 부호를 뒤집었다. 지도 렌더러가
  정리된 뒤 **보정만 남아** 동풍에 서쪽 창을 열었다(2026-08-26 실측, 방위
  11.5°). 현장에서 X 부호를 확인해 걷어냈다 — `TestDirectionMatchesTheField`.
- 그 뒤에도 nz 를 북 성분으로 넣고 회전을 시계로 돌리고 있었다. 둘이 겹치면
  지도 기준 법선을 남북으로 뒤집은 것과 같다 — 방위 11.5° 의 동·서 측창에서는
  북 성분이 ±0.2 라 실측이 못 잡았다. 2026-09-20 지도 변환과 대조해 고쳤다 —
  `TestMatchesTheMap`. 이 검사가 부호·회전 방향의 정본이다.

바꿔야 할 날이 오면 `_world_normal_from_sn` **한 곳**만 고친다.
"""
import math

from aot.aot_flask.geo.facility_bays import _rect_ring
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


def _map_normal(nx, nz, deg):
    """지도가 fitting 을 찍는 식(지도 라벨 모듈의 `_toLngLat`):
    rx(동) = x·cos + z·sin, rz(남) = −x·sin + z·cos → (동, 북)."""
    t = math.radians(deg)
    east = nx * math.cos(t) + nz * math.sin(t)
    south = -nx * math.sin(t) + nz * math.cos(t)
    return (east, -south)


class TestMatchesTheMap:
    """정본은 지도다 — 사용자가 화면에서 보는 것이 물리적 진실이다."""

    def test_agrees_with_the_fitting_transform_for_every_orientation(self):
        for deg in range(0, 360, 15):
            for sn in ([1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1], [0.6, 0, -0.8]):
                got = _world_normal_from_sn(sn, deg)
                exp = _map_normal(sn[0], sn[2], deg)
                assert math.isclose(got[0], exp[0], abs_tol=1e-9), (deg, sn)
                assert math.isclose(got[1], exp[1], abs_tol=1e-9), (deg, sn)

    def test_east_wall_normal_points_out_of_the_footprint_ring(self):
        """`_rect_ring` 이 그리는 사각형의 +X 변 바깥 방향과 같아야 한다."""
        for deg in (0, 30, 90, 150, 265):
            ring = _rect_ring(0.0, 0.0, 0.0, 0.0, 10.0, 40.0, deg)
            # 코너 1·2 가 +X 변 — 그 중점 방향(위도 0 이라 도→m 비례 동일)
            mx = (ring[1][0] + ring[2][0]) / 2
            my = (ring[1][1] + ring[2][1]) / 2
            n = math.hypot(mx, my)
            got = _world_normal_from_sn([1, 0, 0], deg)
            assert math.isclose(got[0], mx / n, abs_tol=1e-6), deg
            assert math.isclose(got[1], my / n, abs_tol=1e-6), deg

    def test_gable_plus_z_faces_south_at_zero(self):
        e, n = _world_normal_from_sn([0, 0, 1], 0.0)
        assert math.isclose(e, 0.0, abs_tol=1e-9) and math.isclose(n, -1.0, abs_tol=1e-9)

    def test_orientation_90_turns_east_wall_to_north(self):
        """footprint 는 90° 에서 +X 변을 북으로 돌린다 — 법선도 그래야 한다."""
        e, n = _world_normal_from_sn([1, 0, 0], 90.0)
        assert math.isclose(e, 0.0, abs_tol=1e-9) and math.isclose(n, 1.0, abs_tol=1e-9)


class TestDirectionMatchesTheField:
    """현장 확인된 방향 (2026-08-26): 미러 없음, model +X = 지도 East."""

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
