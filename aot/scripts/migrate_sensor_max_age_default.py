# coding=utf-8
"""env_coordinator·ext_context_collector 의 `sensor_max_age` 옛 기본값 120초를 '자동' 으로 눕힌다.

수집기(ext_context_collector)는 2026-09-19 에 합류했다 — 같은 옵션·같은 옛
기본값·같은 사고(느린 실외 데이터원이 전부 만료)라 따로 둘 이유가 없다.

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

from aot.utils.measurement_freshness import as_seconds

OLD_DEFAULT = 120.0
DEVICES = ('env_coordinator', 'ext_context_collector')

# 분류 — 화면에 찍는 말과 1:1 이다.
TARGET = 'target'   # 옛 기본값 그대로 → 0 으로 눕힌다
AUTO = 'auto'       # 이미 미지정(0·빈 값) → 센서 주기로 자동 판정 중
KEPT = 'kept'       # 사람이 고른 값 → 손대지 않는다

LABEL = {
    AUTO: '이미 자동 — 미지정, 센서 주기로 판정',
    KEPT: '사람이 고른 값',
}


def classify(value) -> str:
    """저장된 `sensor_max_age` 를 셋 중 하나로 가른다.

    ⚠ **0 을 "사람이 고른 값" 으로 부르지 말 것**(2026-09-20 정정). 0 은 옵션의
    현재 기본값이자 "안 정했다" 는 뜻이다 — 판단은 `measurement_freshness.
    as_seconds` 하나에 맡긴다(0·음수·빈 값·숫자 아님 → 미지정). 여기서 따로
    판단하면 정본과 갈라진다. 예전에는 120 이 아닌 값을 전부 "사람이 고른 값" 으로
    찍어, 이미 자동인 설치를 누가 손으로 정한 것처럼 보고했다.
    """
    try:
        if float(value) == OLD_DEFAULT:
            return TARGET
    except (TypeError, ValueError):
        pass
    return AUTO if as_seconds(value) is None else KEPT


def restart_note(changed_rows) -> str:
    """반영 뒤 안내 — 켜져 있는 Function 만 재시작 대상이다.

    꺼진 Function 은 켤 때 새 값을 읽으므로 재시작할 것이 없다. 예전에는 무엇이
    바뀌었든 "코디네이터를 재시작해야" 라고 찍어, 꺼진 수집기 하나만 바뀐 경우에도
    불필요한 재시작을 권했다.
    """
    active = [name for name, is_active in changed_rows if is_active]
    if active:
        return ('켜져 있는 Function 을 재시작해야 적용됩니다: ' + ', '.join(active))
    return '바뀐 Function 이 모두 꺼져 있어 재시작할 것이 없습니다(켤 때 적용됩니다).'


def collect():
    """(unique_id, 이름, 현재값, 켜짐, 분류) 목록."""
    from aot.databases.models import CustomController
    rows = []
    for row in CustomController.query.filter(
            CustomController.device.in_(DEVICES)).all():
        try:
            opts = json.loads(row.custom_options or '{}')
        except ValueError:
            continue
        value = opts.get('sensor_max_age')
        rows.append((row.unique_id, row.name, value,
                     bool(row.is_activated), classify(value)))
    return rows


def apply_changes(targets):
    from aot.config import SQL_DATABASE_AOT
    from aot.databases.models import CustomController
    from aot.databases.utils import session_scope
    changed = []
    with session_scope(f'sqlite:///{SQL_DATABASE_AOT}') as session:
        for uuid, name, _value, is_active, _kind in targets:
            row = session.query(CustomController).filter(
                CustomController.unique_id == uuid).first()
            if not row:
                continue
            opts = json.loads(row.custom_options or '{}')
            if float(opts.get('sensor_max_age', -1)) != OLD_DEFAULT:
                continue                      # 그 사이에 사람이 고쳤다 — 존중한다
            opts['sensor_max_age'] = 0.0
            row.custom_options = json.dumps(opts)
            changed.append((name, is_active))
    return changed


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='실제로 반영한다')
    args = ap.parse_args()

    # 앱은 여기서 띄운다 — 모듈 머리에서 띄우면 분류 함수만 검사하려 해도
    # 앱 전체가 기동한다.
    from aot.start_flask_ui import app

    with app.app_context():
        try:
            rows = collect()
        except Exception as exc:                             # noqa: BLE001
            print(f'ERROR: 조회 실패 — {exc}', file=sys.stderr)
            return 2

        targets = [r for r in rows if r[4] == TARGET]
        for _u, name, value, _on, kind in rows:
            if kind != TARGET:
                try:
                    shown = f'{float(value):g}초'
                except (TypeError, ValueError):
                    shown = '비어 있음' if value in (None, '') else repr(value)
                print(f'  건너뜀  {name}: {shown} ({LABEL[kind]})')
        for _u, name, value, _on, _k in targets:
            print(f'  대상    {name}: {float(value):g}초 → 0 (센서 주기로 자동)')

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

    print(f'\n{len(changed)}건 반영했습니다. {restart_note(changed)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
