# coding=utf-8
"""MCP 감사로그/승인큐 보존기간 정리 테스트.

`MCPAuditLog` docstring 은 "90일 보존"이라고 적어 놓았지만 그 테이블을 지우는
코드는 어디에도 없었다 — 하루 1회 도는 `_audit_log_purge_job` 은 범용
`audit_log` 만 정리했다. `mcp_confirmation` 도 마찬가지로 아무도 지우지 않았다.

여기서는 mock 없이 임시 sqlite 에 실제 행을 넣고 정리 함수를 태운다
(운영/레포 DB 는 건드리지 않는다). 확인 대상 네 가지:

  1. 보존기간이 지난 행만 지워진다 — 경계 안쪽 행은 남는다.
  2. 두 테이블이 같은 cutoff 로 함께 정리된다(끊어진 confirmation_id 방지).
  3. 보존기간 0 이하면 아무것도 지우지 않는다(자동 정리 끄기).
  4. 정리 쿼리가 타는 인덱스가 실제로 만들어져 있다.
"""
from datetime import datetime, timedelta

import pytest

from aot.aot_flask.extensions import db
import aot.databases.models  # noqa: F401  — 모델 등록(테이블 생성에 필요)
from aot.databases.models import MCPAuditLog, MCPConfirmation
from aot.utils.audit import purge_old_mcp_logs


@pytest.fixture()
def app_ctx(tmp_path):
    """임시 sqlite 에 묶인 앱 컨텍스트."""
    from flask import Flask

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{tmp_path / 'mcp_purge.db'}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


def _seed(age_days, confirmation_id='c-old'):
    """age_days 일 전에 기록된 감사로그 1행 + 대응하는 승인큐 1행."""
    when = datetime.utcnow() - timedelta(days=age_days)

    log = MCPAuditLog(
        timestamp=when,
        agent_id='claude',
        tool_name='operate_device',
        permission='write',
        confirmation_status='approved',
        confirmation_id=confirmation_id,
    )
    confirm = MCPConfirmation(
        unique_id=confirmation_id,
        created_at=when,
        expires_at=when + timedelta(seconds=300),
        tool_name='operate_device',
        agent_id='claude',
        status='consumed',
    )
    db.session.add_all([log, confirm])
    db.session.commit()


def test_purges_only_rows_past_retention(app_ctx):
    _seed(age_days=120, confirmation_id='c-120')   # 90일 초과 — 삭제 대상
    _seed(age_days=89, confirmation_id='c-89')     # 경계 안쪽 — 남아야 한다

    logs, confirms = purge_old_mcp_logs(retention_days=90)

    assert (logs, confirms) == (1, 1)
    assert [r.confirmation_id for r in MCPAuditLog.query.all()] == ['c-89']
    assert [r.unique_id for r in MCPConfirmation.query.all()] == ['c-89']


def test_both_tables_purged_together(app_ctx):
    """감사로그만 지우고 승인큐를 남기면 끊어진 참조가 생긴다 — 함께 지운다."""
    _seed(age_days=200, confirmation_id='c-200')

    purge_old_mcp_logs(retention_days=90)

    assert MCPAuditLog.query.count() == 0
    assert MCPConfirmation.query.count() == 0


def test_pending_rows_are_not_spared(app_ctx):
    """승인 TTL 이 5분이라 보존기간 지난 pending 은 이미 죽은 행이다."""
    when = datetime.utcnow() - timedelta(days=200)
    db.session.add(MCPConfirmation(
        unique_id='c-pending', created_at=when,
        expires_at=when + timedelta(seconds=300),
        tool_name='operate_device', status='pending'))
    db.session.commit()

    _logs, confirms = purge_old_mcp_logs(retention_days=90)

    assert confirms == 1
    assert MCPConfirmation.query.count() == 0


@pytest.mark.parametrize('retention', [0, -1])
def test_zero_or_negative_retention_disables_purge(app_ctx, retention):
    _seed(age_days=9999, confirmation_id='c-ancient')

    assert purge_old_mcp_logs(retention_days=retention) == (0, 0)
    assert MCPAuditLog.query.count() == 1
    assert MCPConfirmation.query.count() == 1


