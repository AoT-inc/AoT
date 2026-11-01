#!/usr/bin/env python3
# coding=utf-8
"""폐루프 추적(trace.json) → 극적인 순간의 시간표.

`run.sh` 가 만든 `<시나리오>__<변형>.trace.json` 에서 사이클마다 한 줄을 뽑는다: 실외 참값(기온·RH·풍속/
돌풍·강우)과 **제어기가 실제로 받은 값**(10 분 평균 풍속·15 분 누적 강수, 두절이면 `-`), 실내 참값,
게이트·비상, 장치별 `물리위치%/명령%(이유)`.

사용:
  python3 timeline.py <trace.json> --events                 # 시나리오의 극적인 순간(최대풍·호우·낙폭·두절 …)
  python3 timeline.py <trace.json> --h 18:22                # 시작 후 18~22 h
  python3 timeline.py <trace.json> --from "2027-09-06 08:00" --to "2027-09-06 12:00" --every 1
  python3 timeline.py <A.trace.json> --b <B.trace.json> --events   # 두 코드 판을 나란히(장치 열만 B 가 추가)
  python3 timeline.py <trace.json> --events --md             # 마크다운 코드블록으로

명령 이유 번호는 `log_channels.REASON_*` 이다(코디네이터가 장치마다 내는 마지막 최종 명령의 이유).
"""
import argparse
import bisect
import datetime as dt
import json
import sys

KST = dt.timezone(dt.timedelta(hours=9))


def _ts(s):
    return dt.datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=KST).timestamp()


def _hhmm(t):
    return dt.datetime.fromtimestamp(t, KST).strftime('%d %H:%M')


def _short(a):
    """장치 약칭: 측창 우 → 'V우', 분무 → 'F', 차광 → 'S', 커튼 → 'C', 팬 → 'P' …"""
    k, n = a.get('kind'), (a.get('name') or '')
    tail = n.replace('3포장-', '').replace('측창', '').strip()
    return {'opening': 'V' + (tail[:2] if tail else ''), 'fogger': 'F', 'shade': 'S',
            'curtain': 'C', 'exhaust_fan': 'X', 'intake_fan': 'I', 'circulation_fan': 'Z',
            'heater': 'H', 'cooler': 'K'}.get(k, (k or '?')[:2])


def _load(p):
    return json.load(open(p))


def _wxf(w, key, t):
    ts = w['t']
    vs = w.get(key)
    if not vs:
        return None
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return vs[0]
    if i >= len(ts) - 1:
        return vs[-1]
    f = (t - ts[i]) / (ts[i + 1] - ts[i])
    return vs[i] + (vs[i + 1] - vs[i]) * f


def events(tr, pad_h):
    """극적인 순간 → [(이름, t_from, t_to)] (겹치면 합친다)."""
    w = tr['weather']
    meta = tr['meta']
    t0, t1 = meta['t0'], meta['t_end']
    ts = w['t']
    out = []

    def add(name, t):
        out.append((name, max(t0, t - pad_h * 3600), min(t1, t + pad_h * 3600)))
    n = len(ts)
    wind10 = []
    for i in range(n):
        lo = max(0, i - 9)
        wind10.append(sum(w['wind'][lo:i + 1]) / (i + 1 - lo))
    if max(wind10) >= 8.0:
        add('최대풍(10분평균 %.0f m/s)' % max(wind10), ts[wind10.index(max(wind10))])
    if max(w['rain']) >= 5.0:
        add('최대 강우 %.0f mm/h' % max(w['rain']), ts[w['rain'].index(max(w['rain']))])
    # 가장 가파른 외기 하강(20 분)
    k = 20
    best, bi = 0.0, None
    for i in range(n - k):
        d = w['T'][i] - w['T'][i + k]
        if d > best:
            best, bi = d, i
    if best >= 5.0:
        add('외기 급강하 %.1f K/20분' % best, ts[bi] + 600)
    if min(w['T']) < 2.0:
        add('외기 최저 %.1f °C' % min(w['T']), ts[w['T'].index(min(w['T']))])
    # 일사 급증(안개 걷힘 등): 20 분 사이 300 W/m² 이상 증가
    best, bi = 0.0, None
    for i in range(n - k):
        d = w['solar'][i + k] - w['solar'][i]
        if d > best:
            best, bi = d, i
    if best >= 300.0:
        add('일사 급증 +%.0f W/m²/20분' % best, ts[bi] + 600)
    for f in (meta.get('scenario_meta') or {}).get('faults') or []:
        if str(f.get('kind', '')).startswith('outdoor_'):
            a = t0 + float(f.get('start_h') or 0.0) * 3600
            b = t0 + float(f['end_h']) * 3600 if f.get('end_h') is not None else t1
            out.append(('실외 관측소 두절(%s)' % f['kind'], max(t0, a - pad_h * 1800),
                        min(t1, b + pad_h * 1800)))
    # 예보 강수
    if w.get('fc_rain') and max(w['fc_rain']) > 0:
        i = w['fc_rain'].index(max(w['fc_rain']))
        add('예보 모델 강수 최대 %.1f mm' % max(w['fc_rain']), ts[i])
    out.sort(key=lambda e: e[1])
    merged = []
    for name, a, b in out:
        if merged and a <= merged[-1][2]:
            merged[-1] = (merged[-1][0] + ' + ' + name, merged[-1][1], max(merged[-1][2], b))
        else:
            merged.append((name, a, b))
    return merged


