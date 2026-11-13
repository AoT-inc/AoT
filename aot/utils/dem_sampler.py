# coding=utf-8
"""서버 DEM 표본기 — 지도의 활성 DEM(XYZ 타일 입력)에서 (경도, 위도) → 고도[m].

화면(MapLibre)이 지형을 그리는 것과 별개로, 2D 지도에서도 3D 결과(경사 길이 등)가
나오도록 서버가 타일을 직접 읽는다. 쓰는 곳은 물 회로의 표고·경사 길이(T2).

    from aot.utils import dem_sampler
    s = dem_sampler.get_sampler()            # 활성 DEM. 없으면 None
    s.elevation(lng, lat)                    # float | None
    s.profile([(lng, lat), ...], step_m)     # [(누적거리 m, 고도 m | None)]
    s.version, s.cell_m(lat)

규칙
- 못 읽으면 **None** 이다. 0 으로 채우지 않는다(타일 404·범위 밖·받기 실패·없는 이웃 타일).
- 판 식별자 `version` = hash(키를 뺀 URL 템플릿, encoding, tile_size, max_zoom). 키가
  바뀌어도 같고, URL·인코딩이 바뀌면 달라진다. 키는 로그·예외·version 어디에도 없다.
- 받기는 전역 동시 4개 · 요청당 10초 · 호출당 예산(`fetch_budget_s`) 이 있고, 실패는
  잠깐 부정 캐시한다. `fetch=False` 는 캐시(메모리·디스크)에 있는 것만 쓴다.
- 디스크 캐시: `<AOT_LOCAL_DIR>/dem_cache/<version>/<z>/<x>/<y>.png`, 상한 512 MB.
"""
import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

import numpy as np

logger = logging.getLogger(__name__)

ENCODINGS = ('terrarium', 'mapbox')
STEP_MIN_M = 2.0
STEP_MAX_M = 5.0
MAX_POINTS = 200
MAX_CONCURRENT_FETCH = 4
FETCH_TIMEOUT_S = 10.0
FETCH_BUDGET_S = 30.0
NEG_TTL_NOT_FOUND_S = 600.0
NEG_TTL_ERROR_S = 60.0
CACHE_MAX_BYTES = 512 * 1024 * 1024
MEM_TILES = 32
EARTH_R = 6371008.8
_EQUATOR_M = 40075016.686
_SENSITIVE_PARAM = re.compile(r'(key|token|secret|sig|auth|password)', re.I)


def dem_cache_root():
    """디스크 타일 캐시의 뿌리. `aot_local` 볼륨(컨테이너 안 쓰기 가능)이 우선이다."""
    local = os.environ.get('AOT_LOCAL_DIR')
    if local:
        return os.path.join(local, 'dem_cache')
    from aot.config import DATABASE_PATH
    return os.path.join(DATABASE_PATH, 'dem_cache')


def suggest_step_m(cell_m):
    """표본 간격 = clamp(셀 크기 / 2, 2 m, 5 m)."""
    return max(STEP_MIN_M, min(STEP_MAX_M, float(cell_m) / 2.0))


# ---------------------------------------------------------------- 키 비노출
def strip_url_secrets(url, secrets=()):
    """URL 에서 키를 뺀 사본. 판 식별자와 로그에 쓰는 형태다.

    알려진 비밀 문자열은 `{api_key}` 로, 이름이 key/token/… 인 쿼리 값은 비운다.
    """
    text = url or ''
    for s in secrets or ():
        if isinstance(s, str) and len(s) >= 4:
            text = text.replace(s, '{api_key}')
    try:
        parts = urlsplit(text)
        if parts.query:
            q = [(k, '' if _SENSITIVE_PARAM.search(k) else v)
                 for k, v in parse_qsl(parts.query, keep_blank_values=True)]
            query = urlencode(q, safe='{}')
            text = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except ValueError:
        pass
    return text


