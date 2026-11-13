# -*- coding: utf-8 -*-
"""웹 응답 시간 — 워커마다 최근 1분의 p50·p95 를 남기고, 다른 프로세스가 모아 읽는다.

자원 압박 판정(`resource_pressure`)의 웹 쪽 입력이다. 측정(26-11-08, 일반 PC 서버
P2 동시 10→20명)에서 CPU 는 11.7→21.6% 로 여유였는데 p95 는 34→260ms 로 7배가 됐다.
작은 서버에서 먼저 오는 것은 CPU 사용률이 아니라 **대기**이고, 그것이 보이는 곳이
응답 시간이다.

구조:
  - 웹 워커: 요청 시작에 `begin()`, 끝에 `end(token)` — 프로세스 안 자료구조만 만진다.
    **진행 중인 요청도 표본이다**(지금까지 걸린 시간으로). 끝난 요청만 세면 스레드가
    전부 막힌 가장 나쁜 순간에 신호가 사라진다.
  - 워커마다 배경 스레드가 `FLUSH_S` 마다 최근 `WINDOW_S` 요약을
    `<호스트>-<pid>.json` 으로 원자적으로 쓴다(요청이 끊겨도 진행 중인 요청을 알린다).
    표본이 없으면 쓰지 않는다 — 파일이 낡으면 읽는 쪽이 "한산함(신호 없음)" 으로 본다.
  - 읽는 쪽(데몬의 입력 드라이버 등): `aggregate()` 가 신선한 파일을 모은다.
    워커 p95 는 합칠 수 없으므로, 표본이 `MIN_WORKER_SAMPLES` 이상인 워커 중 가장 나쁜 것.

한계: gunicorn 이 요청을 스레드에 배정하기 **전**의 대기(accept 대기열)는 앱이 볼 수 없어
여기 들어가지 않는다. 그 몫은 CPU PSI 가 본다.

저장 위치는 웹과 데몬이 함께 보는 DATABASE_PATH 아래 휘발성 폴더다(`web_presence` 와
같은 이유 — 도커에서 웹과 데몬은 다른 컨테이너지만 이 볼륨은 같다). 날아가도 된다.
기록 실패는 요청을 절대 막지 않는다.
"""
import itertools
import json
import logging
import os
import re
import socket
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

#: 요약 창(초) — 최근 이만큼의 요청으로 p50·p95 를 낸다.
WINDOW_S = 60.0
#: 파일로 내보내는 간격(초).
FLUSH_S = 5.0
#: 이보다 오래된 워커 파일은 죽은 워커나 한산한 워커로 보고 무시한다(초).
STALE_S = 30.0
#: 이보다 오래된 파일(남은 .tmp 포함)은 읽는 쪽이 지운다(초).
PURGE_S = 600.0
#: 한 워커의 표본이 이보다 적으면 그 워커의 p95 를 믿지 않는다 — 한두 건의 느린
#: 요청(보고서·백업)이 판정을 흔들지 않게. 파이 스레드 수(6)보다 작게 두어, 스레드가
#: 전부 막힌 경우(진행 중 6건)는 잡는다.
MIN_WORKER_SAMPLES = 5
#: 한 워커가 들고 있는 최대 표본 수(메모리 상한).
MAX_SAMPLES = 5000

_DIR_ENV = 'AOT_WEB_LATENCY_DIR'

_lock = threading.Lock()
_samples = deque(maxlen=MAX_SAMPLES)   # (끝난 monotonic_t, ms)
_inflight = {}                          # token -> 시작 monotonic_t
_tokens = itertools.count(1)
_flusher = {'pid': None}


def latency_dir():
    """워커 요약 파일 폴더. 시험은 환경변수로 바꾼다."""
    override = os.environ.get(_DIR_ENV)
    if override:
        return override
    from aot.config import DATABASE_PATH
    return os.path.join(DATABASE_PATH, 'runtime', 'web_latency')


