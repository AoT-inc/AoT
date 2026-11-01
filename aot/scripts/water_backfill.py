#!/usr/bin/env python3
"""물 결과 백필 — 저장된 `duty_log` 기간의 닫힌 날을 `water_run`·`water_day` 에 채운다.

데몬의 시간별 작업(`aot.utils.water_job`)은 최근 며칠만 따라잡는다. 그보다 오래된 날을 저장하려면 이 명령을
한 번 손으로 돌린다. **자동으로 돌지 않는다.** 읽는 쪽(일지·현황·MCP)은 저장되지 않은 날을 읽을 때 계산하므로
백필은 속도와 `water_day` 이력을 위한 것이다.

* 기본은 미리보기(쓰기 없음). `--apply` 를 줘야 쓴다.
* 이미 닫힌 날(`water_day` 가 있는 날)은 건너뛰고, 이미 저장된 실행은 다시 쓰지 않는다 — 여러 번 돌려도 같다.
* `water_run` 은 `aot_calc` 보존(기본 60일)보다 오래된 것은 쓰지 않는다(보존 밖의 점은 Influx 가 거절한다).
  그보다 오래된 날은 일 합계만 남고, 일지는 그 날을 읽을 때 계산한다.
* 계산은 지금 도면 기준이다 — 그때와 도면이 달랐다면 과거 값도 지금 도면으로 푼 값이다. `network_rev` 가 그 판이다.

사용:
    python3 -m aot.scripts.water_backfill --since 2026-09-15                 # 미리보기
    python3 -m aot.scripts.water_backfill --since 2026-09-15 --until 2026-10-31 --apply
    python3 -m aot.scripts.water_backfill --since 2026-09-15 --plot <uuid> --plot <uuid> --apply

@phase active
@stability experimental
"""
import argparse
import json
import sys
import time
from datetime import date


def _day(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError('YYYY-MM-DD 로 적을 것: %s' % text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--since', type=_day, required=True, help='시작일(현지, 포함)')
    ap.add_argument('--until', type=_day, default=None, help='끝일(현지, 포함). 기본은 오늘')
    ap.add_argument('--plot', action='append', default=[], help='구획 uuid. 여러 번 줄 수 있다. 기본은 전부')
    ap.add_argument('--apply', action='store_true', help='실제로 쓴다(기본은 미리보기)')
    ap.add_argument('--json', action='store_true', help='기계 판독')
    args = ap.parse_args(argv)

    from aot.start_flask_ui import app
    from aot.utils import water_job

    started = time.time()
    rows = []
    with app.app_context():
        for plot in water_job.plots_to_store(args.since, args.plot):
            try:
                days = water_job.process_plot(plot, since_day=args.since, until_day=args.until,
                                              write=args.apply)
            except Exception as exc:                        # noqa: BLE001 — 한 구획의 오류가 나머지를 막지 않는다
                rows.append({'plot': plot.unique_id, 'error': repr(exc)})
                continue
            rows.append({'plot': plot.unique_id, 'name': plot.name, 'days': len(days),
                         'closed': sum(1 for d in days if d.get('closed')),
                         'runs': sum(d.get('runs_written', 0) for d in days),
                         'litres': round(sum(d.get('litres', 0.0) for d in days), 1)})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        mode = '기록함' if args.apply else '미리보기(쓰기 없음)'
        print('물 결과 백필 — %s, %.0f초' % (mode, time.time() - started))
        for r in rows:
            if 'error' in r:
                print('  %s  실패: %s' % (r['plot'], r['error']))
            elif r['days']:
                print('  %s  %s  %d일 처리, 닫힌 날 %d, 실행 %d건, %.1f L'
                      % (r['plot'], r['name'] or '', r['days'], r['closed'], r['runs'], r['litres']))
        if not args.apply:
            print('쓰려면 --apply 를 붙인다.')
    return 1 if any('error' in r for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
