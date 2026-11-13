# coding=utf-8
"""p7_05 마이그레이션: 최소 스키마 위에서 upgrade → downgrade → 재실행 안전 (설계 §5.5)."""
import importlib.util
import os

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'alembic_db', 'alembic', 'versions',
                    'p7_05_camera_driver_20261105.py')


def _load():
    spec = importlib.util.spec_from_file_location('p7_05', PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(engine, fn):
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            fn()


def _engine():
    e = sa.create_engine('sqlite://')
    with e.begin() as c:
        c.execute(sa.text('CREATE TABLE tab (unique_id VARCHAR(36) PRIMARY KEY)'))
        c.execute(sa.text('CREATE TABLE camera (id INTEGER PRIMARY KEY, unique_id VARCHAR(36) '
                          'NOT NULL UNIQUE, name TEXT)'))
        c.execute(sa.text('CREATE TABLE "trigger" (id INTEGER PRIMARY KEY, unique_id VARCHAR(36))'))
        c.execute(sa.text("INSERT INTO camera (unique_id, name) VALUES ('c1', 'old')"))
    return e


def test_upgrade_downgrade_roundtrip_keeps_existing_rows():
    m = _load()
    e = _engine()
    _run(e, m.upgrade)
    _run(e, m.upgrade)                                   # 재실행 안전
    insp = sa.inspect(e)
    assert {'camera_driver', 'camera_event'} <= set(insp.get_table_names())
    assert 'tab_id' in {c['name'] for c in insp.get_columns('camera')}
    assert 'event_kinds' in {c['name'] for c in insp.get_columns('trigger')}
    with e.connect() as c:                               # 기존 카메라: 탭 없음 = 전원 공개
        assert c.execute(sa.text("SELECT tab_id FROM camera WHERE unique_id='c1'")).scalar() is None
    _run(e, m.downgrade)
    _run(e, m.downgrade)
    insp = sa.inspect(e)
    assert not {'camera_driver', 'camera_event'} & set(insp.get_table_names())
    assert 'tab_id' not in {c['name'] for c in insp.get_columns('camera')}
    assert 'event_kinds' not in {c['name'] for c in insp.get_columns('trigger')}
    with e.connect() as c:
        assert c.execute(sa.text('SELECT COUNT(*) FROM camera')).scalar() == 1


def test_downgrade_survives_sql_triggers_that_reference_the_trigger_table():
    """지도 무결성 SQL 트리거(geo_itg_*)는 `trigger` 표를 가리킨다. batch 로 표를 다시 만들면
    'no such table: main.trigger' 로 깨진다(8084 사본 실측) — event_kinds 는 네이티브 DROP COLUMN 이어야 한다."""
    m = _load()
    e = _engine()
    with e.begin() as c:
        c.execute(sa.text('CREATE TABLE audit (n INTEGER)'))
        c.execute(sa.text('CREATE TRIGGER geo_itg_probe AFTER DELETE ON "trigger" BEGIN '
                          'UPDATE audit SET n = 1 WHERE n IN (SELECT id FROM "trigger"); END'))
    _run(e, m.upgrade)
    _run(e, m.downgrade)
    insp = sa.inspect(e)
    assert 'event_kinds' not in {c['name'] for c in insp.get_columns('trigger')}
    with e.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'")).scalar() == 1
