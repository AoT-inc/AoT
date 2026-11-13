# coding=utf-8
"""E2E 용 합성 DEM 타일 서버 — 인터넷 없이 `gis_dem_custom` 입력이 읽을 고도 타일을 돌려준다.

물 회로 '지형 바꾸기'는 **서버가** 후보 DEM 의 타일을 받아 계산한다(브라우저가 아니다). 그래서 시험 안에서
Playwright 로 가로챌 수 없고, 앱 컨테이너가 닿는 곳에 진짜 HTTP 서버가 있어야 한다. 앱을 재시작해도 살아 있게
컴포즈의 별도 서비스(`dem-tiles`)로 띄운다 — `python -m aot.tests.e2e.dem_server`.

경로: ``/<프로필>/{z}/{x}/{y}.png`` (terrarium 인코딩, 256 px). 고도는 시드 배치의 원점 O 에서 잰
로컬 미터 (동 X, 북 Z) 의 일차식이다:  ``고도 = BASE_M + 동쪽 경사 * X + 북쪽 경사 * Z``.
일차식은 쌍선형 보간에서도 그대로라서 시험이 기대 경사 길이를 계산으로 낼 수 있다.
"""
import io
import math
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get('AOT_E2E_DEM_PORT', '8099'))
TILE = 256

#: 시드 배치의 원점 (경도, 위도). 시드(`seed.py`)와 여정 시험이 같은 값을 쓴다.
ORIGIN = (127.0011, 37.0011)
M_PER_DEG_LAT = 111320.0
BASE_M = 120.0

#: 프로필 → (동쪽 경사, 북쪽 경사) — 미터당 미터.
PROFILES = {
    'gentle': (0.02, 0.03),
    'steep': (0.10, 0.16),
}

_cache = {}


def elevation(profile, lng, lat):
    """프로필의 고도[m] — 시험이 기대값을 낼 때도 같은 식을 쓴다."""
    sx, sz = PROFILES[profile]
    x = (lng - ORIGIN[0]) * M_PER_DEG_LAT * math.cos(math.radians(ORIGIN[1]))
    z = (lat - ORIGIN[1]) * M_PER_DEG_LAT
    return BASE_M + sx * x + sz * z


def render_tile(profile, z, x, y):
    """terrarium PNG 바이트. 고도 = R*256 + G + B/256 - 32768."""
    import numpy as np
    from PIL import Image

    n = 2 ** z
    px = (np.arange(TILE) + 0.5) / TILE
    lng = (x + px) / n * 360.0 - 180.0
    merc = math.pi * (1 - 2 * (y + px) / n)
    lat = np.degrees(np.arctan(np.sinh(merc)))
    lngs, lats = np.meshgrid(lng, lat)          # 행 = 위도(북→남), 열 = 경도
    sx, sz = PROFILES[profile]
    gx = (lngs - ORIGIN[0]) * M_PER_DEG_LAT * math.cos(math.radians(ORIGIN[1]))
    gz = (lats - ORIGIN[1]) * M_PER_DEG_LAT
    v = np.clip(BASE_M + sx * gx + sz * gz + 32768.0, 0, 65535.99)
    r = np.floor(v / 256.0)
    g = np.floor(v - r * 256.0)
    b = np.floor((v - np.floor(v)) * 256.0)
    rgb = np.stack([r, g, b], axis=-1).astype('uint8')
    buf = io.BytesIO()
    Image.fromarray(rgb, 'RGB').save(buf, 'PNG')
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802
        parts = self.path.split('?')[0].strip('/').split('/')
        try:
            profile, z, x, y = parts[0], int(parts[1]), int(parts[2]), int(parts[3].split('.')[0])
            if profile not in PROFILES or not (0 <= z <= 22) or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
                raise ValueError
        except (ValueError, IndexError):
            if self.path.rstrip('/') in ('', '/health'):
                return self._send(200, b'ok', 'text/plain')
            return self._send(404, b'', 'text/plain')
        key = (profile, z, x, y)
        if key not in _cache:
            _cache[key] = render_tile(*key)
        self._send(200, _cache[key], 'image/png')

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):                       # 요청마다 로그를 남기지 않는다
        pass


def main():
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print('E2E DEM tiles on :%d' % PORT, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
