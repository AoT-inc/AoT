# coding=utf-8
"""conftest 의 테스트 전용 속도 설정(SQLite fsync 끄기·bcrypt 비용 절감)이 살아 있는지 지킨다.

둘 중 하나가 조용히 사라지면 단위 스위트가 나스에서 다시 몇 배 느려진다 — 여기서 먼저 잡는다.
시간을 재면 부하에 따라 흔들리므로 설정값만 확인한다.
"""
import bcrypt
from sqlalchemy import create_engine, text

from aot.databases.models import User

PASSWORD = 'correct horse battery staple'


def test_sqlite_fsync_is_off_in_tests(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    with engine.connect() as conn:
        assert conn.execute(text('PRAGMA synchronous')).scalar() == 0


def test_password_hash_is_cheap_in_tests():
    user = User()
    user.set_password(PASSWORD)
    assert user.password_hash.startswith(b'$2b$04$'), user.password_hash


def test_cheap_hash_still_verifies():
    user = User()
    user.set_password(PASSWORD)
    assert bcrypt.hashpw(PASSWORD.encode(), user.password_hash) == user.password_hash
    assert bcrypt.hashpw(b'wrong', user.password_hash) != user.password_hash