def make_version(url_template, encoding, tile_size, max_zoom, secrets=()):
    base = '|'.join([strip_url_secrets(url_template, secrets), str(encoding),
                     str(int(tile_size)), str(int(max_zoom))])
    return hashlib.sha256(base.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------- 복호
def decode_rgb(rgb, encoding):
    """(h, w, 3) uint8 → float32 고도[m]."""
    a = rgb.astype(np.float64)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if encoding == 'mapbox':
        z = -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1
    else:
        z = r * 256.0 + g + b / 256.0 - 32768.0
    return z.astype(np.float32)


def _decode_png(data, encoding, tile_size):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert('RGB')
        if im.size != (tile_size, tile_size):
            return None
        return decode_rgb(np.asarray(im), encoding)


# ---------------------------------------------------------------- 받기
_FETCH_SEM = threading.BoundedSemaphore(MAX_CONCURRENT_FETCH)


def default_fetch(url):
    """(status, bytes|None). 예외는 상태 0 으로 접는다(메시지에 URL·키가 실리므로)."""
    import requests
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT_S)
        return resp.status_code, (resp.content if resp.status_code == 200 else None)
    except Exception as exc:  # noqa: BLE001 — URL 이 든 메시지를 올리지 않는다
        return 0, type(exc).__name__


# ---------------------------------------------------------------- 디스크 캐시
_prune_lock = threading.Lock()
_written_since_prune = [0]


