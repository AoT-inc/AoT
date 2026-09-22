# coding=utf-8
"""`migrate_legacy_coordinator_targets` — 옛 코디네이터 목표가 **제어에 다시 닿는가**.

`fe6e37b4` 가 목표 옵션을 이관 없이 뺀 뒤, 구획이 없는 시설의 코디네이터는
조용히 guide 중앙값으로 돌았다. 이 스크립트가 만든 프로그램·구획을
`coordinator_plot.control_targets` 가 **실제로 읽어 내는지**까지 본다 — 행이
생겼다는 것만으로는 제어가 그 값을 쓰는지 알 수 없다(축 판정이 `measurement`·
`shape` 로 가므로 키만 맞아서는 안 닿는다).

지키는 것:
- 곡선(Method)을 쓰던 축은 곡선으로, 숫자를 쓰던 축은 숫자로 풀린다.
- 사람이 만든 구획이 있는 시설은 건드리지 않는다(합치지 않는다).
- 시설 미지정·사라진 곡선은 만들지 않거나 묶지 않고 **말한다**.
- 두 번 돌려도 한 벌이다.
- 옛 옵션 값은 지우지 않는다.
"""
import io
import json
import os
import unittest
from datetime import date


class _Fixture(object):

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'legacy_targets.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import (
            CustomController, GeoFacility, GeoPlot, GeoProgram, Method)
        for model in (GeoPlot, GeoProgram, CustomController, GeoFacility, Method):
            model.query.delete()
        db.session.commit()

    # ── 준비물 ─────────────────────────────────────────────────────────
    def _facility(self, name='육묘장'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility
        fac = GeoFacility(geo_id='map-legacy', name=name,
                          shape_uuid='shape-' + name, bays=[])
        db.session.add(fac)
        db.session.commit()
        return fac

    def _method(self, name='육묘 VPD'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Method
        m = Method(name=name, method_type='DailyMultiPoint')
        db.session.add(m)
        db.session.commit()
        return m

    def _coord(self, facility=None, active=True, name='C', **opts):
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController
        base = {'geo_facility_id': facility.unique_id if facility else '',
                'bay_scope': ''}
        base.update(opts)
        fn = CustomController(name=name, device='env_coordinator',
                              is_activated=active,
                              custom_options=json.dumps(base))
        db.session.add(fn)
        db.session.commit()
        return fn

    def _run(self, apply=False, **kw):
        from aot.scripts import migrate_legacy_coordinator_targets as mig
        buf = io.StringIO()
        code = mig.run(apply=apply, out=buf, **kw)
        return code, buf.getvalue()

    def _targets(self, fn):
        from aot.aot_flask.geo.coordinator_plot import control_targets
        from aot.databases.models import CustomController
        return control_targets(
            CustomController.query.filter_by(unique_id=fn.unique_id).first())


class TestMapping(_Fixture, unittest.TestCase):

    def test_method_bound_vpd_resolves_as_a_curve(self):
        """aot-005 모양 — 곡선 VPD + 숫자 CO₂·DLI·GDD + 시작일."""
        fac = self._facility()
        m = self._method()
        fn = self._coord(fac, vpd_sp_type='method', vpd_method_id=m.unique_id,
                         target_vpd=0.8, co2_sp_type='static', target_co2=800.0,
                         dli_target=14.0, gdd_target_daily=16.0,
                         schedule_start_time='2026-07-28', crop_preset='lettuce')

        code, text = self._run()
        self.assertEqual(1, code, text)
        self.assertIn("VPD 곡선 '육묘 VPD'", text)
        # 곡선을 쓰던 축의 숫자는 옛 코드도 읽지 않았다 — 옮기지 않고 말한다.
        self.assertIn('target_vpd=0.8', text)

        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        t = self._targets(fn)
        self.assertEqual('ok', t['reason'])
        self.assertEqual(m.unique_id, t['vpd']['method_id'])
        self.assertIsNone(t['vpd']['value'])
        self.assertEqual(800.0, t['co2']['value'])
        self.assertEqual(14.0, t['dli'])
        self.assertEqual(16.0, t['gdd_daily'])
        self.assertEqual(date(2026, 7, 28), t['started_on'])
        self.assertEqual(1, t['stage']['total'])

        from aot.databases.models import GeoProgram
        prog = GeoProgram.query.one()
        self.assertEqual('user', prog.source)
        self.assertTrue(prog.usable_for_control())
        # 단계는 하나, 기간 없음(끝까지) — 없던 단계 구분을 지어내지 않는다.
        self.assertEqual([None], [s['days'] for s in prog.stage_list()])
        self.assertNotIn('vpd', prog.stage_list()[0].get('targets') or {})

    def test_numeric_vpd_co2_dli_resolve_as_values(self):
        fac = self._facility()
        fn = self._coord(fac, vpd_sp_type='static', target_vpd=0.9,
                         target_co2=700.0, dli_target=17.0,
                         schedule_start_time='2026-09-01')
        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        t = self._targets(fn)
        self.assertEqual(0.9, t['vpd']['value'])
        self.assertIsNone(t['vpd']['method_id'])
        self.assertEqual(700.0, t['co2']['value'])
        self.assertEqual(17.0, t['dli'])
        self.assertIsNone(t['gdd_daily'])   # 0/없음은 목표가 아니다
        self.assertIn('옮김', text)

    def test_zero_means_off_not_a_target(self):
        """옛 코드에서 0 은 그 축을 끈 것이다 — 0 을 목표로 옮기면 VPD 0 을 향해 돈다."""
        from aot.scripts import migrate_legacy_coordinator_targets as mig
        lt = mig.legacy_targets({'target_vpd': 0.0, 'target_co2': 0,
                                 'dli_target': 0.0, 'gdd_target_daily': None})
        self.assertFalse(mig.has_targets(lt))

    def test_week_offset_moves_the_start_date(self):
        from aot.scripts import migrate_legacy_coordinator_targets as mig
        lt = mig.legacy_targets({'target_vpd': 0.8,
                                 'schedule_start_time': '2026-07-28',
                                 'schedule_week_offset': 1.0})

        class _Fn(object):
            method_start_time = None
        start, notes = mig._started_on(_Fn(), lt)
        self.assertEqual(date(2026, 7, 21), start)
        self.assertTrue(any('주차 보정' in n for n in notes))


class TestLeftAlone(_Fixture, unittest.TestCase):

    def test_facility_with_a_plot_is_untouched(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoProgram
        fac = self._facility()
        db.session.add(GeoPlot(geo_id='map-legacy', kind='vegetation',
                               subject='사람이 만든 구획',
                               facility_uuid=fac.unique_id,
                               started_on=date(2026, 1, 1),
                               ended_on=date(2026, 3, 1)))   # 끝난 구획이어도
        db.session.commit()
        self._coord(fac, target_vpd=0.9)

        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        self.assertIn('이미 구획이 있음 — 건드리지 않음', text)
        self.assertEqual(1, GeoPlot.query.count())
        self.assertEqual(0, GeoProgram.query.count())

    def test_missing_facility_is_reported_not_migrated(self):
        from aot.databases.models import GeoProgram
        self._coord(None, target_vpd=0.9)
        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        self.assertIn('시설 미지정 — 수동', text)
        self.assertEqual(0, GeoProgram.query.count())

    def test_missing_method_is_not_bound_and_is_reported(self):
        fac = self._facility()
        fn = self._coord(fac, vpd_sp_type='method',
                         vpd_method_id='00000000-dead-beef-0000-000000000000',
                         target_co2=900.0)
        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        self.assertIn('VPD 곡선(00000000…)을 찾을 수 없음 — 묶지 않음', text)
        t = self._targets(fn)
        self.assertIsNone(t['vpd']['method_id'])
        self.assertIsNone(t['vpd']['value'])
        self.assertEqual(900.0, t['co2']['value'])

    def test_two_legacy_coordinators_on_one_facility_are_manual(self):
        """시설 구획은 하나만 자동 선택된다 — 어느 쪽 목표를 옮길지 고를 수 없다."""
        from aot.databases.models import GeoProgram
        fac = self._facility()
        self._coord(fac, name='A', target_vpd=0.8)
        self._coord(fac, name='B', target_vpd=1.1)
        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        self.assertEqual(2, text.count('같은 시설에 옛 목표를 가진 코디네이터가 여럿'))
        self.assertEqual(0, GeoProgram.query.count())

    def test_inactive_is_skipped_unless_asked(self):
        from aot.databases.models import GeoProgram
        fac = self._facility()
        self._coord(fac, active=False, target_vpd=0.8)
        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        self.assertIn('꺼져 있음', text)
        self.assertEqual(0, GeoProgram.query.count())
        code, text = self._run(apply=True, include_inactive=True)
        self.assertEqual(0, code, text)
        self.assertEqual(1, GeoProgram.query.count())


class TestIdempotent(_Fixture, unittest.TestCase):

    def test_second_run_does_nothing_and_legacy_keys_stay(self):
        from aot.databases.models import CustomController, GeoPlot, GeoProgram
        fac = self._facility()
        m = self._method()
        fn = self._coord(fac, vpd_sp_type='method', vpd_method_id=m.unique_id,
                         target_co2=800.0, schedule_start_time='2026-07-28')
        before = CustomController.query.filter_by(
            unique_id=fn.unique_id).first().custom_options

        self.assertEqual(0, self._run(apply=True)[0])
        code, text = self._run(apply=True)
        self.assertEqual(0, code, text)
        self.assertIn('이미 옮김', text)
        self.assertIn('옮길 것이 없습니다', text)
        self.assertEqual(1, GeoProgram.query.count())
        self.assertEqual(1, GeoPlot.query.count())
        # 옛 키는 기록이다 — 지우지도 고치지도 않는다.
        after = CustomController.query.filter_by(
            unique_id=fn.unique_id).first().custom_options
        self.assertEqual(before, after)

    def test_preview_writes_nothing(self):
        from aot.databases.models import GeoPlot, GeoProgram
        fac = self._facility()
        self._coord(fac, target_vpd=0.8)
        self.assertEqual(1, self._run()[0])
        self.assertEqual(0, GeoProgram.query.count())
        self.assertEqual(0, GeoPlot.query.count())


if __name__ == '__main__':
    unittest.main()
