# coding=utf-8
"""원장이 끊은 연결이 시설 레거시 컬럼에 남은 경우 — 탐지와 경고 (2026-09-25).

리졸버는 이제 그런 슬롯을 빈 자리로 읽는다(`test_device_binding_resolver`).
여기서는 **그 사실이 사람에게 보이는가** 를 고정한다. 이 부류는 19일간
아무 데서도 보고되지 않았다 — 원장은 정답을 갖고 있었고, 읽는 쪽은 그것을
보지 않았고, 검사기는 지도 도형만 봤다.

실측(로컬): イチゴ 의 측창 슬롯이 9/6 에 끊긴 `측창: 좌/우`(육묘장3 소유)를
레거시 값으로 되돌려 받아, 쿠마모토 코디네이터가 육묘장3 의 측창을 함께
제어했다. 두 코디네이터가 같은 장치를 반대로 밀어 10분 주기로
0→12→6→0 이 반복됐는데, 양쪽 결정 로그에는 각자 정상 근거(`주작용`·
`무구배`)만 남았다.

세 겹을 고정한다:
  1. 무결성 검사 `stale-legacy-ref` 가 그 자리를 찾는다.
  2. 코디네이터가 다른 시설 코디네이터와 같은 장치를 잡으면 error 로 알린다.
  3. 건강 점검이 같은 사실을 severe 로 보고한다.
"""
import ast
import json
import os
import types
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoBinding, GeoFacility, Output
from aot.utils.time_utils import utc_now

# ⚠ **앱 컨텍스트 밖에서 먼저 import 한다.** `aot.aot_flask.geo` 패키지는
#   처음 import 될 때 번역 문자열을 평가하는 모듈을 끌어오는데, 이 테스트의
#   sqlite 앱에는 babel 이 없다. 컨텍스트 안에서 처음 부르면 KeyError('babel')
#   로 죽는다 — 검사 대상과 무관한 실패라 원인을 헷갈리게 만든다.
from aot.aot_flask.geo import device_binding as _device_binding  # noqa: F401
from aot.aot_flask.geo import facility_integration as _facility_integration  # noqa: F401
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin \
    import ProfileLoaderMixin

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
_INTEGRITY = os.path.join(_ROOT, 'aot', 'scripts', 'check_geo_integrity.py')
_HEALTH = os.path.join(_ROOT, 'aot', 'scripts', 'check_env_coordinator_health.py')

FAC_A = 'fac-kumamoto'
FAC_B = 'fac-nursery3'
FIT = 'env_side_vent_outer_u0_left_single'
DEV = 'dev-side-left'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _load(path, *names, extra=None):
    """스크립트에서 이름 붙은 함수만 떼어 깨끗한 네임스페이스에서 돌린다.

    두 스크립트 모두 import 하는 순간 Flask 앱 전체가 딸려 온다 — 이 저장소의
    다른 검사 테스트들과 같은 이유로 AST 로 떼어 쓴다.
    """
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    ns = {'json': json}
    ns.update(extra or {})
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module([node], []), path, 'exec'), ns)
    missing = [n for n in names if n not in ns]
    if missing:
        raise AssertionError('떼어 내지 못했습니다: %s' % missing)
    return ns


