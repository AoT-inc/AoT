#!/usr/bin/env python3
# coding=utf-8
"""SQLite 데이터베이스(*.db)를 -wal 에 남은 커밋까지 포함해 일관되게 복사한다.

앱은 WAL 모드(PRAGMA journal_mode=WAL)로 DB 를 연다. 마지막 체크포인트 이후의
커밋은 `aot.db` 가 아니라 `aot.db-wal` 에만 있으므로, `cp *.db` 는 그 변경을
조용히 버린다(26.11.1 업데이트에서 두 서버가 이전 상태로 돌아간 원인).
sqlite3 백업 API 는 WAL 을 읽어 한 시점의 일관된 사본을 만든다.
쓰는 쪽이 아직 살아 있어도 안전하다.

사용: copy_sqlite_dbs.py SRC_DIR DST_DIR
  SRC_DIR 바로 아래의 *.db 만 복사한다(하위 폴더·-wal·-shm 은 건드리지 않는다).
  DST 에 같은 이름의 -wal/-shm 이 있으면 먼저 지운다(옛 로그가 새 본체에 붙어
  손상되는 것을 막는다).
종료 코드: 0 성공, 1 실패(복사하지 못한 DB 가 있음).
"""
import os
import sqlite3
import sys


def copy_db(src, dst):
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.remove(dst + suffix)
        except FileNotFoundError:
            pass
    tmp = dst + ".copying"
    if os.path.exists(tmp):
        os.remove(tmp)
    # 읽기 전용으로 열면 -shm 을 못 만드는 환경이 있어 일반 연결을 쓰되 쓰지 않는다.
    source = sqlite3.connect(src, timeout=30)
    try:
        dest = sqlite3.connect(tmp)
        try:
            source.backup(dest)
            # 사본은 WAL 아닌 기본 모드로 두지 않는다: 앱이 연결할 때 WAL 로 바꾼다.
        finally:
            dest.close()
    finally:
        source.close()
    check = sqlite3.connect(tmp)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        os.remove(tmp)
        raise RuntimeError("integrity_check: %s" % result)
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(tmp + suffix)
        except FileNotFoundError:
            pass
    os.replace(tmp, dst)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src_dir, dst_dir = argv[1], argv[2]
    os.makedirs(dst_dir, exist_ok=True)
    failed = 0
    for name in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, name)
        if not name.endswith(".db") or not os.path.isfile(src):
            continue
        try:
            copy_db(src, os.path.join(dst_dir, name))
            print("copied %s" % name)
        except Exception as err:  # noqa: BLE001 - 어떤 실패든 업그레이드를 멈춘다
            failed += 1
            print("FAILED %s: %s" % (name, err))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