def prune_cache(root, max_bytes=CACHE_MAX_BYTES):
    """상한을 넘으면 오래된(mtime) 것부터 지운다. 지운 바이트 수를 돌려준다."""
    files, total = [], 0
    for d, _dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
    removed = 0
    if total <= max_bytes:
        return 0
    files.sort()
    for _m, size, p in files:
        if total <= max_bytes:
            break
        try:
            os.remove(p)
            total -= size
            removed += size
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- 표본기
class Sampler:
    def __init__(self, url_template, encoding='terrarium', tile_size=256, max_zoom=12,
                 secrets=(), cache_root=None, fetch_func=None,
                 cache_max_bytes=CACHE_MAX_BYTES, fetch_budget_s=FETCH_BUDGET_S):
        if encoding not in ENCODINGS:
            encoding = 'terrarium'
        self.encoding = encoding
        self.tile_size = int(tile_size or 256)
        self.max_zoom = max(0, min(int(max_zoom if max_zoom is not None else 12), 22))
        self._url = url_template or ''
        self._secrets = tuple(s for s in (secrets or ()) if isinstance(s, str) and s)
        self.version = make_version(self._url, encoding, self.tile_size, self.max_zoom, self._secrets)
        self._root = cache_root or dem_cache_root()
        self._fetch = fetch_func or default_fetch
        self._cache_max = cache_max_bytes
        self._budget = fetch_budget_s
        self._mem = OrderedDict()
        self._neg = {}
        self._lock = threading.Lock()
        self._key_locks = {}
        self._template = None        # {z}{x}{y} 가 든 실제 URL(키 포함, 메모리에만)
        self._template_failed_at = 0.0

    def __repr__(self):
        return '<Sampler %s %s z%d>' % (self.version, self.encoding, self.max_zoom)

    # -- 크기
    def cell_m(self, lat=0.0):
        return _EQUATOR_M * math.cos(math.radians(lat)) / (self.tile_size * 2 ** self.max_zoom)

    def suggest_step_m(self, lat=0.0):
        return suggest_step_m(self.cell_m(lat))

    # -- 좌표
    def _world_px(self, lng, lat):
        n = self.tile_size * (2 ** self.max_zoom)
        lat = max(-85.0511287798, min(85.0511287798, lat))
        x = (lng + 180.0) / 360.0 * n
        s = math.sin(math.radians(lat))
        y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
        return x, y

    # -- 타일
    def _tile_path(self, z, x, y):
        return os.path.join(self._root, self.version, str(z), str(x), '%d.png' % y)

    def _resolve_template(self, deadline):
        if self._template:
            return self._template
        if '{z}' in self._url and '{x}' in self._url:
            self._template = self._url
            return self._template
        # TileJSON(MapTiler 등)
        if time.time() - self._template_failed_at < NEG_TTL_ERROR_S or time.time() >= deadline:
            return None
        with _FETCH_SEM:
            status, body = self._fetch(self._url)
        try:
            tiles = json.loads(body)['tiles'][0] if status == 200 else None
        except Exception:  # noqa: BLE001
            tiles = None
        if not tiles or '{z}' not in tiles:
            self._template_failed_at = time.time()
            logger.warning('[dem] TileJSON 을 읽지 못했습니다 (판 %s, 상태 %s)', self.version, status)
            return None
        self._template = tiles
        return tiles

    def _tile(self, z, x, y, fetch, deadline):
        """tile 고도 배열 | None."""
        key = (z, x, y)
        with self._lock:
            arr = self._mem.get(key)
            if arr is not None:
                self._mem.move_to_end(key)
                return arr
            if self._neg.get(key, 0) > time.time():
                return None
            klock = self._key_locks.setdefault(key, threading.Lock())
        with klock:
            with self._lock:
                arr = self._mem.get(key)
            if arr is not None:
                return arr
            arr = self._from_disk(key)
            if arr is None and fetch:
                arr = self._download(key, deadline)
            if arr is not None:
                with self._lock:
                    self._mem[key] = arr
                    while len(self._mem) > MEM_TILES:
                        self._mem.popitem(last=False)
            return arr

    def _from_disk(self, key):
        path = self._tile_path(*key)
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError:
            return None
        try:
            os.utime(path, None)
            arr = _decode_png(data, self.encoding, self.tile_size)
        except Exception:  # noqa: BLE001
            arr = None
        if arr is None:
            try:
                os.remove(path)
            except OSError:
                pass
        return arr

    def _download(self, key, deadline):
        z, x, y = key
        if time.time() >= deadline:
            return None
        tpl = self._resolve_template(deadline)
        if not tpl:
            return None
        url = tpl.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))
        remaining = deadline - time.time()
        if not _FETCH_SEM.acquire(timeout=max(0.0, min(remaining, FETCH_TIMEOUT_S))):
            return None
        try:
            status, body = self._fetch(url)
        finally:
            _FETCH_SEM.release()
        arr = None
        if status == 200 and isinstance(body, (bytes, bytearray)):
            try:
                arr = _decode_png(bytes(body), self.encoding, self.tile_size)
            except Exception:  # noqa: BLE001
                arr = None
        if arr is None:
            ttl = NEG_TTL_NOT_FOUND_S if status in (404, 403) or status == 200 else NEG_TTL_ERROR_S
            with self._lock:
                self._neg[key] = time.time() + ttl
            logger.warning('[dem] 타일을 받지 못했습니다 (판 %s, z%d/%d/%d, 상태 %s)',
                           self.version, z, x, y, status)
            return None
        self._store_disk(key, bytes(body))
        return arr

    def _store_disk(self, key, data):
        path = self._tile_path(*key)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = '%s.%d.tmp' % (path, threading.get_ident())
            with open(tmp, 'wb') as fh:
                fh.write(data)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning('[dem] 타일 캐시를 쓰지 못했습니다: %s', type(exc).__name__)
            return
        _written_since_prune[0] += 1
        if _written_since_prune[0] >= 50 and _prune_lock.acquire(blocking=False):
            try:
                _written_since_prune[0] = 0
                prune_cache(self._root, self._cache_max)
            finally:
                _prune_lock.release()

    # -- 공개 API
    def elevation(self, lng, lat, fetch=True, _deadline=None):
        """고도[m]. 쌍선형 보간, 못 읽으면 None."""
        deadline = _deadline if _deadline is not None else time.time() + self._budget
        T = self.tile_size
        n = T * (2 ** self.max_zoom)
        px, py = self._world_px(lng, lat)
        fx, fy = px - 0.5, py - 0.5            # 픽셀 중심 기준
        x0, y0 = math.floor(fx), math.floor(fy)
        tx, ty = fx - x0, fy - y0
        vals = []
        for dy in (0, 1):
            for dx in (0, 1):
                gx, gy = x0 + dx, y0 + dy
                if gy < 0 or gy >= n:
                    return None
                gx %= n
                arr = self._tile(self.max_zoom, gx // T, gy // T, fetch, deadline)
                if arr is None:
                    return None
                vals.append(float(arr[gy % T, gx % T]))
        top = vals[0] * (1 - tx) + vals[1] * tx
        bot = vals[2] * (1 - tx) + vals[3] * tx
        return top * (1 - ty) + bot * ty

    def profile(self, points_lnglat, step_m=None, fetch=True):
        """폴리라인을 따라 표본. [(누적 수평거리 m, 고도 m | None)], 최대 200점."""
        pts = [(float(a), float(b)) for a, b in (points_lnglat or [])]
        if not pts:
            return []
        seg = [_haversine_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(seg)
        if step_m is None:
            step_m = self.suggest_step_m(pts[0][1])
        step = max(float(step_m), 1e-6)
        count = int(math.ceil(total / step)) + 1 if total > 0 else 1
        if count > MAX_POINTS:
            count = MAX_POINTS
        dists = [total * i / (count - 1) for i in range(count)] if count > 1 else [0.0]
        deadline = time.time() + self._budget
        out, si, acc = [], 0, 0.0
        for d in dists:
            while si < len(seg) - 1 and d > acc + seg[si]:
                acc += seg[si]
                si += 1
            if si >= len(seg):
                lng, lat = pts[0]
            else:
                f = 0.0 if seg[si] == 0 else min(1.0, max(0.0, (d - acc) / seg[si]))
                (a0, b0), (a1, b1) = pts[si], pts[si + 1]
                lng, lat = a0 + (a1 - a0) * f, b0 + (b1 - b0) * f
            out.append((d, self.elevation(lng, lat, fetch=fetch, _deadline=deadline)))
        return out

    def prefetch(self, points_lnglat, step_m=None):
        """경로가 지나는 타일을 미리 받아 캐시를 데운다(T3 백그라운드용). 읽은 표본 수."""
        prof = self.profile(points_lnglat, step_m, fetch=True)
        return len(prof)


def _haversine_m(a, b):
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dlat, dlng = la2 - la1, math.radians(b[0] - a[0])
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(h)))


