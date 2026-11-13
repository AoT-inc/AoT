# coding=utf-8
"""옛 `irrigation_design` 표 정리 이전(p7_02) 시험 (물 회로 계획서 13절 결정 6).

- 0행이면 표를 지운다
- 행이 있으면 표를 그대로 둔다(자체 설치 운영자의 설계를 지우지 않는다)
- 표가 없어도 실패하지 않는다
- downgrade 는 빈 표를 되만든다
"""
import importlib.util
import logging
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (Path(__file__).resolve().parents[2] / 'alembic_db' / 'alembic' / 'versions'
             / 'p7_02_drop_irrigation_design_20261102.py')
TABLE = 'irrigation_design'


def _load_migration():
    spec = importlib.util.spec_from_file_location('p7_02_drop_irrigation_design', str(MIGRATION))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDropIrrigationDesign(unittest.TestCase):
    def setUp(self):
        self.mig = _load_migration()
        self.engine = sa.create_engine('sqlite://')

    def _run(self, fn):
        with self.engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                fn()

    def _has_table(self):
        return TABLE in set(sa.inspect(self.engine).get_table_names())

    def _make_table(self, rows=0):
        self._run(self.mig.downgrade)
        with self.engine.begin() as conn:
            for i in range(rows):
                conn.execute(sa.text(
                    "INSERT INTO irrigation_design (unique_id, name) VALUES (:u, :n)"),
                    {'u': 'id-%d' % i, 'n': '설계 %d' % i})

    def test_revision_chain(self):
        self.assertEqual(self.mig.revision, 'p7_02_drop_irrigation_design_20261102')
        self.assertEqual(self.mig.down_revision, 'p7_01_facility_layout_20261102')
        # 최신 리비전은 뒤 마이그레이션이 올린다 — 여기서는 이 리비전이 체인에 있다는 것만 본다(head 는 alembic-chain 검사가 지킨다).
        self.assertTrue(self.mig.revision.startswith('p7_02_'))

    def test_empty_table_is_dropped(self):
        self._make_table(rows=0)
        self.assertTrue(self._has_table())
        self._run(self.mig.upgrade)
        self.assertFalse(self._has_table())

    def test_table_with_rows_is_kept_and_warns(self):
        self._make_table(rows=2)
        with self.assertLogs('alembic.runtime.migration', level=logging.WARNING) as cm:
            self._run(self.mig.upgrade)
        self.assertTrue(self._has_table())
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(sa.text('SELECT COUNT(*) FROM irrigation_design')).scalar(), 2)
        self.assertIn(TABLE, cm.output[0])

    def test_missing_table_passes(self):
        self.assertFalse(self._has_table())
        self._run(self.mig.upgrade)
        self.assertFalse(self._has_table())

    def test_upgrade_is_rerunnable(self):
        self._make_table(rows=0)
        self._run(self.mig.upgrade)
        self._run(self.mig.upgrade)
        self.assertFalse(self._has_table())

    def test_downgrade_recreates_empty_table_and_is_rerunnable(self):
        self._run(self.mig.downgrade)
        self._run(self.mig.downgrade)           # 이미 있어도 안전
        self.assertTrue(self._has_table())
        cols = {c['name'] for c in sa.inspect(self.engine).get_columns(TABLE)}
        self.assertTrue({'unique_id', 'name', 'boundary_json', 'rows_json', 'sprinklers_json',
                         'config_json', 'status', 'function_id', 'created_by'} <= cols)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(sa.text('SELECT COUNT(*) FROM irrigation_design')).scalar(), 0)


class TestCodeRemoved(unittest.TestCase):
    def test_model_is_gone(self):
        import aot.databases.models as models
        self.assertFalse(hasattr(models, 'IrrigationDesign'))
        self.assertNotIn(TABLE, models.db.metadata.tables)

    def test_design_routes_use_no_table(self):
        src = (Path(__file__).resolve().parents[1] / 'aot_flask' / 'api' / 'design_ref.py').read_text(encoding='utf-8')
        self.assertNotIn('IrrigationDesign', src)
        self.assertIn("route('/rows')", src)


if __name__ == '__main__':
    unittest.main()