def render(tr, trb, t_from, t_to, every, out):
    meta = tr['meta']
    w = tr['weather']
    acts = meta['actuators']
    names = [_short(a) for a in acts]
    cyc = [c for c in tr['cycles'] if t_from <= c['t'] <= t_to]
    cb = {c['t']: c for c in (trb['cycles'] if trb else [])}
    head = ('시각(KST)  | 외기 T  RH  풍속(돌풍) 비mm/h 일사 | 제어기가 본 풍·15분비(예보) | 실내 T  RH | 게이트/비상 | '
            + ' '.join(names))
    if trb:
        head += ' || B: 게이트 ' + ' '.join(names)
    print(head, file=out)

    def dev_cells(c):
        cells = []
        for a, nm in zip(acts, names):
            aid = a['actuator_id']
            ph = (c.get('phys') or {}).get(aid)
            fin = (c.get('finals') or {}).get(aid)
            cmd = ''
            if fin and fin[0] is not None:
                cmd = '→%g' % fin[0] + ('(r%s)' % fin[1] if fin[1] is not None else '')
            elif (c.get('gate_forced') or {}).get(aid) is not None:
                cmd = '→%g(G)' % c['gate_forced'][aid]
            cells.append('%s%s%s' % (nm, '' if ph is None else '%g' % ph, cmd))
        return ' '.join(cells)
    for i, c in enumerate(cyc):
        if i % every:
            continue
        e = c.get('ext') or {}
        s = c.get('seen') or {}
        tr_ = c.get('truth') or {}
        gate = (c.get('gate_desc') or '').replace(' ', '')
        em = c.get('emergency')
        if em and em[0]:
            gate += ('!' + str(em[1]))[:24]
        seen = '풍%s 비%s' % ('-' if s.get('wind') is None else '%.1f' % s['wind'],
                              '-' if s.get('rain15') is None else '%.2f' % s['rain15'])
        if s.get('fc_rain') is not None:
            seen += ' 예보%.1f' % s['fc_rain']
        line = '%s | %5.1f %3.0f %4.1f(%4.1f) %5.1f %4.0f | %-20s | %5.1f %3.0f | %-22s | %s' % (
            _hhmm(c['t']), e.get('T') or 0, e.get('RH') or 0, e.get('wind') or 0,
            e.get('gust') or (e.get('wind') or 0), e.get('rain') or 0, e.get('solar') or 0,
            seen, tr_.get('T') or 0, tr_.get('RH') or 0, gate[:22], dev_cells(c))
        if trb and c['t'] in cb:
            cbb = cb[c['t']]
            g2 = (cbb.get('gate_desc') or '').replace(' ', '')
            line += ' || %-14s %s' % (g2[:14], dev_cells(cbb))
        print(line, file=out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('trace')
    ap.add_argument('--b', help='비교할 두 번째 trace.json(같은 시나리오)')
    ap.add_argument('--events', action='store_true')
    ap.add_argument('--pad', type=float, default=1.0, help='--events 가 잡는 앞뒤 시간(h)')
    ap.add_argument('--h', help='시작 후 시간 구간 "a:b"')
    ap.add_argument('--from', dest='t_from')
    ap.add_argument('--to', dest='t_to')
    ap.add_argument('--every', type=int, default=1, help='N 사이클마다 한 줄')
    ap.add_argument('--md', action='store_true')
    a = ap.parse_args()
    tr = _load(a.trace)
    trb = _load(a.b) if a.b else None
    meta = tr['meta']
    out = sys.stdout
    if a.md:
        print('```', file=out)
    if a.events:
        for name, t_a, t_b in events(tr, a.pad):
            print('\n## %s  [%s ~ %s]' % (name, _hhmm(t_a), _hhmm(t_b)), file=out)
            render(tr, trb, t_a, t_b, a.every, out)
    else:
        if a.h:
            x, y = [float(v) for v in a.h.split(':')]
            t_a, t_b = meta['t0'] + x * 3600, meta['t0'] + y * 3600
        else:
            t_a = _ts(a.t_from) if a.t_from else meta['t0']
            t_b = _ts(a.t_to) if a.t_to else meta['t_end']
        render(tr, trb, t_a, t_b, a.every, out)
    if a.md:
        print('```', file=out)


if __name__ == '__main__':
    main()