class _DB(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        Output(unique_id=DEV, name='측창: 좌').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _facility(self, uuid, device=DEV):
        GeoFacility(unique_id=uuid, shape_uuid='s-' + uuid, geo_id='map-1',
                    name=uuid, fittings=[{'id': FIT, 'kind': 'side_window',
                                          'actuator_id': device}]).save()

    def _bind(self, fac, ended=False, device=DEV):
        GeoBinding(spatial_kind='fitting', spatial_id='%s:%s' % (fac, FIT),
                   role='actuator', device_kind='output', device_id=device,
                   channel_id='0', valid_from=utc_now(),
                   valid_to=utc_now() if ended else None,
                   ended_reason='unbound' if ended else None).save()


# ─────────────────────────────────────────────────────────────────────────────
# 1. 무결성 검사
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrityFindsStaleLegacyRefs(_DB):

    def _run(self):
        ns = _load(_INTEGRITY, '_stale_legacy_refs', '_json_items',
                   extra={'GeoBinding': GeoBinding, 'GeoFacility': GeoFacility})
        return ns['_stale_legacy_refs']({DEV})

    def test_끝난_연결이_레거시에_남으면_찾는다(self):
        """사고 재현 — 쿠마모토 측창 슬롯."""
        self._facility(FAC_A)
        self._bind(FAC_A, ended=True)
        found = self._run()
        self.assertEqual(1, len(found))
        self.assertEqual(FAC_A, found[0]['facility_uuid'])
        self.assertEqual(DEV, found[0]['legacy_device'])

    def test_원장에_오른_적_없는_슬롯은_보고하지_않는다(self):
        """백필 전 데이터 — 그건 binding-drift/폴백의 영역이다."""
        self._facility(FAC_A)
        self.assertEqual([], self._run())

    def test_다시_연결된_슬롯은_보고하지_않는다(self):
        self._facility(FAC_A)
        self._bind(FAC_A, ended=True)
        self._bind(FAC_A)
        self.assertEqual([], self._run())

    def test_죽은_참조는_dangling_fitting_몫이다(self):
        """장치가 아예 없으면 이 검사가 아니라 dangling-fitting 이 잡는다."""
        self._facility(FAC_A, device='dev-gone')
        self._bind(FAC_A, ended=True, device='dev-gone')
        self.assertEqual([], self._run())

    def test_severe_로_분류되고_목록에_출력된다(self):
        """HEADINGS 에 없으면 집계는 되는데 화면에 안 나온다(2026-08-08 겪음)."""
        with open(_INTEGRITY, encoding='utf-8') as fh:
            src = fh.read()
        tree = ast.parse(src)
        heads, severe = None, None
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == 'HEADINGS':
                    heads = {k.value for k in node.value.keys}
                elif node.targets[0].id == 'SEVERE':
                    severe = {e.value for e in node.value.elts}
        self.assertIn('stale-legacy-ref', heads)
        self.assertIn('stale-legacy-ref', severe)
        self.assertIn("findings['stale-legacy-ref']", src)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 코디네이터 경고
# ─────────────────────────────────────────────────────────────────────────────

class TestCoordinatorWarnsOnSharedActuator(_DB):
    """두 코디네이터가 같은 장치를 잡으면 한쪽 로그에라도 남아야 한다."""

    MOD = 'aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin'

    def _fake(self):
        return types.SimpleNamespace(
            unique_id='coord-me', _by_id={DEV: object()},
            logger=mock.MagicMock())

    def _rows(self, active=True, facility=FAC_B):
        return [types.SimpleNamespace(
            unique_id='coord-other', name='환경제어: 육묘장',
            device='env_coordinator', is_activated=active,
            custom_options=json.dumps({'geo_facility_id': facility}))]

    def _integ(self, *_a, **_k):
        return {'actuators_resolved': [
            {'output_uuid': DEV, 'kind': 'opening'}]}, None

    def _call(self, fake, rows):
        with mock.patch(self.MOD + '.db_retrieve_table_daemon', return_value=rows), \
                mock.patch('aot.aot_flask.geo.facility_integration'
                           '.get_facility_integration', side_effect=self._integ):
            ProfileLoaderMixin._warn_shared_actuators(fake, FAC_A)

    def test_다른_시설_코디네이터와_같은_장치면_error_로_알린다(self):
        fake = self._fake()
        self._call(fake, self._rows())
        fake.logger.error.assert_called_once()
        msg = fake.logger.error.call_args[0][0] % fake.logger.error.call_args[0][1:]
        self.assertIn('측창: 좌', msg)
        self.assertIn('환경제어: 육묘장', msg)

    def test_바뀔_때만_찍는다(self):
        """프로필 재적재는 10분마다 돈다 — 매번 찍으면 하루 144줄이다."""
        fake = self._fake()
        self._call(fake, self._rows())
        self._call(fake, self._rows())
        self.assertEqual(1, fake.logger.error.call_count)

    def test_풀리면_한_번_알린다(self):
        fake = self._fake()
        self._call(fake, self._rows())
        self._call(fake, [])
        self.assertEqual(2, fake.logger.error.call_count)
        self.assertIn('풀렸', fake.logger.error.call_args[0][0])

    def test_꺼진_코디네이터는_보지_않는다(self):
        fake = self._fake()
        self._call(fake, self._rows(active=False))
        fake.logger.error.assert_not_called()

    def test_같은_시설의_코디네이터는_보지_않는다(self):
        """구역(bay) 분할이 정상 구성이다 — `_bays_claimed_by_siblings` 담당."""
        fake = self._fake()
        self._call(fake, self._rows(facility=FAC_A))
        fake.logger.error.assert_not_called()

    def test_빼지_않는다(self):
        """어느 쪽이 주인인지 시스템은 모른다 — 알리기만 한다."""
        fake = self._fake()
        self._call(fake, self._rows())
        self.assertIn(DEV, fake._by_id)

    def test_적재_끝에서_부른다(self):
        import inspect
        src = inspect.getsource(ProfileLoaderMixin._reload_profiles)
        self.assertIn('self._warn_shared_actuators(facility_uuid)', src)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 건강 점검
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthCheckReportsSharedActuator(unittest.TestCase):

    def _run(self, others):
        fake_cc = types.SimpleNamespace(query=types.SimpleNamespace(
            filter_by=lambda **kw: types.SimpleNamespace(all=lambda: others)))
        ns = _load(_HEALTH, '_check_shared_actuators',
                   extra={'CustomController': fake_cc})

        def integ(uuid, *_a, **_k):
            return {'actuators_resolved': [
                {'output_uuid': DEV, 'output_name': '측창: 좌', 'kind': 'opening'}]}, None

        with mock.patch('aot.aot_flask.geo.facility_integration'
                        '.get_facility_integration', side_effect=integ):
            return ns['_check_shared_actuators'](
                FAC_A, types.SimpleNamespace(unique_id='coord-me'))

    def _other(self, active=True, facility=FAC_B):
        return types.SimpleNamespace(
            unique_id='coord-other', name='환경제어: 육묘장', is_activated=active,
            custom_options=json.dumps({'geo_facility_id': facility}))

    def test_공유면_severe_로_보고한다(self):
        found = self._run([self._other()])
        self.assertEqual(1, len(found))
        self.assertEqual('severe', found[0][0])
        self.assertIn('측창: 좌', found[0][1])

    def test_공유가_없으면_조용하다(self):
        self.assertEqual([], self._run([self._other(active=False)]))
        self.assertEqual([], self._run([self._other(facility=FAC_A)]))

    def test_설정_점검에_연결돼_있다(self):
        with open(_HEALTH, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('findings.extend(_check_shared_actuators(facility_uuid, row))', src)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 레거시 컬럼을 직접 읽는 자리가 다시 생기지 않는다
# ─────────────────────────────────────────────────────────────────────────────

# 레거시 컬럼을 **읽어야만 하는** 자리. 여기 없는 곳이 `facility.fittings` /
# `facility.actuators` 를 직접 읽으면 원장이 끊은 연결을 되살린다.
_RAW_READ_ALLOWED = {
    # 정본 출구 — 여기서 원장을 입힌다.
    'aot/aot_flask/geo/device_binding.py',
    # 저장 경로(쓰기 전 원본을 읽는다)와 `_to_dict` 의 원본 적재.
    'aot/aot_flask/geo/facility_io.py',
    # 레거시 → 원장 백필. 원본을 읽는 것이 목적이다.
    'aot/scripts/backfill_geo_binding.py',
}


def test_레거시_시설_참조를_직접_읽지_않는다():
    """`facility.fittings` / `.actuators` 를 직접 읽으면 **두 번째 판정자**가 된다.

    2026-09-25 에 그런 자리가 8곳 있었다 — 제어 경로(코디네이터)는 정본
    출구를 지났지만, 시설 위젯·관수 상태·일지 지도·AI 요약·시운전·시설 일괄
    명령·안전 상태 전환은 레거시 목록을 그대로 읽었다. 그중 셋은 **장치를
    실제로 움직인다** — 한 시설의 안전 상태 명령이 원장이 다른 시설로 넘긴
    창까지 닫았을 것이다. 규칙을 두 벌 두면 갈라지고, 갈라지면 느슨한 쪽이
    실질 동작이 된다.

    판정은 변수 이름에 'fac' 이 든 객체의 속성 읽기만 본다 — 무관한
    `group.actuators` 같은 것을 잡지 않기 위해서다.
    """
    import pathlib
    root = pathlib.Path(_ROOT)
    bad = []
    for path in (root / 'aot').rglob('*.py'):
        rel = str(path.relative_to(root))
        if '/tests/' in rel or 'alembic' in rel or rel in _RAW_READ_ALLOWED:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute)
                    and node.attr in ('fittings', 'actuators')
                    and isinstance(node.ctx, ast.Load)):
                continue
            base = node.value
            name = (base.id if isinstance(base, ast.Name)
                    else base.attr if isinstance(base, ast.Attribute) else '')
            if 'fac' in name.lower():
                bad.append('%s:%d %s.%s' % (rel, node.lineno, name, node.attr))
    assert not bad, (
        '레거시 시설 참조를 직접 읽는다 — `device_binding.resolved_refs()` '
        '또는 `FacilityManager._to_dict()` 를 거칠 것:\n  ' + '\n  '.join(bad))


class TestResolvedRefsKeepsLegacyShape(_DB):

    def test_옛_사전_형식_액추에이터를_버리지_않는다(self):
        """`{slot_key: uuid}` 형식을 리스트로 펴면 값이 전부 사라진다."""
        fac = GeoFacility(unique_id='fac-dict', shape_uuid='s-dict', geo_id='map-1',
                          name='옛형식', fittings=[],
                          actuators={'side_vent_motor': DEV})
        fac.save()
        _, acts = _device_binding.resolved_refs(fac)
        self.assertEqual({'side_vent_motor': DEV}, acts)


if __name__ == '__main__':
    unittest.main()
