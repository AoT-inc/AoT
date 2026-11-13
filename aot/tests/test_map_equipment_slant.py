# coding=utf-8
"""MCP 설비 응답의 경사 길이(T5) — 있을 때만 붙고, 기존 키·값은 그대로다."""
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape
from aot.tools.aot_data_tool_service import AoTDataToolService as S

SITE = [[127.0, 36.0], [127.0, 36.01], [127.01, 36.01], [127.01, 36.0], [127.0, 36.0]]


def _pipe(pid, sub, x0, dy=0.0005, **extra):
    props = {'sub_type': sub, 'parent_node_id': 'site-1'}
    if pid:
        props['node_id'] = pid
    props.update(extra)
    return {'type': 'Feature',
            'geometry': {'type': 'LineString',
                         'coordinates': [[127.001 + x0, 36.001], [127.001 + x0, 36.001 + dy]]},
            'properties': props}


def _lengths(state, pipes, version='v1'):
    return {'state': state, 'version': version, 'pipes': pipes, 'totals': {}}


class SlantTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='m1', name='지도', category='design').save()
        GeoShape(unique_id='s1', geo_id='m1', type='site', feature={
            'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [SITE]},
            'properties': {'name': '대지', 'node_id': 'site-1'}}).save()
        GeoShape(unique_id='eq', geo_id='m1', type='equipment_collection', feature={
            'type': 'FeatureCollection', 'features': [
                _pipe('P-main', 'pipe_main', 0.0),
                _pipe('P-b1', 'pipe_branch', 0.0002),
                _pipe('P-b2', 'pipe_branch', 0.0004),
                _pipe(None, 'pipe_branch', 0.0006),
                _pipe('P-gone', 'pipe_branch', 0.0008)]}).save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _patch(self, ret):
        return mock.patch('aot.utils.water_terrain.pipe_lengths_for', return_value=ret)

    def _summary(self):
        return S.get_map_equipment_tool(area_name='대지')

    def _detail(self):
        return S.get_map_equipment_detail_tool(area_name='대지')

    def test_no_dem_is_byte_identical(self):
        with self._patch(_lengths('none', {})):
            a, d = self._summary(), self._detail()
        with self._patch(None):
            a2, d2 = self._summary(), self._detail()
        self.assertEqual(a, a2)
        self.assertEqual(d, d2)
        self.assertNotIn('terrain', a)
        self.assertNotIn('terrain', d)
        row = a['irrigation'][0]
        self.assertEqual(row['length_basis'], 'horizontal')
        self.assertFalse([k for k in row if '3d' in k])
        self.assertFalse([k for k in d['pipes'] if 'length_3d_m' in k])

    def test_warming_only_state(self):
        with self._patch(_lengths('warming', {})):
            a, d = self._summary(), self._detail()
        self.assertEqual(a['terrain'], {'state': 'warming'})
        self.assertEqual(d['terrain'], {'state': 'warming'})
        self.assertNotIn('main_pipe_length_3d_m', a['irrigation'][0])
        self.assertEqual(d['length_basis'], 'horizontal')

    def test_ready_sums_and_unknowns(self):
        pipes = {'P-main': {'horizontal_m': 55.6, 'slant_m': 60.0},
                 'P-b1': {'horizontal_m': 55.6, 'slant_m': 20.0},
                 'P-b2': {'horizontal_m': 55.6, 'slant_m': None}}
        with self._patch(_lengths('ready', pipes)):
            a, d = self._summary(), self._detail()
        self.assertEqual(a['terrain'], {'state': 'ready', 'version': 'v1'})
        row = a['irrigation'][0]
        self.assertEqual(row['main_pipe_length_3d_m'], 60.0)
        self.assertEqual(row['branch_pipe_length_3d_m'], 20.0)
        self.assertEqual(row['pipes_without_3d'], 1)
        self.assertEqual(a['irrigation_total']['branch_pipe_length_3d_m'], 20.0)
        by = {p['name']: p for p in d['pipes']}
        three = [p.get('length_3d_m') for p in d['pipes']]
        # 대응되는 것은 P-main(60.0), P-b1(20.0)뿐 — slant None·id 없음·표에 없는 id 는 키가 없다
        self.assertEqual(three, [60.0, 20.0, None, None, None])
        self.assertEqual(len(by), 2)  # 가지관 이름이 같아 사전은 접힌다(길이 키 검사는 위 목록)
        for p in d['pipes']:
            self.assertEqual(p['length_m'] > 0, True)

    def test_totals_agree_with_pipe_lengths_for(self):
        pipes = {'P-main': {'horizontal_m': 55.6, 'slant_m': 60.0},
                 'P-b1': {'horizontal_m': 55.6, 'slant_m': 20.0},
                 'P-b2': {'horizontal_m': 55.6, 'slant_m': None}}
        tot = {'slant_m': 60.0 + 20.0 + 55.6, 'unknown_pipes': 1}
        with self._patch(_lengths('ready', pipes)):
            row = self._summary()['irrigation'][0]
        known = row['main_pipe_length_3d_m'] + row['branch_pipe_length_3d_m']
        self.assertAlmostEqual(known + 55.6 * row['pipes_without_3d'], tot['slant_m'], places=1)
        self.assertEqual(row['pipes_without_3d'], tot['unknown_pipes'])

    def test_duplicate_ids_do_not_match(self):
        GeoShape(unique_id='eq2', geo_id='m1', type='equipment', feature=
                 _pipe('P-main', 'pipe_branch', 0.001)).save()
        pipes = {'P-main': {'horizontal_m': 55.6, 'slant_m': 60.0}}
        with self._patch(_lengths('ready', pipes)):
            row = self._summary()['irrigation'][0]
        self.assertNotIn('main_pipe_length_3d_m', row)


if __name__ == '__main__':
    unittest.main()
