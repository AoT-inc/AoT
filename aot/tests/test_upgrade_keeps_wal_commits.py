# coding=utf-8
"""업그레이드·백업이 -wal 에 남은 커밋을 잃지 않는지 지키는 회귀 가드.

26.11.1 업데이트에서 `cp databases/*.db` 가 aot.db 본체만 복사해, 마지막
체크포인트 이후의 커밋(프로그램 등록 등)이 두 서버에서 사라졌다.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "aot" / "scripts" / "copy_sqlite_dbs.py"
UPGRADE = REPO / "aot" / "scripts" / "upgrade_install.sh"
BACKUP = REPO / "aot" / "scripts" / "aot_backup_create.sh"


def _make_wal_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")  # 체크포인트 없이 -wal 에만 쌓인다
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.commit()
    for r in rows:
        conn.execute("INSERT INTO t VALUES (?)", (r,))
        conn.commit()
    return conn  # 열어 둔다: 닫으면 체크포인트된다


def test_copy_keeps_commits_that_exist_only_in_wal(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    live = _make_wal_db(str(src / "aot.db"), ["a", "b", "c"])
    try:
        assert (src / "aot.db-wal").stat().st_size > 0
        # 본체만 복사하면 행이 없다는 것을 먼저 확인(= 옛 동작이 위험했던 이유)
        plain = tmp_path / "plain.db"
        plain.write_bytes((src / "aot.db").read_bytes())
        left = sqlite3.connect(str(plain)).execute(
            "select count(*) from sqlite_master where name='t'").fetchone()[0]
        rows_plain = 0 if not left else sqlite3.connect(str(plain)).execute(
            "select count(*) from t").fetchone()[0]
        assert rows_plain < 3

        subprocess.run([sys.executable, str(HELPER), str(src), str(dst)], check=True)
    finally:
        live.close()
    # 읽기 전에 확인한다: WAL 모드 DB 를 열면 SQLite 가 -wal 을 다시 만든다
    assert not (dst / "aot.db-wal").exists()
    got = sqlite3.connect(str(dst / "aot.db")).execute(
        "select v from t order by rowid").fetchall()
    assert got == [("a",), ("b",), ("c",)]


def test_copy_removes_stale_wal_in_destination(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir(), dst.mkdir()
    (dst / "aot.db-wal").write_bytes(b"stale")
    (dst / "aot.db-shm").write_bytes(b"stale")
    live = _make_wal_db(str(src / "aot.db"), ["x"])
    try:
        subprocess.run([sys.executable, str(HELPER), str(src), str(dst)], check=True)
    finally:
        live.close()
    assert not (dst / "aot.db-wal").exists() and not (dst / "aot.db-shm").exists()
    assert sqlite3.connect(str(dst / "aot.db")).execute("select v from t").fetchall() == [("x",)]


def test_copy_fails_loudly_on_a_corrupt_db(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "aot.db").write_bytes(b"not a database" * 100)
    res = subprocess.run([sys.executable, str(HELPER), str(src), str(dst)])
    assert res.returncode == 1


def test_scripts_do_not_copy_db_files_with_plain_cp():
    for script in (UPGRADE, BACKUP):
        text = script.read_text()
        assert "copy_sqlite_dbs.py" in text, script.name
    assert "databases/*.db" not in "".join(
        line for line in UPGRADE.read_text().splitlines(True)
        if line.lstrip().startswith("if ! cp"))


def test_upgrade_stops_web_and_mcp_before_copying():
    text = UPGRADE.read_text()
    stop = text.index("systemctl stop aotflask aotmcp")
    copy = text.index("copy_sqlite_dbs.py")
    assert stop < copy
