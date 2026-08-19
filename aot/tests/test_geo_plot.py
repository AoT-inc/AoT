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
        self.assertIn('elapsed_days(row', body)

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

    def test_up_target_is_the_zone_from_the_response(self):
        """구역 uuid 는 저장된 값이 아니라 기하에서 파생된다 —
        응답에서만 알 수 있으므로 하드코딩하거나 추측하지 않는다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map',
                                 'aot-map-widget-vector.js'))
        body = src.split('function _attachPlotControl', 1)[1].split(
            '\n        // ── ', 1)[0]
        self.assertIn("kind: 'zone'", body)
        self.assertIn('zone_uuid', body)


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

    def test_stage_targets_come_from_the_server(self):
        """항목 어휘·단위를 화면이 다시 조립하지 않는다.

        조립하면 항목을 늘릴 때 한쪽만 늘어난다. 그리고 **곡선이 걸린 항목은
        숫자를 내지 않는다** — 단계 값을 대신 보이면 실제로 쓰이지 않는 숫자를
        목표라고 말하는 것이 된다.
        """
        from aot.aot_flask.geo.plot_context import _stage_targets
        from aot.aot_flask.geo.program_io import _TARGET_FIELDS, _TARGET_UNITS

        # 어휘와 단위는 한 벌이어야 한다.
        self.assertEqual(set(_TARGET_FIELDS), set(_TARGET_UNITS))

        stage = {'key': 'seedling', 'targets': {'temp_day': 24.0, 'rh': 70.0}}
        out = _stage_targets(stage, None)
        by_key = {t['key']: t for t in out}
        self.assertEqual(by_key['temp_day']['value'], 24.0)
        self.assertEqual(by_key['temp_day']['unit'], '\u00b0C')
        self.assertEqual(by_key['temp_day']['source'], 'stage')
        self.assertNotIn('co2', by_key)          # 미지정 항목은 내지 않는다

    def test_a_curve_never_shows_the_stage_number(self):
        """곡선이 이기는 항목에 단계 값을 보이면 화면이 거짓말을 한다."""
        from aot.aot_flask.geo.plot_context import _stage_targets

        class _Prog(object):
            targets_methods = {'temp_day': 'method-uuid'}

        stage = {'key': 'seedling', 'targets': {'temp_day': 24.0, 'rh': 70.0}}
        out = _stage_targets(stage, _Prog())
        by_key = {t['key']: t for t in out}
        self.assertEqual(by_key['temp_day']['source'], 'method')
        self.assertIsNone(by_key['temp_day']['value'])
        self.assertEqual(by_key['rh']['value'], 70.0)   # 곡선 없는 항목은 그대로

    def test_targets_say_they_do_not_drive_control(self):
        """숫자만 보이면 사람이 '이대로 돌고 있다' 로 읽는다 — 아직 아니다."""
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        self.assertIn('Control is not changed automatically', popup)

    def test_every_plot_form_can_pick_a_kind(self):
        """구획을 만드는 세 화면이 **모두** 종류를 고를 수 있어야 한다.

        한 화면만 빠지면 그 화면으로 만든 구획은 영영 식생이다 — `kind` 는
        나중에 고칠 수 있지만, 고칠 수 있다는 것을 아무도 모른다. 서버가 받는
        축이 화면에 없는 반쪽 상태가 정확히 이 작업이 없애려던 것이다.
        """
        design = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                    'design', 'aot-geo-plot.js'))
        popup = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                   'widgets', 'AoT_map', 'aot-map-popup.js'))
        facility = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                      'facility', 'plot-ui.js'))
        self.assertIn('data-veg-field="kind"', design)
        self.assertIn("_kindSelect('data-nf=\"kind\"'", popup)   # 생성 폼
        self.assertIn("_kindSelect('data-pf=\"kind\"'", popup)   # 편집 폼
        self.assertIn('data-f="kind"', facility)
        for src in (design, popup, facility):
            for k in ('vegetation', 'livestock', 'facility', 'other'):
                self.assertIn("'" + k + "'", src)

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
        # 종류 변경을 실제로 듣는가
        self.assertIn('_wireKindChange', design)
        self.assertIn('refreshProgramChoices', plotjs)
        self.assertIn("getAttribute('data-f') !== 'kind'", facility)

    def test_block_title_does_not_repeat_its_first_label(self):
        """'심겨 있는 것 / 심은 것' 처럼 제목과 첫 행이 같은 말이면 안 된다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js',
                                 'widgets', 'AoT_map', 'aot-map-popup.js'))
        body = src.split('function _plotOverviewHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("_t('This plot')", body)
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
    def _facility(self, bay_count=1, name='온실1', fittings=None):
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
                          fittings=fittings or [])
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

    # ── 단동은 bay_1 자동 ───────────────────────────────────────────────
    def test_single_bay_facility_fills_bay_1(self):
        fac = self._facility(bay_count=1)
        row, err = self._save(facility_uuid=fac.unique_id)
        self.assertIsNone(err)
        self.assertEqual(row['bay_id'], 'bay_1')

    def test_single_bay_facility_corrects_a_wrong_bay_id(self):
        """단동에 'bay_7' 이 와도 서버가 정정한다 — 클라이언트 말을 믿지 않는다."""
        fac = self._facility(bay_count=1)
        row, err = self._save(facility_uuid=fac.unique_id, bay_id='bay_7')
        self.assertIsNone(err)
        self.assertEqual(row['bay_id'], 'bay_1')

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
        self.assertIn("data-nf=\"bay_id\"", body)

        widget = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                    'AoT_map', 'aot-map-widget-vector.js'))
        self.assertIn('_wireFacilityPlotAdd', widget)
        self.assertIn("'/api/geo/plot'", widget)
        # 권한 축은 시설 [현황]과 같아야 한다(둘 다 edit_settings) — 버튼이
        # 보이는데 저장이 403 이면 그게 더 나쁘다.
        self.assertIn('st.repEditByFac && st.repEditByFac[facilityUuid]', widget)

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
        self.assertIn('var ovSame =', widget)
        self.assertIn('if (!ovSame)', widget)
        self.assertIn("cur.outerHTML === node.outerHTML", widget)
        self.assertIn("existing.outerHTML === block.outerHTML", widget)
        self.assertIn("slot.outerHTML === node.outerHTML", widget)

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
        self.assertIn("data-veg-field=\"program_uuid\"", src)
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

    이 레이어가 막으려는 것은 "작물 지식이 네 곳에 흩어져 서로 모르는" 상태다
    (STAGE_DURATION_MAP=AI 전용 · setpoint 캐시=AI 전용 · FunctionCropPreset=제어
    전용 · Method=사람이 수작업). 여기서 고정하는 계약 중 **깨져도 조용한 것**:

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

    def test_dead_function_reference_is_shown_not_dropped(self):
        """조용히 빼면 그 단계에서 자원이 통째로 사라진 것을 아무도 모른다."""
        from aot.aot_flask.geo.plot_context import stage_resources

        out = stage_resources({'functions': [{'id': 'ghost',
                                              'role': 'irrigation'}]})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]['missing'])
        self.assertIsNone(out[0]['active'])

    def test_resource_roles_start_narrow(self):
        """어휘는 한 번 퍼지면 되돌리기 어렵다 — `other` 로 담고 나중에 이름을
        준다(`GeoProgram.kind` 와 같은 태도)."""
        from aot.aot_flask.geo.program_io import _RESOURCE_ROLES
        self.assertEqual(_RESOURCE_ROLES,
                         ('irrigation', 'fertigation', 'other'))

    def test_auto_advance_is_off_by_default(self):
        """켜져 있는 것이 기본이면 사람이 아무 결정도 하지 않았는데 단계가 스스로
        넘어간다 — 업그레이드로 그렇게 되면 특히 나쁘다."""
        prog = self._program()
        self.assertFalse(bool(getattr(prog, 'auto_advance', False)))

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
        self.assertIsNone(plot_io.auto_advance_stage(uid))

        prog.auto_advance = True
        db.session.commit()
        out = plot_io.auto_advance_stage(uid)
        self.assertIsNotNone(out)
        # 같은 읽기가 두 번 들어와도 두 줄이 되지 않는다(동시 읽기 방어).
        self.assertIsNone(plot_io.auto_advance_stage(uid))

        row = GeoPlot.query.filter_by(unique_id=uid).first()
        hist = [h for h in plot_context.stage_history(row) if not h['undone']]
        self.assertEqual(len(hist), 2)
        # 자동으로 남은 줄인지 구분된다 — `decided_by` 가 비었다는 것만으로는
        # "로그인 정보가 없는 사람" 과 구분되지 않는다.
        self.assertTrue(hist[-1]['auto'])

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
        from aot.aot_flask.geo import program_io
        out, err = program_io.create_program({
            'name': '목표4', 'subject': 'tomato',
            'stages': [{'key': 'a', 'name': 'a', 'days': 10,
                        'targets': {'rh': 250}}]})
        self.assertIsNone(out)
        self.assertIn('rh', err or '')

    def test_ui_target_keys_match_the_server(self):
        """화면이 자기 이름을 쓰면 저장은 되는데 읽는 쪽이 못 알아본다."""
        import re
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        block = js.split('var _TARGETS = [', 1)[1].split('];', 1)[0]
        ui_keys = set(re.findall(r"\['(\w+)'", block))
        from aot.aot_flask.geo.program_io import _TARGET_FIELDS
        self.assertEqual(ui_keys, set(_TARGET_FIELDS))

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

    def test_subject_is_picked_from_a_list(self):
        """자유 텍스트로 두면 대상을 바꿀 때마다 철자를 맞춰 적어야 하고,
        한 글자만 달라도 같은 대상으로 묶이지 않는다."""
        js = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                'program-settings.js'))
        self.assertIn('function _subjectRow(', js)
        self.assertIn('__custom__', js)
        # 직접 입력을 비운 채 고르면 **아무것도 보내지 않는다**(기존 값 보존).
        self.assertIn("delete out.subject;", js)

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
        채워진 값을 "조사된 추천값" 으로 읽는다. 단계별 목표는 실제 조사로 채운다.
        """
        import importlib
        mod = importlib.import_module('aot.scripts.seed_programs')
        items = mod.catalog()
        self.assertTrue(items)
        for t in items:
            for st in t['stages']:
                self.assertNotIn('targets', st, '%s 단계에 목표가 채워져 있다' % t['key'])
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