def test_default_retention_comes_from_config(app_ctx):
    """인자를 생략하면 config.MCP_AUDIT_RETENTION_DAYS(90) 를 쓴다."""
    from aot.config import MCP_AUDIT_RETENTION_DAYS

    assert MCP_AUDIT_RETENTION_DAYS == 90

    _seed(age_days=MCP_AUDIT_RETENTION_DAYS + 5, confirmation_id='c-past')
    _seed(age_days=MCP_AUDIT_RETENTION_DAYS - 5, confirmation_id='c-inside')

    assert purge_old_mcp_logs() == (1, 1)
    assert [r.unique_id for r in MCPConfirmation.query.all()] == ['c-inside']


def test_purge_indexes_exist(app_ctx):
    """정리 쿼리(`timestamp < cutoff` / `created_at < cutoff`)가 풀스캔을
    타지 않도록 모델에 선언한 인덱스가 실제로 만들어지는지 확인한다.
    (신규 설치는 alembic 이 아니라 db.create_all 로 이 테이블을 만든다.)"""
    import sqlalchemy as sa

    insp = sa.inspect(db.engine)
    audit_ix = {ix['name'] for ix in insp.get_indexes('mcp_audit_log')}
    confirm_ix = {ix['name'] for ix in insp.get_indexes('mcp_confirmation')}

    assert 'ix_mcp_audit_log_timestamp' in audit_ix
    assert 'ix_mcp_audit_log_confirmation_id' in audit_ix
    assert 'ix_mcp_confirmation_status_created_at' in confirm_ix
    assert 'ix_mcp_confirmation_created_at' in confirm_ix


# ── p6_74 호출 품질 칸 마이그레이션 ─────────────────────────────────────────
# 모델과 마이그레이션을 대조하는 테스트가 따로 없으므로, 이 테스트가 그 몫을
# 한다: 옛 모양 표에 upgrade → downgrade → upgrade 를 두 번씩 태워 멱등인지,
# 올린 뒤 칸이 모델과 같은지 본다. 라이브 DB 가 아니라 임시 sqlite 다.

_P6_74 = 'p6_74_mcp_audit_quality_20260923'


def _load_migration():
    import importlib.util
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions',
                        _P6_74 + '.py')
    spec = importlib.util.spec_from_file_location(_P6_74, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(mod, fn)()


def _cols(engine):
    import sqlalchemy as sa
    return {c['name'] for c in sa.inspect(engine).get_columns('mcp_audit_log')}


def test_p6_74_upgrade_downgrade_is_idempotent(tmp_path):
    import sqlalchemy as sa
    from aot.mcp_server.audit import QUALITY_FIELDS

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as conn:
        # p6_73 시점의 모양 — 품질 칸이 없다.
        conn.execute(sa.text(
            "CREATE TABLE mcp_audit_log (id INTEGER PRIMARY KEY, "
            "unique_id VARCHAR(36) NOT NULL UNIQUE, timestamp DATETIME NOT NULL, "
            "agent_id VARCHAR(100), tool_name VARCHAR(100) NOT NULL, "
            "params_json TEXT, reason TEXT, permission VARCHAR(20), "
            "confirmation_status VARCHAR(20), confirmation_id VARCHAR(36), "
            "user_id VARCHAR(36), result_summary TEXT, error TEXT)"))
        conn.execute(sa.text(
            "INSERT INTO mcp_audit_log (unique_id, timestamp, tool_name) "
            "VALUES ('u1', '2026-09-01 00:00:00', 'search_devices')"))
    base = _cols(engine)
    mod = _load_migration()

    for _ in range(2):
        _run(mod, 'upgrade', engine)
        _run(mod, 'upgrade', engine)          # 두 번 올려도 그대로
        assert _cols(engine) == base | set(QUALITY_FIELDS)
        _run(mod, 'downgrade', engine)
        _run(mod, 'downgrade', engine)
        assert _cols(engine) == base
    _run(mod, 'upgrade', engine)

    # 올린 칸이 모델과 같고, 옛 행은 살아 있으며 새 칸은 NULL 이다.
    assert _cols(engine) == {c.name for c in MCPAuditLog.__table__.columns}
    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT tool_name, duration_ms, call_state FROM mcp_audit_log")).one()
    assert tuple(row) == ('search_devices', None, None)


def test_p6_74_follows_p6_73():
    # 머리(head) 검사는 뒤에 온 마이그레이션의 몫이다(p6_75 는
    # test_mcp_tool_profiles). 여기서는 사슬의 자리만 본다.
    mod = _load_migration()
    assert mod.revision == _P6_74
    assert mod.down_revision == 'p6_73_role_use_ai_chat_20260922'
