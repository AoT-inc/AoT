# coding=utf-8
"""동시 사용자 부하 재생 — HAR 의 요청 패턴을 locust 로 N 명 재생한다.

    # 1) 측정 실행기가 남긴 HAR 에서 패턴을 뽑는다
    python -m aot.tests.dashboard_bench.loadgen extract \
        --har .local/bench/results/pc/har/<조건>/run1_tab0.har --out .local/bench/pattern_P2.json
    # 2) 10명으로 60초 재생
    python -m aot.tests.dashboard_bench.loadgen run --url http://서버 --pattern .local/bench/pattern_P2.json \
        --users 10 --duration 60 --label pc_P2_u10

locust 는 저장소 밖 가상환경에 설치한다(저장소 의존성이 아니다):
    python3 -m venv ~/.venvs/aot-bench && ~/.venvs/aot-bench/bin/pip install locust
    export AOT_BENCH_LOCUST=~/.venvs/aot-bench/bin/locust
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time

from aot.tests.dashboard_bench import harstats
from aot.tests.dashboard_bench.aotclient import default_credentials

HERE = os.path.dirname(os.path.abspath(__file__))


def cmd_extract(args):
    with open(args.har, encoding='utf-8') as fh:
        har = json.load(fh)
    pat = harstats.pattern_from_har(har, settle_ms=int(args.settle * 1000))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(pat, fh, ensure_ascii=False, indent=1)
    per_min = sum(60.0 / g['period_s'] * g.get('burst', 1) for g in pat['polls'] if g['period_s'] > 0)
    print(f'첫 로드 요청 {len(pat["first"])}개, 폴링 {len(pat["polls"])}종 (분당 약 {per_min:.1f}건) → {args.out}')
    return 0


def parse_locust_stats(csv_path):
    """locust `--csv` 의 *_stats.csv → {aggregate: {...}, endpoints: [...]}."""
    rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))

    def row(r):
        def f(k):
            try:
                return float(r[k])
            except (KeyError, ValueError):
                return None
        return dict(name=r['Name'], method=r.get('Type'), requests=int(f('Request Count') or 0),
                    failures=int(f('Failure Count') or 0), rps=f('Requests/s'),
                    avg_ms=f('Average Response Time'), p50_ms=f('50%'), p95_ms=f('95%'),
                    p99_ms=f('99%'), max_ms=f('Max Response Time'))
    agg = [row(r) for r in rows if r['Name'] == 'Aggregated']
    ends = [row(r) for r in rows if r['Name'] != 'Aggregated']
    ends.sort(key=lambda e: -(e['p95_ms'] or 0))
    return dict(aggregate=agg[0] if agg else None, endpoints=ends)


def login_cookie_pool(url, n, user, password):
    """n 번 로그인해 세션 쿠키 목록을 만든다 — 메모리에서만 쓰고 locust 에 환경변수로 넘긴다."""
    from aot.tests.dashboard_bench.aotclient import AotClient
    pool = []
    for _ in range(n):
        c = AotClient(url, user, password)
        pool.append({ck.name: ck.value for ck in c.s.cookies})
    return pool


def locust_cmd(locust, args, users, duration, spawn_rate, prefix):
    return [locust, '-f', os.path.join(HERE, 'locustfile.py'), '--headless', '--host', args.url.rstrip('/'),
            '-u', str(users), '-r', str(spawn_rate), '-t', f'{int(duration)}s',
            '--csv', prefix, '--only-summary']


def cmd_run(args):
    locust = args.locust or os.environ.get('AOT_BENCH_LOCUST') or shutil.which('locust')
    if not locust:
        sys.exit('locust 를 찾지 못했습니다. 저장소 밖 가상환경에 설치하고 AOT_BENCH_LOCUST 를 지정하세요(--help 참고).')
    user, password = (args.user, args.password) if args.user else default_credentials()
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(out_dir, args.label)
    env = dict(os.environ, AOT_BENCH_PATTERN=os.path.abspath(args.pattern),
               AOT_BENCH_USER=user, AOT_BENCH_PASSWORD=password)
    if args.cookie_pool:
        env['AOT_BENCH_COOKIE_POOL'] = json.dumps(login_cookie_pool(args.url, args.cookie_pool, user, password))
        print(f'세션 쿠키 풀 {args.cookie_pool}개로 로그인 없이 재생', flush=True)
    if args.warmup > 0:
        # 예열: 같은 방식으로 몇 명이 잠깐 돌며 템플릿·캐시를 데운다. 결과 파일은 `.warmup` 접두사로 따로 두고 집계에서 뺀다
        # (집계기는 `*.load.json` 만 읽는다).
        wu = max(1, min(args.users, 5))
        print(f'예열 {args.warmup:g}초 (사용자 {wu}명, 집계 제외)', flush=True)
        subprocess.run(locust_cmd(locust, args, wu, args.warmup, wu, prefix + '.warmup'),
                       env=env, capture_output=True, text=True)
    cmd = locust_cmd(locust, args, args.users, args.duration, args.spawn_rate, prefix)
    print('locust 사용자', args.users, '시간', args.duration, '초', flush=True)
    started = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    ended = time.time()
    if proc.returncode not in (0, 1):
        sys.exit(f'locust 실패 (코드 {proc.returncode}): {proc.stderr[-400:]}')
    result = parse_locust_stats(prefix + '_stats.csv')
    result.update(measured_start=round(started, 1), measured_end=round(ended, 1),
                  cookie_pool=args.cookie_pool, warmup_s=args.warmup, spawn_rate=args.spawn_rate, label=args.label, url=args.url, users=args.users, duration_s=args.duration,
                  pattern=os.path.basename(args.pattern))
    agg = result['aggregate'] or {}
    result['server_p95_ms'] = agg.get('p95_ms')
    result['fail_ratio'] = (agg['failures'] / agg['requests']) if agg.get('requests') else None
    with open(prefix + '.load.json', 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(f'요청 {agg.get("requests")}건, {agg.get("rps") or 0:.1f} req/s, '
          f'p50 {agg.get("p50_ms")}ms p95 {agg.get("p95_ms")}ms 실패 {agg.get("failures")}')
    print('저장:', prefix + '.load.json')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='HAR 패턴 → locust 부하 재생')
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract', help='HAR → 패턴 JSON')
    e.add_argument('--har', required=True)
    e.add_argument('--out', required=True)
    e.add_argument('--settle', type=float, default=5.0, help='첫 로드로 치는 초(기본 5)')
    r = sub.add_parser('run', help='패턴을 N 명으로 재생')
    r.add_argument('--url', required=True)
    r.add_argument('--pattern', required=True)
    r.add_argument('--users', type=int, default=10)
    r.add_argument('--duration', type=float, default=60)
    r.add_argument('--spawn-rate', type=float, default=2.0, help='초당 새 사용자 수')
    r.add_argument('--label', default='load')
    r.add_argument('--out', default='.local/bench/results/load')
    r.add_argument('--cookie-pool', type=int, default=0,
                   help='N>0: 미리 N 번만 로그인해 세션 쿠키를 만들고 사용자들이 나눠 쓴다(로그인 제한·비용을 정상 부하에서 뗀다)')
    r.add_argument('--warmup', type=float, default=0,
                   help='측정 전 예열 시간(초). 몇 명이 같은 패턴을 돌며 캐시를 데우고 결과는 집계에서 뺀다')
    r.add_argument('--user')
    r.add_argument('--password')
    r.add_argument('--locust', help='locust 실행 파일(기본: $AOT_BENCH_LOCUST 또는 PATH)')
    args = ap.parse_args(argv)
    if args.cmd == 'run' and ':8084' in args.url:
        print('주의: 8084 는 개발 서버입니다.', file=sys.stderr)
    return cmd_extract(args) if args.cmd == 'extract' else cmd_run(args)


if __name__ == '__main__':
    sys.exit(main())
