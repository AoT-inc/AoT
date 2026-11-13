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
from aot.tests.geo._legacy_marker import bound_shape
from aot.databases.models import GeoMap, GeoShape, Input

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# 지도를 만드는 팩토리들. P1 이후 호출자가 있으면 안 된다.
FACTORIES = {'ensure_map_config', 'create_map_config', 'clone_map_config'}

# 팩토리 모듈은 L3 에서 삭제했다 — 존재하지 않아야 한다.
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

    def test_factory_module_is_gone(self):
        """L3: 지도 팩토리(`ensure/create/clone_map_config`)와 장치 쪽 삭제 가드는
        호출자 0 이라 모듈째 지웠다. 되살리지 않는다 — 지도는 사용자가 만들고
        삭제는 geo/design 의 `delete_design_map` 하나다."""
        self.assertFalse(os.path.exists(os.path.join(ROOT, FACTORY_MODULE)),
                         '지도 팩토리 모듈이 되살아났습니다.')
        names = set()
        for path in _iter_py():
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except Exception:
                continue
            names |= {n.name for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)}
        self.assertEqual(names & (FACTORIES | {'_map_still_referenced',
                                               'delete_map_config'}), set())


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
        bound_shape(unique_id='mk', geo_id='m1', type='aot_device',
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
        bound_shape(unique_id=shape_uid, geo_id=map_uuid, type='aot_device',
                 device_id=dev_uuid, channel_id='0',
                 feature={'type': 'Feature',
                          'geometry': {'type': 'Point',
                                       'coordinates': [1.0, 1.0]},
                          'properties': {}}).save()

    def test_derived_map_follows_placement(self):
        from aot.space.device_membership import map_for_device
        dev = Input(name='센서')
        dev.save()
        self._place(dev.unique_id, 'mA', 'mk1')        # 실제 배치는 A
        self.assertEqual(map_for_device(dev.unique_id), 'mA')

    def test_map_config_id_column_is_gone(self):
        # L3(p7_04): 지도 소속을 담던 장치 컬럼은 사라졌다 — 되살리지 말 것.
        self.assertNotIn('map_config_id', Input.__table__.columns)

    def test_unplaced_device_has_no_map(self):
        from aot.space.device_membership import map_for_device
        dev = Input(name='미배치')                     # 배치 없음
        dev.save()
        self.assertIsNone(map_for_device(dev.unique_id))

    def test_devices_on_map_matches_placement(self):
        from aot.space.device_membership import devices_on_map
        a = Input(name='A장치'); a.save()
        b = Input(name='B장치'); b.save()
        self._place(a.unique_id, 'mA', 'mk-a')
        self._place(b.unique_id, 'mB', 'mk-b')
        self.assertEqual(devices_on_map('mA'), {a.unique_id})
        self.assertEqual(devices_on_map('mB'), {b.unique_id})

    def test_multi_map_placement_is_deterministic(self):
        from aot.space.device_membership import (
            map_for_device, maps_for_device)
        dev = Input(name='양쪽배치'); dev.save()
        self._place(dev.unique_id, 'mA', 'mk-1')
        self._place(dev.unique_id, 'mB', 'mk-2')
        self.assertEqual(maps_for_device(dev.unique_id), ['mA', 'mB'])
        # 단일 값이 필요한 자리에서는 결정적으로 첫 배치를 고른다.
        self.assertEqual(map_for_device(dev.unique_id), 'mA')
        self.assertEqual(map_for_device(dev.unique_id), 'mA')

    def test_prefer_argument_is_gone(self):
        """L3: 컬럼 힌트(`prefer`)는 제거했다 — 대표 지도는 첫 배치 하나."""
        import inspect
        from aot.space.device_membership import map_for_device
        self.assertEqual(list(inspect.signature(map_for_device).parameters),
                         ['device_unique_id'])


class TestParcelImportDoesNotDuplicate(unittest.TestCase):
    """같은 필지를 두 번 가져와도 도형이 두 벌이 되지 않는다.

    예전에는 서버가 무조건 새로 만들었다. 클라이언트가 저장 중 버튼을
    잠그지만 그건 **한 번의 저장 안에서 더블클릭만** 막는다 — 모달을 닫았다
    다시 열어 같은 주소를 가져오면 대지와 라벨이 한 벌 더 생겼다. 실제로
    81초 간격으로 만들어진 짝을 2026-08-08 에 지웠다.

    판정 기준은 `check_geo_integrity` 의 duplicate 와 같은 규칙이어야 한다
    (종류 + 좌표 반올림 기하). 다르면 만들 때는 통과하고 점검에서만 걸리는
    상태가 된다.
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        try:                       # 라우트 모듈이 gettext 를 쓴다
            from flask_babel import Babel
            Babel(self.app)
        except Exception:
            pass
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='m1', name='필지 검증', category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    GEOM = {'type': 'Polygon',
            'coordinates': [[[127.5, 36.1], [127.5001, 36.1],
                             [127.5001, 36.1001], [127.5, 36.1]]]}

    def _site(self, geom):
        GeoShape(geo_id='m1', type='site',
                 feature={'type': 'Feature', 'geometry': geom,
                          'properties': {'name': '기존 필지'}}).save()

    def test_same_parcel_is_detected(self):
        from aot.aot_flask.routes_geo_map import _find_duplicate_site
        self._site(self.GEOM)
        self.assertIsNotNone(_find_duplicate_site('m1', self.GEOM))

    def test_different_parcel_is_not_blocked(self):
        """과차단 방지 — 다른 필지는 정상적으로 들어와야 한다."""
        from aot.aot_flask.routes_geo_map import _find_duplicate_site
        self._site(self.GEOM)
        other = {'type': 'Polygon',
                 'coordinates': [[[127.6, 36.2], [127.6001, 36.2],
                                  [127.6001, 36.2001], [127.6, 36.2]]]}
        self.assertIsNone(_find_duplicate_site('m1', other))

    def test_other_map_is_not_blocked(self):
        """지도가 다르면 같은 필지를 가져올 수 있다 — 지도마다 독립이다."""
        from aot.aot_flask.routes_geo_map import _find_duplicate_site
        GeoMap(unique_id='m2', name='다른 지도', category='design').save()
        self._site(self.GEOM)
        self.assertIsNone(_find_duplicate_site('m2', self.GEOM))

    def test_non_site_shapes_do_not_block(self):
        """대지만 본다 — 같은 자리에 그린 구역이 필지 가져오기를 막으면 안 된다."""
        from aot.aot_flask.routes_geo_map import _find_duplicate_site
        GeoShape(geo_id='m1', type='zone',
                 feature={'type': 'Feature', 'geometry': self.GEOM,
                          'properties': {}}).save()
        self.assertIsNone(_find_duplicate_site('m1', self.GEOM))

    def test_the_endpoint_actually_calls_the_guard(self):
        """가드 함수가 있어도 **부르지 않으면** 아무것도 막지 못한다.

        음성 대조에서 실제로 드러났다: 호출부 한 줄을 지웠는데 함수 단위
        테스트는 전부 통과했다. 함수의 정확성과 그 함수가 실제로 쓰이는지는
        다른 문제다.
        """
        tree = ast.parse(open(os.path.join(ROOT, 'aot/aot_flask/routes_geo_map.py'),
                              encoding='utf-8').read())
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name == 'api_geo_parcel_save_as_site':
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                        called.add(sub.func.id)
        self.assertIn('_find_duplicate_site', called,
                      '필지 저장 경로가 중복 가드를 부르지 않는다')

    def test_geometry_key_matches_the_integrity_checker(self):
        """두 규칙이 갈리면 만들 때는 통과하고 점검에서만 걸린다."""
        import importlib.util
        from aot.aot_flask.routes_geo_map import _parcel_geom_key
        path = os.path.join(ROOT, 'aot/scripts/check_geo_integrity.py')
        spec = importlib.util.spec_from_file_location('_chk', path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            self.skipTest('검사기 모듈을 단독 로드할 수 없음')
        shape = GeoShape(geo_id='m1', type='site',
                         feature={'type': 'Feature', 'geometry': self.GEOM,
                                  'properties': {}})
        self.assertEqual(_parcel_geom_key(self.GEOM),
                         mod._geom_key(shape, 1e-6))


class TestAllMapsAreEqual(unittest.TestCase):
    """P3 원칙 1 — 지도는 공간이지 장치의 소유물이 아니다.

    `category`/`is_device_owned` 로 "사용자 지도"를 가리던 판정이 4갈래로
    갈려 있었다(엄격 design / design-or-NULL / is_device_owned / 둘 다).
    같은 지도가 어떤 화면에는 뜨고 어떤 화면에는 안 뜨는 원인이었다.
    이제 구분할 종류가 없으므로 판정도 없다.
    """

    def test_no_code_branches_on_map_category_or_ownership(self):
        import re
        offenders = []
        # GeoMap 에 한정한다 — 다른 모델의 category(AIDomainGlossary,
        # Notes 등)는 이 원칙과 무관하다.
        pat = re.compile(
            r"GeoMap\.category|GeoMap\.query\.filter_by\(category=|"
            r"is_device_owned")
        for path in _iter_py():
            rel = _rel(path)
            if rel == FACTORY_MODULE:      # 사망 함수 내부는 P5 에서 제거
                continue
            try:
                src = open(path, encoding='utf-8').read()
            except Exception:
                continue
            for i, line in enumerate(src.splitlines(), 1):
                st = line.strip()
                if st.startswith('#') or st.startswith('"'):
                    continue
                if 'db.Column' in line:      # 컬럼 정의는 P5 까지 남는다
                    continue
                if pat.search(line):
                    offenders.append('%s:%d %s' % (rel, i, st[:70]))
        self.assertEqual(
            offenders, [],
            '지도 종류로 분기하는 코드가 남아 있습니다 (원칙 1):\n  ' +
            '\n  '.join(offenders))

    def test_device_deletion_does_not_delete_maps(self):
        """장치를 지워도 지도는 남는다 — delete_map_config 호출자 0."""
        import ast as _ast
        offenders = []
        for path in _iter_py():
            rel = _rel(path)
            if rel == FACTORY_MODULE:
                continue
            try:
                tree = _ast.parse(open(path, encoding='utf-8').read())
            except Exception:
                continue
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Call) and \
                        isinstance(node.func, _ast.Name) and \
                        node.func.id == 'delete_map_config':
                    offenders.append('%s:%d' % (rel, node.lineno))
        self.assertEqual(
            offenders, [],
            '장치 삭제 경로가 지도를 지웁니다 (원칙 1). 임실군 62도형이 '
            '이렇게 사라졌습니다:\n  ' + '\n  '.join(offenders))


if __name__ == '__main__':
    unittest.main()
