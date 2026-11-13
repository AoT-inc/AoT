# coding=utf-8
"""check_geo_writes 의 [L2] 규칙 — 장치 행 latitude/longitude/timezone 대입 금지."""
import ast
import importlib.util
import os
import tempfile
import unittest

_P = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'check_geo_writes.py')
_spec = importlib.util.spec_from_file_location('check_geo_writes', _P)
cgw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cgw)


class DeviceColumnRuleTest(unittest.TestCase):

    def _scan(self, code, rel='aot/aot_flask/utils/x_probe.py'):
        d = tempfile.mkdtemp()
        full = os.path.join(d, rel)
        os.makedirs(os.path.dirname(full))
        open(full, 'w').write(code)
        old = (cgw.ROOT, cgw.SCAN_ROOT)
        cgw.ROOT, cgw.SCAN_ROOT = d, os.path.join(d, 'aot')
        try:
            return cgw.scan_device_columns()
        finally:
            cgw.ROOT, cgw.SCAN_ROOT = old

    def test_positive_plain_and_tuple_and_aug(self):
        hits = self._scan("def f(dev, s):\n    dev.latitude = 1\n"
                          "    s.longitude, s.timezone = 2, 'UTC'\n")
        self.assertEqual(len(hits), 3)

    def test_negative_reads_and_self_and_other_attrs(self):
        hits = self._scan("def f(dev):\n    x = dev.latitude\n    dev.name = 'a'\n"
                          "class A:\n    def g(self):\n        self.latitude = 1\n")
        self.assertEqual(hits, [])

    def test_exempt_prefix_and_file(self):
        self.assertEqual(self._scan("d.latitude = 1\n", 'aot/aot_flask/geo/p.py'), [])
        self.assertEqual(self._scan("d.timezone = 1\n", 'aot/aot_flask/utils/utils_settings.py'), [])

    def test_repo_is_clean(self):
        self.assertEqual(cgw.scan_device_columns(), [])

    def test_transitional_list_is_exactly_two(self):
        self.assertEqual(cgw.DEVICE_COLUMN_TRANSITIONAL,
                         {'aot/utils/twin_config.py', 'aot/utils/device_tz.py'})


class DeadDeviceColumnRuleTest(unittest.TestCase):
    """[L3] 죽은 장치 컬럼 3개 — 속성(읽기·쓰기)·getattr·질의/생성자 키워드 금지."""

    def _scan(self, code, rel='aot/aot_flask/utils/x_probe.py'):
        d = tempfile.mkdtemp()
        full = os.path.join(d, rel)
        os.makedirs(os.path.dirname(full))
        open(full, 'w').write(code)
        old = (cgw.ROOT, cgw.SCAN_ROOT)
        cgw.ROOT, cgw.SCAN_ROOT = d, os.path.join(d, 'aot')
        try:
            return cgw.scan_dead_device_columns()
        finally:
            cgw.ROOT, cgw.SCAN_ROOT = old

    def test_repo_is_clean(self):
        self.assertEqual(cgw.scan_dead_device_columns(), [])

    def test_attribute_read_and_write(self):
        self.assertEqual(len(self._scan("x = dev.map_config_id\n")), 1)
        self.assertEqual(len(self._scan("dev.location_source = 'a'\n")), 1)
        self.assertEqual(len(self._scan("dev.location_updated_utc = None\n")), 1)

    def test_self_and_cls_are_caught(self):
        self.assertEqual(len(self._scan(
            "class A:\n    def f(self):\n        self.location_source = 'm'\n")), 1)

    def test_getattr(self):
        self.assertEqual(len(self._scan("v = getattr(o, 'map_config_id', None)\n")), 1)

    def test_filter_by_and_constructor_keywords(self):
        self.assertEqual(len(self._scan("q = X.query.filter_by(map_config_id='m')\n")), 1)
        self.assertEqual(len(self._scan("o = Input(location_source='manual')\n")), 1)

    def test_not_caught_dict_keys_strings_and_template_context(self):
        code = ("d = {'location_source': 'bound'}\n"
                "d['map_config_id'] = 1\n"
                "render_template('a.html', map_config_id='m')\n"
                "s = 'x.map_config_id'\n")
        self.assertEqual(self._scan(code), [])

    def test_exempt_prefixes(self):
        for rel in ('aot/databases/models/m.py', 'aot/tests/t.py'):
            self.assertEqual(self._scan("x = dev.map_config_id\n", rel), [])


if __name__ == '__main__':
    unittest.main()