# ---------------------------------------------------------------- 팩토리
_SAMPLERS = {}
_SAMPLERS_LOCK = threading.Lock()


def sampler_from_layer(layer, api_keys=None, **kwargs):
    """이미 해석된 DEM 레이어(`split_terrain_layer` 의 두 번째 값) → Sampler | None."""
    if not isinstance(layer, dict) or not layer.get('url'):
        return None
    terrain = layer.get('terrain') or {}
    secrets = [layer.get('api_key')] + list((api_keys or {}).values())
    secrets = [s for s in secrets if isinstance(s, str) and len(s) >= 4]
    s = Sampler(layer['url'], terrain.get('encoding', 'terrarium'),
                terrain.get('tileSize', 256), terrain.get('maxzoom', 12),
                secrets=secrets, **kwargs)
    if kwargs:
        return s
    with _SAMPLERS_LOCK:        # 같은 판은 한 객체를 공유해 메모리 캐시를 아낀다
        return _SAMPLERS.setdefault((s.version, s._url), s)


def get_sampler(map_uuid=None, layer=None, api_keys=None, **kwargs):
    """지도(또는 이미 해석된 레이어)의 Sampler. 지형이 없으면 None.

    DEM 입력은 현재 전역 하나(`get_geo_config()['terrain']`)이고 지도별로는 3D 켜짐만
    다르다. `map_uuid` 는 지도별 DEM 이 생겼을 때를 위한 자리다.
    """
    if layer is None:
        from aot.aot_flask.utils import utils_geo
        cfg = utils_geo.get_geo_config(with_secrets=True) or {}
        layer, api_keys = cfg.get('terrain'), cfg.get('keys')
    return sampler_from_layer(layer, api_keys, **kwargs)
