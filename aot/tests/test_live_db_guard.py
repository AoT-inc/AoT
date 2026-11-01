# coding=utf-8
"""`_live_db_guard.refuse_live_db()` — 라이브 DB 에서 테이블을 비우는 픽스처를 막는다.

배경은 가드 모듈 머리말 참조(2026-10-10 `mcp_audit_log`·`mcp_confirmation` 전량 유실).
"""
import os
from unittest import mock

import pytest

from aot import config
from aot.tests import _live_db_guard as guard


def _point_at(tmp_path, monkeypatch, db_file):
    monkeypatch.setattr(config, 'SQL_DATABASE_AOT', str(db_file))
    monkeypatch.setattr(config, 'AOT_DB_PATH', 'sqlite:///' + str(db_file))
    monkeypatch.delenv(guard.ALLOW_ENV, raising=False)


def test_temp_database_is_allowed(tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch, tmp_path / 'aot.db')
    guard.refuse_live_db()


def test_repo_default_database_is_refused(tmp_path, monkeypatch):
    live = os.path.join(config.PROJECT_DATABASE_PATH, config.DATABASE_NAME)
    _point_at(tmp_path, monkeypatch, live)
    with pytest.raises(RuntimeError, match='AOT_LOCAL_DIR'):
        guard.refuse_live_db()


def test_container_live_database_is_refused(tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch, '/app/aot_local/databases/aot.db')
    with pytest.raises(RuntimeError, match='AOT_LOCAL_DIR'):
        guard.refuse_live_db()


def test_override_env_lets_it_through(tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch, '/app/aot_local/databases/aot.db')
    with mock.patch.dict(os.environ, {guard.ALLOW_ENV: '1'}):
        guard.refuse_live_db()


def test_override_must_be_exactly_one(tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch, '/app/aot_local/databases/aot.db')
    with mock.patch.dict(os.environ, {guard.ALLOW_ENV: 'true'}):
        with pytest.raises(RuntimeError):
            guard.refuse_live_db()


def test_in_memory_database_is_allowed(tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch, tmp_path / 'aot.db')
    monkeypatch.setattr(config, 'AOT_DB_PATH', 'sqlite:///:memory:')
    guard.refuse_live_db()
