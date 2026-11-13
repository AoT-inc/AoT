# coding=utf-8
"""결과 집계기 — 조건별 표(마크다운 + JSON)를 내고 임계값과 비교해 통과/경고/불통을 매긴다.

    python -m aot.tests.dashboard_bench.aggregate --results .local/bench/results/pc \
        --cores 8 --out .local/bench/report-pc

읽는 파일(결과 폴더 안):
    <조건>.summary.json     측정 실행기(runner.py)의 조건별 요약
    <조건>.server.csv       (선택) 같은 시간에 server_sampler.py 가 뽑은 서버 표본
    *.load.json             (선택) loadgen.py 부하 재생 결과 — 동시 사용자 표

임계값은 `config/thresholds.json` 에서 읽는다(제안서 6절). 코드에 숫자를 두지 않는다.
판정: 값 ≤ pass → 통과, ≤ warn → 경고, 그보다 크면 불통. 값이 없으면 판정에서 뺀다.
"""
import argparse
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_THRESHOLDS = os.path.join(HERE, 'config', 'thresholds.json')

PASS, WARN, FAIL, NA = '통과', '경고', '불통', '-'
_RANK = {PASS: 0, WARN: 1, FAIL: 2}


def load_thresholds(path=None):
    with open(path or DEFAULT_THRESHOLDS, encoding='utf-8') as fh:
        return json.load(fh)['metrics']


def evaluate(value, spec):
    """값 하나를 기준표 항목(spec)과 비교해 통과/경고/불통/- 를 돌려준다."""
    if value is None or spec is None:
        return NA
    if value <= spec['pass']:
        return PASS
    warn = spec.get('warn')
    if warn is not None and value <= warn:
        return WARN
    return FAIL


def worst(verdicts):
    """판정들 중 가장 나쁜 것. 판정할 게 하나도 없으면 '-'."""
    ranked = [v for v in verdicts if v in _RANK]
    return max(ranked, key=lambda v: _RANK[v]) if ranked else NA


