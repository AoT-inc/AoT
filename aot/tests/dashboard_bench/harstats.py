# coding=utf-8
"""요청 기록 계산과 HAR 처리 — 순수 함수만(브라우저·네트워크 없이 시험된다).

요청 기록(req) 한 건은 dict: url, method, t(탐색 시작 후 요청 시각, 초), status, enc(전송
바이트), ttfb(ms), failed. 측정 실행기가 CDP 이벤트로 채운다.
"""
import json
from urllib.parse import urlsplit

from aot.tests.dashboard_bench.stats import quantile

#: 이 안의 연속 요청은 한 묶음(같은 순간에 여러 위젯이 보낸 것)으로 본다
BURST_GAP_S = 0.5
SENSITIVE_HEADERS = {'cookie', 'set-cookie', 'authorization', 'x-csrftoken',
                     'x-csrf-token', 'proxy-authorization'}


def net_status(r):
    """요청의 **네트워크** 상태 코드. 브라우저가 캐시 재검증(304)을 받아 캐시된 본문으로 채우면
    CDP `responseReceived` 는 200 으로 합쳐 보고한다 — 실제로 오간 코드는 raw_status 에 있다."""
    return r.get('raw_status') or r.get('status')


def path_of(url):
    """쿼리를 뗀 경로 — 폴링을 URL 별로 묶는 키."""
    return urlsplit(url).path


#: 카메라 사진을 받는 요청의 경로 조각(모던 위젯 last_image, 옛 위젯 acquire_image/still)
CAMERA_PATH_MARKS = ('/camera/last_image/', '/camera_acquire_image/', '/camera/snapshot')


def camera_metrics(steady, dwell_s):
    """켜 둔 구간의 카메라 사진 요청 — 304 비율과 "새 사진 주기".

    갱신 주기(위젯이 묻는 간격)와 촬영 주기(서버가 새 사진을 내는 간격)는 다르다. 304 면 사진이
    그대로라는 뜻이라 전송이 거의 없다. 그래서 시간당 전송량은 새 사진(200) 개수 × 사진 크기로 정해진다.
    new_photo_period_s = 켜 둔 시간 / 200 응답 수 (200 이 없으면 None).
    """
    cam = [r for r in steady if any(m in path_of(r['url']) for m in CAMERA_PATH_MARKS)]
    if not cam:
        return dict(camera_requests=0, camera_304_ratio=None, camera_new_photos=0,
                    camera_new_photo_period_s=None, camera_request_period_s=None,
                    camera_mb_per_hour=None)
    n304 = sum(1 for r in cam if net_status(r) == 304)
    n200 = sum(1 for r in cam if net_status(r) == 200)
    b = sum(r['enc'] for r in cam)
    return dict(
        camera_requests=len(cam), camera_304_ratio=n304 / len(cam), camera_new_photos=n200,
        camera_new_photo_period_s=(dwell_s / n200) if n200 and dwell_s > 0 else None,
        camera_request_period_s=(dwell_s / len(cam)) if dwell_s > 0 else None,
        camera_mb_per_hour=(b / (dwell_s / 3600.0) / 1e6) if dwell_s > 0 else None)


def request_metrics(reqs, settle_s, dwell_s):
    """첫 로드(≤settle_s)와 켜 둔 구간(>settle_s)으로 나눠 요청·전송량·304 를 센다.

    dwell_s 는 켜 둔 구간의 길이(초). 시간당 값은 그 구간을 시간으로 환산한 것이다.
    """
    done = [r for r in reqs if 'enc' in r and not r.get('failed')]
    first = [r for r in done if r['t'] < settle_s]
    steady = [r for r in done if r['t'] >= settle_s]
    n304 = sum(1 for r in steady if net_status(r) == 304)
    steady_bytes = sum(r['enc'] for r in steady)
    ttfbs = [r['ttfb'] for r in done if r.get('ttfb') is not None]
    per_url = {}
    for r in steady:
        d = per_url.setdefault(path_of(r['url']), dict(n=0, bytes=0, n304=0))
        d['n'] += 1
        d['bytes'] += r['enc']
        d['n304'] += net_status(r) == 304
    hours = dwell_s / 3600.0 if dwell_s > 0 else None
    return dict(
        first_requests=len(first),
        first_bytes=sum(r['enc'] for r in first),
        steady_requests=len(steady),
        steady_bytes=steady_bytes,
        steady_304=n304,
        ratio_304=(n304 / len(steady)) if steady else None,
        poll_requests_per_min=(len(steady) / dwell_s * 60) if dwell_s > 0 else None,
        poll_bytes_per_hour=(steady_bytes / hours) if hours else None,
        poll_mb_per_hour=(steady_bytes / hours / 1e6) if hours else None,
        failed_requests=sum(1 for r in reqs if r.get('failed')),
        ttfb_p50_ms=quantile(ttfbs, 0.5),
        ttfb_p95_ms=quantile(ttfbs, 0.95),
        poll_by_url=per_url,
        **camera_metrics(steady, dwell_s),
    )


