# coding=utf-8
"""P1 회귀 테스트 — 지도 자동 생성 폐지.

docs/design/geo-data-integrity.md "지도 소유권 모델" 의 원칙 4 를 고정한다:
지도는 사용자가 명시적으로 만든다. 장치 생성·수정·복제도, 페이지 렌더도
지도를 만들지 않는다.

배경: AoT 초기에는 지도 위에 장치만 있어서 "장치가 지도를 소유한다"가
맞았다. site/facility 도입으로 위치의 정본이 지리요소로 옮겨간 뒤에도
`map_config_id` 자동 배정만 남아, 장치 67개가 전부 지도를 갖는데 그 지도의
91%는 도형이 하나도 없는 상태가 됐다(2026-08-04 운영 3서버 실측).
가장 심한 것은 **GET 요청이 지도를 만들고 커밋**하던 경로였다.

여기서는 소스 수준(AST)으로 자동 생성 경로의 부재를 고정한다. 라우트
핸들러 전체를 띄우려면 폼·데몬·번역 스택이 필요해 단위 테스트에 부적합하고,
정작 검증하고 싶은 것은 "그 코드가 존재하지 않는다"이기 때문이다.
"""
import ast
import os
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape, Input

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# 지도를 만드는 팩토리들. P1 이후 호출자가 있으면 안 된다.
FACTORIES = {'ensure_map_config', 'create_map_config', 'clone_map_config'}

# 팩토리 정의 파일 자체는 예외(내부 호출·정의가 남아 있다 — P5 에서 제거).
FACTORY_MODULE = 'aot/aot_flask/utils/utils_map_config.py'


def _iter_py():
    scan = os.path.join(ROOT, 'aot')
    for dirpath, dirnames, filenames in os.walk(scan):
        dirnames[:] = [d for d in dirnames
                       if d not in ('__pycache__', 'node_modules', 'env',
                                    'tests')]
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def _rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, '/')


class TestNoAutomaticMapCreation(unittest.TestCase):

    def test_no_caller_of_map_factories(self):
        """장치·라우트 어디에서도 지도를 자동 생성하지 않는다."""
        offenders = []
        for path in _iter_py():
            rel = _rel(path)
            if rel == FACTORY_MODULE:
                continue
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and \
                        isinstance(node.func, ast.Name) and \
                        node.func.id in FACTORIES:
                    offenders.append('%s:%d %s()' % (rel, node.lineno,
                                                     node.func.id))
        self.assertEqual(
            offenders, [],
            '지도 자동 생성이 되살아났습니다 (원칙 4). 지도는 사용자가 '
            '명시적으로 만들고, 장치는 배치될 때 지도에 속합니다:\n  ' +
            '\n  '.join(offenders))

    def test_function_list_page_does_not_commit(self):
        """GET /function 목록이 지도를 만들고 커밋하던 루프가 없어야 한다."""
        src = open(os.path.join(ROOT, 'aot/aot_flask/routes_function.py'),
                   encoding='utf-8').read()
        self.assertNotIn('map_cfg_committed', src,
                         'GET 요청이 지도를 생성·커밋하던 루프가 남아 있습니다.')

    def test_device_delete_guard_covers_all_seven_models(self):
        """_map_still_referenced 가 map_config_id 를 가진 7개 모델을 전부 본다.

        목록 누락은 이 도메인의 반복 실패 유형이다 — 과거 Function 이 빠져
        있어, Function 이 참조 중인 지도를 다른 장치 삭제가 지울 수 있었다.
        """
        from aot.aot_flask.utils import utils_map_config as mod
        src = open(mod.__file__.replace('.pyc', '.py'),
                   encoding='utf-8').read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == '_map_still_referenced')
        names = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
        for model in ('Input', 'Output', 'PID', 'Trigger', 'Conditional',
                      'CustomController', 'Function'):
            self.assertIn(model, names,
                          '%s 가 삭제 가드에서 빠졌습니다.' % model)

    def test_factories_are_marked_dead(self):
        """폐지된 팩토리는 사망 표시를 유지한다 — 무심코 되살리지 않도록."""
        src = open(os.path.join(ROOT, FACTORY_MODULE), encoding='utf-8').read()
        tree = ast.parse(src)
        for name in FACTORIES:
            fn = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == name),
                      None)
            self.assertIsNotNone(fn, '%s 가 사라졌습니다.' % name)
            doc = ast.get_docstring(fn) or ''
            self.assertIn('사망', doc,
                          '%s 의 사망 표시가 없습니다 — 되살아날 위험.' % name)



