# coding=utf-8
"""set_pipe_diameters — 대지·구역 이름 하나에 주배관·지관 관경(mm)을 일괄 입력.

임시 sqlite 만 쓴다(라이브 DB 불가). 고정하는 계약
  1. 영역 판정은 설비 상세 읽기와 같은 헬퍼(_area_owner_test) — 소유 링크, 링크 없으면 다각형 포함.
  2. 주배관(pipe_main/main)과 지관(pipe_branch/branch)을 구분하고 점적(is_drip) 줄은 건드리지 않고 센다.
  3. 기본은 빈 배관만 채운다. only_empty=false 일 때만 덮어쓰고 그 개수를 알린다.
  4. 값은 웹 parseDiameter 와 같은 규칙(1 이상의 유한한 수), 둘 다 비면 오류.
  5. 지도 편집 권한(edit_settings), 승인 되읽기에 건수가 실린다.
  6. 저장 뒤 물 회로 수준(level)을 되읽는다.
"""
import unittest

from aot.aot_flask.extensions import db
from aot.databases.models import GeoShape
from aot.tests.test_place_membership import _Base


def _line(x0, y0, x1, y1, sub, name, **props):
    p = {'sub_type': sub, 'name': name}
    p.update(props)
    return {'type': 'Feature', 'properties': p,
            'geometry': {'type': 'LineString', 'coordinates': [[x0, y0], [x1, y1]]}}


def _features(rows):
    row = GeoShape.query.filter_by(geo_id='m1', type='equipment_collection').first()
    return {f['properties']['name']: f['properties'] for f in row.feature['features']}


class _PipeBase(_Base):

    def setUp(self):
        super().setUp()
        from aot.tools.aot_data_tool_service import AoTDataToolService
        self.S = AoTDataToolService
        feats = [
            # 구역 3-1(ZONE_A: 10..40) 소유 링크
            _line(12, 12, 20, 12, 'pipe_main', 'M-link', parent_node_id='n-a'),
            _line(12, 14, 20, 14, 'pipe_branch', 'B-link', parent_node_id='n-a'),
            # 링크 없음 → 다각형 포함(구역 A 안)
            _line(25, 25, 35, 25, 'main', 'M-poly'),
            _line(25, 27, 35, 27, 'branch', 'B-poly', diameter_mm=32),
            # 점적 줄은 제외
            _line(26, 30, 34, 30, 'pipe_branch', 'D-drip', is_drip=True),
            # 다른 곳 소유
            _line(62, 12, 70, 12, 'pipe_main', 'M-other', parent_node_id='n-b'),
            # 구역 B 안, 링크 없음
            _line(65, 20, 75, 20, 'pipe_main', 'M-b-poly'),
        ]
        GeoShape(unique_id='eq1', geo_id='m1', type='equipment_collection',
                 feature={'type': 'FeatureCollection', 'features': feats}).save()
        row = GeoShape.query.filter_by(unique_id='zone-a').first()
        row.feature = dict(row.feature, properties=dict(row.feature['properties'], node_id='n-a'))
        db.session.commit()
        zb = GeoShape.query.filter_by(unique_id='zone-b').first()
        zb.feature = dict(zb.feature, properties=dict(zb.feature['properties'], node_id='n-b'))
        db.session.commit()

    def _set(self, **kw):
        return self.S.set_pipe_diameters(**kw)


class TestScope(_PipeBase):

    def test_main_and_branch_are_distinguished_and_drip_skipped(self):
        out = self._set(area_name='3-1', main_mm=63, branch_mm=25)
        self.assertEqual('success', out['status'], out)
        p = _features(None)
        self.assertEqual(63, p['M-link']['diameter_mm'])
        self.assertEqual(63, p['M-poly']['diameter_mm'])
        self.assertEqual(25, p['B-link']['diameter_mm'])
        self.assertNotIn('diameter_mm', p['D-drip'])
        self.assertEqual(1, out['drip_excluded'])
        self.assertEqual((2, 1), (out['main'], out['branch']))      # B-poly 는 이미 32 → 유지

    def test_other_area_is_untouched(self):
        self._set(area_name='3-1', main_mm=63)
        p = _features(None)
        self.assertNotIn('diameter_mm', p['M-other'])
        self.assertNotIn('diameter_mm', p['M-b-poly'])

    def test_parent_site_includes_descendant_zone_pipes(self):
        out = self._set(area_name='3포장', main_mm=50)
        p = _features(None)
        for n in ('M-link', 'M-poly', 'M-other', 'M-b-poly'):
            self.assertEqual(50, p[n]['diameter_mm'], n)
        self.assertEqual(4, out['main'])

    def test_unknown_area_is_an_error(self):
        out = self._set(area_name='없는곳', main_mm=63)
        self.assertEqual('error', out['status'])

    def test_main_only_leaves_branch_alone(self):
        self._set(area_name='3-1', main_mm=63)
        self.assertNotIn('diameter_mm', _features(None)['B-link'])


