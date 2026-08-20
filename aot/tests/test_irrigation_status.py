# coding=utf-8
"""마지막 관수 판정 — **무엇이 관수인지 아는 경우에만** 센다.

"오늘 물을 줬던가" 는 노지에서 가장 자주 하는 판단이다. 그런데 영역에 묶인
출력은 대부분 범용 on/off 라 그 장치가 물을 주는지 시스템은 모른다(김제 실측).
그것을 "관수" 라고 부르면 화면이 없는 사실을 지어내는 것이 된다.

그래서 근거는 사람이 종류를 밝힌 둘뿐이다 — 시설의 관수 피팅, 프로그램 단계가
선언한 관수 함수(P6). 근거가 없으면 **아무 말도 하지 않는다**.
"""
import os
import tempfile
import unittest
from unittest import mock


class _Fixture(object):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'irrig.db')
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
        from aot.databases.models import (Actions, GeoFacility, GeoPlot,
                                          GeoProgram, Output, Trigger)
        for m in (Actions, GeoFacility, GeoPlot, GeoProgram, Output, Trigger):
            m.query.delete()
        db.session.commit()

    def _facility(self, fittings):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility
        fac = GeoFacility(geo_id='m', name='온실', shape_uuid='shape-1',
                          fittings=fittings)
        db.session.add(fac)
        db.session.commit()
        return fac


class TestEvidence(_Fixture, unittest.TestCase):

    def test_typed_irrigation_fitting_counts(self):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import irrigation_status as irr
        from aot.databases.models import Output
        db.session.add(Output(unique_id='out-1', name='밸브 1',
                              output_type='virtual_on_off_single'))
        db.session.commit()
        fac = self._facility([{'id': 'f1', 'kind': 'irrigation_valve',
                               'actuator_id': 'out-1'}])
        with mock.patch('aot.utils.runtime.get_started_at', return_value=1000.0), \
             mock.patch('aot.utils.runtime.get_last_duration', return_value=600):
            out = irr.last_irrigation(fac.unique_id)
        self.assertIsNotNone(out)
        self.assertEqual('facility', out['source'])
        self.assertEqual('밸브 1', out['device'])
        self.assertEqual(600, out['duration_s'])

    def test_untyped_device_says_nothing(self):
        """범용 on/off 를 관수라고 부르지 않는다 — 그게 이 모듈의 전부다."""
        from aot.aot_flask.geo import irrigation_status as irr
        fac = self._facility([{'id': 'f1', 'kind': 'fan', 'actuator_id': 'out-9'}])
        self.assertIsNone(irr.last_irrigation(fac.unique_id))

    def test_no_evidence_is_none_not_empty_record(self):
        """"관수 기록 없음" 과 "무엇이 관수인지 모름" 은 다르다 — 뒤쪽을 앞쪽
        처럼 말하면 사용자는 장치가 안 돈 줄 안다."""
        from aot.aot_flask.geo import irrigation_status as irr
        self.assertIsNone(irr.last_irrigation(None, None))

    def test_device_known_but_never_ran(self):
        from aot.aot_flask.geo import irrigation_status as irr
        fac = self._facility([{'id': 'f1', 'kind': 'irrigation_layer',
                               'actuator_id': 'out-2'}])
        with mock.patch('aot.utils.runtime.get_started_at', return_value=None), \
             mock.patch('aot.utils.runtime.get_last_duration', return_value=None):
            out = irr.last_irrigation(fac.unique_id)
        self.assertIsNotNone(out, '장치는 있는데 기록이 없다 — 그것도 사실이다')
        self.assertIsNone(out['at'])

    def test_program_declaration_is_evidence(self):
        """P6 선언(역할 `irrigation`)은 사람이 "이건 관수다" 라고 말해 둔
        것이라 화면이 그렇게 불러도 된다.

        재설계(2026-08-20) 뒤에는 프로그램이 역할만 선언하고 **함수는 현장이**
        푼다 — 그래서 이 증거가 서려면 구획이 시설에 매여 있고 그 시설에 관수
        피팅이 있어야 한다. 계획만으로는 아무것도 켜지지 않는 것이 요지다."""
        import datetime
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import irrigation_status as irr
        from aot.databases.models import (Actions, GeoPlot, GeoProgram, Output,
                                          Trigger)
        trg = Trigger(name='야간 관수', trigger_type='trigger_run_pwm_method')
        db.session.add(trg)
        db.session.add(Output(unique_id='out-3', name='관수 밸브',
                              output_type='virtual_on_off_single'))
        db.session.commit()
        db.session.add(Actions(function_id=trg.unique_id, function_type='trigger',
                               action_type='output', do_unique_id='out-3,0'))
        # 현장: 이 시설의 관수 피팅이 out-3 을 켠다.
        fac = self._facility([{'id': 'f1', 'kind': 'irrigation_valve',
                               'actuator_id': 'out-3'}])
        # 계획: 이 프로그램은 관수를 쓴다 — 어느 함수인지는 적지 않는다.
        prog = GeoProgram(name='P', kind='vegetation', subject='상추',
                          resource_defs=[{'role': 'irrigation',
                                          'default': True}],
                          stages=[{'key': 'a', 'name': '생육', 'days': 30}])
        db.session.add(prog)
        db.session.commit()
        plot = GeoPlot(geo_id='m', kind='vegetation', subject='상추',
                       source_kind='facility', program_uuid=prog.unique_id,
                       facility_uuid=fac.unique_id,
                       started_on=datetime.date.today() - datetime.timedelta(days=2))
        db.session.add(plot)
        db.session.commit()

        with mock.patch('aot.utils.runtime.get_started_at', return_value=2000.0), \
             mock.patch('aot.utils.runtime.get_last_duration', return_value=300):
            out = irr.last_irrigation(None, plot)
        self.assertIsNotNone(out)
        self.assertEqual('program', out['source'])
        self.assertEqual('관수 밸브', out['device'])

    def test_declaration_without_actions_finds_nothing(self):
        """선언은 있는데 그 함수가 아무 출력도 안 켜면 셀 것이 없다 —
        지어내지 않는다(실측: 관찰용 트리거가 그 상태였다)."""
        import datetime
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import irrigation_status as irr
        from aot.databases.models import GeoPlot, GeoProgram, Trigger
        trg = Trigger(name='빈 트리거', trigger_type='trigger_run_pwm_method')
        db.session.add(trg)
        db.session.commit()
        # 관수 피팅은 있는데 그 출력을 켜는 함수가 아무 액션도 갖지 않는다.
        fac = self._facility([{'id': 'f1', 'kind': 'irrigation_valve',
                               'actuator_id': 'out-empty'}])
        prog = GeoProgram(name='P', kind='vegetation', subject='상추',
                          resource_defs=[{'role': 'irrigation',
                                          'default': True}],
                          stages=[{'key': 'a', 'name': '생육', 'days': 30}])
        db.session.add(prog)
        db.session.commit()
        plot = GeoPlot(geo_id='m', kind='vegetation', subject='상추',
                       source_kind='facility', program_uuid=prog.unique_id,
                       facility_uuid=fac.unique_id,
                       started_on=datetime.date.today() - datetime.timedelta(days=2))
        db.session.add(plot)
        db.session.commit()
        self.assertIsNone(irr.last_irrigation(None, plot))


