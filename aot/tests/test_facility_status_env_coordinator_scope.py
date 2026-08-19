# coding=utf-8
"""회귀 테스트 — `/api/aot/facility/<uuid>/status` 가 남의 코디네이터를 빌려오지
않는다.

실측(2026-08-19, 로컬 김제 지도 '육묘장' a3d725da-665f-496f-9146-d06135178064):
코디네이터가 없는 이 시설에 `/status` 를 호출하면, 시스템 전체에서 아무
`is_activated=True` env_coordinator 나 하나 골라 그 이름/상태를 그대로
돌려주고 있었다. 같은 요청의 `/env_summary` (facility-scoped 인
`_find_facility_env_coordinator` 사용)는 정직하게 `function: None` 을
돌려줬다 — 한 시설, 두 기준.

`routes_geo_iec.py` 는 DB/앱 컨텍스트 없이도 import 가능하다
(test_geo_tile_cache.py, test_geo_plot.py 참조). 여기서는 그 성질을 이용해
① 헬퍼 두 개(`_function_belongs_to_facility`, `_find_facility_env_coordinator`)
의 동작을 DB 없이 고정하고, ② `/status` 핸들러 소스가 그 헬퍼들을 실제로
쓰는지(=시스템 전체 스캔으로 되돌아가지 않았는지) 소스 검사로 고정한다.

실제 HTTP round-trip 검증은 로컬 docker(aot_local-aot-app-1)에서 수행:
- function_uuid 없이 코디네이터 없는 시설 조회 -> function_name=None, level=idle
- 다른 시설의 function_uuid 를 넘기면 400 거부
- 그 function_uuid 가 실제로 속한 시설로 넘기면 정상 통과
"""
import json
import os
import unittest

