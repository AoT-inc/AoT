# coding=utf-8
"""시설 위젯 ALL STOP(`/api/aot/facility/<uuid>/estop`)은 환경 제어도 멈춘다.

예전 이 API 는 출력만 안전 상태로 보냈다. 시설을 제어하는 env_coordinator 는
그대로 돌아서, 다음 주기에 방금 멈춘 창·난방기를 다시 움직였다 — "멈췄다"는
화면과 실제가 달랐다(2026-09-27).

이제 붙어 켜진 코디네이터가 있으면 함수의 'Emergency Stop' 명령과 **같은
진입점**(`cmd_emergency_stop`: 안전값 + 60초 보류)을 부르고, 없거나 꺼져 있으면
예전처럼 출력만 안전 상태로 보낸다.

데몬은 가짜지만 코디네이터 쪽은 **실제 `cmd_emergency_stop`** 을 돌린다 —
API 가 그 반환 문장으로 정지를 확인하므로, 문장 형식이 바뀌면 여기서 깨진다.
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock
from unittest.mock import MagicMock

from aot.functions.custom_functions.env_coordinator import CustomModule

FAC = 'fac-estop-1'


def _coordinator(actuator_ids):
    """__init__ 없이 긴급 정지에 필요한 상태만 갖춘 실제 코디네이터."""
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.timer_loop = 0.0
    c._emergency_hold_until = 0.0
    c.update_period = 60.0
    c._profiles = [MagicMock(actuator_id=a, safe_default=0.0) for a in actuator_ids]
    c._channel_map = {}
    c._adapter_by_id = {}
    c.control = MagicMock()
    c.control.output_off.return_value = (0, 'ok')
    return c


class _FakeDaemon(object):
    """DaemonControl 대역. 함수 호출은 aot_daemon.module_function 과 같은 모양으로
    답한다 — 돌고 있지 않은 함수에도 status 0 에 안내 문장만 준다."""

    running = {}          # unique_id → 코디네이터 인스턴스
    calls = []

    def module_function(self, controller_type, unique_id, button_id, args_dict,
                        thread=True, return_from_function=False, timeout=None):
        self.calls.append(('module_function', unique_id, button_id))
        inst = self.running.get(unique_id)
        if inst is None:
            return 0, ("Attempting to call {}() in inactive Function Controller "
                       "with ID {}.".format(button_id, unique_id))
        return 0, getattr(inst, button_id)(args_dict)

    def output_off(self, uuid, output_channel=0):
        self.calls.append(('output_off', uuid))
        return 0, 'ok'

    def output_on(self, uuid, output_channel=0, amount=0):
        self.calls.append(('output_on', uuid))
        return 0, 'ok'


class EstopStopsCoordinatorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'estop.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls.app = app
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
        from aot.databases.models import GeoFacility
        from aot.databases.models.controller import CustomController
        GeoFacility.query.delete()
        CustomController.query.delete()
        db.session.add(GeoFacility(
            unique_id=FAC, geo_id='m', name='온실', shape_uuid='shape-1',
            actuators={'heater_1': 'out-heater', 'side_window_1': 'out-win'}))
        db.session.commit()
        _FakeDaemon.running = {}
        _FakeDaemon.calls = []

    def _function(self, uid, activated=True, facility=FAC):
        from aot.aot_flask.extensions import db
        from aot.databases.models.controller import CustomController
        fn = CustomController(unique_id=uid, name='환경 ' + uid,
                              device='env_coordinator', is_activated=activated,
                              custom_options=json.dumps(
                                  {'geo_facility_id_device_id': facility}))
        db.session.add(fn)
        db.session.commit()
        return fn

    def _estop(self):
        from aot.aot_flask import routes_geo_iec
        with mock.patch('aot.aot_client.DaemonControl', _FakeDaemon), \
                mock.patch.object(routes_geo_iec.utils_general,
                                  'user_has_permission', return_value=True), \
                self.app.test_request_context(
                    '/api/aot/facility/%s/estop' % FAC, method='POST',
                    json={'confirm': 'STOP'}):
            resp = routes_geo_iec.api_facility_estop.__wrapped__(FAC)
        if isinstance(resp, tuple):
            resp = resp[0]
        return resp.get_json()

    def _output_calls(self):
        return [c for c in _FakeDaemon.calls if c[0] in ('output_off', 'output_on')]

    # ── 코디네이터가 있으면 그 긴급 정지 진입점 ────────────────────────────────

    def test_estop_puts_the_linked_coordinator_into_emergency_hold(self):
        self._function('fn-a')
        coord = _coordinator(['out-heater', 'out-win'])
        _FakeDaemon.running['fn-a'] = coord

        before = time.time()
        d = self._estop()

        self.assertTrue(d['ok'], d)
        self.assertEqual(d['path'], 'coordinator')
        self.assertGreaterEqual(coord._emergency_hold_until, before + 59)
        self.assertEqual(coord.timer_loop, coord._emergency_hold_until)
        self.assertEqual(coord.control.output_off.call_count, 2)
        self.assertEqual(d['applied'], 2)
        self.assertEqual([(f['unique_id'], f['stopped']) for f in d['functions']],
                         [('fn-a', True)])
        # 정지 로직을 따로 돌리지 않는다 — 출력은 코디네이터가 보냈다.
        self.assertEqual(self._output_calls(), [])

    def test_every_coordinator_of_the_facility_is_stopped(self):
        self._function('fn-a')
        self._function('fn-b')
        self._function('fn-other', facility='fac-somewhere-else')
        a, b, other = (_coordinator(['out-heater']), _coordinator(['out-win']),
                       _coordinator(['out-x']))
        _FakeDaemon.running.update({'fn-a': a, 'fn-b': b, 'fn-other': other})

        d = self._estop()

        self.assertTrue(d['ok'], d)
        self.assertGreater(a._emergency_hold_until, 0)
        self.assertGreater(b._emergency_hold_until, 0)
        self.assertEqual(other._emergency_hold_until, 0.0, '남의 시설 코디네이터를 멈췄다')
        self.assertEqual(sorted(f['unique_id'] for f in d['functions']), ['fn-a', 'fn-b'])

    # ── 없거나 꺼져 있으면 출력만 ──────────────────────────────────────────────

    def test_without_a_coordinator_only_outputs_are_sent_to_safe_state(self):
        d = self._estop()

        self.assertTrue(d['ok'], d)
        self.assertEqual(d['path'], 'outputs')
        self.assertEqual(d['functions'], [])
        self.assertEqual(d['applied'], 2)
        self.assertEqual(sorted(u for _, u in self._output_calls()),
                         ['out-heater', 'out-win'])
        self.assertFalse(any(c[0] == 'module_function' for c in _FakeDaemon.calls))

    def test_deactivated_coordinator_is_not_called_and_outputs_are_sent(self):
        self._function('fn-off', activated=False)
        d = self._estop()

        self.assertTrue(d['ok'], d)
        self.assertEqual(d['path'], 'outputs')
        self.assertFalse(any(c[0] == 'module_function' for c in _FakeDaemon.calls))
        self.assertEqual(len(self._output_calls()), 2)

    def test_coordinator_not_running_in_daemon_falls_back_and_is_not_ok(self):
        """DB 는 켜짐인데 데몬에 없음 — 데몬은 status 0 으로 답하지만 정지가 아니다."""
        self._function('fn-ghost')
        d = self._estop()

        self.assertEqual(len(self._output_calls()), 2, '출력 안전 상태로 넘어가지 않았다')
        self.assertFalse(d['ok'])
        self.assertEqual(d['functions'][0]['stopped'], False)


def test_reply_parser_rejects_the_daemon_inactive_reply():
    from aot.aot_flask.routes_geo_iec import _parse_coordinator_estop_reply as p
    assert p((0, 'Attempting to call cmd_emergency_stop() in inactive Function '
                 'Controller with ID x.')) is None
    assert p((1, 'boom')) is None
    assert p(None) is None
    assert p((0, _coordinator(['a', 'b', 'c']).cmd_emergency_stop({}))) == (3, 0)
