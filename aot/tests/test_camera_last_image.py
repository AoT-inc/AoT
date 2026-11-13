# coding=utf-8
"""`/camera/last_image/<id>` 가 폴링에 맞게 응답하는지 고정한다.

대시보드 카메라 위젯은 이 주소를 몇 초마다 다시 부른다.
- 앱 기본값(SEND_FILE_MAX_AGE_DEFAULT = 1년, public)이면 브라우저가 서버에 묻지 않아
  위젯이 `?t=` 로 캐시를 깨야 했고, 같은 사진을 매번 통째로 받았다.
  → 응답은 `no-cache`·`private` + ETag, 같은 사진이면 304.
- 폴링마다 폴더 전체를 훑고 정렬했다(사진이 쌓일수록 SD 카드 I/O 가 선형 증가).
  → 폴더 mtime 이 그대로면 직전 결과를 쓴다.
"""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from aot.aot_flask import routes_camera


def _write(path, data, mtime):
    with open(path, 'wb') as f:
        f.write(data)
    os.utime(path, (mtime, mtime))


class LastImageTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        routes_camera._LATEST_STILL_CACHE.clear()
        self.app = Flask(__name__)
        # 운영 앱과 같은 기본값 — 이 값이 그대로 실리면 안 된다.
        self.app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000
        camera = SimpleNamespace(path_still=self.dir)
        query = SimpleNamespace(filter_by=lambda **kw: SimpleNamespace(first=lambda: camera))
        self._p = patch.object(routes_camera, 'Camera', SimpleNamespace(query=query))
        self._p.start()
        self.view = routes_camera.camera_last_image.__wrapped__   # login_required 를 건너뜀

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def _get(self, headers=None):
        with self.app.test_request_context('/camera/last_image/cam', headers=headers or {}):
            rv = self.view('cam')
            if isinstance(rv, tuple):
                return rv[0], rv[1]
            return rv, rv.status_code

    def test_returns_newest_with_revalidate_headers(self):
        now = time.time()
        _write(os.path.join(self.dir, 'a.jpg'), b'old', now - 100)
        _write(os.path.join(self.dir, 'b.jpg'), b'new', now - 10)
        rv, status = self._get()
        self.assertEqual(status, 200)
        rv.direct_passthrough = False
        self.assertEqual(rv.get_data(), b'new')
        cc = rv.cache_control
        self.assertTrue(cc.no_cache)
        self.assertTrue(cc.private)
        self.assertFalse(cc.public)
        self.assertEqual(cc.max_age, 0)
        self.assertTrue(rv.headers.get('ETag'))
        rv.close()

    def test_same_photo_is_304(self):
        _write(os.path.join(self.dir, 'a.jpg'), b'img', time.time() - 5)
        first, _ = self._get()
        etag = first.headers['ETag']
        first.close()
        second, status = self._get({'If-None-Match': etag})
        self.assertEqual(status, 304)
        second.close()

    def test_new_photo_changes_answer(self):
        now = time.time()
        _write(os.path.join(self.dir, 'a.jpg'), b'one', now - 50)
        first, _ = self._get()
        etag = first.headers['ETag']
        first.close()
        # 새 파일이 생기면 폴더 mtime 이 바뀐다 — 캐시가 낡은 답을 주면 안 된다.
        _write(os.path.join(self.dir, 'b.jpg'), b'two', now)
        os.utime(self.dir, (now + 1, now + 1))
        second, status = self._get({'If-None-Match': etag})
        self.assertEqual(status, 200)
        second.direct_passthrough = False
        self.assertEqual(second.get_data(), b'two')
        second.close()

    def test_unchanged_folder_is_not_rescanned(self):
        _write(os.path.join(self.dir, 'a.jpg'), b'img', time.time() - 5)
        self._get()[0].close()
        with patch.object(routes_camera.os, 'scandir',
                          side_effect=AssertionError('폴더를 다시 훑었다')):
            rv, status = self._get()
            self.assertEqual(status, 200)
            rv.close()

    def test_png_is_served_as_png(self):
        _write(os.path.join(self.dir, 'a.png'), b'png', time.time())
        rv, _ = self._get()
        self.assertEqual(rv.mimetype, 'image/png')
        rv.close()

    def test_empty_folder_is_404(self):
        _write(os.path.join(self.dir, 'note.txt'), b'x', time.time())
        _, status = self._get()
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
