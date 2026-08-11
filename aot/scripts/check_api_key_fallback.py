#!/usr/bin/env python3
# coding=utf-8
"""레거시 API 키 컬럼(`users.api_key_hash`)을 제거해도 되는지 판정한다.

키는 p6_32 부터 `user_api_key` 테이블에 산다. 레거시 컬럼은 **백필이 돌지 않은
서버**를 위해 남겨 둔 폴백이고, 읽기(`User.resolve_api_key`)가 새 테이블 →
레거시 컬럼 순으로 본다. 컬럼을 지우는 것은 "폴백이 쓰이지 않는다" 를 확인한
뒤의 일이다 — 지금 지우면 백필 전인 서버의 모든 API 연동이 즉시 끊긴다.

폴백에 도달하는 조건은 하나뿐이다:

    해시가 users.api_key_hash 에는 있는데 user_api_key 에는 없다

새 테이블에서 찾으면 그 자리에서 끝나고(폐기된 키도 폴백으로 새지 않는다 —
`resolve_api_key` 가 즉시 (None, None) 을 돌려준다), 못 찾을 때만 레거시를 본다.
그래서 위 집합이 비어 있으면 **폴백은 현재 데이터로 도달 불가능**하다.

이 검사는 "지금 데이터가 어떤가" 만 본다. 런타임에 실제로 폴백을 탔는지는
`User._note_legacy_fallback` 이 남기는 경고로 확인한다:

    [API키] 사용자 'xxx' 가 레거시 컬럼(users.api_key_hash)으로 인증됐습니다

둘 다(이 검사 0건 + 그 로그 0줄) 확인해야 컬럼을 지울 수 있다. 검사만으로는
"검사 이후에 들어온 요청" 을 알 수 없고, 로그만으로는 "아직 안 쓴 키가 남아
있는지" 를 알 수 없기 때문이다.

표준 라이브러리만 쓴다 — 설치가 깨진 서버에서도 돌아야 한다. DB 경로는
`aot.config` 에서 가져오되, 못 가져오면 `--db` 로 받는다.

사용:
    python3 -m aot.scripts.check_api_key_fallback
    python3 -m aot.scripts.check_api_key_fallback --db /opt/AoT/aot_local/databases/aot.db
    python3 -m aot.scripts.check_api_key_fallback --json

종료 코드: 0 = 폴백 도달 불가(제거 가능) · 1 = 아직 도달 가능 · 2 = 검사 실패
"""
import argparse
import json
import os
import sqlite3
import sys


def _default_db_path():
    """aot.config 의 DB 경로. 가져오지 못하면 None."""
    try:
        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..')))
        from aot.config import SQL_DATABASE_AOT
        return SQL_DATABASE_AOT
    except Exception:
        return None


def _table_exists(con, name):
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone()
    return row is not None


def inspect(db_path):
    """(결과 dict, 종료코드)."""
    if not db_path or not os.path.exists(db_path):
        return {"error": "DB를 찾을 수 없습니다: {}".format(db_path)}, 2

    # 읽기 전용으로 연다 — 운영 서버에 그대로 돌려도 안전해야 한다.
    con = sqlite3.connect('file:{}?mode=ro'.format(db_path), uri=True)
    try:
        if not _table_exists(con, 'users'):
            return {"error": "users 테이블이 없습니다."}, 2

        columns = [c[1] for c in con.execute("PRAGMA table_info(users)")]
        if 'api_key_hash' not in columns:
            # 이미 제거된 서버 — 할 일이 없다.
            return {"legacy_column": False, "reachable": [],
                    "legacy_total": 0, "backfilled": 0}, 0

        if not _table_exists(con, 'user_api_key'):
            # p6_32 가 아직 안 돌았다. 이 서버는 레거시 컬럼이 유일한 정본이다.
            rows = con.execute(
                "SELECT name FROM users "
                "WHERE api_key_hash IS NOT NULL AND api_key_hash != ''").fetchall()
            return {"legacy_column": True, "migrated": False,
                    "reachable": [r[0] for r in rows],
                    "legacy_total": len(rows), "backfilled": 0}, 1

        legacy_total = con.execute(
            "SELECT COUNT(*) FROM users "
            "WHERE api_key_hash IS NOT NULL AND api_key_hash != ''").fetchone()[0]

        # 폴백에 도달하는 키 = 레거시 컬럼에는 있는데 새 테이블에는 없는 해시.
        reachable = [r[0] for r in con.execute(
            "SELECT name FROM users "
            "WHERE api_key_hash IS NOT NULL AND api_key_hash != '' "
            "AND api_key_hash NOT IN (SELECT key_hash FROM user_api_key) "
            "ORDER BY name")]

        return {"legacy_column": True, "migrated": True,
                "reachable": reachable,
                "legacy_total": legacy_total,
                "backfilled": legacy_total - len(reachable)}, (1 if reachable else 0)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(
        description="레거시 API 키 컬럼을 제거해도 되는지 판정한다.")
    parser.add_argument('--db', default=None, help="aot.db 경로(기본: aot.config)")
    parser.add_argument('--json', action='store_true', help="기계 판독 출력")
    parser.add_argument('--quiet', action='store_true', help="요약만")
    args = parser.parse_args()

    result, code = inspect(args.db or _default_db_path())

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    if 'error' in result:
        print("검사 실패: {}".format(result['error']))
        return code

    if not result.get('legacy_column'):
        print("OK: 레거시 컬럼(users.api_key_hash)이 이미 제거돼 있습니다.")
        return code

    if not result.get('migrated'):
        print("아직 p6_32 가 실행되지 않았습니다 — user_api_key 테이블이 없습니다.")
        print("레거시 컬럼이 유일한 정본이므로 절대 제거하면 안 됩니다. "
              "(레거시 키 {}건)".format(result['legacy_total']))
        return code

    reachable = result['reachable']
    if not args.quiet:
        print("레거시 컬럼 키: {}건 (이관됨 {}건 / 미이관 {}건)".format(
            result['legacy_total'], result['backfilled'], len(reachable)))

    if reachable:
        print("폴백에 도달하는 사용자 {}명 — 백필이 필요합니다:".format(len(reachable)))
        for name in reachable:
            print("  - {}".format(name))
        print("조치: 앱을 재시작해 p6_32 백필을 다시 돌리십시오. "
              "그래도 남으면 그 키는 새 테이블에 없는 값입니다.")
        return code

    print("OK: 폴백에 도달하는 키가 없습니다 — 현재 데이터로는 레거시 컬럼이 "
          "읽히지 않습니다.")
    print("주의: 컬럼 제거 전에 런타임 로그도 함께 확인하십시오 — "
          "'레거시 컬럼(users.api_key_hash)으로 인증됐습니다' 가 0줄이어야 합니다.")
    return code


if __name__ == '__main__':
    sys.exit(main())
