#!/usr/bin/env python3
# coding=utf-8
"""그룹 스코프 데이터의 무결성 검사.

정본 설계: `docs/design/access-scope-groups.md` §3-1

접근 제어 데이터는 **틀려도 에러를 내지 않는다.** 죽은 자원을 가리키는 grant 는
평범한 행이고, 멤버가 없는 그룹은 정상적으로 조회되며, 어느 그룹에도 안 든
사용자는 로그인이 잘 된다. 그래서 사람이 화면에서 발견하기 전에 배포가 스스로
알려주게 한다 — `check_geo_integrity.py` 와 같은 자리다.

검사 5종:

| 검사 | 무엇 | 왜 위험한가 |
|------|------|-------------|
| `orphan-grant` | 실존하지 않는 자원을 가리키는 grant | **uuid 가 재사용되면 아무도 부여한 적 없는 권한이 생긴다** |
| `empty-group` | 멤버가 없는 그룹 | 부여만 있고 쓰는 사람이 없다 — 자원이 통째로 잠겨 있을 수 있다 |
| `ungrouped-user` | 어느 그룹에도 안 든 사용자 | 그룹을 쓰는 설치에서는 사실상 아무 grant 도 못 받는 계정 |
| `unscoped-device` | 탭 없는 장치 | 미지정 = 전원 공개이므로 **스코프의 구멍** |
| `legacy-schedule` | 만든 사람 uuid 가 없는 예약 | 발화 시 재검사가 면제되는 **한시 구멍**(§8-7) |

`legacy-schedule` 이 0 이 되기 전에는 "예약 우회로가 닫혔다" 고 말하지 않는다.
1회성 예약은 스스로 사라지지만 **반복(cron) 예약은 사람이 다시 저장해야**
해소되므로, 건수만이 아니라 이름을 함께 찍는다 — 건수만 세면 무엇을 손봐야
하는지 알 수 없다.

표준 라이브러리만 쓰고 DB 를 **읽기 전용**으로 연다. 운영 서버에 그대로
돌려도 된다.

사용:
    python3 -m aot.scripts.check_scope_grants
    python3 -m aot.scripts.check_scope_grants --db /opt/AoT/aot_local/databases/aot.db
    python3 -m aot.scripts.check_scope_grants --json
    python3 -m aot.scripts.check_scope_grants --quiet

종료 코드: 0 = 정상 · 1 = 문제 발견 · 2 = 검사 실패
"""
import argparse
import json
import os
import sqlite3
import sys

#: 부여 대상 종류 → (테이블, uuid 컬럼).
#:
#: `aot.databases.models.user_group.RESOURCE_TYPES` 와 같은 어휘여야 한다.
#: 여기서만 늘리고 저기서 안 늘리면 새 종류의 고아를 영영 못 본다 —
#: `test_scope_grants_check.py` 가 두 목록이 같은지 고정한다.
RESOURCE_TABLES = {
    'tab': ('tab', 'unique_id'),
    'dashboard': ('dashboard', 'unique_id'),
    'geo_map': ('geo_map', 'unique_id'),
    'geo_facility': ('geo_facility', 'unique_id'),
}

#: 탭을 가질 수 있는 장치 테이블. 장치의 스코프 정본은 자기 탭 하나다(§4-3).
DEVICE_TABLES = ('input', 'output', 'function', 'conditional', 'trigger',
                 'pid', 'custom_controller')

#: 출력 순서. 새 검사를 추가하면 **여기에만** 넣으면 된다 — 출력 루프가 이
#: 선언 순서를 따른다. (`check_geo_integrity` 는 예전에 출력 키 목록이 따로
#: 하드코딩돼 있어, 검사를 넣어도 집계에만 잡히고 화면에는 안 나왔다.)
HEADINGS = [
    ('orphan-grant', '실존하지 않는 자원을 가리키는 부여'),
    ('empty-group', '멤버가 없는 그룹'),
    ('ungrouped-user', '어느 그룹에도 속하지 않은 사용자'),
    ('unscoped-device', '탭이 없는 장치 (스코프의 구멍)'),
    ('legacy-schedule', '만든 사람을 모르는 예약 (재검사 면제)'),
]

#: severe = 접근 제어가 의도와 다르게 동작할 수 있는 것.
#: 나머지는 운영상 알아야 할 것이지 그 자체로 고장은 아니다.
SEVERE = {'orphan-grant'}


def _default_db_path():
    try:
        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..')))
        from aot.config import SQL_DATABASE_AOT
        return SQL_DATABASE_AOT
    except Exception:
        return None


def _table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def _columns(con, table):
    return {c[1] for c in con.execute("PRAGMA table_info({})".format(table))}


