#!/usr/bin/env python3
# coding=utf-8
"""통합환경제어의 `shade_transmittance` 를 **시설로** 옮긴다 (설계문서 D9).

차광막은 시설의 물건이고 그 성질은 시설이 안다. 그런데 그 값이 세 곳에 흩어져
있었다:

  · 함수 옵션 `shade_transmittance`      — 사용자가 코디네이터마다 입력
  · 시설 냉방부하 계산                    — **0.50 하드코딩**
  · 액추에이터별 액션 옵션                — 개별 지정(이건 남는다)

이제 정본은 `GeoFacility.envelope.curtain.shade.transmittance` 하나다. 이
스크립트는 함수에 남아 있던 값을 그 자리로 옮긴다.

⚠ **덮어쓰지 않는다.** 시설이 이미 값을 갖고 있으면 건드리지 않는다 — 시설
  쪽이 더 나중에, 더 그 물건을 아는 사람이 정한 값이다. 충돌은 보고만 한다.

⚠ **차광막이 없다고 선언한 시설에는 쓰지 않는다.** 쓰면 화면에 없는 값이
  데이터에만 남아, 나중에 차광막을 켜는 순간 아무도 정한 적 없는 투과율이
  살아난다.

```bash
python3 -m aot.scripts.migrate_shade_transmittance          # 미리보기(쓰기 없음)
python3 -m aot.scripts.migrate_shade_transmittance --apply  # 실제 반영
python3 -m aot.scripts.migrate_shade_transmittance --json
```
종료 0 = 옮길 것 없음 · 1 = 대상 있음(미리보기) 또는 충돌 · 2 = 실패.
**`--apply` 전에 DB 백업.**
"""
import argparse
import json
import sys


def _rows(session):
    from aot.databases.models import CustomController
    from aot.databases.models.geo import GeoFacility
    out = []
    for fn in session.query(CustomController).all():
        if 'env_coordinator' not in (fn.device or ''):
            continue
        try:
            opts = json.loads(fn.custom_options or '{}')
        except (TypeError, ValueError):
            continue
        try:
            tau = float(opts.get('shade_transmittance') or 0.0)
        except (TypeError, ValueError):
            continue
        if not (0.0 < tau <= 1.0):
            continue                       # 0/미설정 — 옮길 것이 없다
        fid = opts.get('geo_facility_id') or ''
        fac = (session.query(GeoFacility)
               .filter(GeoFacility.unique_id == fid).first()) if fid else None
        out.append((fn, tau, fac))
    return out


def _plan(session):
    """세션 **안에서** 필요한 값을 전부 뽑는다 → (계획, 건너뜀).

    ⚠ ORM 행을 세션 밖으로 들고 나가지 말 것. `session_scope` 가 닫히면
      지연 로딩 속성이 `DetachedInstanceError` 로 터진다 — 그것도 **보고를
      찍는 도중에** 터지므로, 일부만 출력된 채 실패한다(2026-08-27 실측).
    """
    plan, skipped = [], []
    for fn, tau, fac in _rows(session):
        name = fn.name or fn.unique_id
        if fac is None:
            skipped.append((name, tau, 'no-facility',
                            '연동 시설이 없다 — 옮길 곳이 없다'))
            continue
        env = dict(fac.envelope or {})
        shade = dict((env.get('curtain') or {}).get('shade') or {})
        if not shade.get('enabled'):
            skipped.append((name, tau, 'no-shade-curtain',
                            '%s: 차광막이 없다고 선언돼 있다' % (fac.name or '')))
            continue
        existing = shade.get('transmittance')
        if existing is not None:
            kind = ('conflict' if abs(float(existing) - tau) > 1e-6
                    else 'already-same')
            skipped.append((name, tau, kind,
                            '%s: 시설 값 %s — 덮어쓰지 않는다'
                            % (fac.name or '', existing)))
            continue
        plan.append((name, tau, fac.name or fac.unique_id, fac.unique_id))
    return plan, skipped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)

    try:
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        from sqlalchemy.orm.attributes import flag_modified
    except Exception as exc:                                    # noqa: BLE001
        print('검사 실패: %s' % exc, file=sys.stderr)
        return 2

    try:
        with session_scope(AOT_DB_PATH) as session:
            plan, skipped = _plan(session)
            if args.apply:
                from aot.databases.models.geo import GeoFacility
                for _name, tau, _fname, fuid in plan:
                    fac = (session.query(GeoFacility)
                           .filter(GeoFacility.unique_id == fuid).first())
                    if fac is None:
                        continue
                    env = dict(fac.envelope or {})
                    curtain = dict(env.get('curtain') or {})
                    shade = dict(curtain.get('shade') or {})
                    shade['transmittance'] = tau
                    curtain['shade'] = shade
                    env['curtain'] = curtain
                    fac.envelope = env
                    flag_modified(fac, 'envelope')
                session.commit()
    except Exception as exc:                                    # noqa: BLE001
        print('검사 실패: %s' % exc, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            'moved' if args.apply else 'to_move': [
                {'function': n, 'transmittance': t, 'facility': fn}
                for n, t, fn, _u in plan],
            'skipped': [{'function': n, 'transmittance': t,
                         'reason': k, 'detail': d}
                        for n, t, k, d in skipped],
        }, ensure_ascii=False, indent=1))
    else:
        verb = '옮겼습니다' if args.apply else '옮길 수 있습니다'
        if plan:
            print('%d건 %s:' % (len(plan), verb))
            for name, tau, fname, _u in plan:
                print('  %-28s %.2f → %s' % (name[:28], tau, fname))
        else:
            print('옮길 것이 없습니다.')
        if skipped:
            print('\n건너뜀 %d건:' % len(skipped))
            for n, t, k, d in skipped:
                print('  %-28s %.2f  [%s] %s' % (n[:28], t, k, d))

    conflicts = [s for s in skipped if s[2] == 'conflict']
    if args.apply:
        return 1 if conflicts else 0
    return 1 if (plan or conflicts) else 0


if __name__ == '__main__':
    sys.exit(main())
