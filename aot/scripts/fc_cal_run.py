#!/usr/bin/env python3
# coding=utf-8
"""예보 현장 보정을 한 번 돌려 본다 — 데몬 예약 작업(`forecast_data.calibrate`)과 같은 코드(`aot.utils.fc_cal`).

    python3 aot/scripts/fc_cal_run.py --dry                 # 모든 대지 점검 결과만 본다(아무것도 쓰지 않는다)
    python3 aot/scripts/fc_cal_run.py --site <대지 uuid>      # 한 대지를 실제로 점검한다(판·성적·알림을 쓴다)

이력은 L0 예보 발표본이 쌓인 만큼만 있다(시간별은 2026-10-25 부터). 14일 미만이면 '표본 부족' 으로 나오는 것이 정상이다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--site', help='대지 uuid(없으면 예보 출처가 지정된 모든 대지)')
    ap.add_argument('--dry', action='store_true', help='계산·판정만 하고 아무것도 쓰지 않는다')
    ap.add_argument('--reduced', action='store_true', help='저사양 축소 동작으로')
    args = ap.parse_args(argv)

    from aot.aot_flask.app import create_app
    from aot.utils.fc_cal import job
    from aot.utils.fc_cal.runner import calibrate_site
    from aot.utils.fc_cal.sources import InfluxSources

    app = create_app()
    with app.app_context():
        io = InfluxSources()
        p = job.params_for_profile(True if args.reduced else None)
        sites = [args.site] if args.site else [s for s in io.sites() if io.has_forecast(s)]
        for sid in sites:
            s = calibrate_site(sid, io, params=p, dry=args.dry, email=not args.dry)
            by = {}
            for i in s['items']:
                by.setdefault((i['kind'], i['var']), []).append('%s:%s' % (i['band'], i['status']))
            print(json.dumps({'site': sid, 'rev': s['rev'], 'mode': s['mode'], 'dry': s['dry'],
                              'events': s['events'], 'timed_out': s['timed_out'],
                              'items': {'%s/%s' % k: v for k, v in by.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