def _percentile(sorted_values, q):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def summarize(values):
    """응답 시간(ms) 목록 → {'n', 'p50', 'p95'}."""
    ordered = sorted(values)
    return {'n': len(ordered),
            'p50': _percentile(ordered, 0.50),
            'p95': _percentile(ordered, 0.95)}


# ── 워커 쪽 ───────────────────────────────────────────────────────────

def begin(now=None):
    """요청 시작. 토큰을 돌려준다(실패하면 None). 예외를 내지 않는다."""
    try:
        _ensure_flusher()
        t = time.monotonic() if now is None else now
        with _lock:
            token = next(_tokens)
            _inflight[token] = t
        return token
    except Exception:
        return None


def end(token, now=None, keep=True):
    """요청 끝. `begin()` 이 준 토큰으로 소요 시간을 쌓는다. 예외를 내지 않는다.

    keep=False 면 진행 중 목록에서만 빼고 표본으로 남기지 않는다 — 시작 때는 몰랐지만
    응답이 페이지(HTML)였던 요청.
    """
    if token is None:
        return
    try:
        t = time.monotonic() if now is None else now
        with _lock:
            start = _inflight.pop(token, None)
        if start is not None and keep:
            record((t - start) * 1000.0, now=t)
    except Exception:
        pass


#: 원래 느려서 "대기" 신호가 아닌 경로 — 로그인(비밀번호 해시)·로그아웃.
_EXCLUDED_PREFIXES = ('/static/', '/login', '/logout')


def is_excluded(path, headers):
    """이 요청을 응답 시간 표본에서 뺄까.

    빼는 것: 정적 파일, 로그인·로그아웃, 페이지(문서) 요청. 페이지는 브라우저가
    `Sec-Fetch-Dest: document` 를 보내고, 그 머리가 없는 클라이언트도 `Accept` 첫
    항목이 text/html 이다. 폴링(XHR·fetch)은 둘 다 아니다. 여기서 못 거른 페이지는
    끝에서 `is_page_response` 로 버린다(`end(keep=False)`).
    """
    path = path or ''
    if path.startswith(_EXCLUDED_PREFIXES):
        return True
    # 스크립트 요청(XHR·fetch)은 HTML 조각을 받더라도(`dataType:'html'` 폴링) 페이지가 아니다
    if is_fetch(headers):
        return False
    try:
        if (headers.get('Sec-Fetch-Dest') or '').lower() == 'document':
            return True
        accept = (headers.get('Accept') or '').lower()
        return accept.split(',')[0].strip().startswith('text/html')
    except Exception:
        return False


#: 이보다 큰 HTML 응답은 페이지로 본다(바이트). 렌더된 화면은 수십 KB 이고,
#: 문자열을 그대로 돌려주는 폴링(`/daemonactive` 의 'alive' 등)은 Flask 기본값 때문에
#: text/html 로 나가지만 몇 바이트다.
PAGE_MIN_BYTES = 2048


def is_fetch(headers):
    """브라우저가 스크립트로 보낸 요청(XHR·fetch)인가 — 그렇다면 페이지가 아니다."""
    try:
        return (headers.get('X-Requested-With') == 'XMLHttpRequest'
                or (headers.get('Sec-Fetch-Dest') or '').lower() == 'empty')
    except Exception:
        return False


def is_page_response(was_fetch, mimetype, content_length):
    """시작 때 못 거른 페이지인가(머리를 안 보내는 클라이언트). 스크립트 요청은 아니다.

    길이를 모르는 응답(스트리밍)은 페이지로 보지 않는다 — 앱의 페이지는 스트리밍하지
    않고, 길이를 모르는 쪽은 영상 스트림(`/video_feed`) 같은 것이라 시작이 곧 끝이다.
    """
    if was_fetch or mimetype != 'text/html':
        return False
    return (content_length or 0) > PAGE_MIN_BYTES


def record(ms, now=None):
    """끝난 요청 하나의 소요 시간을 쌓는다."""
    t = time.monotonic() if now is None else now
    with _lock:
        _samples.append((t, float(ms)))


