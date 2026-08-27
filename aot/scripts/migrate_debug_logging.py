#!/usr/bin/env python3
# coding=utf-8
"""옛 옵션 `debug_logging` 을 컬럼 `log_level_debug` 로 옮긴다 (2026-08-27).

통합환경제어에는 같은 뜻의 스위치가 둘이었고(함수 옵션 `debug_logging` + 화면
위 [기본 설정] 의 `log_level_debug`), 그것을 하나로 합쳤다. 그런데 **값을 옮기지
않았다** — 옛 옵션이 켜져 있던 코디네이터가 꺼진 컬럼을 읽게 되어, 켜 둔 사람이
아무것도 안 했는데 **사이클 결정 로그 기록이 멈췄다.**

증상이 조용하다. 제어는 그대로 돌고, 화면도 그대로다. 없어지는 것은 **나중에
"왜 그렇게 했나" 를 묻을 근거**뿐이라, 물어볼 일이 생겼을 때 비로소 드러난다 —
실제로 그렇게 발견했다(영양·쿠마모토 점검 중 편차·적분 채널이 비어 있었다).

⚠ **켜 두었던 것만 켠다.** 옛 옵션이 꺼져 있었거나 없던 코디네이터는 건드리지
  않는다 — 아무도 켠 적 없는 로그를 켜면 그것도 사람이 정하지 않은 변경이다.

```bash
python3 -m aot.scripts.migrate_debug_logging          # 미리보기(쓰기 없음)
python3 -m aot.scripts.migrate_debug_logging --apply
```
종료 0 = 옮길 것 없음 · 1 = 대상 있음(미리보기) · 2 = 실패.
"""
import argparse
import json
import sys


def _plan(session):
    from aot.databases.models import CustomController
    out = []
    for fn in session.query(CustomController).all():
        if 'env_coordinator' not in (fn.device or ''):
            continue
        try:
            opts = json.loads(fn.custom_options or '{}')
        except (TypeError, ValueError):
            continue
        was_on = bool(opts.get('debug_logging'))
        if was_on and not fn.log_level_debug:
            out.append((fn.unique_id, fn.name or fn.unique_id))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    try:
        from aot.config import AOT_DB_PATH
        from aot.databases.models import CustomController
        from aot.databases.utils import session_scope
        with session_scope(AOT_DB_PATH) as s:
            plan = _plan(s)
            if args.apply:
                for uid, _n in plan:
                    row = (s.query(CustomController)
                           .filter(CustomController.unique_id == uid).first())
                    if row is not None:
                        row.log_level_debug = True
                s.commit()
    except Exception as exc:                                    # noqa: BLE001
        print('실패: %s' % exc, file=sys.stderr)
        return 2

    verb = '켰습니다' if args.apply else '켤 수 있습니다'
    if plan:
        print('%d건 %s:' % (len(plan), verb))
        for _uid, name in plan:
            print('  %s' % name)
        print('\n⚠ 재시작해야 데몬이 새 값을 읽습니다.')
    else:
        print('옮길 것이 없습니다.')
    return 0 if args.apply or not plan else 1


if __name__ == '__main__':
    sys.exit(main())
