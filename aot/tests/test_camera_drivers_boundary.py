# coding=utf-8
"""경계 고정: `aot.camera_drivers` 는 옛 패키지 `aot.camera.*`(26-11 에 지움)를 import 하지 않고,
DB·Flask 에도 기대지 않는다(설계 §3, §10.1 '경계'). 레거시/모던 구분은 설계 §0."""
import ast
import os

ROOT = os.path.join(os.path.dirname(__file__), '..', 'camera_drivers')


def _imports():
    for dirpath, _d, files in os.walk(ROOT):
        for fn in files:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            tree = ast.parse(open(path, encoding='utf-8').read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        yield path, a.name
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        yield path, node.module


def _hits(pred):
    return sorted({'%s -> %s' % (os.path.relpath(p, ROOT), m) for p, m in _imports() if pred(m)})


def test_does_not_import_modern_camera_package():
    bad = _hits(lambda m: m == 'aot.camera' or m.startswith('aot.camera.'))
    assert not bad, bad


def test_legacy_camera_package_is_gone():
    # 옛 `aot/camera`(미완성 모던 패키지)는 26-11 에 처분했다. 화면이 쓰던 카탈로그와
    # 플랫폼 감지는 aot/utils/camera_types.py·camera_platform.py 로 옮겼다.
    legacy = os.path.join(os.path.dirname(__file__), '..', 'camera')
    assert not os.path.exists(legacy)


def test_has_files_to_scan():
    assert sum(1 for _ in _imports()) > 10


# DB 에 닿는 파일은 이 셋뿐이다(P2). 나머지(인터페이스·VIGI 클라이언트)는 DB·Flask 를 모른다.
# P4: 이벤트 기록·디스패치(event_hub)·트리거 저장 검증·화면 상태(status)도 DB 를 만진다
_DB_FILES = ('db_store.py', 'service.py', 'runtime.py', 'event_hub.py', 'trigger_camera_event.py',
             'status.py')


def test_only_store_and_service_touch_database_and_nothing_imports_flask():
    bad = [h for h in _hits(lambda m: m == 'flask' or m.startswith('flask.')
                            or m.startswith('aot.aot_flask'))]
    assert not bad, bad
    db = [h for h in _hits(lambda m: m.startswith('aot.databases'))
          if not h.split(' -> ')[0].endswith(_DB_FILES)]
    assert not db, db
