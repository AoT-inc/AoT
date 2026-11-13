# coding=utf-8
"""서버 DEM 표본기 — 합성 PNG 타일과 가짜 fetch 로만 시험한다(네트워크 없음)."""
import io
import logging
import math
import os
import re
import tempfile
import unittest

import numpy as np
from PIL import Image

from aot.utils import dem_sampler as ds

T = 256
ZOOM = 3
URL = 'https://dem.example.com/t/{z}/{x}/{y}.png'


def world_z(gx, gy):
    """세계 픽셀 좌표의 선형 고도 — 쌍선형 보간이 정확히 이 값을 되돌려야 한다."""
    return 100.0 + 0.5 * gx + 0.25 * gy


def encode_terrarium(z):
    v = np.asarray(z, dtype=np.float64) + 32768.0
    r = np.floor(v / 256.0)
    g = np.floor(v) % 256
    b = np.floor((v - np.floor(v)) * 256.0)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def encode_mapbox(z):
    v = np.rint((np.asarray(z, dtype=np.float64) + 10000.0) * 10.0).astype(np.int64)
    return np.stack([v // 65536, (v // 256) % 256, v % 256], axis=-1).astype(np.uint8)


def png(rgb):
    buf = io.BytesIO()
    Image.fromarray(rgb, 'RGB').save(buf, 'PNG')
    return buf.getvalue()


def linear_tile(x, y, encoding='terrarium', size=T):
    gy, gx = np.mgrid[0:size, 0:size]
    z = world_z(x * size + gx, y * size + gy)
    return png(encode_terrarium(z) if encoding == 'terrarium' else encode_mapbox(z))


class FakeNet:
    def __init__(self, missing=(), encoding='terrarium'):
        self.calls = []
        self.missing = set(missing)
        self.encoding = encoding

    def __call__(self, url):
        self.calls.append(url)
        z, x, y = map(int, re.search(r'/t/(\d+)/(\d+)/(\d+)\.png', url).groups())
        if (z, x, y) in self.missing:
            return 404, None
        return 200, linear_tile(x, y, self.encoding)


def lnglat_of_px(gx, gy):
    n = T * 2 ** ZOOM
    lng = gx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / n))))
    return lng, lat


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def sampler(self, net=None, url=URL, encoding='terrarium', **kw):
        self.net = net or FakeNet(encoding=encoding)
        return ds.Sampler(url, encoding, T, ZOOM, cache_root=self.tmp.name,
                          fetch_func=self.net, **kw)


class TestDecode(unittest.TestCase):
    def test_terrarium(self):
        rgb = np.array([[[128, 0, 0], [129, 10, 128]]], dtype=np.uint8)
        z = ds.decode_rgb(rgb, 'terrarium')
        self.assertAlmostEqual(float(z[0, 0]), 0.0)
        self.assertAlmostEqual(float(z[0, 1]), 256 + 10 + 0.5, places=3)

    def test_mapbox(self):
        # (0,0,0) → -10000, (1,134,160) → -10000 + 100000*0.1 = 0 → 100000 = 1*65536+134*256+160
        rgb = np.array([[[0, 0, 0], [1, 134, 160]]], dtype=np.uint8)
        z = ds.decode_rgb(rgb, 'mapbox')
        self.assertAlmostEqual(float(z[0, 0]), -10000.0, places=3)
        self.assertAlmostEqual(float(z[0, 1]), 0.0, places=3)