def total_blocking_time(longtasks, start_ms, end_ms, threshold=50.0):
    """[start_ms, end_ms) 에 시작한 긴 작업의 (길이 - 50ms) 합. longtasks = [(시작ms, 길이ms)]."""
    return sum(max(0.0, d - threshold) for s, d in longtasks if start_ms <= s < end_ms)


def sanitize_har(har):
    """HAR 에서 세션 쿠키·인증 머리글을 지운다(복사본을 돌려준다)."""
    har = json.loads(json.dumps(har))
    for entry in har.get('log', {}).get('entries', []):
        for part in ('request', 'response'):
            node = entry.get(part) or {}
            node['headers'] = [h for h in node.get('headers', [])
                               if h.get('name', '').lower() not in SENSITIVE_HEADERS]
            if 'cookies' in node:
                node['cookies'] = []
    return har


def pattern_from_har(har, settle_ms=5000):
    """HAR → 부하 재생용 요청 패턴.

    첫 로드: 시작 후 settle_ms 안에 시작한 요청 전부(순서 유지, 같은 URL 이 두 번이면 두 번).
    폴링: 그 뒤의 요청을 (메서드, 경로, 본문) 으로 묶어 간격 중앙값을 주기로 삼는다.
    """
    entries = har.get('log', {}).get('entries', [])
    if not entries:
        return dict(first=[], polls=[], settle_ms=settle_ms, span_s=0)
    from datetime import datetime

    def ts(e):
        return datetime.fromisoformat(e['startedDateTime'].replace('Z', '+00:00')).timestamp()
    entries = sorted(entries, key=ts)
    t0 = ts(entries[0])
    # 서버 자신의 요청만 — 막아 둔 외부 자원(CDN·폰트)은 HAR 에 남아 있어도 재생 대상이 아니다
    host = urlsplit(entries[0]['request']['url']).netloc
    first, groups = [], {}
    for e in entries:
        if urlsplit(e['request']['url']).netloc != host or e.get('response', {}).get('status') == 0:
            continue
        rel_ms = (ts(e) - t0) * 1000
        req = e['request']
        u = urlsplit(req['url'])
        target = u.path + (('?' + u.query) if u.query else '')
        body = (req.get('postData') or {}).get('text')
        ctype = (req.get('postData') or {}).get('mimeType')
        item = dict(method=req['method'], url=target, body=body, content_type=ctype)
        if rel_ms < settle_ms:
            first.append(item)
        else:
            key = (req['method'], u.path, body)
            groups.setdefault(key, dict(item, times=[]))['times'].append(rel_ms / 1000)
    span_s = max(0.0, (ts(entries[-1]) - t0) - settle_ms / 1000)
    polls = []
    for g in groups.values():
        times = sorted(g.pop('times'))
        # 위젯 여럿이 같은 요청을 한꺼번에 보내는 묶음(0.5초 안)은 한 번의 주기 사건으로 본다.
        # 묶음 안의 간격을 주기로 읽으면 주기가 0.003초가 되어 부하가 수천 배로 부풀려진다.
        bursts = [[times[0]]]
        for t in times[1:]:
            if t - bursts[-1][-1] < BURST_GAP_S:
                bursts[-1].append(t)
            else:
                bursts.append([t])
        starts = [b[0] for b in bursts]
        gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
        period = quantile(gaps, 0.5) if gaps else None
        g['count'] = len(times)
        g['burst'] = max(1, round(len(times) / len(bursts)))
        # 한 번만 보인 요청은 주기를 모른다 — 구간 전체를 주기로 삼아 "구간당 1회" 로 본다
        g['period_s'] = period if period else max(span_s, 1.0)
        polls.append(g)
    polls.sort(key=lambda g: g['period_s'])
    return dict(first=first, polls=polls, settle_ms=settle_ms, span_s=span_s)
