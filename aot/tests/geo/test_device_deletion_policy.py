# coding=utf-8
"""Phase C — 장치 삭제 정책의 통일과 그 정책 자체.

두 가지를 고정한다.

**① 정책**: 장치를 지워도 구역 폴리곤·시설 슬롯은 남는다(B4). 도형은 자산
(측량·작도 결과)이고 장치는 소모품이라, 같이 지우면 자산이 날아간다.
예외는 위치 마커 하나뿐 — 장치를 놓으려고 찍은 점이라 가리킬 대상이 없으면
의미가 없다.

**② 배선**: 장치 삭제 진입점 **17곳**(utils_* 7 + tab_service 7 + 진단 일괄 3)이
전부 `end_all_for_device()` 를 지나간다. 예전에는 그중 4곳만 도형을 정리했고
나머지 13곳으로 지운 장치의 도형은 아무 에러 없이 남았다. 그래서 배선을
소스 수준(AST)으로 고정한다 — 한 곳만 빠져도 그 경로는 조용히 옛날처럼
행동하고, 그 침묵이 이 도메인의 고질병이다.

②를 소스 검사로 하는 이유: 삭제 함수 하나를 실제로 돌리려면 데몬·폼·번역
스택이 전부 필요해 단위 테스트에 맞지 않는데, 정작 검증하고 싶은 것은
"그 호출이 존재하는가"뿐이다(`test_geo_map_ownership.py` 와 같은 방식).
"""
import ast
import os
import time
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding as B
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import GeoBinding, GeoMap, GeoShape, Output

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# 장치 삭제 진입점 — (파일, 함수명). 설계 문서의 17곳과 같은 목록이어야 한다.
DELETE_ENTRY_POINTS = [
    ('aot/aot_flask/utils/utils_input.py', 'input_del'),
    ('aot/aot_flask/utils/utils_output.py', 'output_del'),
    ('aot/aot_flask/utils/utils_function.py', 'function_del'),
    ('aot/aot_flask/utils/utils_controller.py', 'controller_del'),
    ('aot/aot_flask/utils/utils_conditional.py', 'conditional_del'),
    ('aot/aot_flask/utils/utils_pid.py', 'pid_del'),
    ('aot/aot_flask/utils/utils_trigger.py', 'trigger_del'),
    ('aot/services/tab_service.py', '_delete_input_entry'),
    ('aot/services/tab_service.py', '_delete_output_entry'),
    ('aot/services/tab_service.py', '_delete_trigger_entry'),
    ('aot/services/tab_service.py', '_delete_conditional_entry'),
    ('aot/services/tab_service.py', '_delete_pid_entry'),
    ('aot/services/tab_service.py', '_delete_custom_controller_entry'),
    ('aot/services/tab_service.py', '_delete_function_entry'),
    ('aot/aot_flask/utils/utils_settings.py', 'settings_diagnostic_delete_inputs'),
    ('aot/aot_flask/utils/utils_settings.py', 'settings_diagnostic_delete_outputs'),
    ('aot/aot_flask/utils/utils_settings.py', 'settings_diagnostic_delete_functions'),
]

