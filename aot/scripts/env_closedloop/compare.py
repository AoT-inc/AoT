#!/usr/bin/env python3
# coding=utf-8
"""폐루프 결과 비교표 — 결과 폴더 하나면 KPI 표, 둘이면 A→B 표.

사용:
  python3 compare.py <결과폴더A> [<결과폴더B>] [--md] [--variant orig|fans] [--actuators] [--storm]

각 폴더의 `<시나리오>__<변형>.summary.json` 을 읽는다(run.sh 가 만든다).
A/B 표의 칸은 같으면 값 하나, 다르면 `A→B` 다. --md 는 마크다운 표.
--actuators 는 장치별 이동·반전·펄스 수(시간당)를 덧붙인다.
--storm 은 극한 기상 열(`metrics.STORM_COLUMNS` — 강풍 중 열림·비 들이침·두절 중 열림·서리·밤 젖음 …)
로 바꾼다. 없는 값은 `-`.
"""
import argparse
import glob
import json
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# metrics 는 순수 모듈이다 — 패키지(env_control/__init__)를 거치지 않고 파일로 읽는다.
_METRICS = os.path.abspath(os.path.join(
    HERE, '..', '..', 'functions', 'utils', 'env_control', 'sim', 'metrics.py'))
_spec = importlib.util.spec_from_file_location('_envsim_metrics', _METRICS)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
KPI_COLUMNS, STORM_COLUMNS, fmt = _m.KPI_COLUMNS, _m.STORM_COLUMNS, _m.fmt


def load(d):
    out = {}
    for p in sorted(glob.glob(os.path.join(d, '*.summary.json'))):
        s = json.load(open(p))
        out[(s.get('scenario'), s.get('variant'))] = s
    return out


def cell(a, b, key, f):
    va = a.get(key) if a else None
    vb = b.get(key) if b else None
    if b is None:
        return fmt(va, f)
    sa, sb = fmt(va, f), fmt(vb, f)
    return sa if sa == sb else f'{sa}→{sb}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dirs', nargs='+')
    ap.add_argument('--md', action='store_true')
    ap.add_argument('--variant')
    ap.add_argument('--actuators', action='store_true')
    ap.add_argument('--storm', action='store_true', help='극한 기상 열로 본다')
    a = ap.parse_args()
    A = load(a.dirs[0])
    B = load(a.dirs[1]) if len(a.dirs) > 1 else None
    keys = sorted(set(A) | set(B or {}), key=lambda k: (k[1] or '', k[0] or ''))
    if a.variant:
        keys = [k for k in keys if k[1] == a.variant]
    cols = STORM_COLUMNS if a.storm else KPI_COLUMNS
    head = ['scenario', 'db'] + [c[0] for c in cols]
    rows = []
    for k in keys:
        sa = A.get(k)
        sb = B.get(k) if B is not None else None
        r = [k[0], k[1]] + [cell(sa or {}, sb if B is not None else None, key, f)
                            for _, key, f in cols]
        na = (sa or sb or {}).get('not_applicable')
        if na:
            r[0] += '(*)'
        rows.append(r)
    if a.md:
        print('| ' + ' | '.join(head) + ' |')
        print('|' + '---|' * len(head))
        for r in rows:
            print('| ' + ' | '.join(r) + ' |')
    else:
        w = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
        print('  '.join(h.ljust(n) for h, n in zip(head, w)))
        for r in rows:
            print('  '.join(str(x).ljust(n) for x, n in zip(r, w)))
    if any('(*)' in r[0] for r in rows):
        print('(*) 시나리오가 요구하는 장치가 이 DB 에 없음 — 고장이 효과를 내지 못한다')
    if a.actuators:
        print()
        for k in keys:
            for tag, src in (('A', A), ('B', B)):
                s = (src or {}).get(k)
                if not s:
                    continue
                for aid, v in (s.get('actuators') or {}).items():
                    print(f"{k[0]:24s} {k[1]:5s} {tag} {v['kind']:12s} {str(v['name'])[:16]:16s} "
                          f"mv/h={v['moves_per_h']:.2f} rev/h={v['reversals_per_h']:.2f} "
                          f"pulse/h={v['pulse_starts_per_h']:.2f} cmd_rev/h="
                          f"{v['cmd_reversals_per_h']:.2f} mean={v['mean_pos']}")


if __name__ == '__main__':
    main()