if __name__ == '__main__':
    unittest.main()


class TestSharedByFacilityAndField(unittest.TestCase):
    """시설·노지가 **같은 판정·같은 렌더러**를 쓴다.

    같은 질문("오늘 물을 줬던가")에 계층마다 다른 문장으로 답하면 사용자는
    그것이 다른 이야기인 줄 안다.
    """

    def _read(self, path):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, '..', path), encoding='utf-8') as fh:
            return fh.read()

    def test_both_modals_send_it(self):
        for path, needle in (
                ('aot_flask/routes_geo_iec.py', "'irrigation':  irrigation_status"),
                ('aot_flask/routes_geo.py', "'irrigation': _irr")):
            self.assertIn(needle, self._read(path), path)

    def test_both_modals_use_the_same_renderer(self):
        js = self._read('aot_flask/static/js/widgets/AoT_map/'
                        'aot-map-widget-vector.js')
        self.assertEqual(2, js.count('buildIrrigationHtml('),
                         '시설·노지 중 한쪽만 그리고 있다')

    def test_renderer_says_nothing_without_evidence(self):
        js = self._read('aot_flask/static/js/widgets/AoT_map/aot-map-popup.js')
        body = js.split('function buildIrrigationHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("if (!irr) return '';", body,
                      '근거가 없을 때 "기록 없음" 이라 적으면 장치가 안 돈 줄 안다')