MAP = 'map-del-1'
DEV = 'dev-del-0001'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _calls_in(path, func_name):
    """해당 함수 본문에서 호출되는 이름 집합(중첩 함수 포함)."""
    tree = ast.parse(open(os.path.join(ROOT, path), encoding='utf-8').read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        found.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        found.add(fn.attr)
    return found


class TestAllDeletePathsGoThroughTheGateway(unittest.TestCase):

    def test_every_entry_point_calls_end_all_for_device(self):
        """17곳 전부. 하나만 빠져도 그 경로는 조용히 고아를 만든다."""
        missing = []
        for path, func in DELETE_ENTRY_POINTS:
            calls = _calls_in(path, func)
            if not calls:
                missing.append('%s:%s (함수를 찾지 못함)' % (path, func))
            elif 'end_all_for_device' not in calls:
                missing.append('%s:%s' % (path, func))
        self.assertEqual(missing, [],
                         '이 삭제 경로가 게이트웨이를 거치지 않는다: %s' % missing)

    def test_entry_point_list_is_the_documented_seventeen(self):
        """목록 자체가 17이어야 한다 — 새 삭제 경로를 만들면 여기도 늘린다."""
        self.assertEqual(len(DELETE_ENTRY_POINTS), 17)

    def test_no_direct_shape_delete_by_device_id_outside_geo(self):
        """`GeoShape...filter(device_id==...).delete()` 직삭제가 없어야 한다.

        이것이 Phase C 이전의 4곳이며, 구역 폴리곤까지 함께 지우던 코드다.
        `check_geo_writes.py` 가 소유권을 보지만 그쪽은 geo 패키지 밖만
        본다 — 이 테스트는 패턴 자체가 되살아나는 것을 본다.
        """
        offenders = []
        for path, _func in DELETE_ENTRY_POINTS:
            text = open(os.path.join(ROOT, path), encoding='utf-8').read()
            if 'GeoShape.query.filter' in text:
                offenders.append(path)
        self.assertEqual(sorted(set(offenders)), [],
                         '장치 삭제 경로가 도형을 직접 지운다: %s' % offenders)


# 사용자 코드 파일을 만드는 종류만 대상이다 — PID·Trigger·시퀀스는 파이썬
# 코드를 저장하지 않으므로 지울 파일도 없다.
USER_CODE_DELETE_PATHS = [
    ('aot/aot_flask/utils/utils_input.py', 'input_del'),
    ('aot/aot_flask/utils/utils_output.py', 'output_del'),
    ('aot/aot_flask/utils/utils_conditional.py', 'conditional_del'),
    ('aot/aot_flask/utils/utils_controller.py', 'controller_del'),
    ('aot/aot_flask/utils/utils_settings.py', 'settings_diagnostic_delete_inputs'),
    ('aot/aot_flask/utils/utils_settings.py', 'settings_diagnostic_delete_outputs'),
    # 탭 삭제 연쇄. 처음 이 가드를 쓸 때 여기를 빠뜨렸는데, 로컬에 고아
    # conditional 파일 5개가 남아 있는 것을 보고 되짚어 찾았다 — 목록이
    # 불완전하면 가드가 통과하면서도 같은 구멍이 남는다.
    ('aot/services/tab_service.py', '_delete_input_entry'),
    ('aot/services/tab_service.py', '_delete_output_entry'),
    ('aot/services/tab_service.py', '_delete_conditional_entry'),
    ('aot/services/tab_service.py', '_delete_custom_controller_entry'),
]


class TestUserCodeFilesAreDeletedWithTheDevice(unittest.TestCase):
    """장치를 지우면 그 장치의 사용자 코드 파일도 사라져야 한다.

    2026-08-14 운영에서 발견: 출력 삭제가 `user_python_code/output_*.py` 를
    하나도 지우지 않아 고아 파일 3개가 남아 있었다. 그 파일에는 실제 장치
    uuid 와 output_on/output_off 호출이 그대로 들어 있었다. DB 행이 없어
    실행되지는 않지만(데몬은 Output 행을 보고 실행한다), 지워진 설비의 제어
    코드가 디스크에 남는 것 자체가 위생 문제다.

    당시 정리하던 곳은 6경로 중 둘뿐이었고 그마저 서로 다른 파일에 인라인으로
    복제돼 있었다 — `end_all_for_device` 와 똑같은 모양의 배선 누락이라,
    똑같이 소스 수준에서 고정한다.
    """

    def test_every_path_calls_the_shared_helper(self):
        missing = []
        for path, func in USER_CODE_DELETE_PATHS:
            calls = _calls_in(path, func)
            if not calls:
                missing.append('%s:%s (함수를 찾지 못함)' % (path, func))
            elif 'delete_python_file' not in calls:
                missing.append('%s:%s' % (path, func))
        self.assertEqual(missing, [],
                         '이 삭제 경로가 사용자 코드 파일을 남긴다: %s' % missing)

    def test_no_inline_os_remove_of_user_code(self):
        """이름 규약을 인라인으로 다시 쓰지 말 것 — 한 벌만 고치면 갈린다."""
        offenders = []
        for path, _func in USER_CODE_DELETE_PATHS:
            text = open(os.path.join(ROOT, path), encoding='utf-8').read()
            if 'PATH_PYTHON_CODE_USER' in text and 'os.remove' in text:
                offenders.append(path)
        self.assertEqual(sorted(set(offenders)), [],
                         '사용자 코드 파일을 직접 지운다(헬퍼를 쓸 것): %s' % offenders)

    def test_helper_covers_every_kind_that_writes_code(self):
        """파일을 만드는 종류는 전부 지우는 표에도 있어야 한다."""
        from aot.utils.code_verification import USER_CODE_FILENAME
        self.assertEqual(sorted(USER_CODE_FILENAME),
                         ['conditional', 'input', 'output'])
        # 생성 쪽 이름과 실제로 일치하는지 — 출력은 'output_<id>.py' 다
        # (aot/outputs/on_off_python.py · pwm_python.py 의 file_run).
        self.assertEqual(USER_CODE_FILENAME['output'], 'output_{}.py')
        self.assertEqual(USER_CODE_FILENAME['input'],
                         'input_python_code_{}.py')
        self.assertEqual(USER_CODE_FILENAME['conditional'],
                         'conditional_{}.py')


class TestStartupPurgesOrphanUserCode(unittest.TestCase):
    """기동 자가정리 — 이미 생긴 고아는 배포본이 스스로 걷어낸다.

    삭제 경로를 고쳐도 **이미 남은 고아는 사라지지 않는다.** 그것을 운영자가
    서버에 들어가 지우게 하거나 사용자에게 안내하는 것은 해법이 아니다 —
    코드가 만든 쓰레기는 코드가 치운다.

    여기서 지키는 것은 "지운다" 보다 **"살아 있는 것을 안 지운다"** 다.
    오판으로 멀쩡한 장치의 코드를 날리면 되돌릴 방법이 없다.
    """

    def setUp(self):
        import tempfile
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, age_sec):
        path = os.path.join(self.dir, name)
        with open(path, 'w') as fh:
            fh.write('# t\n')
        stamp = time.time() - age_sec
        os.utime(path, (stamp, stamp))
        return path

    def _purge(self):
        # 모듈이 import 시점에 상수를 바인딩하므로 config 가 아니라 그 모듈의
        # 이름을 바꿔야 한다.
        from aot.utils import code_verification as cv
        original = cv.PATH_PYTHON_CODE_USER
        cv.PATH_PYTHON_CODE_USER = self.dir
        try:
            cv.purge_orphan_user_code()
        finally:
            cv.PATH_PYTHON_CODE_USER = original

    def test_live_device_file_is_never_removed(self):
        out = Output(unique_id='live-0001')
        db.session.add(out)
        db.session.commit()
        keep = self._write('output_live-0001.py', 3600)
        self._purge()
        self.assertTrue(os.path.exists(keep),
                        '살아 있는 장치의 코드를 지웠다')

    def test_orphan_is_removed(self):
        db.session.add(Output(unique_id='live-0001'))
        db.session.commit()
        gone = self._write('output_dead-0002.py', 3600)
        self._purge()
        self.assertFalse(os.path.exists(gone))

    def test_freshly_written_file_is_left_alone(self):
        """저장 도중 기동이 겹치는 경우를 배제한다."""
        db.session.add(Output(unique_id='live-0001'))
        db.session.commit()
        fresh = self._write('output_dead-0003.py', 5)
        self._purge()
        self.assertTrue(os.path.exists(fresh))

    def test_unrelated_files_are_left_alone(self):
        db.session.add(Output(unique_id='live-0001'))
        db.session.commit()
        other = self._write('README.txt', 3600)
        init = self._write('__init__.py', 3600)
        self._purge()
        self.assertTrue(os.path.exists(other))
        self.assertTrue(os.path.exists(init))

    def test_empty_database_deletes_nothing(self):
        """장치가 하나도 없으면 판단 근거가 없다 — 전량 삭제로 가면 안 된다."""
        survivor = self._write('output_dead-0004.py', 3600)
        self._purge()
        self.assertTrue(os.path.exists(survivor),
                        '장치 목록이 비었는데 파일을 지웠다')