def snapshot(now=None):
    """이 워커의 최근 창 요약 — 끝난 요청 + 진행 중인 요청(지금까지의 시간)."""
    t = time.monotonic() if now is None else now
    with _lock:
        cutoff = t - WINDOW_S
        while _samples and _samples[0][0] < cutoff:
            _samples.popleft()
        values = [v for _, v in _samples]
        running = [(t - s) * 1000.0 for s in _inflight.values()]
    out = summarize(values + running)
    out['inflight'] = len(running)
    out['oldest_inflight_ms'] = max(running) if running else None
    return out


def flush(now=None):
    """요약을 파일로 쓴다. 표본이 없으면 쓰지 않는다. 쓴 경로 또는 None."""
    summary = snapshot(now)
    if not summary['n']:
        return None
    folder = latency_dir()
    os.makedirs(folder, exist_ok=True)
    payload = dict(summary, t=time.time(), pid=os.getpid())
    # 도커에서는 컨테이너마다 PID 가 1부터 다시 시작해, 같은 볼륨을 보는 두 컨테이너
    # (웹·MCP)의 워커가 같은 번호를 가질 수 있다 — 호스트 이름(컨테이너 ID)을 붙인다.
    host = re.sub(r'[^A-Za-z0-9_.-]', '_', socket.gethostname() or 'host')
    path = os.path.join(folder, '%s-%d.json' % (host, os.getpid()))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return path


def _flush_loop():
    while True:
        time.sleep(FLUSH_S)
        try:
            flush()
        except Exception:
            logger.debug('web_latency flush failed', exc_info=True)


def _ensure_flusher():
    """이 프로세스에 배경 기록 스레드를 하나 둔다. gunicorn 은 마스터에서 fork 하므로
    PID 가 바뀌었으면(워커) 새로 띄운다 — 스레드는 fork 를 건너오지 않는다."""
    pid = os.getpid()
    if _flusher['pid'] == pid:
        return
    with _lock:
        if _flusher['pid'] == pid:
            return
        _flusher['pid'] = pid
    threading.Thread(target=_flush_loop, name='aot-web-latency', daemon=True).start()


# ── 읽는 쪽 ───────────────────────────────────────────────────────────

def aggregate(now=None):
    """신선한 워커 요약을 모은다.

    Returns:
        {'workers', 'n', 'p95_ms', 'p50_ms', 'inflight', 'oldest_inflight_ms'} —
        믿을 만한 워커가 없으면 p95/p50 은 None. 폴더가 없으면(웹이 아직 요청을
        안 받음) None.
    """
    folder = latency_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    wall = time.time() if now is None else now
    rows = []
    for name in names:
        path = os.path.join(folder, name)
        if not name.endswith('.json'):
            # 비정상 종료로 남은 .tmp — 오래됐으면 치운다
            try:
                if wall - os.path.getmtime(path) > PURGE_S:
                    os.remove(path)
            except OSError:
                pass
            continue
        try:
            with open(path, encoding='utf-8') as f:
                row = json.load(f)
            age = wall - float(row.get('t') or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if age > PURGE_S:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        if age <= STALE_S:
            rows.append(row)

    def num(row, key):
        try:
            return float(row.get(key))
        except (TypeError, ValueError):
            return None

    trusted = [r for r in rows
               if (num(r, 'n') or 0) >= MIN_WORKER_SAMPLES and num(r, 'p95') is not None]
    oldest = [num(r, 'oldest_inflight_ms') for r in rows]
    oldest = [v for v in oldest if v is not None]
    return {
        'workers': len(rows),
        'n': int(sum(num(r, 'n') or 0 for r in rows)),
        'p95_ms': max(num(r, 'p95') for r in trusted) if trusted else None,
        'p50_ms': max(num(r, 'p50') for r in trusted) if trusted else None,
        'inflight': int(sum(num(r, 'inflight') or 0 for r in rows)),
        'oldest_inflight_ms': max(oldest) if oldest else None,
    }


def _reset_for_tests():
    with _lock:
        _samples.clear()
        _inflight.clear()
