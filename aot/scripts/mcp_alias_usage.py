#!/usr/bin/env python3
# coding=utf-8
"""MCP 옛 이름 별칭이 최근에 얼마나 쓰였는지 센다(재설계 PR 9, 2026-11-03).

별칭표(`aot.tools.domain.renames`)는 전환 기간만 둔다 — 기본 표면을 도메인으로 바꾼 뒤 2주 안에 비우는 정리 PR 을 낸다.
비워도 되는지는 이 표가 말한다: 최근 N일 감사 로그(`mcp_audit_log`)의 도메인 도구 호출에서 **옛 op·인자 이름이 실제로 쓰인 수**.
0 에 가까우면 `renames.rows()` 의 항목을 지워도 호출이 깨지지 않는다.

DB 는 읽기 전용으로만 연다. 표준 라이브러리 + 순수 파이썬 별칭표만 쓴다.

    python3 -m aot.scripts.mcp_alias_usage --days 14
    python3 -m aot.scripts.mcp_alias_usage --db /opt/AoT/aot_local/databases/aot.db --days 14
"""
import argparse
import datetime
import os
import sqlite3
import sys


def _default_db():
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
        from aot.config import SQL_DATABASE_AOT
        return SQL_DATABASE_AOT
    except Exception:
        return None


def collect(db_path, days):
    """(표 {옛 이름: [횟수, 마지막]}, 본 호출 수). 감사 표가 없으면 ({}, 0)."""
    from aot.tools.domain import renames
    from aot.tools.domain.registry import DOMAIN_TOOLS
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mcp_audit_log'").fetchone():
            return {}, 0
        from aot.utils.timekit import naive_utc, utc_now        # 감사 행의 timestamp 는 naive UTC
        since = (naive_utc(utc_now()) - datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        marks = ','.join('?' * len(DOMAIN_TOOLS))
        rows = con.execute(
            "SELECT tool_name, params_json, timestamp FROM mcp_audit_log "
            "WHERE timestamp >= ? AND tool_name IN (%s)" % marks, (since,) + tuple(DOMAIN_TOOLS)).fetchall()
    finally:
        con.close()
    return renames.usage(rows), len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--db', default=None, help="aot.db 경로(기본: aot.config)")
    parser.add_argument('--days', type=int, default=14, help="최근 며칠(기본 14)")
    args = parser.parse_args(argv)
    path = args.db or _default_db()
    if not path or not os.path.exists(path):
        print("DB 를 찾지 못했다 — --db 로 경로를 준다.")
        return 2
    from aot.tools.domain import renames
    table, seen = collect(path, args.days)
    print("최근 %d일 도메인 호출 %d건 중 옛 이름이 쓰인 것:" % (args.days, seen))
    registered = renames.rows()
    for old, new, since in registered:
        count, last = table.get(old, [0, None])
        print("  %-48s → %-28s 등록 %s  %4d건%s" % (old, new, since, count, ('  마지막 %s' % last) if last else ''))
    unlisted = sorted(set(table) - {r[0] for r in registered})
    for old in unlisted:                                   # 인자 이름 별칭은 'op=...' 같은 키로 잡힌다
        print("  %-48s %s  %4d건" % (old, ' ' * 38, table[old][0]))
    total = sum(v[0] for v in table.values())
    print("합계 %d건 — %s" % (total, "별칭표를 비워도 된다" if total == 0 else "쓰이는 이름이 남았다: 지우기 전에 확인"))
    return 0


if __name__ == '__main__':
    sys.exit(main())