class TestUnplacedDevicesAreNowhere(unittest.TestCase):
    """원칙 3 — 배치하지 않은 장치는 어느 지도에도 없다.

    P1 이 자동 생성을 없애면서 map_config_id=NULL 이 예외에서 정상값이 됐다.
    그런데 collect_devices 는 NULL 을 "아직 배정 안 됨 → 모든 지도에 표시"로
    해석하고 있어서, **새로 만든 장치가 모든 지도에 나타나는** 회귀가 생겼다
    (2026-08-04 운영 DB 사본에서 재현). 원칙 3·4 는 함께 가야 한다.
    """

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        try:
            from flask_babel import Babel
            Babel(app)
        except Exception:
            pass
        self.app = app
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_device_without_placement_is_on_no_map(self):
        from aot.aot_flask.utils import utils_geo
        GeoMap(unique_id='m1', name='지도1', category='design').save()
        GeoMap(unique_id='m2', name='지도2', category='design').save()
        Input(name='미배치센서').save()          # map_config_id 기본 None

        for uuid in ('m1', 'm2'):
            devs = utils_geo.collect_devices(None, include_all=True,
                                             map_uuid=uuid)
            self.assertNotIn(
                '미배치센서', [d.get('name') for d in devs],
                '배치하지 않은 장치가 지도 %s 에 나타났습니다 (원칙 3).' % uuid)

    def test_placed_device_appears_only_on_its_map(self):
        from aot.aot_flask.utils import utils_geo
        GeoMap(unique_id='m1', name='지도1', category='design').save()
        GeoMap(unique_id='m2', name='지도2', category='design').save()
        dev = Input(name='배치센서')
        dev.save()
        GeoShape(unique_id='mk', geo_id='m1', type='aot_device',
                 device_id=dev.unique_id, channel_id='0',
                 feature={'type': 'Feature',
                          'geometry': {'type': 'Point',
                                       'coordinates': [1.0, 1.0]},
                          'properties': {}}).save()

        names_m1 = [d.get('name') for d in utils_geo.collect_devices(
            None, include_all=True, map_uuid='m1')]
        names_m2 = [d.get('name') for d in utils_geo.collect_devices(
            None, include_all=True, map_uuid='m2')]
        self.assertIn('배치센서', names_m1)
        self.assertNotIn('배치센서', names_m2)


class TestMapMembershipIsDerived(unittest.TestCase):
    """P2 — "장치가 어느 지도에 있는가"는 배치(마커)에서 파생한다.

    저장 컬럼 `map_config_id` 는 초기 모델("장치가 지도를 소유한다")의
    화석이다. 원칙 2 에 따라 읽기를 전부 파생으로 옮겼으므로, 컬럼 값이
    무엇이든(비어 있든, 엉뚱한 값이든) 결과가 배치를 따라야 한다.
    """

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        try:
            from flask_babel import Babel
            Babel(app)
        except Exception:
            pass
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='mA', name='지도A', category='design').save()
        GeoMap(unique_id='mB', name='지도B', category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _place(self, dev_uuid, map_uuid, shape_uid):
        GeoShape(unique_id=shape_uid, geo_id=map_uuid, type='aot_device',
                 device_id=dev_uuid, channel_id='0',
                 feature={'type': 'Feature',
                          'geometry': {'type': 'Point',
                                       'coordinates': [1.0, 1.0]},
                          'properties': {}}).save()

    def test_derived_map_ignores_stale_column(self):
        from aot.aot_flask.geo.device_membership import map_for_device
        dev = Input(name='센서', map_config_id='mB')   # 컬럼은 B 를 가리킴
        dev.save()
        self._place(dev.unique_id, 'mA', 'mk1')        # 실제 배치는 A
        self.assertEqual(map_for_device(dev.unique_id), 'mA',
                         '파생이 낡은 컬럼값을 따라갔습니다.')

    def test_unplaced_device_has_no_map(self):
        from aot.aot_flask.geo.device_membership import map_for_device
        dev = Input(name='미배치', map_config_id='mA')  # 컬럼만 있고 배치 없음
        dev.save()
        self.assertIsNone(map_for_device(dev.unique_id))

    def test_devices_on_map_matches_placement(self):
        from aot.aot_flask.geo.device_membership import devices_on_map
        a = Input(name='A장치'); a.save()
        b = Input(name='B장치'); b.save()
        self._place(a.unique_id, 'mA', 'mk-a')
        self._place(b.unique_id, 'mB', 'mk-b')
        self.assertEqual(devices_on_map('mA'), {a.unique_id})
        self.assertEqual(devices_on_map('mB'), {b.unique_id})

    def test_multi_map_placement_is_deterministic(self):
        from aot.aot_flask.geo.device_membership import (
            map_for_device, maps_for_device)
        dev = Input(name='양쪽배치'); dev.save()
        self._place(dev.unique_id, 'mA', 'mk-1')
        self._place(dev.unique_id, 'mB', 'mk-2')
        self.assertEqual(maps_for_device(dev.unique_id), ['mA', 'mB'])
        # 단일 값이 필요한 자리에서는 결정적으로 첫 배치를 고른다.
        self.assertEqual(map_for_device(dev.unique_id), 'mA')
        self.assertEqual(map_for_device(dev.unique_id), 'mA')
    def test_prefer_hint_avoids_stale_copy_map(self):
        """전환기 힌트: 여러 지도에 배치된 경우 기존 컬럼값을 존중한다.

        koat 실측에서 28건이 미사용 복사본 지도(먼저 생성됨)로 잡혔다.
        단순 "첫 배치" 규칙은 사용자가 실제로 쓰는 지도를 놓친다.
        """
        from aot.aot_flask.geo.device_membership import map_for_device
        dev = Input(name='다중배치'); dev.save()
        self._place(dev.unique_id, 'mA', 'mk-old')   # 먼저 생성된 사본
        self._place(dev.unique_id, 'mB', 'mk-real')  # 실제 쓰는 지도
        self.assertEqual(map_for_device(dev.unique_id), 'mA')          # 힌트 없음
        self.assertEqual(map_for_device(dev.unique_id, prefer='mB'), 'mB')

    def test_prefer_hint_is_ignored_when_not_placed(self):
        """정본은 배치다 — 배치에 없는 힌트는 무시한다."""
        from aot.aot_flask.geo.device_membership import map_for_device
        dev = Input(name='한곳배치'); dev.save()
        self._place(dev.unique_id, 'mA', 'mk-1')
        self.assertEqual(map_for_device(dev.unique_id, prefer='mB'), 'mA')


if __name__ == '__main__':
    unittest.main()