os.environ.setdefault('ALEMBIC_RUNNING', '1')

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models.controller import CustomController
from aot.aot_flask.routes_geo_iec import (
    _function_belongs_to_facility,
    _find_facility_env_coordinator,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTES_GEO_IEC_PATH = os.path.join(
    ROOT, 'aot', 'aot_flask', 'routes_geo_iec.py')


class _FakeFunction(object):
    """CustomController 를 흉내내는 최소 더미 — `_function_belongs_to_facility`
    와 `_find_facility_env_coordinator` 가 실제로 읽는 속성만 갖는다."""

    def __init__(self, unique_id, facility_uuid=None, is_activated=True,
                 name='Env Coordinator', custom_options=None):
        self.unique_id = unique_id
        self.is_activated = is_activated
        self.name = name
        if custom_options is not None:
            self.custom_options = custom_options
        else:
            opts = {}
            if facility_uuid is not None:
                opts['geo_facility_id_device_id'] = facility_uuid
            self.custom_options = json.dumps(opts)


class TestFunctionBelongsToFacility(unittest.TestCase):

    def test_matching_facility_is_true(self):
        fn = _FakeFunction('f1', facility_uuid='fac-A')
        self.assertTrue(_function_belongs_to_facility(fn, 'fac-A'))

    def test_other_facility_is_false(self):
        """다른 시설 소속 function 을 '내 것'으로 오인하면 안 된다."""
        fn = _FakeFunction('f1', facility_uuid='fac-A')
        self.assertFalse(_function_belongs_to_facility(fn, 'fac-B'))

    def test_unlinked_function_is_false(self):
        fn = _FakeFunction('f1', facility_uuid=None)
        self.assertFalse(_function_belongs_to_facility(fn, 'fac-A'))

    def test_legacy_geo_facility_id_key_still_matches(self):
        fn = _FakeFunction('f1', custom_options=json.dumps(
            {'geo_facility_id': 'fac-LEGACY'}))
        self.assertTrue(_function_belongs_to_facility(fn, 'fac-LEGACY'))

    def test_malformed_custom_options_is_false_not_exception(self):
        fn = _FakeFunction('f1', custom_options='not json')
        self.assertFalse(_function_belongs_to_facility(fn, 'fac-A'))


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _make_env_coordinator(unique_id, facility_uuid=None, is_activated=False,
                           name='Env Coordinator'):
    opts = {}
    if facility_uuid is not None:
        opts['geo_facility_id_device_id'] = facility_uuid
    fn = CustomController(unique_id=unique_id, device='env_coordinator',
                           name=name, is_activated=is_activated,
                           custom_options=json.dumps(opts))
    fn.save()
    return fn


class TestFindFacilityEnvCoordinatorScoping(unittest.TestCase):
    """핵심 회귀: 시설에 코디네이터가 없으면, 다른 시설 것을 빌려오지 않는다.

    실제 sqlite(in-memory)에 진짜 CustomController 행을 심어 쿼리를 그대로
    태운다 — mock 으로 필터 로직을 흉내내는 대신, `/status` 가 실제로 거치는
    `CustomController.query.filter_by(device='env_coordinator').all()` 경로
    자체를 검증한다.
    """

    def setUp(self):
        self.app = _make_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_no_coordinator_for_this_facility_returns_none_even_if_others_exist(self):
        _make_env_coordinator('other', facility_uuid='fac-OTHER', is_activated=True)
        result = _find_facility_env_coordinator('fac-NONE')
        self.assertIsNone(
            result,
            '시스템의 다른 시설 코디네이터를 이 시설 것으로 골라왔습니다 — '
            '실측된 버그(a3d725da 육묘장)의 재발입니다.')

    def test_prefers_activated_among_this_facilitys_own_functions(self):
        _make_env_coordinator('i1', facility_uuid='fac-A', is_activated=False)
        active = _make_env_coordinator('a1', facility_uuid='fac-A', is_activated=True)
        result = _find_facility_env_coordinator('fac-A')
        self.assertEqual(result.unique_id, active.unique_id)

    def test_falls_back_to_first_own_function_if_none_activated(self):
        only = _make_env_coordinator('o1', facility_uuid='fac-A', is_activated=False)
        result = _find_facility_env_coordinator('fac-A')
        self.assertEqual(result.unique_id, only.unique_id)

    def test_explicit_function_uuid_from_other_facility_fails_ownership_check(self):
        """CLAUDE.md 요구사항 3 — 명시 function_uuid 도 소유 시설을 검증한다."""
        other = _make_env_coordinator('other', facility_uuid='fac-OTHER',
                                       is_activated=True)
        self.assertFalse(_function_belongs_to_facility(other, 'fac-MINE'))
        self.assertTrue(_function_belongs_to_facility(other, 'fac-OTHER'))


class TestStatusRouteUsesFacilityScopedLookup(unittest.TestCase):
    """소스 가드 — `/status` 핸들러가 다시 시스템 전체 스캔으로 퇴행하지
    않았는지 고정한다 (DB/앱 컨텍스트 없이 문자열 검사만 한다)."""

    def setUp(self):
        with open(ROUTES_GEO_IEC_PATH, encoding='utf-8') as f:
            src = f.read()
        start = src.index('def api_facility_iec_status(')
        end = src.index('\n@blueprint.route', start)
        self.handler_src = src[start:end]

    def test_handler_delegates_to_facility_scoped_helper(self):
        self.assertIn(
            '_find_facility_env_coordinator(facility_uuid)', self.handler_src,
            '/status 가 facility-scoped 조회(_find_facility_env_coordinator)를 '
            '쓰지 않습니다 — env_summary 와 판정 기준이 다시 갈라졌을 수 있습니다.')

    def test_handler_no_longer_scans_whole_system_for_any_activated_coordinator(self):
        self.assertNotIn(
            "device='env_coordinator', is_activated=True).first()",
            self.handler_src,
            '/status 가 시설 구분 없이 시스템 전체에서 활성 코디네이터를 '
            '골라오는 옛 경로가 되살아났습니다.')

    def test_handler_verifies_explicit_function_uuid_ownership(self):
        self.assertIn(
            '_function_belongs_to_facility(', self.handler_src,
            '명시적으로 넘어온 function_uuid 가 이 시설 소유인지 검증하지 '
            '않습니다 — 다른 시설의 function_uuid 를 그대로 신뢰하게 됩니다.')


if __name__ == '__main__':
    unittest.main()
