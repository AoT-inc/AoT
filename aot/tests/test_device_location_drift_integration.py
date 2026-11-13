# coding=utf-8
"""검사기 ↔ 앱 정본 연결 고정 + check_geo_integrity 합류 경로."""
import unittest
from collections import defaultdict
from unittest import mock

from aot.scripts import check_device_location_drift as drift


class KindTablesMatchCanonical(unittest.TestCase):
    def test_same_kinds_and_tables(self):
        from aot.space.device_binding import device_kind_models
        canon = tuple((k, m.__tablename__) for k, m in device_kind_models())
        self.assertEqual(drift.DEVICE_TABLES, canon)


class IntegrityJoin(unittest.TestCase):
    def test_failure_is_recorded_not_raised(self):
        from aot.scripts import check_geo_integrity as cgi
        findings = defaultdict(list)
        with mock.patch.object(drift, 'analyze', side_effect=RuntimeError('boom')), \
                mock.patch.object(drift, 'open_ro', return_value=mock.Mock()), \
                mock.patch('aot.aot_flask.extensions.db') as db:
            db.engine.url.database = '/x.db'
            db.engine.url.get_backend_name.return_value = 'sqlite'
            cgi._check_device_location_drift(findings)
        self.assertEqual(findings['device-location-drift'][0]['criterion'], 'check_failed')

    def test_info_item_does_not_block_unless_strict(self):
        from aot.scripts import check_geo_integrity as cgi
        f = {'device-location-drift': [{'criterion': 'x', 'count': 1}]}
        self.assertEqual(cgi._blocking(f), 0)
        self.assertEqual(cgi._blocking(f, strict_location=True), 1)
        self.assertEqual(cgi._blocking({'duplicate': [1]}), 1)
        self.assertEqual(cgi.report(f, 5, quiet=True), 0)
        self.assertEqual(cgi.report(f, 5, quiet=True, strict_location=True), 1)


if __name__ == '__main__':
    unittest.main()
