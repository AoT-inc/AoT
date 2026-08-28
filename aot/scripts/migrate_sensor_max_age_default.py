# coding=utf-8
"""env_coordinator 의 `sensor_max_age` 옛 기본값 120초를 '자동' 으로 눕힌다.

120초는 **기본값이었지 누가 고른 값이 아니다.** 그런데 그보다 느린 센서는 전부
만료로 걸려 그 축이 통째로 죽는다 — 기상청 300초 · OpenWeather 600초라 실외
데이터원은 사실상 전부다. 육묘장3 이 이 값 그대로였고, 측창 둘이 24시간 내내
`실외 값 없음` 으로 서 있었다(2026-08-28). 영양·쿠마모토가 1200 인 것은 누군가
같은 일을 겪고 손으로 고쳤다는 뜻이다 — 같은 일이 이미 두 번 있었다.

기본값을 0(= 센서가 정한다)으로 바꿨지만 **그것만으로는 기존 설치가 안 낫는다**.
저장된 값은 그대로 남기 때문이다. 이 스크립트가 그 간극을 메운다.

**정확히 120.0 인 것만 건드린다.** 사람이 고른 값(1200 등)은 손대지 않는다 —
숫자를 판단으로 덮어쓰면 그 사람이 왜 그 값을 넣었는지 알 방법이 사라진다.

    python3 -m aot.scripts.migrate_sensor_max_age_default            # 미리보기
    python3 -m aot.scripts.migrate_sensor_max_age_default --apply    # 실제 반영

종료 0=바꿀 것 없음/성공, 1=바꿀 것 있음(미리보기), 2=실패.
⚠ `--apply` 전에 DB 를 백업할 것.
"""

import argparse
import json
import sys

from aot.start_flask_ui import app
from aot.databases.models import CustomController
from aot.databases.utils import session_scope
from aot.config import SQL_DATABASE_AOT

OLD_DEFAULT = 120.0


def collect():
    """(unique_id, 이름, 현재값) 중 옛 기본값 그대로인 것."""
    targets, kept = [], []
    for row in CustomController.query.filter(
            CustomController.device == 'env_coordinator').all():
        try:
            opts = json.loads(row.custom_options or '{}')
        except ValueError:
            continue
        value = opts.get('sensor_max_age')
        if value is None:
            continue
        if float(value) == OLD_DEFAULT:
            targets.append((row.unique_id, row.name, float(value)))
        else:
            kept.append((row.unique_id, row.name, float(value)))
    return targets, kept


def apply_changes(targets):
    changed = 0
    with session_scope(f'sqlite:///{SQL_DATABASE_AOT}') as session:
        for uuid, _name, _value in targets:
            row = session.query(CustomController).filter(
                CustomController.unique_id == uuid).first()
            if not row:
                continue
            opts = json.loads(row.custom_options or '{}')
            if float(opts.get('sensor_max_age', -1)) != OLD_DEFAULT:
                continue                      # 그 사이에 사람이 고쳤다 — 존중한다
            opts['sensor_max_age'] = 0.0
            row.custom_options = json.dumps(opts)
            changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='실제로 반영한다')
    args = ap.parse_args()

    with app.app_context():
        try:
            targets, kept = collect()
        except Exception as exc:                             # noqa: BLE001
            print(f'ERROR: 조회 실패 — {exc}', file=sys.stderr)
            return 2

        for _u, name, value in kept:
            print(f'  건너뜀  {name}: {value:g}초 (사람이 고른 값)')
        for _u, name, value in targets:
            print(f'  대상    {name}: {value:g}초 → 0 (센서 주기로 자동)')

        if not targets:
            print('바꿀 것이 없습니다.')
            return 0

        if not args.apply:
            print(f'\n미리보기입니다. {len(targets)}건을 바꾸려면 --apply 를 붙이세요.')
            print('⚠ DB 를 먼저 백업하세요.')
            return 1

        try:
            changed = apply_changes(targets)
        except Exception as exc:                             # noqa: BLE001
            print(f'ERROR: 반영 실패 — {exc}', file=sys.stderr)
            return 2

    print(f'\n{changed}건 반영했습니다. 코디네이터를 재시작해야 적용됩니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
