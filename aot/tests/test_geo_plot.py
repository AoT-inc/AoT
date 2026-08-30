# coding=utf-8
"""식생 구획(작기)의 불변식과 계약을 고정한다.

설계 정본: docs/design/geo-vegetation-plot.md

여기서 지키는 것 중 **깨져도 조용한 것**이 여럿이다:

- 겹침을 막는 제약이 나중에 들어오면(유니크 인덱스·검증) 간작·혼작이
  저장에서 거부된다. 정상 기능이 DB 에서 막히는 형태라 원인 도달이 늦다.
- 식생 구획이 `device_membership._CONTAINER_TYPES` 에 끼면 장치의 **소속**이
  작기마다 바뀌고, 작기가 끝나는 순간 그 장치가 무소속이 된다. 지도는
  멀쩡해 보이고 소속만 조용히 흔들린다.
- `typesToSync` 에 'vegetation' 이 들어가면 GeoShape 전량교체 저장 경로가
  식생을 자기 것으로 착각한다.
- `theme_keys` 화이트리스트에 'theme_plot' 이 없으면 색 피커는 색이
  바뀐 것처럼 보이고 새로고침하면 되돌아온다(2026-08-08 device_unit 이 그랬다).
- 미배정 면적을 단순 합으로 빼면 겹친 만큼 이중으로 빠져 음수가 된다.

DB 를 쓰는 것은 저장 경로 검증뿐이고, 나머지는 순수 계산·소스 검사다.
"""
import ast
import json
import os
import re
import unittest
from datetime import date, timedelta

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')

_MEMBERSHIP = os.path.join(_ROOT, 'aot_flask', 'geo', 'device_membership.py')
_MIGRATION = os.path.join(_ROOT, '..', 'alembic_db', 'alembic', 'versions',
                          'p6_34_geo_planting_20260813.py')
_ROUTES_GEO = os.path.join(_ROOT, 'aot_flask', 'routes_geo.py')
_DESIGN_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                          'aot-geo-design-v3.js')
_THEME_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                         'aot-geo-theme-colors.js')
_MODEL = os.path.join(_ROOT, 'databases', 'models', 'geo_plot.py')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _square(x0, y0, size):
    """(x0,y0) 에서 시작하는 정사각형 Polygon geometry."""
    return {
        'type': 'Polygon',
        'coordinates': [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0],
        ]],
    }


# ---------------------------------------------------------------------------
# 1. 면적 — 겹침이 있어도 미배정이 음수가 되지 않는다
# ---------------------------------------------------------------------------

class TestAreaMath(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import plot_context
        self.ctx = plot_context

    def _sh(self, geom):
        from shapely.geometry import shape
        return shape(geom)

    def test_area_of_known_square_is_close_to_expected(self):
        """0.001도 정사각형(적도 부근) ≈ 111.32m × 111.32m."""
        area = self.ctx.shapely_area_m2(self._sh(_square(0.0, 0.0, 0.001)))
        expected = 111.32 * 111.32
        self.assertAlmostEqual(area, expected, delta=expected * 0.02)

    def test_interior_ring_is_subtracted(self):
        """구멍을 빼지 않으면 미배정 면적이 실제보다 작게(음수까지) 나온다."""
        from shapely.geometry import Polygon

        outer = [(0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001), (0, 0)]
        hole = [(0.0002, 0.0002), (0.0008, 0.0002),
                (0.0008, 0.0008), (0.0002, 0.0008), (0.0002, 0.0002)]
        donut = Polygon(outer, [hole])
        solid = Polygon(outer)

        self.assertLess(self.ctx.shapely_area_m2(donut),
                        self.ctx.shapely_area_m2(solid))

    def test_union_of_overlapping_plots_counts_overlap_once(self):
        """겹친 구획 둘의 합집합 < 단순 합. 이것이 미배정 계산의 근거다."""
        from shapely.ops import unary_union

        a = self._sh(_square(0.0, 0.0, 0.001))
        b = self._sh(_square(0.0005, 0.0, 0.001))     # 절반 겹침

        simple_sum = (self.ctx.shapely_area_m2(a) +
                      self.ctx.shapely_area_m2(b))
        union = self.ctx.shapely_area_m2(unary_union([a, b]))

        self.assertLess(union, simple_sum)
        # 겹친 만큼 정확히 차이가 난다 (오차 2%)
        overlap = self.ctx.shapely_area_m2(a.intersection(b))
        self.assertAlmostEqual(simple_sum - union, overlap,
                               delta=overlap * 0.02)

    def test_empty_geometry_is_zero_not_error(self):
        self.assertEqual(self.ctx.shapely_area_m2(None), 0.0)


# ---------------------------------------------------------------------------
# 1b. 치수·식재량 — 면적 하나로 답할 수 없는 질문
# ---------------------------------------------------------------------------

# 김제(북위 약 35.8도). 경도 1도가 위도 1도의 0.81배로 줄어드는 위도라, 투영을
# 빼먹거나 도(degree) 공간에서 사각형을 구하면 폭과 길이가 눈에 띄게 갈린다.
_KIMJE_LAT = 35.8
_KIMJE_LNG = 126.88


def _rect_at(lng, lat, width_m, length_m, rot_deg=0.0):
    """(lng, lat) 를 좌하단으로 하는 width_m × length_m 직사각형 Polygon.

    `rot_deg` 로 비스듬히 놓을 수 있다 — 실제 두둑은 축에 정렬돼 있지 않고,
    축 정렬 bounding box 로 재면 그때 실제보다 크고 뚱뚱하게 나온다.
    """
    import math

    m_lat = 111320.0
    m_lng = m_lat * math.cos(math.radians(lat))
    t = math.radians(rot_deg)
    corners_m = [(0.0, 0.0), (width_m, 0.0), (width_m, length_m), (0.0, length_m)]
    ring = []
    for x, y in corners_m:
        rx = x * math.cos(t) - y * math.sin(t)
        ry = x * math.sin(t) + y * math.cos(t)
        ring.append([lng + rx / m_lng, lat + ry / m_lat])
    ring.append(ring[0])
    return {'type': 'Polygon', 'coordinates': [ring]}


class _FakeRow(object):
    """`dimensions()` 는 행에서 `feature` 만 읽는다 — DB 를 켤 이유가 없다."""

    def __init__(self, geometry):
        self.feature = {'type': 'Feature', 'properties': {},
                        'geometry': geometry}


class TestDimensions(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import plot_context
        self.ctx = plot_context

    def test_rectangular_plot_reports_its_two_sides(self):
        """40m × 46m ≈ 1837m² — 상추 구획 '앞두둑' 규모."""
        dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 40.0, 46.0)))

        self.assertAlmostEqual(dims['width_m'], 40.0, delta=0.5)
        self.assertAlmostEqual(dims['length_m'], 46.0, delta=0.5)
        # 네모난 구획은 외접사각형을 거의 다 채운다 → 경고가 뜨면 안 된다.
        self.assertGreater(dims['rect_fill_pct'], 95.0)
        self.assertIsNone(dims['shape_note'])

    def test_width_is_always_the_short_side(self):
        """줄 수를 짧은 변에서 세는 약속이 깨지면 '몇 줄' 의 답이 뒤집힌다."""
        for w, l in ((12.0, 60.0), (60.0, 12.0)):
            dims = self.ctx.dimensions(
                _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, w, l)))
            self.assertLess(dims['width_m'], dims['length_m'])
            self.assertAlmostEqual(dims['width_m'], 12.0, delta=0.3)

    def test_rotated_plot_measures_its_own_sides_not_the_axes(self):
        """비스듬한 두둑 — 축 정렬로 재면 폭이 두 배 가까이 부풀어 오른다."""
        dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 10.0, 50.0, rot_deg=35.0)))

        self.assertAlmostEqual(dims['width_m'], 10.0, delta=0.5)
        self.assertAlmostEqual(dims['length_m'], 50.0, delta=0.5)
        self.assertIsNone(dims['shape_note'])

    def test_dimensions_agree_with_area(self):
        """`width × length` 와 `area_m2` 가 같은 평면에서 재어져야 한다.

        투영 기준 위도가 갈리면 두 값이 설명 없이 어긋나고, 화면에서 그것을
        본 사람은 어느 쪽이 맞는지 알 방법이 없다.
        """
        row = _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 40.0, 46.0))
        dims = self.ctx.dimensions(row)
        product = dims['width_m'] * dims['length_m']
        self.assertAlmostEqual(product, self.ctx.area_m2(row),
                               delta=product * 0.02)

    def test_triangle_raises_the_shape_warning(self):
        """삼각형은 외접사각형의 절반만 채운다 — 경고가 없으면 AI 가 두 배로 센다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))
        tri = {'type': 'Polygon', 'coordinates': [[
            [_KIMJE_LNG, _KIMJE_LAT],
            [_KIMJE_LNG + 40.0 / m_lng, _KIMJE_LAT],
            [_KIMJE_LNG, _KIMJE_LAT + 46.0 / m_lat],
            [_KIMJE_LNG, _KIMJE_LAT],
        ]]}
        dims = self.ctx.dimensions(_FakeRow(tri))

        self.assertAlmostEqual(dims['rect_fill_pct'], 50.0, delta=3.0)
        self.assertIsNotNone(dims['shape_note'])
        self.assertIn('FEWER', dims['shape_note'])

    def test_l_shaped_plot_also_warns(self):
        """ㄱ자 밭 — 삼각형만 잡고 끝나는 임계값이면 쓸모가 없다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))

        def _p(x, y):
            return [_KIMJE_LNG + x / m_lng, _KIMJE_LAT + y / m_lat]

        ell = {'type': 'Polygon', 'coordinates': [[
            _p(0, 0), _p(40, 0), _p(40, 12), _p(12, 12), _p(12, 46), _p(0, 46),
            _p(0, 0),
        ]]}
        dims = self.ctx.dimensions(_FakeRow(ell))
        self.assertIsNotNone(dims['shape_note'])

    def test_missing_geometry_is_none_not_error(self):
        self.assertIsNone(self.ctx.dimensions(_FakeRow(None)))
        self.assertIsNone(self.ctx.dimensions(
            _FakeRow({'type': 'Point', 'coordinates': [1, 2]})))


class TestCapacityEstimate(unittest.TestCase):
    """평평한 배치 — 줄 간격 + 그루 간격."""

    def setUp(self):
        from aot.aot_flask.geo import plot_context
        self.ctx = plot_context
        self.dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 4.0, 20.0)))

    def test_counts_rows_across_the_short_side(self):
        """폭 4m 를 40cm 간격으로 → 10줄.

        11줄이 아니다. 기둥 세기(구간 수+1)로 세면 맨 바깥 두 줄이 경계선
        **위에** 서고, 그것은 밭에서 성립하지 않는다.
        """
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)

        self.assertEqual(cap['layout'], 'flat')
        self.assertEqual(cap['rows_possible'], 10)
        self.assertEqual(cap['plants_per_row'], int(2000 // 15))
        self.assertEqual(cap['total_plants'],
                         cap['rows_possible'] * cap['plants_per_row'])

    def test_half_spacing_stays_free_at_each_edge_by_default(self):
        """여백을 안 줘도 칸 세기가 양쪽에 간격 절반씩을 남긴다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)
        self.assertEqual(cap['edge_margin_cm'], 0.0)
        self.assertLessEqual(cap['rows_possible'] * 40, self.dims['width_m'] * 100)

    def test_basis_always_says_it_is_approximate(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)
        self.assertIn('Approximate', cap['basis'])
        self.assertIn('bounding rectangle', cap['basis'])
        self.assertIn('edge_margin_cm', cap['basis'])

    def test_shape_warning_is_carried_into_basis(self):
        """capacity 만 읽는 호출자에게도 형상 경고가 닿아야 한다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))
        tri = {'type': 'Polygon', 'coordinates': [[
            [_KIMJE_LNG, _KIMJE_LAT],
            [_KIMJE_LNG + 4.0 / m_lng, _KIMJE_LAT],
            [_KIMJE_LNG, _KIMJE_LAT + 20.0 / m_lat],
            [_KIMJE_LNG, _KIMJE_LAT],
        ]]}
        cap = self.ctx.capacity_estimate(
            self.ctx.dimensions(_FakeRow(tri)), 40, 15)
        self.assertIn('FEWER', cap['basis'])

    def test_edge_margin_eats_into_both_axes(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=100)

        self.assertEqual(cap['usable_width_m'], 2.0)
        self.assertEqual(cap['usable_length_m'], 18.0)
        self.assertEqual(cap['rows_possible'], 5)
        self.assertEqual(cap['plants_per_row'], 120)
        self.assertIn('100 cm was taken off each edge', cap['basis'])

    def test_margin_larger_than_the_plot_yields_zero_not_a_negative_count(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=300)
        self.assertEqual(cap['rows_possible'], 0)
        self.assertEqual(cap['total_plants'], 0)
        self.assertIn('Nothing fits', cap['basis'])

    def test_zero_margin_is_allowed_and_means_zero(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=0)
        self.assertEqual(cap['edge_margin_cm'], 0.0)
        self.assertEqual(cap['rows_possible'], 10)

    def test_nothing_asked_is_none(self):
        self.assertIsNone(self.ctx.capacity_estimate(self.dims))

    def test_plant_spacing_is_required_for_any_count(self):
        """그루 간격 없이는 어떤 배치에서도 셀 수 없다."""
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, 40)
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, edge_margin_cm=100)

    def test_flat_layout_needs_a_row_spacing(self):
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, None, 15)

    def test_garbage_spacing_is_rejected(self):
        for bad in (0, -40, 'abc'):
            with self.assertRaises(ValueError):
                self.ctx.capacity_estimate(self.dims, bad, 15)

    def test_negative_or_garbage_margin_is_rejected(self):
        for bad in (-10, 'abc'):
            with self.assertRaises(ValueError):
                self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=bad)


class TestBedLayout(unittest.TestCase):
    """두둑 배치 — 간격(고랑 포함) + 두둑당 줄 수.

    두둑 폭 + 고랑 폭 쌍은 폐기했다. 농부는 둘을 따로 세지 않아서, 같은 밭이
    120+40 으로도 160+0 으로도 기록됐다 — 에러 없이 두둑 수만 달라지는 종류다.
    """

    def setUp(self):
        from aot.aot_flask.geo import plot_context
        self.ctx = plot_context
        self.dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 4.0, 20.0)))

    def test_pitch_already_includes_the_furrow(self):
        """폭 4m 를 160cm 간격으로 → 두둑 2개. 두둑당 2줄이면 4줄."""
        cap = self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                         bed_pitch_cm=160, rows_per_bed=2)

        self.assertEqual(cap['layout'], 'beds')
        self.assertEqual(cap['beds_possible'], 2)
        self.assertEqual(cap['rows_per_bed'], 2)
        self.assertEqual(cap['rows_possible'], 4)
        self.assertNotIn('ask_user', cap)

    def test_row_spacing_is_neither_needed_nor_used(self):
        """두둑당 줄 수가 그 자리를 대신한다 — 요구하면 헛것을 묻는 셈이다."""
        cap = self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                         bed_pitch_cm=160, rows_per_bed=2)
        self.assertNotIn('row_spacing_cm', cap)

        with_row = self.ctx.capacity_estimate(
            self.dims, row_spacing_cm=40, plant_spacing_cm=15,
            bed_pitch_cm=160, rows_per_bed=2)
        self.assertEqual(with_row['rows_possible'], cap['rows_possible'])

    def test_basis_says_the_spacing_includes_the_furrow(self):
        """이 문장이 없으면 사용자가 두둑 윗면 폭을 넣어도 알 길이 없다."""
        cap = self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                         bed_pitch_cm=160, rows_per_bed=2)
        self.assertIn('includes the furrow', cap['basis'])
        self.assertIn('conservative', cap['basis'])

    def test_pitch_and_rows_must_come_together(self):
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                       bed_pitch_cm=160)
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                       rows_per_bed=2)

    def test_rows_per_bed_must_be_a_whole_number_of_one_or_more(self):
        for bad in (0, -1, 2.5, 'abc'):
            with self.assertRaises(ValueError):
                self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                           bed_pitch_cm=160, rows_per_bed=bad)

    def test_pitch_wider_than_the_plot_is_zero_with_a_reason(self):
        cap = self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                         bed_pitch_cm=600, rows_per_bed=2)
        self.assertEqual(cap['beds_possible'], 0)
        self.assertEqual(cap['total_plants'], 0)
        self.assertIn('not enough for one bed', cap['basis'])

    def test_bed_layout_combines_with_edge_margin(self):
        """여백을 먼저 빼고 남은 폭에 두둑을 놓는다."""
        cap = self.ctx.capacity_estimate(self.dims, plant_spacing_cm=15,
                                         edge_margin_cm=50, bed_pitch_cm=150,
                                         rows_per_bed=1)
        self.assertEqual(cap['usable_width_m'], 3.0)
        self.assertEqual(cap['beds_possible'], 2)


class TestFlatLayoutAsksForNotes(unittest.TestCase):
    """배치를 모르면 "노트로 남겨라" 고 시킨다 — 컬럼으로 저장하지 않는다.

    한 번 컬럼으로 만들었다가 되돌렸다. 대화에서 나오는 결론마다 컬럼을 늘릴
    수 없고, 모호한 말을 정수 칸에 밀어 넣으면 같은 밭이 두 가지로 기록된다.
    """

    def setUp(self):
        from aot.aot_flask.geo import plot_context
        self.ctx = plot_context
        self.dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 4.0, 20.0)))

    def test_flat_layout_carries_the_instruction(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)
        self.assertEqual(cap['layout'], 'flat')
        self.assertIn('ask_user', cap)

    def test_it_points_at_a_note_not_a_column(self):
        """노트가 정본이다. 저장 도구(modify_plot)를 시키면 안 된다."""
        ask = self.ctx._FLAT_LAYOUT_ASK
        self.assertIn('create_note', ask)
        self.assertIn("target_type=\"plot\"", ask)
        self.assertNotIn('modify_plot', ask)

    def test_it_asks_the_pitch_as_one_number(self):
        """두둑과 고랑을 따로 물으면 같은 밭이 두 가지로 기록된다."""
        ask = self.ctx._FLAT_LAYOUT_ASK
        self.assertIn('ONE number', ask)
        self.assertIn('bed_pitch_cm', ask)
        self.assertIn('rows_per_bed', ask)

    def test_it_names_no_country(self):
        """ko/ja 를 함께 쓰고 설치처의 나라도 고정이 아니다."""
        ask = self.ctx._FLAT_LAYOUT_ASK
        for banned in ('Korea', 'Korean', 'Japan', 'Japanese'):
            self.assertNotIn(banned, ask)


class TestPlotNotesAreVisible(unittest.TestCase):
    """구획 노트가 AI 컨텍스트에 실리는 통로 — 여기가 비면 "적어 두라" 가 헛돈다."""

    def test_note_digest_resolves_plot_names(self):
        src = _read(os.path.join(_ROOT, 'ai', 'services', 'ai_context_service.py'))
        digest = src[src.index('def get_note_digests'):]
        digest = digest[:digest.index('def ', 10)]
        self.assertIn('GeoPlot', digest,
                      '구획이 이름맵에 없으면 노트가 다이제스트에서 버려진다')
        self.assertIn("'plot'", digest)


# ---------------------------------------------------------------------------
# 2. 상위 zone 을 받지도, 자르지도 않는다 (equipment 와 같은 모델)
# ---------------------------------------------------------------------------

class TestNoParentSelection(unittest.TestCase):
    """구획을 만들 때 사용자가 zone 을 고르는 절차가 없어야 한다.

    equipment 는 상위를 사람이 고르지 않는다 — 그냥 그리고
    `recalculateSpatialRelationships()` 가 공간 포함으로 파생한다. 식생도 같다.

    예전에는 `zone_uuid` 를 받아 경계로 자르고 밖이면 거부했는데, 식생 모드에서
    zone 도형은 **클릭조차 되지 않아**(다른 모드의 레이어다) 사용자가 고를 방법이
    없었다. 할 수 없는 일을 요구하는 절차였다. 되살리지 말 것.
    """

    def test_write_path_takes_no_zone_and_no_clip(self):
        import inspect
        from aot.aot_flask.geo import plot_io

        sig = inspect.signature(plot_io.save_plot)
        self.assertEqual(list(sig.parameters), ['data'],
                         'save_plot 에 clip 같은 축이 되살아났다')

        code = '\n'.join(
            l for l in _read(plot_io.__file__.replace('.pyc', '.py')).splitlines()
            if not l.lstrip().startswith('#'))
        self.assertNotIn('clip_to_zone', code)
        self.assertNotIn("data.get('zone_uuid')", code)

    def test_client_does_not_send_zone_uuid_when_creating(self):
        js = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                          'design', 'aot-geo-plot.js')
        code = '\n'.join(
            line for line in _read(js).splitlines()
            if not line.lstrip().startswith(('*', '//', '/*')))
        self.assertNotIn('zone_uuid:', code,
                         '생성 페이로드에 zone_uuid 가 되살아났다')
        self.assertNotIn('_selectedZoneUuid', code)

    def test_zone_is_still_derived_for_reading(self):
        """저장 때 안 받을 뿐, 읽을 때는 여전히 공간 포함으로 파생한다."""
        from aot.aot_flask.geo import plot_context
        self.assertTrue(hasattr(plot_context, 'zone_for_plot'))


# ---------------------------------------------------------------------------
# 3. 쓰기 검증 (VP-1 · VP-2 · VP-4)
# ---------------------------------------------------------------------------

class TestWriteValidation(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import plot_io
        self.io = plot_io

    def test_geometry_must_be_polygon(self):
        for geom in ({'type': 'Point', 'coordinates': [1, 2]},
                     {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}):
            err = self.io._validate_geometry({'geometry': geom})
            self.assertIsNotNone(err, '%s 가 통과했다' % geom['type'])

    def test_polygon_passes(self):
        self.assertIsNone(
            self.io._validate_geometry({'geometry': _square(0, 0, 0.001)}))

    def test_forbidden_props_are_stripped(self):
        feature = {'properties': {'device_id': 'abc', 'channel_id': '0',
                                  'color': '#fff', 'name': '두둑1'}}
        cleaned, removed = self.io._strip_forbidden(feature)
        self.assertEqual(cleaned['properties'], {'name': '두둑1'})
        self.assertEqual(set(removed), {'device_id', 'channel_id', 'color'})

    def test_date_parsing_rejects_garbage(self):
        value, err = self.io._parse_date('2026-13-99', 'started_on')
        self.assertIsNone(value)
        self.assertIsNotNone(err)

    def test_date_parsing_accepts_iso_and_empty(self):
        value, err = self.io._parse_date('2026-08-13', 'started_on')
        self.assertEqual(value, date(2026, 8, 13))
        self.assertIsNone(err)

        value, err = self.io._parse_date('', 'ended_on')
        self.assertIsNone(value)
        self.assertIsNone(err)


# ---------------------------------------------------------------------------
# 4. 수명 판정 — 30일부터 30년까지 같은 구조
# ---------------------------------------------------------------------------

class TestLifetime(unittest.TestCase):
    def _row(self, planted, ended=None):
        from aot.databases.models import GeoPlot
        return GeoPlot(geo_id='m', feature={}, subject='c',
                           started_on=planted, ended_on=ended)

    def test_open_ended_is_active_for_decades(self):
        """종료일이 없는 행 하나가 과수 30년을 담는다."""
        row = self._row(date.today() - timedelta(days=365 * 30))
        self.assertTrue(row.is_active())

    def test_ended_in_past_is_inactive(self):
        row = self._row(date.today() - timedelta(days=60),
                        date.today() - timedelta(days=1))
        self.assertFalse(row.is_active())

    def test_ends_today_is_already_inactive(self):
        """종료일 당일부터 활성이 아니다.

        `>= on` 으로 두면 "재배 종료"를 누른 사람이 화면에서는 사라진 구획을
        새로고침하면 다시 보게 된다. 하루만 어긋나는 종류라 신고되기 어렵다.
        `active_plots` 의 쿼리와 같은 부등호를 써야 한다.
        """
        row = self._row(date.today() - timedelta(days=30), date.today())
        self.assertFalse(row.is_active())

    def test_ends_tomorrow_is_still_active(self):
        row = self._row(date.today() - timedelta(days=30),
                        date.today() + timedelta(days=1))
        self.assertTrue(row.is_active())

    def test_future_plot_is_not_active_yet(self):
        row = self._row(date.today() + timedelta(days=7))
        self.assertFalse(row.is_active())


# ---------------------------------------------------------------------------
# 5. 겹침 허용 (VP-3) — 막는 장치가 생기지 않았는지 소스로 확인
# ---------------------------------------------------------------------------

class TestNoHardcodedLocale(unittest.TestCase):
    """AI 에게 보내는 문구에 특정 나라의 관행을 박지 않는다.

    첫 판에 "Most **Korean** open-field vegetables…" 라고 적었다. 이 제품은
    ko/ja 를 함께 쓰고 설치처의 나라도 고정이 아니라, 다른 지역 사용자에게는
    틀린 근거가 된다. 두둑 농사 자체는 어디서나 흔하므로 나라 이름 없이도
    같은 말이 된다.
    """

    def test_ask_user_text_names_no_country(self):
        from aot.aot_flask.geo import plot_context
        text = plot_context._FLAT_LAYOUT_ASK
        for banned in ('Korea', 'Korean', 'Japan', 'Japanese'):
            self.assertNotIn(banned, text)

    def test_no_bed_layout_ui_strings_remain(self):
        """두둑 배치는 화면 입력이 아니라 노트로 남긴다 — 라벨이 되살아나면 안 된다.

        26.08.5 에 지도 폼의 두둑 폭·고랑 폭 입력과 ko/ja 라벨이 있었고,
        p6_36 에서 컬럼과 함께 걷어냈다. 다시 들어오면 노트 정본과 화면 입력이
        두 벌이 되어, 같은 밭이 두 군데에 서로 다르게 적히게 된다.
        """
        from babel.messages.pofile import read_po

        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'design', 'aot-geo-plot.js'))
        for banned in ('Bed layout', 'Bed width (cm)', 'Furrow width (cm)',
                       'bed_width_cm', 'path_width_cm'):
            self.assertNotIn(banned, js)

        for lang in ('ko', 'ja'):
            path = os.path.join(_ROOT, 'aot_flask', 'translations', lang,
                                'LC_MESSAGES', 'messages.po')
            with open(path, encoding='utf-8') as fh:
                cat = read_po(fh)
            for banned in ('Bed layout', 'Bed width (cm)', 'Furrow width (cm)'):
                self.assertNotIn(banned, cat,
                                 '%s: 걷어낸 라벨 %r 가 되살아났다' % (lang, banned))


class TestSplitShape(unittest.TestCase):
    """대지/구역을 식생 구획으로 분할한다 — 긴 변 방향을 따른다.

    LLM 은 구역이 지도 어디에 있는지 알 방법이 없어(어떤 도구도 경계 폴리곤을
    안 내준다) 좌표를 지어내면 엉뚱한 자리에 조용히 저장된다. 그래서 사람이
    이미 그려 둔 도형을 서버가 나눈다.
    """

    def setUp(self):
        from aot.aot_flask.geo import plot_split
        self.ps = plot_split

    def _rot_rect(self, w, l, rot=0.0):
        return _rect_at(_KIMJE_LNG, _KIMJE_LAT, w, l, rot_deg=rot)

    def test_parts_gives_that_many_pieces(self):
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=3)
        self.assertEqual(len(strips), 3)
        self.assertEqual(info['count'], 3)
        # 등분은 남는 폭이 없다 — 세 조각이 도형을 다 덮는다.
        self.assertAlmostEqual(info['covered_area_m2'], info['source_area_m2'],
                               delta=info['source_area_m2'] * 0.02)

    def test_strip_width_gives_floor_of_the_short_axis(self):
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           strip_width_cm=400)
        self.assertEqual(len(strips), 7)      # 30m / 4m = 7.5 → 7
        self.assertEqual(info['strip_width_m'], 4.0)

    def test_pieces_run_along_the_longest_side(self):
        """축이 아니라 **밭의 긴 방향**을 따라야 한다.

        35도 기울어진 10x50 밭을 축(정북)으로 자르면 조각이 밭을 비스듬히
        가로질러 길이가 50m 가 안 나온다. 긴 변을 따르면 50m 가 나온다.
        """
        strips, info = self.ps.split_shape(self._rot_rect(10.0, 50.0, rot=35.0),
                                           parts=2, orientation='long')
        for b in strips:
            self.assertAlmostEqual(b['length_m'], 50.0, delta=1.0)
        # 방향은 0~180 으로 정규화된 값이고, 35도 회전한 긴 변은 125도다
        # (긴 변이 원래 세로였으므로 35+90).
        self.assertAlmostEqual(info['orientation_deg'], 125.0, delta=2.0)

    def test_edge_margin_shrinks_inward(self):
        """여백은 안쪽 버퍼다 — 외접사각형에서 빼면 오목한 곳에 안 남는다."""
        plain, _ = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                       orientation='long')
        inset, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                          orientation='long', edge_margin_m=2)
        self.assertLess(info['covered_area_m2'],
                        sum(b['area_m2'] for b in plain))
        for b in inset:
            self.assertAlmostEqual(b['length_m'], 86.0, delta=1.5)

    def test_concave_shape_breaks_a_strip_into_separate_pieces(self):
        """끊긴 띠는 각각 다른 구획이다 — 하나로 묶으면 길이가 거짓이 된다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))

        def _p(x, y):
            return [_KIMJE_LNG + x / m_lng, _KIMJE_LAT + y / m_lat]

        # ㄷ자: 가운데가 깊게 파여 위쪽 띠가 좌우로 끊긴다.
        u = {'type': 'Polygon', 'coordinates': [[
            _p(0, 0), _p(60, 0), _p(60, 40), _p(40, 40), _p(40, 10),
            _p(20, 10), _p(20, 40), _p(0, 40), _p(0, 0),
        ]]}
        # parts 단독 기본값이 'short' 로 바뀌었다 — 이 노치는 가로띠(long)로
        # 잘라야만 끊긴다(세로띠로 자르면 안 끊긴다), 그래서 방향을 고정한다.
        strips, info = self.ps.split_shape(u, parts=2, orientation='long')
        self.assertGreater(len(strips), 2, '끊긴 조각이 합쳐졌다')
        self.assertEqual(info['count'], len(strips))

    def test_parts_survives_the_loop(self):
        """루프 안 지역변수가 파라미터 `parts` 를 덮으면 안 된다.

        구현 중 실제로 `parts = list(piece.geoms)` 로 덮어썼다 — each_input
        클로버 버그와 같은 형태다. 오목한 도형은 띠가 끊겨 그 경로를 반드시
        지나므로 여기서 걸린다.
        """
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))

        def _p(x, y):
            return [_KIMJE_LNG + x / m_lng, _KIMJE_LAT + y / m_lat]

        u = {'type': 'Polygon', 'coordinates': [[
            _p(0, 0), _p(60, 0), _p(60, 40), _p(40, 40), _p(40, 10),
            _p(20, 10), _p(20, 40), _p(0, 40), _p(0, 0),
        ]]}
        for n in (2, 3, 5):
            # parts 단독 기본값이 'short' 로 바뀌면서 이 노치는 세로띠로는
            # 안 끊긴다 — 위 docstring 이 말하는 경로를 실제로 타려면 방향을
            # 고정해야 한다.
            strips, info = self.ps.split_shape(u, parts=n, orientation='long')
            self.assertIsNotNone(strips, info)

    def test_neither_parts_nor_width_is_rejected(self):
        """적어도 하나는 줘야 한다 — 굵기를 사용자가 정하지 않으면 안 된다."""
        geom = self._rot_rect(30.0, 90.0)
        out, err = self.ps.split_shape(geom)
        self.assertIsNone(out)
        self.assertIn('parts', err)

    def test_parts_one_uses_the_whole_area(self):
        """`parts=1` 은 "나누지 않는다" — 구역 전체가 구획 하나가 된다.

        예전에는 2 이상만 받아서, 밭 하나를 통째로 한 작기로 쓰려는 사람이
        이 도구를 아예 쓸 수 없었다(도형을 손으로 다시 그려야 했다)."""
        geom = self._rot_rect(30.0, 90.0)
        # parts=1 은 나누지 않으므로 어느 축을 골라도 같은 폴리곤이 나오지만,
        # strip_widths_m 이 보고하는 축(=orientation)은 여전히 갈린다 — 기본값
        # 자체(모드별 분기)는 아래 test_orientation_default_depends_on_mode 가
        # 다루므로 여기서는 'long' 을 고정해 원래 숫자(30.0)를 그대로 본다.
        strips, info = self.ps.split_shape(geom, parts=1, orientation='long')
        self.assertEqual(len(strips), 1)
        self.assertEqual(info['count'], 1)
        # 도형 전체를 덮는다 — 잘려 나간 면적이 없어야 한다.
        self.assertAlmostEqual(info['covered_area_m2'], info['source_area_m2'],
                               delta=1.0)
        self.assertEqual(info['strip_widths_m'], [30.0])

    def test_parts_one_still_honours_edge_margin(self):
        """전체를 쓰더라도 가장자리 여백은 그대로 적용된다 — 여백을 준 만큼
        안으로 들어온 하나가 나온다."""
        geom = self._rot_rect(30.0, 90.0)
        whole, _i1 = self.ps.split_shape(geom, parts=1)
        inset, _i2 = self.ps.split_shape(geom, parts=1, edge_margin_m=2)
        self.assertEqual(len(inset), 1)
        self.assertLess(inset[0]['area_m2'], whole[0]['area_m2'])

    def test_parts_one_does_not_warn_about_aspect_ratio(self):
        """나눌 것이 없는데 "짧은 변으로 바꿔 보라" 는 조언은 할 말이 아니다."""
        # 30x90 은 3:1 이라 경고 기준(4:1) 아래지만, 가늘고 긴 밭이면
        # parts=1 에서도 종횡비가 크게 잡힌다 — 아예 내지 않는 것이 맞다.
        _s, info = self.ps.split_shape(self._rot_rect(10.0, 90.0), parts=1)
        self.assertIsNone(info['aspect_ratio'])
        self.assertNotIn("orientation='short'", info['note'])

    def test_parts_zero_or_negative_is_still_rejected(self):
        for bad in (0, -1):
            out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=bad)
            self.assertIsNone(out, 'parts=%r should be rejected' % bad)
            self.assertIn('parts', err)

    def test_parts_and_width_together_gives_exact_count_at_exact_width(self):
        """둘 다 주면 균등분할이 아니다 — 정확히 N개, 정확히 W 폭, 남는 만큼 여백.

        30x90 사각형(짧은 축 30m)에서 parts=3, strip_width_cm=400(4m)를 같이
        주면: 3개 × 4m = 12m 만 자르고, 남는 18m 은 양쪽에 9m 씩 여백이 된다.
        parts 만 줬다면(등분) 조각 폭이 10m 이었을 것이고, strip_width_cm 만
        줬다면(자동) 개수가 7개 나왔을 것이다 — 둘 다 다른 결과다.
        """
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=3,
                                           strip_width_cm=400)
        self.assertEqual(len(strips), 3)
        self.assertEqual(info['count'], 3)
        self.assertAlmostEqual(info['strip_width_m'], 4.0)
        for b in strips:
            self.assertAlmostEqual(b['length_m'], 90.0, delta=1.0)
        # 3*4=12m 만 덮는다 — 30m 전체를 덮는 등분(parts=3)과는 다르다.
        self.assertAlmostEqual(info['covered_area_m2'], 12.0 * 90.0,
                               delta=12.0 * 90.0 * 0.05)
        self.assertIn('leftover', info['note'])

    def test_parts_and_width_together_respects_orientation_and_angle(self):
        """조합 모드도 방향/각도 파라미터를 그대로 받는다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                           strip_width_cm=400,
                                           orientation='short')
        self.assertEqual(len(strips), 2)
        for b in strips:
            self.assertAlmostEqual(b['length_m'], 30.0, delta=1.0)

    def test_parts_and_width_together_rejects_when_shape_too_small(self):
        """N개 * W 폭이 짧은 축보다 크면 여백이 음수가 되므로 거부한다."""
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=10,
                                       strip_width_cm=400)
        self.assertIsNone(out)
        self.assertIn('short axis', err)

    def test_parts_and_width_together_differs_from_either_alone(self):
        """세 입력 조합이 서로 다른 결과를 낸다는 것을 명시적으로 고정한다."""
        geom = self._rot_rect(30.0, 90.0)
        parts_only, _ = self.ps.split_shape(geom, parts=3)
        width_only, _ = self.ps.split_shape(geom, strip_width_cm=400)
        both, _ = self.ps.split_shape(geom, parts=3, strip_width_cm=400)
        self.assertEqual(len(parts_only), 3)
        self.assertEqual(len(width_only), 7)
        self.assertEqual(len(both), 3)
        self.assertNotAlmostEqual(parts_only[0]['area_m2'], both[0]['area_m2'],
                                  delta=0.01)

    # -- widths_cm: 조각마다 다른 폭 ----------------------------------------

    def test_widths_cm_gives_each_piece_its_own_width(self):
        """세 조각을 각각 다른 폭으로 — 등분이 아니다.

        widths_cm 단독 기본값이 'short' 로 바뀌었으므로(순수 parts 와 같은
        취급), 90m 축을 따라 놓이는지 확인하려면 'long' 을 고정해야 한다.
        """
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           widths_cm=[500, 1000, 300],
                                           orientation='long')
        self.assertEqual(len(strips), 3)
        self.assertEqual(info['count'], 3)
        self.assertEqual(info['strip_widths_m'], [5.0, 10.0, 3.0])
        for b in strips:
            self.assertAlmostEqual(b['length_m'], 90.0, delta=1.0)
        # 조각 면적이 폭에 비례해 서로 다르다(90m 길이 * 폭).
        widths_sorted = sorted(s['area_m2'] for s in strips)
        self.assertLess(widths_sorted[0], widths_sorted[1])
        self.assertLess(widths_sorted[1], widths_sorted[2])
        # 5+10+3=18m, 짧은 축 30m 중 12m 이 여백 — note 에 남는다.
        self.assertIn('leftover', info['note'])

    def test_widths_cm_overrides_parts_and_strip_width_cm(self):
        """셋 다 주면 widths_cm 가 이긴다 — 나머지는 조용히 무시된다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           parts=99, strip_width_cm=1,
                                           widths_cm=[500, 500])
        self.assertEqual(len(strips), 2)
        self.assertEqual(info['strip_widths_m'], [5.0, 5.0])

    def test_widths_cm_accepts_a_single_piece(self):
        """폭 하나짜리 목록도 받는다 — `parts=1` 에서 시작해 개별 폭 조정을
        켜면 조각이 하나뿐인 목록이 만들어진다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           widths_cm=[500])
        self.assertEqual(len(strips), 1)
        self.assertEqual(info['strip_widths_m'], [5.0])

    def test_widths_cm_rejects_empty_list(self):
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0), widths_cm=[])
        self.assertIsNone(out)
        self.assertIn('widths_cm', err)

    def test_widths_cm_rejects_non_positive_width(self):
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                       widths_cm=[500, 0])
        self.assertIsNone(out)
        self.assertIn('widths_cm', err)

    def test_widths_cm_last_piece_is_clamped_when_it_overflows(self):
        """마지막 조각만 커서 넘치면 거부 대신 들어가는 만큼 잘라 준다 —
        조각을 하나씩 입력하다 마지막 값이 남는 자리보다 큰, 실사용에서
        흔한 경우. 'long' 고정 — widths_cm 기본값('short')이면 짧은 축이
        90m 가 되어 40m 가 넘치지 않는다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           widths_cm=[2000, 2000],
                                           orientation='long')
        self.assertIsNotNone(strips)
        self.assertEqual(len(strips), 2)
        # 첫 조각은 요청대로 20m, 마지막은 남는 10m로 줄어든다(첫 조각을
        # 안 건드리는 것이 "마지막이 커서 넘쳤다" 는 문제 정의와 맞다).
        self.assertEqual(info['strip_widths_m'], [20.0, 10.0])
        self.assertEqual(info['widths_clamped_from_cm'], 2000)
        self.assertIn('shortened', info['note'])

    def test_widths_cm_rejects_when_earlier_pieces_alone_exceed_short_axis(self):
        """마지막 조각을 0으로 줄여도 안 들어가면 "마지막이 커서" 가 아니라
        애초에 안 맞는 요청이다 — 그때는 그대로 거부한다. 'long' 고정 —
        기본값('short')이면 짧은 축이 90m 가 되어 3500cm 도 들어간다."""
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                       widths_cm=[3500, 500],
                                       orientation='long')
        self.assertIsNone(out)
        self.assertIn('short axis', err)

    def test_widths_cm_respects_orientation_and_angle(self):
        """조합 모드와 마찬가지로 widths_cm 도 방향/각도를 그대로 받는다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           widths_cm=[500, 1000],
                                           orientation='short')
        for b in strips:
            self.assertAlmostEqual(b['length_m'], 30.0, delta=1.0)

    def test_widths_cm_round_trip_from_equal_split_is_accepted(self):
        """UI 는 균등분할의 strip_widths_m(cm 반올림)을 그대로 되돌려보낸다
        (개별 폭 조정 토글을 막 켰을 때). 부동소수 합산 오차만으로 "정확히
        도형 크기인데 초과" 판정이 나면 안 된다 — 실사용에서 68.2/68.2 처럼
        딱 맞아떨어지는 경계에서 걸린 회귀. 'long' 을 양쪽에 고정한다 — 짧은
        축(68.2m)에 걸리는 경계를 재현하려는 것이라, 두 호출이 기본값('short'
        면 짧은 축이 90m 가 되어 경계 자체가 사라진다)에 각자 알아서 맡기면
        안 된다."""
        shape = self._rot_rect(68.2, 90.0)
        _s, info = self.ps.split_shape(shape, parts=3, orientation='long')
        widths_cm = [round(w * 100) for w in info['strip_widths_m']]
        strips, info2 = self.ps.split_shape(shape, widths_cm=widths_cm,
                                            orientation='long')
        self.assertIsNotNone(strips)
        self.assertEqual(len(strips), 3)

    def test_uniform_modes_also_report_strip_widths_m(self):
        """등분·자동폭·조합 모드도 조각별 폭 리스트를 낸다 — 전부 같은 값의
        반복이지만, UI 가 모드에 관계없이 이 리스트 하나로 개별 폭 입력칸을
        채울 수 있어야 한다. parts 는 'long' 고정 — 기본값('short')이면 짧은
        축이 90m 가 되어 폭이 [10,10,10]이 아니라 [30,30,30]이 된다."""
        _s, info_parts = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=3,
                                             orientation='long')
        self.assertEqual(info_parts['strip_widths_m'], [10.0, 10.0, 10.0])
        _s, info_width = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                             strip_width_cm=400)
        self.assertEqual(info_width['strip_widths_m'], [4.0] * 7)

    def test_too_many_pieces_is_refused_not_truncated(self):
        """조용히 자르면 사용자는 자기가 본 것이 전부인 줄 안다."""
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                       strip_width_cm=1)
        self.assertIsNone(out)
        self.assertIn('more than this tool will propose', err)

    def test_strip_wider_than_the_shape_is_refused(self):
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                       strip_width_cm=5000)
        self.assertIsNone(out)
        self.assertIn('across its short axis', err)

    def test_covered_area_is_not_called_planted_area(self):
        """띠는 도형을 빈틈없이 덮는다 — 고랑을 뺀 식재 면적이 아니다.

        고랑 폭을 모르는 것이 이 설계의 선택이므로 식재 면적은 낼 수 없다.
        이름이 'planted' 였다면 그 숫자가 그대로 모종 주문량이 된다.
        """
        _strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=3)
        self.assertIn('covered_area_m2', info)
        self.assertNotIn('planted_area_m2', info)
        self.assertIn('NOT the plantable area', info['note'])

    def test_orientation_short_cuts_across_the_long_side(self):
        """orientation='short' 는 짧은 변을 눕혀 정방형에 가까운 조각을 낸다.

        재현 사례: 2,618.6㎡ 구역을 parts=5 로 나누면 6.43m×81.7m(12.7:1)가
        나왔다 — 짧은 변(32m) 기준이면 32m×16.4m(2:1)로 훨씬 정방형에
        가까웠을 것이다. 여기서는 30x90 사각형으로 같은 관계를 고정한다.
        """
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                           orientation='short')
        self.assertEqual(len(strips), 2)
        for b in strips:
            self.assertAlmostEqual(b['length_m'], 30.0, delta=1.0)
        self.assertAlmostEqual(info['strip_width_m'], 45.0, delta=0.5)
        self.assertAlmostEqual(info['orientation_deg'], 0.0, delta=2.0)
        self.assertEqual(info['orientation'], 'short')

    def test_orientation_default_depends_on_strip_width_cm(self):
        """생략하면 모드로 정해진다 — strip_width_cm 이 있으면(단독/조합)
        'long', 순수 parts 나 widths_cm 단독이면 'short'.

        strip_width_cm(두둑)은 고랑 방향이 실제 작업 방향과 맞아야 하므로
        방향을 바꾸지 않는다는 계약이 이 테스트의 핵심이다 — 여기서 회귀가
        나면 실제 두둑이 엉뚱한 방향으로 잘린다.
        """
        _s, info_parts = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2)
        self.assertEqual(info_parts['orientation'], 'short')

        _s, info_strip = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                             strip_width_cm=400)
        self.assertEqual(info_strip['orientation'], 'long')

        # 조합(parts + strip_width_cm)도 strip_width_cm 쪽 계약을 따른다.
        _s, info_both = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                            strip_width_cm=400)
        self.assertEqual(info_both['orientation'], 'long')

        # widths_cm 단독은 parts 단독과 같은 취급 — 'short'.
        _s, info_widths = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                              widths_cm=[500, 500])
        self.assertEqual(info_widths['orientation'], 'short')

    def test_explicit_orientation_overrides_the_mode_default(self):
        """직접 주면 모드와 상관없이 그 값이 이긴다 — 생략했을 때만 자동."""
        _s, info_parts_long = self.ps.split_shape(
            self._rot_rect(30.0, 90.0), parts=2, orientation='long')
        self.assertEqual(info_parts_long['orientation'], 'long')

        _s, info_strip_short = self.ps.split_shape(
            self._rot_rect(30.0, 90.0), strip_width_cm=400, orientation='short')
        self.assertEqual(info_strip_short['orientation'], 'short')

    def test_default_orientation_matches_an_explicit_call_with_the_same_result(self):
        """생략과 그 결과에 해당하는 명시적 값이 완전히 같은 조각을 낸다."""
        strips_default, info_default = self.ps.split_shape(
            self._rot_rect(30.0, 90.0), parts=2)
        strips_short, info_short = self.ps.split_shape(
            self._rot_rect(30.0, 90.0), parts=2, orientation='short')
        self.assertAlmostEqual(info_default['strip_width_m'],
                               info_short['strip_width_m'])
        for a, b in zip(strips_default, strips_short):
            self.assertAlmostEqual(a['length_m'], b['length_m'], delta=0.1)

    def test_invalid_orientation_is_rejected(self):
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                       orientation='sideways')
        self.assertIsNone(out)
        self.assertIn('orientation', err)

    def test_aspect_ratio_flags_long_narrow_parts_split(self):
        """parts 등분이 가늘고 길면 orientation='short' 를 쓰라고 알린다.

        'long' 고정 — 기본값이 'short' 로 바뀐 뒤에도 명시적으로 긴 변을
        고르면 여전히 가늘고 길어질 수 있다는 것을 확인한다. 기본값 자체가
        이 문제를 피해가는지는 아래
        test_default_short_for_parts_avoids_the_narrow_aspect_ratio 가 본다.
        """
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=5,
                                           orientation='long')
        self.assertIsNotNone(info['aspect_ratio'])
        self.assertGreater(info['aspect_ratio'], 4.0)
        self.assertIn("orientation='short'", info['note'])

    def test_default_short_for_parts_avoids_the_narrow_aspect_ratio(self):
        """실사용 재현 사례 — 예전 기본값(긴 변)이면 이 요청이 12.7:1 짜리
        가늘고 긴 조각을 냈다. 기본값이 'short' 로 바뀐 지금은 같은 요청이
        정방형에 가까운 조각을 내고, 경고도 붙지 않는다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=5)
        self.assertIsNotNone(strips)
        self.assertLess(info['aspect_ratio'], 4.0)
        self.assertNotIn("orientation='short'", info['note'])

    def test_aspect_ratio_absent_for_strip_width_mode(self):
        """두둑 폭 지정은 원래 가늘고 길다 — parts 전용 경고 대상이 아니다."""
        _strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                            strip_width_cm=400)
        self.assertIsNone(info['aspect_ratio'])
        self.assertNotIn("orientation=", info['note'])

    # -- angle_deg: 임의 각도가 orientation 프리셋을 덮어쓴다 --------------

    def test_angle_deg_sets_a_custom_direction(self):
        """angle_deg 는 long/short 프리셋이 아닌 임의 각도를 그대로 쓴다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                           angle_deg=45.0)
        self.assertIsNotNone(strips)
        self.assertAlmostEqual(info['orientation_deg'], 45.0, delta=1.0)
        self.assertEqual(info['orientation'], 'custom')
        self.assertIn('custom', info['note'])

    def test_angle_deg_overrides_orientation_when_both_given(self):
        """둘 다 주어지면 angle_deg 가 이긴다 — orientation 은 조용히 무시된다.

        rot_rect(10, 50, rot=35) 의 긴 변은 125도다(다른 테스트에서 고정한
        값). orientation='short' 만 줬다면 (125+90)%180=35도가 나왔을
        것이다 — angle_deg=125 를 같이 주면 그 대신 125도가 나와야 한다.
        """
        strips, info = self.ps.split_shape(self._rot_rect(10.0, 50.0, rot=35.0),
                                           parts=2, orientation='short',
                                           angle_deg=125.0)
        self.assertIsNotNone(strips)
        self.assertAlmostEqual(info['orientation_deg'], 125.0, delta=2.0)
        self.assertEqual(info['orientation'], 'custom')

    def test_angle_deg_works_with_strip_width_mode_too(self):
        """orientation 과 달리 angle_deg 는 두둑(strip_width_cm) 경로도 받는다."""
        strips, info = self.ps.split_shape(self._rot_rect(30.0, 90.0),
                                           strip_width_cm=400, angle_deg=90.0)
        self.assertIsNotNone(strips)
        self.assertAlmostEqual(info['orientation_deg'], 90.0, delta=1.0)

    def test_angle_deg_out_of_range_is_rejected(self):
        for bad in (180.0, -1.0, 360.0):
            out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                           angle_deg=bad)
            self.assertIsNone(out, 'angle_deg=%r should have been rejected' % bad)
            self.assertIn('angle_deg', err)

    def test_angle_deg_non_numeric_is_rejected(self):
        out, err = self.ps.split_shape(self._rot_rect(30.0, 90.0), parts=2,
                                       angle_deg='sideways')
        self.assertIsNone(out)
        self.assertIn('angle_deg', err)

    def test_angle_deg_absent_leaves_orientation_behavior_unchanged(self):
        """회귀: angle_deg 를 안 주면 orientation 만으로 지금과 같이 동작한다.

        parts 단독 기본값이 'short' 로 바뀌었으므로, 'long' 쪽은 명시적으로
        고정해야 이 테스트가 원래 의도(두 프리셋을 대조)대로 성립한다.
        """
        strips_long, info_long = self.ps.split_shape(
            self._rot_rect(30.0, 90.0), parts=2, orientation='long')
        strips_short, info_short = self.ps.split_shape(
            self._rot_rect(30.0, 90.0), parts=2, orientation='short')
        self.assertEqual(info_long['orientation'], 'long')
        self.assertEqual(info_short['orientation'], 'short')
        for b in strips_long:
            self.assertAlmostEqual(b['length_m'], 90.0, delta=1.0)
        for b in strips_short:
            self.assertAlmostEqual(b['length_m'], 30.0, delta=1.0)


class TestSplitAcrossLayers(unittest.TestCase):
    """MCP 도구·REST 라우트가 `plot_split.split_shape()` 를 어떻게
    감싸는지 — 두 계층 모두 새 파라미터를 그대로 관통시키고, `orientation`
    을 하드코딩하지 않아 모드별 기본값이 어긋나지 않는지 확인한다.

    임시 sqlite DB 만 쓰고 라이브를 건드리지 않는다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from flask_babel import Babel

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'split_layers.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        # routes_geo_plot 는 라우트 모듈이라 forms_dashboard(위젯 목록의
        # gettext 지연문자열)까지 딸려 들어온다 — Babel 확장이 없으면 임포트
        # 시점에 KeyError('babel') 로 죽는다.
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        # routes_geo_plot 를 바로 임포트하면 routes_geo_device_split 과의
        # 순환 임포트에 걸린다(그쪽이 이 모듈의 _require_edit 을 가져오려다
        # 아직 초기화가 끝나지 않은 이 모듈을 만난다) — 실제 앱이 하는 순서
        # 그대로 routes_geo 를 먼저 임포트해 전체 체인이 정상 순서로 돌게 한다.
        import aot.aot_flask.routes_geo  # noqa: F401

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _zone(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoShape
        shape = GeoShape(
            geo_id='map-split-layers', type='zone',
            feature={'type': 'Feature', 'properties': {},
                    'geometry': _rect_at(_KIMJE_LNG, _KIMJE_LAT, 30.0, 90.0)})
        db.session.add(shape)
        db.session.commit()
        return shape

    # -- MCP 도구(aot_data_tool_service) ------------------------------------

    def test_mcp_propose_defaults_short_for_parts_alone(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        zone = self._zone()
        result = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, parts=2)
        self.assertNotIn('error', result)
        self.assertEqual(result['orientation'], 'short')

    def test_mcp_propose_defaults_long_for_strip_width_cm(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        zone = self._zone()
        result = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, strip_width_cm=400)
        self.assertNotIn('error', result)
        self.assertEqual(result['orientation'], 'long')

    def test_mcp_propose_passes_through_angle_deg_and_widths_cm(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        zone = self._zone()

        by_angle = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, parts=2, angle_deg=45.0)
        self.assertNotIn('error', by_angle)
        self.assertEqual(by_angle['orientation'], 'custom')
        self.assertAlmostEqual(by_angle['orientation_deg'], 45.0, delta=1.0)

        by_widths = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, widths_cm=[500, 1000, 300])
        self.assertNotIn('error', by_widths)
        self.assertEqual(by_widths['pieces'], 3)

    def test_mcp_propose_edge_margin_m_is_meters_not_centimeters(self):
        """edge_margin_m=2 는 2m 여백이다 — 옛 cm 계약대로 200 을 넘기면
        도형(짧은 축 30m)이 통째로 사라져 에러가 난다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        zone = self._zone()
        plain = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, parts=1)
        inset = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, parts=1, edge_margin_m=2)
        self.assertNotIn('error', inset)
        self.assertLess(inset['covered_area_m2'], plain['covered_area_m2'])

        overflowed = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, parts=1, edge_margin_m=200)
        self.assertIn('error', overflowed)

    def test_mcp_apply_creates_plots_with_widths_cm(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        zone = self._zone()
        result = AoTDataToolService.apply_plot_split(
            zone_id=zone.unique_id, subject='상추',
            started_on=date.today().isoformat(),
            widths_cm=[500, 1000, 300])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created_count'], 3)

    # -- REST 라우트(routes_geo_plot) ------------------------------------

    def test_route_layer_also_defaults_short_for_parts_alone(self):
        from aot.aot_flask import routes_geo_plot as routes
        zone = self._zone()
        args, err = routes.split_args_from({'zone_id': zone.unique_id, 'parts': 2})
        self.assertIsNone(err)
        out, fail = routes.compute_split(args)
        self.assertIsNone(fail)
        _strips, info, _shape = out
        self.assertEqual(info['orientation'], 'short')

    def test_route_layer_also_defaults_long_for_strip_width_cm(self):
        from aot.aot_flask import routes_geo_plot as routes
        zone = self._zone()
        args, err = routes.split_args_from(
            {'zone_id': zone.unique_id, 'strip_width_cm': 400})
        self.assertIsNone(err)
        out, fail = routes.compute_split(args)
        self.assertIsNone(fail)
        _strips, info, _shape = out
        self.assertEqual(info['orientation'], 'long')

    def test_route_layer_edge_margin_m_field_name(self):
        from aot.aot_flask import routes_geo_plot as routes
        zone = self._zone()
        args, err = routes.split_args_from(
            {'zone_id': zone.unique_id, 'parts': 1, 'edge_margin_m': 2})
        self.assertIsNone(err)
        out, fail = routes.compute_split(args)
        self.assertIsNone(fail)
        _strips, info, _shape = out
        self.assertAlmostEqual(info['edge_margin_m'], 2.0)

    # -- 두 계층이 어긋나지 않는지 --------------------------------------------

    def test_mcp_and_route_layer_agree_on_the_default_orientation(self):
        """같은 도형·같은 모드에 대해 MCP 와 REST 가 같은 기본값을 낸다 —
        어느 한쪽이 'long' 을 다시 하드코딩하면 여기서 걸린다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        from aot.aot_flask import routes_geo_plot as routes
        zone = self._zone()

        mcp_result = AoTDataToolService.propose_plot_split(
            zone_id=zone.unique_id, parts=2)
        args, err = routes.split_args_from({'zone_id': zone.unique_id, 'parts': 2})
        self.assertIsNone(err)
        out, fail = routes.compute_split(args)
        self.assertIsNone(fail)
        _strips, route_info, _shape = out

        self.assertEqual(mcp_result['orientation'], route_info['orientation'])


class TestBedSpecIsNotAColumn(unittest.TestCase):
    """두둑 배치는 컬럼이 아니라 구획 노트에 남는다.

    26.08.5 에 `bed_width_cm`/`path_width_cm` 컬럼이 있었고 p6_36 에서 걷어냈다.
    되살리면 두 가지가 다시 성립한다 — 농부가 "두둑 폭" 을 고랑 포함으로도
    제외로도 답해 같은 밭이 두 가지로 기록되고, 대화에서 나오는 결론마다
    컬럼이 늘어난다.
    """

    def test_model_has_no_bed_columns(self):
        from aot.databases.models import GeoPlot
        cols = set(GeoPlot.__table__.columns.keys())
        for banned in ('bed_width_cm', 'path_width_cm',
                       'bed_pitch_cm', 'rows_per_bed'):
            self.assertNotIn(banned, cols)

    def test_write_path_does_not_persist_a_bed_spec(self):
        from aot.aot_flask.geo import plot_io
        src = _read(plot_io.__file__.replace('.pyc', '.py'))
        for banned in ('bed_width_cm', 'path_width_cm', 'bed_pitch_cm'):
            self.assertNotIn(banned, src)

    def test_drop_migration_rescues_values_into_notes(self):
        """사람이 적은 사실을 스키마 결정 때문에 조용히 버리지 않는다."""
        mig = os.path.join(_ROOT, '..', 'alembic_db', 'alembic', 'versions',
                           'p6_36_drop_planting_bed_spec_20260814.py')
        src = _read(mig)
        self.assertIn('INSERT INTO notes', src)
        self.assertIn("'planting'", src)
        self.assertIn('drop_column', src)


class TestOverlapStaysAllowed(unittest.TestCase):
    def test_migration_has_no_uniqueness_on_geometry(self):
        """겹침 유일성 인덱스가 추가되면 간작·혼작이 DB 에서 거부된다."""
        src = _read(_MIGRATION)
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, 'attr', getattr(fn, 'id', ''))
            if name != 'create_index':
                continue
            # 인덱스 대상 컬럼 목록(3번째 인자)에 기하·작물이 끼면 안 된다.
            if len(node.args) >= 3 and isinstance(node.args[2], ast.List):
                cols = [e.value for e in node.args[2].elts
                        if isinstance(e, ast.Constant)]
                self.assertNotIn('feature', cols)
                self.assertNotIn('subject', cols)

        self.assertNotIn('UniqueConstraint(\'geo_id\'', src)

    def test_no_overlap_check_in_write_path(self):
        """저장 경로에 겹침 거부가 들어오면 정상 기능이 막힌다."""
        from aot.aot_flask.geo import plot_io
        src = _read(plot_io.__file__.replace('.pyc', '.py'))
        lowered = src.lower()
        for banned in ('overlaps(', 'is_overlapping', 'reject_overlap'):
            self.assertNotIn(banned, lowered,
                             '저장 경로에 겹침 검사가 생겼다 — VP-3 위반')

    def test_integrity_checker_does_not_flag_overlap(self):
        checker = os.path.join(_ROOT, 'scripts', 'check_geo_integrity.py')
        src = _read(checker)
        self.assertNotIn("'plot-overlap'", src)
        self.assertNotIn('plot-overlapping', src)


# ---------------------------------------------------------------------------
# 6. 소속에 끼지 않는다 — 참조와 소속은 다른 축
# ---------------------------------------------------------------------------

class TestNotAContainer(unittest.TestCase):
    def test_container_types_excludes_vegetation(self):
        """식생이 컨테이너가 되면 장치 소속이 작기마다 바뀐다."""
        from aot.aot_flask.geo import device_membership
        self.assertEqual(device_membership._CONTAINER_TYPES, ('site', 'zone'))

    def test_plot_has_no_zone_column(self):
        """소속을 물질화하면 map_overlay_id 가 겪은 오염 계열이 되살아난다."""
        from aot.databases.models import GeoPlot
        cols = set(GeoPlot.__table__.columns.keys())
        for banned in ('zone_uuid', 'zone_id', 'parent_id', 'device_id'):
            self.assertNotIn(banned, cols)

    def test_no_binding_written_for_plots(self):
        """센서는 참조일 뿐이다 — geo_binding 행을 만들면 안 된다."""
        from aot.aot_flask.geo import plot_io, plot_context
        for mod in (plot_io, plot_context):
            src = _read(mod.__file__.replace('.pyc', '.py'))
            self.assertNotIn('GeoBinding', src)
            self.assertNotIn('device_binding.bind', src)


# ---------------------------------------------------------------------------
# 7. 저장처 분리 — GeoShape 경로에 실리지 않는다
# ---------------------------------------------------------------------------

class TestStorageSeparation(unittest.TestCase):
    def test_types_to_sync_excludes_vegetation(self):
        """typesToSync 에 들어가면 전량교체 저장이 식생을 GeoShape 로 만든다."""
        src = _read(_DESIGN_JS)
        for line in src.splitlines():
            if 'typesToSync' in line and '[' in line:
                self.assertNotIn("'vegetation'", line)

    def test_valid_shape_types_excludes_vegetation(self):
        """GeoShape 어휘에 넣으면 두 저장처가 생긴다."""
        from aot.databases.geo_integrity_ddl import VALID_SHAPE_TYPES
        self.assertNotIn('vegetation', VALID_SHAPE_TYPES)
        self.assertNotIn('plot', VALID_SHAPE_TYPES)

    def test_vegetation_module_does_not_call_save_overlays(self):
        js = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                          'design', 'aot-geo-plot.js')
        # 주석은 뺀다 — 이 파일의 머리말이 "saveOverlays 를 쓰지 않는다" 라고
        # 적고 있어서, 문자열만 세면 그 설명 자체가 위반으로 잡힌다.
        code = '\n'.join(
            line for line in _read(js).splitlines()
            if not line.lstrip().startswith(('*', '//', '/*')))
        self.assertNotIn('saveOverlays', code)
        self.assertNotIn('saveDesign', code)


# ---------------------------------------------------------------------------
# 8. 테마색 — 화이트리스트에 없으면 저장이 조용히 버려진다
# ---------------------------------------------------------------------------

class TestThemeKey(unittest.TestCase):
    def test_server_whitelist_has_theme_plot(self):
        src = _read(_ROUTES_GEO)
        self.assertIn("'theme_plot'", src,
                      "theme_keys 에 없으면 색 피커가 저장되지 않는다")

    def test_defaults_has_single_plot_entry(self):
        """기본값은 DEFAULTS 한 벌뿐 — 새 폴백을 만들지 않는다."""
        src = _read(_THEME_JS)
        self.assertEqual(src.count('plot:'), 1)


# ---------------------------------------------------------------------------
# 9. 저장 경로 통합 — DB 를 실제로 쓴다
# ---------------------------------------------------------------------------
# 응답 빌더를 **실제로 부른다** — 소스를 읽는 검사만으로는 못 잡는다
# ---------------------------------------------------------------------------

class TestContentsBuildersActuallyRun(unittest.TestCase):
    """`/contents` 응답 빌더 두 개를 진짜로 호출한다.

    이 파일에는 `_build_plot_contents` 를 **소스 문자열로** 읽는 검사가 열 개쯤
    있는데, 그 전부가 통과하는 동안 이 엔드포인트는 500 이었다 — 컬럼 이름을
    옮긴 뒤 `row.crop` 이 남아 있었고, 아무도 함수를 부르지 않았기 때문에
    `AttributeError` 가 실행 시점까지 살아 있었다.

    증상은 **모달의 [환경·제어] 탭이 빈 화면**이다. 위젯이 `!data.ok` 를
    `pane.innerHTML = ''` 로 처리해서 오류도 안 보인다.

    그래서 여기서는 어떤 값이 맞는지는 따지지 않는다 — **부르면 도는가**만 본다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'contents.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _plot(self, **over):
        from aot.aot_flask.geo import plot_io
        payload = {
            'map_uuid': 'map-contents',
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(0.0, 0.0, 0.001)},
            'subject': '상추',
            'started_on': date.today().isoformat(),
        }
        payload.update(over)
        row, err = plot_io.save_plot(payload)
        self.assertIsNone(err)
        return row

    @staticmethod
    def _routes():
        """`routes_geo_plot` 을 바로 import 하면 순환 참조로 죽는다 —
        `routes_geo_device_split` 이 이 모듈에서 이름을 가져가기 때문이다.
        앱과 같은 순서(`routes_geo` 먼저)로 부르면 사슬이 풀린다."""
        import aot.aot_flask.routes_geo  # noqa: F401
        import aot.aot_flask.routes_geo_plot as rp
        return rp

    def test_open_field_contents_builds(self):
        _build_plot_contents = self._routes()._build_plot_contents
        saved = self._plot()
        out = _build_plot_contents(saved['unique_id'])
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(out['plot']['subject'], '상추')
        self.assertEqual(out['plot']['kind'], 'vegetation')

    def test_facility_contents_builds(self):
        """시설 구획은 기하가 없어 다른 분기를 탄다 — 따로 부른다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoPlot, GeoShape
        _build_facility_plot_contents = \
            self._routes()._build_facility_plot_contents

        outer = GeoShape(geo_id='map-contents', type='facility',
                         feature={'type': 'Feature', 'properties': {},
                                  'geometry': _square(0.0, 0.0, 0.002)})
        db.session.add(outer)
        db.session.commit()
        fac = GeoFacility(geo_id='map-contents', name='1동',
                          shape_uuid=outer.unique_id, bays=[])
        db.session.add(fac)
        db.session.commit()

        saved = self._plot(feature=None, facility_uuid=fac.unique_id)
        # 노지 쪽과 달리 이 빌더는 uuid 가 아니라 **행**을 받는다.
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        out = _build_facility_plot_contents(row)
        self.assertTrue(out.get('ok'), out)
        self.assertEqual(out['plot']['subject'], '상추')


# ---------------------------------------------------------------------------

class TestSaveRoundTrip(unittest.TestCase):
    """save → end → copy 흐름. 임시 DB(파일)만 쓰고 라이브를 건드리지 않는다."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'plot.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _save(self, **over):
        from aot.aot_flask.geo import plot_io
        payload = {
            'map_uuid': 'map-test',
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(0.0, 0.0, 0.001)},
            'subject': '상추',
            'started_on': date.today().isoformat(),
        }
        payload.update(over)
        return plot_io.save_plot(payload)

    def test_create_then_end_keeps_the_row(self):
        from aot.databases.models import GeoPlot
        from aot.aot_flask.geo import plot_io

        created, err = self._save()
        self.assertIsNone(err)
        uid = created['unique_id']

        ended, err = plot_io.end_plot(uid, reason='harvested')
        self.assertIsNone(err)
        self.assertIsNotNone(ended['ended_on'])

        # 종료는 삭제가 아니다 — 이력이 남아야 연작 장해를 판단할 수 있다.
        self.assertIsNotNone(
            GeoPlot.query.filter_by(unique_id=uid).first())

    def test_end_before_planted_is_rejected(self):
        from aot.aot_flask.geo import plot_io
        created, _ = self._save(started_on=date.today().isoformat())
        _, err = plot_io.end_plot(
            created['unique_id'],
            ended_on=(date.today() - timedelta(days=5)).isoformat())
        self.assertIsNotNone(err, 'VP-2 가 강제되지 않았다')

    def test_geometry_frozen_after_end(self):
        """VP-6 — 종료된 작기의 기하가 바뀌면 과거 이력이 거짓말이 된다."""
        from aot.aot_flask.geo import plot_io
        created, _ = self._save()
        plot_io.end_plot(created['unique_id'])

        _, err = plot_io.save_plot({
            'unique_id': created['unique_id'],
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(0.5, 0.5, 0.001)},
        })
        self.assertIsNotNone(err)

    def test_name_change_still_allowed_after_end(self):
        """날짜 정정·이름 변경까지 막으면 오기입을 고칠 수 없다."""
        from aot.aot_flask.geo import plot_io
        created, _ = self._save()
        plot_io.end_plot(created['unique_id'])

        updated, err = plot_io.save_plot({
            'unique_id': created['unique_id'], 'name': '고친 이름',
        })
        self.assertIsNone(err)
        self.assertEqual(updated['name'], '고친 이름')

    def test_partial_update_does_not_wipe_untouched_fields(self):
        """페이로드에 없는 키를 None 으로 덮으면 부분 저장이 값을 지운다."""
        from aot.aot_flask.geo import plot_io
        created, _ = self._save(variety='청치마', name='두둑1')

        updated, err = plot_io.save_plot({
            'unique_id': created['unique_id'], 'subject': '배추',
        })
        self.assertIsNone(err)
        self.assertEqual(updated['subject'], '배추')
        self.assertEqual(updated['variety'], '청치마')
        self.assertEqual(updated['name'], '두둑1')

    def test_copy_carries_geometry_and_marks_source(self):
        from aot.aot_flask.geo import plot_io
        created, _ = self._save()
        copied, err = plot_io.copy_plot(created['unique_id'])

        self.assertIsNone(err)
        self.assertEqual(copied['source_kind'], 'copied')
        self.assertEqual(copied['source_ref'], created['unique_id'])
        self.assertEqual(json.dumps(copied['feature']['geometry'], sort_keys=True),
                         json.dumps(created['feature']['geometry'], sort_keys=True))
        self.assertNotEqual(copied['unique_id'], created['unique_id'])

    def test_overlapping_plots_both_save(self):
        """VP-3 — 간작·혼작. 겹친다고 거부하면 실제 농사를 담지 못한다."""
        a, err_a = self._save(subject='토마토')
        b, err_b = self._save(subject='바질',
                              feature={'type': 'Feature', 'properties': {},
                                       'geometry': _square(0.0005, 0.0, 0.001)})
        self.assertIsNone(err_a)
        self.assertIsNone(err_b)
        self.assertNotEqual(a['unique_id'], b['unique_id'])


# ---------------------------------------------------------------------------
# 10. sensors_for_plot — Output(액추에이터)이 섞이면 안 된다
# ---------------------------------------------------------------------------

class TestSensorsExcludeOutputs(unittest.TestCase):
    """구획 sensors 필드(in_plot/from_zone)에 Output이 섞이지 않는다.

    2026-08-13 실측: virtual_on_off_single 밸브(Output) 마커가 폴리곤 안에
    있으면 in_plot/from_zone 에 그대로 나가 AI가 밸브를 센서로 읽으려 시도했다
    (get_sensor_reading 이 "no directly connected sensors" 로 실패).
    device_ids_in_geometry/device_ids_in_shape 은 Input·Output 구분 없이
    장치 참조 전부를 돌려주는 범용 계약이므로(device_membership 모듈
    docstring), 걸러야 할 지점은 그 이름이 'sensors' 인 여기다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'sensors.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _marker(self, geo_id, device_id, lng, lat):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoShape
        shape = GeoShape(geo_id=geo_id, device_id=device_id, type='aot_device',
                         feature={'type': 'Feature', 'properties': {},
                                 'geometry': {'type': 'Point',
                                             'coordinates': [lng, lat]}})
        db.session.add(shape)
        db.session.commit()
        return shape

    def test_output_marker_in_plot_is_not_reported_as_sensor(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, Input, Output
        from aot.aot_flask.geo import plot_context

        sensor = Input(name='온도계')
        valve = Output(name='v331')
        db.session.add_all([sensor, valve])
        db.session.commit()

        self._marker('map-sensors', sensor.unique_id, 0.0004, 0.0004)
        self._marker('map-sensors', valve.unique_id, 0.0006, 0.0006)

        plot = GeoPlot(
            geo_id='map-sensors', subject='상추', started_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                    'geometry': _square(0.0, 0.0, 0.001)})
        db.session.add(plot)
        db.session.commit()

        sensors = plot_context.sensors_for_plot(plot)

        self.assertIn(sensor.unique_id, sensors['in_plot'])
        self.assertNotIn(valve.unique_id, sensors['in_plot'])
        self.assertNotIn(valve.unique_id, sensors['from_zone'])


# ---------------------------------------------------------------------------
# 11. 작물명으로 구역을 찾는다 — 관리인은 '3-1' 이 아니라 '콩밭' 이라 부른다
# ---------------------------------------------------------------------------

class TestSubjectNameTargetResolution(unittest.TestCase):
    """`_resolve_note_target` 의 작물명 폴백.

    2026-08-13 실측: `resolve_target('콩밭')` 이 needs_disambiguation 을 내고
    후보로 zone 이름('1포장','3-1',...)만 늘어놓았다 — 지도 이름을 모르는
    사람에게는 답이 없는 되물음이다.

    이 폴백은 **쓰기 도구**(add_schedule·create_note)의 타깃 해석에도 그대로
    쓰인다. 그래서 여기서 고정하는 것 중 진짜 위험한 것은 "찾는다"가 아니라
    **"애매하면 안 찾는다"** 쪽이다: 같은 작물이 두 구획에 있을 때 하나를
    골라버리면 엉뚱한 밭에 조용히 기록이 남는다.

    **2026-08-18 계약 변경**: 예전에는 작물명이 그 작물이 든 **구역**으로
    풀렸다(구획은 쓰기 대상이 아니었으므로). 노트의 선택 구간이 구획에 붙은
    예정이 되면서 그 전제가 깨졌다 — 구역으로 접으면 사용자가 '장풍' 을
    물었을 때 리졸버는 '3-1' 이라 답하고, 정작 장풍에 달린 예정 2건은 어떤
    이름으로도 닿지 못한다(실측: 0건). 이제 **구획**으로 푼다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        from flask_babel import Babel

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'subjecttarget.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        # aot_data_tool_service → config_translations 의 모듈 레벨 lazy_gettext.
        # Babel 미등록 상태에서 처음 문자열화되면 KeyError('babel') 이 난다.
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        # 김제 지도를 본뜬 최소 구성: zone 둘, 그 안에 콩과 상추.
        from aot.databases.models import GeoMap, GeoShape, GeoPlot
        db.session.add(GeoMap(name='김제', unique_id='map-subject'))

        def _zone(name, x0):
            db.session.add(GeoShape(
                geo_id='map-subject', type='zone',
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': _square(x0, 0.0, 0.001)}))

        _zone('3-1', 0.0)      # 콩
        _zone('3-2', 0.01)     # 상추
        _zone('3-3', 0.02)     # 콩 (같은 작물 두 번째 구역 — 모호성 테스트용)
        db.session.commit()

        def _plot(subject, x0, **over):
            row = GeoPlot(
                geo_id='map-subject', subject=subject, started_on=date.today(),
                feature={'type': 'Feature', 'properties': {},
                         'geometry': _square(x0 + 0.0002, 0.0002, 0.0004)})
            for k, v in over.items():
                setattr(row, k, v)
            db.session.add(row)
            return row

        _plot('콩', 0.0)
        _plot('상추', 0.01, variety='청치마')
        cls._second_bean = _plot('콩', 0.02)
        db.session.commit()
        # 두 번째 콩은 개별 테스트에서만 살린다(기본은 콩 = 3-1 하나).
        cls._second_bean.ended_on = date.today() - timedelta(days=1)
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _resolve(self, name):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._resolve_note_target(name)

    def test_subject_with_place_suffix_resolves_to_its_plot(self):
        """'콩밭' → 콩이 심긴 **구획**. 구역이 아니다(클래스 docstring 참조)."""
        target_id, target_type, name, _, _ = self._resolve('콩밭')
        self.assertEqual(name, '콩')
        self.assertEqual(target_type, 'plot')
        self.assertTrue(target_id)

    def test_spaced_suffix_also_resolves(self):
        """'상추 재배지' — 붙여 쓰든 띄어 쓰든 같은 답이어야 한다."""
        self.assertEqual(self._resolve('상추 재배지')[2], '상추')
        self.assertEqual(self._resolve('상추재배지')[2], '상추')

    def test_bare_subject_name_resolves(self):
        self.assertEqual(self._resolve('콩')[2], '콩')

    def test_variety_name_resolves(self):
        """품종으로 부르는 사람도 있다 — '청치마'는 상추 구획의 품종."""
        self.assertEqual(self._resolve('청치마')[1], 'plot')
        self.assertEqual(self._resolve('청치마')[2], '상추')

    def test_zone_name_still_wins_over_subject(self):
        """폴백은 **최후**다. 지도 이름이 맞으면 그것이 답이어야 한다."""
        self.assertEqual(self._resolve('3-2')[2], '3-2')

    def test_unknown_word_still_fails(self):
        """폴백이 아무거나 주워 담으면 엉뚱한 곳에 쓰기가 일어난다."""
        self.assertIsNone(self._resolve('없는이름12345')[0])

    def test_ended_plot_does_not_resolve(self):
        """작년 작물이 올해 노트를 끌고 가면 안 된다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot

        row = GeoPlot(
            geo_id='map-subject', subject='배추', started_on=date.today() - timedelta(days=200),
            ended_on=date.today() - timedelta(days=10),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.0003, 0.0003, 0.0003)})
        db.session.add(row)
        db.session.commit()
        try:
            self.assertIsNone(self._resolve('배추밭')[0])
        finally:
            db.session.delete(row)
            db.session.commit()

    def test_same_subject_in_two_zones_refuses_to_guess(self):
        """모호하면 매치하지 않는다 — 이 리졸버는 쓰기 도구가 함께 쓴다.

        구획 단위로 풀게 된 뒤에도 그대로다: 같은 작물의 구획이 둘이면 어느
        쪽인지 알 방법이 없고, 하나를 골라 버리면 엉뚱한 밭에 조용히 쓰인다.
        """
        from aot.aot_flask.extensions import db

        self._second_bean.ended_on = None       # 3-3 의 콩을 되살린다
        db.session.commit()
        try:
            self.assertIsNone(self._resolve('콩밭')[0])
        finally:
            self._second_bean.ended_on = date.today() - timedelta(days=1)
            db.session.commit()

    def test_plot_outside_every_zone_is_still_a_target(self):
        """zone 밖 구획도 대상이다 — **계약이 뒤집혔다.**

        예전에는 버렸다(구획에는 쓸 수 없으니 담을 GeoShape 가 있어야 했다).
        지금은 구획 자신이 노트·예정을 갖는다. 버리면 사용자가 방금 만든 것에
        리졸버가 도달하지 못한다.
        """
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot

        row = GeoPlot(
            geo_id='map-subject', subject='들깨', started_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.5, 0.5, 0.0003)})
        db.session.add(row)
        db.session.commit()
        try:
            tid, ttype, name, _, _ = self._resolve('들깨밭')
            self.assertTrue(tid)
            self.assertEqual(ttype, 'plot')
            self.assertEqual(name, '들깨')
        finally:
            db.session.delete(row)
            db.session.commit()

    def test_failure_response_points_at_subject_names(self):
        """되물음이 zone 이름만 늘어놓으면 사용자는 여전히 답할 수 없다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        r = AoTDataToolService.resolve_target_tool('없는이름12345')
        self.assertEqual(r['status'], 'needs_disambiguation')
        subjects = {c['subject'] for c in r['subject_targets']}
        self.assertIn('콩', subjects)
        self.assertIn('상추', subjects)


class TestSubstringFallbackIsNotGreedy(unittest.TestCase):
    """3단계(부분문자열)가 짧은 이름을 아무 문장에나 붙이지 않는다.

    2026-08-13 로컬 실측: 이름이 '2' 인 zone 이 있는 지도에서
    `resolve_target('비닐하우스 2동 옆 창고')` 가 그 zone 을 `status: success` 로
    확정하고 "정확히 한 엔티티로 해석됐다" 는 note 까지 달았다. 호출부에는
    의심할 근거가 하나도 없고, 이 리졸버는 `add_schedule`·`create_note` 가
    함께 쓴다 — 조용히 엉뚱한 구역에 쓰기가 일어난다.

    작물명 폴백(위)보다 앞 단계라, 여기서 아무거나 잡아채면 폴백은 도달조차
    하지 못한다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'substring.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        from aot.databases.models import GeoShape
        for name, x0 in (('2', 0.0), ('1포장', 0.01), ('2포장', 0.02),
                         ('3포장', 0.03), ('육묘장', 0.04)):
            db.session.add(GeoShape(
                geo_id='map-sub', type='zone',
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': _square(x0, 0.0, 0.001)}))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _resolve(self, name):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._resolve_note_target(name)

    def test_one_char_zone_name_does_not_swallow_a_sentence(self):
        self.assertIsNone(self._resolve('비닐하우스 2동 옆 창고')[0])

    def test_one_char_query_does_not_pick_among_names(self):
        """반대 방향도 같다 — 한 글자는 지도 이름 절반 안에 들어 있다."""
        self.assertIsNone(self._resolve('장')[0])

    def test_exact_one_char_name_still_resolves(self):
        """1단계 정확일치는 그대로다 — 길이 제한은 3단계에만 건다."""
        self.assertEqual(self._resolve('2')[2], '2')

    def test_ambiguous_substring_refuses_instead_of_taking_the_first(self):
        """'포장' → 1·2·3포장. 하나를 골라버리면 고른 사실조차 말하지 않는다."""
        self.assertIsNone(self._resolve('포장')[0])

    def test_unambiguous_substring_still_resolves(self):
        """이름 하나만 걸리면 종전대로 답한다 — 과잉 차단이 아니다."""
        self.assertEqual(self._resolve('육묘')[2], '육묘장')

    def test_korean_particle_attached_to_a_name_still_resolves(self):
        """'1포장에서' — 조사가 붙어도 찾아야 한다(어절 경계로 막으면 안 되는 이유)."""
        self.assertEqual(self._resolve('1포장에서')[2], '1포장')


class TestPlaceSuffixStripping(unittest.TestCase):
    """접미사 제거는 작물 매칭이 실패한 뒤에만 도는 보조 수단이다."""

    def _strip(self, text):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._strip_place_suffix(text)

    def test_common_suffixes(self):
        self.assertEqual(self._strip('콩밭'), '콩')
        self.assertEqual(self._strip('상추 재배지'), '상추')
        self.assertEqual(self._strip('토마토하우스'), '토마토')

    def test_suffix_alone_is_not_stripped_to_nothing(self):
        """'밭' 만 들어오면 남는 게 없다 — 빈 문자열로 전체 매칭을 열면 안 된다."""
        self.assertIsNone(self._strip('밭'))
        self.assertIsNone(self._strip('재배지'))

    def test_no_suffix_returns_none(self):
        self.assertIsNone(self._strip('콩'))
        self.assertIsNone(self._strip('3-1'))


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------------------
# 10. 시설 bay 흡수 (Phase 2) — 기하는 참조가 아니라 스냅샷
# ---------------------------------------------------------------------------

class TestBayBackfill(unittest.TestCase):
    """`bays[].crop`(레거시 시설 필드) → GeoPlot 백필의 판정 규칙.

    실제 이관은 운영 데이터에서만 일어나므로(개발 DB 에는 bay 작물이 없다),
    **무엇을 옮기고 무엇을 건너뛰는지**를 여기서 고정한다. 조용히 잘못 옮기면
    지도에 안 그려지는 유령 구획이 생기거나 같은 작물이 두 벌이 된다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        from flask_babel import Babel
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'bay.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        # `aot.aot_flask.geo` 패키지를 임포트하면 `config_translations` 의
        # lazy_gettext 지연문자열까지 딸려 들어온다 — Babel 확장이 없으면 그
        # 시점에 KeyError('babel') 로 죽는다. 예전에는 다른 클래스가 먼저 그
        # 패키지를 임포트해 줘서 우연히 지나갔고, 클래스 이름이 바뀌어 실행
        # 순서가 달라지자 드러났다.
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoPlot, GeoShape
        for model in (GeoPlot, GeoShape, GeoFacility):
            model.query.delete()
        db.session.commit()

    def _facility_with_bay(self, subject, with_geometry=True, bay_id='bay_1'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoShape

        # 시설 외곽 도형 — GeoFacility.shape_uuid 는 필수다.
        outer = GeoShape(geo_id='map-bay', type='facility',
                         feature={'type': 'Feature', 'properties': {},
                                  'geometry': _square(0.0, 0.0, 0.002)})
        db.session.add(outer)
        db.session.flush()

        shape_uuid = None
        if with_geometry:
            shape = GeoShape(geo_id='map-bay', type='facility_bay',
                             parent_id=outer.id,
                             feature={'type': 'Feature', 'properties': {},
                                      'geometry': _square(0.0, 0.0, 0.0005)})
            db.session.add(shape)
            db.session.flush()
            shape_uuid = shape.unique_id

        fac = GeoFacility(name='온실1', geo_id='map-bay',
                          shape_uuid=outer.unique_id, bays=[{
            'id': bay_id, 'name': '1동', 'crop': subject,
            'polygon_shape_uuid': shape_uuid,
        }])
        db.session.add(fac)
        db.session.commit()
        return fac

    def _plan(self):
        from aot.scripts.backfill_facility_bay_crops import _plan
        return _plan(None)

    def test_bay_with_crop_and_geometry_is_planned(self):
        self._facility_with_bay('토마토')
        planned, skipped = self._plan()
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]['subject'], '토마토')
        self.assertIn(':', planned[0]['source_ref'])   # <facility>:<bay>

    def test_bay_without_geometry_is_skipped_not_created(self):
        """기하 없이 만들면 지도에 안 그려지는 유령 구획이 된다."""
        self._facility_with_bay('상추', with_geometry=False)
        planned, skipped = self._plan()
        self.assertEqual(planned, [])
        self.assertEqual(skipped[0]['why'], 'no-geometry')

    def test_bay_without_crop_is_ignored(self):
        self._facility_with_bay('')
        planned, skipped = self._plan()
        self.assertEqual(planned, [])
        self.assertEqual(skipped, [])

    def test_rerun_does_not_duplicate(self):
        """재실행해도 두 벌이 되지 않는다 — source_ref 로 알아본다."""
        from aot.scripts.backfill_facility_bay_crops import _apply

        self._facility_with_bay('오이')
        planned, _ = self._plan()
        made, failed = _apply(None, planned)
        self.assertEqual(len(made), 1)
        self.assertEqual(failed, [])

        planned2, skipped2 = self._plan()
        self.assertEqual(planned2, [])
        self.assertEqual(skipped2[0]['why'], 'already-migrated')

    def test_migrated_plot_is_a_snapshot_not_a_reference(self):
        """bay 기하가 바뀌어도 옮긴 구획은 따라 움직이지 않는다.

        따라 움직이면 "작년에 여기 뭐가 있었나" 의 답이 조용히 달라진다.
        """
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoShape
        from aot.scripts.backfill_facility_bay_crops import _apply

        self._facility_with_bay('딸기')
        planned, _ = self._plan()
        _apply(None, planned)

        before = json.dumps(GeoPlot.query.first().feature['geometry'],
                            sort_keys=True)

        # bay 를 다시 나눈 것처럼 원본 도형의 기하를 바꾼다
        shape = GeoShape.query.filter_by(type='facility_bay').first()
        shape.feature = {'type': 'Feature', 'properties': {},
                         'geometry': _square(9.0, 9.0, 0.0005)}
        db.session.commit()

        after = json.dumps(GeoPlot.query.first().feature['geometry'],
                           sort_keys=True)
        self.assertEqual(before, after, '스냅샷이 아니라 참조로 붙어 있다')

    def test_source_kind_marks_origin(self):
        from aot.databases.models import GeoPlot
        from aot.scripts.backfill_facility_bay_crops import _apply

        self._facility_with_bay('가지')
        planned, _ = self._plan()
        _apply(None, planned)
        self.assertEqual(GeoPlot.query.first().source_kind, 'bay_snapshot')


# ---------------------------------------------------------------------------
# 11. 관수 밸브 교차 (Phase 3) — 계층이 아니라 교차
# ---------------------------------------------------------------------------

class TestValveIntersection(unittest.TestCase):
    """밸브와 식생은 소속 관계가 아니다.

    밸브 하나가 두 작물을 적시고, 한 작물이 두 밸브에 걸친다. 그래서 "이
    구획의 밸브" 를 하나로 정하지 않고 **겹치는 면적**을 낸다. 여기서 관수량을
    계산하지 않는 것도 같은 이유다 — 겹친 곳에서 물은 공유되므로 작물별
    요구량을 합산하면 물리적으로 틀린 숫자가 된다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'valve.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoShape
        GeoPlot.query.delete()
        GeoShape.query.delete()
        db.session.commit()

    def _plot(self, x0=0.0, size=0.001):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot
        row = GeoPlot(geo_id='m-valve', subject='상추',
                          started_on=date.today(),
                          feature={'type': 'Feature', 'properties': {},
                                   'geometry': _square(x0, 0.0, size)})
        db.session.add(row)
        db.session.commit()
        return row

    def _valve_area(self, x0, size=0.001, name='밸브구역'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoShape
        shape = GeoShape(geo_id='m-valve', type='device',
                         feature={'type': 'Feature',
                                  'properties': {'name': name},
                                  'geometry': _square(x0, 0.0, size)})
        db.session.add(shape)
        db.session.commit()
        return shape

    def _valves(self, row):
        from aot.aot_flask.geo import plot_context
        return plot_context.valves_for_plot(row)

    def test_no_overlap_no_valve(self):
        row = self._plot()
        self._valve_area(5.0)                 # 멀리 떨어진 구역
        self.assertEqual(self._valves(row), [])

    def test_coverage_is_relative_to_the_plot_not_the_valve(self):
        """사람이 알고 싶은 것은 "내 두둑이 얼마나 젖는가" 다."""
        row = self._plot(size=0.001)
        self._valve_area(0.0005, size=0.001)   # 절반 겹침
        v = self._valves(row)
        self.assertEqual(len(v), 1)
        self.assertAlmostEqual(v[0]['coverage_pct'], 50.0, delta=2.0)

    def test_two_valves_on_one_plot(self):
        """한 작물이 두 밸브에 걸치는 것은 정상이다."""
        row = self._plot(size=0.001)
        self._valve_area(-0.0004, name='A')
        self._valve_area(0.0006, name='B')
        v = self._valves(row)
        self.assertEqual(len(v), 2)
        # 많이 덮는 것이 먼저 온다
        self.assertGreaterEqual(v[0]['overlap_m2'], v[1]['overlap_m2'])

    def test_unassigned_valve_area_is_reported_not_hidden(self):
        """밸브가 안 정해진 구역에 걸친 것도 알아야 한다 — 물 줄 수단이 없다."""
        row = self._plot()
        self._valve_area(0.0)
        v = self._valves(row)
        self.assertEqual(len(v), 1)
        self.assertTrue(v[0]['unassigned'])
        self.assertIsNone(v[0]['device_id'])

    def test_no_water_amount_is_computed(self):
        """관수량을 내지 않는다 — 겹친 곳에서 물은 공유된다."""
        row = self._plot()
        self._valve_area(0.0)
        for key in ('water_l', 'liters', 'demand', 'amount'):
            self.assertNotIn(key, self._valves(row)[0])


class _FakeCalRow(object):
    """달력 계산(elapsed_days 등)은 행에서 날짜만 읽는다 — DB 를 켤 이유가 없다.

    기존 `_FakeRow`(geometry 전용)를 고치지 않고 따로 둔다 — 그쪽 시그니처를
    바꾸면 이미 그것을 쓰는 치수 테스트들이 함께 흔들린다.
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)


class TestElapsedDays(unittest.TestCase):
    """재배 일수 — 심은 날이 1일차, 끝난 작기는 종료일에서 멈춘다.

    +1 을 한 곳에서만 한다. 화면마다 0일차/1일차가 갈리면 같은 두둑이 창마다
    하루씩 다른 나이를 갖는다.
    """

    def _row(self, planted, ended=None, expected=None):
        return _FakeCalRow(started_on=planted, ended_on=ended,
                           expected_end_on=expected)

    def test_plot_day_is_day_one(self):
        from aot.aot_flask.geo import plot_context
        today = date.today()
        self.assertEqual(plot_context.elapsed_days(self._row(today)), 1)

    def test_counts_forward(self):
        from aot.aot_flask.geo import plot_context
        row = self._row(date.today() - timedelta(days=3))
        self.assertEqual(plot_context.elapsed_days(row), 4)

    def test_ended_plot_stops_at_its_end_date(self):
        """작년에 끝난 작기가 오늘까지 나이를 먹으면 이력이 거짓말이 된다."""
        from aot.aot_flask.geo import plot_context
        row = self._row(date(2025, 4, 1), ended=date(2025, 6, 30))
        self.assertEqual(plot_context.elapsed_days(row), 91)
        # 며칠 뒤에 물어도 같은 답이어야 한다
        self.assertEqual(
            plot_context.elapsed_days(row, on=date(2026, 1, 1)), 91)

    def test_no_started_on_is_none_not_zero(self):
        from aot.aot_flask.geo import plot_context
        self.assertIsNone(plot_context.elapsed_days(self._row(None)))


class TestDaysToExpectedEnd(unittest.TestCase):
    """예상 종료까지 — 지난 것을 숨기지 않는다(음수로 낸다)."""

    def _row(self, expected, ended=None):
        return _FakeCalRow(started_on=date.today() - timedelta(days=10),
                           ended_on=ended, expected_end_on=expected)

    def test_future_is_positive(self):
        from aot.aot_flask.geo import plot_context
        row = self._row(date.today() + timedelta(days=44))
        self.assertEqual(plot_context.days_to_expected_end(row), 44)

    def test_past_is_negative_not_hidden(self):
        """늦어지고 있다는 것 자체가 사용자가 봐야 할 사실이다."""
        from aot.aot_flask.geo import plot_context
        row = self._row(date.today() - timedelta(days=12))
        self.assertEqual(plot_context.days_to_expected_end(row), -12)

    def test_ended_plot_has_no_countdown(self):
        from aot.aot_flask.geo import plot_context
        row = self._row(date.today() + timedelta(days=5), ended=date.today())
        self.assertIsNone(plot_context.days_to_expected_end(row))

    def test_unset_is_none(self):
        from aot.aot_flask.geo import plot_context
        self.assertIsNone(plot_context.days_to_expected_end(self._row(None)))


class TestDimsAreDetailOnly(unittest.TestCase):
    """치수는 상세 조회에만 싣는다 — 목록에서 행마다 돌릴 이유가 없다.

    DB 를 타지 않지만 구획마다 최소회전 외접사각형을 구하는 기하 계산이다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'dims.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _row(self):
        # to_dict 는 소속 zone 을 공간 포함으로 파생하므로(저장하지 않는다)
        # DB 가 필요하다 — 그 자체가 이 설계의 핵심이라 대역으로 가리지 않는다.
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot
        GeoPlot.query.delete()
        row = GeoPlot(geo_id='m-dims', subject='상추',
                          started_on=date.today(),
                          feature={'type': 'Feature', 'properties': {},
                                   'geometry': _square(0.0, 0.0, 0.0005)})
        db.session.add(row)
        db.session.commit()
        return row

    def test_list_payload_has_no_dims(self):
        from aot.aot_flask.geo import plot_context
        d = plot_context.to_dict(self._row(), with_sensors=False,
                                     with_valves=False)
        self.assertNotIn('dims', d)

    def test_days_are_always_present(self):
        """달력만 보는 값이라 목록에도 싣는다 — 구역 요약이 이걸 쓴다."""
        from aot.aot_flask.geo import plot_context
        d = plot_context.to_dict(self._row(), with_sensors=False,
                                     with_valves=False)
        self.assertEqual(d['days_since_planted'], 1)
        self.assertIn('days_to_expected_end', d)

    def test_dims_can_be_asked_for_explicitly(self):
        from aot.aot_flask.geo import plot_context
        d = plot_context.to_dict(self._row(), with_sensors=False,
                                     with_valves=False, with_dims=True)
        self.assertIsNotNone(d['dims'])
        self.assertIn('width_m', d['dims'])

    def test_ai_brief_does_not_carry_two_names_for_dimensions(self):
        """`_plot_brief` 는 `dimensions` 키로 직접 싣는다 —
        `to_dict` 가 `dims` 로 한 번 더 실으면 LLM 컨텍스트에 같은 것을
        가리키는 이름이 둘이 된다."""
        src = _read(os.path.join(_ROOT, 'ai', 'services',
                                 'aot_data_tool_service.py'))
        head = src.split('def _plot_brief', 1)[1][:900]
        self.assertIn('with_dims=False', head)


class TestAlsoCovers(unittest.TestCase):
    """"켜면 무엇이 함께 젖는가" — valves_for_plot 의 역방향.

    밸브를 켜는 사람이 알아야 하는 것은 "이 구획이 얼마나 젖는가" 가 아니라
    무엇이 **함께** 젖는가다. 겹침이 정상인 도메인이라 한 밸브가 여러 작물을
    적시는 것이 예외가 아니라 기본이다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'cover.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot
        GeoPlot.query.delete()
        db.session.commit()

    def _plot(self, x0, subject, size=0.001, ended=None):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot
        row = GeoPlot(geo_id='m-cov', subject=subject,
                          started_on=date.today() - timedelta(days=1),
                          ended_on=ended,
                          feature={'type': 'Feature', 'properties': {},
                                   'geometry': _square(x0, 0.0, size)})
        db.session.add(row)
        db.session.commit()
        return row

    def _covered(self, geom, exclude=None):
        from aot.aot_flask.geo import plot_context
        return plot_context.plots_covered_by_shape(
            geom, 'm-cov', exclude_uuid=exclude)

    def test_lists_every_plot_the_valve_touches(self):
        a = self._plot(0.0, '상추')
        self._plot(0.0005, '대파')          # 겹침
        got = self._covered(_square(0.0, 0.0, 0.001), exclude=a.unique_id)
        self.assertEqual([p['subject'] for p in got], ['대파'])

    def test_excludes_itself(self):
        """자기 자신이 "함께 젖는 것" 으로 나오면 안 된다."""
        a = self._plot(0.0, '상추')
        got = self._covered(_square(0.0, 0.0, 0.001), exclude=a.unique_id)
        self.assertEqual(got, [])

    def test_touching_edges_do_not_count(self):
        """경계를 맞대고 있을 뿐인 옆 두둑은 함께 젖지 않는다."""
        self._plot(0.001, '대파', size=0.001)      # 딱 붙어 있다
        got = self._covered(_square(0.0, 0.0, 0.001))
        self.assertEqual(got, [])

    def test_ended_plots_are_not_watered(self):
        """끝난 작기는 이제 그 자리에 없다."""
        self._plot(0.0005, '대파', ended=date.today() - timedelta(days=1))
        got = self._covered(_square(0.0, 0.0, 0.001))
        self.assertEqual(got, [])

    def test_sorted_by_how_much_gets_wet(self):
        self._plot(0.0009, '조금')          # 살짝 겹침
        self._plot(0.0001, '많이')          # 많이 겹침
        got = self._covered(_square(0.0, 0.0, 0.001))
        self.assertEqual([p['subject'] for p in got], ['많이', '조금'])

    def test_no_water_amount(self):
        """역방향에서도 관수량을 계산하지 않는다."""
        self._plot(0.0005, '대파')
        got = self._covered(_square(0.0, 0.0, 0.001))
        for key in ('water_l', 'liters', 'demand'):
            self.assertNotIn(key, got[0])


class TestAreaContentsIsShared(unittest.TestCase):
    """구역과 식생이 인벤토리를 **같은 본체**로 센다.

    두 벌로 복사하면 같은 장치를 두 화면이 다르게 세게 되고, 이 도메인은
    이미 그 실패로 크게 데었다("같은 구역의 센서 수가 화면마다 달랐다").
    """

    def test_zone_builder_delegates(self):
        src = _read(_ROUTES_GEO)
        body = src.split('def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_build_area_contents(', body)
        # 구역이 자기 벌로 다시 세면 안 된다
        self.assertNotIn('Output.query.filter(', body)
        self.assertNotIn('DeviceMeasurements.query.filter_by(', body)

    def test_plot_builder_delegates(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))
        body = src.split('def _build_plot_contents', 1)[1]
        self.assertIn('_build_area_contents(', body)
        self.assertNotIn('Output.query.filter(', body)

    def test_scope_is_opt_in_so_zone_payload_is_unchanged(self):
        """구역은 빌려오는 것이 없다 — `scope` 키가 붙으면 안 된다."""
        src = _read(_ROUTES_GEO)
        body = src.split('def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn('scope_of', body)

    def test_plot_is_not_a_container(self):
        """구획은 컨테이너가 아니다 — 인벤토리를 만든다고 소속으로 만들지 말 것."""
        src = _read(_MEMBERSHIP)
        head = src.split('_CONTAINER_TYPES', 1)[1][:400]
        self.assertNotIn('plot', head)
        self.assertNotIn('vegetation', head)


class TestPlotCacheInvalidation(unittest.TestCase):
    """저장·종료·삭제가 모달 캐시를 버린다.

    쓰기는 REST 만 지나가는 것이 아니라 AI/MCP 도구도 `plot_io` 로 온다.
    라우트에 흩으면 새 진입점이 조용히 빠지고, 증상은 "저장은 됐는데 화면이
    30초 동안 안 바뀐다" 라 버그로 읽히지도 않는다.
    """

    def _io_src(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_io.py'))

    def test_every_commit_path_invalidates(self):
        src = self._io_src()
        for fn in ('def save_plot', 'def end_plot', 'def delete_plot'):
            body = src.split(fn, 1)[1].split('\ndef ', 1)[0]
            self.assertIn('_invalidate_caches()', body,
                          '%s 가 캐시를 안 버린다' % fn)

    def test_invalidation_clears_all_not_just_one(self):
        """새 구획이 생기면 같은 밸브를 쓰는 이웃의 also_covers 도 달라진다."""
        src = self._io_src()
        body = src.split('def _invalidate_caches', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('invalidate_plot_contents(None)', body)

    def test_plot_cache_is_separate_from_zone_cache(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))
        self.assertIn('_PLANTING_CONTENTS_CACHE', src)
        self.assertIn('def cached_plot_contents', src)


class TestCoverageWarningIsSymmetric(unittest.TestCase):
    """"켜면 무엇이 함께 젖는가" 는 **구역·식생 양쪽**에 있어야 한다.

    식생 창에만 경고를 두면 "구역에서 켜면 안전하다"는 잘못된 대비가 생긴다.
    구역에서 켠 밸브도 그 안의 여러 작물에 물을 준다.
    """

    def test_zone_contents_attaches_also_covers(self):
        src = _read(_ROUTES_GEO)
        body = src.split('def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('plots_by_valve_device', body)
        self.assertIn("also_covers", body)

    def test_plot_contents_attaches_also_covers(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))
        body = src.split('def _build_plot_contents', 1)[1]
        self.assertIn('plots_by_valve_device', body)
        self.assertIn('also_covers', body)

    def test_both_use_the_same_counter(self):
        """따로 세면 같은 밸브가 두 화면에서 다른 작물 목록을 갖는다."""
        zone = _read(_ROUTES_GEO).split(
            'def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        plant = _read(os.path.join(
            _ROOT, 'aot_flask', 'routes_geo_plot.py')).split(
            'def _build_plot_contents', 1)[1]
        for body in (zone, plant):
            self.assertIn('covered_subject_names(', body)

    def test_only_the_plot_view_excludes_itself(self):
        """구역에서는 그 구역의 모든 작물이 나와야 한다 — 뺄 '자기' 가 없다."""
        zone = _read(_ROUTES_GEO).split(
            'def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        plant = _read(os.path.join(
            _ROOT, 'aot_flask', 'routes_geo_plot.py')).split(
            'def _build_plot_contents', 1)[1]
        self.assertNotIn('exclude_uuid', zone)
        self.assertIn('exclude_uuid', plant)

    def test_names_not_uuids(self):
        """화면에 uuid 를 내보내지 않는다 — 사람이 읽을 이름만."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo',
                                 'plot_context.py'))
        body = src.split('def covered_subject_names', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn("'unique_id'", body.split('exclude_uuid')[-1])


class TestPlotControlReusesZoneMachinery(unittest.TestCase):
    """식생 [환경·제어]는 구역의 기계를 **빌려 쓴다**.

    폴링·토글·예약·이력 오버레이를 따로 구현하면 같은 장치가 두 화면에서
    다르게 움직인다. 모달은 한 번에 하나만 열리므로 상태 슬롯도 공유한다.
    """

    def _vector(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map',
                                  'aot-map-widget-vector.js'))

    def test_plot_does_not_get_its_own_polling(self):
        src = self._vector()
        body = src.split('function _attachPlotControl', 1)[1].split(
            '\n        function ', 1)[0]
        self.assertIn('_startZoneOutputPolling(uid)', body)
        self.assertIn('_renderZoneDevices(', body)
        self.assertIn('_wireZoneTabs(', body)

    def test_plot_never_writes_zone_scoped_settings(self):
        """구획 창에서 구역 설정(rep_key·output_order)을 쓰면 **그 구역을 보는
        다른 사람의 설정**이 바뀐다. zoneUuid 를 비워 그 경로를 없앤다."""
        src = self._vector()
        body = src.split('function _attachPlotControl', 1)[1].split(
            '\n        // ── ', 1)[0]
        self.assertIn('zoneUuid: null', body)
        # 주석은 그 두 이름을 **설명하려고** 언급한다 — 코드만 본다.
        code = '\n'.join(l for l in body.split('\n')
                         if not l.lstrip().startswith('//'))
        self.assertNotIn("/output_order", code)
        self.assertNotIn("/rep_key", code)

    def test_drag_reorder_is_zone_only(self):
        src = self._vector()
        body = src.split('function _renderZoneDevices', 1)[1].split(
            '\n        function ', 1)[0]
        self.assertIn('isPlot', body)
        self.assertIn('canCtrl && !isPlot && window.AoTActuatorOrder', body)

    def test_hook_is_late_bound(self):
        """제어 함수는 식생 로더보다 **늦게** 정의된다 — 직접 참조하면
        ReferenceError 가 나고 try/catch 가 삼켜 식생 레이어가 통째로 안 뜬다."""
        src = self._vector()
        self.assertIn('_plotControlHooks', src)
        self.assertIn('_plotControlHooks[uniqueId] = _attachPlotControl',
                      src)
        # 로더 쪽은 등록소를 거쳐야 한다(이름 직접 참조 금지)
        loader = src.split('AoTMapPlot.load(', 1)[1][:900]
        self.assertNotIn('attachControl: _attachPlotControl', loader)


class TestScopeBadgeAndCoverageMarkup(unittest.TestCase):
    """배지·경고의 표시 규칙 — 색을 고정하지 않고, 숨기지 않는다."""

    def _popup(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-popup.js'))

    def _css(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css',
                                  'widget', 'aot-sensor-label.css'))

    def test_only_nearest_gets_a_badge(self):
        """배지는 `nearest` 하나뿐이다.

        'plot' 은 기본이라 말할 것이 없고, 'irrigation' 은 **마커가 구획 밖에
        있다**는 뜻일 뿐인데 화면에서는 기능 분류처럼 읽혔다 — 같은 밸브가
        구획에 따라 [관수] 였다 아니었다 했다. 왜 여기 있고 얼마나 중요한지는
        덮는 비율이 이미 말한다. 거리는 비율이 대신 말해 주지 못한다.
        """
        body = self._popup().split('function scopeBadgeHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("scope === 'nearest'", body)
        self.assertNotIn("scope === 'irrigation'", body)
        self.assertIn("return '';", body)

    def test_irrigation_badge_style_is_gone_too(self):
        self.assertNotIn('aot-scope-irrigation', self._css())

    def test_zone_scope_is_gone(self):
        """'구역에 있다' 는 이유만으로 싣던 것은 폐지됐다 — 이 구획에 닿지도
        않는 장치까지 나와 식생 패널이 구역 패널의 복사본이 됐다."""
        body = self._popup().split('function scopeBadgeHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertNotIn("scope === 'zone'", body)

    def test_badge_color_is_inherited_not_fixed(self):
        """고정색을 주면 어느 바탕과 반드시 부딪친다 — 실제로 비활성 탭
        배경과 같은 값이라 글자가 통째로 사라졌다."""
        css = self._css()
        block = css.split('.aot-act-tag.aot-scope-nearest', 1)[1][:700]
        self.assertIn('color: inherit', block)
        self.assertIn('border: 1px solid currentColor', block)

    def test_no_plot_screen_msgid_carries_a_literal_percent(self):
        """구획 화면이 쓰는 **모든** msgid 에 리터럴 `%` 가 없어야 한다.

        세 번 겪었다(`%(pct)s%` · `{pct}%` · `{n}% of days`). babel 은 `%` 를
        python-format 지시자로 읽어 **그 언어 카탈로그 전체의 컴파일을 거부**한다
        — 한 문구가 아니라 그 언어가 통째로 영어로 나온다. 치환을 JS 가 직접
        하더라도 마찬가지다.

        문구 하나씩 막으면 다음 문구에서 또 겪는다. 그래서 규칙으로 막는다:
        `%` 는 값 쪽에 붙이고 msgid 에는 자리표시자만 둔다.
        """
        import re
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        design = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                    'design', 'aot-geo-plot.js'))
        used = set()
        for src in (popup, design):
            used |= set(re.findall(r"_t\('((?:[^'\\]|\\.)+)'\)", src))

        # `%(name)s` 는 이 저장소가 쓰는 정식 gettext 자리표시자다 — 그것만
        # 걷어낸 뒤에도 `%` 가 남으면 리터럴이다.
        bad = []
        for mid in used:
            if '%' not in mid:
                continue
            if re.sub(r'%\([A-Za-z_]+\)[sd]', '', mid).find('%') != -1:
                bad.append(mid)
        self.assertEqual(bad, [],
                         'msgid 에 리터럴 %% 가 있다(그 언어 전체가 영어로 나온다): %s'
                         % bad)

    def test_percent_is_not_in_the_catalog_string(self):
        """번역 문구에 리터럴 `%` 를 넣지 않는다.

        치환은 JS 가 직접 하므로 `%` 는 포맷 지시자가 아닌데, **babel 은 그렇게
        읽지 않는다** — `%(pct)s%` 든 `{pct}%` 든 "placeholders are incompatible"
        로 `pybabel compile` 을 통째로 거부한다. 카탈로그가 컴파일되지 않으면 그
        언어 전체가 영어로 나온다(그 한 문구만이 아니다).

        그래서 `%` 는 값 쪽에 붙인다 — msgid 에는 자리표시자만 남는다.
        """
        body = self._popup().split('function coverageHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('{pct} of this plot', body)
        self.assertNotIn('%% of this plot', body)
        self.assertNotIn('%(pct)s', body)
        self.assertNotIn('{pct}%', body)

    def test_coverage_goes_in_its_own_slot(self):
        """meta 에 이어붙이면 `.aot-act-meta-text` 안쪽이라 flex 자식이 아니고,
        줄바꿈이 안 먹어 시간 숫자에 달라붙는다."""
        popup = self._popup()
        row = popup.split('function buildOutputRow', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('opts.note', row)
        vector = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                    'widgets', 'AoT_map',
                                    'aot-map-widget-vector.js'))
        self.assertIn('note: coverHtml', vector)

    def test_coverage_is_not_hidden_behind_a_tooltip(self):
        """물은 되돌릴 수 없다 — 접거나 툴팁으로 숨기지 않는다."""
        css = self._css()
        block = css.split('.aot-act-coverage {', 1)[1][:400]
        self.assertNotIn('display: none', block)
        self.assertIn('white-space: normal', block)


class TestZoneShowsWhatIsPlanted(unittest.TestCase):
    """구역 [현황]이 "지금 심겨 있는 것" 을 싣는다.

    농장 지도인데 계층 어디에도 작물이 없었다 — 구역 모달은 센서·장치·기능만
    알고 무엇이 자라는지는 몰랐다.
    """

    def test_zone_contents_carries_allocation(self):
        src = _read(_ROUTES_GEO)
        body = src.split('def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('zone_allocation(', body)
        self.assertIn("'allocation'", body)

    def test_allocation_reports_days(self):
        """"무엇이 며칠째" 를 한 줄로 말하려면 재배 일수가 배분에 있어야 한다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo',
                                 'plot_context.py'))
        body = src.split('def zone_allocation', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('days_since_planted', body)
        # 값의 출처는 `_days_shown`(= `elapsed_days` + 시작 전 방어)이다.
        # 이름을 고정하는 이유는 "달력에서 파생된 값" 이어야 하기 때문이고,
        # 그 성질은 감싼 쪽도 그대로 갖는다.
        self.assertIn('_days_shown(row', body)

    def test_unassigned_uses_union_not_sum(self):
        """단순 합으로 빼면 겹친 만큼 이중으로 빠져 미배정이 음수가 된다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo',
                                 'plot_context.py'))
        body = src.split('def zone_allocation', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('unary_union', body)

    def test_no_total_row_in_the_ui(self):
        """비율의 합이 100%를 넘는 것이 정상이라(간작·혼작) 합계를 내지 않는다 —
        띄우면 사용자가 그것을 오류로 읽는다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = src.split('function buildZonePlotsHtml', 1)[1].split(
            '\n  function ', 1)[0]
        for word in ("_t('Total')", "'Sum'", 'reduce('):
            self.assertNotIn(word, body)

    def test_rows_link_down_to_the_plot(self):
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertIn('aot-ov-plot-link', popup)
        vector = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                    'widgets', 'AoT_map',
                                    'aot-map-widget-vector.js'))
        body = vector.split('function _renderZoneOverview', 1)[1].split(
            '\n        function ', 1)[0]
        # 내려가기 전에 구역 모달을 닫는다 — 모달을 쌓지 않는다
        self.assertIn('_closeZoneModal(uid)', body)
        self.assertIn('AoTMapPlot.openModal', body)


class TestSiteCropCount(unittest.TestCase):
    """필지는 작물을 **숫자로만** 낸다.

    구역 행은 이미 `이름 | 값 | 상태` 3열이라 작물명을 이어붙이면 한 열이 두
    가지를 말하게 되고 열 간격이 틀어진다.
    """

    def test_counts_include_subjects(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))
        self.assertIn('_plot_counts', src)
        body = src.split('def _plot_counts', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("'subjects'", body)
        self.assertIn("'plots'", body)

    def test_child_rows_do_not_carry_subject_names(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))
        body = src.split('def _child_entry', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn('subject', body)

    def test_failure_does_not_break_the_site_modal(self):
        """식생이 없는 지도가 정상이다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))
        body = src.split('def _plot_counts', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('except Exception', body)
        self.assertIn("{'subjects': 0, 'plots': 0}", body)


class TestPlotCacheAlsoDropsZone(unittest.TestCase):
    """구획을 고치면 **구역 응답도** 달라진다.

    구역 [현황]이 작물 목록·면적 배분을 싣고 출력마다 `also_covers` 를 단다.
    구획의 소속은 저장돼 있지 않고 기하에서 파생되므로, 기하를 옮기면 "전" 과
    "후" 두 구역이 함께 낡는다 — 어느 쪽인지 따지지 않고 전부 버린다.
    """

    def test_invalidates_zone_cache_too(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_io.py'))
        body = src.split('def _invalidate_caches', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('invalidate_zone_contents_all()', body)

    def test_helper_exists(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))
        self.assertIn('def invalidate_zone_contents_all', src)


class TestPlotGoesUpToItsZone(unittest.TestCase):
    """식생 → 구역 → 필지로 거슬러 올라갈 수 있어야 한다.

    계층이 한 방향으로만 흐르면 위젯 안에서 길을 잃는다.
    """

    def test_header_has_the_up_button(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = src.split('function buildPlotModal', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('up: true', body)

    def test_up_target_comes_from_the_response_not_a_constant(self):
        """상위는 **응답이 정한다** — 종류까지.

        예전에는 `kind: 'zone'` 으로 고정했다. 그런데 `zone_uuid` 는 이름과 달리
        zone 이 아닐 수 있다 — `container_for_geometry` 의 계약이 "감싸는
        site/zone" 이라, zone 이 없는 자리에서는 **site 도형**이 온다(시설
        구획이 특히 그렇다: 구역이 없으므로 필지가 잡힌다).

        그것을 zone 으로 믿고 구역 화면을 열면 조회가 빈 손으로 끝나고 화면이
        **스켈레톤에 멈춘다** — 에러가 없어서 "뒤로가기가 고장" 으로만 보인다
        (실측: 필지 "육묘장" 안의 시설 "육묘장" — 이름까지 같아 오래 안 보였다).
        """
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map',
                                 'aot-map-widget-vector.js'))
        body = src.split('function _attachPlotControl', 1)[1].split(
            '\n        // ── ', 1)[0]
        # 시설 구획의 상위는 **시설**이다.
        self.assertIn("kind: 'facility'", body)
        self.assertIn('facility_uuid', body)
        # 노지 구획은 서버가 준 종류로 갈린다 — 상수로 박지 않는다.
        self.assertIn('zone_kind', body)
        self.assertIn('zone_uuid', body)

    def test_server_says_what_the_container_actually_is(self):
        """화면이 판단할 근거(`zone_kind`)를 서버가 실어야 한다.

        없으면 소비처마다 도형을 다시 조회해 확인해야 하고, 대개는 확인하지
        않고 이름을 믿는다 — 그 믿음이 위 버그였다.
        """
        ctx = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_context.py'))
        self.assertIn("'zone_kind'", ctx)
        routes = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))
        self.assertIn("'zone_kind'", routes)


class TestPlotShowsOnlyWhatItTouches(unittest.TestCase):
    """식생 패널은 **이 구획에 닿는 것만** 낸다.

    합집합(구획 안 ∪ 구역 전체 ∪ 밸브)으로 내던 시절에는 이 구획에 물 한 방울
    주지 않는 밸브까지 올라와, 식생 패널이 구역 패널의 복사본이 됐다 — 그럴
    거면 구역 패널을 열면 된다. 실측(김제 새바람): 출력 4개 중 실제로 닿는
    것은 2개, 나머지 둘은 교차가 0이었다.
    """

    def _src(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))

    def _body(self):
        return self._src().split('def _build_plot_contents', 1)[1]

    def test_zone_devices_are_not_unioned_in(self):
        body = self._body()
        self.assertNotIn('plot_ids | zone_ids | valve_ids', body)
        self.assertIn('direct = plot_ids | valve_ids', body)

    def test_fallback_is_per_kind(self):
        """종류를 섞어 판정하면 "센서는 있는데 밸브가 없는" 구획에서 센서까지
        폴백이 걸린다."""
        body = self._body()
        self.assertIn("for kind in ('inputs', 'outputs', 'functions')", body)
        self.assertIn('have = kinds_direct[kind]', body)
        self.assertIn('if have or not kinds_zone[kind]', body)

    def test_fallback_takes_only_the_closest(self):
        body = self._body()
        self.assertIn('nearest_devices(', body)
        self.assertIn('limit=1', body)

    def test_distance_is_reported(self):
        """왜 여기 있는지, 얼마나 믿을 값인지 판단할 근거."""
        self.assertIn("item['distance_m'] = nearest", self._body())

    def test_devices_without_markers_are_skipped(self):
        """위치를 모르면 "가장 가깝다" 고 말할 근거가 없다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo',
                                 'plot_context.py'))
        body = src.split('def nearest_devices', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('load_markers', body)
        self.assertIn('representative_point', body)

    def test_single_sensor_still_says_where_it_came_from(self):
        """센서가 하나면 탭이 없어 배지가 걸릴 자리가 없다 — 그 하나가 구획
        밖에서 온 값이면 그 사실이 사라지는 것이 가장 위험하다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map',
                                 'aot-map-widget-vector.js'))
        self.assertIn('aot-zone-sensor-src', src)
        self.assertIn("sensors[0].scope !== 'plot'", src)


class TestOverviewIsAboutNotesNotDevices(unittest.TestCase):
    """식생 [현황]의 중심은 **노트**다.

    현 상황(관찰·작업·사진)을 말할 수 있는 것은 노트뿐이다. 예전에는 여기에
    "이 구획 안의 센서 · 1" 같은 **개수**와 밸브 커버리지 목록이 있었다 —
    값도 없이 장치 이야기만 하면서 정작 봐야 할 노트를 아래로 밀어냈고,
    그 내용은 [환경·제어]가 값·배지·영향 범위까지 제대로 낸다.
    """

    def _body(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        return src.split('function _plotOverviewHtml', 1)[1].split(
            '\n  function ', 1)[0]

    def test_no_device_listing(self):
        body = self._body()
        for gone in ('_plotSensorsHtml', '_plotValvesHtml'):
            self.assertNotIn(gone, body)

    def test_those_helpers_are_deleted_not_orphaned(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertNotIn('function _plotSensorsHtml', src)
        self.assertNotIn('function _plotValvesHtml', src)

    def test_notes_are_present(self):
        """노트는 여전히 이 탭의 본론이다 — 다만 이제 **통합 기록 블록 안**에
        있다(Phase 2). 블록이 직접 그리지 않고 공용 컴포넌트를 부르므로,
        여기서는 '기록 블록이 있는가' 로 확인하고 '그 블록이 공용 노트
        컴포넌트를 쓰는가' 는 test_geo_record_unified.py 가 본다."""
        self.assertIn('buildRecordBlock(', self._body())

    def test_missing_valve_is_still_reported(self):
        """밸브 목록이 아니라 **빠진 것**을 알리는 줄은 남는다 — "적실 수단이
        아직 없다" 는 장치 나열이 아니라 상태다."""
        self.assertIn('_plotNoValveHtml', self._body())


class TestInvolvementOrdering(unittest.TestCase):
    """관여도가 높은 장치가 위로.

    DB 순서 그대로 두면 이 구획의 75.9% 를 적시는 밸브가 24.1% 짜리 아래로
    내려간다(실측). 급한 상황에서 사람은 맨 위를 누른다.
    """

    def _key(self):
        import importlib
        mod = importlib.import_module('aot.aot_flask.routes_geo_plot')
        return mod._involvement_key

    def test_higher_coverage_comes_first(self):
        key = self._key()
        rows = [{'name': 'low', 'scope': 'irrigation', 'coverage_pct': 24.1},
                {'name': 'high', 'scope': 'plot', 'coverage_pct': 75.9}]
        rows.sort(key=key)
        self.assertEqual([r['name'] for r in rows], ['high', 'low'])

    def test_plot_device_without_coverage_counts_as_full(self):
        """비율은 밸브에만 있는 개념이다 — 구획 안의 팬·조명에는 잴 것이 없다."""
        key = self._key()
        rows = [{'name': 'valve', 'scope': 'irrigation', 'coverage_pct': 90.0},
                {'name': 'fan', 'scope': 'plot'}]
        rows.sort(key=key)
        self.assertEqual([r['name'] for r in rows], ['fan', 'valve'])

    def test_nearest_always_last(self):
        key = self._key()
        rows = [{'name': 'far', 'scope': 'nearest', 'distance_m': 5.0},
                {'name': 'weak', 'scope': 'irrigation', 'coverage_pct': 0.1}]
        rows.sort(key=key)
        self.assertEqual([r['name'] for r in rows], ['weak', 'far'])

    def test_same_scope_is_ordered_by_coverage(self):
        """스코프가 같으면 비율만이 순서를 정한다.

        이 경우가 실제 버그를 드러냈다 — plot/irrigation 이 섞인 구획은
        스코프만으로도 우연히 맞아서 한동안 안 보였다.
        """
        key = self._key()
        rows = [{'name': 'v312', 'scope': 'irrigation', 'coverage_pct': 39.8},
                {'name': 'v321', 'scope': 'irrigation', 'coverage_pct': 60.2}]
        rows.sort(key=key)
        self.assertEqual([r['name'] for r in rows], ['v321', 'v312'])

    def test_coverage_is_attached_before_sorting(self):
        """**호출 순서**가 틀리면 키가 맞아도 결과가 틀린다.

        정렬이 `coverage_pct` 부착보다 앞서면 정렬 시점에 비율이 없어 전부
        0으로 읽히고 조용히 이름순으로 떨어진다. 실제로 그렇게 나갔다
        (블랙틴: 39.8% 가 60.2% 보다 위). 키만 단위테스트하면 못 잡는다.
        """
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))
        body = src.split('def _build_plot_contents', 1)[1]
        attach = body.index("out['coverage_pct'] = pct")
        sort_at = body.index('inv[group].sort(key=_involvement_key)')
        self.assertLess(attach, sort_at,
                        'coverage_pct 부착이 관여도 정렬보다 뒤에 있다')

    def test_zone_modal_keeps_its_drag_order(self):
        """사람이 드래그로 정한 순서는 명시적 의사표시라 계산이 이겨선 안 된다."""
        src = _read(_ROUTES_GEO)
        body = src.split('def _build_zone_contents', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn('_involvement_key', body)


class TestFallbackWhenSensorGivesNoData(unittest.TestCase):
    """구획 안에 센서가 **있어도 값을 못 주면** 인접 센서를 함께 낸다.

    빈 차트만 보여주면 사용자는 "이 구획은 볼 값이 없다" 로 읽는다 — 바로
    옆에 멀쩡한 센서가 있는데도.
    """

    def _src(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))

    def test_liveness_not_just_existence(self):
        body = self._src().split('def _build_plot_contents', 1)[1]
        self.assertIn('_env_of(', body)
        self.assertIn("valid', 0) == 0", body)
        self.assertIn("reason = 'stale'", body)

    def test_dead_sensor_is_kept_not_hidden(self):
        """빼면 고장이 화면에서 사라져 아무도 고치지 않는다."""
        body = self._src().split('def _build_plot_contents', 1)[1]
        self.assertIn("item['no_data'] = True", body)

    def test_live_sensor_is_ordered_first(self):
        """첫 탭이 자동으로 그려진다 — 죽은 센서가 앞이면 열자마자 빈 차트다."""
        import importlib
        mod = importlib.import_module('aot.aot_flask.routes_geo_plot')
        rows = [{'name': 'dead', 'scope': 'plot', 'no_data': True},
                {'name': 'live', 'scope': 'nearest', 'distance_m': 36.6}]
        rows.sort(key=mod._sensor_order_key)
        self.assertEqual([r['name'] for r in rows], ['live', 'dead'])

    def test_liveness_uses_the_shared_counter(self):
        """필지·구역이 "센서 응답 2/3" 을 셀 때 쓰는 것과 같은 함수여야 한다."""
        body = self._src().split('def _env_of', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('env_for_devices', body)

    def test_query_failure_is_not_read_as_dead(self):
        """인플럭스가 잠깐 흔들릴 때마다 옆 구획 센서로 갈아타면 안 된다."""
        body = self._src().split('def _env_of', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("'valid': 1", body.split('except Exception')[1])

    def test_env_is_measured_once_not_twice(self):
        """판정용과 인벤토리용으로 같은 influx 왕복을 두 번 하지 않는다
        (실측 약 64ms). 집합이 안 바뀌었으면 잰 것을 그대로 넘긴다."""
        body = self._src().split('def _build_plot_contents', 1)[1]
        self.assertIn('env=(None if added_input else plot_env)', body)
        src = _read(_ROUTES_GEO)
        head = src.split('def _build_area_contents', 1)[1][:200]
        self.assertIn('env=None', head)


class TestNoDataStatusTakesItsOwnSpace(unittest.TestCase):
    """차트 없이 문구만 남을 때 absolute 를 푼다.

    absolute 는 로딩 중 차트 **위에** 얹히기 위한 것이다. 그릴 차트가 없으면
    부모 높이가 0이 되어 문구가 아래 장치 목록 위로 겹쳐 앉는다(실측 118px).
    """

    def _js(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'common', 'sensor-label.js'))

    def test_empty_chart_box_is_removed(self):
        body = self._js().split('function renderHistory', 1)[1]
        seg = body.split('if (!series.length)', 1)[1][:400]
        self.assertIn('chartEl.remove()', seg)
        self.assertIn('_standaloneStatus(', seg)

    def test_both_empty_paths_use_the_same_helper(self):
        body = self._js().split('function renderHistory', 1)[1]
        self.assertEqual(body.count('_standaloneStatus('), 2)

    def test_css_releases_absolute(self):
        css = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css',
                                 'widget', 'aot-sensor-label.css'))
        block = css.split('.aot-sensor-popup-chart-status.is-standalone', 1)[1][:300]
        self.assertIn('position: static', block)
        self.assertIn('min-height', block)


class TestHistoryRequestsAreBatched(unittest.TestCase):
    """센서 이력을 채널마다 낱개로 치지 않는다.

    온습도 노드 하나가 6채널이면 차트 한 개에 요청 6건이고, 브라우저의 오리진당
    ~6 연결 상한에 그대로 걸린다 — 폰에서는 그만큼 라디오를 깨운다.
    `/data_batch` 가 이미 `kind:'past'` 를 받고 응답 모양도 같다.
    """

    def _js(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'common', 'sensor-label.js'))

    def test_uses_the_batch_endpoint(self):
        body = self._js().split('function _fetchPastSeries', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("'/data_batch'", body)
        self.assertIn("kind: 'past'", body)

    def test_falls_back_to_single_requests(self):
        """배치가 실패해도 차트가 비면 안 된다 —
        `aot-data-batch.js` 의 directFallback 과 같은 태도."""
        body = self._js().split('function _fetchPastSeries', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('_fetchPastOneByOne(chunk, past)', body)
        self.assertEqual(body.count('_fetchPastOneByOne'), 3)  # 길이불일치·throw·단건

    def test_length_mismatch_is_not_trusted(self):
        """정렬이 깨진 배치 결과를 그리면 온도 자리에 습도가 들어간다."""
        body = self._js().split('function _fetchPastSeries', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('res.length !== chunk.length', body)

    def test_chunk_cap_matches_server_workers(self):
        """서버가 past 를 동시에 처리하므로(_run_past_jobs, 워커 8) 한 요청이
        곧 한 번의 동시 실행 파도다 — 상한을 워커 수에 맞춘다."""
        self.assertIn('_PAST_BATCH_MAX = 8', self._js())
        rg = _read(os.path.join(_ROOT, 'aot_flask', 'routes_general.py'))
        self.assertIn('_BATCH_MAX_WORKERS = 8', rg)

    def test_server_runs_past_items_concurrently(self):
        """ORM·request 는 요청 스레드에서 다 풀고, 스레드에는 문자열·숫자만
        들어간다 — 그래야 influx 조회를 동시에 돌릴 수 있다."""
        rg = _read(os.path.join(_ROOT, 'aot_flask', 'routes_general.py'))
        self.assertIn('def _run_past_jobs', rg)
        self.assertIn('def _resolve_past_job', rg)
        body = rg.split('def _run_past_jobs', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('ThreadPoolExecutor', body)
        self.assertIn('_series_points', body)

    def test_series_points_takes_no_orm_object(self):
        """만료된 ORM 속성을 스레드에서 건드리면 그 스레드가 DB 를 친다."""
        rg = _read(os.path.join(_ROOT, 'aot_flask', 'routes_general.py'))
        head = rg.split('def _series_points', 1)[1][:400]
        self.assertIn('db_name', head)
        self.assertNotIn('settings', head)

    def test_count_window_asymmetry_is_preserved(self):
        """무제한 조회는 COUNT 에 범위를 주지 않는다 — 리팩터 중 여기에 범위를
        넣어 /async/…/0/0 이 662점에서 204(빈 응답)로 깨졌다."""
        rg = _read(os.path.join(_ROOT, 'aot_flask', 'routes_general.py'))
        body = rg.split('def _series_points', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('count_start_str', body)
        self.assertIn('count_end_str', body)

    def test_single_channel_skips_the_batch(self):
        """1건이면 POST 로 감쌀 이유가 없다."""
        body = self._js().split('function _fetchPastSeries', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('jobs.length === 1', body)


class TestScheduleScoping(unittest.TestCase):
    """일정의 대상은 장치 id 만이 아니다.

    `SchedulerJobMeta.target_id` 는 site·zone 도형 uuid 도 담는다 — 실제
    데이터에 "제초작업 - 투입인원 4명…" 같은 농작업 이벤트가 필지/구역을
    대상으로 들어 있다. 예전에는 장치 id 만 봐서 **그 계층 자신에게 걸린
    일정이 그 계층 모달에서 영영 안 보였다**(실측: 1포장에 자기 uuid 를
    대상으로 한 활성 이벤트가 있는데 집계는 0이었다).
    """

    def _src(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))

    def test_targets_include_the_shape_itself(self):
        from aot.aot_flask.geo import site_summary as ss

        class _Shape(object):
            unique_id = 'shape-1'

        got = ss.schedule_targets(_Shape(), {'dev-a', 'dev-b'})
        self.assertIn('shape-1', got)
        self.assertIn('dev-a', got)

    def test_targets_include_children_for_the_rollup(self):
        """필지 요약은 이미 하위 구역의 장치·상태를 합산한다 — 일정만 자기
        것으로 좁히면 같은 화면 안에서 기준이 갈린다."""
        from aot.aot_flask.geo import site_summary as ss

        class _Shape(object):
            unique_id = 'site-1'

        got = ss.schedule_targets(_Shape(), set(), ['zone-1', 'zone-2'])
        self.assertEqual(got, {'site-1', 'zone-1', 'zone-2'})

    def test_count_uses_the_shared_target_set(self):
        body = self._src().split('def _schedule_count', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn('schedule_targets(', body)
        # 장치 id 만 보던 옛 형태로 되돌아가면 안 된다
        self.assertNotIn('target_id.in_(list(device_ids))', body)

    def test_live_states_are_declared_once(self):
        """세는 곳과 나열하는 곳이 다른 집합을 쓰면 "3건 예정" 인데 목록에는
        2건만 나온다."""
        src = self._src()
        self.assertIn('SCHEDULE_LIVE_STATES', src)
        self.assertEqual(src.count("('DRAFT', 'PENDING', 'RUNNING')"), 1)

    def test_upcoming_keeps_the_two_target_buckets(self):
        """서버는 대상(도형/장치)으로 나눠 담는다 — 화면이 필요하면 쓰라고.

        ⚠ **화면에서는 이 둘을 카테고리로 보여주지 않는다.** 한때 '농작업' /
        '장치 예약' 이라 이름 붙였는데 둘 다 틀렸다: 시스템에 그런 구분이
        없고(전부 같은 SchedulerJobMeta), 그 이름은 용도를 농업으로 못 박는다
        — 이 소프트웨어는 공원·시설물·교통에도 쓴다고 이미 정해 두었다.
        """
        body = self._src().split('def upcoming_schedule', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn("'own'", body)
        self.assertIn("'devices'", body)
        self.assertIn('shape_targets', body)

    def test_upcoming_reuses_the_ai_serializer(self):
        """앵커 tz 로 벽시계를 맞추는 규칙이 거기 하나뿐이다 — 다시 만들면
        같은 일정이 화면과 AI 답변에서 다른 시각으로 나온다."""
        body = self._src().split('def upcoming_schedule', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn('_schedule_summary(row)', body)

    def test_zone_contents_carries_schedule(self):
        body = _read(_ROUTES_GEO).split('def _build_zone_contents', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn('upcoming_schedule(', body)
        self.assertIn("'schedule': schedule", body)

    def test_empty_schedule_says_so_instead_of_vanishing(self):
        """**계약이 바뀌었다.** 예전에는 예정이 없으면 블록을 아예 안 그렸다
        (빈 블록은 노이즈였다). 지금은 예정과 노트가 한 블록이라 그럴 수 없다 —
        노트는 거의 항상 있고, 예정만 없다고 블록을 지우면 노트가 함께 사라진다.
        대신 "예정 없음" 한 줄을 낸다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = js.split('function buildRecordBlock', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("_t('Nothing scheduled yet.')", body)

    def test_no_invented_categories_in_the_ui(self):
        """화면은 하나의 목록이다 — 시스템에 없는 구분을 만들지 않는다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        for gone in ("_t('Field work')", "_t('Device schedule')"):
            self.assertNotIn(gone, js)

        # 소제목(aot-ov-sub-title) 자체는 금지 대상이 아니다 — 금지해야 할
        # 것은 **시스템에 없는 구분**이다. 통합 기록 블록의 '예정'/'지난 것'
        # 은 실재하는 구분(시각이 앞이냐 뒤냐)이라 소제목이 맞다.
        for line in js.splitlines():
            if 'aot-ov-sub-title' not in line or '.aot-ov-sub-title' in line:
                continue
            self.assertTrue(
                ("_t('Coming up')" in line or "_t('Up to now')" in line
                 or 'opts.sub' in line or 'title' in line),
                '설명 없는 소제목: %s' % line.strip())

    def test_no_agriculture_only_wording_in_generic_surfaces(self):
        """이 소프트웨어는 용도를 농업으로 한정하지 않는다(landing 문구).
        일정은 어느 현장에나 있는 것이라 그 이름에 '농' 을 넣지 않는다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = js.split('function buildRecordBlock', 1)[1].split(
            '\n  function _fmtWhen', 1)[0]
        for word in ('Field work', 'farm', 'Farm', 'irrigation', 'waters'):
            self.assertNotIn(word, body)


class TestPlotSchedule(unittest.TestCase):
    """구획에도 다가오는 일정을 낸다 — **닿는 것만**."""

    def _src(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))

    def test_detail_endpoint_carries_it_not_contents(self):
        """**[현황] 탭은 상세 조회로 그려진다.**

        `/contents` 는 [환경·제어] 전용이라, 거기 넣으면 API 에는 값이 있는데
        화면에는 안 뜬다 — 실제로 그렇게 만들어 놓고 이 테스트의 옛 버전이
        "contents 에 필드가 있는가" 만 보느라 통과시켰다. 사용자가 화면을
        확인해 달라고 해서야 드러났다.
        """
        src = self._src()
        self.assertIn("out['schedule'] = _plot_schedule(row)", src)
        contents = src.split('def _build_plot_contents', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertNotIn("'schedule'", contents)

    def test_scope_is_direct_not_the_whole_zone(self):
        """구역 장치까지 넣으면 없앤 "구역 패널의 복사본" 이 일정 쪽으로
        되살아난다."""
        body = self._src().split('def _plot_schedule', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn('upcoming_schedule(row, plot | valves)', body)
        self.assertNotIn('device_ids_in_shape', body)

    def test_plot_itself_is_a_target(self):
        """구획을 대상으로 하는 일정 경로가 생겼을 때 화면만 조용히 못
        따라가는 일이 없게, 대상 집합에 구획 자신을 넣어 둔다."""
        body = self._src().split('def _plot_schedule', 1)[1].split(
            '\ndef ', 1)[0]
        # upcoming_schedule 의 첫 인자가 구획 행이면 그 uuid 가 own 대상이 된다
        self.assertIn('upcoming_schedule(row,', body)

    def test_creation_is_one_shared_endpoint(self):
        """구획 전용 생성 경로를 두지 않는다 — 대지·구역·시설도 같은 것을
        쓴다. 계층마다 만들면 tz 앵커·중복 승인 같은 함정을 각자 다시 밟는다."""
        self.assertNotIn('api_plot_add_schedule', self._src())
        rg = _read(_ROUTES_GEO)
        self.assertIn("@blueprint.route('/api/geo/schedule', methods=['POST'])", rg)
        self.assertIn('def _schedule_payload', rg)

    def test_overview_renders_it_with_the_shared_builder(self):
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = js.split('function _plotOverviewHtml', 1)[1].split(
            '\n  function ', 1)[0]
        # Phase 2: 예정과 노트가 한 블록이라 빌더도 하나다. 순서(노트가
        # 마지막)는 이제 블록 **안**의 문제라 buildRecordBlock 이 지킨다.
        self.assertIn('buildRecordBlock(p.schedule,', body)
        self.assertNotIn('_ovNotesBlock()', body)


class TestPlotTimezone(unittest.TestCase):
    """구획의 현지 시각은 **소속 구역**을 따른다.

    `resolve_location_tz` 가 GeoPlot 을 모르면 시스템 tz 로 조용히 떨어져,
    여러 지역에 걸친 지도에서 구획에 걸린 일정이 남의 지역 시각으로 표시된다.
    """

    def _src(self):
        return _read(os.path.join(_ROOT, 'utils', 'device_tz.py'))

    def test_plot_branch_exists(self):
        src = self._src()
        body = src.split('def resolve_location_tz', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('GeoPlot', body)
        self.assertIn('zone_for_plot', body)

    def test_it_resolves_through_the_container_not_its_own_column(self):
        """구획에는 tz 컬럼이 없다 — 소속 도형의 resolve_timezone 을 쓴다
        (설계 §8: 운영 그룹은 한 시계를 공유한다)."""
        body = self._src().split('def resolve_location_tz', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn('container.resolve_timezone()', body)

    def test_lookup_failure_falls_through(self):
        """구획 조회가 실패해도 장치 조회·시스템 폴백이 계속 이어져야 한다."""
        body = self._src().split('def resolve_location_tz', 1)[1].split(
            '\ndef ', 1)[0]
        seg = body.split('GeoPlot', 1)[1]
        self.assertIn('except Exception', seg)
        self.assertIn('return get_device_tz(None)', body)


class TestNoWateringLanguage(unittest.TestCase):
    """"적신다" 고 쓰지 않는다 — 그 장치가 관수 장치라는 근거가 없다.

    판정은 *장치 영역 도형이 구획과 겹친다* 하나뿐이다. 실측(김제): 영역에
    묶인 출력이 전부 `virtual_on_off_single`(범용 on/off)이고, 'v341' 같은
    이름은 그 농장의 작명일 뿐 시스템이 읽는 값이 아니다. 관수인지 조명인지
    모르는 채 "물" 을 말하면 다른 장치를 쓰는 농장에서 화면이 거짓말이 된다.
    """

    def _popup(self):
        return _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-popup.js'))

    def test_ui_string_is_neutral(self):
        body = self._popup().split('function coverageHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("_t('Also covers')", body)
        self.assertNotIn('Also waters', body)

    def test_missing_device_notice_is_neutral(self):
        src = self._popup()
        self.assertIn('A device area over this plot has no device assigned yet.',
                      src)
        self.assertNotIn('An irrigation area over this plot', src)

    def test_server_helper_warns_about_its_own_name(self):
        """이름(`valves_*`)이 가정을 담고 있어 다음 사람이 되살리기 쉽다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo',
                                 'plot_context.py'))
        body = src.split('def valves_for_plot', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('관수 장치를 가려내지 않는다', body)
        self.assertIn('virtual_on_off_single', body)


class TestScheduleIsConsistentAcrossLayers(unittest.TestCase):
    """대지·구역·식생·시설이 **같은 창·같은 블록**으로 일정을 보여준다.

    예전에는 대지만 "오늘 N건" 숫자, 구역·식생은 목록(지금부터), 시설은 아예
    없었다. 창이 달라서 **대지가 0인데 구역을 열면 내일 일이 있는** 상태가
    실제로 났다(실측: 3포장 '오늘 0' / 3-2 구역 8/19 08:00). 위 계층이 아래를
    덮지 못하면 롤업이라고 부를 수 없다.
    """

    def test_site_summary_carries_the_same_list(self):
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'site_summary.py'))
        self.assertIn("'schedule': upcoming_schedule(", src)

    def test_site_tile_no_longer_duplicates_it(self):
        """숫자 타일('오늘')과 목록('지금부터')이 나란히 있으면 두 값이
        어긋나는 것이 정상처럼 보인다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = js.split('function _buildSiteSummaryHTML', 1)[1].split(
            '\n        function ', 1)[0]
        self.assertNotIn("_siteTileHTML('schedule'", body)
        self.assertIn('buildRecordBlock(', body)

    def test_no_layer_has_its_own_add_form(self):
        """**계약이 뒤집혔다.** 예정을 만드는 자리는 노트 하나다 — 본문의 한
        구간을 골라 시각을 준다. 계층마다 폼을 두면 사용자가 쓰기 **전에**
        종류를 고르는 옛 방식으로 되돌아간다(2026-08-18, 네 계층 통합).
        계약은 test_note_schedule_link.py 가 지킨다."""
        for f in ('aot-map-widget-vector.js', 'aot-map-plot.js',
                  'aot-map-popup.js'):
            js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                    'widgets', 'AoT_map', f))
            for gone in ('wireScheduleAdd', 'wireRecordAdd', '_scheduleFormHtml'):
                self.assertNotIn(gone, js, '%s 에 %s 가 남아 있다' % (f, gone))

    def test_facility_identity_is_covered(self):
        """시설은 정체성이 둘이다 — 일정은 GeoFacility uuid 로 붙는데 장치·기하는
        GeoShape 쪽이다. 도형만 보면 방금 만든 일정이 안 보인다."""
        rg = _read(_ROUTES_GEO)
        body = rg.split('def _schedule_payload', 1)[1].split('\ndef ', 1)[0]
        # 시설 uuid 는 자손 목록과 **함께** 들어간다 — 자손 확장이 붙은 뒤에도
        # 이 uuid 를 빠뜨리면 방금 만든 일정이 그 시설 화면에서 안 보인다.
        self.assertIn('list(kids) + [fac.unique_id]', body)

    def test_every_layer_uses_the_same_record_block(self):
        """네 계층이 **같은 빌더**를 쓴다 — 계층마다 다른 모양이면 사용자는
        화면을 옮길 때마다 어디에 무엇이 있는지 다시 찾아야 한다.

        순서(예정 먼저, 노트 뒤)는 이제 블록 **안**의 문제라 빌더가 지킨다."""
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        # zone
        zone = popup.split('function buildZoneStatusHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('buildRecordBlock(', zone)
        # site · facility
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        for fn in ('_buildSiteSummaryHTML', '_appendFacilitySchedule'):
            body = js.split('function %s' % fn, 1)[1].split(
                '\n        function ', 1)[0]
            self.assertIn('buildRecordBlock(', body, '%s 가 공용 빌더를 안 쓴다' % fn)
        # 블록 안의 순서
        rec = popup.split('function buildRecordBlock', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertLess(rec.index("_t('Coming up')"),
                        rec.index('window.AoTNotesBlock.html('))


class TestVocabularyIsNotAgricultureOnly(unittest.TestCase):
    """AoT 는 용도를 농업으로 한정하지 않는다.

    소개 문구가 이미 그렇게 정해져 있다(landing: "특정 용도나 장소에 매이지
    않습니다 — 온실·축사·노지는 물론 공원·시설물·교통처럼…"). 그런데 화면
    문구는 이 농장 사례 하나를 보고 '재배'·'파종'·'농작업' 처럼 농업에서만
    통하는 말을 쓰고 있었다. 공원·도로 현장에서는 그 말이 그냥 틀린 말이 된다.

    **판정은 한국어 번역으로 한다** — 영어 msgid 가 중립이어도 번역이 농업으로
    좁히면 화면은 좁아진다(실제로 'Planted on' 이 '파종일' 이었다).
    """

    _BANNED = ('재배', '파종', '농작업', '농장', '작물')

    def _ko(self):
        import re
        src = _read(os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                                 'LC_MESSAGES', 'messages.po'))
        out = {}
        for m in re.finditer(r'msgid "([^"]*)"\nmsgstr "([^"]*)"', src):
            out[m.group(1)] = m.group(2)
        return out

    def _modal_msgids(self):
        """모달 빌더들이 실제로 쓰는 msgid 만 본다 — 카탈로그 전체에는 다른
        화면(작물 관리 등)의 문구도 있다."""
        import re
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        return set(re.findall(r"_t\('([^']+)'\)", src))

    def test_no_agriculture_only_korean_in_modal_strings(self):
        ko = self._ko()
        bad = []
        for mid in self._modal_msgids():
            val = ko.get(mid)
            if not val:
                continue
            for w in self._BANNED:
                if w in val:
                    bad.append('%s -> %s (%s)' % (mid, val, w))
        self.assertEqual(bad, [], '농업 한정 단어가 모달 문구에 남아 있다: %s' % bad)

    def test_subject_msgid_is_gone(self):
        """'Crop' 은 영어에서도 수확물을 뜻한다 — 공원의 나무는 subject 이 아니다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        design = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                    'design', 'aot-geo-plot.js'))
        for s in (src, design):
            self.assertNotIn("_t('Crop')", s)

    def test_plot_labels_are_not_borrowed_from_another_meaning(self):
        """같은 영어 단어를 다른 뜻으로 쓰는 화면과 msgid 를 공유하면 안 된다.

        `Period` 는 이 저장소에서 **폴링 주기**("주기")다. 구획의 기간 제목에
        그대로 쓰면 번역이 "주기" 로 나온다 — 영어로는 맞아 보이고 한국어에서만
        틀리므로 리뷰에서 잘 안 보인다("Sensors"="센서류" 와 같은 계열).
        """
        import re
        design = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                    'design', 'aot-geo-plot.js'))
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        # 빌려 쓰면 안 되는 msgid 와, 그것을 쓰는 다른 화면의 뜻:
        #   Period → 폴링 주기("주기")
        #   Stage / Stages → 시설 센서 색구간의 단("단 1", "단")
        self.assertNotIn("_t('Period')", design)
        for borrowed in ("_t('Period')", "_t('Stage')", "_t('Stages')"):
            self.assertNotIn(borrowed, popup,
                             '%s 는 다른 뜻으로 이미 번역돼 있다' % borrowed)

        ko = _read(os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                                'LC_MESSAGES', 'messages.po'))
        cat = dict(re.findall(
            r'^msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', ko, re.M))
        # 구획 화면이 쓰는 라벨의 한국어가 실제로 그 뜻인지 고정한다.
        self.assertEqual(cat.get('Dates'), '기간')
        self.assertEqual(cat.get('What is here'), '대상')
        self.assertEqual(cat.get('Start date'), '시작일')
        self.assertEqual(cat.get('Current stage'), '단계')
        self.assertEqual(cat.get('Stage count'), '단계 수')

    def test_gdd_stage_needs_all_three_or_falls_back(self):
        """GDD 판정은 셋이 모두 갖춰졌을 때만 한다 — 하나라도 없으면 날짜로
        되돌아가고, **되돌아간 이유를 함께 싣는다.**

        이유 없이 되돌아가면 "왜 GDD 가 안 잡히지" 를 알 방법이 없다. 그 상태로
        단계가 조용히 뒤처지는 것이 정확히 이 설계가 막으려는 것이다.
        """
        from aot.aot_flask.geo import plot_context

        class _Plot(object):
            started_on = None
            ended_on = None

        # 프로그램이 없다
        self.assertEqual(
            plot_context.gdd_accumulated(_Plot(), None)['reason'], 'no-program')

        # 기준온도가 없다 — 지어내지 않는다
        class _NoBase(object):
            photosynthesis = None
        out = plot_context.gdd_accumulated(_Plot(), _NoBase())
        self.assertFalse(out['usable'])
        self.assertEqual(out['reason'], 'no-t-base')

        # 기준온도는 있는데 시작일이 없다
        class _Base(object):
            photosynthesis = {'T_base': 10.0}
        out = plot_context.gdd_accumulated(_Plot(), _Base())
        self.assertEqual(out['reason'], 'no-start-date')

    def test_stage_gdd_is_a_length_not_a_total(self):
        """단계의 `gdd` 는 **그 단계의 길이**다(`days` 와 같은 규약).

        누적값으로 읽으면 마지막 단계만 맞고 나머지가 다 어긋나는데, 화면에서는
        "단계가 이상하다" 로만 보인다.
        """
        from aot.aot_flask.geo.plot_context import _stage_by_gdd

        stages = [{'key': 'a', 'name': 'A', 'gdd': 100},
                  {'key': 'b', 'name': 'B', 'gdd': 100},
                  {'key': 'c', 'name': 'C', 'gdd': 100}]
        # 누적 150 → 길이 해석이면 2단계(50 소진), 누적 해석이면 2단계 경계
        out = _stage_by_gdd(stages, {'value': 150.0}, None)
        self.assertEqual(out['index'], 2)
        self.assertEqual(out['source'], 'gdd')
        self.assertEqual(out['gdd_in_stage'], 50.0)
        self.assertEqual(out['gdd_left'], 50.0)

    def test_mixed_stages_refuse_gdd_judgement(self):
        """한 단계라도 `gdd` 가 없으면 판정하지 않는다.

        0 으로 치면 그 단계가 건너뛰어지고, 날짜로 메우면 두 기준이 한 프로그램
        안에서 섞인다 — 어느 쪽도 사람이 예상할 수 없다.
        """
        from aot.aot_flask.geo.plot_context import _stage_by_gdd

        stages = [{'key': 'a', 'name': 'A', 'gdd': 100},
                  {'key': 'b', 'name': 'B'},                 # 비었다
                  {'key': 'c', 'name': 'C', 'gdd': 100}]
        self.assertIsNone(_stage_by_gdd(stages, {'value': 150.0}, None))

    def test_last_stage_may_run_to_the_end(self):
        """마지막 단계의 빈 `gdd` 는 '끝까지' 다 — `days` 와 같은 규약."""
        from aot.aot_flask.geo.plot_context import _stage_by_gdd

        stages = [{'key': 'a', 'name': 'A', 'gdd': 100},
                  {'key': 'b', 'name': 'B'}]
        out = _stage_by_gdd(stages, {'value': 500.0}, None)
        self.assertEqual(out['index'], 2)
        self.assertIsNone(out['gdd_left'])

    def test_gdd_is_not_the_coordinator_gdd(self):
        """`cumulative_tracker` 의 GDD 와 **다른 값**이다.

        그쪽은 제어 보상용으로 사이클마다 적분하고 env_coordinator 함수가 있어야
        한다. 노지 구획에는 코디네이터가 없으므로 여기에 얹을 수 없다. 그 사실을
        문서와 코드 주석에 남긴 것을 고정한다 — 나중에 "GDD 가 두 개네" 를 보고
        한쪽으로 합치려는 시도를 막기 위해서다.
        """
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_context.py'))
        body = src.split('def gdd_accumulated', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('cumulative_tracker', body)
        self.assertIn('Tmax', body)

    def test_singular_and_plural_mean_the_same_thing(self):
        """같은 것을 단수는 "함수", 복수는 "기능" 이라 부르고 있었다.

        구역 모달의 "기능 0" 은 AoT Function 의 개수인데, 메뉴에서는 같은 것을
        "함수" 라 부른다. 영어(`Function`/`Functions`)로는 자연스러운 단복수라
        리뷰에서 안 보인다 — `Period`="주기" 와 같은 계열이다.
        """
        import re
        ko = _read(os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                                'LC_MESSAGES', 'messages.po'))
        cat = dict(re.findall(
            r'^msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', ko, re.M))
        self.assertEqual(cat.get('Function'), cat.get('Functions'),
                         '단수·복수가 다른 말로 번역돼 있다')

    def test_zone_about_block_has_a_title(self):
        """제목 없는 블록은 사진 아래에 다섯 줄이 떠 있는 모양이 된다 —
        구획 모달의 "구획 정보" 와 같은 자리이므로 같은 방식으로 이름을 준다."""
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = popup.split('function buildZoneAboutHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("_t('Zone information')", body)

    def test_tabs_split_by_now_versus_fixed(self):
        """[현황]=지금 값 · [개요]=바뀌지 않는 사실.

        예전에는 대상·시작일·예상 종료일이 **두 탭에 다** 있었고, 현재 단계·
        목표·자원은 [개요] 에만 있었다 — 어느 쪽이 정본인지 알 수 없고, "지금
        어떤가" 를 보러 온 사람이 [개요] 까지 뒤져야 했다.
        """
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        over = popup.split('function _plotOverviewHtml', 1)[1].split(
            '\n  function ', 1)[0]
        about = popup.split('function _plotAboutHtml', 1)[1].split(
            '\n  function ', 1)[0]
        prog = popup.split('function _plotProgramHtml', 1)[1].split(
            '\n  function ', 1)[0]

        # 지금 값은 [현황] 에만.
        # `_plotStageTargetRows` 는 목록에서 뺐다 — [목표] 카드를 없앴다
        # (2026-08-20). [현재] 가 값 옆에 목표를 세우게 되면서 두 카드가 거의
        # 같은 말을 했고, 이쪽은 재는 센서가 없는 항목까지 늘어놓았다.
        for now in ('_plotStageProposalHtml',
                    '_plotStageResourceRows', '_plotGddRows'):
            self.assertIn(now, over, '%s 가 [현황] 에 없다' % now)
            self.assertNotIn(now, about, '%s 가 [개요] 에도 있다' % now)
            self.assertNotIn(now, prog, '%s 가 프로그램 블록에 남아 있다' % now)

        # 정체성은 [개요] 에만 — 두 탭에 같은 행을 두지 않는다.
        self.assertIn('_plotSubjectLabel(p)', about)
        self.assertNotIn('_plotSubjectLabel(p)', over)
        self.assertIn("_t('Start date')", about)
        self.assertNotIn("_t('Start date')", over)

    def test_form_labels_are_plain_text(self):
        """`_fr`·`_fRow` 는 라벨을 이스케이프한다 — HTML 을 넘기면 태그가 그대로
        화면에 찍힌다(실제로 `<span …>품목</span>` 이 보였다)."""
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        for bad in ('_fr(\'<span', '_fRow(\'<span'):
            self.assertNotIn(bad, popup)

    def test_expected_end_row_carries_one_fact(self):
        """한 열에는 한 정보만.

        예전에는 한 행이 "2026-09-07 (프로그램 기준) (19일 남음)" 이었다 —
        날짜·출처·남은 일수 셋이 한 칸에 들어가 좁은 폭에서 줄이 접히고, 눈이
        날짜를 찾기 전에 괄호부터 읽는다. 남은 일수는 아래 행으로 분리하고,
        출처는 뺀다([개요] 탭의 프로그램 블록이 이미 말한다).
        """
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        # [현황]의 진행 정보는 _plotOverviewHtml 이 부르는 두 함수에 흩어져
        # 있다(막대 + AoTViz 가 없을 때의 되돌림). 둘을 합쳐서 본다 — 한쪽만
        # 보면 막대로 옮긴 것을 "사라졌다" 로 읽는다.
        over = ''.join(
            popup.split('function ' + fn, 1)[1].split('\n  function ', 1)[0]
            for fn in ('_plotOverviewHtml', '_plotProgressHtml',
                       '_plotProgressRows'))
        about = popup.split('function _plotAboutHtml', 1)[1].split(
            '\n  function ', 1)[0]
        # 날짜는 [개요](바뀌지 않는 사실), 남은 일수는 [현황](지금 값).
        self.assertIn("_pRow(_t('Expected end'), _esc(p.expected_end_on))", about)
        self.assertIn("_t('Days left')", over)
        # [현황]이 예상 종료일 자체를 다시 말하지 않는다. 기간 막대의 눈금
        # 오른쪽 끝은 **값**(p.expected_end_on / tl.end)이지 라벨이 아니므로
        # 이 규칙과 무관하다 — 폴백 라벨로만 쓰는 것은 허용한다.
        self.assertNotIn("_pRow(_t('Expected end')", over)
        # 출처 꼬리표를 되살리지 않는다.
        self.assertNotIn('from programme', over)
        self.assertNotIn('from programme', about)

    def test_stage_targets_come_from_the_server(self):
        """항목 어휘·단위를 화면이 다시 조립하지 않는다.

        조립하면 항목을 늘릴 때 한쪽만 늘어난다. 그리고 **곡선이 걸린 항목은
        숫자를 내지 않는다** — 단계 값을 대신 보이면 실제로 쓰이지 않는 숫자를
        목표라고 말하는 것이 된다.
        """
        from aot.aot_flask.geo.plot_context import _stage_targets
        from aot.aot_flask.geo.program_io import fixed_target_defs

        class _Prog(object):
            targets_methods = None

            def target_def_list(self):
                return fixed_target_defs('vegetation')

        stage = {'key': 'seedling', 'targets': {'temp_day': 24.0, 'rh': 70.0}}
        out = _stage_targets(stage, _Prog())
        by_key = {t['key']: t for t in out}
        self.assertEqual(by_key['temp_day']['value'], 24.0)
        self.assertEqual(by_key['temp_day']['unit'], '\u00b0C')
        self.assertEqual(by_key['temp_day']['source'], 'stage')
        # 라벨도 서버가 붙인다 — 화면이 키로 표를 뒤지지 않게.
        self.assertTrue(by_key['temp_day'].get('label'))
        self.assertNotIn('co2', by_key)          # 미지정 항목은 내지 않는다

    def test_a_curve_never_shows_the_stage_number(self):
        """곡선이 이기는 항목에 단계 값을 보이면 화면이 거짓말을 한다."""
        from aot.aot_flask.geo.plot_context import _stage_targets

        from aot.aot_flask.geo.program_io import fixed_target_defs

        class _Prog(object):
            targets_methods = {'temp_day': 'method-uuid'}

            def target_def_list(self):
                return fixed_target_defs('vegetation')

        stage = {'key': 'seedling', 'targets': {'temp_day': 24.0, 'rh': 70.0}}
        out = _stage_targets(stage, _Prog())
        by_key = {t['key']: t for t in out}
        self.assertEqual(by_key['temp_day']['source'], 'method')
        self.assertIsNone(by_key['temp_day']['value'])
        self.assertEqual(by_key['rh']['value'], 70.0)   # 곡선 없는 항목은 그대로

    def test_targets_say_they_do_not_drive_control(self):
        """숫자만 보이면 사람이 '이대로 돌고 있다' 로 읽는다 — 아직 아니다.

        **문구는 카드가 아니라 목표 숫자에 딸린다.** [목표] 카드를 없앨 때
        (2026-08-20) 이 문장이 함께 사라질 뻔했다 — 그 카드에만 있었기
        때문이다. 지금은 구획 [현황]의 [현재] 바로 밑에 붙는다: 프로그램
        목표가 그 눈금으로 들어가므로 문장이 붙을 자리도 거기다.

        **시설·구역에는 붙지 않는다** — 그쪽 목표는 코디네이터가 실제로 쫓는
        값이라 같은 문장이 거짓이 된다. 그래서 공용 빌더가 아니라 구획
        빌더에 있어야 한다.
        """
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertIn('Control is not changed automatically', popup)
        over = popup.split('function _plotOverviewHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('Control is not changed automatically', over,
                      '구획 [현황] 이 아닌 곳으로 옮겨졌다 — 프로그램 목표가 '
                      '보이는 자리에 있어야 한다')
        shared = popup.split('function buildEnvNowHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertNotIn('Control is not changed automatically', shared,
                         '공용 [현재] 빌더에 붙었다 — 시설 목표는 코디네이터가 '
                         '실제로 쫓는 값이라 이 문장이 거짓이 된다')

    def test_every_plot_form_can_pick_a_kind(self):
        """구획을 만드는 세 화면이 **모두** 종류를 고를 수 있어야 한다.

        한 화면만 빠지면 그 화면으로 만든 구획은 영영 식생이다 — `kind` 는
        나중에 고칠 수 있지만, 고칠 수 있다는 것을 아무도 모른다. 서버가 받는
        축이 화면에 없는 반쪽 상태가 정확히 이 작업이 없애려던 것이다.
        """
        # 폼은 이제 **공용 컴포넌트 한 벌**이다(`common/aot-plot-form.js`).
        # 화면마다 마크업을 확인하던 예전 검사를 그대로 두면 통합을 되돌려야
        # 통과하게 된다 — 지켜야 하는 것은 "세 화면이 종류를 고를 수 있는가"
        # 이지 "각자 select 를 적어 두었는가" 가 아니다.
        form = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                                  'aot-plot-form.js'))
        design = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                    'design', 'aot-geo-plot.js'))
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        facility = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                      'facility', 'plot-ui.js'))
        # 공용 폼이 종류 칸과 네 어휘를 갖는다.
        self.assertIn("key: 'kind'", form)
        for k in ('vegetation', 'livestock', 'facility', 'other'):
            self.assertIn("'" + k + "'", form)
        # 세 화면이 그것을 쓴다 — 각자 자기 필드 속성으로.
        self.assertIn("attr: 'data-veg-field'", design)
        self.assertIn("attr: 'data-nf'", popup)
        self.assertIn("attr: 'data-f'", facility)
        # 구획 모달 편집 폼은 아직 자기 마크업을 갖는다(4단계는 등록 폼 셋).
        self.assertIn("_kindSelect('data-pf=\"kind\"'", popup)

    def test_program_list_follows_the_chosen_kind(self):
        """종류를 바꿨는데 프로그램 목록이 옛 종류로 남으면, 화면에 보이는
        선택지를 골라도 서버가 거절한다 — 저장이 안 되는 이유가 화면 어디에도
        없다. 세 화면 모두 **종류별로** 받아야 한다."""
        design = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                    'design', 'aot-geo-plot.js'))
        plotjs = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                    'widgets', 'AoT_map', 'aot-map-plot.js'))
        facility = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                      'facility', 'plot-ui.js'))
        for src in (design, plotjs, facility):
            self.assertIn("'/api/geo/programs?kind=' + encodeURIComponent(", src)
            self.assertNotIn('/api/geo/programs?kind=vegetation', src)
        # 종류 변경을 실제로 듣는 곳은 이제 **공용 폼 하나**다. 세 화면은
        # 목록을 가져오는 함수(`loadPrograms`)만 넘긴다 — 캐시가 화면마다
        # 다른 곳에 있기 때문이다(디자인은 인스턴스, 위젯은 구획 모듈).
        form = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                                  'aot-plot-form.js'))
        self.assertIn('ctx.loadPrograms', form)
        self.assertIn("selKind.addEventListener('change'", form)
        for src in (design, facility):
            self.assertIn('loadPrograms', src)
        self.assertIn('loadPrograms: _loadPrograms', plotjs)

    def test_block_title_does_not_repeat_its_first_label(self):
        """'심겨 있는 것 / 심은 것' 처럼 제목과 첫 행이 같은 말이면 안 된다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = src.split('function _plotOverviewHtml', 1)[1].split(
            '\n  function ', 1)[0]
        # [현황] 은 "지금" 이다 — 대상·시작일 같은 정체성은 [개요] 가 갖는다.
        self.assertIn("_t('Progress')", body)
        self.assertNotIn("_t('Growing now')", body)
        # [개요]도 같은 문제를 겪었다 — 제목과 첫 행이 둘 다 '심은 것' 이었다.
        about = src.split('function _plotAboutHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("_t('Basics')", about)


def _load_integrity_checker():
    """앱 전체를 끌어오지 않고 검사기 모듈만 로드한다.

    `check_geo_integrity` 는 모듈 상단에서 `from aot.start_flask_ui import app`
    한다 — 그대로 import 하면 Flask 앱 전체(라우트·폼·babel)가 딸려와 테스트가
    앱 부팅에 묶인다(실제로 babel 미초기화로 죽는다). `app` 은 `main()` 이
    app_context 를 열 때만 쓰이고 검사 함수는 쓰지 않으므로 스텁으로 세운다.

    스텁은 로드 직후 걷어낸다 — 남겨 두면 같은 프로세스의 다른 테스트가 진짜
    `start_flask_ui` 대신 이 껍데기를 받는다.
    """
    import importlib
    import sys
    import types

    had_real = 'aot.start_flask_ui' in sys.modules
    if not had_real:
        stub = types.ModuleType('aot.start_flask_ui')
        stub.app = None
        sys.modules['aot.start_flask_ui'] = stub
    try:
        return importlib.import_module('aot.scripts.check_geo_integrity')
    finally:
        if not had_real:
            sys.modules.pop('aot.start_flask_ui', None)


class TestFacilityParentPlot(unittest.TestCase):
    """시설 구획 — 위치의 정본이 기하가 아니라 부모다 (p6_39).

    노지 두둑은 갈아엎으면 위치가 바뀌므로 기하가 정본이고 소속은 파생이다.
    시설은 반대다 — 동·구역이 구조물로 존재하고 사람도 "3동" 이라 부른다.
    그래서 여기서 고정하는 것은 **뒤집힌 정본**이 조용히 되돌아가지 않는 것이다.

    깨져도 조용한 것들:

    - VP-7(기하 또는 부모 중 하나는 있어야 한다)이 빠지면 어디에도 없는 구획이
      만들어진다. 지도에 안 그려지고 어떤 소속 판정에도 안 걸린다.
    - `geometry_of` 폴백이 사라지면 시설 구획만 모든 읽기 경로에서 조용히
      빠진다(지도·소속·센서). 목록에는 계속 보인다.
    - 면적을 내면 시설 외피 면적이 재배 면적으로 읽힌다. 노지형·베드형·수직형은
      같은 바닥 면적에 재배 규모가 전혀 다른데, 숫자에는 그 표시가 없다.
    - 단동에서 `bay_id` 가 NULL 로 남으면 "시설 전체"와 "구역 1"이 같은 대상을
      두 가지로 표현하게 된다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'facility_plot.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoPlot, GeoShape
        for model in (GeoPlot, GeoShape, GeoFacility):
            model.query.delete()
        db.session.commit()

    # ── 준비 ────────────────────────────────────────────────────────────
    def _facility(self, bay_count=1, name='온실1', fittings=None, bays=None):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoShape

        outer = GeoShape(geo_id='map-fac', type='facility',
                         feature={'type': 'Feature', 'properties': {},
                                  'geometry': _square(0.0, 0.0, 0.002)})
        db.session.add(outer)
        db.session.flush()
        fac = GeoFacility(name=name, geo_id='map-fac',
                          shape_uuid=outer.unique_id,
                          structure='connected' if bay_count > 1 else 'single',
                          bay_count=bay_count,
                          # 중심·방위가 있어야 구역 기하를 파생할 수 있다
                          # (없으면 slice_geometry 가 None 을 돌려준다 — 좌표를
                          # 지어내지 않는다는 계약).
                          geometry_3d={'span_width_m': 8.0, 'length_m': 30.0,
                                       'spacing_m': 0.0,
                                       'center_lng': 0.0, 'center_lat': 0.0,
                                       'orientation_deg': 0.0},
                          fittings=fittings or [],
                          # 실제 시설은 저장될 때 구역 메타를 갖는다
                          # (`facility_io`: 단동이면 [{'id': 'main', ...}]).
                          # 생성 시점에 넣는 이유는 하나다 — 만들어 둔 뒤 고쳐
                          # 커밋하면 그 두 번째 커밋이 after_commit 사슬을 깨워
                          # 테스트 단독 실행에서 babel 미등록으로 터진다.
                          bays=bays if bays is not None else [])
        db.session.add(fac)
        db.session.commit()
        return fac

    def _save(self, **over):
        from aot.aot_flask.geo import plot_io
        payload = {'map_uuid': 'map-fac', 'subject': '토마토',
                   'started_on': date.today().isoformat()}
        payload.update(over)
        return plot_io.save_plot(payload)

    # ── VP-7 ────────────────────────────────────────────────────────────
    def test_geometry_or_facility_is_required(self):
        row, err = self._save()
        self.assertIsNone(row)
        self.assertIn('VP-7', err or '')

    def test_facility_alone_is_enough(self):
        fac = self._facility()
        row, err = self._save(facility_uuid=fac.unique_id)
        self.assertIsNone(err)
        self.assertIsNone(row['feature'])
        self.assertEqual(row['location_source'], 'facility')
        self.assertEqual(row['facility_uuid'], fac.unique_id)

    def test_clearing_the_parent_without_geometry_is_refused(self):
        fac = self._facility()
        row, _ = self._save(facility_uuid=fac.unique_id)
        out, err = self._save(unique_id=row['unique_id'], facility_uuid=None)
        self.assertIsNone(out)
        self.assertIn('VP-7', err or '')

    def test_facility_alone_implies_the_map(self):
        """시설을 주면 지도는 시설이 안다 — 지도 uuid 를 따로 묻지 않는다."""
        from aot.aot_flask.geo import plot_io

        fac = self._facility()
        row, err = plot_io.save_plot({
            'facility_uuid': fac.unique_id, 'subject': '토마토',
            'started_on': date.today().isoformat(),
        })
        self.assertIsNone(err)
        self.assertEqual(row['geo_id'], 'map-fac')

    # ── 단동도 구역 하나를 채운다 ───────────────────────────────────────
    def test_single_bay_facility_fills_a_bay(self):
        """구역 목록을 만들 근거가 없으면 관례 id('bay_1')로 물러선다."""
        fac = self._facility(bay_count=1)      # bays 메타 없음
        row, err = self._save(facility_uuid=fac.unique_id)
        self.assertIsNone(err)
        self.assertEqual(row['bay_id'], 'bay_1')

    def test_single_bay_facility_corrects_a_wrong_bay_id(self):
        """단동에 'bay_7' 이 와도 서버가 정정한다 — 클라이언트 말을 믿지 않는다."""
        fac = self._facility(bay_count=1)
        row, err = self._save(facility_uuid=fac.unique_id, bay_id='bay_7')
        self.assertIsNone(err)
        self.assertEqual(row['bay_id'], 'bay_1')

    # ── 구역 안에서의 몫 (p6_50) ────────────────────────────────────────
    #
    # 시설 구획은 기하가 없어 같은 구역의 두 구획이 **똑같이 "그 구역 전체"** 를
    # 가리킨다. 몫이 없으면 화면도 서버도 둘을 구분하지 못한다 — 그런데 그것이
    # 에러로 나타나지 않고 "면적이 같게 보인다" 로만 나타난다.

    def _facility_with_capacity(self, total=12, unit='bed'):
        return self._facility(bay_count=1, bays=[{
            'id': 'main', 'name': '온실1', 'crop': None,
            'capacity': {'unit': unit, 'total': total},
        }])

    def test_amount_derives_percent_from_the_zone_total(self):
        """비율은 **저장하지 않고 파생한다** — 총량이 바뀌면 따라 바뀌어야 한다."""
        fac = self._facility_with_capacity(total=12)
        row, err = self._save(facility_uuid=fac.unique_id,
                              allocation={'amount': 4})
        self.assertIsNone(err)
        self.assertEqual(row['allocation']['amount'], 4)
        self.assertEqual(row['allocation']['total'], 12)
        self.assertEqual(row['allocation']['unit'], 'bed')
        self.assertAlmostEqual(row['allocation']['percent'], 33.3, places=1)

    def test_percent_follows_the_total_when_it_changes(self):
        """총량을 고치면 같은 4베드가 다른 비율이 된다(그래서 저장하지 않는다)."""
        from aot.aot_flask.extensions import db

        fac = self._facility_with_capacity(total=12)
        row, _ = self._save(facility_uuid=fac.unique_id, allocation={'amount': 4})
        self.assertAlmostEqual(row['allocation']['percent'], 33.3, places=1)

        fac.bays = [{'id': 'main', 'name': '온실1',
                     'capacity': {'unit': 'bed', 'total': 8}}]
        db.session.commit()

        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot
        again = plot_context.to_dict(
            GeoPlot.query.filter_by(unique_id=row['unique_id']).first())
        self.assertEqual(again['allocation']['amount'], 4)
        self.assertEqual(again['allocation']['total'], 8)
        self.assertAlmostEqual(again['allocation']['percent'], 50.0, places=1)

    def test_percent_is_the_fallback_when_no_total_is_recorded(self):
        """총량을 아직 안 적은 시설에서도 두 구획은 구분돼야 한다."""
        fac = self._facility(bay_count=1)          # capacity 없음
        row, err = self._save(facility_uuid=fac.unique_id,
                              allocation={'percent': 40})
        self.assertIsNone(err)
        self.assertEqual(row['allocation']['percent'], 40)
        self.assertNotIn('total', row['allocation'])

    def test_the_sum_may_exceed_the_total(self):
        """간작·혼작이 정상이다(VP-3) — 합이 넘어도 저장을 막지 않는다."""
        fac = self._facility_with_capacity(total=12)
        a, err_a = self._save(facility_uuid=fac.unique_id, subject='토마토',
                              allocation={'amount': 8})
        b, err_b = self._save(facility_uuid=fac.unique_id, subject='바질',
                              allocation={'amount': 8})
        self.assertIsNone(err_a)
        self.assertIsNone(err_b)
        self.assertEqual(a['allocation']['amount'], 8)
        self.assertEqual(b['allocation']['amount'], 8)

    def test_amount_and_percent_together_are_refused(self):
        """어느 쪽이 정본인지 모호한 값을 저장하면 화면마다 다른 숫자가 된다."""
        fac = self._facility_with_capacity()
        row, err = self._save(facility_uuid=fac.unique_id,
                              allocation={'amount': 4, 'percent': 30})
        self.assertIsNone(row)
        self.assertIn('하나만', err or '')

    def test_zero_or_negative_share_is_refused(self):
        fac = self._facility_with_capacity()
        for bad in (0, -3):
            row, err = self._save(facility_uuid=fac.unique_id,
                                  allocation={'amount': bad})
            self.assertIsNone(row, bad)
            self.assertIn('0보다', err or '')

    def test_percent_over_100_is_refused(self):
        """한 구획이 구역의 100%를 넘게 쓸 수는 없다(합계와는 다른 이야기다)."""
        fac = self._facility(bay_count=1)
        row, err = self._save(facility_uuid=fac.unique_id,
                              allocation={'percent': 120})
        self.assertIsNone(row)
        self.assertIn('100', err or '')

    def test_a_plot_with_its_own_geometry_refuses_a_share(self):
        """노지 구획은 면적이 도형에서 나온다 — 몫을 적으면 정본이 둘이 된다.

        조용히 무시하지 않는 이유: 무시하면 "적었는데 화면이 안 바뀐다" 가 되고
        그때 원인이 입력인지 저장인지 가릴 방법이 없다.
        """
        row, err = self._save(feature={'type': 'Feature', 'properties': {},
                                       'geometry': _square(0.0, 0.0, 0.001)},
                              allocation={'percent': 50})
        self.assertIsNone(row)
        self.assertIn('기하', err or '')

    def test_a_partial_save_keeps_the_share(self):
        """날짜만 고치는 저장이 적어 둔 몫을 지우면 안 된다."""
        fac = self._facility_with_capacity()
        row, _ = self._save(facility_uuid=fac.unique_id, allocation={'amount': 4})
        again, err = self._save(unique_id=row['unique_id'],
                                expected_end_on='2026-12-31')
        self.assertIsNone(err)
        self.assertEqual(again['allocation']['amount'], 4)

    def test_an_empty_share_clears_it(self):
        """잘못 적은 것을 되돌릴 수단이 없으면 사람은 아무 숫자나 두고 만다."""
        fac = self._facility_with_capacity()
        row, _ = self._save(facility_uuid=fac.unique_id, allocation={'amount': 4})
        again, err = self._save(unique_id=row['unique_id'], allocation=None)
        self.assertIsNone(err)
        self.assertIsNone(again['allocation'])

    def test_single_bay_uses_the_facilitys_real_bay_id_not_a_constant(self):
        """**실제 단동 시설의 구역 id 는 'main' 이다.**

        `facility_io` 가 단동 시설을 저장할 때 `bays=[{'id': 'main', ...}]` 을
        만든다. 예전에는 저장 경로가 단동만 대조를 건너뛰고 `'bay_1'` 을 박아,
        저장은 성공하는데 읽는 쪽(`bay_geometries`/`bay_names`)에 그 키가 없어
        구획이 **구역 기하 대신 시설 외피로 폴백**하고 구역 이름이 비었다 —
        화면에서는 구획이 시설에 붙지 않고 따로 노는 것으로 보였다.
        에러는 나지 않았고 `check_geo_integrity` 의 `plot-unknown-bay` 만이 봤다.

        픽스처가 `bays` 를 비워 두는 바람에 위의 두 테스트는 폴백 경로만 돌아
        이 버그를 통과시켰다 — 그래서 여기서는 실제 시설과 같은 모양을 만든다.
        """
        # 실제 단동 시설과 같은 모양 — 구역 메타가 'main' 하나.
        fac = self._facility(bay_count=1,
                             bays=[{'id': 'main', 'name': '온실1', 'crop': None}])

        # 결과가 'main' 이라는 것 자체가 "목록을 따랐다" 는 증거다 — 상수를
        # 박는 옛 코드에서는 여기서 'bay_1' 이 나온다.
        row, err = self._save(facility_uuid=fac.unique_id)
        self.assertIsNone(err)
        self.assertEqual(row['bay_id'], 'main')

        # 클라이언트가 옛 상수를 보내도 실제 id 로 정정된다.
        row2, err2 = self._save(facility_uuid=fac.unique_id, subject='바질',
                                bay_id='bay_1')
        self.assertIsNone(err2)
        self.assertEqual(row2['bay_id'], 'main')

    # ── 다동 ────────────────────────────────────────────────────────────
    def test_multi_bay_rejects_unknown_bay_id(self):
        fac = self._facility(bay_count=3)
        row, err = self._save(facility_uuid=fac.unique_id, bay_id='bay_9')
        self.assertIsNone(row)
        self.assertIn('bay_9', err or '')

    def test_multi_bay_accepts_a_real_bay_and_allows_whole_facility(self):
        fac = self._facility(bay_count=3)
        row, err = self._save(facility_uuid=fac.unique_id, bay_id='bay_2')
        self.assertIsNone(err)
        self.assertEqual(row['bay_id'], 'bay_2')

        whole, err = self._save(facility_uuid=fac.unique_id, subject='바질')
        self.assertIsNone(err)
        self.assertIsNone(whole['bay_id'])     # 다동에서 NULL = 시설 전체

    def test_unknown_facility_is_refused(self):
        row, err = self._save(facility_uuid='no-such-facility')
        self.assertIsNone(row)
        self.assertIn('시설', err or '')

    # ── 기하 파생 ───────────────────────────────────────────────────────
    def test_geometry_is_derived_from_the_facility(self):
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac = self._facility()
        saved, _ = self._save(facility_uuid=fac.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        self.assertFalse(row.has_own_geometry())
        geom = plot_context.geometry_of(row)
        self.assertEqual(geom.get('type'), 'Polygon')
        # 저장된 것이 아니라 파생이다 — 행은 여전히 비어 있어야 한다.
        self.assertIsNone(row.feature)

    def test_derived_geometry_is_not_written_back(self):
        """파생을 응답에서 받아 그대로 되돌려 저장해도 각인되지 않는다."""
        from aot.databases.models import GeoPlot

        fac = self._facility()
        saved, _ = self._save(facility_uuid=fac.unique_id)
        self.assertIsNotNone(saved.get('derived_feature'))
        self.assertIsNone(saved['feature'])

        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertIsNone(row.feature)

    # ── 면적·치수·밸브를 내지 않는다 ────────────────────────────────────
    def test_no_area_no_dims_no_valves(self):
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac = self._facility()
        saved, _ = self._save(facility_uuid=fac.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        # 0 이 아니라 None 이다 — 0 은 "면적이 없다"는 거짓말이다.
        self.assertIsNone(saved['area_m2'])
        detail = plot_context.to_dict(row, with_sensors=False,
                                          with_dims=True, with_valves=True)
        self.assertNotIn('dims', detail)
        self.assertNotIn('valves', detail)

    def test_zone_allocation_skips_facility_plots(self):
        """온실 하나가 zone 을 통째로 덮은 것처럼 계산되면 안 된다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoShape

        zone = GeoShape(geo_id='map-fac', type='zone',
                        feature={'type': 'Feature', 'properties': {'name': 'Z'},
                                 'geometry': _square(0.0, 0.0, 0.01)})
        db.session.add(zone)
        db.session.commit()

        fac = self._facility()
        self._save(facility_uuid=fac.unique_id)
        alloc = plot_context.zone_allocation(zone)
        self.assertEqual(alloc['plots'], [])
        self.assertEqual(alloc['assigned_m2'], 0.0)

    # ── 이력 보호 ───────────────────────────────────────────────────────
    def test_ended_plot_cannot_move_to_another_bay(self):
        from aot.aot_flask.geo import plot_io

        fac = self._facility(bay_count=3)
        row, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_1')
        plot_io.end_plot(row['unique_id'])
        out, err = self._save(unique_id=row['unique_id'],
                              facility_uuid=fac.unique_id, bay_id='bay_2')
        self.assertIsNone(out)
        self.assertIn('VP-6', err or '')

    def test_copy_keeps_the_parent(self):
        from aot.aot_flask.geo import plot_io

        fac = self._facility(bay_count=3)
        row, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_2')
        copy, err = plot_io.copy_plot(row['unique_id'])
        self.assertIsNone(err)
        self.assertEqual(copy['facility_uuid'], fac.unique_id)
        self.assertEqual(copy['bay_id'], 'bay_2')

    def test_modal_payload_can_move_a_plot_between_zones(self):
        """모달 편집이 보내는 것과 같은 페이로드로 구역을 옮길 수 있는가.

        모달은 `data-pf` 필드를 전부 싣고 빈 칸은 `''` 로 보낸다 — 그 모양
        그대로 처리돼야 한다. 빈 `bay_id` 는 "시설 전체" 라는 뜻이다.
        """
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        fac = self._facility(bay_count=3)
        saved, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_1')

        moved, err = plot_io.save_plot({
            'unique_id': saved['unique_id'], 'bay_id': 'bay_2',
            'subject': '토마토', 'variety': '', 'name': '',
            'started_on': date.today().isoformat(), 'expected_end_on': '',
            'color': '#6a8f3c',
        })
        self.assertIsNone(err)
        self.assertEqual(moved['bay_id'], 'bay_2')

        whole, err = plot_io.save_plot({
            'unique_id': saved['unique_id'], 'bay_id': ''})
        self.assertIsNone(err)
        self.assertIsNone(whole['bay_id'])        # 빈 값 = 시설 전체

        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertEqual(row.facility_uuid, fac.unique_id)   # 부모는 유지된다

    def test_response_carries_the_zone_choices(self):
        """모달이 구역을 고르려면 선택지가 응답에 있어야 한다."""
        fac = self._facility(bay_count=3)
        saved, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_2')
        ids = [b['id'] for b in saved.get('facility_bays') or []]
        self.assertEqual(ids, ['bay_1', 'bay_2', 'bay_3'])

    # ── 구역 단위 기하 파생 ─────────────────────────────────────────────
    def test_bay_geometry_is_narrower_than_the_whole_facility(self):
        """구역 하나짜리 구획이 시설 전체 자리를 차지하지 않는다."""
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac = self._facility(bay_count=3)
        saved, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_2')
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        geom = plot_context.geometry_of(row)
        self.assertEqual(geom.get('type'), 'Polygon')

        whole, _ = self._save(facility_uuid=fac.unique_id, subject='바질')
        whole_row = GeoPlot.query.filter_by(
            unique_id=whole['unique_id']).first()
        whole_geom = plot_context.geometry_of(whole_row)

        # 시설 전체(외피 폴백)보다 좁아야 한다 — 같으면 좁히기가 안 된 것이다.
        a_bay = plot_context.shapely_area_m2(
            plot_context._shapely(geom))
        a_all = plot_context.shapely_area_m2(
            plot_context._shapely(whole_geom))
        self.assertGreater(a_bay, 0)
        self.assertLess(a_bay, a_all * 0.75)

    def test_bay_geometry_matches_the_editor_rectangle(self):
        """편집기(`rotatedRectRing`)와 같은 규칙으로 계산되는가.

        같은 규칙이 아니면 구역이 시설 밖으로 삐져나온 것처럼 보인다. 여기서는
        면적으로 본다 — 연동 3동 중 1동은 span×length 여야 한다.
        """
        from aot.aot_flask.geo import facility_bays, plot_context

        fac = self._facility(bay_count=3)
        spec = facility_bays.spec_from_row(fac)
        geom = facility_bays.geometry_for_bay(spec, 'bay_2')
        area = plot_context.shapely_area_m2(plot_context._shapely(geom))
        self.assertAlmostEqual(area, 8.0 * 30.0, delta=8.0)   # span 8 × length 30

    def test_detached_bays_are_a_multipolygon(self):
        """분리동은 동 사이가 비어 있다 — 하나의 사각형으로 덮지 않는다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import facility_bays
        from aot.databases.models import GeoFacility

        fac = self._facility(bay_count=3)
        fac.structure = 'single'          # 분리동
        g3d = dict(fac.geometry_3d or {})
        g3d['spacing_m'] = 3.0
        fac.geometry_3d = g3d
        db.session.commit()

        spec = facility_bays.spec_from_row(
            GeoFacility.query.filter_by(unique_id=fac.unique_id).first())
        # 병합 구역(1~3동)을 하나 만들어 본다.
        geom = facility_bays.slice_geometry(
            spec, {'id': 'bay_1_3', 'bay_start': 1, 'bay_end': 3})
        self.assertEqual(geom.get('type'), 'MultiPolygon')
        self.assertEqual(len(geom['coordinates']), 3)

    def test_unplaced_facility_has_no_derived_geometry(self):
        """지도에 배치되지 않은 시설은 좌표를 **지어내지 않는다**."""
        from aot.aot_flask.geo import facility_bays

        spec = {'structure': 'connected', 'bay_count': 2,
                'geometry_3d': {'span_width_m': 8, 'length_m': 30},  # 중심 없음
                'bays': [], 'name': 'x'}
        self.assertIsNone(facility_bays.geometry_for_bay(spec, 'bay_1'))

    def test_response_carries_the_bay_geometry_for_drawing(self):
        """위젯이 그릴 수 있도록 `derived_feature` 로 나가되 `feature` 는 빈 채."""
        fac = self._facility(bay_count=3)
        saved, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_3')
        self.assertIsNone(saved['feature'])
        df = saved.get('derived_feature')
        self.assertTrue(df and df.get('geometry'))
        self.assertEqual(df['properties']['derived_from'], 'bay')

    # ── 센서 — 마커가 아니라 fitting 에서 찾는다 ────────────────────────
    def _facility_with_sensors(self):
        """구역 2개, 각 구역에 센서 fitting 하나씩.

        시설 센서는 로컬 미터 좌표(`position`)로 붙어 있고 **지도 마커가
        아니다.** 그래서 구역 귀속은 기하 교차가 아니라 x 좌표 → 슬라이스
        매핑으로 정해진다(`facility_bays.build_fitting_bay_map`).
        """
        from aot.aot_flask.extensions import db
        from aot.databases.models import Input

        ids = []
        for name in ('1동 온습도', '2동 온습도'):
            inp = Input(name=name, device='TEST00')
            db.session.add(inp)
            db.session.flush()
            ids.append(inp.unique_id)
        db.session.commit()

        # span 8m × 2구역 → bay_1 은 x 0~8, bay_2 는 x 8~16.
        fittings = [
            {'id': 'f1', 'kind': 'sensor', 'input_id': ids[0],
             'sensor_role': 'indoor', 'position': [4.0, 1.5, 15.0]},
            {'id': 'f2', 'kind': 'sensor', 'input_id': ids[1],
             'sensor_role': 'indoor', 'position': [12.0, 1.5, 15.0]},
        ]
        return self._facility(bay_count=2, fittings=fittings), ids

    def test_bay_plot_sees_only_its_own_bay_sensor(self):
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac, ids = self._facility_with_sensors()
        saved, err = self._save(facility_uuid=fac.unique_id, bay_id='bay_1')
        self.assertIsNone(err)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        out = plot_context.sensors_for_plot(row)
        self.assertEqual(out['source'], 'bay')
        self.assertEqual(out['in_bay'], [ids[0]])
        self.assertEqual(sorted(out['from_facility']), sorted(ids))
        # 마커 판정은 아예 돌지 않는다 — 파생 기하(시설 외피)로 세면 시설
        # 어딘가의 장치가 전부 이 구획의 것으로 잡힌다.
        self.assertEqual(out['in_plot'], [])

    def test_a_plot_never_sees_the_weather_station(self):
        """구획은 **기르는 대상이 겪는 환경**만 묻는 자리다.

        기상대를 섞으면 같은 '온도' 가 두 뜻으로 한 목록에 서고, 겨울에 안 25°C ·
        밖 -5°C 면 어느 쪽이 이 작물의 온도인지 화면이 답하지 못한다.

        ⚠ **위치로는 가릴 수 없다.** 기상대도 시설 어딘가에 서 있어서 좌표 →
        슬라이스 매핑이 그것에 동을 붙인다. 가르는 것은 사람이 정한 `sensor_role`
        하나뿐이고, 미설정은 실내로 본다(서버·프런트 공통 폴백).

        반대 방향은 시설 모달이 맡는다 — 그쪽 환경 카드에는 실외가 **들어간다**
        (`_baySensors`). 같은 시설을 보면서 두 화면의 목록이 다른 것은 의도다.
        """
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        from aot.aot_flask.extensions import db as _db
        from aot.databases.models import Input as _Input
        ids = []
        for _n in ('실내 온습도', '기상대'):
            _i = _Input(name=_n, device='TEST00')
            _db.session.add(_i); _db.session.flush()
            ids.append(_i.unique_id)
        _db.session.commit()
        fittings = [
            {'id': 'f1', 'kind': 'sensor', 'input_id': ids[0],
             'sensor_role': 'indoor', 'position': [4.0, 1.5, 15.0]},
            {'id': 'f2', 'kind': 'sensor', 'input_id': ids[1],
             'sensor_role': 'outdoor', 'position': [12.0, 1.5, 15.0]},
        ]
        fac = self._facility(bay_count=2, fittings=fittings)
        saved, err = self._save(facility_uuid=fac.unique_id, bay_id='bay_1')
        self.assertIsNone(err)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        out = plot_context.sensors_for_plot(row)
        self.assertNotIn(ids[1], out['from_facility'], '실외 센서가 구획에 실렸다')
        self.assertNotIn(ids[1], out['in_bay'])
        self.assertEqual([ids[0]], out['from_facility'])

    def test_facility_modal_keeps_outdoor_in_its_environment_list(self):
        """시설은 안과 밖을 함께 다루는 단위다 — 창을 열지, 커튼을 칠지는 바깥이
        어떤가에서 나오는 판단이라 환경 카드가 그것을 말해야 한다.

        실외는 **동으로 나누지 않는다**(바깥은 어느 동의 것도 아니다). 그리고
        **평균에는 넣지 않는다** — 목록에 보이는 것과 한 숫자로 접는 것은 다른
        일이고, 안팎을 평균 내면 어느 곳도 가리키지 않는 값이 나온다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = vec.split('function _baySensors', 1)[1].split('\n        }', 1)[0]
        self.assertIn('!window.AoTMapBay.isIndoor(s)', body, '실외를 모으지 않는다')
        self.assertIn('.concat(outdoor)', body)
        self.assertNotIn('s.bay_id', body.split('var outdoor', 1)[1],
                         '실외를 동으로 나누면 안 된다')
        # 평균(칩)은 계속 실내만.
        summ = vec.split('function _sensorSummary', 1)[1].split('\n        }', 1)[0]
        self.assertIn('window.AoTMapBay.isIndoor(s)', summ)

    def test_whole_facility_plot_falls_back_to_facility_scope(self):
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac, ids = self._facility_with_sensors()
        saved, _ = self._save(facility_uuid=fac.unique_id)   # 다동 + bay 없음
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        out = plot_context.sensors_for_plot(row)
        self.assertEqual(out['source'], 'facility')
        self.assertEqual(out['in_bay'], [])
        self.assertEqual(sorted(out['from_facility']), sorted(ids))

    def test_dead_fitting_reference_is_not_reported_as_a_sensor(self):
        """fitting 이 지워진 장치를 가리키면 센서로 세지 않는다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot, Input

        fac, ids = self._facility_with_sensors()
        Input.query.filter_by(unique_id=ids[0]).delete()
        db.session.commit()

        saved, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_1')
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        out = plot_context.sensors_for_plot(row)
        self.assertEqual(out['in_bay'], [])
        self.assertEqual(out['from_facility'], [ids[1]])
        self.assertEqual(out['source'], 'facility')

    # ── 제어 축 교차 ────────────────────────────────────────────────────
    def _coordinator(self, name, bay_scope=None, activated=True):
        import json as _json
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController

        opts = {'geo_facility_id': self._fac_uuid}
        if bay_scope:
            opts['bay_scope'] = bay_scope
        c = CustomController(name=name, device='env_coordinator',
                             custom_options=_json.dumps(opts),
                             is_activated=activated)
        db.session.add(c)
        db.session.commit()
        return c

    def test_control_picks_the_bay_coordinator_and_the_whole_facility_one(self):
        """구역 전담과 시설 전체가 함께 도는 것이 정상 구성이다.

        한쪽만 보이면 "왜 내 설정이 안 먹지" 를 설명할 근거가 사라진다.
        """
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac = self._facility(bay_count=3)
        self._fac_uuid = fac.unique_id
        self._coordinator('1동 전담', bay_scope='bay_1')
        self._coordinator('온실 전체')
        self._coordinator('2동 전담', bay_scope='bay_2')

        saved, _ = self._save(facility_uuid=fac.unique_id, bay_id='bay_1')
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        out = plot_context.facility_control_for_plot(row)

        names = sorted(c['name'] for c in out['coordinators'])
        self.assertEqual(names, ['1동 전담', '온실 전체'])
        scopes = {c['name']: c['scope'] for c in out['coordinators']}
        self.assertEqual(scopes['1동 전담'], 'bay')
        self.assertEqual(scopes['온실 전체'], 'facility')
        self.assertEqual(out['source'], 'bay')
        self.assertEqual(out['bay']['name'], 'Bay 1')

    def test_whole_facility_plot_does_not_claim_a_bay_coordinator(self):
        """시설 전체 구획을 한 구역짜리 코디네이터가 대표할 수는 없다."""
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        fac = self._facility(bay_count=3)
        self._fac_uuid = fac.unique_id
        self._coordinator('2동 전담', bay_scope='bay_2')

        saved, _ = self._save(facility_uuid=fac.unique_id)   # bay 없음
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        out = plot_context.facility_control_for_plot(row)
        self.assertEqual(out['coordinators'], [])
        self.assertEqual(out['source'], 'none')

    def test_control_is_read_only(self):
        """재료만 낸다 — 여기서 제어를 걸지 않는다(관수량 미계산과 같은 결)."""
        import inspect
        from aot.aot_flask.geo import plot_context

        src = inspect.getsource(plot_context.facility_control_for_plot)
        for banned in ('DaemonControl', 'output_on', 'set_output',
                       'db.session.add', 'db.session.commit'):
            self.assertNotIn(banned, src)

    def test_facility_knows_what_is_growing_in_it(self):
        """반대 방향 — 제어 화면이 "무엇이 며칠째" 를 말할 수 있어야 한다."""
        from aot.aot_flask.geo import plot_context

        fac = self._facility(bay_count=3)
        self._save(facility_uuid=fac.unique_id, bay_id='bay_1', subject='토마토')
        self._save(facility_uuid=fac.unique_id, subject='바질')      # 시설 전체

        rows = plot_context.plots_in_facility(fac.unique_id)
        self.assertEqual(sorted(r.subject for r in rows), ['바질', '토마토'])

        # 구역 뷰에서도 **시설 전체 구획이 함께** 보여야 한다 — 그 작물도 이
        # 구역에서 자라고 있다.
        in_bay1 = plot_context.plots_in_facility(fac.unique_id, bay_id='bay_1')
        self.assertEqual(sorted(r.subject for r in in_bay1), ['바질', '토마토'])
        in_bay2 = plot_context.plots_in_facility(fac.unique_id, bay_id='bay_2')
        self.assertEqual([r.subject for r in in_bay2], ['바질'])

        brief = plot_context.plot_brief_for_control(rows[0])
        self.assertNotIn('area_m2', brief)      # 시설에서는 낼 수 없는 값
        self.assertIn('days_since_planted', brief)

    # ── 구역 구성 변경 경고 ─────────────────────────────────────────────
    def test_shrinking_the_zones_reports_orphaned_plots(self):
        from aot.aot_flask.geo.facility_io import FacilityManager
        from aot.databases.models import GeoFacility

        fac = self._facility(bay_count=3)
        self._save(facility_uuid=fac.unique_id, bay_id='bay_3', subject='토마토')
        self._save(facility_uuid=fac.unique_id, bay_id='bay_1', subject='상추')

        fac.bay_count = 2                      # 3동 → 2동
        from aot.aot_flask.extensions import db
        db.session.commit()

        row = GeoFacility.query.filter_by(unique_id=fac.unique_id).first()
        orphans = FacilityManager._orphaned_plots(row)
        self.assertEqual([o['subject'] for o in orphans], ['토마토'])

    def test_whole_facility_plots_are_never_orphaned(self):
        """구역이 어떻게 바뀌든 "시설 전체" 라는 자리는 사라지지 않는다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo.facility_io import FacilityManager
        from aot.databases.models import GeoFacility

        fac = self._facility(bay_count=3)
        self._save(facility_uuid=fac.unique_id, subject='바질')
        fac.bay_count = 1
        db.session.commit()
        row = GeoFacility.query.filter_by(unique_id=fac.unique_id).first()
        self.assertEqual(FacilityManager._orphaned_plots(row), [])

    def test_no_judgement_without_a_zone_list(self):
        """치수를 아직 안 넣은 시설에서 근거 없이 경고하지 않는다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo.facility_io import FacilityManager
        from aot.databases.models import GeoFacility

        fac = self._facility(bay_count=2)
        self._save(facility_uuid=fac.unique_id, bay_id='bay_1', subject='상추')
        fac.geometry_3d = {}                   # 슬라이스를 만들 수 없다
        db.session.commit()
        row = GeoFacility.query.filter_by(unique_id=fac.unique_id).first()
        self.assertEqual(FacilityManager._orphaned_plots(row), [])

    def test_integrity_flags_an_unknown_bay(self):
        from collections import defaultdict
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility

        chk = _load_integrity_checker()
        fac = self._facility(bay_count=3)
        self._save(facility_uuid=fac.unique_id, bay_id='bay_3', subject='토마토')
        fac.bay_count = 2
        db.session.commit()

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        self.assertEqual(len(findings['plot-unknown-bay']), 1)
        self.assertEqual(findings['plot-unknown-bay'][0]['bay_id'], 'bay_3')

    # ── 무결성 검사 ─────────────────────────────────────────────────────
    def test_integrity_does_not_flag_a_missing_geometry_as_bad(self):
        from collections import defaultdict
        chk = _load_integrity_checker()

        fac = self._facility()
        self._save(facility_uuid=fac.unique_id)

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        self.assertEqual(findings['plot-bad-geometry'], [])
        self.assertEqual(findings['plot-no-location'], [])
        self.assertEqual(findings['plot-dangling-facility'], [])

    def test_integrity_flags_a_dead_facility_reference(self):
        from collections import defaultdict
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility
        chk = _load_integrity_checker()

        fac = self._facility()
        self._save(facility_uuid=fac.unique_id)
        GeoFacility.query.filter_by(unique_id=fac.unique_id).delete()
        db.session.commit()

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        self.assertEqual(len(findings['plot-dangling-facility']), 1)
        self.assertIn('plot-dangling-facility', chk.SEVERE)

    def test_integrity_flags_a_kind_mismatch(self):
        """쓰기 게이트웨이를 지나지 않은 행은 아무도 안 본다.

        `save_plot` 이 붙일 때와 종류만 바꿀 때 둘 다 막지만, 게이트웨이가
        생기기 전에 만들어진 행·백필·직접 수정은 그 검사를 지나지 않는다. 어긋난
        채로도 **에러가 나지 않고** 화면에는 그럴듯한 단계와 목표가 뜬다.
        """
        from collections import defaultdict
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoProgram
        chk = _load_integrity_checker()

        prog = GeoProgram(name='젖소 표준', subject='젖소', kind='livestock',
                          stages=[{'key': 'lactation', 'name': '착유기',
                                   'days': 305}])
        db.session.add(prog)
        db.session.commit()

        fac = self._facility()
        saved, err = self._save(subject='상추',
                                facility_uuid=fac.unique_id)   # kind='vegetation'
        self.assertIsNone(err)
        # 게이트웨이를 우회해 직접 붙인다 — 정확히 이 검사가 잡아야 할 모양이다.
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        row.program_uuid = prog.unique_id
        db.session.commit()

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        hits = findings['plot-program-kind-mismatch']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['plot_kind'], 'vegetation')
        self.assertEqual(hits[0]['program_kind'], 'livestock')
        # 값이 제어로 흐르므로 경고가 아니라 severe 다.
        self.assertIn('plot-program-kind-mismatch', chk.SEVERE)
        # 출력 루프가 HEADINGS 선언 순서를 따르므로, 여기 없으면 집계에만
        # 잡히고 화면에는 안 나온다(2026-08-08 에 실제로 겪은 모양).
        self.assertIn('plot-program-kind-mismatch', chk.HEADINGS)

    def test_integrity_flags_a_dead_program_reference(self):
        """프로그램을 지우면 단계·목표·예상 종료일이 통째로 사라지는데 화면에는
        '프로그램 없음' 으로만 보인다 — 지운 것인지 끊어진 것인지 구분되지
        않는다."""
        from collections import defaultdict
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoProgram
        chk = _load_integrity_checker()

        prog = GeoProgram(name='상추 표준', subject='상추', kind='vegetation',
                          stages=[{'key': 'grow', 'name': '생육기',
                                   'days': 40}])
        db.session.add(prog)
        db.session.commit()
        fac = self._facility()
        saved, err = self._save(subject='상추', facility_uuid=fac.unique_id,
                                program_uuid=prog.unique_id)
        self.assertIsNone(err)

        GeoProgram.query.filter_by(unique_id=prog.unique_id).delete()
        db.session.commit()

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        self.assertEqual(len(findings['plot-dangling-program']), 1)
        # 구획 자체는 계속 보인다 — 화면에서 사라지는 것도, 잘못 붙은 것도
        # 아니므로 severe 가 아니다.
        self.assertNotIn('plot-dangling-program', chk.SEVERE)
        self.assertIn('plot-dangling-program', chk.HEADINGS)

    def test_integrity_is_quiet_when_the_pair_matches(self):
        """정상 조합에서 조용한지 확인한다 — 안 그러면 위 두 검사가 항상
        켜져 있는 것과 같아 아무 정보도 주지 않는다."""
        from collections import defaultdict
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoProgram
        chk = _load_integrity_checker()

        prog = GeoProgram(name='상추 표준', subject='상추', kind='vegetation',
                          stages=[{'key': 'grow', 'name': '생육기',
                                   'days': 40}])
        db.session.add(prog)
        db.session.commit()
        fac = self._facility()
        _saved, err = self._save(subject='상추', facility_uuid=fac.unique_id,
                                 program_uuid=prog.unique_id)
        self.assertIsNone(err)

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        self.assertEqual(findings['plot-program-kind-mismatch'], [])
        self.assertEqual(findings['plot-dangling-program'], [])

    def test_integrity_flags_a_plot_with_no_location_at_all(self):
        """검증을 우회해 들어온 행(직접 INSERT·옛 백필)도 잡힌다."""
        from collections import defaultdict
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot
        chk = _load_integrity_checker()

        db.session.add(GeoPlot(geo_id='map-fac', feature=None, subject='공중부양',
                                   started_on=date.today()))
        db.session.commit()

        findings = defaultdict(list)
        chk._collect_plots(findings, None, {'map-fac': '테스트지도'})
        self.assertEqual(len(findings['plot-no-location']), 1)

class TestFacilityPlotRendering(unittest.TestCase):
    """지도 위젯이 시설 구획을 그릴 수 있는가 — 소스로 고정한다.

    시설 구획은 `feature` 가 비어 있고 서버가 `derived_feature` 로 자리를 준다.
    위젯이 `p.feature.geometry` 만 보면 **온실 작물만 지도에서 통째로 사라지는데**,
    목록·AI·편집기에는 그대로 보이므로 아무도 없어진 줄 모른다. 라벨과 폴리곤이
    서로 다른 접근자를 쓰다 한쪽만 고쳐지는 것도 같은 계열이라, 공용 접근자
    하나(`_geomOf`)를 쓰는 것까지 함께 본다.
    """

    _WIDGET_VEG = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                               'AoT_map', 'aot-map-plot.js')
    _WIDGET_POPUP = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                 'AoT_map', 'aot-map-popup.js')
    _DESIGN_VEG = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                               'design', 'aot-geo-plot.js')

    def test_widget_falls_back_to_the_derived_geometry(self):
        src = _read(self._WIDGET_VEG)
        self.assertIn('derived_feature', src,
                      '위젯이 파생 기하를 모르면 시설 구획이 지도에서 사라진다')
        self.assertIn('function _geomOf(', src)

    def test_polygon_and_label_use_the_same_accessor(self):
        """폴리곤은 뜨는데 라벨은 안 뜨는(또는 반대) 상태를 막는다."""
        src = _read(self._WIDGET_VEG)
        self.assertGreaterEqual(src.count('_geomOf(p)'), 2)
        # 옛 직접 접근이 되살아나면 그 자리만 조용히 빠진다.
        self.assertNotIn('var geom = p.feature && p.feature.geometry;', src)

    def test_facility_plot_label_is_offset_from_the_bay_chip(self):
        """구역 칩과 같은 자리에 겹쳐 그리지 않는다(둘 다 못 읽게 된다)."""
        src = _read(self._WIDGET_VEG)
        self.assertIn("location_source === 'facility'", src)
        self.assertIn('_southOffsetPoint', src)

    def test_modal_says_where_instead_of_area(self):
        """면적이 빈 자리를 "계산 중" 으로 읽지 않도록 위치와 이유를 말한다."""
        src = _read(self._WIDGET_POPUP)
        self.assertIn('_plotPlaceHtml', src)
        self.assertIn("p.location_source !== 'facility'", src)
        self.assertIn('facility_name', src)

    def test_client_preview_follows_the_server_zone_rule(self):
        """저장 전 경고의 판정이 서버 규칙과 같은가 (소스로 고정).

        구역 편집기 상태(`bays`)와 동 수 입력(`bay_count`)은 서로 다른 위젯이라
        **어긋난 순간이 실재한다.** 그때 `bays` 를 그대로 믿으면 "사라지는 구역
        없음" 으로 읽고 경고 없이 저장하는데, 서버는 `bay_count` 로 다시 자르므로
        실제로는 그 구역이 사라진다 — 2026-08-19 에 실제로 그렇게 저장돼 구획
        하나가 갈 곳을 잃었다(서버 경고 로그만 남았다).

        그래서 미리보기도 서버와 같은 두 단계를 밟아야 한다: `bay_end <=
        bay_count` 로 거르고, 남는 것이 없으면 bay 당 1구역으로 합성한다.
        """
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                 'aot-facility-design.js'))
        body = src.split('function plannedBayIds(', 1)[1].split('\n  }', 1)[0]
        self.assertIn('e <= n', body, 'bay_count 범위를 벗어난 구역을 걸러야 한다')
        self.assertIn("'bay_' + i", body, 'bay 당 1구역 폴백이 있어야 한다')

    def test_server_is_the_authority_on_orphans(self):
        """미리보기를 지나쳐도 저장 응답이 사실을 말해야 한다."""
        io_src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'facility_io.py'))
        self.assertIn('orphaned_plots', io_src)
        self.assertIn('_orphaned_plots', io_src)
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'aot-facility-design.js'))
        self.assertIn('json.orphaned_plots', js)

    def test_modal_can_edit_a_facility_plot(self):
        """시설 구획도 모달에서 고칠 수 있어야 한다 — 노지와 같은 자리에서.

        편집 폼 자체는 종류를 가리지 않지만(기하를 안 보낸다), **구역 선택**이
        없으면 시설 구획만 위치를 못 고쳐 시설 편집기까지 다녀와야 한다.
        """
        src = _read(self._WIDGET_POPUP)
        self.assertIn("data-pf=\"bay_id\"", src)
        self.assertIn("p.location_source === 'facility'", src)
        self.assertIn('facility_bays', src)

    def test_place_block_does_not_repeat_its_title(self):
        """블록 제목과 행 라벨이 같은 말이면 안 된다('위치/위치')."""
        src = _read(self._WIDGET_POPUP)
        body = src.split('function _plotPlaceHtml', 1)[1].split(
            '\n  // ', 1)[0]
        self.assertIn("_t('Where')", body)
        self.assertNotIn("_t('Location')", body)
        # 시설과 구역은 **두 행**이다 — 한 열에 두 정보를 이어붙이지 않는다.
        self.assertIn("_t('Facility')", body)
        self.assertIn("_t('Zone')", body)
        self.assertNotIn("' · '", body)

    def test_facility_modal_shows_what_is_growing(self):
        """시설(구역) 모달의 [현황]에 식생 블록이 있는가 — 제어 → 식생 방향.

        서버가 런타임에 `plots` 를 실어도 **그리는 코드가 없으면 화면에는
        아무것도 없다.** 실제로 그 상태로 한 번 "구현했다" 고 보고했다
        (2026-08-19) — API 까지만 만들고 위젯을 건드리지 않았다.
        """
        popup = _read(self._WIDGET_POPUP)
        self.assertIn('function buildFacilityPlotsHtml(', popup)
        self.assertIn('buildFacilityPlotsHtml: buildFacilityPlotsHtml', popup)

        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('_appendFacilityPlots(uid, facilityUuid, pane)', widget)
        self.assertIn('rt.plots', widget)

    def test_bay_view_includes_whole_facility_plots(self):
        """구역 뷰에서 "시설 전체" 구획도 보여야 한다 — 그 작물도 거기 자란다.

        서버 `plots_in_facility` 와 **같은 규칙**이어야 한다. 한쪽만 고치면
        같은 구역이 화면과 API 에서 다른 목록을 갖는다.
        """
        popup = _read(self._WIDGET_POPUP)
        body = popup.split('function buildFacilityPlotsHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('!bayId || !p.bay_id || p.bay_id === bayId', body)
        # 구역 뷰에서 시설 전체인 것은 그렇다고 밝힌다 — 아니면 이 구역 전용으로 읽힌다.
        self.assertIn("_t('Whole facility')", body)

    def test_widget_can_create_a_facility_plot(self):
        """위젯에서 **새로 심을 수 있어야** 한다.

        시설 구획은 기하를 그리지 않으므로 지도 위젯에서 만들 수 있다. 이것이
        없으면 구획이 하나도 없는 시설은 위젯에서 손댈 것이 아무것도 없고,
        시설 편집기(geo/facility)까지 갈 수 있는 계정만 온실 식생을 관리하게
        된다 — 지도만 쓰는 사람에게는 기능이 없는 것과 같다.
        """
        popup = _read(self._WIDGET_POPUP)
        body = popup.split('function buildFacilityPlotsHtml', 1)[1].split(
            '\n  function ', 1)[0]
        # 비어 있어도 권한이 있으면 블록을 낸다 — 아니면 버튼이 나타날 자리가 없다.
        self.assertIn('!items.length && !opts.canEdit', body)
        self.assertIn('aot-ov-plot-add', body)
        # 구역 칸은 공용 폼이 낸다(`target: 'facility'` 일 때만).
        self.assertIn("target: 'facility'", body)
        form = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                                  'aot-plot-form.js'))
        self.assertIn("key: 'bay_id'", form)
        self.assertIn("when: 'facility'", form)

        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('_wireFacilityPlotAdd', widget)
        self.assertIn("'/api/geo/plot'", widget)
        # 권한 축은 시설 [현황]과 같아야 한다(둘 다 edit_settings) — 버튼이
        # 보이는데 저장이 403 이면 그게 더 나쁘다.
        # 권한 축은 **작기 운영**(edit_plots, p6_51)이다 — 시설 설정(대표 센서
        # 선택 등)과 다른 축이라, 예전처럼 같은 플래그를 쓰면 작기만 맡기려 해도
        # 시설 설정이 함께 열린다.
        self.assertIn('rt.can_edit_plots', widget)

    def test_periodic_refresh_does_not_wipe_the_plot_form(self):
        """[현황]은 30초마다 통째로 다시 그려진다 — 작성 중인 폼이 사라지면 안 된다.

        처음에는 "버튼이 안 먹는다" 로 보인다(폼을 열자마자 갱신이 지운다).
        `_ovEditing`(설명 편집)과 **따로** 둔다: 동시에 열릴 수 있고, 한쪽을 닫을
        때 다른 쪽 보호까지 풀리면 안 된다.
        """
        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('if (st._plantEditing) return;', widget)
        self.assertIn('st._plantEditing = on;', widget)
        # 팝업이 닫히면 잠금도 풀려야 한다 — 아니면 다음에 열었을 때 갱신이 멈춘다.
        self.assertIn('st2._plantEditing = false;', widget)

    def test_polling_does_not_repaint_unchanged_blocks(self):
        """[현황]은 위젯 폴링 주기(기본 5초)마다 불린다 — 값이 그대로면 DOM 도 그대로.

        예전에는 매번 `innerHTML` 을 통째로 갈아끼워 **아무것도 안 바뀌어도 모달이
        계속 깜빡였다.** 실측(2026-08-19): 44초 동안 DOM 변경 15건 이상 → 고친 뒤
        같은 조건에서 0건, 실제로 구획이 하나 추가된 순간에만 2건.
        """
        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        # [현황] 본문 · 환경 · 식생 · 기록 네 자리 모두 같으면 손대지 않는다.
        # 넷 다 **지난번에 만든 문자열**과 견준다 — 이유는
        # `test_comparison_is_build_to_build_not_against_the_live_dom` 참조.
        self.assertIn('var ovSame = (st2._ovHtml === ovHtml)', widget)
        self.assertIn('if (!ovSame)', widget)
        self.assertIn('if (pane._aotEnvNowHtml === html) return;', widget)
        self.assertIn('if (pane._aotPlotsHtml === html) return;', widget)
        self.assertIn('if (pane._aotRecordHtml === html) return;', widget)

    def test_comparison_parses_before_comparing(self):
        """문자열 HTML 과 DOM 의 `outerHTML` 을 직접 비교하면 안 된다.

        브라우저가 파싱하며 속성 순서·따옴표·`style` 표기를 정규화하므로
        (`display:none` → `display: none;`), 내용이 같아도 **항상 다르다** —
        비교를 넣어도 매번 교체돼 깜빡임이 그대로다(실제로 그렇게 한 번 고쳤다).
        """
        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('function _parseNode(html)', widget)
        # 원본 문자열과 DOM 을 직접 비교하던 형태가 되살아나면 잡는다.
        self.assertNotIn('existing.outerHTML === html', widget)
        self.assertNotIn('cur.outerHTML === html', widget)

    def test_comparison_is_build_to_build_not_against_the_live_dom(self):
        """**깜빡임이 되살아났던 진짜 이유.**

        예전 가드는 갓 만든 노드를 **현재 DOM**(`cur.outerHTML` 등)과 견줬다.
        그 자체로는 옳았는데, 나중에 들어온 사용자 지정 이름 번역
        (`aot-user-i18n.js`, p6_53)이 전제를 깨뜨렸다 — 그 층은 우리가 쓴
        **직후** 텍스트 노드를 번역본으로 바꿔 놓는다. 그래서 현재 DOM 은 늘
        번역본이고 새로 만든 HTML 은 늘 원문이라 **영원히 다르다고 나오고**,
        가드가 있는데도 매 폴링(5초)마다 통째로 교체됐다.

        사용자가 본 화면이 정확히 그 조합이다(사이트 언어 한국어 + 이름 번역
        켜짐): 5초마다 원문이 잠깐 보였다가 번역본으로 바뀌는 것이 깜빡임의
        정체였다. 번역을 끄면 안 보이니 재현 조건이 좁아 오래 남았다.

        그래서 비교는 **원문 대 원문**(지난번에 우리가 만든 문자열)으로 한다 —
        번역기가 DOM 을 어떻게 바꾸든 영향받지 않는다.
        """
        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        # 폴링이 다시 그리는 자리는 전부 이 규칙을 지난다.
        self.assertIn('function _setHtmlIfChanged(el, html)', widget)
        self.assertIn('if (el._aotLastHtml === html) return false;', widget)
        # 살아 있는 DOM 과 견주는 형태가 되살아나면 잡는다 — 번역을 켜는 순간
        # 조용히 무력해지는 비교다.
        for dead in ('cur.outerHTML === node.outerHTML',
                     'existing.outerHTML === block.outerHTML',
                     'slot.outerHTML === node.outerHTML'):
            self.assertNotIn(dead, widget,
                             '살아 있는 DOM 과 견주면 번역이 켜진 화면에서 무력하다: %s'
                             % dead)
        # 기록은 DOM 속성이 아니라 JS 프로퍼티에 둔다 — 속성으로 두면 그 쓰기
        # 자체가 또 하나의 변경이 되어 번역기의 관찰자를 깨운다.
        self.assertNotIn("setAttribute('data-aot-last-html'", widget)

    def test_async_note_list_is_excluded_from_the_comparison(self):
        """노트 목록은 비동기로 채워진다 — 비교에 넣으면 무한 재교체가 된다.

        `buildRecordBlock` 은 그 자리를 '…' 로 두고 나중에 채우므로, 새 HTML 과
        화면이 늘 달라 폴링마다 교체 → 노트 재로딩 → 다시 교체가 반복된다.
        지금 화면의 노트를 새 노드에 옮겨 심고 비교한다(교체할 때도 살아남는다).
        """
        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('newList.innerHTML = curList.innerHTML', widget)

        # 공용 노트 블록도 같은 내용이면 되쓰지 않는다 — `innerHTML` 대입은
        # 내용이 같아도 자식을 전부 갈아끼운다.
        shared = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                                    'sensor-label.js'))
        self.assertIn("listEl.innerHTML !== cache.html", shared)

    def test_design_form_can_pick_a_program(self):
        """geo/design 에서 만든 구획도 프로그램을 붙일 수 있어야 한다.

        여기만 빠지면 "지도에서 그린 구획" 과 "시설/위젯에서 만든 구획" 이 서로
        다른 기능을 갖게 된다 — 같은 것을 만드는 두 경로가 다르게 동작하는 것은
        이 저장소가 반복해서 겪은 실패다.
        """
        src = _read(self._DESIGN_VEG)
        # 폼 마크업은 공용 컴포넌트가 낸다 — 이 화면은 그것을 쓴다는 사실과
        # 목록을 어떻게 가져오는지만 갖는다.
        self.assertIn("attr: 'data-veg-field'", src)
        form = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                                  'aot-plot-form.js'))
        self.assertIn("key: 'program_uuid'", form)
        # 그 구획의 종류로 묻는다 — 박아 두면 다른 종류가 섞인다.
        self.assertIn("'/api/geo/programs?kind=' + encodeURIComponent(", src)
        self.assertNotIn('programs?kind=vegetation', src)

    def test_ai_can_attach_a_program_when_creating(self):
        """도구 설명이 "program_id 로 넘긴다" 고 적고 실제로 안 받으면 거짓말이다."""
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S
        sig = inspect.signature(S.create_plot)
        self.assertIn('program_id', sig.parameters)

        src = _read(os.path.join(_ROOT, 'ai', 'services', 'aot_data_tool_service.py'))
        body = src.split('def modify_plot', 1)[1].split('\n    @staticmethod', 1)[0]
        self.assertIn("'program_uuid'", body)

    def test_design_page_does_not_draw_facility_plots(self):
        """편집기는 **편집할 수 있는 것만** 그린다.

        시설 구획은 기하가 없어 여기서 옮기거나 고칠 수 없다. 그려 두면 사람이
        그렇게 하려 든다 — 파생 기하 폴백을 이 파일에 넣지 말 것.
        """
        src = _read(self._DESIGN_VEG)
        self.assertIn('if (!plot || !plot.feature) return null;', src)
        # 주석에는 나온다(왜 안 그리는지 적혀 있다) — 막는 것은 **사용**이다.
        self.assertNotIn('.derived_feature', src)

class TestProgram(unittest.TestCase):
    """재배 프로그램(P1) — 템플릿과 인스턴스, 버전 고정.

    이 레이어가 막으려는 것은 "작물 지식이 네 곳에 흩어져 서로 모르는" 상태였다
    (STAGE_DURATION_MAP=AI 전용 · setpoint 캐시=AI 전용 · FunctionCropPreset=제어
    전용 · Method=사람이 수작업). 지금은 이 표가 정본이고 나머지는 템플릿 재료다.
    여기서 고정하는 계약 중 **깨져도 조용한 것**:

    - 구획이 버전을 고정하지 않으면, 프로그램을 고치는 순간 진행 중인 작기의
      "그때 무엇을 목표로 길렀나" 가 소급해서 바뀐다. 에러는 나지 않는다.
    - `source='ai'` 인 프로그램이 검토 없이 제어에 쓰이면, 지어낸 단계 기간과
      목표 온도가 곧바로 온실 설정이 된다.
    - 내장/외부 프로그램을 사람이 직접 고칠 수 있으면 업그레이드·외부 갱신이
      그 수정을 덮어써 조용히 되돌아간다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'program.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoProgram, GeoPlot
        for model in (GeoPlot, GeoProgram):
            model.query.delete()
        db.session.commit()

    def _program(self, subject='tomato', variety=None, source='builtin',
                 stages=None, version=1, reviewed=None, kind='vegetation'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoProgram
        row = GeoProgram(
            name='%s 표준' % subject, subject=subject, variety=variety,
            source=source, kind=kind,
            version=version, reviewed_at=reviewed,
            stages=stages if stages is not None else [
                {'key': 'seedling', 'name': '육묘기', 'days': 21},
                {'key': 'vegetative', 'name': '영양생장기', 'days': 35},
                {'key': 'harvest', 'name': '수확기', 'days': None},
            ])
        db.session.add(row)
        db.session.commit()
        return row

    def _plant(self, **over):
        from aot.aot_flask.geo import plot_io
        payload = {'map_uuid': 'map-p', 'subject': '토마토',
                   'started_on': date.today().isoformat(),
                   'feature': {'type': 'Feature', 'properties': {},
                               'geometry': _square(0.0, 0.0, 0.001)}}
        payload.update(over)
        return plot_io.save_plot(payload)

    # ── 버전 고정 ───────────────────────────────────────────────────────
    def test_plot_pins_the_program_version(self):
        prog = self._program()
        row, err = self._plant(program_uuid=prog.unique_id)
        self.assertIsNone(err)
        self.assertEqual(row['program']['version'], 1)

    def test_confirming_a_stage_moves_the_anchor(self):
        """승인은 기록이 아니라 **보정**이다.

        확인한 날부터 남은 단계를 다시 계산하지 않으면, 승인은 아무것도 바꾸지
        않는 체크박스가 된다 — 그런 기능은 만들지 않는 편이 낫다.
        """
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': 10},
            {'key': 's3', 'name': '3', 'days': None}])
        saved, err = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=25)).isoformat())
        self.assertIsNone(err)
        uid = saved['unique_id']
        from aot.databases.models import GeoPlot
        row = GeoPlot.query.filter_by(unique_id=uid).first()

        # 원장이 비면 지금까지와 똑같이 파생한다 — 26일차면 3단계.
        self.assertEqual(plot_context.stage_of(row)['key'], 's3')
        self.assertIsNone(plot_context.stage_anchor(row))

        # 2단계가 **5일 전에** 시작됐다고 확인하면 거기서부터 다시 센다.
        ev, err2 = plot_io.accept_stage(
            uid, stage_key='s2',
            started_on=(date.today() - timedelta(days=5)).isoformat(),
            source='days', decided_by='tester')
        self.assertIsNone(err2)
        st = plot_context.stage_of(row)
        self.assertEqual(st['key'], 's2')
        # 순번은 **전체 기준**이다 — 잘린 구간 기준이면 "2단계 (1/2)" 로 보인다.
        self.assertEqual(st['index'], 2)
        self.assertEqual(st['total'], 3)

    def test_undo_keeps_the_row_and_restores_the_previous_anchor(self):
        """행을 지우면 '누가 언제 확인했다가 물렀다' 가 사라진다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io
        from aot.databases.models import GeoPlot

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': None}])
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=20)).isoformat())
        uid = saved['unique_id']
        row = GeoPlot.query.filter_by(unique_id=uid).first()
        plot_io.accept_stage(uid, stage_key='s2',
                             started_on=date.today().isoformat(),
                             decided_by='tester')
        self.assertIsNotNone(plot_context.stage_anchor(row))

        out, err = plot_io.undo_stage(uid, decided_by='tester')
        self.assertIsNone(err)
        self.assertIsNone(plot_context.stage_anchor(row))
        hist = plot_context.stage_history(row)
        self.assertEqual(len(hist), 1)            # 지우지 않았다
        self.assertTrue(hist[0]['undone'])

    def test_going_backwards_is_refused(self):
        """뒤로 가는 전환은 되돌리기로만 한다 — 여기로도 되면 원장에 앞뒤가
        섞여 기준점이 어디인지 추적할 수 없다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_io

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': 10},
            {'key': 's3', 'name': '3', 'days': None}])
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=25)).isoformat())
        uid = saved['unique_id']
        plot_io.accept_stage(uid, stage_key='s3',
                             started_on=date.today().isoformat())
        out, err = plot_io.accept_stage(uid, stage_key='s2',
                                        started_on=date.today().isoformat())
        self.assertIsNone(out)
        self.assertIn('되돌리기', err or '')

    def test_no_proposal_until_the_ledger_has_a_row(self):
        """기존 구획 전부에 소급해서 '승인하세요' 를 띄우지 않는다.

        승인은 사람이 한 번 누른 시점부터 의미를 갖는다.
        """
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 5},
            {'key': 's2', 'name': '2', 'days': None}])
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=20)).isoformat())
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertIsNone(plot_context.stage_proposal(row))

    def test_pending_transition_is_not_stored(self):
        """대기 중 전환을 행으로 만들면 프로그램 수정·GDD 변화에 조용히 낡는다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_context.py'))
        body = src.split('def stage_proposal', 1)[1].split('\ndef ', 1)[0]
        for w in ('db.session.add', 'db.session.commit'):
            self.assertNotIn(w, body)

    def test_ai_manifest_names_match_the_handlers(self):
        """매니페스트가 시키는 인자 이름이 핸들러가 받는 이름이어야 한다.

        `crop`→`subject` 로 옮기고 매니페스트를 안 고쳐서, LLM 은 `crop` 을
        넘기라는 안내를 읽고 그대로 넘겼다 — `create_plot` 은 "subject
        required" 로 실패하고 `modify_plot` 은 **아무것도 안 바꾸고 success** 를
        돌려줬다. 문서가 거짓말을 하면 도구는 있으나 마나다.
        """
        import inspect
        from aot.ai.services import tool_registry as R
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        src = _read(os.path.join(_ROOT, 'ai', 'services', 'tool_registry.py'))
        # 구획 도구의 매니페스트에 옛 이름이 남아 있으면 안 된다.
        for bad in ('"required": ["crop", "started_on"]',
                    '"required": ["zone_id", "crop", "started_on"]'):
            self.assertNotIn(bad, src)

        # 핸들러가 실제로 받는 이름인지 확인한다.
        for tool, must in (('create_plot', ('subject', 'kind', 'program_id')),
                           ('confirm_plot_stage', ('plot_id', 'stage_key',
                                                   'started_on')),
                           ('apply_plot_resources', ('plot_id',)),
                           ('undo_plot_stage', ('plot_id',))):
            fn = getattr(S, tool)
            params = set(inspect.signature(fn).parameters)
            for name in must:
                self.assertIn(name, params, '%s 가 %s 를 안 받는다' % (tool, name))

    def test_modify_plot_refuses_a_no_op(self):
        """알아듣지 못한 인자에 success 를 돌려주면 AI 는 바꿨다고 보고하고
        사용자는 반영된 줄 안다 — 이 저장소가 반복해서 겪은 계열이다."""
        src = _read(os.path.join(_ROOT, 'ai', 'services',
                                 'aot_data_tool_service.py'))
        body = src.split('def modify_plot', 1)[1].split('\n    @staticmethod', 1)[0]
        self.assertIn('nothing to change', body)
        self.assertIn('unknown field', body)

    def test_stage_tools_are_gated(self):
        """단계 확정은 기준점을 옮기고, 자원 적용은 물이 나온다."""
        from aot.ai.services import tool_registry as R

        approval = set(R.approval_required_tools())
        for t in ('confirm_plot_stage', 'undo_plot_stage',
                  'apply_plot_resources'):
            self.assertIn(t, approval, '%s 가 승인 대상이 아니다' % t)
        # 자원 적용은 물리 행위다 — `activate_function` 과 같은 무게로 둔다.
        src = _read(os.path.join(_ROOT, 'ai', 'services', 'tool_registry.py'))
        decl = src.split("Tool('apply_plot_resources'", 1)[1][:200]
        self.assertIn('physical=True', decl)

    def test_stage_editor_fits_a_fixed_width_drawer(self):
        """단계 편집이 드로어(520px 고정) 안에 들어가야 한다.

        처음에는 5열 표였는데 `grid-template-columns` 는 4트랙이었다 — 다섯
        번째가 암시적 트랙으로 밀려 [목표]·[×] 가 화면 밖 253px 에 놓였고,
        `overflow-x: hidden` 이라 스크롤로도 못 갔다. **목표·자원을 아예 설정할
        수 없었고 단계 삭제도 안 됐다.**

        그래서 표를 버리고 접히는 항목으로 갔다가(2026-08-20), 다시 **트랙**
        으로 갔다(2026-08-21): 가로 막대(비율)와 세로 목록(편집)이 같은 것을 두
        방향으로 두 번 그리고 있었고, 여섯 단계가 세로 공간을 전부 차지했다.
        지금은 막대의 구간이 곧 메뉴이고 **고른 단계 하나만** 아래에 그린다.

        여기서 고정하는 것은 "다열 표로 돌아가지 않는다" 와 "단계마다 한 벌씩
        DOM 을 만들지 않는다" 둘이다.
        """
        css = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'pages',
                                 'geo-program.css'))
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        # 다열 표를 되살리지 않는다.
        self.assertNotIn('.veg-stage-head', css)
        self.assertNotIn('veg-stage-row', js)
        # 트랙이 메뉴다 — 구간을 고르고 끌 수 있어야 한다.
        self.assertIn('aot-stage-seg', js)
        self.assertIn("data-act=\"stage-pick\"", js)
        # 순서는 **끌어서** 바꾼다. HTML5 네이티브 DnD 는 쓰지 않는다 — 터치에서
        # 안 되고(폰에서 순서를 못 바꾸면 절반만 있는 기능이다), 위젯·팝업
        # 안에서 시작조차 안 되는 경우가 있다. 이 저장소가 이미 그렇게 정했다
        # (`widgets/AoT_facility/aot-actuator-order.js`).
        self.assertNotIn('draggable="true"', js)
        self.assertIn("addEventListener('touchstart'", js)
        self.assertIn("addEventListener('touchmove'", js)
        # 단계 패널은 **한 벌**이다(고른 것만 그린다).
        self.assertIn('function _stagePanel()', js)
        self.assertNotIn('function _stageRow(', js)
        # 그래서 편집 중인 값의 정본은 DOM 이 아니라 State 다.
        self.assertIn('function _readStagePanel(', js)
        self.assertIn('State.stages', js)

    def test_stage_editor_does_not_branch_on_viewport(self):
        """드로어는 1440px 화면에서도 520px 다 — 좁은 것은 뷰포트가 아니라
        드로어라, 뷰포트 브레이크포인트는 데스크탑에서 영영 걸리지 않는다."""
        import re
        css = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'pages',
                                 'geo-program.css'))
        # 주석 안의 `@media` 는 "예전에 이랬다" 는 설명이다 — 규칙만 본다.
        stripped = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        self.assertNotIn('@media', stripped)

    def test_add_selector_uses_the_app_dropdown(self):
        """`aot-standard-select` 는 **`selectpicker` 와 한 쌍**이다.

        그 CSS 는 `.bootstrap-select.aot-standard-select` 를 겨냥하므로,
        selectpicker 없이 원본 select 에만 붙이면 스타일이 하나도 안 걸리고
        브라우저 기본 드롭다운이 뜬다 — 앱의 다른 목록(function·output·camera)과
        생김새도 동작도 갈린다.
        """
        html = _read(os.path.join(_ROOT, 'aot_flask', 'templates', 'pages',
                                  'geo', 'programs.html'))
        block = html.split('id="veg-base"', 1)[0][-260:] + \
                html.split('id="veg-base"', 1)[1][:260]
        self.assertIn('selectpicker', block)
        self.assertIn('aot-standard-select', block)

    def test_add_selector_is_refreshed_after_refill(self):
        """selectpicker 는 원본 select 를 **복제해** 자기 목록을 그린다.

        `innerHTML` 을 갈아끼운 뒤 알리지 않으면 화면에는 옛 목록("불러오는
        중…")이 그대로 남는다 — 값은 바뀌는데 보이는 것만 낡는 종류라
        알아채기 어렵다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        body = js.split('function renderBase', 1)[1].split('\n  function ', 1)[0]
        self.assertIn("selectpicker('refresh')", body)

    def test_program_card_follows_the_input_card(self):
        """카드에 버튼을 늘리지 않는다 — 좁은 화면에서 밀리는 것은 버튼 수다.

        input 카드와 같은 골격: 드래그 핸들 · 이름 · 부가정보 · 톱니 하나.
        삭제·복제는 드로어 푸터로 내린다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        html = _read(os.path.join(_ROOT, 'aot_flask', 'templates', 'pages',
                                  'geo', 'programs.html'))
        self.assertIn('aot-entry-drag-handle', js)
        self.assertIn('fa-grip-lines', js)
        self.assertIn('fa-cog', js)
        # 카드에서 삭제·복제 버튼을 없앴다(푸터로 옮겼다).
        card = js.split('function _rowHtml', 1)[1].split('\n  /**', 1)[0]
        self.assertNotIn("data-act=\"delete\"", card)
        self.assertNotIn("data-act=\"copy\"", card)
        self.assertIn('veg-drawer-del', html)
        self.assertIn('veg-drawer-copy', html)
        # 이름 앞 배지 금지 — 한 열에는 한 정보만.
        self.assertNotIn('_sourceBadge', js)

    def test_program_never_switches_functions_itself(self):
        """프로그램이 함수를 스스로 켜고 끄지 않는다.

        관수를 켜는 것은 물이 나오는 일이고, 이 저장소는 이미
        `activate_function` 을 승인 대상(`mutating=True`)으로 두고 있다. 목표값도
        아직 표시 전용인 마당에 자원만 자동으로 물리 동작을 하면 앞뒤가 맞지 않고,
        P7(자동 승인)과 겹치면 "단계가 저절로 넘어가고 그 순간 관수가 켜진다" 가
        된다 — 그것은 **다른 결정**이다.
        """
        io_src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_io.py'))
        # 자동 승인 경로에는 자원 적용이 붙어 있지 않다.
        auto = io_src.split('def auto_advance_stage', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn('apply_stage_resources', auto)
        # 단계 확인 경로에도 붙어 있지 않다.
        accept = io_src.split('def accept_stage', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn('_set_function_activation', accept)

    def test_apply_touches_only_declared_functions(self):
        """선언에 없는 함수를 끄지 않는다 — 프로그램은 농장 전체의 함수 목록을
        알지 못한다."""
        io_src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_io.py'))
        body = io_src.split('def apply_stage_resources', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('activate=True', body)
        self.assertNotIn('activate=False', body)

    def test_apply_does_not_trust_a_success_shaped_reply(self):
        """`{"status": "success"}` 를 무조건 믿지 않는다 — 이 저장소가 겪은
        "성공이라고 답하는데 안 돈 것" 계열이다."""
        io_src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_io.py'))
        body = io_src.split('def apply_stage_resources', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("res.get('error')", body)

    def test_missing_resource_is_shown_not_dropped(self):
        """조용히 빼면 그 단계에서 자원이 통째로 사라진 것을 아무도 모른다.

        P6 재설계로 자리가 옮겨졌다 — 예전에는 "죽은 함수 참조" 를 남겼고, 이제는
        "선언한 역할을 맡을 함수가 이 자리에 없다" 를 남긴다. 원칙은 같다.
        """
        from aot.aot_flask.geo.plot_context import stage_resources

        prog = self._program(source='user')
        prog.resource_defs = [{'role': 'irrigation', 'default': True}]
        out = stage_resources({'key': 'a'}, prog, None)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['role'], 'irrigation')
        self.assertFalse(out[0]['found'])
        # 노지 구획(시설 없음)은 아직 현장 어휘가 없다 — 이유를 밝힌다.
        self.assertEqual(out[0]['reason'], 'no-facility')
        self.assertIsNone(out[0]['active'])

    def test_stage_can_turn_a_declared_role_off(self):
        """단계가 끈 역할은 목록에 나오지 않는다 — 그 단계에는 요구가 없다."""
        from aot.aot_flask.geo.plot_context import stage_resources

        prog = self._program(source='user')
        prog.resource_defs = [{'role': 'irrigation', 'default': True}]
        self.assertEqual(
            stage_resources({'key': 'a', 'resources': {'irrigation': False}},
                            prog, None), [])

    def test_declared_role_says_where_it_came_from(self):
        """밝히지 않으면 "이 단계에서 일부러 끈 것" 과 "원래 안 쓰는 것" 을
        사람이 구분할 수 없다."""
        from aot.aot_flask.geo.plot_context import declared_roles

        prog = self._program(source='user')
        prog.resource_defs = [{'role': 'irrigation', 'default': False}]
        self.assertEqual(declared_roles({'key': 'a'}, prog), [])
        self.assertEqual(
            declared_roles({'key': 'a', 'resources': {'irrigation': True}},
                           prog),
            [{'role': 'irrigation', 'source': 'stage'}])

    def test_field_resolves_the_role_to_its_own_function(self):
        """**같은 프로그램이 자리마다 다른 함수를 쓴다** — 이것이 재설계의 요지다.

        프로그램에는 함수 uuid 가 없고, 시설의 관수 피팅이 켜는 출력을 되짚어
        함수를 찾는다. 그래서 두 번째 온실에서 같은 프로그램을 써도 복제할
        필요가 없다.
        """
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo.plot_context import functions_for_role
        from aot.databases.models import (Actions, GeoFacility, GeoPlot,
                                          Output, Trigger)

        trg = Trigger(name='A동 관수', trigger_type='trigger_run_pwm_method')
        db.session.add(trg)
        db.session.add(Output(unique_id='out-A', name='A동 밸브',
                              output_type='virtual_on_off_single'))
        db.session.commit()
        db.session.add(Actions(function_id=trg.unique_id,
                               function_type='trigger', action_type='output',
                               do_unique_id='out-A,0'))
        fac = GeoFacility(name='A동', geo_id='m', shape_uuid='shape-A',
                          fittings=[{'id': 'f1', 'kind': 'irrigation_valve',
                                     'actuator_id': 'out-A'}])
        db.session.add(fac)
        db.session.commit()
        plot = GeoPlot(geo_id='m', kind='vegetation', subject='상추',
                       source_kind='facility', facility_uuid=fac.unique_id,
                       started_on=date.today())
        db.session.add(plot)
        db.session.commit()

        fns, reason = functions_for_role('irrigation', plot)
        self.assertEqual(reason, 'ok')
        self.assertEqual([f['name'] for f in fns], ['A동 관수'])

    def test_role_without_field_vocabulary_says_so(self):
        """시비는 시설 설계기에 fitting 종류가 아직 없다. 없는 어휘를 지어내지
        않고 이유를 낸다 — 지어내면 실제 배관과 무관한 분류가 데이터에 남는다."""
        from aot.aot_flask.geo.plot_context import functions_for_role

        fns, reason = functions_for_role('fertigation', None)
        self.assertEqual(fns, [])
        self.assertEqual(reason, 'no-vocabulary')

    def test_resource_roles_start_narrow(self):
        """어휘는 한 번 퍼지면 되돌리기 어렵다 — `other` 로 담고 나중에 이름을
        준다(`GeoProgram.kind` 와 같은 태도)."""
        from aot.aot_flask.geo.program_io import _RESOURCE_ROLES
        self.assertEqual(_RESOURCE_ROLES,
                         ('irrigation', 'fertigation', 'other'))

    # ── 자원 역할 선언 (P6 재설계, 2026-08-20) ──────────────────────────
    # 프로그램은 함수를 가리키지 않는다. 계획이 현장을 미리 지정하면 충돌을 풀
    # 방법이 없고, 같은 프로그램을 두 번째 자리에서 쓰려면 복제해야 해서 작물
    # 지식이 두 벌이 된다.

    def test_program_declares_roles_not_function_ids(self):
        """프로그램에 함수 uuid 가 들어갈 자리가 없다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': '역할선언', 'subject': 'tomato',
            'resource_defs': [{'role': 'irrigation'}],
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}]})
        self.assertIsNone(err)
        self.assertEqual(out['resource_defs'],
                         [{'role': 'irrigation', 'default': True}])
        # 프로그램 응답 어디에도 함수 uuid 가 없다.
        self.assertNotIn('functions', out)

    def test_unknown_role_is_refused(self):
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'tomato',
            'resource_defs': [{'role': 'lighting'}],
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}]})
        self.assertIsNone(out)
        self.assertIn('lighting', err or '')

    def test_stage_overrides_only_declared_roles(self):
        """정의에 없는 역할을 단계가 켜면 화면에 그릴 근거가 없다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'tomato',
            'resource_defs': [{'role': 'irrigation'}],
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'resources': {'fertigation': True}}]})
        self.assertIsNone(out)
        self.assertIn('fertigation', err or '')

    def test_stage_can_switch_a_role_off(self):
        """"이 단계는 쓰지 않는다" 와 "기본값을 따른다" 는 다른 사실이다 —
        수확 전 단수(斷水)를 빈 칸으로 표현하면 실수와 구분되지 않는다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'tomato',
            'resource_defs': [{'role': 'irrigation', 'default': True}],
            'stages': [{'key': 'a', 'name': 'a', 'days': 10},
                       {'key': 'b', 'name': 'b', 'days': None,
                        'resources': {'irrigation': False}}]})
        self.assertIsNone(err)
        self.assertNotIn('resources', out['stages'][0])   # 기본값을 따른다
        self.assertEqual(out['stages'][1]['resources'], {'irrigation': False})

    def test_legacy_function_ids_are_kept_not_dropped(self):
        """p6_48 이전의 함수 uuid 는 "이 함수가 그 자리에 배치돼야 한다" 는
        정보다. 읽는 쪽은 안 보지만 조용히 버리지 않는다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'functions': [{'id': 'legacy-uuid',
                                       'role': 'irrigation'}]}]})
        self.assertIsNone(err)
        self.assertEqual(out['stages'][0]['functions'],
                         [{'id': 'legacy-uuid', 'role': 'irrigation'}])

    def test_resource_defs_survive_a_partial_save(self):
        """키가 없으면 기존 값을 지킨다 — 부분 저장 규칙."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'tomato',
            'resource_defs': [{'role': 'irrigation'}],
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}]})
        self.assertIsNone(err)
        same, err = program_io.update_program(out['unique_id'],
                                              {'name': '새 이름'})
        self.assertIsNone(err)
        self.assertEqual(same['resource_defs'],
                         [{'role': 'irrigation', 'default': True}])

    def test_auto_advance_is_off_by_default(self):
        """켜져 있는 것이 기본이면 사람이 아무 결정도 하지 않았는데 단계가 스스로
        넘어간다 — 업그레이드로 그렇게 되면 특히 나쁘다."""
        saved, _ = self._plant()
        from aot.databases.models import GeoPlot
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertFalse(bool(row.auto_advance))

    def test_auto_advance_lives_on_the_plot_not_the_program(self):
        """P8 — 자동 승인이 묻는 것은 "이 자리를 사람 눈 없이 믿을 수 있는가" 다.

        프로그램에 두면 같은 작물의 두 구획을 나눌 방법이 없고, 나누려면 작물
        지식을 한 벌 더 복제하게 된다. 양쪽에 두면 "왜 넘어갔나" 의 답이 두 곳이
        된다 — 그래서 프로그램에는 **없어야** 한다.
        """
        from aot.databases.models import GeoPlot, GeoProgram
        self.assertFalse(hasattr(GeoProgram, 'auto_advance'))
        self.assertTrue(hasattr(GeoPlot, 'auto_advance'))

    def test_auto_advance_records_and_is_idempotent(self):
        from datetime import timedelta
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_context, plot_io
        from aot.databases.models import GeoPlot

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': 10},
            {'key': 's3', 'name': '3', 'days': None}])
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=25)).isoformat())
        uid = saved['unique_id']
        plot_io.accept_stage(uid, stage_key='s1',
                             started_on=(date.today()
                                         - timedelta(days=25)).isoformat())

        # 꺼져 있으면 아무것도 하지 않는다.
        self.assertEqual(plot_io.auto_advance_stage(uid), [])

        row = GeoPlot.query.filter_by(unique_id=uid).first()
        row.auto_advance = True
        db.session.commit()
        out = plot_io.auto_advance_stage(uid)
        self.assertTrue(out)
        # 같은 읽기가 두 번 들어와도 두 줄이 되지 않는다(동시 읽기 방어).
        self.assertEqual(plot_io.auto_advance_stage(uid), [])

        row = GeoPlot.query.filter_by(unique_id=uid).first()
        hist = [h for h in plot_context.stage_history(row) if not h['undone']]
        self.assertEqual(len(hist), 2)
        # 자동으로 남은 줄인지 구분된다 — `decided_by` 가 비었다는 것만으로는
        # "로그인 정보가 없는 사람" 과 구분되지 않는다.
        self.assertTrue(hist[-1]['auto'])

    def test_auto_advance_catches_up_more_than_one_stage(self):
        """한 줄만 적고 멈추면 3주 만에 연 구획의 이력에 구멍이 남는다.

        원장이 비어 있어도 첫 전환부터 민다 — 켜 두었는데 아무것도 기록되지
        않으면 사람은 기능이 꺼진 것으로 본다.
        """
        from datetime import timedelta
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_context, plot_io
        from aot.databases.models import GeoPlot

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': 10},
            {'key': 's3', 'name': '3', 'days': None}])
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=25)).isoformat())
        uid = saved['unique_id']
        row = GeoPlot.query.filter_by(unique_id=uid).first()
        row.auto_advance = True
        db.session.commit()

        out = plot_io.auto_advance_stage(uid)
        self.assertTrue(out, '원장이 비어 있어도 첫 전환을 기록해야 한다')
        row = GeoPlot.query.filter_by(unique_id=uid).first()
        # 25일차면 3단계다 — 확인 없이 거기까지 도달해 있어야 한다.
        self.assertEqual(plot_context.stage_of(row)['key'], 's3')
        self.assertEqual(plot_io.auto_advance_stage(uid), [])

    def test_recorded_date_does_not_depend_on_when_you_look(self):
        """자동 승인이 "오늘" 을 적으면 그 기록은 무슨 일이 있었는지가 아니라
        **언제 열어 봤는지**를 남기는 것이 된다.

        날짜는 자료에서 되짚는다 — 같은 단계가 유효한 동안 언제 관찰해도 같은
        날이 나와야 한다.
        """
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io
        from aot.databases.models import GeoPlot

        prog = self._program(stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': 10},
            {'key': 's3', 'name': '3', 'days': None}])
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() - timedelta(days=25)).isoformat())
        uid = saved['unique_id']
        plot_io.accept_stage(uid, stage_key='s1',
                             started_on=(date.today()
                                         - timedelta(days=25)).isoformat())
        row = GeoPlot.query.filter_by(unique_id=uid).first()

        seen = set()
        for back in (0, 1, 2):
            pr = plot_context.stage_proposal(
                row, on=date.today() - timedelta(days=back))
            self.assertIsNotNone(pr)
            seen.add(pr['started_on'])
        self.assertEqual(len(seen), 1, '관찰 시점에 따라 날짜가 달라진다: %s' % seen)

    def test_auto_advance_needs_a_date_it_can_defend(self):
        """되짚을 날짜가 없으면 기록하지 않고 사람에게 묻는 상태로 둔다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_io.py'))
        body = src.split('def auto_advance_stage', 1)[1]
        self.assertIn("proposal.get('started_on')", body)

    def test_auto_advance_runs_only_on_the_detail_route(self):
        """목록 조회에 넣으면 지도 한 장(수십 구획) 읽기가 그만큼 쓰기를 한다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))
        detail = src.split('def api_plot_get', 1)[1].split('\ndef ', 1)[0]
        listing = src.split('def api_plot_list', 1)[1].split('\ndef ', 1)[0] \
            if 'def api_plot_list' in src else ''
        self.assertIn('auto_advance_stage', detail)
        self.assertNotIn('auto_advance_stage', listing)

    def test_kind_reaches_the_client(self):
        """종류를 저장해 놓고 안 내보내면 화면이 프로그램을 좁힐 수 없다.

        조용한 실패다 — 목록은 정상으로 보이고, 식생 구획의 프로그램 선택지에
        가축 프로그램이 섞여 있을 뿐이다.
        """
        row, err = self._plant()
        self.assertIsNone(err)
        self.assertEqual(row.get('kind'), 'vegetation')

    def test_program_of_another_kind_is_refused(self):
        """식생 구획에 가축 프로그램이 붙으면 단계·목표 해석이 통째로
        엉뚱해지는데 **에러는 나지 않는다** — 붙는 순간 막는 것이 유일하게 싼
        자리다(붙은 뒤에는 어느 쪽이 틀렸는지 알 방법이 없다)."""
        prog = self._program(subject='젖소', kind='livestock')
        row, err = self._plant(program_uuid=prog.unique_id)
        self.assertIsNone(row)
        self.assertIn('종류', err or '')

    def test_changing_kind_alone_cannot_orphan_the_program(self):
        """프로그램은 그대로 두고 **종류만** 바꾸는 저장이 검사를 지나치면
        안 된다.

        붙일 때만 대조하면 이 경로가 뚫린다 — 식생 프로그램이 매달린 채 종류만
        가축이 되고, 아무 에러 없이 단계·목표 해석이 통째로 어긋난다.
        """
        prog = self._program()
        saved, err = self._plant(program_uuid=prog.unique_id)
        self.assertIsNone(err)

        from aot.aot_flask.geo import plot_io
        row, err2 = plot_io.save_plot({'unique_id': saved['unique_id'],
                                       'kind': 'livestock'})
        self.assertIsNone(row)
        self.assertIn('종류', err2 or '')

    def test_kind_can_change_when_no_program_is_attached(self):
        """거부가 종류 자체가 아니라 **짝이 어긋남** 때문인지 확인한다."""
        from aot.aot_flask.geo import plot_io
        saved, err = self._plant()
        self.assertIsNone(err)
        row, err2 = plot_io.save_plot({'unique_id': saved['unique_id'],
                                       'kind': 'livestock'})
        self.assertIsNone(err2)
        self.assertEqual(row['kind'], 'livestock')

    def test_matching_kind_is_accepted(self):
        """거부가 종류 대조 때문인지 확인한다 — 같은 종류는 그대로 붙는다."""
        prog = self._program()
        row, err = self._plant(program_uuid=prog.unique_id)
        self.assertIsNone(err)
        self.assertEqual(row['program']['unique_id'], prog.unique_id)

    def test_editing_the_program_does_not_move_a_running_plot(self):
        """프로그램을 고쳐도 진행 중인 작기의 해석은 그대로여야 한다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)

        prog.stages = [{'key': 'seedling', 'name': '육묘기', 'days': 99}]
        prog.version = 2
        db.session.commit()

        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        brief = plot_context.program_brief(row)
        self.assertEqual(brief['version'], 1)          # 고정된 버전
        self.assertEqual(brief['latest_version'], 2)
        self.assertTrue(brief['newer_version'])        # 새 버전이 있다는 **사실만**

    def test_saving_again_does_not_silently_upgrade(self):
        """저장할 때마다 최신 버전으로 끌어올리면 고정의 의미가 없다."""
        from aot.aot_flask.extensions import db

        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)
        prog.version = 3
        db.session.commit()

        again, err = self._plant(unique_id=saved['unique_id'], variety='대저')
        self.assertIsNone(err)
        self.assertEqual(again['program']['version'], 1)

        # 사람이 명시적으로 고르면 올라간다.
        upgraded, err = self._plant(unique_id=saved['unique_id'],
                                    program_uuid=prog.unique_id,
                                    program_version='latest')
        self.assertIsNone(err)
        self.assertEqual(upgraded['program']['version'], 3)

    def test_unknown_program_is_refused(self):
        row, err = self._plant(program_uuid='no-such-program')
        self.assertIsNone(row)
        self.assertIn('프로그램', err or '')

    def test_program_is_optional(self):
        """프로그램 없이도 종전대로 동작한다 — 필수가 아니다."""
        row, err = self._plant()
        self.assertIsNone(err)
        self.assertNotIn('program', row)

    def test_deleted_program_is_reported_not_hidden(self):
        """근거가 사라진 것을 조용히 빈칸으로 두지 않는다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoProgram, GeoPlot

        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)
        GeoProgram.query.filter_by(unique_id=prog.unique_id).delete()
        db.session.commit()

        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertTrue(plot_context.program_brief(row)['missing'])

    # ── 출처가 신뢰를 정한다 ────────────────────────────────────────────
    def test_ai_program_needs_review_before_control(self):
        import datetime as _dt
        ai = self._program(source='ai')
        self.assertFalse(ai.usable_for_control())
        ai.reviewed_at = _dt.datetime(2026, 8, 19)
        self.assertTrue(ai.usable_for_control())

    def test_builtin_and_external_are_read_only(self):
        """내장·외부를 직접 고치게 두면 갱신이 그 수정을 덮어쓴다."""
        self.assertFalse(self._program(source='builtin').is_editable())
        self.assertFalse(self._program(subject='cucumber',
                                       source='external').is_editable())
        self.assertTrue(self._program(subject='lettuce', source='user').is_editable())

    # ── 파생 ────────────────────────────────────────────────────────────
    def test_total_days_is_the_sum_of_stage_lengths(self):
        """`days` 는 누적이 아니라 **그 단계의 길이**다(예상 수확일의 근거)."""
        prog = self._program()
        self.assertEqual(prog.total_days(), 56)        # 21 + 35 + (끝까지)

    def test_copy_carries_the_program(self):
        from aot.aot_flask.geo import plot_io
        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)
        copy, err = plot_io.copy_plot(saved['unique_id'])
        self.assertIsNone(err)
        self.assertEqual(copy['program']['unique_id'], prog.unique_id)

    # ── P2: 단계 파생 · 예상 종료일 ──────────────────────────────────────
    def _plant_days_ago(self, days, **over):
        from datetime import timedelta
        return self._plant(started_on=(date.today() - timedelta(days=days)).isoformat(),
                           **over)

    def test_stage_follows_elapsed_days(self):
        """심은 날이 1일차 — `elapsed_days` 와 같은 기준으로 단계를 찾는다."""
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program()          # 육묘 21 · 영양생장 35 · 수확 끝까지
        for days, want, idx in ((0, 'seedling', 1),      # 1일차
                                (20, 'seedling', 1),     # 21일차 = 경계
                                (21, 'vegetative', 2),   # 22일차
                                (55, 'vegetative', 2),   # 56일차 = 경계
                                (56, 'harvest', 3)):     # 57일차 이후는 끝까지
            saved, err = self._plant_days_ago(days, program_uuid=prog.unique_id,
                                              subject='단계%d' % days)
            self.assertIsNone(err)
            row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
            st = plot_context.stage_of(row)
            self.assertEqual((st['key'], st['index']), (want, idx),
                             '%d일 경과' % days)
            self.assertEqual(st['source'], 'days')

    def test_future_plot_is_not_a_stage(self):
        """계획만 세운 구획을 "육묘기" 라 부르면 심지도 않은 것을 기르는 중으로 읽는다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id,
                               started_on=(date.today() + timedelta(days=5)).isoformat())
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        st = plot_context.stage_of(row)
        self.assertEqual(st['state'], 'not_started')
        self.assertEqual(st['days_until_start'], 5)

    def test_every_map_label_kind_is_registered(self):
        """**라벨 종류를 새로 만들면 네 표에 전부 등록해야 한다.**

        빠뜨렸을 때의 증상이 표마다 다르고 전부 조용하다:

          LABEL_Z 누락              → 다른 라벨 뒤에 깔린다(폴백이 0)
          LABEL_COLLISION_RANK 누락 → 충돌 순위가 호버 여부에 따라 튄다
          LABEL_ZOOM_GATED 누락     → **줌아웃에서도 화면을 덮는다**
          LABEL_KEYS 누락           → 라벨 컨트롤에 그 종류가 안 나온다

        자동 판정을 두지 않는 이유는 종류마다 "멀리서도 필요한 기준인가" 가
        사람이 정할 판단이기 때문이다(기본값으로 때우면 그 판단이 생략된 채
        굳는다). 대신 등록을 빠뜨린 것을 여기서 잡는다.

        실제로 셋이 빠져 있었다 — 시설 구역(bay)·구획(plot) 이 네 표 전부에서,
        센서(sensor)가 Z·RANK 두 표에서.
        """
        import re
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-widget-vector.js'))

        def _obj_keys(name):
            m = re.search(r'var %s = \{(.*?)\};' % name, js, re.S)
            self.assertIsNotNone(m, '%s 표가 사라졌다' % name)
            return set(re.findall(r"'?([A-Za-z_]+)'?\s*:", m.group(1)))

        def _arr_keys(name):
            m = re.search(r"var %s = \[(.*?)\];" % name, js, re.S)
            self.assertIsNotNone(m, '%s 목록이 사라졌다' % name)
            return set(re.findall(r"'([a-z]+)'", m.group(1)))

        z = _obj_keys('LABEL_Z')
        rank = _obj_keys('LABEL_COLLISION_RANK')
        gated = _obj_keys('LABEL_ZOOM_GATED')
        keys = _arr_keys('LABEL_KEYS')

        # 쌓임과 충돌은 **같은 종류 집합**이어야 한다(한쪽은 다른 쪽의 역순이다).
        self.assertEqual(z, rank,
                         'LABEL_Z 와 LABEL_COLLISION_RANK 의 종류가 다르다: %s'
                         % sorted(z ^ rank))
        # 컨트롤에 나오는 종류는 전부 쌓임 순서를 가져야 한다.
        self.assertFalse(keys - z, 'LABEL_Z 에 없는 종류: %s' % sorted(keys - z))
        # 줌 게이트 대상도 마찬가지.
        self.assertFalse(gated - z, 'LABEL_Z 에 없는 종류: %s' % sorted(gated - z))
        # 대지·구역은 **게이트 대상이 아니다**(멀리서 위치를 잡는 기준).
        self.assertNotIn('site', gated)
        self.assertNotIn('zone', gated)
        # 이번에 채운 것들이 되돌아가지 않게.
        for k in ('bay', 'plot', 'sensor'):
            self.assertIn(k, z, '%s 가 LABEL_Z 에서 빠졌다' % k)
            self.assertIn(k, gated, '%s 가 줌 게이트에서 빠졌다' % k)

    def test_note_pins_are_zoom_gated_like_other_labels(self):
        """노트 핀도 라벨이다 — 축척이 낮을수록 핀만 빽빽해져 지도를 덮는다.

        예전에는 `data-label-kind` 를 안 새겨 위젯의 관리(줌 게이트·쌓임·충돌)
        **밖**에 있었고, 다른 라벨이 전부 접힌 축척에서 혼자 남았다.

        충돌에서는 **살아 있는 값에 진다** — 겹치면 지금 읽어야 하는 것은
        측정값·장치 상태이고, 노트는 정적이라 줌인해서 다시 찾을 수 있다. 대신
        영역 라벨(구획·구역·대지)보다는 앞선다: 그 자리를 콕 집은 표식이라 넓은
        이름에 가려지면 찍은 뜻이 없어진다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        # 네 표 중 셋에 등록(라벨 컨트롤 행은 만들지 않는다 — 노트는 자기
        # 표시 축이 따로 있다).
        for name in ('LABEL_Z', 'LABEL_COLLISION_RANK', 'LABEL_ZOOM_GATED'):
            block = vec.split('var %s = {' % name, 1)[1].split('};', 1)[0]
            self.assertIn('note:', block, '%s 에 note 가 없다' % name)
        # 표식이 없으면 명부는 아무 일도 하지 않는다.
        self.assertIn("_wireLabelStacking(\n                                window.AoTWidgetInstances[uniqueId], el, 'note')", vec)
        # 순위: 살아 있는 값 아래, 영역 라벨 위.
        rank = vec.split('var LABEL_COLLISION_RANK = {', 1)[1].split('};', 1)[0]
        import re as _re
        vals = dict(_re.findall(r"'?([A-Za-z_]+)'?\s*:\s*([\d.]+)", rank))
        self.assertLess(float(vals['note']), float(vals['device']))
        self.assertGreater(float(vals['note']), float(vals['plot']))

    def test_bay_and_plot_labels_go_through_the_widget_gate(self):
        """라벨은 `data-label-kind` 를 새겨야 위젯의 관리(줌 게이트·쌓임·충돌)를
        받는다. 명부에 이름을 올리는 것만으로는 아무 일도 안 일어난다 — 그 값을
        읽는 요소가 없기 때문이다.

        실제로 둘이 밖에 있었다:
          구역 칩  → 'facility' 로 새겨져 시설 라벨과 한 몸이었다(따로 못 끈다)
          구획 칩  → **아무것도 안 새겼다**. 자체 줌 규칙만 있어, 시설·장치
                     라벨이 다 접힌 축척에서 홀로 남았다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        # 구역 칩은 자기 이름으로 등록한다.
        self.assertIn("_wireLabelStacking(_uidInstTop, bEl, 'bay')", vec)
        # 구획 칩도 종류를 새긴다(모듈이 달라 스택 배선을 못 부르므로 표식만).
        self.assertIn("el.dataset.labelKind = 'plot'", plot)
        self.assertIn('label_min_zoom', vec)
        for k in ('bay', 'plot'):
            self.assertRegex(vec, r'LABEL_ZOOM_GATED = \{[\s\S]{0,200}%s:' % k)
        # 시설은 L2 축(더 넓은 축척부터 계속 보임)으로 옮겨졌다(60e1671a) —
        # L1 표가 아니라 L2 표에서 찾는다.
        self.assertRegex(vec, r'LABEL_ZOOM_GATED_L2 = \{[\s\S]{0,200}facility:')

    def test_space_words_do_not_collide(self):
        """다섯 낱말이 각자 다른 것을 가리킨다 — 대지(site) · 구역(zone) ·
        시설(facility) · 동(bay) · 구획(plot). 어휘 표는 CLAUDE.md '공간 어휘'.

        섞이면 사용자가 화면마다 다른 말을 배운다. 2026-08-23 까지 실제로
        섞여 있었다:

          `Site`/`Sites`/`Site list` → "필지"  (다른 곳은 "대지")
          `Bays` → "베이 수" · `Bay Scope` → "구역(Bay) 범위"
          `Zone capacity` → "구역 총량"   ← **msgid 자체가 틀렸다**(bay 의 총량)

        ⚠ `Parcel*` 은 건드리지 않는다 — 지적도에서 주소로 불러오는 필지라
        site 와 다른 것이다.
        """
        import re
        po = _read(os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                                'LC_MESSAGES', 'messages.po'))

        def _ko(msgid):
            m = re.search(r'msgid "%s"\nmsgstr "([^"]*)"' % re.escape(msgid), po)
            return m.group(1) if m else None

        # site 는 '대지' 하나로.
        for mid in ('Site', 'Sites', 'Site list'):
            self.assertEqual('대지', (_ko(mid) or '').split()[0],
                             '%s 의 한국어가 대지가 아니다: %r' % (mid, _ko(mid)))
        # bay 는 '동'. **'구역' 이 들어가면 안 된다** — zone 이 쓰는 말이다.
        for mid in ('Bays', 'Bay Scope (optional)', 'Toggle Bay labels',
                    'Bay capacity'):
            ko = _ko(mid)
            self.assertIsNotNone(ko, '%s 번역이 없다' % mid)
            self.assertNotIn('구역', ko,
                             '%s: bay 를 "구역" 이라 부르면 zone 과 겹친다 (%r)'
                             % (mid, ko))
        # 지적도 필지는 그대로.
        self.assertEqual('필지', _ko('Parcel'))
        # bay 의 총량을 zone 이라 부르던 msgid 가 되살아나지 않게.
        for f in ('widgets/AoT_map/aot-map-popup.js', 'common/aot-plot-form.js'):
            js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', f))
            self.assertNotIn("_t('Zone capacity')", js)
            self.assertNotIn("zone capacity below", js)

    def test_plot_label_hiding_uses_a_class_not_inline_style(self):
        """**이번 정리의 계기.** 구획 라벨은 `.style.display` 로 직접 숨었다 —
        다른 모든 라벨 종류(입력·출력·시설·대지·구역·장치·노트)는 클래스
        (`.aot-type-hidden`/`.aot-zoom-hidden`)로 숨는다.

        임시 표시(`.aot-focus-show`, 모달이 열려 있는 동안 강제로 보이게 하는
        장치)는 **클래스만** 상대한다 — 위젯 CSS 의 숨김 규칙이
        `.aot-type-hidden:not(.aot-focus-show)` 형태라, `.aot-focus-show` 를
        붙이면 그 `:not()` 이 깨져 숨김이 풀린다. 인라인 `style.display` 는 이
        메커니즘 밖이라 `.aot-focus-show` 가 아무리 붙어도 소용없다 —
        **도형은 켜지는데 라벨은 안 켜지는** 그 증상이 정확히 이것이었다.
        """
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        body = plot.split('function _applyLabelVisibility', 1)[1] \
                   .split('\n    function ', 1)[0]
        self.assertIn("classList.toggle('aot-type-hidden'", body)
        self.assertNotIn('style.display', body)
        # 다른 함수에도 인라인 display 숨김이 남아 있지 않아야 한다 — 배경색
        # 등 표시용 인라인 스타일(`el.style.background = ...`)은 무관하니
        # display 값 지정만 좁혀서 본다.
        self.assertNotIn("style.display = show", plot)
        self.assertNotIn("style.display = hidden", plot)

    def test_plot_label_uses_the_shared_zoom_gate_not_a_private_threshold(self):
        """구획 라벨은 자기만의 줌 임계(`AoTMapLabelLayers.resolve().minZoom`,
        하드코딩 16)로 숨었다 — 위젯의 통합 줌 게이트(`label_min_zoom`, 기본
        17)와 **다른 기준**이었다. 사용자가 `label_min_zoom` 을 고쳐도 구획
        라벨은 안 따라오고, 0(안 숨김)으로 낮춰도 구획만 계속 숨는 — "한
        옵션을 만지면 다른 옵션이 안 먹는다" 는 증상이 이 갈림에서 나왔다.

        고친 뒤에는 다른 라벨과 **완전히 같은 경로**를 지난다: 요소에
        `dataset.labelKind='plot'` 을 새기고(이미 있었다), 위젯의 중앙
        `_applyZoomGate`(`LABEL_ZOOM_GATED`/`label_min_zoom` 을 읽는 그 함수)
        가 `[data-label-kind]` 전체를 훑을 때 함께 걸린다. 새 라벨을 막
        만들었을 때 다음 줌 이벤트를 기다리지 않도록, 렌더 직후 그 함수를
        한 번 불러 준다.
        """
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        # 사설 임계값을 다시 읽지 않는다.
        self.assertNotIn('reg.resolve', plot)
        self.assertNotIn('labelMinZoom', plot)
        self.assertNotIn('getZoom() >=', plot)
        # 렌더 직후 위젯의 중앙 게이트를 불러 새 요소에 즉시 반영한다.
        render = plot.split('function _renderLabels', 1)[1] \
                     .split('\n    function ', 1)[0]
        self.assertIn('_inst._applyZoomGate()', render)
        # 자체 zoom 리스너는 없앴다 — 위젯의 zoom/zoomend 핸들러 하나로 충분하다.
        self.assertNotIn("map.on('zoom'", plot)

    def test_plot_label_is_owned_by_one_module(self):
        """구획 라벨의 DOM 을 만드는 곳(`aot-map-plot.js`)과 그 라벨의 숨김
        클래스를 새기는 곳이 **같아야 한다.** 예전에는 위젯(`aot-map-widget-
        vector.js`)이 `AoTMapPlot.setLabelVisible` 을 부르고 **또** 자기가
        직접 `querySelectorAll` 로 같은 요소에 클래스를 새겼다 — 두 벌이 되면
        한쪽만 고쳤을 때 조용히 갈리고, 실제로 그렇게 갈려서 이번 결함이 났다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        self.assertNotIn('data-label-kind="plot"', vec)
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        # 라벨 요소를 만드는 것도, 그 뒤로 숨김 클래스를 새기는 것도 이 파일뿐.
        self.assertIn("el.dataset.labelKind = 'plot'", plot)
        self.assertIn("classList.toggle('aot-type-hidden'", plot)

    def test_plot_shape_and_label_are_separate_axes(self):
        """구획만 도형과 라벨이 **한 스위치**에 묶여 있었다 — 다른 계층
        (대지·구역·시설)은 레이어 컨트롤에서 둘이 따로다. 도형을 끄면 이름까지
        사라져 "어디인지는 감추되 무엇이 있는지는 남긴다" 를 할 수 없었다.

        `setVisible`(둘 다)은 위젯 옵션 `show_plots` 가 쓰는 큰 스위치로 남기고,
        레이어 컨트롤은 `setShapeVisible`, 라벨 컨트롤은 `setLabelVisible` 을
        쓴다.
        """
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('function setShapeVisible', plot)
        self.assertIn('function setLabelVisible', plot)
        # 라벨 표시는 **라벨 축만** 본다(도형 축을 보면 다시 묶인다). 줌은
        # 이 함수의 일이 아니다 — `test_plot_label_uses_the_shared_zoom_gate`
        # 가 그 경계를 따로 고정한다.
        self.assertIn('st.labelVisible === false', plot)
        self.assertNotIn('var show = (st.visible !== false)', plot)
        # 도형 카테고리 토글은 도형만 끈다.
        self.assertIn('AoTMapPlot.setShapeVisible(uniqueId, map, visible)', vec)
        self.assertNotIn('AoTMapPlot.setVisible(uniqueId, map, visible)', vec)

    def test_focus_fetches_features_without_turning_the_category_on(self):
        """도형 종류를 꺼 두면 **데이터 자체를 안 받아온다**(레이어는 옵션이 켜져
        있을 때만 만들어진다) — 실측으로 `aot_devices` 소스의 피처가 0개였다.
        그래서 "켜진 장치의 도형을 보인다" 가 그릴 것이 없었다.

        ⚠ 그렇다고 `_ensureShapeLayer[cat]` 을 부르면 안 된다. 그것은 카테고리
        **레이어를 만들고**, 만들어진 레이어는 보인다 — 실측으로 출력 하나가
        켜지자 **모든** 장치 도형이 떴고, 다른 모달이 열려 카테고리가 정상
        상태로 돌아가는 순간 그 전부가 함께 사라졌다.

        필요한 것은 레이어가 아니라 **피처 하나**다. 직접 받아 focus 소스에만
        넣는다 — 카테고리를 꺼 둔 상태는 처음부터 끝까지 그대로다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('function _fetchFocusShapes', vec)
        # 데이터만 받는다 — 레이어를 만드는 경로를 타면 안 된다.
        head = vec.split('function _fetchFocusShapes', 1)[1].split('\n    function ', 1)[0]
        self.assertIn('geoFetch(', head)
        self.assertNotIn('_ensureShapeLayer', head)
        self.assertNotIn('addGeoJSONLayer', head)
        # 출력 ON 은 'device' 종류로 확보한다.
        self.assertIn("dev.is_activated === true, 'device'", vec)

    def test_focus_paints_with_the_theme_not_a_baked_color(self):
        """도형의 색은 피처가 아니라 **테마(theme_config)** 가 정한다 —
        `feature.properties.color` 는 각인 금지 대상이라 오버레이 응답에 아예
        없다(`geo_overlays.py` 에 'color' 라는 낱말이 없다). 그것을 읽던
        `['get','color']` 는 언제나 비어 폴백 한 색으로 통일됐다: 켜진 출력이
        보라(#995aff)가 아니라 브랜드 딥그린으로 나왔다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        focus = vec.split('function _ensureFocusLayers', 1)[1].split('\n    function ', 1)[0]
        self.assertNotIn("['get', 'color']", focus)
        # 면 fill·면 line·점 고리 셋 다 같은 키를 읽는다.
        self.assertEqual(3, focus.count("['get', 'aot_focus_color']"))
        # 칠하는 색은 종류마다 테마에서 해석한다.
        self.assertIn('function _focusColor', vec)
        self.assertIn('T.deviceColor(', vec)
        # 구획만 예외 — 그 색은 구획 행에서 오고 평소 레이어도 그것을 칠한다.
        self.assertIn("if (cat === 'plot' && pr.color) return pr.color;", vec)
        # 원본이 아니라 **사본**에 찍는다(각인 방지).
        rp = vec.split('function _repaintFocus', 1)[1].split('\n    // ', 1)[0]
        self.assertIn('props.aot_focus_color = color', rp)
        self.assertIn("geometry: f.geometry, properties: props", rp)

    def test_program_row_shows_even_with_no_programs(self):
        """등록된 프로그램이 0건이어도 줄을 낸다.

        예전에는 선택지가 비면 줄 자체를 뺐다. 그러면 프로그램을 한 번도 만들지
        않은 설치에서 "프로그램" 이라는 낱말이 화면 어디에도 없고, 사용자는 그것을
        **기능이 없다/고장났다** 로 읽는다 — 2026-08-23 "구버전 모달이 떴다 ·
        프로그램 연동이 안 된다" 는 보고가 실제로 그것이었다(코드는 최신이었고
        다른 것은 `geo_program` 이 0건이라는 사실뿐이었다).
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        block = js.split('// 재배 프로그램 —', 1)[1].split('// 구역 안에서의 몫', 1)[0]
        self.assertNotIn('if ((p.program_choices || []).length) {', block)
        # 하나도 없을 때야말로 만들러 갈 길을 보여야 한다.
        self.assertIn("_t('No programs yet — create one')", block)
        self.assertIn("'/geo/programs'", block)
        for lang in ('ko', 'ja'):
            po = _read(os.path.join(_ROOT, 'aot_flask', 'translations', lang,
                                    'LC_MESSAGES', 'messages.po'))
            self.assertIn('msgid "No programs yet — create one"', po,
                          '%s 번역이 없다' % lang)

    def test_a_failed_fetch_does_not_burn_the_only_attempt(self):
        """"종류당 한 번" 가드를 **함수 첫 줄에서** 세우면 실패한 시도가 기회를
        태운다 — 아직 지도 uuid 를 못 읽는 이른 시점에 한 번 불리면 그대로 영구히
        죽고, 그 위젯에서는 꺼 둔 종류의 도형이 다시는 안 나온다.

        증상이 고약하다: 장치 도형 레이어를 **켰다 끄면** 그때부터 동작한다(그
        조작이 `aot_devices` 소스를 만들어 이 경로를 건너뛰게 하므로). 사용자가
        찾아낸 그 우회법이 곧 진단이었다(2026-08-23 koat).
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = vec.split('function _fetchFocusShapes', 1)[1] \
                  .split('\n    /**', 1)[0]
        # 가드는 uuid 를 확인한 **뒤에** 선다.
        guard = body.index("st['_fetch_' + cat] = 1;")
        bail = body.index('if (!type || !mapUuid) return;')
        self.assertLess(bail, guard,
                        '가드가 mapUuid 검사보다 앞서면 이른 호출이 기회를 태운다')
        # 빈 응답·실패는 가드를 되돌린다.
        self.assertIn("if (!feats.length) { st['_fetch_' + cat] = 0; return; }", body)
        self.assertIn(".catch(function () { st['_fetch_' + cat] = 0; });", body)

    def test_a_locked_map_is_not_moved_by_opening_a_modal(self):
        """잠금의 뜻은 "다른 곳으로 가지 않는다" 이다.

        모달을 열 때마다 카메라가 대상으로 날아가면 그 뜻이 무너진다 — 사용자가
        맞춰 둔 화면이 창을 하나 열 때마다 사라진다. 상호작용만 막고 프로그램
        이동은 그대로 두던 것이 원인이었다.

        **강조는 남긴다.** 카메라를 건드리지 않으므로 잠금과 무관하고, 지도가
        움직이지 않을 때야말로 "이 패널이 어느 도형 얘기인가" 를 알려 줄 유일한
        단서다. 실측: 잠근 채로 열면 모달 O · 강조 O · 카메라 그대로 · `_lastFocus`
        null(닫은 뒤 재구성도 함께 조용해진다).
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = vec.split('function _focusMapOn', 1)[1].split('\n    /**', 1)[0]
        self.assertIn('if (_mapIsLocked(map)) return;', body)
        # 관문은 **강조 뒤, 카메라 앞**에 있어야 한다.
        hl = body.index('_highlightShape(uid,')
        gate = body.index('if (_mapIsLocked(map)) return;')
        move = body.index('map.easeTo(')
        self.assertLess(hl, gate, '강조보다 앞서면 잠금이 강조까지 막는다')
        self.assertLess(gate, move, '카메라 이동보다 뒤면 관문이 무의미하다')
        # 판정은 저장된 옵션이 아니라 지금 상호작용 상태로 한다(실행 중에 바뀐다).
        helper = vec.split('function _mapIsLocked', 1)[1].split('\n    function ', 1)[0]
        self.assertIn('dragPan', helper)
        self.assertNotIn('isLocked', helper)

    def test_focus_draws_devices_that_have_no_area(self):
        """**면이 없는 장치가 있다** — 위치 마커만 있고 맡은 영역이 없는 것.

        koat 실측: 출력 18개 중 펌프 2개가 점뿐이었다. 면만 그리던 시절에는 그
        장치를 켜도 라벨만 켜지고 도형은 영영 안 나왔고, 사용자에게는 "출력을
        켜도 도형이 활성화되지 않는다" 로 보였다(면이 있는 장치로 시험하면
        멀쩡해서 더 찾기 어렵다).
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        layers = vec.split('function _ensureFocusLayers', 1)[1] \
                    .split('\n    function ', 1)[0]
        # 점 전용 고리 레이어가 있어야 한다.
        self.assertIn("id: 'aot-focus-pt-' + uid, type: 'circle'", layers)
        # 면 레이어는 점을 받지 않는다(그 반대도).
        self.assertEqual(2, layers.count("['==', ['geometry-type'], 'Polygon']"))
        self.assertIn("['==', ['geometry-type'], 'Point']", layers)
        # 칠할 목록이 점을 걸러내면 위 레이어는 늘 비어 있다.
        rp = vec.split('function _repaintFocus', 1)[1].split('\n    // ', 1)[0]
        self.assertIn('/Polygon|Point/.test(f.geometry.type)', rp)

    def test_focus_fetches_every_kind_when_the_caller_omits_one(self):
        """모달 쪽 호출부는 대상 종류를 넘기지 않는다 — 공용 셸 하나가 구역·구획·
        시설·장치를 모두 열기 때문이다. 종류가 없을 때 받아오지 않으면 **꺼 둔
        종류의 대상은 모달을 열어도 아무 일도 일어나지 않는다**(실측: 장치 도형
        카테고리가 꺼진 위젯에서 장치를 골라도 도형이 뜨지 않았다 — 켜진 출력만
        `'device'` 를 넘겨 우연히 동작했다).
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = vec.split('function _setFocus', 1)[1].split('\n    /** 이 위젯', 1)[0]
        self.assertIn('cat ? [cat] : Object.keys(_FOCUS_OVERLAY_TYPE)', body)
        # 종류당 한 번만 받는 가드가 있어야 다섯 번 훑는 것이 비용이 되지 않는다.
        fetch = vec.split('function _fetchFocusShapes', 1)[1].split('\n    /**', 1)[0]
        self.assertIn("if (st['_fetch_' + cat]) return;", fetch)

    def test_focus_does_not_dictate_a_display_value(self):
        """임시 표시가 `display` 를 정하면 **그 라벨이 원래 무엇이었는지**를
        여기서 정해 버린다. 값 키의 원형 모드(`--circle`)는 `display: flex` 로
        숫자를 원 한가운데 놓으므로, `block` 으로 바뀌는 순간 숫자가 좌상단으로
        밀린다(실측). 라벨 종류마다 display 가 달라 하나를 고르면 언제나 어느
        하나는 깨진다 — 대신 숨김 규칙이 이 클래스를 비켜 가게 한다.
        """
        py = _read(os.path.join(_ROOT, 'widgets', 'AoT_map.py'))
        self.assertNotIn('.aot-focus-show {', py)
        for cls in ('.aot-type-hidden', '.aot-zoom-hidden'):
            self.assertIn('%s:not(.aot-focus-show)' % cls, py,
                          '%s 가 임시 표시를 비켜 가지 않는다' % cls)
        # 원형 모드가 flex 인 것이 이 규칙의 전제다.
        css = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'widget',
                                 'aot-sensor-label.css'))
        circle = css.split('.aot-sensor-map-marker--circle {', 1)[1].split('}', 1)[0]
        self.assertIn('display: flex', circle)

    def test_the_injected_hide_rule_matches_the_template(self):
        """`.aot-type-hidden` 은 위젯 템플릿과 JS 두 곳에서 심긴다(템플릿 캐시
        보험). 한쪽만 고치면 **나중에 심긴 쪽이 이겨** 조용히 갈라진다 — 실제로
        템플릿에만 `:not(.aot-focus-show)` 를 붙였더니 임시 표시가 통째로 안
        들었다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn(
            "'.aot-type-hidden:not(.aot-focus-show) { display: none !important; }'",
            vec)

    def test_every_label_key_has_a_row_in_the_labels_panel(self):
        """라벨 패널에 행이 없는 종류는 **끌 수는 있는데 켤 수가 없다** — 툴바
        빠른 버튼이나 옛 저장으로 꺼진 축을 되돌릴 자리가 화면에 없기 때문이다.
        구획이 그랬다: [도형] 그룹의 체크박스만 있어서 그것이 켜져 있는데도 라벨이
        안 나왔고, 사용자에게는 "토글이 켜져 있는데 반영이 안 된다" 로 보였다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        keys = set(re.findall(r"'([a-z]+)'",
                              vec.split('var LABEL_KEYS = [', 1)[1].split(']', 1)[0]))
        rows = set(re.findall(r"key: '([a-z]+)'",
                              vec.split('const labelDefs = [', 1)[1].split('\n            ];', 1)[0]))
        self.assertTrue(keys, 'LABEL_KEYS 를 못 읽었다')
        self.assertEqual(set(), keys - rows,
                         '라벨 패널에 행이 없는 종류: %s' % sorted(keys - rows))

    def test_render_does_not_reset_the_plot_label_axis(self):
        """`opts.visible` 은 [도형] 그룹의 `show_plots` 다. 렌더가 그것으로 라벨까지
        내리면 5분 주기 갱신과 새로고침마다 라벨 토글이 지워진다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-plot.js'))
        render = js.split('function _render(uid, map, rows, opts)', 1)[1] \
                   .split('\n    // ── 라벨', 1)[0]
        # 도형 축만 건드린다(라벨 축을 함께 내리지 않는다).
        self.assertNotIn('setVisible(uid, map, opts.visible', render)
        # ⚠ `opts.visible` 은 **페이지 로드 당시 스냅샷**이다. 렌더가 그것으로
        #   매번 되쓰면 5분 폴링·베이스맵 전환·모달 저장 후 재로드가 돌 때마다
        #   방금 끈 도형이 되살아난다. 저장된 상태가 있으면 그것이 이긴다.
        self.assertIn("typeof _stNow.shapeVisible === 'boolean'", render,
                      '렌더가 저장된 도형 상태보다 옵션 스냅샷을 앞세웁니다')
        self.assertIn('opts.visible !== false', render,
                      '선-시딩이 안 됐을 때의 폴백이 사라졌습니다')

    def test_plot_label_axis_survives_being_set_before_render(self):
        """새로고침 직후 위젯은 저장된 라벨 상태를 되살리려고 500·1500·3000ms 에
        `setLabelVisible` 을 부른다. 그때 구획은 아직 서버에서 안 왔을 수 있다 —
        예전에는 `if (st)` 라 그 호출이 조용히 버려져, 뒤늦게 렌더된 라벨이 켜진
        채 돌아왔다("꺼 두고 새로고침하면 되살아난다").
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-plot.js'))
        setl = js.split('function setLabelVisible', 1)[1].split('\n    }', 1)[0]
        self.assertIn('STATE[uid] = STATE[uid] || {}', setl)
        self.assertNotIn('if (st) st.labelVisible', setl)
        sets = js.split('function setShapeVisible', 1)[1].split('\n    }', 1)[0]
        self.assertIn('.shapeVisible = !!visible', sets)
        self.assertNotIn('if (st) st.shapeVisible', sets)
        # 레이어가 나중에 생겨도 그 전에 정해진 뜻을 따른다 — 이 모듈은 자기만의
        # fetch 를 쓰므로 위젯의 나머지 초기화와 시간이 어긋난 채 끝난다. 그래서
        # `load()` 가 **fetch 를 걸기 전에** opts 로 받은 초기 상태를 STATE 에
        # 미리 심는다(파일 머리말 "초기 표시 상태 계약"). 나중에 오는
        # `addLayerPanel` 의 적용은 확인이지 최초 통보가 아니다.
        load = js.split('function load(', 1)[1].split('\n    function ', 1)[0]
        self.assertIn("typeof st.shapeVisible !== 'boolean'", load,
                      'fetch 전에 도형 축을 선-시딩하지 않습니다')
        self.assertIn("typeof st.labelVisible !== 'boolean'", load,
                      'fetch 전에 라벨 축을 선-시딩하지 않습니다')

    def test_focus_prefers_the_area_over_the_marker(self):
        """장치는 한 uuid 에 피처가 **둘**이다 — 위치 마커(Point)와 그 장치가 맡은
        영역(Polygon). 먼저 만나는 것을 잡으면 대개 Point 가 걸리는데, 이 표시는
        fill/line 레이어로 그리므로 점은 아무것도 그리지 못한다.

        실측으로 그랬다: `hasFeature: true, geom: 'Point'` 인데 그려진 피처는 0개 —
        **라벨만 켜지고 도형은 안 나온다** 가 그 증상이다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = vec.split('function _findInFeatures', 1)[1].split('\n    function ', 1)[0]
        # 면이면 즉시 반환, 점은 폴백으로만.
        self.assertIn('if (/Polygon/.test(g.type', body)
        self.assertIn('fallback', body)
        # 나중에 면이 도착하면 점을 갈아 준다.
        self.assertIn("if (cur && /Polygon/.test((cur.geometry || {}).type", vec)

    def test_active_focus_survives_opening_another_modal(self):
        """켜진 장치의 표시는 **모달과 무관**해야 한다. 창을 갈아 끼울 때 거두는
        것은 'modal' 이유뿐이고, 'active' 는 그 장치가 꺼질 때까지 남는다."""
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        body = vec.split('function _clearModalFocus', 1)[1].split('\n    function ', 1)[0]
        self.assertIn("st.targets[u].modal", body)
        self.assertIn("'modal', false", body)
        # 'active' 를 함께 거두면 켜진 장치가 모달 한 번에 사라진다.
        self.assertNotIn("'active', false", body)

    def test_hidden_things_come_back_while_you_look_at_them(self):
        """사용자가 꺼 둔 도형·라벨이라도 **지금 봐야 할 이유**가 있으면 보인다:
        그 대상의 모달이 열려 있거나, 그 출력이 켜져 있을 때.

        ⚠ **꺼 둔 상태를 바꾸지 않는다.** 토글을 켜 버리면 모달을 닫았을 때
        사용자가 꺼 둔 것이 켜진 채로 남는다. 그래서 숨김 클래스는 그대로 두고
        더 강한 클래스를 얹었다 뗀다.

        ⚠ 이유를 **이유별로 센다.** 모달을 닫았다고 바로 끄면 그 장치가 아직
        켜져 있는데도 사라진다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        py = _read(os.path.join(_ROOT, 'widgets', 'AoT_map.py'))

        self.assertIn('function _setFocus', vec)
        self.assertIn("'modal'", vec)
        self.assertIn("'active'", vec)
        # 토글 상태를 건드리지 않는다 — 숨김 클래스를 지우는 코드가 없어야 한다.
        self.assertNotIn("classList.remove('aot-type-hidden')", vec)

        # CSS 는 **숨김 규칙이 이 클래스를 비켜 가는** 방식이다. 예전에는
        # `.aot-focus-show { display: block !important }` 로 되살렸는데, 그러면
        # 라벨의 생김새를 여기서 정해 버려 원형 값 키가 깨졌다
        # (`test_focus_does_not_dictate_a_display_value`).
        self.assertIn('.aot-type-hidden:not(.aot-focus-show)', py)
        self.assertIn('.aot-zoom-hidden:not(.aot-focus-show)', py)

        # 창을 갈아 끼울 때도 앞 대상의 이유를 거둔다(remove() 는 닫힘 리스너를
        # 지나지 않는다 — 실측으로 앞 대상이 계속 보였다).
        self.assertIn('function _clearModalFocus', vec)
        self.assertIn('_clearModalFocus(_prevInst, uid)', vec)

        # 라벨은 uuid 로 찾는다 — 표식이 없으면 명부가 있어도 못 찾는다.
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        self.assertIn('el.dataset.plotUuid', plot)
        self.assertIn('el.dataset.deviceId', vec)

    def test_shape_option_is_live_appliable(self):
        """도형 표시 옵션은 **두 표에 다 있어야** 화면이 즉시 반응한다.
        한쪽만 넣으면 저장은 되는데 새로고침해야 반영된다 — 사용자에게는
        "옵션이 작동하지 않는다" 로 보인다(구획이 실제로 그랬다).
        """
        lp = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'app',
                                'dashboard-widget-live-preview.js'))
        # 자동저장 대상.
        m = re.search(r'var MAP_SAFE_KEYS = \{(.*?)\};', lp, re.S)
        self.assertIsNotNone(m, 'MAP_SAFE_KEYS 가 사라졌다')
        self.assertIn('show_plots', m.group(1))
        # 지도 카테고리 매핑.
        m2 = re.search(r'var MAP_SHAPE_CAT = \{(.*?)\};', lp, re.S)
        self.assertIsNotNone(m2, 'MAP_SHAPE_CAT 가 사라졌다')
        self.assertIn("show_plots: 'plot'", m2.group(1))
        # 지도 쪽이 그 카테고리를 실제로 처리하는가.
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn("cat === 'plot' && window.AoTMapPlot", vec)

    def test_end_dialog_wording_is_not_agriculture_only(self):
        """종료 창의 선택지도 **중립어**여야 한다 — 구획의 `kind` 는 vegetation |
        livestock | facility | other 다.

        "심는다"(plant)는 축사·창고를 이어받는 자리에서 그냥 틀리고, 종류를 고르는
        칸이 바로 아래 있는데 선택지 이름이 하나를 미리 말해 버린다. 아이콘·
        "휴경" 과 같은 계열의 실수다.

        종료 사유의 `Failed` 도 뺐다 — 작업·요청 실패에도 쓰이는 말이라 일본어가
        「失敗しました」 라는 **문장형**이고, 드롭다운에 "실패했습니다" 가 선다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertNotIn('Plant the next one', js)
        self.assertNotIn('pick what to grow', js)
        self.assertIn("_t('Start the next one')", js)
        # 종료 사유는 전용 낱말.
        self.assertIn("""'<option value="failed">' + _esc(_t('Lost'))""", js)

    def test_japanese_says_advice_one_way(self):
        """같은 것을 두 말로 부르면 사용자가 둘을 다른 기능으로 읽는다. 일본어
        카탈로그에 「助言」(문어체) 10건과 「アドバイス」 13건이 섞여 있었다 —
        일상어인 쪽으로 모았다.

        「紐づく」 도 뺐다. IT 업계 말이라 농가 화면에서 딱딱하다.
        """
        ja = _read(os.path.join(_ROOT, 'aot_flask', 'translations', 'ja',
                                'LC_MESSAGES', 'messages.po'))
        self.assertNotIn('助言', ja)
        self.assertNotIn('紐づ', ja)

    def test_plot_icon_is_not_a_plant(self):
        """구획은 **식생 전용이 아니다** — `kind` 가 vegetation | livestock |
        facility | other 다. 새싹·잎사귀 아이콘은 가축사·창고를 관리하는 화면에서
        그냥 틀린 그림이고, 종류를 고르는 자리가 따로 있는데 아이콘이 하나를
        미리 말해 버린다.

        같은 이유로 `crop`→`subject`(p6_42), "휴경"→종류별 이름을 이미 고쳤다.
        """
        for rel in (('aot_flask', 'static', 'js', 'geo', 'aot-map-custom-controls.js'),
                    ('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                     'aot-map-widget-vector.js')):
            js = _read(os.path.join(_ROOT, *rel))
            for icon in ('fa-seedling', 'fa-leaf', 'fa-tree', 'fa-cannabis'):
                self.assertNotIn(icon, js,
                                 '%s: 구획에 식물 아이콘(%s)을 쓰면 안 된다'
                                 % (rel[-1], icon))

    def test_plot_has_a_quick_toggle_and_facility_still_hides_its_chip(self):
        """오른쪽 툴바의 빠른 토글은 자주 누르는 것만 둔다. 함수 라벨은 드물어
        빼고 그 자리를 **구획(plot)** 이 받는다 — 한 구역에 두둑이 수십 개면 이
        라벨이 지도에서 가장 자주 걸린다.

        ⚠ **동(bay) 칩은 시설 토글이 끈다.** 지도에서 사람이 보는 시설 이름이 곧
        이 칩이기 때문이다(시설 가장자리 칩은 예전에 없앴고 동 칩이 단일
        진입점이다). 한때 동 토글로 갈랐다가 "[시설] 을 눌러도 시설 이름이 안
        꺼진다" 가 됐다 — 화면에 시설 라벨이 따로 없으니 그 버튼이 아무 일도 안
        하는 것으로 보인다.
        """
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        m = re.search(r'var quickLabels = \[(.*?)\];', vec, re.S)
        self.assertIsNotNone(m, 'quickLabels 가 사라졌다')
        keys = re.findall(r"key: '([a-z]+)'", m.group(1))
        self.assertEqual(['input', 'output', 'plot', 'facility'], keys)
        # 시설 토글이 동 칩을 끈다(갈라 놓으면 시설 버튼이 아무 일도 안 한다).
        self.assertIn("key === 'facility' && inst.bayMarkers", vec)
        self.assertNotIn("key === 'bay' && inst.bayMarkers", vec)
        # 구획 라벨은 다른 모듈(AoTMapPlot)이 DOM 을 들고 있다 — 여기서는
        # 그 모듈의 함수만 부르고 클래스를 직접 새기지 않는다. 두 곳이 같은
        # 요소를 건드리면 한쪽만 고쳤을 때 조용히 갈린다(도형·라벨이 반대로
        # 켜지던 사고가 그 모양이었다 — `test_plot_label_is_owned_by_one_module`
        # 가 이 경계를 고정한다).
        self.assertNotIn("""querySelectorAll('[data-label-kind="plot"]')""", vec)
        self.assertIn('AoTMapPlot.setLabelVisible(uniqueId, inst.map, !hidden)', vec)
        # 사람이 끄고 켜는 축에 bay 는 없다(시설이 대신한다).
        for m2 in re.finditer(r"var LABEL_KEYS = \[(.*?)\];", vec, re.S):
            self.assertNotIn("'bay'", m2.group(1))
            self.assertIn("'plot'", m2.group(1))

    def test_one_chip_per_facility_and_a_way_into_each_bay(self):
        """**시설 하나에 칩 하나.** 구역마다 칩을 두면 서로를 덮는다 — 구역
        중심이 8.4m 인 시설이 있는데(폭 7m·6동을 둘로 나눈 것) 줌 17 에서 그
        거리는 30px 남짓이라 칩 하나 폭도 안 된다.

        겹칠 때만 접는 방법도 있었지만 그러면 줌을 만질 때마다 칩 개수가 바뀌어
        지도가 요동친다. 어차피 구역에는 시설을 거쳐 들어간다.

        ⚠ 그래서 **모달에 구역 전환 줄이 먼저 있어야 한다.** 예전에는 다른
        구역으로 가는 길이 지도의 구역 칩뿐이었다 — 칩을 접는 순간 나머지
        구역에 닿을 방법이 사라진다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-widget-vector.js'))
        # 칩은 시설당 하나 — 구역이 여럿이면 첫 것만.
        self.assertIn('bSlices.slice(0, 1)', js)
        self.assertIn('dataset.bayRollup', js)
        # 그 칩은 시설 이름을 단다(첫 구역 이름이 아니라).
        self.assertIn('_multiBay ? (fac.name', js)
        # 구역 전환 줄과 그 배선.
        self.assertIn('aot-bay-switch', js)
        self.assertIn('data-bay-switch', js)
        self.assertIn("closest('[data-bay-switch]')", js)
        # 겹침 계산은 없앴다 — 줌마다 칩 개수가 바뀌면 지도가 요동친다.
        self.assertNotIn('_applyBayCrowding', js)

    def test_track_markers_do_not_map_onto_the_rounded_caps(self):
        """트랙은 양끝이 둥글다(반지름 = 높이/2). 0~100% 를 트랙 폭에 그대로
        매핑하면 마커가 라운드 안에 박혀 **시작·끝이 실제보다 바깥으로** 보인다.

        보정은 CSS 가 한다(캡 크기가 트랙 높이에서 파생되므로). JS 가 퍼센트를
        `left` 로 직접 박으면 그 보정이 통째로 무력해지고, 증상은 "끝에서만 몇
        px 어긋난다" 라 눈으로 잡기 어렵다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'common', 'aot-dataviz.js'))
        css = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css',
                                 'components', 'aot-dataviz.css'))

        # 마커는 위치값만 넘긴다.
        self.assertIn('--aot-viz-pos', js)
        for cls in ('aot-viz-now', 'aot-viz-target'):
            self.assertNotIn('"%s" style="left:' % cls, js,
                             '%s: 퍼센트를 left 에 직접 박으면 캡 보정이 죽는다' % cls)

        # 보정식은 트랙 높이에서 파생돼야 한다 — 4px 을 적어 두면 높이를 바꿀 때
        # 조용히 어긋난다.
        self.assertIn('var(--aot-viz-track-h) / 2', css)
        self.assertIn('100% - var(--aot-viz-track-h)', css)

        # 구간(면)은 보정하지 않는다 — 100% 인 구간이 캡을 안 채우면 양끝에
        # 트랙 배경이 남아 "덜 찼다" 로 보인다.
        self.assertIn('"aot-viz-ok" style="left:', js)

    def test_planned_plot_is_visible_but_says_it_has_not_started(self):
        """계획 구획은 **목록에 보이되** 자라는 것과 구분돼야 한다.

        예전에는 저장은 되는데 어느 화면에도 나타나지 않았다(지도·기본 목록·시설
        목록 모두 `started_on <= today` 로 걸렀다). 만든 사람이 자기가 만든 것을
        찾을 수 없으니 "저장이 안 됐나" 하고 다시 만들게 되고, 그 중복도 안 보인다.
        """
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        saved, _ = self._plant(
            started_on=(date.today() + timedelta(days=7)).isoformat())
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        d = plot_context.to_dict(row)
        self.assertTrue(d['planned'])
        self.assertEqual(d['days_until_start'], 7)
        # **음수를 내보내지 않는다.** 그대로 실으면 화면이 "-6일차" 를 그린다.
        self.assertIsNone(d['days_since_planted'])

        # 계산 자체는 음수를 유지해야 한다 — `stage_of` 가 그 부호로 계획을
        # 판정한다. 여기서 눕히면 그 판정이 통째로 사라진다(실제 회귀 이력).
        self.assertLessEqual(plot_context.elapsed_days(row), 0)

    def test_ending_a_plot_can_hand_the_place_over(self):
        """수확이 끝났다고 그 자리가 없어지지 않는다 — 휴지기·정지·다음 작기가
        이어진다. 종료와 생성을 따로 하게 두면 사람이 그 사이에 도형을 다시
        그리고 몫을 다시 적어야 하고, 그 왕복이 곧 자리를 잃는 것이다.
        """
        from aot.aot_flask.geo import plot_io, plot_context
        from aot.databases.models import GeoPlot

        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)
        uid = saved['unique_id']

        res, err = plot_io.succeed_plot(uid, subject='휴경',
                                        program_uuid=None, variety=None)
        self.assertIsNone(err)
        ended, nxt = res['ended'], res['next']

        # 끝난 것은 **지워지지 않는다** — 종료일만 적힌다.
        self.assertIsNotNone(GeoPlot.query.filter_by(unique_id=uid).first())
        self.assertFalse(ended['active'])
        self.assertTrue(ended['ended_on'])

        # 새 것은 같은 자리를 그대로 물려받는다.
        src = GeoPlot.query.filter_by(unique_id=uid).first()
        new = GeoPlot.query.filter_by(unique_id=nxt['unique_id']).first()
        self.assertEqual(src.facility_uuid, new.facility_uuid)
        self.assertEqual(src.bay_id, new.bay_id)
        self.assertEqual(src.allocation, new.allocation)   # 몫도 물려준다
        self.assertEqual(src.feature, new.feature)
        # 프로그램은 **명시적으로 비웠다**(휴지기).
        self.assertIsNone(new.program_uuid)
        # 시작은 종료 다음 날 — 같은 날로 두면 하루가 두 작기에 걸친다.
        self.assertEqual(new.started_on, src.ended_on + timedelta(days=1))

    def test_succession_keeps_the_program_unless_told_otherwise(self):
        """`program_uuid` 를 **주지 않는 것**과 `None` 을 주는 것은 다른 뜻이다.
        기본값을 None 으로 두면 "안 줬다" 와 "비워라" 를 구별할 수 없어, 이어심기가
        늘 프로그램을 잃는다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)
        res, err = plot_io.succeed_plot(saved['unique_id'])   # 인자 없음
        self.assertIsNone(err)
        new = GeoPlot.query.filter_by(unique_id=res['next']['unique_id']).first()
        self.assertEqual(prog.unique_id, new.program_uuid)

    def test_resting_name_is_not_agriculture_only(self):
        """**"휴경" 은 중립어가 아니다** — 경작(耕)을 전제한 말이라 축사·시설에는
        그냥 틀리다. 반대로 넷을 "쉬는 중" 으로 통일하면 농가 화면이 관공서
        말투가 된다. 그래서 종류마다 부르는 말이 따로 있고, 그 표는 한 곳
        (`AoTPlotLabels`)에 있다 — 대상·품종 라벨과 같은 자리다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'common', 'aot-plot-labels.js'))
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertIn('var RESTING', js)
        for kind in ('vegetation', 'livestock', 'facility', 'other'):
            self.assertRegex(js, r'RESTING[\s\S]{0,400}%s:' % kind)
        # 종료 창은 표를 **부른다**(자기 기본값을 적지 않는다).
        self.assertIn('AoTPlotLabels.resting', popup)
        self.assertNotIn("_t('Fallow')", popup)
        # `Not in use` 는 이미 "사용 중이 아님" 으로 번역돼 있어 이름 자리에
        # 문장이 들어간다 — 빌려 쓰지 않는다.
        self.assertNotIn("'Not in use'", js)

    def test_end_dialog_does_not_claim_anything_is_deleted(self):
        """옛 문구는 "지도에서 사라지고 이력으로만 남습니다" 였다 — 도형이 지워지는
        것으로 읽혀 사람이 종료를 못 눌렀다. 실제로 `end_plot` 은 행도 기하도
        남기고 종료일만 적는다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-popup.js'))
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'widgets', 'AoT_map', 'aot-map-plot.js'))
        self.assertIn('function openPlotEnd', js)
        self.assertIn('Nothing is deleted', js)
        self.assertNotIn('It disappears from the map', plot)
        # 세 선택지가 다 있어야 한다.
        for v in ("'none'", "'rest'", "'next'"):
            self.assertIn(v, js)

    def test_planned_plot_still_shows_its_stages(self):
        """계획을 세우는 사람이 알고 싶은 것은 "언제부터" 만이 아니라 **어떤
        단계로 얼마나** 다. 그 구조는 프로그램에 이미 있으니 축을 그대로 그린다.

        다만 오늘 마커도 현재 단계 강조도 두지 않는다 — 아직 아무 단계도 아니라서,
        마커를 왼쪽 끝에 세우면 "이제 막 시작했다" 로 읽힌다.
        """
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program()
        saved, _ = self._plant(
            program_uuid=prog.unique_id,
            started_on=(date.today() + timedelta(days=30)).isoformat())
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        tl = plot_context.timeline(row)
        self.assertTrue(tl and tl['stages'], '계획에도 단계 축이 있어야 한다')
        # 위치는 0 이 아니라 **없는 값**이다.
        self.assertIsNone(tl['today_pct'])
        self.assertIsNone(tl['elapsed_days'])
        self.assertEqual(tl['days_until_start'], 30)
        # 어느 단계도 진행 중이 아니다.
        self.assertEqual(0, sum(1 for st in tl['stages'] if st.get('current')))

    def test_a_clearable_date_has_one_markup(self):
        """iOS 는 날짜 입력을 비울 수단을 주지 않는다(피커의 [재설정]도 표시된
        날짜를 넣는다). "종료 미정" 은 정상 상태이므로 화면이 지우는 수단을
        줘야 한다.

        마크업은 **한 곳**(`AoTPlotForm.clearableDate`)이다 — 구획 모달이 아직
        자기 입력 빌더를 갖고 있어서, 각자 적으면 두 화면의 x 가 다른 자리에
        다른 크기로 선다.
        """
        form = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                  'common', 'aot-plot-form.js'))
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertIn('function clearableDate', form)
        self.assertIn('function wireDateClear', form)
        self.assertIn('clearableDate: clearableDate', form)
        # 구획 모달은 빌려 쓴다(자기 버튼을 새로 적지 않는다).
        self.assertIn('AoTPlotForm.clearableDate', popup)
        self.assertNotIn('aot-pf-date-clear', popup)
        # 시작일에는 붙지 않는다 — 비어 있으면 안 되는 값이다.
        self.assertIn("field !== 'started_on'", popup)
        self.assertIn("f.key !== 'started_on'", form)

    def test_planned_plot_stays_on_the_map(self):
        """**계획 구획도 지도에 그린다** (2026-08-22 판단 번복).

        처음에는 "아직 심지 않은 것을 그리면 있는 것처럼 보인다" 로 지도에서
        뺐는데, 그러자 구획을 만든 자리에서 그것이 사라졌다 — 자리를 정하는
        일이 곧 계획이고 그 자리를 정하는 화면이 지도다. 만들자마자 사라지면
        무엇을 어디에 두었는지 확인할 방법이 없다.

        대신 **점선**으로 가른다(`planned` 속성 → 별도 line 레이어).
        `line-dasharray` 는 data-driven 을 지원하지 않아 레이어를 나눈다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                'widgets', 'AoT_map', 'aot-map-plot.js'))
        # 지도도 계획을 받는다.
        self.assertIn('include_planned=1', js)
        # 피처가 자기 상태를 싣고, 선 레이어가 그것으로 갈린다.
        self.assertIn('planned: !!p.planned', js)
        self.assertIn("'line-dasharray': [2, 2]", js)
        self.assertIn('aot-plot-line-planned-', js)
        # 레이어 이름은 `aot-plot-` 으로 시작해야 레이어 컨트롤이 찾는다
        # (`getLayerIdsByType('plot')` 가 이름을 본다).
        for m in re.finditer(r"(\w+):\s*'(aot-[a-z-]+)-' \+ uid", js):
            self.assertTrue(m.group(2).startswith('aot-plot-'),
                            '%s: 레이어 이름이 aot-plot- 으로 시작해야 한다'
                            % m.group(2))

    def test_planned_plot_is_out_of_the_default_query_but_in_the_list(self):
        """기본 조회는 활성만 — 제어와 옛 소비처가 계획을 보면 안 된다.
        계획을 원하는 자리(지도·목록)만 `include_planned` 를 켠다."""
        from datetime import timedelta
        from aot.databases.models import GeoPlot
        from aot.aot_flask.geo import plot_context

        saved, _ = self._plant(
            started_on=(date.today() + timedelta(days=7)).isoformat())
        uid = saved['unique_id']
        row = GeoPlot.query.filter_by(unique_id=uid).first()

        default = plot_context.active_plots(row.geo_id)
        planned = plot_context.active_plots(row.geo_id, include_planned=True)
        self.assertNotIn(uid, [r.unique_id for r in default])
        self.assertIn(uid, [r.unique_id for r in planned])

    def test_control_never_sees_a_planned_plot(self):
        """코디네이터가 아직 심지도 않은 작물의 목표를 따르면 빈 온실을 그 작물
        기준으로 덥히고 적신다. 그래서 `plots_in_facility` 의 **기본값**이 곧
        안전 결정이다 — 화면만 켠다."""
        import inspect
        from aot.aot_flask.geo import plot_context

        sig = inspect.signature(plot_context.plots_in_facility)
        self.assertIs(sig.parameters['include_planned'].default, False)

        # 켜는 곳은 화면 하나뿐이어야 한다.
        for mod in ('routes_geo_iec.py', 'coordinator_plot.py'):
            path = os.path.join(_ROOT, 'aot_flask',
                                'geo' if mod == 'coordinator_plot.py' else '',
                                mod)
            if not os.path.exists(path):
                continue
            self.assertNotIn('include_planned', _read(path),
                             '%s: 제어 경로가 계획 구획을 보면 안 된다' % mod)

    def test_past_the_end_is_said_not_pinned(self):
        """마지막 단계에 길이가 있고 그마저 지나면 그 사실을 말한다."""
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program(stages=[
            {'key': 'seedling', 'name': '육묘기', 'days': 10},
            {'key': 'harvest', 'name': '수확기', 'days': 10},
        ])
        saved, _ = self._plant_days_ago(30, program_uuid=prog.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        st = plot_context.stage_of(row)
        self.assertEqual(st['state'], 'past_end')
        self.assertEqual(st['days_past'], 11)      # 31일차 − 20일

    def test_no_program_no_stage(self):
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot
        saved, _ = self._plant()
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertIsNone(plot_context.stage_of(row))

    def test_expected_end_is_derived_but_manual_wins(self):
        """사람이 적은 값이 이긴다 — 덮으면 자기가 적은 날짜가 사라진다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot

        prog = self._program()                      # 총 56일
        saved, _ = self._plant(program_uuid=prog.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

        due, src = plot_context.expected_end(row)
        self.assertEqual(src, 'program')
        # 심은 날이 1일차이므로 마지막 날은 +55 다(56일차).
        self.assertEqual(due, row.started_on + timedelta(days=55))

        row.expected_end_on = date.today() + timedelta(days=99)
        due2, src2 = plot_context.expected_end(row)
        self.assertEqual(src2, 'manual')
        self.assertEqual(due2, row.expected_end_on)

    def test_derived_end_is_not_written_back(self):
        """파생 종료일을 컬럼에 써 넣지 않는다 — 사람 입력과 구분이 사라진다."""
        from aot.databases.models import GeoPlot
        prog = self._program()
        saved, _ = self._plant(program_uuid=prog.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertIsNone(row.expected_end_on)          # 컬럼은 비어 있다
        self.assertIsNotNone(saved['expected_end_on'])  # 응답에는 실린다
        self.assertEqual(saved['expected_end_source'], 'program')

    def test_days_to_expected_end_uses_the_derived_date(self):
        """프로그램을 골라 둔 구획이 "예상 종료 없음" 으로 보이면 안 된다."""
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot
        prog = self._program()
        saved, _ = self._plant_days_ago(10, program_uuid=prog.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        self.assertEqual(plot_context.days_to_expected_end(row), 45)

    def test_control_brief_carries_the_stage(self):
        """제어 화면이 "지금 어느 단계인가" 를 말할 수 있어야 한다."""
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoPlot
        prog = self._program()
        saved, _ = self._plant_days_ago(30, program_uuid=prog.unique_id)
        row = GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()
        brief = plot_context.plot_brief_for_control(row)
        self.assertEqual(brief['stage_name'], '영양생장기')
        self.assertEqual((brief['stage_index'], brief['stage_total']), (2, 3))

    # ── P3: 관리(생성·복제·수정·삭제) ───────────────────────────────────
    def test_builtin_cannot_be_edited_but_can_be_copied(self):
        """내장을 고치게 두면 업그레이드가 그 수정을 덮어써 조용히 되돌아간다."""
        from aot.aot_flask.geo import program_io

        builtin = self._program(source='builtin')
        out, err = program_io.update_program(builtin.unique_id, {'name': 'x'})
        self.assertIsNone(out)
        self.assertIn('복제', err or '')

        copy, err = program_io.clone_program(builtin.unique_id)
        self.assertIsNone(err)
        self.assertEqual(copy['source'], 'user')
        self.assertEqual(copy['derived_from'], builtin.unique_id)
        self.assertTrue(copy['editable'])

    def test_clone_does_not_follow_the_original(self):
        """`derived_from` 은 출처 기록이지 링크가 아니다 — 원본이 바뀌어도 그대로."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import program_io
        from aot.databases.models import GeoProgram

        src = self._program(source='builtin')
        copy, _ = program_io.clone_program(src.unique_id)
        src.stages = [{'key': 'x', 'name': 'x', 'days': 1}]
        db.session.commit()

        row = GeoProgram.query.filter_by(unique_id=copy['unique_id']).first()
        self.assertEqual(len(row.stage_list()), 3)      # 복제 시점 그대로

    def test_version_rises_only_when_content_changes(self):
        """저장 버튼을 눌렀다는 이유로 올리면 고정 버전과의 차이가 의미를 잃는다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        same, err = program_io.update_program(row.unique_id,
                                                   {'name': row.name})
        self.assertIsNone(err)
        self.assertEqual(same['version'], 1)

        changed, err = program_io.update_program(row.unique_id,
                                                      {'name': '새 이름'})
        self.assertIsNone(err)
        self.assertEqual(changed['version'], 2)

    def test_stage_without_days_must_be_last(self):
        """중간에 "끝까지" 를 두면 그 뒤 단계는 시작되지 않는다 — 저장은 되고
        화면만 이상해지는 종류라 서버가 막는다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': None},
                       {'key': 'b', 'name': 'b', 'days': 10}]})
        self.assertIsNone(out)
        self.assertIn('마지막', err or '')

    def test_program_in_use_cannot_be_deleted(self):
        """지우면 그 작기가 "무엇을 목표로 길렀나" 의 근거를 잃는다."""
        from aot.aot_flask.geo import program_io

        prog = self._program(source='user')
        self._plant(program_uuid=prog.unique_id)
        out, err = program_io.delete_program(prog.unique_id)
        self.assertIsNone(out)
        self.assertIn('구획', err or '')

    def test_unused_program_can_be_deleted(self):
        from aot.aot_flask.geo import program_io
        prog = self._program(source='user')
        out, err = program_io.delete_program(prog.unique_id)
        self.assertIsNone(err)
        self.assertTrue(out['ok'])

    def test_ai_tool_requires_a_source_note(self):
        """근거가 없으면 나중에 이 값을 고칠 사람이 판단할 재료가 없다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        res = S.create_program(name='x', subject='tomato',
                                    stages=[{'key': 'a', 'name': 'a', 'days': 10}])
        self.assertEqual(res['status'], 'error')
        self.assertIn('source_note', res['message'])

    def test_ai_created_program_is_not_usable_for_control(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        res = S.create_program(
            name='AI 토마토', subject='tomato', source_note='RDA 지침 기준',
            stages=[{'key': 'seedling', 'name': '육묘기', 'days': 20},
                    {'key': 'harvest', 'name': '수확기', 'days': None}])
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['program']['source'], 'ai')
        self.assertFalse(res['program']['usable_for_control'])

    def test_review_flag_unlocks_control(self):
        from aot.aot_flask.geo import program_io
        row = self._program(source='ai')
        out, err = program_io.update_program(row.unique_id, {'reviewed': True})
        self.assertIsNone(err)
        self.assertTrue(out['usable_for_control'])

    # ── AI 가 사람의 프로그램을 채우면 검토 게이트로 되돌아간다 ────────────
    #
    # 게이트가 `create_program` 만 막고 있었다. 실제로 쓰이는 흐름은 사람이 빈
    # 프로그램을 만들고(source='user') AI 에게 채우게 하는 쪽인데, 그때는
    # source 가 user 로 남아 지어냈을지 모르는 숫자가 검토 없이 제어에 닿았다.

    def test_ai_filling_a_user_program_sends_it_back_for_review(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        row = self._program(source='user')
        self.assertTrue(row.usable_for_control())      # 사람 것이라 원래는 통과

        res = S.modify_program(
            program_id=row.unique_id,
            stages=[{'key': 'seedling', 'name': '육묘기', 'days': 20,
                     'targets': {'temp_day': 24.0}},
                    {'key': 'harvest', 'name': '수확기', 'days': None}])
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['program']['source'], 'ai')
        self.assertFalse(res['program']['usable_for_control'])

    def test_ai_rewriting_a_reviewed_program_clears_the_review(self):
        """전에 검토했더라도 AI 가 내용을 다시 썼으면 그 검토는 지금 내용에
        대한 것이 아니다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S
        from aot.utils.time_utils import utc_now

        row = self._program(source='ai', reviewed=utc_now())
        self.assertTrue(row.usable_for_control())

        res = S.modify_program(
            program_id=row.unique_id,
            stages=[{'key': 'harvest', 'name': '수확기', 'days': None}])
        self.assertEqual(res['status'], 'success')
        self.assertFalse(res['program']['usable_for_control'])

    def test_ai_renaming_does_not_touch_the_gate(self):
        """이름·설명은 제어에 닿지 않는다 — 고쳤다고 검토를 무르면 사람이
        검토한 프로그램이 이름 한 번에 잠긴다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        row = self._program(source='user')
        res = S.modify_program(program_id=row.unique_id, name='새 이름')
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['program']['source'], 'user')
        self.assertTrue(res['program']['usable_for_control'])

    def test_ai_cannot_mark_its_own_work_reviewed(self):
        """AI 가 `reviewed` 를 세울 수 있으면 게이트가 없는 것과 같다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='ai')
        out, err = program_io.update_program(
            row.unique_id, {'reviewed': True, 'notes': 'AI 가 스스로 확인'},
            by='ai')
        self.assertIsNone(err)
        self.assertFalse(out['usable_for_control'])

    def test_person_editing_stages_keeps_their_own_program(self):
        """사람이 화면에서 고치는 경로(by=None)는 그대로다 — 사람이 쓴 것은
        사람이 이미 본 것이다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        out, err = program_io.update_program(
            row.unique_id,
            {'stages': [{'key': 'harvest', 'name': '수확기', 'days': None}]})
        self.assertIsNone(err)
        self.assertEqual(out['source'], 'user')
        self.assertTrue(out['usable_for_control'])

    # ── delete_program (AI 도구) ────────────────────────────────────────
    # program_io.delete_program 자체의 참조 무결성은 위
    # test_program_in_use_cannot_be_deleted / test_unused_program_can_be_deleted
    # 가 지킨다. 여기서는 도구 계층(AoTDataToolService.delete_program) 이 그
    # 결과를 그대로 전달하는지만 본다 — 얇은 어댑터라 자체 로직이 없다.

    def test_ai_tool_deletes_unused_program(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S
        prog = self._program(source='user')
        res = S.delete_program(program_id=prog.unique_id)
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['deleted'], prog.unique_id)

    def test_ai_tool_refuses_program_in_use(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S
        prog = self._program(source='user')
        self._plant(program_uuid=prog.unique_id)
        res = S.delete_program(program_id=prog.unique_id)
        self.assertEqual(res['status'], 'error')
        self.assertIn('구획', res['message'])

    def test_ai_tool_requires_program_id(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S
        res = S.delete_program()
        self.assertEqual(res['status'], 'error')
        self.assertIn('program_id', res['message'])

    # ── 단계 목표 ───────────────────────────────────────────────────────
    def test_stage_targets_are_validated_and_kept(self):
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': '목표', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'temp_day': '22', 'rh': 70}}]})
        self.assertIsNone(err)
        self.assertEqual(out['stages'][0]['targets'], {'temp_day': 22.0, 'rh': 70.0})

    def test_blank_target_is_omitted_not_zeroed(self):
        """빈 칸을 0 으로 채우면 "미지정" 과 구분할 수 없다."""
        from aot.aot_flask.geo import program_io
        out, _ = program_io.create_program({
            'name': '목표2', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'temp_day': '22', 'co2': ''}}]})
        self.assertEqual(out['stages'][0]['targets'], {'temp_day': 22.0})

    def test_unknown_target_key_is_refused(self):
        """어휘를 고정하지 않으면 temp/temperature/t_day 가 섞여 들어온다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': '목표3', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'temperature': 22}}]})
        self.assertIsNone(out)
        self.assertIn('temperature', err or '')

    def test_target_out_of_range_is_refused(self):
        """범위는 항목 정의(`min`/`max`)가 정한다. 오류는 **라벨**로 말한다 —
        사람이 화면에서 보는 이름이 키가 아니라 라벨이기 때문이다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': '목표4', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'rh': 250}}]})
        self.assertIsNone(out)
        self.assertIn('Humidity', err or '')

    def test_ui_does_not_carry_its_own_target_vocabulary(self):
        """항목은 프로그램마다 다르다 — 화면이 목록을 갖고 있으면 사용자가 만든
        항목은 영영 안 보이고, 고정 항목을 늘려도 한쪽만 늘어난다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertNotIn('var _TARGETS = [', js)
        # 서버가 준 정의를 그린다.
        self.assertIn('State.defs', js)
        self.assertIn('p.target_defs', js)

        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertNotIn('var _TARGET_LABELS', popup)
        self.assertIn('t.label', popup)

    # ── 목표 항목 정의 (2026-08-20 재설계) ─────────────────────────────

    def test_kind_decides_the_fixed_items(self):
        """종류마다 목표가 다르다 — 축사 화면에 DLI·VPD 칸이 나오면 틀린 말이다.

        가축·시설·기타는 **고정 항목이 없다.** AoT 에 그 종류의 측정·제어 축이
        아직 없어, 근거 없이 지어낸 어휘를 화면에 내보내지 않는다.
        """
        from aot.aot_flask.geo import program_io

        veg = {d['key'] for d in program_io.fixed_target_defs('vegetation')}
        self.assertEqual(veg, {'temp_day', 'temp_night', 'rh', 'co2',
                               'dli', 'vpd'})
        for kind in ('livestock', 'facility', 'other'):
            self.assertEqual(program_io.fixed_target_defs(kind), [], kind)

    def test_fixed_items_cannot_be_deleted_but_can_be_hidden(self):
        """실제 시설이 모든 항목을 재지 못하는 것은 당연하다 — 안 쓰는 칸은
        숨겨 치우되, 어휘는 남는다(제어·AI 가 `co2` 를 계속 찾을 수 있어야 한다).
        """
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        # 고정 항목을 통째로 빼고 저장해도 서버가 되돌려 놓는다.
        out, err = program_io.update_program(row.unique_id, {'target_defs': []})
        self.assertIsNone(err)
        keys = [d['key'] for d in out['target_defs']]
        self.assertIn('co2', keys)

        # 숨기기는 받아들인다.
        defs = [dict(d, hidden=(d['key'] == 'co2')) for d in out['target_defs']]
        out, err = program_io.update_program(row.unique_id,
                                             {'target_defs': defs})
        self.assertIsNone(err)
        by_key = {d['key']: d for d in out['target_defs']}
        self.assertTrue(by_key['co2']['hidden'])
        self.assertFalse(by_key['rh']['hidden'])

    def test_user_item_needs_a_known_measurement_or_none(self):
        """오타를 받아 두면 "센서가 있는데 안 잡힌다" 를 나중에 만난다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        defs = program_io.fixed_target_defs('vegetation') + [
            {'key': 'ec', 'label': '배양액 EC', 'unit': 'dS/m',
             'measurement': 'no_such_measurement'}]
        out, err = program_io.update_program(row.unique_id,
                                             {'target_defs': defs})
        self.assertIsNone(out)
        self.assertIn('no_such_measurement', err or '')

        # 물리량을 고르지 않는 것은 정상이다 — 표시·조언 전용으로 남는다.
        defs[-1]['measurement'] = None
        out, err = program_io.update_program(row.unique_id,
                                             {'target_defs': defs})
        self.assertIsNone(err)
        by_key = {d['key']: d for d in out['target_defs']}
        self.assertIsNone(by_key['ec']['measurement'])
        self.assertFalse(by_key['ec']['fixed'])

    def test_user_item_value_is_accepted_once_defined(self):
        """정의에 있는 항목이라야 값이 들어간다 — 고아 값에는 그릴 라벨이 없다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        stages = [{'key': 'a', 'name': 'a', 'days': 10, 'targets': {'ec': 1.8}}]

        out, err = program_io.update_program(row.unique_id, {'stages': stages})
        self.assertIsNone(out)
        self.assertIn('ec', err or '')

        defs = program_io.fixed_target_defs('vegetation') + [
            {'key': 'ec', 'label': '배양액 EC', 'unit': 'dS/m',
             'measurement': 'electrical_conductivity_soil',
             'min': 0.0, 'max': 10.0}]
        out, err = program_io.update_program(
            row.unique_id, {'target_defs': defs, 'stages': stages})
        self.assertIsNone(err)
        self.assertEqual(out['stages'][0]['targets']['ec'], 1.8)

    def test_removing_an_item_that_still_has_values_is_refused(self):
        """조용히 지우지 않는다 — 화면이 값도 함께 지운 뒤 보내야 한다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        defs = program_io.fixed_target_defs('vegetation') + [
            {'key': 'ec', 'label': 'EC', 'unit': 'dS/m', 'measurement': None}]
        _, err = program_io.update_program(row.unique_id, {
            'target_defs': defs,
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'ec': 1.8}}]})
        self.assertIsNone(err)

        out, err = program_io.update_program(
            row.unique_id,
            {'target_defs': program_io.fixed_target_defs('vegetation')})
        self.assertIsNone(out)
        self.assertIn('ec', err or '')

    def test_switching_kind_starts_clean_not_with_leftovers(self):
        """식생→가축으로 바꾸면 DLI·VPD 가 "사용자 항목" 으로 둔갑해 남으면 안 된다.

        가축·시설은 **고정 항목 없이 빈 상태에서 시작**한다. 걸러내지 않으면 축사
        화면에 식생 항목이 그대로 남고, 라벨은 msgid 라 번역도 되지 않는다.
        """
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        out, err = program_io.update_program(row.unique_id, {'kind': 'livestock'})
        self.assertIsNone(err)
        self.assertEqual(out['kind'], 'livestock')
        self.assertEqual(out['target_defs'], [])

        # 사람이 만든 항목은 종류가 바뀌어도 남는다 — 그건 그 사람의 것이다.
        defs = [{'key': 'nh3', 'label': '암모니아', 'unit': 'ppm'}]
        out, err = program_io.update_program(row.unique_id, {'target_defs': defs})
        self.assertIsNone(err)
        self.assertEqual([d['key'] for d in out['target_defs']], ['nh3'])

        out, err = program_io.update_program(row.unique_id, {'kind': 'vegetation'})
        self.assertIsNone(err)
        keys = [d['key'] for d in out['target_defs']]
        self.assertIn('nh3', keys)          # 사용자 항목 보존
        self.assertIn('co2', keys)          # 식생 고정 항목 복귀

    def test_switching_kind_is_refused_when_values_would_be_orphaned(self):
        """조용히 지우지 않는다 — 무엇이 걸리는지 말하고 사람이 정하게 한다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        _, err = program_io.update_program(row.unique_id, {
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'co2': 800}}]})
        self.assertIsNone(err)

        out, err = program_io.update_program(row.unique_id, {'kind': 'livestock'})
        self.assertIsNone(out)
        self.assertIn('co2', err or '')
        self.assertIn('대상 종류', err or '')

    def test_program_default_covers_stages_that_do_not_override(self):
        """값을 단계마다 다시 적게 하면 4단계 × 6항목이 빈 칸 24개가 된다.

        목표는 대개 작기 내내 같고 달라지는 것은 일부다. 프로그램에 한 번 적고
        달라지는 단계에서만 덮어쓴다.
        """
        from aot.aot_flask.geo import program_io, plot_context

        row = self._program(source='user')
        defs = [dict(d, default=(70 if d['key'] == 'rh' else None))
                for d in program_io.fixed_target_defs('vegetation')]
        out, err = program_io.update_program(row.unique_id, {
            'target_defs': defs,
            'stages': [{'key': 'a', 'name': 'a', 'days': 10},
                       {'key': 'b', 'name': 'b', 'days': None,
                        'targets': {'rh': 85}}]})
        self.assertIsNone(err)

        from aot.databases.models import GeoProgram
        prow = GeoProgram.query.filter_by(unique_id=row.unique_id).first()

        # 덮어쓰지 않은 단계는 기본값을 따르고, 출처를 밝힌다.
        t0 = {t['key']: t for t in
              plot_context._stage_targets(prow.stage_list()[0], prow)}
        self.assertEqual(t0['rh']['value'], 70)
        self.assertEqual(t0['rh']['source'], 'default')

        # 덮어쓴 단계는 그 값이 이긴다.
        t1 = {t['key']: t for t in
              plot_context._stage_targets(prow.stage_list()[1], prow)}
        self.assertEqual(t1['rh']['value'], 85)
        self.assertEqual(t1['rh']['source'], 'stage')

    def test_default_is_range_checked_like_a_stage_value(self):
        """기본값도 목표값이다 — 검사를 건너뛰면 범위 밖 값이 조용히 들어간다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        defs = [dict(d, default=(250 if d['key'] == 'rh' else None))
                for d in program_io.fixed_target_defs('vegetation')]
        out, err = program_io.update_program(row.unique_id,
                                             {'target_defs': defs})
        self.assertIsNone(out)
        self.assertIn('Humidity', err or '')

    def test_ui_stage_shows_only_overridden_items(self):
        """단계마다 항목을 전부 그리면 쓰지 않는 빈 칸이 화면을 채운다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        # 덮어쓴 항목만 그리고, 나머지는 고르기로 꺼낸다.
        self.assertIn("defs.filter(function (d) { return t[d.key] != null; })", js)
        self.assertIn('data-tf-add', js)
        # 값은 항목 행에서 한 번 적는다.
        self.assertIn('data-def-val', js)

    def test_plant_only_fields_are_hidden_for_other_kinds(self):
        """축사 프로그램에 "광합성 지수" 가 떠 있으면 무엇을 적어야 할지 알 수 없고,
        알 수 없는 칸이 하나 있으면 화면 전체를 못 믿게 된다.

        광합성 모델 상수·기준온도(GDD)·관수/시비는 전부 **식물 개념**이다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertIn('function _isVeg()', js)
        # 광합성·기준온도·GDD 안내는 식생에서만 낸다.
        self.assertIn('var vegOnly = _isVeg()', js)
        # 단계의 적산온도 칸도 식생에서만.
        #
        # **들여쓰기까지 고정하지 않는다** — 단계 상세를 재배치할 때마다 공백이
        # 달라져 테스트가 깨지는데, 그때 확인해야 할 것은 "식생에서만 내는가"
        # 이지 "몇 칸 들여썼는가" 가 아니다(2026-08-21에 실제로 겪었다).
        import re as _re
        self.assertTrue(
            _re.search(r"_isVeg\(\)\s*\?\s*_stageField\(_T\('stage_gdd'", js),
            '단계 적산온도 칸이 _isVeg() 뒤에 있지 않다')
        # 관수·시비 역할도 식생에서만(그 밖은 역할 없는 자원 하나). P6 재설계로
        # 자리가 `_roleChoices()` 로 옮겨졌다 — 원칙은 같다.
        self.assertIn("return _isVeg() ? _RES_ROLES : ['other'];", js)

    def test_kind_and_defs_are_set_before_anything_reads_them(self):
        """순서가 뒤집히면 이번 렌더가 **직전 프로그램의 값**으로 그려진다.

        실제로 그랬다: 종류를 축사로 바꿔도 첫 번에는 광합성 칸이 그대로 남고,
        한 번 더 바꿔야 사라졌다(`_kindNow` 를 읽는 곳보다 뒤에서 세웠다).
        `State.defs` 도 같은 문제였다 — 단계 목표가 이전 정의로 그려진다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        set_kind = js.index("_kindNow = p.kind || 'vegetation';")
        set_defs = js.index('State.defs = (p.target_defs || [])')
        read_veg = js.index('var vegOnly = _isVeg()')
        # 단계는 이제 State 로 옮겨 담고(`State.stages = ...`) 거기서 그린다 —
        # 그 대입이 `_kindNow`·`State.defs` 보다 뒤여야 한다는 것은 같다.
        read_stages = js.index('State.stages = (p.stages || [])')
        self.assertLess(set_kind, read_veg)
        self.assertLess(set_kind, read_stages)
        self.assertLess(set_defs, read_stages)

    def test_multiline_input_is_not_a_pill(self):
        """`.aot-modern-input` 은 **한 줄 입력용**이라 알약 반경(9999px)을
        `!important` 로 건다. 그것이 여러 줄 textarea 에 걸리면 좌우가 통째로
        둥글어져 거대한 타원이 된다 — 이 저장소가 반복해서 겪는 문제다.

        그리고 공용 textarea 규칙은 코드 편집기용이라 `white-space: pre` 로 줄을
        접지 않는다. 지침은 산문이라 가로 스크롤이 아니라 줄바꿈이 맞다.

        규칙은 **공용 컴포넌트**에 있다(`components/aot-drawer-form.css`) —
        구획 운영 페이지(`/plots`)의 설정 드로어가 같은 골격을 쓰기 때문이다.
        예전처럼 `#veg-drawer-body` 로 묶어 두면 골격만 같고 그 골격을
        성립시키는 규칙이 안 따라가, 그쪽 지침 칸이 다시 타원이 된다.
        """
        css = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'css',
                                 'components', 'aot-drawer-form.css'))
        self.assertIn('border-radius: 16px !important', css)
        self.assertIn('white-space: pre-wrap !important', css)
        # id 가 아니라 클래스로 걸려야 두 드로어가 함께 받는다. 주석에는
        # 그 내력이 남아 있으므로 **셀렉터 줄만** 본다.
        self.assertIn('.aot-drawer-rows', css)
        selectors = [ln for ln in css.splitlines()
                     if '#veg-drawer-body' in ln and not ln.lstrip().startswith('*')]
        self.assertEqual([], selectors)
        # 두 드로어 모두 그 클래스를 달고 있어야 한다.
        for page in ('programs.html', 'plots.html'):
            html = _read(os.path.join(_ROOT, 'aot_flask', 'templates', 'pages',
                                      'geo', page))
            self.assertIn('aot-drawer-rows', html, page)
            self.assertIn('aot-drawer-form.css', html, page)

    def test_program_css_uses_only_defined_variables(self):
        """없는 CSS 변수를 쓰면 그 선언이 **통째로 무시된다** — gap 이 아예 안 걸리는데
        화면에는 아무 표시도 없다. 실제로 `--aot-space-xs`(존재하지 않음)를 썼었다.
        """
        import re
        root = os.path.join(_ROOT, 'aot_flask', 'static', 'css')
        defined = set()
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith('.css'):
                    continue
                for m in re.finditer(r'(--[a-z0-9-]+)\s*:',
                                     _read(os.path.join(dirpath, fn))):
                    defined.add(m.group(1))
        # **폴백이 없는 것만** 본다. `var(--x, 12px)` 는 변수가 없어도 폴백이
        # 받아 주므로 의도된 쓰임이다(이 파일에도 그런 줄이 있다). 폴백 없이
        # 없는 변수를 쓰는 것만이 선언을 통째로 잃는다.
        css = _read(os.path.join(root, 'pages', 'geo-program.css'))
        bare = set(re.findall(r'var\((--[a-z0-9-]+)\s*\)', css))
        missing = sorted(bare - defined)
        self.assertEqual(missing, [], '정의되지 않은 CSS 변수(폴백 없음): %s' % missing)

    def test_researched_targets_carry_their_source(self):
        """출처가 없으면 나중에 이 숫자를 고칠 사람이 판단할 근거가 없다 —
        지어낸 값과도 구분되지 않는다."""
        from aot.scripts.crop_target_sources import SOURCES, SPECIES_TARGETS
        from aot.scripts.seed_programs import catalog

        for crop, spec in SPECIES_TARGETS.items():
            self.assertIn(spec.get('src'), SOURCES, crop)
            src = SOURCES[spec['src']]
            self.assertTrue(src.get('title'), crop)

        by_key = {t['key']: t for t in catalog()}
        for crop in SPECIES_TARGETS:
            item = by_key[crop]
            self.assertTrue(item.get('notes'), crop)
            self.assertIn('출처', item['notes'], crop)

    def test_guidance_is_sourced_too(self):
        """지침은 범위 검사가 없어 **지어내기 가장 쉬운 자리**다. 그래서 본문과
        출처를 한 짝으로 요구하고(`_guidance_for`), 실제로 단계에 실리는지 본다.

        정본은 `seed_programs._STAGE_GUIDANCE` **한 곳**이다 — 목표값 표
        (`crop_target_sources`)에 두지 않는다. 두 곳에 두면 어느 쪽이 화면에
        나가는지 알 수 없게 된다.
        """
        import aot.scripts.crop_target_sources as cts
        from aot.scripts.seed_programs import _STAGE_GUIDANCE, catalog

        self.assertFalse(hasattr(cts, 'SPECIES_GUIDANCE'),
                         '지침 표가 두 곳에 있다')
        self.assertTrue(_STAGE_GUIDANCE, '지침이 비어 있다')
        for key, entry in _STAGE_GUIDANCE.items():
            self.assertEqual(len(entry), 2, key)      # (본문, 출처)
            self.assertTrue((entry[0] or '').strip(), key)
            self.assertTrue((entry[1] or '').strip(), key)

        # 표만 있고 안 실리면 아무도 못 읽는다.
        by_key = {t['key']: t for t in catalog()}
        for (crop, stage) in _STAGE_GUIDANCE:
            item = by_key[crop]
            got = {st['key'] for st in item['stages'] if st.get('guidance')}
            self.assertIn(stage, got, '%s/%s' % (crop, stage))
    def test_researched_values_stay_in_range(self):
        """범위를 벗어난 값은 저장 단계에서 거절된다 — 카탈로그가 그런 값을 들고
        있으면 그 템플릿은 영영 쓸 수 없다."""
        from aot.aot_flask.geo import program_io
        from aot.scripts.seed_programs import catalog

        for item in catalog():
            if item['scope'] != 'species':
                continue
            defs = item.get('target_defs')
            if not defs:
                continue
            cleaned, err = program_io._clean_target_defs(defs, 'vegetation')
            self.assertIsNone(err, '%s: %s' % (item['key'], err))
            for st in item['stages']:
                if not st.get('targets'):
                    continue
                _, terr = program_io._clean_targets(st['targets'], cleaned)
                self.assertIsNone(terr, '%s/%s: %s' % (item['key'], st['key'], terr))

    def test_fixed_defs_are_published_per_kind(self):
        """화면이 저장하지 않고 종류를 바꿔 볼 수 있어야 한다 — 그러려면 새 종류의
        고정 항목을 스스로 세울 수 있어야 한다."""
        from aot.aot_flask.geo import program_io

        for kind in program_io.VALID_KINDS:
            defs = program_io.fixed_target_defs(kind)
            self.assertIsInstance(defs, list)
        self.assertEqual(len(program_io.fixed_target_defs('vegetation')), 6)
        self.assertEqual(program_io.fixed_target_defs('livestock'), [])

    def test_guidance_is_kept_on_the_stage(self):
        """AI 도 사람도 이 글을 읽는다 — 저장되지 않으면 둘 다 못 본다."""
        from aot.aot_flask.geo import program_io

        row = self._program(source='user')
        out, err = program_io.update_program(row.unique_id, {
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'guidance': '  상토가 마르지 않게 관리한다.  '}]})
        self.assertIsNone(err)
        self.assertEqual(out['stages'][0]['guidance'],
                         '상토가 마르지 않게 관리한다.')

        # 빈 글은 키를 남기지 않는다 — 있는데 비었다로 읽히면 안 된다.
        out, err = program_io.update_program(row.unique_id, {
            'stages': [{'key': 'a', 'name': 'a', 'days': 10, 'guidance': '   '}]})
        self.assertIsNone(err)
        self.assertNotIn('guidance', out['stages'][0])

    def test_guidance_reaches_the_ai_not_just_the_screen(self):
        """구획을 조회한 AI 가 그 단계의 지침을 **받는다**.

        payload 에서 조용히 빠지면 AI 는 프로그램에 적힌 지침 대신 일반론으로
        답한다 — 답이 그럴듯해서 빠진 것을 아무도 눈치채지 못한다.
        """
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        prog = self._program(source='user', stages=[
            {'key': 'seedling', 'name': '육묘기', 'days': 21,
             'guidance': '상토가 마르지 않게 관리한다.'},
            {'key': 'harvest', 'name': '수확기', 'days': None},
        ])
        row, err = self._plant(program_uuid=prog.unique_id)
        self.assertIsNone(err)

        one = AoTDataToolService.get_plot(plot_id=row['unique_id'])
        self.assertEqual(one['plot']['stage']['guidance'],
                         '상토가 마르지 않게 관리한다.')

        # 목록 경로도 같아야 한다 — 상세만 실으면 "구획 여럿" 질문에서 빠진다.
        many = AoTDataToolService.list_plots(map_id='map-p')
        self.assertEqual(many['plots'][0]['stage']['guidance'],
                         '상토가 마르지 않게 관리한다.')

        # 프로그램 조회는 **모든** 단계의 지침을 낸다(다음 단계를 미리 묻는다).
        got = AoTDataToolService.get_program(program_id=prog.unique_id)
        self.assertEqual(got['program']['stages'][0]['guidance'],
                         '상토가 마르지 않게 관리한다.')

    def test_ai_is_told_the_guidance_field_exists(self):
        """payload 에 있는 것과 AI 가 쓰는 것은 다르다.

        도구 설명에 없는 필드는 모델이 존재를 모르거나, 알아도 일반 재배 지식보다
        우선할 이유를 모른다. 그래서 규칙이 **닿아야** 한다 — 슬림 매니페스트와
        MCP 페이로드 양쪽에서(한쪽만 고치면 인앱 AI 와 외부 MCP 클라이언트가
        서로 다른 계약을 읽는다).

        2026-08-25: `get_plot` 과 `list_plots` 는 규칙을 응답의 `_reading` 으로
        옮겼다. 설명에 전부 적어 두면 그 도구를 부르지 않는 대화까지 값을 치르기
        때문이다. **불변식은 그대로다** — 옮겼다고 규칙이 안 닿으면 이 테스트가
        지키려던 실패로 돌아간다. 그래서 두 갈래를 함께 본다: 설명에 `_reading`
        을 따르라는 포인터가 남아 있는가, 그리고 `_reading` 이 실제로 지침
        규칙을 내는가(지침이 있을 때와 없을 때 양쪽).
        """
        from aot.ai.services import tool_registry
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        # 선언 자리를 본다 — `manifest_system_tools()` 는 등급이 켜지면
        # 서랍 도구를 걸러내므로, 그 출력으로 검사하면 등급 설정에 따라 결과가
        # 갈린다(검사하려는 것은 설명 문구이지 노출 여부가 아니다).
        declared = {t.name: (t.manifest or {}).get('description') or ''
                    for t in tool_registry.TOOLS}
        mcp = {e['tool_name']: e.get('description') or ''
               for e in tool_registry.virtual_tools()}
        for surface, by_name in (('manifest', declared), ('mcp', mcp)):
            for name in ('get_plot', 'list_plots'):
                # 포인터 한 줄까지 지우면 모델은 `_reading` 을 그냥 지나치는
                # 데이터로 본다 — 이 테스트가 막으려는 바로 그것.
                self.assertIn('_reading', by_name.get(name, ''),
                              '%s/%s 설명에 _reading 포인터가 없다'
                              % (surface, name))

        # 그리고 포인터가 가리키는 곳이 실제로 규칙을 내야 한다 — 양쪽 분기 모두.
        wrote = AoTDataToolService._plot_reading_notes(
            {'stage': {'guidance': '상토가 마르지 않게 관리한다.'}})
        self.assertTrue(any('stage.guidance' in n and 'Quote it' in n
                            for n in wrote),
                        '지침이 있는데 인용하라는 규칙이 안 나왔다: %r' % wrote)
        none = AoTDataToolService._plot_reading_notes(
            {'stage': {'guidance': None}})
        self.assertTrue(any('null' in n for n in none),
                        '지침이 없는데 없다고 말하라는 규칙이 안 나왔다: %r' % none)

        # 제어 경로에는 싣지 않는다 — 지침은 제어를 바꾸지 않는다(설계 정본).
        from aot.aot_flask.geo import coordinator_plot
        import inspect
        self.assertNotIn(
            'guidance', inspect.getsource(coordinator_plot.control_targets),
            '지침이 제어 목표로 새어 들어갔다')

    def test_template_catalog_never_carries_unsourced_guidance(self):
        """지침은 범위 검사가 없어 **가장 지어내기 쉬운 필드**다.

        그래서 카탈로그의 규율은 하나다 — 본문과 출처를 함께 적지 않으면 실리지
        않는다. 지금은 `_STAGE_GUIDANCE` 가 비어 있어 아무 지침도 없고, 나중에
        누가 출처 없이 한 줄 적어 넣으면 여기서 걸린다.
        """
        from aot.scripts import seed_programs

        for item in seed_programs.catalog():
            filled = [st for st in item['stages'] if st.get('guidance')]
            if item['scope'] == 'category':
                # 소속 5종을 뭉뚱그린 자리라 어느 작물의 지침도 그 범위의 것이
                # 아니다 — 일수는 중앙값으로 요약되지만 산문은 요약되지 않는다.
                self.assertEqual(filled, [],
                                 '%s: 카테고리에는 지침을 붙이지 않는다'
                                 % item['key'])
                continue
            if not filled:
                self.assertIsNone(item.get('guidance_sources'))
                continue
            self.assertTrue(item.get('guidance_sources'),
                            '%s: 지침이 있는데 출처가 없다' % item['key'])

        # 출처가 빈 항목은 **거절이 아니라 누락**이다 — 시드가 실패해 카탈로그
        # 전체가 안 나오는 것보다 근거 없는 한 줄만 빠지는 편이 낫다.
        self.assertEqual(seed_programs._guidance_for('x', 'y'), (None, None))
        try:
            seed_programs._STAGE_GUIDANCE[('x', 'y')] = ('마르지 않게', '')
            self.assertEqual(seed_programs._guidance_for('x', 'y'), (None, None))
            seed_programs._STAGE_GUIDANCE[('x', 'y')] = ('마르지 않게', '어느 자료')
            self.assertEqual(seed_programs._guidance_for('x', 'y'),
                             ('마르지 않게', '어느 자료'))
        finally:
            seed_programs._STAGE_GUIDANCE.pop(('x', 'y'), None)

    def test_template_guidance_source_follows_into_the_programme(self):
        """지침만 남고 출처가 사라지면, 나중에 그 말을 고칠 사람이 판단할 재료가
        없다. 템플릿에서 만든 프로그램의 `source_note` 가 출처를 데리고 간다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py'))
        self.assertIn('guidance_sources', src,
                      'api_program_create 가 지침 출처를 source_note 로 옮기지 '
                      '않는다')

    def test_control_axis_is_found_by_measurement_not_by_key(self):
        """사용자가 이름을 붙여도 제어에 닿아야 한다 — 키로 찾으면 못 찾는다."""
        from aot.aot_flask.geo import coordinator_plot

        self.assertEqual(coordinator_plot.axis_of(
            {'key': 'co2_in', 'measurement': 'co2', 'shape': 'instant'}), 'co2')
        # DLI 는 순간 광량이 아니라 일적산이다.
        self.assertEqual(coordinator_plot.axis_of(
            {'key': 'x', 'measurement': 'radiation', 'shape': 'daily'}), 'dli')
        self.assertIsNone(coordinator_plot.axis_of(
            {'key': 'x', 'measurement': 'radiation', 'shape': 'instant'}))
        # 물리량이 없는 항목은 어느 축에도 닿지 않는다.
        self.assertIsNone(coordinator_plot.axis_of(
            {'key': 'nh3', 'measurement': None, 'shape': 'instant'}))

    def test_ambiguous_axis_picks_nothing(self):
        """둘 중 하나를 임의로 고르면 화면과 제어가 갈린다."""
        from aot.aot_flask.geo import coordinator_plot

        a = {'key': 'co2', 'measurement': 'co2', 'shape': 'instant',
             'fixed': True, 'value': 800}
        b = {'key': 'co2_in', 'measurement': 'co2', 'shape': 'instant',
             'fixed': False, 'value': 900}
        # 고정 항목이 이긴다.
        self.assertEqual(coordinator_plot._pick_by_axis([a, b])['co2'], a)
        # 고정 항목이 없고 후보가 둘이면 고르지 않는다.
        c = dict(b, key='co2_out')
        self.assertNotIn('co2', coordinator_plot._pick_by_axis([b, c]))

    def test_adding_a_program_opens_the_drawer(self):
        """추가하면 바로 고칠 수 있어야 한다 — 한 줄 늘어난 것만으로는
        사용자가 "이제 뭘 해야 하나" 를 알 수 없다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertIn('function focusName(', js)
        self.assertIn('openEditor(newId); focusName(newId);', js)

    def test_settings_open_in_a_drawer_with_a_save_button(self):
        """설정은 **드로어**에서 고친다(input 페이지와 같은 셸).

        인라인 편집에는 되돌릴 자리가 없었다 — 잘못 고치면 그대로 반영됐다.
        드로어는 저장을 눌러야 반영되므로, 닫으면 원래 값이 남는다.
        """
        tpl = _read(os.path.join(_ROOT, 'aot_flask', 'templates', 'pages', 'geo',
                                 'programs.html'))
        self.assertIn('aot-option-modal aot-widget-drawer', tpl)
        self.assertIn('id="veg-drawer-save"', tpl)
        self.assertIn('aot-widget-drawer.js', tpl)

        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        # 목록에 인라인 편집 영역을 남겨 두면 두 경로가 생긴다.
        self.assertNotIn('aot-entry-detail', js)
        self.assertIn("modal.setAttribute('data-config-uid-target', uuid)", js)

    def test_subject_is_not_asked_in_the_drawer(self):
        """품목(`subject`)은 **드로어에서 묻지 않는다**(2026-08-21).

        만들 때 정해지고(템플릿이면 그 대상, 빈 프로그램이면 이름과 같게) 뒤에
        바꿀 일이 없는 값인데, 화면에 두면 "이름과 무엇이 다른가" 를 설명해야
        하는 칸이 하나 더 생긴다. 실제로 이름이 "무" 인데 품목이 `cucumber` 인
        상태를 만들어 놓고도 무엇이 잘못인지 알기 어려웠다.

        여기서 고정하는 것은 **값이 조용히 지워지지 않는다** 는 것이다 — 칸이
        없으면 `collect` 가 키를 보내지 않고, 부분 저장 규칙상 서버가 기존 값을
        지킨다. 빈 값을 실어 보내면 그 규칙이 깨진다.
        """
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertNotIn('function _subjectRow(', js)
        self.assertNotIn("data-pf=\"subject\"", js)
        # 빈 값은 **보내지 않는다**(기존 값 보존).
        self.assertIn('if (!out.subject) delete out.subject;', js)
        # 새로 만들 때는 이름과 같게 — 아무도 못 고치는 자리표시자를 남기지 않는다.
        self.assertNotIn("_T('new_subject'", js)

    def test_program_kind_widens_beyond_vegetation(self):
        """식생은 대상 중 하나일 뿐이다 — 같은 구조가 가축·시설물·도로에도 쓰인다."""
        from aot.aot_flask.geo.program_io import VALID_KINDS
        self.assertEqual(VALID_KINDS,
                         ('vegetation', 'livestock', 'facility', 'other'))

        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertIn("var _KINDS = ['vegetation', 'livestock', 'facility', 'other']", js)

    def test_plot_pickers_never_mix_kinds(self):
        """다른 종류의 프로그램이 선택지에 섞이면 안 된다.

        예전에는 `kind=vegetation` 을 박아 두어 섞이지 않았다. 이제는 구획이
        종류를 가지므로 **그 구획의 종류로** 물어야 한다 — 박아 두면 가축 구획의
        선택지가 식생 프로그램이 되고, 그것을 고른 저장을 서버가 거절한다.
        """
        for path in (
            os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo', 'facility',
                         'plot-ui.js'),
            os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                         'aot-map-plot.js'),
        ):
            src = _read(path)
            self.assertIn("'/api/geo/programs?kind=' + encodeURIComponent(", src)
            self.assertNotIn('programs?kind=vegetation', src)

    def test_program_kind_is_validated(self):
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'lawn', 'kind': 'spaceship',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}]})
        self.assertIsNone(out)
        self.assertIn('종류', err or '')

        ok, err = program_io.create_program({
            'name': '잔디 관리', 'subject': 'lawn', 'kind': 'facility',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}]})
        self.assertIsNone(err)
        self.assertEqual(ok['kind'], 'facility')

    # ── 목표 곡선(Method) ───────────────────────────────────────────────
    def _method(self, name='곡선'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Method
        m = Method(name=name, method_type='Daily')
        db.session.add(m)
        db.session.commit()
        return m

    def test_target_method_is_stored_and_validated(self):
        from aot.aot_flask.geo import program_io
        m = self._method()
        out, err = program_io.create_program({
            'name': '곡선 프로그램', 'subject': 'lettuce',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}],
            'targets_methods': {'temp_day': m.unique_id}})
        self.assertIsNone(err)
        self.assertEqual(out['target_methods'], {'temp_day': m.unique_id})

    def test_dead_method_reference_is_refused(self):
        """죽은 참조를 두면 나중에 "곡선이 있는데 값이 안 나온다" 를 만난다."""
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': 'x', 'subject': 'lettuce',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}],
            'targets_methods': {'temp_day': 'no-such-method'}})
        self.assertIsNone(out)
        self.assertIn('메서드', err or '')

    def test_curve_keys_use_the_same_vocabulary_as_targets(self):
        from aot.aot_flask.geo import program_io
        m = self._method()
        out, err = program_io.create_program({
            'name': 'y', 'subject': 'lettuce',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10}],
            'targets_methods': {'temperature': m.unique_id}})
        self.assertIsNone(out)
        self.assertIn('temperature', err or '')

    def test_list_and_detail_return_the_same_shape(self):
        """상세에만 있는 키가 생기면 화면이 어느 쪽에서 왔는지에 따라 달라진다."""
        from aot.aot_flask.geo import program_io
        row = self._program(source='user')
        listed = program_io.to_dict(row, with_stages=False)
        detail = program_io.to_dict(row)
        self.assertIn('target_methods', listed)
        self.assertIn('target_methods', detail)
        self.assertTrue(set(listed).issubset(set(detail)))


class TestProgramSeed(unittest.TestCase):
    """템플릿 카탈로그 — **DB 에 미리 깔지 않는다**.

    쓰지도 않는 작물 7종이 목록에 먼저 들어가 있으면 사용자는 자기 것을 찾기 전에
    남의 것을 지나쳐야 한다. AoT 는 농장 전용이 아니라 공원·체육시설·교통시설에도
    쓰이므로 "채소 7종" 이 기본값인 것은 특히 좁다.
    """

    def test_catalog_reads_the_hardcoded_table(self):
        src = _read(os.path.join(_ROOT, 'scripts', 'seed_programs.py'))
        self.assertIn('from aot.ai.context.growth_stage_resolver import '
                      'STAGE_DURATION_MAP', src)
        self.assertIn('_CROP_PRESETS', src)
        # 단계 기간을 여기 다시 적으면 두 곳이 갈린다.
        self.assertNotIn("'seedling', 21", src)

    def test_nothing_is_installed_by_default(self):
        """카탈로그는 코드 상수다 — 화면에서 고를 때 비로소 만들어진다."""
        src = _read(os.path.join(_ROOT, 'scripts', 'seed_programs.py'))
        self.assertNotIn("source='builtin'", src.split('def purge_builtin')[0])
        self.assertIn('def purge_builtin(', src)

    def test_catalog_does_not_invent_targets(self):
        """**채워진 숫자는 빈 칸보다 강한 주장이다.**

        한 번 광합성 프리셋의 작물 단위 값을 모든 단계에 복사했다가 되돌렸다 —
        그것은 단계별 값이 아니고(육묘기와 착과기의 목표가 같을 리 없다), 사람은
        채워진 값을 "조사된 추천값" 으로 읽는다.

        그래서 목표는 **출처가 있는 작물에만** 들어간다(`crop_target_sources`).
        자료를 못 찾은 작물은 비어 있는 것이 옳다.
        """
        import importlib
        mod = importlib.import_module('aot.scripts.seed_programs')
        from aot.scripts.crop_target_sources import SPECIES_TARGETS
        items = mod.catalog()
        self.assertTrue(items)
        for t in items:
            sourced = t['key'] in SPECIES_TARGETS
            for st in t['stages']:
                if not sourced:
                    self.assertNotIn('targets', st,
                                     '%s 단계에 근거 없는 목표가 있다' % t['key'])
            if not sourced:
                for d in (t.get('target_defs') or []):
                    self.assertIsNone(d.get('default'), t['key'])

        # 시금치는 자료가 낮·밤을 나누지 않아 **목표를 비운 채 지침만** 남겼다.
        spinach = next(t for t in items if t['key'] == 'spinach')
        self.assertFalse(any(st.get('targets') for st in spinach['stages']))
        self.assertTrue(any(st.get('guidance') for st in spinach['stages']))
        # 광합성 파라미터는 **작물 단위 모델 상수**라 단계와 무관하다 — 그쪽은 싣는다.
        lettuce = next(t for t in items if t['key'] == 'lettuce')
        self.assertTrue(lettuce['photosynthesis'])

    def test_cumulative_days_become_stage_lengths(self):
        import importlib
        mod = importlib.import_module('aot.scripts.seed_programs')
        stages = mod._stages_from_cumulative([
            ('seedling', 21), ('vegetative', 56), ('harvest', 999)])
        self.assertEqual([s['days'] for s in stages], [21, 35, None])
        # 999 는 "끝까지" 다 — 길이로 옮기지 않는다.
        self.assertIsNone(stages[-1]['days'])



class TestEmptyStatesKeepTheirTitle(unittest.TestCase):
    """**연결된 것이 없어도 제목과 안내는 남는다.**

    빈 블록을 통째로 지우면 사용자는 "그 칸이 있다는 것" 조차 모른다 — 붙일
    것이 없는 것인지 화면이 덜 그려진 것인지 구분할 수단이 없다. 실제로 시설
    모달의 [현황]이 센서가 없으면 아무것도 안 그렸고, [환경·제어]는 제목 없이
    "액추에이터 없음" 한 줄만 떠 있었다(2026-08-19).
    """

    _POPUP = os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                          'widgets', 'AoT_map', 'aot-map-popup.js')
    _VECTOR = os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                           'widgets', 'AoT_map', 'aot-map-widget-vector.js')

    def test_env_now_block_survives_having_no_sensors(self):
        body = _read(self._POPUP).split('function buildEnvNowHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("_t('No sensors are linked to this place yet.')", body)
        # 제목 없이 빠져나가는 길이 없어야 한다.
        self.assertNotIn("return '';", body)

    def test_actuator_empty_state_carries_a_title(self):
        js = _read(self._POPUP)
        # 제목 없는 맨 안내문(옛 형태)이 되살아나면 잡는다.
        self.assertNotIn("'<div class=\"aot-act-empty\">'", js)
        # 어휘는 [환경]/[제어] 로 통일했다 — 빈 상태도 같은 제목을 쓴다.
        self.assertEqual(1, js.count("_emptyBlock(_t('Control'), _t('No actuators'))"))
        self.assertNotIn("_t('Actuators')", js)

    def test_sensor_section_is_seeded_so_the_tab_is_never_blank(self):
        """[환경·제어]의 센서 자리는 값이 없으면 렌더가 아예 안 돈다
        (`_renderBayChart` 가 `sensors.length` 에서 즉시 반환). 그래서 빈 상태는
        **처음 markup 에 심어** 둬야 한다 — 값이 붙으면 그 자리를 통째로
        갈아끼우므로 남지 않는다."""
        js = _read(self._VECTOR)
        # 시설 모달의 센서 자리 — 구역 팝업에도 같은 data-pane 이 있어 그쪽을
        # 집지 않도록 섹션 마크업에서 바로 자른다.
        sec = js.split('data-zone="sensors"', 1)[1][:800]
        self.assertIn('AoTMapPopup.emptyBlock(', sec)
        self.assertIn("'No sensors are linked to this place yet.'", sec)

    def test_status_tab_has_no_control_toggle(self):
        """자동 제어를 켜고 끄는 것은 시설 설정에서 하는 일이다. [현황]은
        "지금 어떤가" 만 말한다 — 조작 손잡이가 섞이면 상태를 보러 온 사람이
        설정 화면을 보게 된다(2026-08-20 사용자 지적)."""
        body = _read(self._POPUP).split('function buildOverviewSection', 1)[1].split(
            '\n  function ', 1)[0]
        for gone in ('aot-iec-toggle', 'Auto Control On', 'canToggle'):
            self.assertNotIn(gone, body, '현황에 조작 손잡이가 남아 있다: %s' % gone)
        # 응답 없음은 상태라 남는다 — 그때도 제목이 무엇에 대한 말인지 밝힌다.
        self.assertIn("_t('Automatic control')", body)

    def test_empty_state_titles_are_translated(self):
        """번역이 없으면 한국어 화면에 영어 한 줄만 남는다 — 빈 상태는 그 자체로
        드물어서 눈에 잘 안 띈다."""
        po = os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                          'LC_MESSAGES', 'messages.po')
        src = _read(po)
        for msgid in ('No sensors are linked to this place yet.',
                      'No automatic control is linked to this facility',
                      'Automatic control', 'Actuators', 'No actuators', 'Sensors'):
            needle = 'msgid "%s"\nmsgstr "' % msgid
            self.assertIn(needle, src, '%s 번역 없음' % msgid)
            after = src.split(needle, 1)[1].split('"', 1)[0]
            self.assertTrue(after.strip(), '%s 번역이 비어 있다' % msgid)


class _CoordPlotFixture(object):
    """코디네이터 × 구획 테스트의 공용 준비물.

    `unittest.TestCase` 를 상속하지 **않는다** — 상속하면 아래 두 클래스가
    서로의 테스트를 다시 실행한다(같은 검사를 두 번 도는 것도 문제지만, 실패가
    어느 쪽 것인지 읽을 수 없게 된다).
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from flask_babel import Babel

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'coord_plot.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController, GeoPlot, GeoProgram
        GeoPlot.query.delete()
        GeoProgram.query.delete()
        CustomController.query.delete()
        db.session.commit()

    _FAC = 'fac-coord-1'

    def _coord(self, facility=_FAC, bay='', pinned=None):
        import json
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController
        opts = {'geo_facility_id': facility, 'bay_scope': bay,
                'target_vpd': 1.1, 'target_co2': 700.0,
                'vpd_sp_type': 'static', 'co2_sp_type': 'static',
                'dli_target': 0.0}
        if pinned:
            opts['source_plot_id'] = pinned
        fn = CustomController(name='C', device='env_coordinator',
                              custom_options=json.dumps(opts))
        db.session.add(fn)
        db.session.commit()
        return fn

    def _plot(self, subject, bay=None, days_ago=5, ended_days_ago=None,
              facility=_FAC):
        # **날짜를 고정하지 않는다** — 프로그램 단계는 오늘 기준으로 계산되므로
        # 박아 둔 날짜는 시간이 지나면 `past_end` 가 되어, 어느 날 갑자기
        # "비교 행이 비었다" 로 실패한다(그렇게 한 번 겪었다).
        from datetime import date, timedelta
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot

        today = date.today()
        row = GeoPlot(geo_id='map-coord', kind='vegetation', subject=subject,
                      facility_uuid=facility, bay_id=bay,
                      started_on=today - timedelta(days=days_ago),
                      ended_on=(None if ended_days_ago is None
                                else today - timedelta(days=ended_days_ago)))
        db.session.add(row)
        db.session.commit()
        return row


class TestCoordinatorPlotResolver(_CoordPlotFixture, unittest.TestCase):
    """기준 구획 선택 규칙(R0~R5) — 정본 `plot_context.plot_for_coordinator`.

    설계: `docs/design/coordinator-plot-targets.md`.
    """

    # ── R2 / R3 / R4 ────────────────────────────────────────────────────

    def test_no_facility_says_so(self):
        from aot.aot_flask.geo import plot_context
        out = plot_context.plot_for_coordinator(self._coord(facility=''))
        self.assertEqual('no-facility', out['reason'])
        self.assertIsNone(out['plot'])

    def test_no_plot_leaves_the_coordinator_alone(self):
        """R2 — 후보가 없으면 아무것도 하지 않는다. **폴백을 없애지 말 것**:
        온실을 비워도 난방은 돌아야 한다."""
        from aot.aot_flask.geo import plot_context
        out = plot_context.plot_for_coordinator(self._coord())
        self.assertEqual('none', out['reason'])
        self.assertIsNone(out['plot'])

    def test_single_candidate_is_the_reference(self):
        from aot.aot_flask.geo import plot_context
        self._plot('상추')
        out = plot_context.plot_for_coordinator(self._coord())
        self.assertEqual('only', out['reason'])
        self.assertEqual('상추', out['plot']['subject'])

    def test_two_candidates_are_never_auto_picked(self):
        """R4 — 겹침(간작·혼작)이 정상인 도메인이라 자동 선택은 조용히 틀린다."""
        from aot.aot_flask.geo import plot_context
        self._plot('상추')
        self._plot('바질')
        out = plot_context.plot_for_coordinator(self._coord())
        self.assertEqual('ambiguous', out['reason'])
        self.assertIsNone(out['plot'])
        self.assertEqual(2, len(out['candidates']))

    def test_ended_plot_is_not_a_candidate(self):
        from aot.aot_flask.geo import plot_context
        self._plot('상추', days_ago=10, ended_days_ago=2)
        out = plot_context.plot_for_coordinator(self._coord())
        self.assertEqual('none', out['reason'])

    # ── R5 ──────────────────────────────────────────────────────────────

    def test_pinned_plot_wins_over_the_others(self):
        from aot.aot_flask.geo import plot_context
        a = self._plot('상추')
        self._plot('바질')
        out = plot_context.plot_for_coordinator(self._coord(pinned=a.unique_id))
        self.assertEqual('pinned', out['reason'])
        self.assertEqual('상추', out['plot']['subject'])

    def test_pinned_gone_is_reported_not_silently_replaced(self):
        """R5 — 지정이 사라지면 사실을 말한다. 조용히 다른 구획으로 갈아타면
        사람은 자기가 고른 것이 아직 쓰인다고 믿는다."""
        from aot.aot_flask.geo import plot_context
        self._plot('상추')
        out = plot_context.plot_for_coordinator(self._coord(pinned='gone-uuid'))
        self.assertTrue(out['pinned_missing'])
        self.assertEqual('gone-uuid', out['pinned'])   # 값은 지우지 않는다
        self.assertEqual('only', out['reason'])        # 나머지 규칙 재적용

    # ── 방향 비대칭 (의도된 것) ─────────────────────────────────────────

    def test_bay_coordinator_sees_a_facility_wide_plot(self):
        """구역 코디네이터 × 시설 전체 구획:
        `plots_in_facility`(내 구역에서 무엇이 자라나) → **포함**,
        `facility_control_for_plot`(이 구획을 맡는 제어가 누구냐) → **제외**.
        답이 달라야 하는 서로 다른 질문이라 둘을 같게 만들지 말 것."""
        from aot.aot_flask.geo import plot_context
        row = self._plot('상추', bay=None)
        out = plot_context.plot_for_coordinator(self._coord(bay='bay_1'))
        self.assertEqual('only', out['reason'])

        ctrl = plot_context.facility_control_for_plot(row)
        self.assertEqual([], ctrl['coordinators'])

    def test_other_bay_plot_is_not_a_candidate(self):
        from aot.aot_flask.geo import plot_context
        self._plot('상추', bay='bay_2')
        out = plot_context.plot_for_coordinator(self._coord(bay='bay_1'))
        self.assertEqual('none', out['reason'])


class TestCoordinatorPlotWiring(unittest.TestCase):
    """표시(Phase 1)의 배선 — 화면 두 곳이 **같은 구현**을 쓰는지."""

    _JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                       'aot-coordinator-plot.js')
    _POPUP = os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                          'widgets', 'AoT_map', 'aot-map-popup.js')
    _TPL = os.path.join(_ROOT, 'aot_flask', 'templates', 'pages',
                        'function_options', 'custom_function_options.html')

    def test_settings_page_has_the_anchor(self):
        """앵커는 **[연동 시설] 바로 아래**다 (2026-08-27 자리 이동).

        예전에는 함수 옵션 맨 위(`custom_function_options.html`)였다. 시설을
        고르면 따라오는 정보인데 고르기도 전에 읽게 됐다 — 사용자 지적:
        *"시설 옵션에서 시설을 선택하면 해당 시설에 달려오는 정보이므로 그
        이후에 짧은 요약만 제공하는 게 나아보임."*

        지금 자리는 옵션 배치의 `@status` 이고, 그 표식을 그리는 것이
        `Custom_Options.html` 의 `env_status` 갈래다. **요약 모드**로 붙는다 —
        표가 아니라 두 줄이다.
        """
        import os
        opts = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'templates', 'pages', 'form_options',
            'Custom_Options.html')
        src = _read(opts)
        self.assertIn('class="aot-coord-plot"', src)
        self.assertIn('data-summary="1"', src,
                      '요약 모드로 붙지 않았다 — 설정 화면에 표가 통째로 나온다')
        # 옛 자리에 되살아나면 같은 사실을 두 곳이 말한다.
        self.assertNotIn('class="aot-coord-plot"', _read(self._TPL),
                         '함수 옵션 맨 위에 다시 생겼다')

    def test_facility_modal_no_longer_lists_targets(self):
        """목표 목록은 [현황]에서 뺐다(2026-08-20) — 목표만 나열하면 "그래서
        지금 맞나" 에 답하지 못한 채 칸만 차지한다. 목표는 값 옆에 붙고
        (`buildEnvNowHtml`), 전체 목록은 그것을 정하는 함수 설정에서 본다."""
        src = _read(self._POPUP)
        self.assertNotIn('aot-coord-plot', src)
        # 로더 자체는 설정 화면이 그대로 쓴다 — 지우지 않았다.
        self.assertTrue(os.path.exists(self._JS))
        # 비교 규칙(어느 옵션과 견주는가)이 위젯 쪽에 복제되면 안 된다.
        for leaked in ('target_vpd', 'vpd_sp_type', 'gdd_target_daily'):
            self.assertNotIn(leaked, src)

    def test_loader_is_in_the_map_widget_bundle(self):
        """번들에 없으면 시설 모달의 앵커가 영영 안 채워진다(에러도 안 난다)."""
        import json
        cfg = json.load(open(os.path.join(
            _ROOT, 'aot_flask', 'static', 'js', 'tools', 'bundles.json'),
            encoding='utf-8'))
        self.assertIn('common/aot-coordinator-plot.js',
                      cfg['aot-map-widget']['inputs'])

    def test_the_only_write_is_picking_the_reference_plot(self):
        """목표는 프로그램에서 오고 제어가 매 사이클 읽는다 — 화면이 값을 옮길
        일이 없다. 쓰기가 하나라도 늘면 그 경로만 승인·권한 판단을 비켜간다."""
        import re
        js = _read(self._JS)
        posts = re.findall(r"fetch\('([^']+)'[\s\S]{0,120}?method: 'POST'", js)
        self.assertEqual(1, len(posts), '쓰기 경로는 하나여야 한다: %r' % (posts,))
        self.assertIn('/api/geo/coordinator/', posts[0])
        for verb in ('PUT', 'DELETE'):
            self.assertNotIn("method: '%s'" % verb, js)

    def test_the_automatic_path_only_reads(self):
        """`load()` 는 화면이 열릴 때마다 저절로 돈다 — 거기서 쓰면 아무도 누른
        적 없는 설정 변경이 일어난다."""
        js = _read(self._JS)
        body = js.split('  function load(el) {', 1)[1].split('\n  function ', 1)[0]
        self.assertNotIn('POST', body)

    def test_empty_compact_card_removes_itself(self):
        """시설 모달에는 [구획] 블록이 이미 있다 — 빈 카드가 또 서면 같은 사실을
        두 블록이 각자 적는다."""
        js = _read(self._JS)
        body = js.split('function render(', 1)[1].split('\n  function ', 1)[0]
        self.assertIn('if (compact) { el.remove(); return; }', body)



class TestControlReadsTheProgram(_CoordPlotFixture, unittest.TestCase):
    """제어가 읽는 목표의 정본은 **프로그램**이다.

    코디네이터에는 목표 옵션이 없다 — 있으면 같은 사실이 두 곳에 남고, 사람이
    어느 쪽을 고쳐야 하는지 매번 판단해야 한다.
    """

    def _program(self, targets, photo=None, methods=None, source='user',
                 reviewed=True):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoProgram
        from aot.utils.time_utils import utc_now
        prog = GeoProgram(name='P', kind='vegetation', subject='상추',
                          source=source,
                          reviewed_at=(utc_now() if reviewed else None),
                          stages=[{'key': 'veg', 'name': '생육', 'days': 30,
                                   'targets': targets}],
                          targets_methods=methods,
                          photosynthesis=photo or {})
        db.session.add(prog)
        db.session.commit()
        return prog

    def _linked(self, **kw):
        from aot.aot_flask.extensions import db
        prog = self._program(**kw)
        row = self._plot('상추')
        row.program_uuid = prog.unique_id
        db.session.commit()
        return row

    def test_targets_come_from_the_running_stage(self):
        from aot.aot_flask.geo import coordinator_plot
        self._linked(targets={'vpd': 0.9, 'co2': 800, 'dli': 14},
                     photo={'gdd_daily': 13.0, 'T_base': 4.0})
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual('ok', t['reason'])
        self.assertEqual(0.9, t['vpd']['value'])
        self.assertEqual(800.0, t['co2']['value'])
        self.assertEqual(14.0, t['dli'])
        self.assertEqual(13.0, t['gdd_daily'])
        self.assertEqual(4.0, t['T_base'])

    def test_curve_comes_from_the_program_not_the_function(self):
        """곡선 선택도 프로그램에 있다 — 예전에는 `vpd_sp_type='method'` 와
        `vpd_method_id` 를 함수에 또 설정해야 했다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import coordinator_plot
        from aot.databases.models import Method
        m = Method(name='VPD 곡선', method_type='setpoint')
        db.session.add(m)
        db.session.commit()
        self._linked(targets={'vpd': 0.9}, methods={'vpd': m.unique_id})

        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual(m.unique_id, t['vpd']['method_id'])
        # 곡선이 걸린 항목은 숫자를 미리 정하지 않는다 — 제어가 Method 를 돌린다.
        self.assertIsNone(t['vpd']['value'])

    def test_started_on_is_the_schedule(self):
        """주차 진행의 기준은 구획의 시작일이다. 함수에 날짜를 또 적지 않는다."""
        from aot.aot_flask.geo import coordinator_plot
        row = self._linked(targets={'vpd': 0.9})
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual(row.started_on, t['started_on'])

    def test_unreviewed_ai_program_is_not_used_for_control(self):
        """AI 가 지어낸 단계 목표가 곧바로 온실 설정이 되지 않게 하는 장치를
        여기서 우회하면 그 장치가 통째로 무의미해진다."""
        from aot.aot_flask.geo import coordinator_plot
        self._linked(targets={'vpd': 0.9}, source='ai', reviewed=False)
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual('program-unreviewed', t['reason'])
        self.assertIsNone(t['vpd']['value'])

    def test_no_plot_is_not_an_error(self):
        """구획 없는 시설이 정상 구성이다 — 목표 없이 guide 범위로 돈다."""
        from aot.aot_flask.geo import coordinator_plot
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual('none', t['reason'])
        self.assertIsNone(t['vpd']['value'])
        self.assertIsNone(t['dli'])

    def test_plot_without_a_program_says_so(self):
        from aot.aot_flask.geo import coordinator_plot
        self._plot('상추')
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual('no-program', t['reason'])

    # ── 옵션에서 걷어낸 것이 되살아나지 않게 ────────────────────────────

    _INFO = os.path.join(_ROOT, 'functions', 'custom_functions',
                         'env_coordinator_impl', '_function_info.py')
    _COORD = os.path.join(_ROOT, 'functions', 'custom_functions',
                          'env_coordinator.py')

    def test_the_duplicated_options_are_gone(self):
        src = _read(self._INFO)
        for oid in ('target_vpd', 'target_co2', 'dli_target', 'gdd_target_daily',
                    'vpd_sp_type', 'co2_sp_type', 'vpd_method_id', 'co2_method_id',
                    'schedule_start_time', 'target_source',
                    # 작물이 무엇인가도 프로그램이 안다 — 코드에 박힌 5종 중
                    # 하나를 함수에서 또 고르면 실제로 심긴 것과 갈린다.
                    'crop_preset'):
            self.assertNotIn("'id': '%s'" % oid, src,
                             '%s 가 되살아났다 — 설정이 다시 두 곳이 된다' % oid)

    def test_the_safety_options_stay(self):
        """걷어낸 것은 목표뿐이다. 안전 가이드라인과 장비는 이 시설의 것이라
        프로그램으로 옮기면 그 프로그램을 다른 시설에 못 쓴다.

        ⚠ `schedule_week_offset` 은 2026-08-27 에 **뺐다**(설계문서 D19).
          그것은 안전 설정이 아니라 **구획 시작일의 보정값**이었다 — 작기
          도중에 설치했다면 구획 `started_on` 에 실제 파종일을 적으면 되고,
          같은 사실을 두 곳에 적으면 갈라진다. 로컬 3개 전부 0 이었다.
        """
        src = _read(self._INFO)
        for oid in ('temp_max', 'temp_min', 'humid_max', 'humid_min',
                    'guide_T_min', 'guide_T_max', 'guide_RH_min', 'guide_RH_max',
                    'schedule_end_time'):
            self.assertIn("'id': '%s'" % oid, src, '%s 가 사라졌다' % oid)
        self.assertNotIn("'id': 'schedule_week_offset'", src,
                         '주차 오프셋이 되살아났다 — 구획 시작일이 정본이다')

    def test_preset_no_longer_writes_targets(self):
        """프리셋이 목표를 채우던 경로(자동 동기화·강제 적용 버튼)는 없어졌다.
        남아 있으면 프로그램 값을 저장만으로 되돌린다."""
        src = _read(self._COORD)
        for gone in ('_sync_crop_targets', '_CROP_PRESET_OPTION_MAP',
                     'cmd_apply_crop_targets'):
            self.assertNotIn(gone, src)

    def test_setpoints_read_the_plot(self):
        helpers = _read(os.path.join(
            _ROOT, 'functions', 'custom_functions', 'env_coordinator_impl',
            '_helpers_mixin.py'))
        for fn_name in ('_get_vpd_setpoint', '_get_co2_setpoint'):
            body = helpers.split('def %s' % fn_name, 1)[1].split('\n    def ', 1)[0]
            self.assertIn('_plot_targets()', body)
            self.assertNotIn('self.target_', body)

    def test_cycle_clears_the_cache(self):
        """사이클 안에서는 한 번만 읽는다 — 항목마다 읽으면 한 사이클에서 서로
        다른 목표를 보게 된다."""
        cyc = _read(os.path.join(
            _ROOT, 'functions', 'custom_functions', 'env_coordinator_impl',
            '_cycle_mixin.py'))
        body = cyc.split('def _run_cycle', 1)[1][:800]
        self.assertIn('self._plot_targets_cache = None', body)


class TestModelConstantsComeFromTheProgram(_CoordPlotFixture, unittest.TestCase):
    """Big-Leaf 모델 상수도 프로그램이 정본이다.

    예전에는 코드에 박힌 작물 5종 중 하나를 코디네이터 설정에서 골랐다 — 같은
    작물을 프로그램과 함수 두 곳에서 정하는 셈이었고, 함수에서 고른 것이 실제로
    심긴 것과 다를 수 있었다.
    """

    def _linked(self, photo):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoProgram
        prog = GeoProgram(name='P', kind='vegetation', subject='상추',
                          stages=[{'key': 'veg', 'name': '생육', 'days': 30,
                                   'targets': {'vpd': 0.9}}],
                          photosynthesis=photo)
        db.session.add(prog)
        db.session.commit()
        row = self._plot('상추')
        row.program_uuid = prog.unique_id
        db.session.commit()
        return row

    def test_model_constants_are_carried(self):
        from aot.aot_flask.geo import coordinator_plot
        self._linked({'A_max': 30.0, 'K_L': 150.0, 'K_C': 800.0,
                      'T_opt': 20.0, 'T_sigma': 7.0, 'VPD_half': 0.9,
                      'T_base': 4.0})
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual(30.0, t['model']['A_max'])
        self.assertEqual(0.9, t['model']['VPD_half'])
        self.assertEqual(4.0, t['T_base'])

    def test_keys_match_the_control_side_dataclass(self):
        """이름이 갈리면 값이 조용히 무시된다 — 그때 모델은 기본값으로 돈다."""
        from aot.functions.utils.env_control.photosynthesis import CropParams
        from aot.aot_flask.geo import coordinator_plot
        for key in coordinator_plot.MODEL_KEYS:
            self.assertTrue(hasattr(CropParams(), key), '%s 가 CropParams 에 없다' % key)

    def test_no_plot_means_generic_defaults(self):
        """기를 것이 없으면 최적화할 대상도 없다 — 옛 동작(함수에서 고른
        프리셋)으로 되돌리면 다시 두 곳에서 작물을 정하게 된다."""
        from aot.aot_flask.geo import coordinator_plot
        t = coordinator_plot.control_targets(self._coord())
        self.assertEqual({}, t['model'])

    def test_editor_saves_every_model_key(self):
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        from aot.aot_flask.geo import coordinator_plot
        for key in coordinator_plot.MODEL_KEYS:
            self.assertIn("key: '%s'" % key, js, '%s 편집란이 없다' % key)
        self.assertIn('[data-photo]', js)

    def test_server_validates_them(self):
        """틀린 값이 들어가도 에러가 나지 않는다 — 모델이 엉뚱한 제한 요인을
        고를 뿐이다. 그래서 저장할 때 한 번 본다."""
        from aot.aot_flask.geo import program_io
        self.assertIsNone(program_io._check_photosynthesis({'A_max': 25}))
        self.assertTrue(program_io._check_photosynthesis({'A_max': 'x'}))
        self.assertTrue(program_io._check_photosynthesis({'VPD_half': 99}))
        # 모르는 키는 거부하지 않는다 — 어휘가 늘 때 저장이 막히면 안 된다.
        self.assertIsNone(program_io._check_photosynthesis({'future_key': 1}))


class TestPlotTimeline(_CoordPlotFixture, unittest.TestCase):
    """기간 축 — 시작·현재·단계 경계를 한 줄로.

    계산은 **서버에만** 둔다. 단계 길이·기준점(P5)·"끝까지" 단계 처리가 전부
    여기 규칙이라, 화면이 다시 조립하면 두 곳이 곧 갈린다.
    """

    def _linked(self, stages, days_ago=2):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoProgram
        prog = GeoProgram(name='P', kind='vegetation', subject='상추',
                          stages=stages)
        db.session.add(prog)
        db.session.commit()
        row = self._plot('상추', days_ago=days_ago)
        row.program_uuid = prog.unique_id
        db.session.commit()
        return row

    _S3 = [{'key': 'a', 'name': '육묘기', 'days': 3},
           {'key': 'b', 'name': '생육기', 'days': 7},
           {'key': 'c', 'name': '수확기', 'days': None}]

    def test_segments_span_the_axis(self):
        from aot.aot_flask.geo import plot_context
        tl = plot_context.timeline(self._linked(self._S3))
        self.assertEqual(0.0, tl['stages'][0]['from_pct'])
        self.assertEqual(100.0, tl['stages'][-1]['to_pct'])
        for a, b in zip(tl['stages'], tl['stages'][1:]):
            self.assertEqual(a['to_pct'], b['from_pct'], '구간 사이가 벌어졌다')

    def test_current_stage_is_marked_once(self):
        from aot.aot_flask.geo import plot_context
        tl = plot_context.timeline(self._linked(self._S3, days_ago=4))
        cur = [s for s in tl['stages'] if s['current']]
        self.assertEqual(1, len(cur))
        self.assertEqual('생육기', cur[0]['name'])

    def test_open_ended_program_has_no_end_date(self):
        """마지막 단계가 "끝까지" 면 종료일을 **지어내지 않는다** — 축에 날짜를
        적으면 화면이 "그날 끝난다" 고 말하게 된다."""
        from aot.aot_flask.geo import plot_context
        tl = plot_context.timeline(self._linked(self._S3))
        self.assertTrue(tl['open_end'])
        self.assertIsNone(tl['end'])
        # 열린 구간도 폭은 있어야 한다 — 0 이면 축에서 사라진다.
        self.assertGreater(tl['stages'][-1]['to_pct'],
                           tl['stages'][-1]['from_pct'])

    def test_closed_program_gets_an_end_date(self):
        from aot.aot_flask.geo import plot_context
        stages = [{'key': 'a', 'name': '1', 'days': 3},
                  {'key': 'b', 'name': '2', 'days': 7}]
        tl = plot_context.timeline(self._linked(stages))
        self.assertFalse(tl['open_end'])
        self.assertEqual(10, tl['total_days'])
        self.assertIsNotNone(tl['end'])

    def test_past_the_end_is_not_clamped(self):
        """예정을 넘긴 것 자체가 정보다 — 100%로 잘라 버리면 늦었다는 사실이
        화면에서 사라진다."""
        from aot.aot_flask.geo import plot_context
        stages = [{'key': 'a', 'name': '1', 'days': 2}]
        tl = plot_context.timeline(self._linked(stages, days_ago=10))
        self.assertGreater(tl['today_pct'], 100.0)

    def test_carried_in_the_control_brief(self):
        """시설 모달이 읽는 payload 에 실려야 화면이 그린다."""
        from aot.aot_flask.geo import plot_context
        row = self._linked(self._S3)
        brief = plot_context.plot_brief_for_control(row)
        self.assertIn('timeline', brief)
        self.assertTrue(brief['timeline']['stages'])

    def test_client_does_not_recompute(self):
        """화면은 서버가 준 퍼센트만 쓴다 — 단계 길이를 다시 더하기 시작하면
        기준점·열린 구간 처리가 곧 갈린다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                'AoT_map', 'aot-map-popup.js'))
        body = js.split('function _timelineHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('st.to_pct', body)
        self.assertIn('tl.today_pct', body)
        for gone in ('days_ago', 'Date.now()', 'new Date('):
            self.assertNotIn(gone, body, '화면이 기간을 다시 계산한다: %s' % gone)


# ── 카드에서 뺄 항목 — 구획은 상위 것을 물려받는다 ────────────────────────
#
# 구획의 [현재]에 뜨는 값은 구획이 가진 것이 아니다(시설 구획이면 그 동·시설,
# 노지 구획이면 그 구역의 센서). 같은 센서인데 창을 옮겼다고 다른 항목이 보이면
# 사용자는 두 화면 중 어느 쪽이 맞는지 알 방법이 없다.
#
# **깨져도 조용하다.** 물려받기가 끊기면 구획 창에만 감춘 항목이 도로 나타나는데,
# 에러는 없고 그 화면만 아는 사람이 아니면 눈치채기 어렵다. 반대로 구획에 [설정]
# 버튼이 생기면, 거기서 고친 것이 그 시설·구역을 보는 **다른 사람의 화면**을
# 함께 바꾼다(rep_key 를 구획 창에 넘기지 않는 것과 같은 이유).
class TestPlotInheritsHiddenRows(unittest.TestCase):

    _ROUTES = os.path.join(_ROOT, 'aot_flask', 'routes_geo_plot.py')
    _WIDGET = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                           'AoT_map', 'aot-map-widget-vector.js')

    def test_both_builders_emit_it(self):
        """시설 구획·노지 구획 **둘 다**. 한쪽만 내면 그쪽 창만 조용히 갈린다 —
        서버에 `/contents` 빌더가 둘이라는 것 자체가 이미 한 번 데인 자리다."""
        src = _read(self._ROUTES)
        for fn in ('_build_facility_plot_contents', '_build_plot_contents'):
            body = src.split('def %s' % fn, 1)[1].split('\ndef ', 1)[0]
            self.assertIn(
                "'hidden_rows'", body,
                '%s 가 hidden_rows 를 내지 않는다 — 그 경로의 구획 창만 '
                '상위 설정을 무시한다' % fn)

    def test_source_is_where_the_values_come_from(self):
        """시설 구획은 시설, 노지 구획은 구역. 시설 구획도 zone_uuid 를 가질 수
        있지만(시설이 구역 안에 있으면) 그 구역은 값을 주지 않는다."""
        # `routes_geo_plot` 을 바로 임포트하면 `routes_geo_device_split` 과의
        # 순환 임포트에 걸린다 — 실제 앱과 같은 순서로 `routes_geo` 를 먼저
        # 태운다(이 파일의 다른 클래스가 setUpClass 에서 하는 것과 같다).
        # 이 검사는 앱 컨텍스트가 필요 없어 그 클래스에 얹지 않았다.
        import aot.aot_flask.routes_geo  # noqa: F401
        from aot.aot_flask import routes_geo_plot as routes
        from aot.aot_flask.geo import site_summary
        calls = {}

        def _fac(uuid):
            calls['facility'] = uuid
            return {'now': ['RH']}

        def _shape(uuid):
            calls['shape'] = uuid
            return {'now': ['T']}

        # DB 를 켜지 않고 **어느 쪽을 보는지**만 본다 — 이 검사가 지키는 것은
        # 조회 결과가 아니라 출처 선택이다.
        real_fac = site_summary.hidden_rows_for_facility
        real_shape = site_summary.hidden_rows_for_shape
        site_summary.hidden_rows_for_facility = _fac
        site_summary.hidden_rows_for_shape = _shape
        try:
            self.assertEqual(
                routes._inherited_hidden_rows(facility_uuid='F', zone_uuid='Z'),
                {'now': ['RH']})
            self.assertEqual(calls.get('facility'), 'F')
            self.assertNotIn('shape', calls,
                             '시설이 있는데 구역까지 봤다 — 값을 주지 않는 쪽이다')
            calls.clear()
            self.assertEqual(routes._inherited_hidden_rows(zone_uuid='Z'),
                             {'now': ['T']})
            self.assertEqual(calls.get('shape'), 'Z')
        finally:
            site_summary.hidden_rows_for_facility = real_fac
            site_summary.hidden_rows_for_shape = real_shape

    def test_missing_parent_hides_nothing(self):
        """상위를 못 찾은 것과 상위가 아무것도 감추지 않은 것은 화면에서 같은
        결과라야 한다 — 못 찾았다고 전부 감추면 구획 창이 통째로 빈다."""
        from aot.aot_flask.geo import site_summary
        self.assertEqual(site_summary.hidden_rows_for_shape(None), {})
        self.assertEqual(site_summary.hidden_rows_for_facility(None), {})

    def test_client_applies_it_but_offers_no_button(self):
        """구획 창은 물려받은 것을 적용만 한다. `configurable` 을 넘기면 거기서
        고친 것이 상위를 바꾼다 — 저장이 상위에 있기 때문이다."""
        js = _read(self._WIDGET)
        # 구획 창의 `/contents` 한 곳만 본다 — 짧은 조각으로 자르면 다른 창의
        # 코드까지 딸려 들어와 `configurable` 이 거기서 걸린다.
        body = js.split("'/api/geo/plot/' + encodeURIComponent(plotUuid) +",
                        1)[1].split('_renderZoneDevices', 1)[0]
        self.assertIn('hidden_rows', body,
                      '구획 창이 물려받은 설정을 읽지 않는다')
        # **주석은 빼고 본다.** 왜 안 넘기는지를 적어 둔 주석에 그 낱말이
        # 들어 있어, 그대로 세면 설명을 쓴 것만으로 검사가 깨진다.
        code = '\n'.join(
            l.split('//', 1)[0] for l in body.splitlines())
        self.assertNotIn(
            'configurable', code,
            '구획 창에 [설정] 버튼이 생겼다 — 고치면 그 시설·구역을 보는 '
            '다른 사람의 화면이 함께 바뀐다')


class TestPlotStageSchedule(unittest.TestCase):
    """P8 — 구획이 일정을 고친다.

    프로그램은 **참고**고, 경계는 구획이 갖는다. 정본:
    docs/design/program-layer.md §P8
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'sched.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoProgram, GeoPlotStageEvent
        for model in (GeoPlotStageEvent, GeoPlot, GeoProgram):
            model.query.delete()
        db.session.commit()

    _S3 = [{'key': 's1', 'name': '1', 'days': 10},
           {'key': 's2', 'name': '2', 'days': 10},
           {'key': 's3', 'name': '3', 'days': None}]

    def _linked(self, days_ago=0, stages=None, **over):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot, GeoProgram
        from datetime import timedelta

        prog = GeoProgram(name='P', kind='vegetation', subject='토마토',
                          stages=stages if stages is not None else self._S3)
        db.session.add(prog)
        db.session.commit()
        saved, err = plot_io.save_plot({
            'map_uuid': 'map-p', 'subject': '토마토',
            'started_on': (date.today() - timedelta(days=days_ago)).isoformat(),
            'program_uuid': prog.unique_id,
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(0.0, 0.0, 0.001)}})
        self.assertIsNone(err)
        for k, v in over.items():
            setattr(GeoPlot.query.filter_by(
                unique_id=saved['unique_id']).first(), k, v)
        db.session.commit()
        return GeoPlot.query.filter_by(unique_id=saved['unique_id']).first()

    # ── 승인 전에는 넘어가지 않는다 ──────────────────────────────────────
    def test_stage_is_held_at_the_anchor_until_confirmed(self):
        """제어가 이 값을 읽는다 — 고정하지 않으면 화면이 "확인하시겠습니까" 를
        묻는 동안 목표 온도가 이미 다음 단계 값으로 바뀌어 있다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s1',
                             started_on=(date.today()
                                         - timedelta(days=25)).isoformat())
        st = plot_context.stage_of(row)
        self.assertEqual(st['key'], 's1', '확인하지 않았는데 넘어갔다')
        self.assertIsNotNone(st.get('pending'),
                             '앞서간 사실 자체는 남아야 한다')
        self.assertEqual(st['pending']['stage_key'], 's3')
        self.assertTrue(st['overdue_days'] > 0)

    def test_auto_advance_plots_are_not_held(self):
        """"확인 없이 넘어가도 된다" 는 결정이 이미 있다. 고정하면 아무도 상세
        화면을 열지 않는 동안 그 구획의 목표가 멈춘다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25, auto_advance=True)
        plot_io.accept_stage(row.unique_id, stage_key='s1',
                             started_on=(date.today()
                                         - timedelta(days=25)).isoformat())
        self.assertEqual(plot_context.stage_of(row)['key'], 's3')

    def test_plots_without_a_ledger_behave_as_before(self):
        """승인은 한 번 누른 시점부터 의미를 갖는다(§P5) — 이 예외가 없으면
        업그레이드가 기존 구획 전부의 단계를 첫 단계로 얼린다."""
        from aot.aot_flask.geo import plot_context
        row = self._linked(days_ago=25)
        self.assertEqual(plot_context.stage_of(row)['key'], 's3')

    def test_the_proposal_still_sees_past_the_hold(self):
        """제안은 "앞서갔다" 는 사실 자체다 — 고정된 값을 보면 영영 뜨지 않는다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s1',
                             started_on=(date.today()
                                         - timedelta(days=25)).isoformat())
        pr = plot_context.stage_proposal(row)
        self.assertIsNotNone(pr)
        self.assertEqual(pr['stage_key'], 's3')

    # ── 연기·앞당김 ──────────────────────────────────────────────────────
    def test_postponing_a_boundary_moves_the_ones_after_it(self):
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        before = plot_context.stage_schedule(row)['boundaries']
        base_s2 = before[1]['starts_on']
        base_s3 = before[2]['starts_on']

        out, err = plot_io.shift_stage(row.unique_id, stage_key='s2', days=7)
        self.assertIsNone(err)
        after = plot_context.stage_schedule(row)['boundaries']
        self.assertEqual((after[1]['starts_on'] - base_s2).days, 7)
        self.assertEqual((after[2]['starts_on'] - base_s3).days, 7,
                         '뒤 단계가 함께 밀려야 한다')

    def test_the_programme_value_releases_the_pin(self):
        """화면에 되돌리기 버튼이 없다 — 표준으로 돌아가는 수단은 입력 칸 안에
        있다. 박아 두어도 날짜는 같지만 뜻이 다르다: 박힌 경계는 프로그램을
        고쳐도 따라오지 않는다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        row = self._linked(days_ago=0)
        plot_io.set_stage_days(row.unique_id, {'s1': 15})
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        self.assertIn('s2', row.stage_plan or {})

        plot_io.set_stage_days(row.unique_id, {'s1': 10})   # 프로그램 값
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        self.assertNotIn('s2', row.stage_plan or {})

    def test_pinning_the_next_boundary_absorbs_the_change(self):
        """"이 단계만 늘리고 다음은 그대로" 는 다음 경계도 함께 박으면 된다 —
        모드 플래그를 만들지 않는 이유다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        keep = plot_context.stage_schedule(row)['boundaries'][2]['starts_on']
        out, err = plot_io.set_stage_plan(row.unique_id, {
            's2': (keep - timedelta(days=3)).isoformat(),
            's3': keep.isoformat()})
        self.assertIsNone(err)
        after = plot_context.stage_schedule(row)['boundaries']
        self.assertEqual(after[2]['starts_on'], keep)

    def test_relative_moves_are_stored_as_absolute_dates(self):
        """상대값을 저장하면 앞 단계가 밀릴 때 그 7일이 어느 날이었는지 조용히
        달라진다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        row = self._linked(days_ago=0)
        plot_io.shift_stage(row.unique_id, stage_key='s2', days=7)
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        self.assertIn('s2', row.stage_plan)
        self.assertRegex(row.stage_plan['s2']['started_on'],
                         r'^\d{4}-\d{2}-\d{2}$')

    def test_stage_length_is_the_editing_unit(self):
        """사람이 고치는 값은 **그 단계가 며칠인가**다(2026-08-24).

        날짜를 직접 받으면 계산을 사람이 떠안는다 — "육묘를 닷새 더" 를 말하려고
        정식일을 머릿속에서 더해야 한다. 프로그램이 이미 단계마다 며칠로 적으므로
        같은 어휘를 쓴다.
        """
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)          # s1 10일 · s2 10일 · s3 끝까지
        before = plot_context.stage_schedule(row)['boundaries']
        out, err = plot_io.set_stage_days(row.unique_id, {'s1': 15})
        self.assertIsNone(err)
        after = plot_context.stage_schedule(row)['boundaries']
        self.assertEqual((after[1]['starts_on'] - before[1]['starts_on']).days, 5)
        self.assertEqual((after[2]['starts_on'] - before[2]['starts_on']).days, 5,
                         '뒤 단계가 함께 밀려야 한다')

    def test_lengths_are_applied_cumulatively(self):
        """앞 단계를 늘린 뒤의 뒤 단계 기간은 **밀린 자리에서** 세야 한다.
        각자 원래 자리에서 세면 앞의 변경이 두 번 반영된다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        start = plot_context.stage_schedule(row)['boundaries'][0]['starts_on']
        out, err = plot_io.set_stage_days(row.unique_id, {'s1': 15, 's2': 20})
        self.assertIsNone(err)
        b = plot_context.stage_schedule(row)['boundaries']
        self.assertEqual((b[1]['starts_on'] - start).days, 15)
        self.assertEqual((b[2]['starts_on'] - start).days, 35)

    def test_the_length_lands_as_a_date(self):
        """기간을 그대로 저장하면 앞 단계가 밀릴 때 그것이 가리키던 날이 조용히
        달라진다 — 받은 즉시 날짜로 환산한다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        row = self._linked(days_ago=0)
        plot_io.set_stage_days(row.unique_id, {'s1': 15})
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        self.assertIn('s2', row.stage_plan)
        self.assertRegex(row.stage_plan['s2']['started_on'],
                         r'^\d{4}-\d{2}-\d{2}$')

    def test_the_last_stage_has_no_length_to_set(self):
        """끝내는 날은 재배 종료가 정한다 — 마지막 단계에는 다음 경계가 없다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        out, err = plot_io.set_stage_days(row.unique_id, {'s3': 30})
        self.assertIsNone(out)
        self.assertIn('마지막 단계', err)
        view = plot_context.stage_schedule_view(row)
        self.assertFalse(view[-1]['editable'])
        self.assertTrue(view[0]['editable'])

    def test_the_view_reports_the_real_length_and_the_standard(self):
        """화면이 고치는 값은 **실제 기간**이고, 프로그램이 적은 값은 따로 낸다 —
        둘을 한 칸에 담으면 "표준과 다른가" 를 말할 수 없다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        plot_io.set_stage_days(row.unique_id, {'s1': 15})
        view = plot_context.stage_schedule_view(row)
        self.assertEqual(view[0]['days'], 15)
        self.assertEqual(view[0]['program_days'], 10)

    def test_a_boundary_that_already_passed_cannot_be_planned(self):
        """지나간 경계를 옮기는 일은 원장(확인·되돌리기)이 하는 일이다 — 두
        수단이 같은 값을 다투면 무엇이 정본인지 알 수 없다."""
        from aot.aot_flask.geo import plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s2',
                             started_on=(date.today()
                                         - timedelta(days=10)).isoformat())
        out, err = plot_io.set_stage_plan(
            row.unique_id, {'s1': date.today().isoformat()})
        self.assertIsNone(out)
        self.assertIn('지나간', err)

    def test_a_boundary_cannot_land_before_the_one_before_it(self):
        """읽는 쪽에서 조용히 바로잡으면 사람이 적은 값과 화면이 보이는 값이
        갈린다 — 저장 전에 거절한다."""
        from aot.aot_flask.geo import plot_io

        row = self._linked(days_ago=0)
        out, err = plot_io.set_stage_plan(
            row.unique_id,
            {'s2': (date.today() - timedelta(days=1)).isoformat()})
        self.assertIsNone(out)
        self.assertIn('빠릅니다', err)

    def test_confirming_clears_the_plans_behind_it(self):
        """남겨 두면 되돌리기를 했을 때 지워진 줄 알았던 옛 계획이 되살아난다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        row = self._linked(days_ago=0)
        plot_io.shift_stage(row.unique_id, stage_key='s2', days=3)
        plot_io.accept_stage(
            row.unique_id, stage_key='s2',
            started_on=(date.today() + timedelta(days=13)).isoformat())
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        self.assertNotIn('s2', row.stage_plan or {})

    def test_the_plan_reaches_the_expected_end(self):
        """2주 미룬 구획이 여전히 옛 날짜로 끝난다고 말하면 안 된다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0, stages=[
            {'key': 's1', 'name': '1', 'days': 10},
            {'key': 's2', 'name': '2', 'days': 10}])
        before, _ = plot_context.expected_end(row)
        plot_io.shift_stage(row.unique_id, stage_key='s2', days=7)
        after, src = plot_context.expected_end(row)
        self.assertEqual((after - before).days, 7)
        self.assertEqual(src, 'program')

    def test_the_axis_shows_who_set_each_boundary(self):
        """프로그램과 달라진 구간이 보여야 "참고는 프로그램, 실제는 이것" 이
        이해된다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        plot_io.shift_stage(row.unique_id, stage_key='s2', days=7)
        tl = plot_context.timeline(row)
        got = [st['source'] for st in tl['stages']]
        self.assertEqual(got[1], 'planned')

    def test_a_plan_alone_delays_the_stage(self):
        """원장이 없어도 계획은 듣는다 — 연기의 값은 "아직 안 넘어갔다" 다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=11)          # 11일차 = 원래는 2단계
        self.assertEqual(plot_context.stage_of(row)['key'], 's2')
        plot_io.shift_stage(row.unique_id, stage_key='s2', days=5)
        self.assertEqual(plot_context.stage_of(row)['key'], 's1',
                         '미뤘는데도 다음 단계로 넘어가 있다')

    def test_the_table_marks_the_same_stage_the_header_does(self):
        """표의 '지금' 과 "현재 단계" 줄이 서로 다른 칸을 가리키면 사람은 어느
        쪽을 믿을지 매번 고른다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s1',
                             started_on=(date.today()
                                         - timedelta(days=25)).isoformat())
        st = plot_context.stage_of(row)
        view = plot_context.stage_schedule_view(row)
        cur = [v for v in view if v['state'] == 'current']
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0]['index'], st['index'])

    def test_past_stages_keep_their_dates(self):
        """자동 승인이 3단계를 한 번에 따라잡으면 1·2단계에는 원장 줄이 없다.
        그렇다고 빈 칸으로 두면 표가 "이 작기가 어떻게 흘러왔나" 를 답하지
        못한다 — 확인 전까지 따르던 일정이 곧 그 답이다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s3',
                             started_on=(date.today()
                                         - timedelta(days=5)).isoformat())
        view = plot_context.stage_schedule_view(row)
        past = [v for v in view if v['index'] < 3]
        self.assertEqual(len(past), 2)
        self.assertTrue(all(v['starts_on'] for v in past),
                        '지나간 단계가 빈 칸으로 남았다: %s' % past)
        # 1단계는 시작일에서, 2단계는 프로그램 길이로 이어진다.
        self.assertEqual(past[0]['starts_on'],
                         (date.today() - timedelta(days=25)).isoformat())
        self.assertEqual(past[1]['starts_on'],
                         (date.today() - timedelta(days=15)).isoformat())

    def test_the_axis_keeps_the_stages_already_passed(self):
        """기준점 이후만 그리면 3단계가 확인된 구획의 축이 3단계에서 시작해,
        그 작기가 어떻게 흘러왔는지가 화면에서 사라진다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s3',
                             started_on=(date.today()
                                         - timedelta(days=5)).isoformat())
        tl = plot_context.timeline(row)
        keys = [st['key'] for st in tl['stages']]
        self.assertEqual(keys, ['s1', 's2', 's3'],
                         '지나간 단계가 축에서 사라졌다: %s' % keys)
        # 축의 왼쪽 끝은 **시작일**이고, 기준점은 확인된 전환의 날이다.
        self.assertEqual(tl['start'],
                         (date.today() - timedelta(days=25)).isoformat())
        self.assertEqual(tl['anchor'],
                         (date.today() - timedelta(days=5)).isoformat())

    def test_the_axis_marks_the_same_stage_the_header_does(self):
        """축이 자기 폭으로 따로 고르면 승인 대기로 고정된 구획에서 축은 녹협을,
        "현재 단계" 줄은 수확을 가리킨다 — 실제로 그렇게 갈렸다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s3',
                             started_on=(date.today()
                                         - timedelta(days=5)).isoformat())
        st = plot_context.stage_of(row)
        tl = plot_context.timeline(row)
        cur = [x for x in tl['stages'] if x['current']]
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0]['key'], st['key'])

    def test_the_axis_stays_monotonic_when_the_ledger_jumps_ahead(self):
        """확인된 전환이 프로그램의 날짜 계산보다 앞서 있을 수 있다(자동 승인이
        어긋난 날을 적었거나 사람이 건너뛰었을 때).

        그때 앞 단계의 파생 날짜가 기준점을 넘어서면 칸 폭이 음수가 되고, "오늘"
        마커는 앞 칸에 찍히는데 현재 단계는 뒤 칸으로 표시된다 — 화면이 자기와
        모순된다. 앞 칸들을 기준점에 붙이고 폭 0 으로 둔다.
        """
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        # 6단계 × 10일 = 60일짜리인데, 25일차에 마지막 단계가 확인돼 있다.
        row = self._linked(days_ago=25, stages=[
            {'key': 'a', 'name': '1', 'days': 10},
            {'key': 'b', 'name': '2', 'days': 10},
            {'key': 'c', 'name': '3', 'days': 10},
            {'key': 'd', 'name': '4', 'days': 10},
            {'key': 'e', 'name': '5', 'days': None}])
        plot_io.accept_stage(row.unique_id, stage_key='e',
                             started_on=(date.today()
                                         - timedelta(days=5)).isoformat())
        tl = plot_context.timeline(row)

        prev = None
        for st in tl['stages']:
            if not st['starts_on']:
                continue
            if prev is not None:
                self.assertGreaterEqual(st['starts_on'], prev,
                                        '축의 날짜가 거꾸로 간다: %s' % tl['stages'])
            prev = st['starts_on']

        # "오늘" 은 현재로 표시된 칸 **안**에 있어야 한다.
        cur = [x for x in tl['stages'] if x['current']][0]
        self.assertEqual(cur['key'], plot_context.stage_of(row)['key'])
        self.assertGreaterEqual(tl['today_pct'], cur['from_pct'])
        self.assertLessEqual(tl['today_pct'], cur['to_pct'])

    def test_the_detail_payload_carries_the_schedule(self):
        """서버가 알고 화면이 못 받으면 고칠 자리가 없다."""
        from aot.aot_flask.geo import plot_context
        row = self._linked(days_ago=0)
        out = plot_context.to_dict(row)
        self.assertTrue(out.get('stage_schedule'))
        self.assertIn('auto_advance', out)

    # ── 구획만의 단계 구성 (2026-08-24) ─────────────────────────────────
    def test_a_stage_can_be_dropped_for_this_plot_only(self):
        """육묘 없이 바로 정식하는 작기가 있다. 프로그램을 고치면 그 프로그램을
        쓰는 모든 구획이 함께 바뀌므로, 뺀 사실은 구획이 든다."""
        from aot.aot_flask.geo import plot_context, plot_io
        from aot.databases.models import GeoProgram

        row = self._linked(days_ago=0)
        out, err = plot_io.remove_stage(row.unique_id, stage_key='s1')
        self.assertIsNone(err)
        keys = [v['key'] for v in plot_context.stage_schedule_view(row)]
        self.assertEqual(keys, ['s2', 's3'])
        # 프로그램은 그대로다.
        prog = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
        self.assertEqual([st['key'] for st in prog.stage_list()],
                         ['s1', 's2', 's3'])

    def test_a_passed_stage_cannot_be_dropped(self):
        """확인된 전환이 가리키는 단계를 없애면 그때 무엇을 했는지의 답이 사라진다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_io

        row = self._linked(days_ago=25)
        plot_io.accept_stage(row.unique_id, stage_key='s2',
                             started_on=(date.today()
                                         - timedelta(days=10)).isoformat())
        out, err = plot_io.remove_stage(row.unique_id, stage_key='s1')
        self.assertIsNone(out)
        self.assertIn('지나간', err)

    def test_the_last_stage_standing_cannot_be_dropped(self):
        from aot.aot_flask.geo import plot_io
        row = self._linked(days_ago=0, stages=[{'key': 'only', 'name': '하나',
                                                'days': None}])
        out, err = plot_io.remove_stage(row.unique_id, stage_key='only')
        self.assertIsNone(out)
        self.assertIn('마지막 남은', err)

    def test_a_stage_can_be_added_to_this_plot(self):
        """표준 프로그램에 자리가 없는 일(추비)을 이 작기에만 넣는다."""
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=0)
        out, err = plot_io.add_stage(row.unique_id, name='추비', days=5,
                                     after='s1')
        self.assertIsNone(err)
        view = plot_context.stage_schedule_view(row)
        self.assertEqual([v['name'] for v in view], ['1', '추비', '2', '3'])
        # 끼운 만큼 뒤가 밀린다 — 일정은 하나의 규칙으로 돈다.
        self.assertEqual(view[2]['starts_on'],
                         (date.today() + timedelta(days=15)).isoformat())

    def test_an_added_stage_can_be_taken_back_out(self):
        """더한 단계를 뺄 때 `removed` 에 적으면 프로그램에 없는 키가 영영 남는다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        row = self._linked(days_ago=0)
        out, err = plot_io.add_stage(row.unique_id, name='추비', days=5,
                                     after='s1')
        key = out['stage_key']
        plot_io.remove_stage(row.unique_id, stage_key=key)
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        ov = row.stage_override_map()
        self.assertEqual(ov['added'], [])
        self.assertNotIn(key, ov['removed'])

    def test_guidance_can_be_written_where_the_programme_left_none(self):
        """카탈로그 프로그램은 지침을 비운 채로 온다 — 없어도 적을 수 있어야 한다."""
        from aot.aot_flask.geo import plot_context, plot_io
        from aot.databases.models import GeoProgram

        row = self._linked(days_ago=0)
        out, err = plot_io.set_stage_guidance(row.unique_id, stage_key='s2',
                                              text='정식 전 이틀 물 끊기')
        self.assertIsNone(err)
        view = plot_context.stage_schedule_view(row)
        got = [v['guidance'] for v in view if v['key'] == 's2'][0]
        self.assertEqual(got, '정식 전 이틀 물 끊기')
        # 프로그램은 그대로다 — 같은 프로그램을 쓰는 다른 구획이 함께 바뀌면 안 된다.
        prog = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
        self.assertIsNone(prog.stage_list()[1].get('guidance'))

    def test_guidance_survives_a_confirmed_transition(self):
        """경계 날짜는 확정보다 앞선 것이 지워진다. 지침이 그 규칙을 타면 지나간
        단계에 적어 둔 관찰이 전환 한 번에 사라진다."""
        from datetime import timedelta
        from aot.aot_flask.geo import plot_context, plot_io

        row = self._linked(days_ago=25)
        plot_io.set_stage_guidance(row.unique_id, stage_key='s1',
                                   text='올해는 늦서리가 왔다')
        plot_io.accept_stage(row.unique_id, stage_key='s2',
                             started_on=(date.today()
                                         - timedelta(days=10)).isoformat())
        view = plot_context.stage_schedule_view(row)
        got = [v['guidance'] for v in view if v['key'] == 's1'][0]
        self.assertEqual(got, '올해는 늦서리가 왔다')

    def test_the_schedule_can_become_a_reusable_programme(self):
        """구획에서 맞춰 놓은 것이 그 구획 안에만 있으면 다음 작기·옆 밭이 같은
        일을 처음부터 다시 한다. 담기는 것은 **지금 따르는** 목록이고, 기간은
        표준이 아니라 실제 날수다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoProgram

        row = self._linked(days_ago=0)
        plot_io.set_stage_days(row.unique_id, {'s1': 15})
        plot_io.add_stage(row.unique_id, name='추비', days=5, after='s1')
        plot_io.set_stage_guidance(row.unique_id, stage_key='s2',
                                   text='정식 전 이틀 물 끊기')

        out, err = plot_io.save_as_program(row.unique_id, name='내 콩 표준')
        self.assertIsNone(err)
        prog = GeoProgram.query.filter_by(
            unique_id=out['program']['unique_id']).first()
        got = [(st.get('name'), st.get('days'), st.get('guidance'))
               for st in prog.stage_list()]
        # 1단계를 15일로 잡아 s2 경계를 박아 두었고, 그 사이에 추비 5일을
        # 끼웠다 — 박힌 경계는 고정이므로 1단계가 10일로 줄어든다. 등록되는 값은
        # **표준이 아니라 지금 실제로 따르는 기간**이라 그 10이 담긴다.
        self.assertEqual(got, [('1', 10, None), ('추비', 5, None),
                               ('2', 10, '정식 전 이틀 물 끊기'),
                               ('3', None, None)])
        self.assertEqual(prog.source, 'user')
        self.assertEqual(prog.subject, row.subject)

    def test_registering_does_not_move_the_plot(self):
        """등록은 **복사**다. 진행 중인 작기의 해석이 등록 한 번에 바뀌면
        "그때 무엇을 목표로 길렀나" 의 답이 조용히 달라진다."""
        from aot.aot_flask.geo import plot_io
        from aot.databases.models import GeoPlot

        row = self._linked(days_ago=0)
        before = row.program_uuid
        out, err = plot_io.save_as_program(row.unique_id, name='복사본')
        self.assertIsNone(err)
        row = GeoPlot.query.filter_by(unique_id=row.unique_id).first()
        self.assertEqual(row.program_uuid, before)
        self.assertNotEqual(out['program']['unique_id'], before)

    def test_registering_twice_does_not_collide_on_the_name(self):
        from aot.aot_flask.geo import plot_io
        row = self._linked(days_ago=0)
        a, err = plot_io.save_as_program(row.unique_id, name='같은 이름')
        self.assertIsNone(err)
        b, err = plot_io.save_as_program(row.unique_id, name='같은 이름')
        self.assertIsNone(err)
        self.assertNotEqual(a['program']['name'], b['program']['name'])

    def test_a_planned_boundary_turns_gdd_off(self):
        """사람이 날짜를 잡았는데 적산온도가 그것을 앞질러 가면 그 편집이
        무의미해진다(선언 > 계획 > GDD > 경과일)."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_context.py'))
        body = src.split('def stage_of(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("not sched['planned']", body)


class TestValveCoverageCost(unittest.TestCase):
    """밸브가 덮는 구획 — **값은 그대로, 일은 덜 하게** (2026-08-24).

    구획 창을 열 때마다 `plots_by_valve_device` 가 돈다. 밸브마다 모든 구획의
    기하를 **다시 파싱**하고 있어서(밸브 16 × 구획 23 = 368회) 창 하나에 24ms
    를 물었다. 기하는 한 번만 만들고, 경계 상자로 먼저 걸러 낸다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'cov.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot
        GeoPlot.query.delete()
        db.session.commit()

    def _plot(self, name, lng, lat, size=0.001):
        from aot.aot_flask.geo import plot_io
        saved, err = plot_io.save_plot({
            'map_uuid': 'map-c', 'subject': name,
            'started_on': date.today().isoformat(),
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(lng, lat, size)}})
        self.assertIsNone(err)
        return saved

    def test_the_bbox_filter_does_not_change_the_answer(self):
        """상자로 거르는 것은 **걸러 내기에만** 쓴다 — 통과한 쌍은 그대로
        정확히 계산한다. 값이 달라지면 "무엇이 함께 젖는가" 가 틀린 답이 된다."""
        from aot.aot_flask.geo import plot_context

        near = self._plot('가까운', 0.0, 0.0)
        self._plot('먼', 5.0, 5.0)
        active = plot_context.active_plots('map-c')

        # 첫 구획에 겹치는 도형 하나.
        got = plot_context.plots_covered_by_shape(
            _square(0.0005, 0.0005, 0.001), 'map-c', candidates=active)
        self.assertEqual([g['unique_id'] for g in got], [near['unique_id']])

        # 아무것도 안 겹치는 도형.
        self.assertEqual(plot_context.plots_covered_by_shape(
            _square(90.0, 45.0, 0.001), 'map-c', candidates=active), [])

    def test_prepared_geometry_gives_the_same_answer(self):
        """기하를 미리 만들어 넘겨도 답이 같아야 한다 — 다르면 밸브마다 다른
        구획 목록이 나온다."""
        from aot.aot_flask.geo import plot_context

        self._plot('가', 0.0, 0.0)
        self._plot('나', 0.0005, 0.0)
        active = plot_context.active_plots('map-c')
        shape = _square(0.0003, 0.0, 0.0012)

        plain = plot_context.plots_covered_by_shape(
            shape, 'map-c', candidates=active)
        prepared = {r.unique_id: plot_context._shapely(
            plot_context.geometry_of(r)) for r in active}
        fast = plot_context.plots_covered_by_shape(
            shape, 'map-c', candidates=active, prepared=prepared)
        self.assertEqual(plain, fast)
        self.assertTrue(plain, '겹치는 구획을 하나도 못 찾았다')

    def test_the_geometry_is_built_once_per_plot(self):
        """밸브마다 같은 구획을 다시 파싱하면 밸브 수 × 구획 수가 된다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'geo', 'plot_context.py'))
        body = src.split('def plots_by_valve_device', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('prepared=prepared', body,
                      '밸브마다 기하를 다시 만든다')


class TestPlotScheduleWiring(unittest.TestCase):
    """화면·마이그레이션 배선 — 서버만 맞고 화면이 안 부르면 아무 일도 안 난다."""

    _PLOT_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                            'AoT_map', 'aot-map-plot.js')
    _POPUP_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                             'AoT_map', 'aot-map-popup.js')

    def test_the_modal_can_postpone_as_well_as_confirm(self):
        """연기할 수단이 없으면 사람이 할 수 있는 것은 "예정대로 갔다" 뿐이다."""
        js = _read(self._PLOT_JS)
        self.assertIn('aot-ov-plot-stage-defer', js)
        self.assertIn("'/schedule'", js)

    def test_the_schedule_card_sits_in_the_settings_tab(self):
        """[현황]은 "지금 어떤가" 를 답하는 자리다. 일정을 짜는 것은 그 구획을
        어떻게 기를지 정하는 일이라 작물·시작일을 고치는 자리(기본 정보) 다음에
        있어야 한다."""
        html = _read(self._POPUP_JS)
        about = html.split('function _plotAboutHtml(', 1)[1].split('\n  function ', 1)[0]
        overview = html.split('function _plotOverviewHtml(', 1)[1].split('\n  function ', 1)[0]
        self.assertIn('_plotScheduleHtml(p)', about)
        self.assertNotIn('_plotScheduleHtml(p)', overview)
        # 기본 정보(Basics) 다음이다 — 그 앞에 끼면 편집 폼과 사이가 갈린다.
        self.assertLess(about.index("_t('Basics')"),
                        about.index('_plotScheduleHtml(p)'))

    def test_the_schedule_card_is_rendered(self):
        html = _read(self._POPUP_JS)
        self.assertIn('_plotScheduleHtml', html)
        # 고치는 칸은 **기간(일)** 이다 — 날짜 입력으로 되돌리지 말 것(사람이
        # 계산을 떠안는다, 2026-08-24).
        self.assertIn('aot-ov-sched-days', html)
        self.assertIn('aot-ov-plot-auto', html)
        # 되돌리기 버튼은 두지 않는다 — 프로그램과 같은 값을 적으면 풀린다.
        self.assertNotIn('aot-ov-plot-sched-reset', html)

    def test_the_plot_modal_shows_a_skeleton_while_loading(self):
        """구획 창은 조회가 끝난 뒤에야 떴다 — 그 왕복 동안 화면에는 아무 일도
        일어나지 않아 누른 사람은 눌린 줄을 모른다. 구역·시설 창처럼 껍데기를
        먼저 띄운다.

        껍데기는 **같은 골격**이어야 한다(같은 헤더·같은 탭). 도착하는 순간 창이
        다시 그려지는 것처럼 보이면 자리막이를 두는 뜻이 없다.
        """
        popup = _read(self._POPUP_JS)
        self.assertIn('function buildPlotModalSkeleton', popup)
        skel = popup.split('function buildPlotModalSkeleton', 1)[1] \
                    .split('\n  function ', 1)[0]
        for part in ('buildModalHeader', 'buildSectionNav', 'skeleton('):
            self.assertIn(part, skel, '껍데기가 진짜 창과 다른 골격이다: %s' % part)
        self.assertIn('buildPlotModalSkeleton:', popup, '내보내지 않았다')

        js = _read(self._PLOT_JS)
        open_fn = js.split('function openModal(', 1)[1].split('\n    function ', 1)[0]
        # 껍데기를 **조회보다 먼저** 띄운다.
        self.assertLess(open_fn.index('buildPlotModalSkeleton'),
                        open_fn.index("fetch('/api/geo/plot/"),
                        '조회가 끝난 뒤에 창을 연다')
        # 실패해도 자리막이가 영영 남지 않는다.
        self.assertIn('Failed to load data.', open_fn)

    def test_registering_sits_at_the_bottom_of_the_programme_card(self):
        """무엇을 따르고 있는지 말하는 자리가 [프로그램] 카드다 — "이것을
        프로그램으로 만든다" 도 같은 자리에서 이어진다. 단계 일정 카드에 두면
        [단계 더하기] 바로 아래에 또 다른 여닫는 버튼이 서서 둘이 한 벌처럼
        읽힌다."""
        html = _read(self._POPUP_JS)
        prog = html.split('function _plotProgramHtml(', 1)[1] \
                   .split('\n  function ', 1)[0]
        sched = html.split('function _plotScheduleHtml(', 1)[1] \
                    .split('\n  function ', 1)[0]
        self.assertIn('aot-ov-sched-regopen', prog)
        self.assertNotIn('aot-ov-sched-regopen', sched)
        # 카드의 **맨 아래**다 — 단계 기록 다음.
        self.assertLess(prog.index('_plotStageHistoryHtml'),
                        prog.index('aot-ov-sched-regopen'))

    def test_the_back_arrow_is_wired_from_the_detail_not_the_contents(self):
        """제목줄의 뒤로가기가 `/contents` 응답에서만 드러났다. 그 조회는
        센서·환경·밸브를 함께 끌어오는 무거운 것이라(실측 250ms 대 상세 17ms),
        창이 다 그려진 뒤에도 화살표만 한참 뒤에 튀어나왔다.

        상위가 누구인지는 구획 상세에 이미 들어 있다 — 거기서 배선한다.
        """
        js = _read(self._PLOT_JS)
        open_fn = js.split('function openModal(', 1)[1] \
                    .split('\n    function ', 1)[0]
        self.assertIn('opts.wireUp(', open_fn)
        # 제어 배선(`/contents` 를 타는 쪽)보다 **먼저** 부른다.
        self.assertLess(open_fn.index('opts.wireUp('),
                        open_fn.index('opts.attachControl('),
                        '뒤로가기가 제어 배선 뒤에 붙는다')
        # 그리고 **조회보다도 먼저** 한 번 부른다 — 목록에 이미 있는 것으로
        # 지도에서 상위를 풀 수 있으므로 왕복을 기다릴 이유가 없다.
        self.assertLess(open_fn.index('opts.wireUp('),
                        open_fn.index("fetch('/api/geo/plot/"),
                        '뒤로가기가 조회를 기다린다')

        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                    'widgets', 'AoT_map',
                                    'aot-map-widget-vector.js'))
        self.assertIn('wireUp: function', widget, '위젯이 배선을 안 빌려준다')
        self.assertIn('_plotUpHooks', widget)
        # 목록만 있을 때는 **지도에서** 상위를 푼다(도형 properties 에 type 이
        # 없으므로 어느 소스에서 찾았는지가 곧 종류다).
        self.assertIn('_upFromMap', widget)

    def test_the_schedule_reuses_the_shared_button_and_input_styles(self):
        """버튼·글상자를 새로 만들지 않는다 — 이 창에는 이미 `.aot-ov-pill` 과
        `.aot-ov-desc-input` 이 있고, 카드마다 자기 모양을 만들기 시작하면 같은
        창 안에서 버튼 높이·라운드가 갈린다."""
        html = _read(self._POPUP_JS)
        sched = html.split('function _plotScheduleHtml(', 1)[1] \
                    .split('\n  function ', 1)[0]
        for cls in ('aot-ov-pill', 'aot-ov-desc-input', 'aot-ov-desc-actions'):
            self.assertIn(cls, sched, '공용 클래스를 안 쓴다: %s' % cls)
        # 자체 여닫기 표식(`details` + 손수 만든 +/− 마커)을 되살리지 말 것.
        self.assertNotIn('aot-ov-sched-more', html)

    def test_the_program_page_no_longer_owns_auto_advance(self):
        """양쪽에 두면 "왜 넘어갔나" 의 답이 두 곳이 된다(P8)."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertNotIn('auto_advance', js)

    def test_the_migration_carries_the_value_over(self):
        """사람이 켜 둔 결정을 업그레이드가 조용히 끄면, 그 사람은 자동 승인이
        멈춘 것을 한참 뒤에야 안다."""
        path = os.path.join(_ROOT, '..', 'alembic_db', 'alembic',
                            'versions', 'p6_56_plot_stage_plan_20260824.py')
        src = _read(path)
        self.assertIn('UPDATE geo_plot SET auto_advance = 1', src)
        self.assertIn("batch.drop_column('auto_advance')", src)

    def test_the_alembic_head_constant_matches(self):
        """상수와 파일 head 가 어긋나면 업그레이드가 조용히 멈춘다."""
        import os as _os
        from aot.config import ALEMBIC_VERSION
        vers = _os.path.join(_ROOT, '..', 'alembic_db', 'alembic', 'versions')
        self.assertTrue(
            _os.path.exists(_os.path.join(vers, ALEMBIC_VERSION + '.py')),
            'ALEMBIC_VERSION 이 가리키는 파일이 없다: %s' % ALEMBIC_VERSION)


# ---------------------------------------------------------------------------
# 목록·브리프의 얇은 구획 뷰 — 응답 상한을 넘기지 않기 위한 장치
# ---------------------------------------------------------------------------

_TOOL_SERVICE = os.path.join(_ROOT, 'ai', 'services',
                             'aot_data_tool_service.py')


class TestPlotSummaryView(unittest.TestCase):
    """`_plot_summary` 는 순수 dict 변환이라 DB 를 켜지 않는다.

    왜 이 테스트가 있나. 실측(2026-08-26): get_system_brief 79,707 토큰 중
    구획 36건이 60,480(75.9%)이었고, 항목의 76%가 stage_schedule/timeline/
    stage 라는 **같은 단계 정보 세 벌**이었다. 상한(15,000)을 넘으면 캡이
    목록을 잘라 "31건 중 1건" 이 나간다 — 구획이 몇 개인지조차 답이 안 된다.
    """

    def _summarize(self, d):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._plot_summary(d)

    def _full(self):
        return {
            'unique_id': 'p-1', 'subject': '콩', 'variety': '백태',
            'kind': 'vegetation', 'zone_name': '3-2', 'zone_kind': 'zone',
            'area_m2': 1024.6, 'started_on': '2026-06-15',
            'days_since_planted': 73, 'planned': False, 'active': True,
            'expected_end_on': '2026-09-06', 'days_to_expected_end': 11,
            # 아래는 화면 배선이거나 상세의 몫이다.
            'geo_id': 'g-1', 'map_id': 'm-1', 'source_ref': 'z-1',
            'source_kind': 'copied', 'color': '#71c45a',
            'location_source': 'own', 'facility_uuid': None,
            'expected_end_source': 'program', 'auto_advance': True,
            'stage_history': [{'stage_key': 'stage_6'}],
            'stage_proposal': None,
            'stage_schedule': [{'index': i, 'editable': True,
                                'removable': False} for i in range(1, 7)],
            'timeline': {'stages': [{'key': 'stage_%d' % i}
                                    for i in range(1, 7)]},
            'program': {'name': '콩', 'version': 3, 'stage_count': 6,
                        'usable_for_control': True},
            'stage': {'name': '수확', 'index': 6, 'total': 6, 'days_left': 11,
                      'day_in_stage': 3, 'targets': [], 'resources': [],
                      'guidance': None, 'state': 'running'},
        }

    def test_the_three_copies_of_the_stage_plan_do_not_ship(self):
        out = self._summarize(self._full())
        for k in ('stage_schedule', 'timeline', 'stage_history',
                  'stage_proposal', 'auto_advance'):
            self.assertNotIn(k, out, '목록에 상세가 실린다: %s' % k)

    def test_screen_wiring_does_not_ship(self):
        """LLM 이 이것으로 답하는 질문은 없다. 행 수만큼 곱해질 뿐이다."""
        out = self._summarize(self._full())
        for k in ('geo_id', 'source_ref', 'source_kind', 'color',
                  'location_source', 'expected_end_source'):
            self.assertNotIn(k, out, '화면 배선이 AI 로 간다: %s' % k)

    def test_what_the_list_must_still_answer(self):
        """무엇이 어디에 얼마나, 언제 심어 지금 어느 단계인가 — 목록이
        스스로 답해야 하는 것들이다. 여기서 빠지면 모델이 상세를 36번 부른다."""
        out = self._summarize(self._full())
        for k in ('unique_id', 'subject', 'variety', 'zone_name', 'area_m2',
                  'started_on', 'days_since_planted', 'expected_end_on',
                  'days_to_expected_end', 'active', 'stage'):
            self.assertIn(k, out, '목록에서 답할 수 없게 된다: %s' % k)
        # 상세로 넘어가는 열쇠는 절대 빠지면 안 된다.
        self.assertEqual('p-1', out['unique_id'])

    def test_the_stage_is_thinned_but_keeps_the_program_name(self):
        out = self._summarize(self._full())
        self.assertEqual({'name', 'index', 'total', 'day_in_stage',
                          'days_left'}, set(out['stage']))
        # 프로그램은 이름만 — 버전·단계수는 프로그램을 고르는 화면의 값이다.
        self.assertEqual('콩', out['program_name'])
        self.assertNotIn('program', out)

    def test_guidance_survives_because_a_note_is_keyed_off_it(self):
        """list_plots 는 "지침이 하나라도 있는가" 로 안내문을 가른다. 요약이
        guidance 를 지우면 그 판정이 뒤집혀 안내가 거짓이 된다."""
        d = self._full()
        d['stage']['guidance'] = '꼬투리가 마르면 수확한다'
        out = self._summarize(d)
        self.assertEqual('꼬투리가 마르면 수확한다', out['stage']['guidance'])

    def test_the_facility_split_reads_the_row_not_the_summary(self):
        """시설/노지 분류는 `facility_uuid`·`source_kind` 로 하는데 **둘 다
        요약에 실리지 않는다.** dict 를 보고 판정하면 시설 구획이 통째로 노지로
        넘어가고, 아무 오류 없이 온실 작물이 노지 작물로 보고된다."""
        src = _read(_TOOL_SERVICE)
        body = src.split('def get_crop_status(', 1)[1].split('\n    @staticmethod', 1)[0]
        split = body.split('def _in_facility(', 1)[1].split('\n\n', 1)[0]
        self.assertIn('row.facility_uuid', split)
        self.assertIn('row.source_kind', split)
        self.assertNotIn("d.get('facility_uuid')", split)

    def test_the_list_paths_summarize_and_the_detail_path_does_not(self):
        """get_plot 까지 요약으로 접으면 단계 일정·치수를 볼 자리가 사라진다 —
        목록이 얇아도 되는 이유가 상세가 남아 있다는 것이기 때문이다."""
        src = _read(_TOOL_SERVICE)
        for fn in ('get_crop_status', 'list_plots', 'get_plot_history'):
            body = src.split('def %s(' % fn, 1)[1] \
                      .split('\n    @staticmethod', 1)[0]
            self.assertIn('summary=True', body, '%s 가 상세를 싣는다' % fn)
        detail = src.split('def get_plot(', 1)[1] \
                    .split('\n    @staticmethod', 1)[0]
        self.assertNotIn('summary=True', detail)