def read_server_csv(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return rows


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def server_stats(rows, cores=1.0, skip_s=0.0):
    """서버 표본 → 평균 CPU(% of 전체 용량)·최대·메모리·온도·스로틀.

    - 시스템 CPU(`sys_cpu_pct`, ssh 방식)가 있으면 그 평균을 쓴다(이미 전체 대비 %).
    - 없으면 컨테이너 CPU(docker stats, 코어 1개 = 100%)를 `cores` 로 나눠 전체 대비 %로 바꾼다.
    - skip_s: 맨 앞 몇 초를 버린다(첫 로드 스파이크는 따로 보려면 0).
    """
    if not rows:
        return {}
    t0 = min(_num(r['ts']) for r in rows if _num(r.get('ts')) is not None)
    rows = [r for r in rows if (_num(r.get('ts')) or 0) - t0 >= skip_s]
    sys_cpu = [v for v in (_num(r.get('sys_cpu_pct')) for r in rows) if v is not None]
    proc_cpu = [v for v in (_num(r.get('cpu_pct')) for r in rows) if v is not None]
    # docker 는 컨테이너 여러 개가 같은 시각에 여러 행이다 — 시각별로 합친다
    by_ts = {}
    for r in rows:
        c = _num(r.get('cpu_pct'))
        if c is not None:
            by_ts[r['ts']] = by_ts.get(r['ts'], 0.0) + c
    if sys_cpu:
        cpu_series, basis = sys_cpu, '시스템 전체'
    else:
        cpu_series, basis = [v / max(cores, 1e-9) for v in by_ts.values()], f'프로세스 합 / {cores:g}코어'
    mem = [v for v in (_num(r.get('mem_mb')) for r in rows) if v is not None]
    temp = [v for v in (_num(r.get('temp_c')) for r in rows) if v is not None]
    throttled = 0
    for r in rows:
        raw = (r.get('throttled') or '').strip()
        if raw:
            try:
                throttled |= int(raw, 16) & 0xF       # 현재 상태 비트(저전압·주파수 제한·스로틀·온도 제한)
            except ValueError:
                pass
    return dict(
        samples=len(rows), cpu_basis=basis,
        cpu_avg_pct=(sum(cpu_series) / len(cpu_series)) if cpu_series else None,
        cpu_max_pct=max(cpu_series) if cpu_series else None,
        proc_cpu_peak_pct=max(by_ts.values()) if by_ts else None,
        mem_max_mb=max(mem) if mem else None,
        temp_max_c=max(temp) if temp else None,
        throttled=throttled if any((r.get('throttled') or '').strip() for r in rows) else None,
        disk_util_max_pct=max([v for v in (_num(r.get('disk_util_pct')) for r in rows) if v is not None] or [None]),
    )


def condition_metrics(summary, server=None, load=None):
    """조건 하나의 판정용 값 모음."""
    st = summary['stats']

    def med(k):
        return (st.get(k) or {}).get('median')
    net = summary['options']['net']
    m = dict(
        lcp_ms=med('lcp_ms'),
        tbt_ms=med('tbt_ms'),
        main_cpu_avg_pct=med('main_cpu_avg_pct'),
        poll_mb_per_hour=med('poll_mb_per_hour'),
        ttfb_p95_ms=med('ttfb_p95_ms'),
        net=net,
    )
    m['server_p95_ms'] = (load or {}).get('server_p95_ms') if load else med('ttfb_p95_ms')
    if server:
        m['server_cpu_avg_pct'] = server.get('cpu_avg_pct')
        m['server_throttled'] = server.get('throttled')
    return m


def judge(metrics, thresholds):
    """값 → {지표: 판정}. when_net 이 있는 지표는 그 회선에서만 판정한다."""
    out = {}
    for key, spec in thresholds.items():
        when = spec.get('when_net')
        if when and metrics.get('net') not in when:
            out[key] = NA
            continue
        out[key] = evaluate(metrics.get(key), spec)
    return out


def collect(results_dir, thresholds, cores=1.0, skip_s=0.0):
    conditions, loads = [], []
    for path in sorted(glob.glob(os.path.join(results_dir, '*.summary.json'))):
        with open(path, encoding='utf-8') as fh:
            summary = json.load(fh)
        label = summary['label']
        server = None
        csv_path = os.path.join(results_dir, label + '.server.csv')
        if os.path.exists(csv_path):
            server = server_stats(read_server_csv(csv_path), cores=cores, skip_s=skip_s)
        metrics = condition_metrics(summary, server)
        verdicts = judge(metrics, thresholds)
        conditions.append(dict(
            label=label, options=summary['options'], repeats=summary['repeats'],
            visibility_ok=summary.get('visibility_ok'),
            metrics=metrics, server=server, verdicts=verdicts, overall=worst(verdicts.values()),
            stats={k: summary['stats'][k] for k in (
                'lcp_ms', 'tbt_ms', 'poll_mb_per_hour', 'main_cpu_avg_pct', 'first_requests', 'first_bytes',
                'ratio_304', 'heap_max_mb', 'camera_requests', 'camera_304_ratio', 'camera_new_photo_period_s',
                'camera_request_period_s', 'camera_mb_per_hour') if k in summary['stats']}))
    for path in sorted(glob.glob(os.path.join(results_dir, '*.load.json'))):
        with open(path, encoding='utf-8') as fh:
            load = json.load(fh)
        server = None
        csv_path = path.replace('.load.json', '.server.csv')
        if os.path.exists(csv_path):
            server = server_stats(read_server_csv(csv_path), cores=cores, skip_s=skip_s)
        agg = load.get('aggregate') or {}
        v = {}
        v['server_p95_ms'] = evaluate(agg.get('p95_ms'), thresholds.get('server_p95_ms'))
        if server:
            v['server_cpu_avg_pct'] = evaluate(server.get('cpu_avg_pct'), thresholds.get('server_cpu_avg_pct'))
            v['server_throttled'] = evaluate(server.get('throttled'), thresholds.get('server_throttled'))
        loads.append(dict(label=load['label'], users=load['users'], duration_s=load['duration_s'],
                          requests=agg.get('requests'), rps=agg.get('rps'), p50_ms=agg.get('p50_ms'),
                          p95_ms=agg.get('p95_ms'), p99_ms=agg.get('p99_ms'),
                          fail_ratio=load.get('fail_ratio'), server=server, verdicts=v,
                          overall=worst(v.values()), top_endpoints=load.get('endpoints', [])[:5]))
    return dict(conditions=conditions, loads=loads)


# --- 마크다운 ---------------------------------------------------------------
def _fmt(v, nd=0, suffix=''):
    return '-' if v is None else f'{v:.{nd}f}{suffix}'


def _cell(value, verdict, nd=0):
    return f'{_fmt(value, nd)} ({verdict})' if verdict != NA else _fmt(value, nd)


def render_markdown(report, thresholds):
    out = ['# 대시보드 리소스 측정 결과', '']
    out.append('판정 기준(`config/thresholds.json`): ' + ', '.join(
        f'{s["label"]} ≤ {s["pass"]}{s["unit"]}' + (f'(경고 ≤ {s["warn"]})' if s.get('warn') is not None else '')
        for s in thresholds.values()))
    out.append('')
    if report['conditions']:
        out += ['## 조건별 (클라이언트 중앙값, 사분위 범위는 JSON 참고)', '',
                '| 프로필 | 회선 | CPU 감속 | 캐시 | 탭 | 기기 | 노출 | 반복 | LCP ms | TBT ms | 켜 둔 메인 % | 폴링 MB/h | 서버 CPU % | p95 ms | 가시성 | 종합 |',
                '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        for c in report['conditions']:
            o, m, v = c['options'], c['metrics'], c['verdicts']
            vis = '-' if o['tabs'] <= 1 else ('정상' if c['visibility_ok'] else '폴링 멈춤 의심')
            out.append('| ' + ' | '.join([
                o['profile'], o['net'], f'{o["cpu"]:g}x', o['cache'], str(o['tabs']), o['device'], o['exposure'],
                str(c['repeats']),
                _cell(m.get('lcp_ms'), v.get('lcp_ms', NA)),
                _cell(m.get('tbt_ms'), v.get('tbt_ms', NA)),
                _cell(m.get('main_cpu_avg_pct'), v.get('main_cpu_avg_pct', NA), 1),
                _cell(m.get('poll_mb_per_hour'), v.get('poll_mb_per_hour', NA), 2),
                _cell(m.get('server_cpu_avg_pct'), v.get('server_cpu_avg_pct', NA), 1),
                _cell(m.get('server_p95_ms'), v.get('server_p95_ms', NA)),
                vis, f'**{c["overall"]}**']) + ' |')
        out += ['', '폴링 MB/h 는 LTE·저속 LTE 에서만 판정한다. 서버 CPU 는 같은 시간대 서버 표본이 있을 때만 채운다.', '']
    cams = [c for c in report['conditions']
            if ((c['stats'].get('camera_requests') or {}).get('median') or 0) > 0]
    if cams:
        out += ['## 카메라 위젯 (사진 요청)', '',
                '시간당 전송량은 갱신 주기가 아니라 **새 사진 주기 × 사진 크기**로 정해진다(304 는 사진이 그대로라는 뜻).', '',
                '| 프로필 | 회선 | CPU 감속 | 사진 요청 | 요청 주기 s | 304 비율 | 새 사진 주기 s | 사진 MB/h |',
                '|---|---|---|---|---|---|---|---|']
        for c in cams:
            o, st = c['options'], c['stats']

            def md(k, nd=0):
                return _fmt((st.get(k) or {}).get('median'), nd)
            ratio = (st.get('camera_304_ratio') or {}).get('median')
            out.append('| ' + ' | '.join([
                o['profile'], o['net'], f'{o["cpu"]:g}x', md('camera_requests'), md('camera_request_period_s', 1),
                '-' if ratio is None else f'{ratio * 100:.0f}%', md('camera_new_photo_period_s', 1),
                md('camera_mb_per_hour', 1)]) + ' |')
        out.append('')
    if report['loads']:
        out += ['## 동시 사용자 (부하 재생)', '',
                '| 라벨 | 사용자 | 시간 s | 요청 | req/s | p50 ms | p95 ms | p99 ms | 실패율 | 서버 CPU % | 종합 |',
                '|---|---|---|---|---|---|---|---|---|---|---|']
        for l in report['loads']:
            cpu = (l['server'] or {}).get('cpu_avg_pct')
            out.append('| ' + ' | '.join([
                l['label'], str(l['users']), f'{l["duration_s"]:g}', str(l['requests']), _fmt(l['rps'], 1),
                _fmt(l['p50_ms']), _cell(l['p95_ms'], l['verdicts'].get('server_p95_ms', NA)), _fmt(l['p99_ms']),
                _fmt((l['fail_ratio'] or 0) * 100, 1, '%') if l['fail_ratio'] is not None else '-',
                _cell(cpu, l['verdicts'].get('server_cpu_avg_pct', NA), 1), f'**{l["overall"]}**']) + ' |')
        out.append('')
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='측정 결과 집계기')
    ap.add_argument('--results', required=True, help='runner 가 결과를 쓴 폴더')
    ap.add_argument('--thresholds', default=DEFAULT_THRESHOLDS)
    ap.add_argument('--cores', type=float, default=1.0, help='서버 코어 수(docker 컨테이너 CPU 를 전체 대비로 바꿀 때)')
    ap.add_argument('--skip-seconds', type=float, default=0.0, help='서버 표본 앞부분 버리기')
    ap.add_argument('--out', help='출력 접두(.md 와 .json 을 쓴다). 없으면 표준출력만')
    args = ap.parse_args(argv)
    thresholds = load_thresholds(args.thresholds)
    report = collect(args.results, thresholds, cores=args.cores, skip_s=args.skip_seconds)
    md = render_markdown(report, thresholds)
    print(md)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out + '.md', 'w', encoding='utf-8') as fh:
            fh.write(md)
        with open(args.out + '.json', 'w', encoding='utf-8') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print('저장:', args.out + '.md', args.out + '.json', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