def _check_orphan_grants(con, findings):
    if not _table_exists(con, 'group_grant'):
        return
    known_groups = set()
    if _table_exists(con, 'user_group'):
        known_groups = {r[0] for r in
                        con.execute("SELECT unique_id FROM user_group")}

    for row in con.execute(
            "SELECT id, group_uuid, resource_type, resource_uuid, level "
            "FROM group_grant"):
        gid, group_uuid, rtype, ruuid, level = row

        # 그룹 자체가 사라진 grant. 그룹 삭제가 grant 를 정리하지 않으면 여기
        # 걸린다 — 그리고 같은 uuid 로 그룹을 다시 만들 수는 없지만(uuid 는
        # 새로 발급된다) 판정 시 그냥 무시되므로 조용히 무의미해진다.
        if known_groups and group_uuid not in known_groups:
            findings['orphan-grant'].append({
                'id': gid, 'reason': 'group-missing',
                'group_uuid': group_uuid,
                'resource_type': rtype, 'resource_uuid': ruuid})
            continue

        target = RESOURCE_TABLES.get(rtype)
        if target is None:
            # 모르는 종류. 어휘가 갈라졌다는 뜻이라 그 자체로 보고 대상이다.
            findings['orphan-grant'].append({
                'id': gid, 'reason': 'unknown-resource-type',
                'group_uuid': group_uuid,
                'resource_type': rtype, 'resource_uuid': ruuid})
            continue

        table, column = target
        if not _table_exists(con, table):
            continue                      # 그 기능이 없는 설치
        hit = con.execute(
            "SELECT 1 FROM {} WHERE {} = ?".format(table, column),
            (ruuid,)).fetchone()
        if hit is None:
            findings['orphan-grant'].append({
                'id': gid, 'reason': 'resource-missing',
                'group_uuid': group_uuid,
                'resource_type': rtype, 'resource_uuid': ruuid,
                'level': level})


def _check_empty_groups(con, findings):
    if not _table_exists(con, 'user_group'):
        return
    has_members = _table_exists(con, 'user_group_member')
    for uid, name in con.execute("SELECT unique_id, name FROM user_group"):
        count = 0
        if has_members:
            count = con.execute(
                "SELECT COUNT(*) FROM user_group_member WHERE group_uuid = ?",
                (uid,)).fetchone()[0]
        if count:
            continue
        grants = 0
        if _table_exists(con, 'group_grant'):
            grants = con.execute(
                "SELECT COUNT(*) FROM group_grant WHERE group_uuid = ?",
                (uid,)).fetchone()[0]
        findings['empty-group'].append({
            'name': name, 'unique_id': uid, 'grants': grants})


def _check_ungrouped_users(con, findings):
    """그룹을 **쓰는** 설치에서만 의미가 있다.

    grant 가 0건이면 모든 자원이 전원 공개이므로 그룹 없는 사용자가 잃는 것이
    없다. 그때도 보고하면 단일 팀 설치에서 전 사용자가 매번 경고로 뜬다.
    """
    if not _table_exists(con, 'group_grant'):
        return
    if con.execute("SELECT COUNT(*) FROM group_grant").fetchone()[0] == 0:
        return
    if not _table_exists(con, 'users'):
        return

    cols = _columns(con, 'users')
    enabled = " AND is_enabled = 1" if 'is_enabled' in cols else ""
    has_members = _table_exists(con, 'user_group_member')

    # 면제 역할은 그룹이 없어도 전체를 조작한다 — 보고 대상이 아니다.
    exempt_roles = set()
    if _table_exists(con, 'roles') and 'bypass_group_scope' in _columns(con, 'roles'):
        exempt_roles = {r[0] for r in con.execute(
            "SELECT id FROM roles WHERE bypass_group_scope = 1")}

    for uid, name, role_id in con.execute(
            "SELECT unique_id, name, role_id FROM users WHERE 1=1" + enabled):
        if role_id in exempt_roles:
            continue
        count = 0
        if has_members:
            count = con.execute(
                "SELECT COUNT(*) FROM user_group_member WHERE user_uuid = ?",
                (uid,)).fetchone()[0]
        if count == 0:
            findings['ungrouped-user'].append({'name': name, 'unique_id': uid})


def _check_unscoped_devices(con, findings):
    """탭 없는 장치. 그룹을 쓰는 설치에서만 보고한다(위와 같은 이유)."""
    if not _table_exists(con, 'group_grant'):
        return
    if con.execute("SELECT COUNT(*) FROM group_grant").fetchone()[0] == 0:
        return

    for table in DEVICE_TABLES:
        if not _table_exists(con, table):
            continue
        cols = _columns(con, table)
        if 'tab_id' not in cols:
            continue
        name_col = 'name' if 'name' in cols else 'unique_id'
        for uid, name in con.execute(
                "SELECT unique_id, {} FROM {} "
                "WHERE tab_id IS NULL OR tab_id = ''".format(name_col, table)):
            findings['unscoped-device'].append({
                'table': table, 'unique_id': uid, 'name': name})