class TestDeletionKeepsAssets(unittest.TestCase):
    """정책 — 도형은 남고 마커만 사라진다."""

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        B.reset_fallback_log()
        GeoMap(unique_id=MAP, name='삭제 정책 검증', category='design').save()
        Output(unique_id=DEV, name='밸브').save()

        self.marker = GeoShape(geo_id=MAP, type='aot_device', device_id=DEV,
                               channel_id='0', feature={})
        self.marker.save()
        self.area = GeoShape(geo_id=MAP, type='device', device_id=DEV,
                             channel_id='0', feature={})
        self.area.save()

        B.bind('shape', self.marker.unique_id, 'marker', 'output', DEV,
               commit=True)
        B.bind('shape', self.area.unique_id, 'area', 'output', DEV,
               commit=True)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_area_polygon_survives_as_an_unassigned_slot(self):
        """구역 폴리곤은 자산이다 — 장치를 지워도 남고, 미배정 자리가 된다."""
        area_uid = self.area.unique_id
        B.end_all_for_device(DEV, commit=True)

        self.assertIsNotNone(
            GeoShape.query.filter_by(unique_id=area_uid).first(),
            '구역 폴리곤이 장치와 함께 지워졌다 — 측량 결과를 잃는 회귀')
        self.assertIsNone(B.current_one('shape', area_uid, role='area'))
        slots = [s['spatial_id'] for s in B.unbound_slots(map_uuid=MAP)]
        self.assertIn(area_uid, slots, '남은 도형이 미배정 자리로 안 보인다')

    def test_position_marker_is_removed(self):
        """마커는 유일하게 자산 가치가 없는 도형이다."""
        marker_uid = self.marker.unique_id
        B.end_all_for_device(DEV, commit=True)
        self.assertIsNone(
            GeoShape.query.filter_by(unique_id=marker_uid).first())

    def test_bindings_end_rather_than_vanish(self):
        B.end_all_for_device(DEV, commit=True)
        rows = GeoBinding.query.filter_by(device_id=DEV).all()
        self.assertEqual(len(rows), 2, '바인딩 행이 지워졌다 — 이력이 사라진다')
        self.assertTrue(all(r.valid_to is not None for r in rows))
        self.assertEqual({r.ended_reason for r in rows}, {'device_deleted'})

    def test_other_devices_are_untouched(self):
        other = 'dev-other-0002'
        Output(unique_id=other, name='다른 밸브').save()
        shape = GeoShape(geo_id=MAP, type='device', device_id=other,
                         channel_id='0', feature={})
        shape.save()
        B.bind('shape', shape.unique_id, 'area', 'output', other, commit=True)

        B.end_all_for_device(DEV, commit=True)
        self.assertIsNotNone(B.current_one('shape', shape.unique_id,
                                           role='area'))

    def test_legacy_marker_without_binding_is_still_removed(self):
        """바인딩 없이 컬럼만 가진 마커도 정리한다.

        백필이 죽은 참조에 바인딩을 만들지 않았고 쓰기 전환도 진행 중이라
        이런 마커가 남아 있다. 바인딩만 보면 영원히 정리되지 않는다.
        """
        legacy = GeoShape(geo_id=MAP, type='aot_device', device_id=DEV,
                          channel_id='7', feature={})
        legacy.save()
        uid = legacy.unique_id
        B.end_all_for_device(DEV, commit=True)
        self.assertIsNone(GeoShape.query.filter_by(unique_id=uid).first())

    def test_unknown_device_is_a_no_op(self):
        self.assertEqual(B.end_all_for_device('dev-nope'), 0)
        self.assertEqual(B.end_all_for_device(None), 0)


if __name__ == '__main__':
    unittest.main()