class TestOverwrite(_PipeBase):

    def test_only_empty_is_default_and_keeps_filled(self):
        out = self._set(area_name='3-1', branch_mm=20)
        self.assertEqual(32, _features(None)['B-poly']['diameter_mm'])
        self.assertEqual(1, out['kept_filled'])
        self.assertEqual(0, out['overwritten'])

    def test_explicit_false_overwrites_and_counts(self):
        out = self._set(area_name='3-1', branch_mm=20, only_empty=False)
        self.assertEqual(20, _features(None)['B-poly']['diameter_mm'])
        self.assertEqual(1, out['overwritten'])

    def test_string_false_is_false(self):
        self._set(area_name='3-1', branch_mm=20, only_empty='false')
        self.assertEqual(20, _features(None)['B-poly']['diameter_mm'])


class TestValidation(_PipeBase):

    def test_bad_values_are_rejected_without_writing(self):
        for bad in (0, 0.5, -3, 'abc', float('nan'), True):
            out = self._set(area_name='3-1', main_mm=bad)
            self.assertEqual('error', out['status'], bad)
        self.assertNotIn('diameter_mm', _features(None)['M-link'])

    def test_needs_at_least_one_value(self):
        self.assertEqual('error', self._set(area_name='3-1')['status'])
        self.assertEqual('error', self._set(area_name='3-1', main_mm='')['status'])

    def test_numeric_string_and_decimal(self):
        self._set(area_name='3-1', main_mm='63.5')
        self.assertEqual(63.5, _features(None)['M-link']['diameter_mm'])


class TestApprovalAndPermission(_PipeBase):

    def test_registered_as_map_edit_write(self):
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_registry as R
        self.assertIn('set_pipe_diameters', R.write_tools())
        self.assertIn('set_pipe_diameters', R._SPACE_NON_PLOT_WRITES)
        self.assertEqual('edit_settings', gate.required_write_permission('set_pipe_diameters'))

    def test_read_back_names_area_counts_overwrites_and_drip(self):
        from aot.tools import mcp_safety_gate as gate
        text = gate.read_back_text('set_pipe_diameters',
                                   {'area_name': '3-1', 'main_mm': 63, 'branch_mm': 20,
                                    'only_empty': False})
        self.assertIn('3-1', text)
        self.assertIn('main 2 pipes', text)
        self.assertIn('branch 2 pipes', text)
        self.assertIn('overwrites 1', text)
        self.assertIn('skips 1 drip', text)
        # 읽기 전용: 되읽기가 값을 쓰지 않는다
        self.assertNotIn('diameter_mm', _features(None)['M-link'])

    def test_domain_operation_exists(self):
        from aot.tools.domain.registry_data import OPS
        self.assertTrue(any(o.op == 'pipe_diameters_set' and o.tool == 'configure' for o in OPS))


class TestWaterReadback(_PipeBase):

    def test_response_carries_level_when_the_area_has_nozzles(self):
        from unittest import mock
        fake = {'circuits': [{'level': 'L1-partial', 'network': 0, 'summary': {}, 'assumptions': [],
                              'excluded_ratio': 0.2, 'missing': [], 'coverage': {'ratio': 0.8}}]}
        with mock.patch('aot.utils.water_net_link.pressure_for_area', return_value=fake), \
                mock.patch('aot.utils.water_net_link.pressure_brief',
                           return_value={'level': 'L1-partial', 'diameter_ratio': 0.8,
                                         'bound': 'flow-upper'}):
            out = self._set(area_name='3-1', main_mm=63)
        self.assertEqual([{'level': 'L1-partial', 'diameter_ratio': 0.8}], out['water'])


if __name__ == '__main__':
    unittest.main()