class TestSampling(Base):
    def test_bilinear_exact_on_linear_field_terrarium(self):
        s = self.sampler()
        gx, gy = 1000.3, 700.8
        z = s.elevation(*lnglat_of_px(gx, gy))
        self.assertAlmostEqual(z, world_z(gx - 0.5, gy - 0.5), delta=0.05)

    def test_mapbox_decode_path(self):
        s = self.sampler(encoding='mapbox')
        gx, gy = 500.0, 600.0     # 정수 격자 중심 근처 → 0.1 m 양자화 안에서 일치
        z = s.elevation(*lnglat_of_px(gx + 0.5, gy + 0.5))
        self.assertAlmostEqual(z, world_z(gx, gy), delta=0.2)

    def test_crossing_tile_boundary_uses_neighbour_tile(self):
        s = self.sampler()
        gx = 2 * T            # 타일 x=1 과 2 의 경계
        prof = s.profile([lnglat_of_px(gx - 20, 900), lnglat_of_px(gx + 20, 900)], 2.0)
        zs = [z for _d, z in prof]
        self.assertTrue(all(z is not None for z in zs))
        self.assertTrue(all(b >= a - 1e-3 for a, b in zip(zs, zs[1:])))   # 선형이라 단조
        tiles = {tuple(map(int, re.findall(r'\d+', u.split('/t/')[1]))) for u in self.net.calls}
        self.assertTrue({(ZOOM, 1, 3), (ZOOM, 2, 3)} <= tiles)

    def test_404_gives_none_not_zero(self):
        s = self.sampler(FakeNet(missing={(ZOOM, 3, 2)}))
        self.assertIsNone(s.elevation(*lnglat_of_px(3 * T + 100, 2 * T + 100)))

    def test_out_of_range_is_none(self):
        s = self.sampler()
        self.assertIsNone(s.elevation(10.0, 89.9))

    def test_cache_hit_makes_no_network_call(self):
        s = self.sampler()
        p = lnglat_of_px(1000.3, 700.8)
        a = s.elevation(*p)
        n = len(self.net.calls)
        self.assertGreater(n, 0)
        self.assertEqual(s.elevation(*p), a)
        self.assertEqual(len(self.net.calls), n)
        # 새 인스턴스(메모리 비움)도 디스크에서 읽는다
        s2 = ds.Sampler(URL, 'terrarium', T, ZOOM, cache_root=self.tmp.name,
                        fetch_func=self.net)
        self.assertEqual(s2.elevation(*p), a)
        self.assertEqual(len(self.net.calls), n)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, s.version, str(ZOOM))))

    def test_failed_tile_is_negative_cached(self):
        s = self.sampler(FakeNet(missing={(ZOOM, 3, 2)}))
        p = lnglat_of_px(3 * T + 100, 2 * T + 100)
        s.elevation(*p)
        n = len(self.net.calls)
        s.elevation(*p)
        self.assertEqual(len(self.net.calls), n)

    def test_fetch_false_uses_cache_only(self):
        s = self.sampler()
        p = lnglat_of_px(1000.3, 700.8)
        self.assertIsNone(s.elevation(*p, fetch=False))
        self.assertEqual(self.net.calls, [])
        s.elevation(*p)
        self.assertIsNotNone(s.elevation(*p, fetch=False))

    def test_tilejson_url_is_resolved(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url.endswith('tiles.json?key=SECRETKEY123'):
                return 200, b'{"tiles": ["https://t.example.com/t/{z}/{x}/{y}.png?key=SECRETKEY123"]}'
            return 200, linear_tile(*list(map(int, re.search(r'/t/(\d+)/(\d+)/(\d+)', url).groups()))[1:])
        s = ds.Sampler('https://api.example.com/tiles.json?key=SECRETKEY123', 'terrarium', T, ZOOM,
                       secrets=['SECRETKEY123'], cache_root=self.tmp.name, fetch_func=fetch)
        self.assertIsNotNone(s.elevation(*lnglat_of_px(1000.3, 700.8)))


class TestVersionAndSecrets(Base):
    def test_version_ignores_key_but_not_url_or_params(self):
        k1 = ds.make_version('https://a.com/{z}/{x}/{y}.png?key=AAAAAAAA', 'terrarium', 256, 12)
        k2 = ds.make_version('https://a.com/{z}/{x}/{y}.png?key=BBBBBBBB', 'terrarium', 256, 12)
        self.assertEqual(k1, k2)
        self.assertEqual(ds.make_version('https://a.com/{z}/{x}/{y}.png?x=1&token=Q', 'mapbox', 256, 12),
                         ds.make_version('https://a.com/{z}/{x}/{y}.png?x=1&token=R', 'mapbox', 256, 12))
        self.assertNotEqual(k1, ds.make_version('https://b.com/{z}/{x}/{y}.png?key=AAAAAAAA', 'terrarium', 256, 12))
        self.assertNotEqual(k1, ds.make_version('https://a.com/{z}/{x}/{y}.png?key=AAAAAAAA', 'mapbox', 256, 12))
        self.assertNotEqual(k1, ds.make_version('https://a.com/{z}/{x}/{y}.png?key=AAAAAAAA', 'terrarium', 512, 12))
        self.assertNotEqual(k1, ds.make_version('https://a.com/{z}/{x}/{y}.png?key=AAAAAAAA', 'terrarium', 256, 13))

    def test_version_ignores_bare_secret_in_path(self):
        a = ds.make_version('https://a.com/SECRET99/{z}/{x}/{y}.png', 'terrarium', 256, 12, ['SECRET99'])
        b = ds.make_version('https://a.com/OTHER777/{z}/{x}/{y}.png', 'terrarium', 256, 12, ['OTHER777'])
        self.assertEqual(a, b)

    def test_key_never_in_logs_version_or_exceptions(self):
        def boom(url):
            return 0, 'ConnectionError'
        s = ds.Sampler('https://a.com/{z}/{x}/{y}.png?key=TOPSECRET1', 'terrarium', T, ZOOM,
                       secrets=['TOPSECRET1'], cache_root=self.tmp.name, fetch_func=boom)
        with self.assertLogs(ds.logger, level=logging.DEBUG) as cm:
            self.assertIsNone(s.elevation(*lnglat_of_px(100, 100)))
        self.assertNotIn('TOPSECRET1', '\n'.join(cm.output))
        self.assertNotIn('TOPSECRET1', s.version)
        self.assertNotIn('TOPSECRET1', repr(s))
        for d, _dirs, files in os.walk(self.tmp.name):
            self.assertNotIn('TOPSECRET1', d)

    def test_default_fetch_swallows_url_bearing_exception(self):
        import requests
        orig = requests.get

        def bad(url, timeout=None):
            raise requests.ConnectionError('failed for ' + url)
        requests.get = bad
        try:
            status, msg = ds.default_fetch('https://a.com/x?key=TOPSECRET1')
        finally:
            requests.get = orig
        self.assertEqual(status, 0)
        self.assertNotIn('TOPSECRET1', msg)

    def test_factory_from_layer_and_none(self):
        self.assertIsNone(ds.sampler_from_layer(None))
        self.assertIsNone(ds.sampler_from_layer({'url': ''}))
        layer = {'url': 'https://a.com/{z}/{x}/{y}.png?key=ABCD1234', 'api_key': 'ABCD1234',
                 'terrain': {'encoding': 'mapbox', 'tileSize': 512, 'maxzoom': 14}}
        s = ds.sampler_from_layer(layer)
        self.assertEqual((s.encoding, s.tile_size, s.max_zoom), ('mapbox', 512, 14))
        self.assertIs(ds.sampler_from_layer(layer), s)


class TestStepAndProfile(Base):
    def test_step_rule(self):
        self.assertEqual(ds.suggest_step_m(30.0), 5.0)
        self.assertEqual(ds.suggest_step_m(7.0), 3.5)
        self.assertEqual(ds.suggest_step_m(1.0), 2.0)

    def test_cell_m(self):
        s = ds.Sampler(URL, 'terrarium', 256, 15, cache_root=self.tmp.name, fetch_func=FakeNet())
        self.assertAlmostEqual(s.cell_m(0.0), 4.777, places=2)
        self.assertLess(s.cell_m(60.0), s.cell_m(0.0))

    def test_profile_cap_200_and_endpoints(self):
        s = self.sampler()
        a, b = lnglat_of_px(1000, 700), lnglat_of_px(1300, 700)
        total = ds._haversine_m(a, b)
        prof = s.profile([a, b], 0.01)
        self.assertEqual(len(prof), ds.MAX_POINTS)
        self.assertEqual(prof[0][0], 0.0)
        self.assertAlmostEqual(prof[-1][0], total, places=3)

    def test_profile_uses_requested_step(self):
        s = self.sampler()
        a, b = lnglat_of_px(1000, 700), lnglat_of_px(1010, 700)
        total = ds._haversine_m(a, b)
        prof = s.profile([a, b], total / 4)
        self.assertEqual(len(prof), 5)

    def test_profile_none_where_uncovered(self):
        s = self.sampler(FakeNet(missing={(ZOOM, 3, 2)}))
        prof = s.profile([lnglat_of_px(3 * T - 5, 2 * T + 100), lnglat_of_px(3 * T + 60, 2 * T + 100)], 5.0)
        self.assertIsNone(prof[-1][1])
        self.assertIsNotNone(prof[0][1])

    def test_disk_prune_removes_oldest(self):
        for i, age in enumerate((300, 200, 100)):
            p = os.path.join(self.tmp.name, 'v', str(i) + '.png')
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as fh:
                fh.write(b'x' * 1000)
            os.utime(p, (1_000_000 - age, 1_000_000 - age))
        ds.prune_cache(self.tmp.name, 2000)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'v', '0.png')))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, 'v', '2.png')))


if __name__ == '__main__':
    unittest.main()
