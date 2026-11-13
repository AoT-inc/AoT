# coding=utf-8
"""장치 위치 드리프트 검사기(check_device_location_drift) 판정 고정.

임시 sqlite 파일만 만들어 읽기 전용으로 검사한다 — 앱 DB 를 건드리지 않는다.
6경우: 컬럼만 · 마커만 · 둘 일치 · 둘 불일치 · explicit tz 자리 없음 · 레거시 컬럼만.
"""
import json
import os
import sqlite3
import tempfile
import unittest

from aot.scripts import check_device_location_drift as drift

DEFAULT = (10.0, 20.0)      # 테스트 전용 기본 좌표(실제 설치 값과 무관)
MAP = 'map-1'


def _point(lat, lng):
    return json.dumps({'type': 'Feature', 'properties': {},
                       'geometry': {'type': 'Point', 'coordinates': [lng, lat]}})


class DriftCheckerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        con = sqlite3.connect(self.path)
        con.executescript('''
            CREATE TABLE geo_map (unique_id TEXT);
            CREATE TABLE geo_setting (default_lat REAL, default_lng REAL);
            CREATE TABLE geo_shape (unique_id TEXT, type TEXT, device_id TEXT,
                                    channel_id TEXT, feature TEXT);
            CREATE TABLE geo_facility (unique_id TEXT, shape_uuid TEXT);
            CREATE TABLE geo_binding (id INTEGER PRIMARY KEY, spatial_kind TEXT,
                spatial_id TEXT, role TEXT, device_id TEXT, channel_id TEXT,
                valid_from TEXT, valid_to TEXT);
        ''')
        for _kind, table in drift.DEVICE_TABLES:
            con.execute('CREATE TABLE "%s" (unique_id TEXT, name TEXT, latitude '
                        'REAL, longitude REAL, tz_source TEXT, map_config_id '
                        'TEXT)' % table)
        con.execute('INSERT INTO geo_map VALUES (?)', (MAP,))
        con.execute('INSERT INTO geo_setting VALUES (?, ?)', DEFAULT)
        con.commit()
        self.con = con

    def tearDown(self):
        self.con.close()
        os.unlink(self.path)

    def _input(self, uid, lat=None, lng=None, tz=None, cfg=None):
        self.con.execute('INSERT INTO input VALUES (?,?,?,?,?,?)',
                         (uid, 'n-' + uid, lat, lng, tz, cfg))

    def _marker(self, shape, dev, lat, lng, bind=True):
        self.con.execute('INSERT INTO geo_shape VALUES (?,?,?,?,?)',
                         (shape, 'aot_device', dev, '0', _point(lat, lng)))
        if bind:
            self.con.execute('INSERT INTO geo_binding (spatial_kind, spatial_id,'
                             " role, device_id, channel_id, valid_from) VALUES "
                             "('shape',?, 'marker', ?, '0', '2026-01-01')", (shape, dev))

    def _area(self, shape, dev, lat, lng):
        self.con.execute('INSERT INTO geo_shape VALUES (?,?,?,?,?)',
                         (shape, 'zone', None, '0', _point(lat, lng)))
        self.con.execute('INSERT INTO geo_binding (spatial_kind, spatial_id,'
                         " role, device_id, channel_id, valid_from) VALUES "
                         "('shape',?, 'area', ?, '0', '2026-01-01')", (shape, dev))

    def _run(self, **kw):
        self.con.commit()
        ro = drift.open_ro(self.path)
        try:
            return drift.analyze(ro, **kw)
        finally:
            ro.close()

    def test_column_only(self):
        self._input('a', 37.0, 127.0)
        r = self._run()
        t = r['summary']['total']
        self.assertEqual((t['col'], t.get('marker', 0), t.get('binding', 0)),
                         (1, 0, 0))
        self.assertTrue(r['l4_ok'])

    def test_marker_only(self):
        self._input('a')
        self._marker('s1', 'a', 37.0, 127.0)
        r = self._run()
        t = r['summary']['total']
        self.assertEqual((t.get('col', 0), t['marker'], t['binding']), (0, 1, 1))
        self.assertTrue(r['l4_ok'])

    def test_column_matches_marker(self):
        self._input('a', 37.0, 127.0)
        self._marker('s1', 'a', 37.0, 127.0)
        r = self._run()
        self.assertEqual(r['criteria'], dict.fromkeys(drift.CRITERIA, 0))
        self.assertEqual(r['report_only']['col_vs_marker_far'], 0)

    def test_column_differs_from_marker(self):
        self._input('a', 37.0, 127.0)
        self._marker('s1', 'a', 37.01, 127.0)        # 약 1.1 km
        r = self._run()
        self.assertEqual(r['criteria']['far_from_place'], 1)
        self.assertFalse(r['l4_ok'])
        self.assertGreater(r['rows'][0]['col_vs_place_m'], 1000)
        self.assertEqual(r['rows'][0]['place_rank'], 'marker')

    def test_explicit_tz_without_place(self):
        self._input('a', 37.0, 127.0, tz='explicit')
        self._input('b', 37.0, 127.0, tz='inherited')
        r = self._run()
        self.assertEqual(r['criteria']['explicit_tz_no_place'], 1)
        self.assertEqual(r['summary']['tz_source'], {'explicit': 1, 'inherited': 1})
        self.assertFalse(r['l4_ok'])

    def test_legacy_column_only_marker(self):
        self._input('a', 37.0, 127.0)
        self._marker('s1', 'a', 37.0, 127.0, bind=False)
        r = self._run()
        self.assertEqual(r['criteria']['legacy_only_markers'], 1)
        self.assertFalse(r['l4_ok'])

    def test_default_coords_and_dangling_map_config(self):
        self._input('a', DEFAULT[0], DEFAULT[1], cfg='ghost')
        self._input('b', 1.0, 1.0, cfg=MAP)
        r = self._run()
        self.assertEqual(r['report_only']['default_coords_rows'], 1)
        self.assertEqual(r['criteria']['dangling_map_config'], 1)
        self.assertEqual(r['summary']['total']['map_config'], 2)
        # --default-coords 인자가 GeoSetting 보다 우선
        r2 = self._run(default_coords=(1.0, 1.0))
        self.assertEqual(r2['report_only']['default_coords_rows'], 1)

    def test_map_config_column_absent_reports_zero(self):
        # 컬럼이 드롭된 DB — 검사는 죽지 않고 0 + 'absent' 로 보고한다.
        for _kind, table in drift.DEVICE_TABLES:
            self.con.execute('ALTER TABLE "%s" DROP COLUMN map_config_id' % table)
        self.con.execute('INSERT INTO input (unique_id, name, latitude, longitude,'
                         " tz_source) VALUES ('a','n-a',1.0,1.0,NULL)")
        self.con.commit()
        r = self._run()
        self.assertEqual(r['map_config_column'], 'absent')
        self.assertEqual(r['criteria']['dangling_map_config'], 0)
        self.assertIn('(column absent)', drift.render(r))

    def test_ended_binding_marker_is_not_legacy(self):
        self._input('a', 37.0, 127.0)
        self._marker('s1', 'a', 37.0, 127.0, bind=False)
        self.con.execute('INSERT INTO geo_binding (spatial_kind, spatial_id, role,'
                         " device_id, channel_id, valid_from, valid_to) VALUES "
                         "('shape','s1','marker','a','0','2026-01-01','2026-02-01')")
        r = self._run()
        self.assertEqual(r['criteria']['legacy_only_markers'], 0)

    def test_marker_bound_only_elsewhere_is_reported_not_counted(self):
        self._input('a', 37.0, 127.0)
        self._marker('s1', 'a', 37.0, 127.0, bind=False)
        self._area('z1', 'a', 37.0, 127.0)
        r = self._run()
        self.assertEqual(r['criteria']['legacy_only_markers'], 0)
        self.assertEqual(r['report_only']['markers_bound_elsewhere'], 1)

    def test_area_rank_far_is_reference_only(self):
        self._input('a', 37.0, 127.0)
        self._area('z1', 'a', 37.01, 127.0)          # 약 1.1 km, 구역 rank
        r = self._run()
        self.assertEqual(r['criteria']['far_from_place'], 0)
        self.assertEqual(r['report_only']['far_ref_nonmarker'], 1)
        self.assertTrue(r['l4_ok'])

    def test_channel_suffix_device_id(self):
        self._input('a', 37.0, 127.0)
        self._marker('s1', 'a::2', 37.0, 127.0, bind=False)
        r = self._run()
        self.assertEqual(r['criteria']['legacy_only_markers'], 1)
        self.assertEqual(r['legacy_only_markers'][0]['device_id'], 'a')

    def test_latest_binding_wins_within_rank(self):
        self._input('a', 37.0, 127.0)
        for sid, vf, lat in (('s1', '2026-01-01', 37.5), ('s2', '2026-03-01', 37.0)):
            self.con.execute('INSERT INTO geo_shape VALUES (?,?,?,?,?)',
                             (sid, 'aot_device', None, '0', _point(lat, 127.0)))
            self.con.execute('INSERT INTO geo_binding (spatial_kind, spatial_id,'
                             " role, device_id, channel_id, valid_from) VALUES "
                             "('shape',?, 'marker','a','0',?)", (sid, vf))
        r = self._run()
        self.assertEqual(r['criteria']['far_from_place'], 0)

    def test_open_ro_quotes_path(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'a#b?c.db')
        sqlite3.connect(path).execute('CREATE TABLE t (x)').connection.close()
        con = drift.open_ro(path)
        self.assertEqual(con.execute('SELECT count(*) FROM t').fetchone()[0], 0)
        con.close()
        os.unlink(path)
        os.rmdir(d)

    def test_main_exit_codes_json_verbose(self):
        import contextlib
        import io
        self._input('a', 37.0, 127.0)
        self.con.commit()

        def run(*extra):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = drift.main(['--db', self.path, *extra])
            return code, buf.getvalue()
        code, out = run('--json')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)['l4_ok'])
        self._input('b', 1.0, 1.0, tz='explicit')
        self.con.commit()
        code, out = run()
        self.assertEqual(code, 1)
        self.assertNotIn('n-b', out)
        code, out = run('--verbose')
        self.assertIn('n-b', out)
        self.assertEqual(drift.main(['--db', os.path.join(tempfile.gettempdir(), 'nope-xyz.db')]), 2)

    def test_default_output_hides_identity(self):
        self._input('a', 37.0, 127.0, tz='explicit')
        res = drift._strip_ids(self._run())
        self.assertNotIn('uuid', json.dumps(res))
        self.assertNotIn('n-a', json.dumps(res))


if __name__ == '__main__':
    unittest.main()
