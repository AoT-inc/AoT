# coding=utf-8
"""Input.device_status — 수리 중·철거됨·점검 중 센서(리허설 F5/B5, 과제 C1).

  · 상태가 ok 가 아니면 평균에서 빠진다(사유 `device_status:<값>`).
  · 침묵 판정·freshness 에서 '정지' 가 아니라 알려진 상태(known_status)로 나온다.
  · 철거됨은 목록에서 접고 개수만 센다.
  · ok(또는 NULL)는 기존 동작 그대로.
  · 마이그레이션은 재실행 안전·다운그레이드 가능, 기존 행은 NULL(= ok).
"""
import importlib.util
import os
from datetime import datetime
from unittest import mock

from aot.databases.models import Input
from aot.services.resolvers.device_resolver import (
    device_status, device_status_info, is_reliable_sensor)
from aot.tests.test_zone_summary_groups import TestNiyangNursery
from aot.tools.aot_data_tool_service import AoTDataToolService as M


def _set(uid, status, note=None):
    Input.query.filter(Input.unique_id == uid).update({
        'device_status': status, 'device_status_note': note,
        'device_status_since': datetime(2026, 9, 4)})


class TestHelper:
    def test_unknown_or_null_is_ok(self):
        for v in (None, '', 'weird'):
            row = mock.Mock(device_status=v)
            assert device_status(row) == 'ok'
            assert is_reliable_sensor(row)
            assert device_status_info(row) is None

    def test_info_shape(self):
        row = mock.Mock(device_status='repair', device_status_note='측정부 오류',
                        device_status_since=datetime(2026, 9, 4))
        assert not is_reliable_sensor(row)
        assert device_status_info(row) == {
            'status': 'repair', 'note': '측정부 오류', 'since': '2026-09-04T00:00:00'}


class TestZoneAverage(TestNiyangNursery):

    def test_each_status_leaves_the_average_with_reason(self):
        for st in ('repair', 'removed', 'maintenance'):
            _set('fs-geo', st)
            _, z = self._zone()
            assert self._group(z, 'facility')['n_devices'] == 2
            assert {'device': '시설 안 마커',
                    'reason': 'device_status:%s' % st} in z['excluded']
            _set('fs-geo', 'ok')

    def test_ok_and_null_unchanged(self):
        _, base = self._zone()
        _set('fs-geo', 'ok')
        _, z = self._zone()
        assert z['groups'] == base['groups']
        assert not any(e['reason'].startswith('device_status')
                       for e in z.get('excluded', []))

    def test_overview_skips_unreliable_sensor(self):
        _set('fs-geo', 'repair')
        _, z = self._zone(detail=True)
        flagged = [d for d in z['sensors'] if d.get('device_status')]
        assert [d['device_name'] for d in flagged] == ['시설 안 마커']


class TestFreshnessAndSilence(TestNiyangNursery):

    def _fresh(self, **kw):
        with mock.patch.object(M, '_last_seen_seconds',
                               return_value=(10 ** 6, None, 'temperature')):
            return M.get_device_freshness(**kw)

    def test_repair_is_known_status_not_stale(self):
        out0 = self._fresh()
        _set('fs-geo', 'repair', '측정부 오류로 수리 중')
        out = self._fresh()
        assert out['stale_count'] == out0['stale_count'] - 1
        ks = out['known_status_devices']
        assert [e['device_id'] for e in ks] == ['fs-geo']
        assert ks[0]['device_status']['note'] == '측정부 오류로 수리 중'
        assert out['removed_count'] == 0

    def test_removed_is_counted_only(self):
        _set('fs-geo', 'removed')
        out = self._fresh()
        assert out['known_status_count'] == 0
        assert out['removed_count'] == 1
        assert all(e['device_id'] != 'fs-geo' for e in out['stale_devices'])

    def test_ok_has_no_known_status(self):
        out = self._fresh()
        assert out['known_status_count'] == 0 and out['removed_count'] == 0

    def _silent(self):
        with mock.patch.object(M, '_last_seen_seconds',
                               return_value=(None, None, None)):
            return M._silent_devices_in_scope('system', None)

    def test_silent_excludes_known_status_and_lists_it(self):
        base = self._silent()
        _set('fs-geo', 'maintenance', '점검')
        _set('fs-in', 'removed')
        v = self._silent()
        assert v['count'] == base['count'] - 2
        assert v['active_total'] == base['active_total'] - 2
        assert [e['device_id'] for e in v['known_status']] == ['fs-geo']
        assert v['removed_count'] == 1


def _load_migration():
    here = os.path.dirname(os.path.abspath(__file__))
    name = 'p6_85_input_device_status_20261013'
    path = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions',
                        name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn)()


def test_migration_chain_position():
    mod = _load_migration()
    assert mod.down_revision == 'p6_84_matter_enabled_20261010'


def test_migration_up_down_keeps_rows(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE input (id INTEGER PRIMARY KEY, name TEXT)"))
        c.execute(sa.text("INSERT INTO input (name) VALUES ('온습도_7')"))
    mod = _load_migration()
    _run(mod, 'upgrade', engine)
    _run(mod, 'upgrade', engine)            # 재실행 안전
    cols = {c['name'] for c in sa.inspect(engine).get_columns('input')}
    assert {'device_status', 'device_status_note', 'device_status_since'} <= cols
    with engine.begin() as c:
        assert c.execute(sa.text("SELECT device_status FROM input")).scalar() == 'ok'
    _run(mod, 'downgrade', engine)
    _run(mod, 'downgrade', engine)
    cols = {c['name'] for c in sa.inspect(engine).get_columns('input')}
    assert not cols & {'device_status', 'device_status_note', 'device_status_since'}
    with engine.begin() as c:
        assert c.execute(sa.text("SELECT name FROM input")).scalar() == '온습도_7'


class TestDeviceDetail(TestNiyangNursery):

    def test_detail_carries_status_object_and_note(self):
        _set('fs-geo', 'repair', '측정부 오류로 수리 중')
        out = M.get_device_detail(device_id='fs-geo')
        what = out.get('what') or out
        assert what['device_status']['status'] == 'repair'
        assert '측정부 오류로 수리 중' in what['active_note']

    def test_detail_ok_has_no_note(self):
        what = (lambda o: o.get('what') or o)(M.get_device_detail(device_id='fs-geo'))
        assert what['device_status'] == {'status': 'ok'}
        assert what['active_note'] is None