def _check_legacy_schedules(con, findings):
    """소유자를 모르는 예약 — §8-7 의 한시 면제 대상.

    발화 시 재검사(`AISchedulerService._scope_denies`)는 **예약을 만든 사람**
    (`scheduler_jobs_meta.user_id`)으로 판정한다. 그 값이 NULL 이면 물을 사람이
    없어 면제되고, 그 예약은 제어 게이트를 지나지 않는다.

    새 컬럼을 만들지 않은 것이 요지다 — `user_id` 는 이미 있었고, 그래서
    **이 변경 이전에 만들어진 예약도 같은 경로로 검사된다**(kwargs 에 실었다면
    잡스토어에 이미 직렬화된 예약은 영영 검사 밖에 남았을 것이다).

    이 값이 0 이 되기 전에는 "예약 우회로가 닫혔다" 고 말하지 않는다.
    **1회성은 발화하면 사라지지만 반복(cron)은 사람이 다시 저장해야** 해소되므로
    구분해서 이름과 함께 찍는다 — 건수만 세면 무엇을 손봐야 하는지 알 수 없다.

    ⚠ **grant 가 0건이면 보고하지 않는다.** 아무 자원도 제한되지 않는 설치에는
    우회할 게이트 자체가 없다 — 그때도 보고하면 그룹을 쓰지 않는 모든 설치가
    영구히 종료 1 을 내고, 그런 검사는 곧 아무도 안 본다.
    """
    if con.execute("SELECT COUNT(*) FROM group_grant").fetchone()[0] == 0:
        return
    table = 'scheduler_jobs_meta'
    if not _table_exists(con, table):
        return
    cols = _columns(con, table)
    if 'user_id' not in cols:
        return                            # 그 스키마가 아닌 설치

    # 이미 끝난 예약은 다시 발화하지 않으므로 구멍이 아니다. 넣으면 완료된
    # 수백 건이 영구히 쌓여 실제로 손볼 것을 덮는다.
    live_states = ('PENDING', 'RUNNING', 'DRAFT')
    placeholders = ','.join('?' * len(live_states))
    has_state = 'state' in cols
    has_cron = 'schedule_cron' in cols
    label_col = 'action_type' if 'action_type' in cols else 'id'

    query = "SELECT id, {}{} FROM {} WHERE user_id IS NULL".format(
        label_col, ', schedule_cron' if has_cron else '', table)
    args = ()
    if has_state:
        query += " AND state IN ({})".format(placeholders)
        args = live_states

    for row in con.execute(query, args):
        entry = {'id': row[0], 'label': row[1]}
        if has_cron:
            # 1회성은 발화하면 사라지지만 반복은 남는다 — 사람이 다시 저장해
            # 주어야 해소되므로 구분해서 보인다.
            entry['recurring'] = bool(row[2])
        findings['legacy-schedule'].append(entry)


def inspect(db_path):
    if not db_path or not os.path.exists(db_path):
        return {"error": "DB를 찾을 수 없습니다: {}".format(db_path)}, 2

    con = sqlite3.connect('file:{}?mode=ro'.format(db_path), uri=True)
    try:
        findings = {key: [] for key, _ in HEADINGS}
        if not _table_exists(con, 'group_grant'):
            # p6_52 가 아직 안 돌았다. 검사할 것이 없는 것이지 실패가 아니다.
            return {'migrated': False, 'findings': findings, 'counts':
                    {k: 0 for k in findings}}, 0

        _check_orphan_grants(con, findings)
        _check_empty_groups(con, findings)
        _check_ungrouped_users(con, findings)
        _check_unscoped_devices(con, findings)
        _check_legacy_schedules(con, findings)
    except sqlite3.Error as exc:
        return {"error": "SQLite 오류: {}".format(exc)}, 2
    finally:
        con.close()

    counts = {k: len(v) for k, v in findings.items()}
    severe = sum(counts[k] for k in SEVERE)
    # severe 가 아닌 것도 종료 1 로 올린다 — "알아야 할 것" 을 0 으로 보고하면
    # 아무도 안 본다. 심각도는 출력에서 구분한다.
    code = 1 if sum(counts.values()) else 0
    return {'migrated': True, 'findings': findings, 'counts': counts,
            'severe': severe}, code


def _render(result, quiet=False):
    if 'error' in result:
        print("검사 실패: {}".format(result['error']))
        return
    if not result.get('migrated'):
        print("group_grant 테이블이 없습니다 (p6_52 미적용) — 검사할 것이 없습니다.")
        return

    counts = result['counts']
    total = sum(counts.values())
    if total == 0:
        print("정상 — 그룹 스코프 데이터에 문제가 없습니다.")
        return

    for key, title in HEADINGS:
        rows = result['findings'][key]
        if not rows:
            continue
        mark = '심각' if key in SEVERE else '확인'
        print("\n[{}] {} — {}건 ({})".format(key, title, len(rows), mark))
        if quiet:
            continue
        for row in rows[:20]:
            print("    {}".format(json.dumps(row, ensure_ascii=False)))
        if len(rows) > 20:
            print("    … 외 {}건".format(len(rows) - 20))

    print("\n합계 {}건 (심각 {}건)".format(total, result.get('severe', 0)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--db', default=None, help='aot.db 경로')
    parser.add_argument('--json', action='store_true', help='기계 판독')
    parser.add_argument('--quiet', action='store_true', help='건수 요약만')
    args = parser.parse_args()

    result, code = inspect(args.db or _default_db_path())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _render(result, quiet=args.quiet)
    return code


if __name__ == '__main__':
    sys.exit(main())
