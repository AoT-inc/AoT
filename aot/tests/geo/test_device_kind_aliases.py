# coding=utf-8
"""L1c — 장치 종류 별칭 계층·마커 상수·위치 Mixin 동등성.

각 호출 자리의 dict 가 전환 전과 키·값이 모두 같음을 리터럴로 고정한다.
"""
import importlib.util
import os

import pytest

from aot.space.device_binding import device_kind_models
from aot.space.device_kind import (
    CANONICAL_KINDS, canonical_kind, models_for)
from aot.databases.geo_marker_kinds import MARKER_TYPE, MARKER_TYPES
from aot.databases.models import (
    Conditional, CustomController, Function, Input, Output, PID, Trigger)


def test_canonical_matches_device_kind_models():
    assert CANONICAL_KINDS == tuple(k for k, _ in device_kind_models())


def test_canonical_kind_global_and_geo():
    assert canonical_kind('custom_controller') == 'device'
    assert canonical_kind('generic_function') == 'function'
    assert canonical_kind('function') == 'function'          # 정본
    assert canonical_kind('function', vocabulary='geo') == 'device'
    assert canonical_kind('custom', vocabulary='geo') == 'device'
    assert canonical_kind('generic_function', vocabulary='geo') == 'function'
    assert canonical_kind('INPUT') == 'input'
    for bad in ('custom', 'camera', '', None):
        with pytest.raises(ValueError):
            canonical_kind(bad)
    with pytest.raises(ValueError):
        canonical_kind('input', vocabulary='nope')


def test_api_geo_and_overlays_maps():
    # api/geo.py:714 (전환 전 리터럴)
    before = {
        'input': Input, 'output': Output, 'pid': PID, 'trigger': Trigger,
        'conditional': Conditional, 'device': CustomController,
        'function': CustomController, 'custom': CustomController,
        'generic_function': Function}
    after = models_for(('input', 'output', 'pid', 'trigger', 'conditional',
                        'device', 'function', 'custom', 'generic_function'),
                       vocabulary='geo')
    assert after == before and list(after) == list(before)
    # geo_overlays.py:1404
    before2 = {k: v for k, v in before.items() if k != 'device'}
    after2 = models_for(('input', 'output', 'pid', 'trigger', 'conditional',
                         'function', 'custom', 'generic_function'),
                        vocabulary='geo')
    assert after2 == before2 and list(after2) == list(before2)


def test_ai_action_maps():
    assert models_for(('input', 'output', 'function', 'custom_controller')) == {
        'input': Input, 'output': Output, 'function': Function,
        'custom_controller': CustomController}
    assert models_for(('input', 'output', 'function', 'custom_controller',
                       'pid')) == {
        'input': Input, 'output': Output, 'function': Function,
        'custom_controller': CustomController, 'pid': PID}


def test_tab_service_maps():
    names = ('input', 'output', 'trigger', 'conditional', 'pid',
             'custom_controller', 'function')
    assert models_for(names) == {
        'input': Input, 'output': Output, 'trigger': Trigger,
        'conditional': Conditional, 'pid': PID,
        'custom_controller': CustomController, 'function': Function}
    assert list(models_for(names)) == list(names)
    assert models_for(('input', 'output')) == {'input': Input, 'output': Output}


def test_device_tool_map():
    after = models_for(('input', 'output', 'device', 'function'),
                       vocabulary='geo')
    assert after == {'input': Input, 'output': Output,
                     'device': CustomController, 'function': CustomController}


def test_member_models():
    assert models_for(('input', 'output', 'device')) == {
        'input': Input, 'output': Output, 'device': CustomController}


def test_marker_constants():
    assert MARKER_TYPE == 'aot_device'
    assert MARKER_TYPES == ('aot_device', 'device')
    from aot.aot_flask.geo import device_placement
    from aot.databases.models import geo_marker_position
    assert device_placement.MARKER_TYPE == MARKER_TYPE
    assert geo_marker_position.MARKER_TYPES == MARKER_TYPES


def test_device_location_columns_removed():
    """장치 위치 정본 하나 L4: 장치 행은 더 이상 위치 컬럼을 들지 않는다 —
    위치·시간대·좌표는 전부 배치(geo_binding+도형)에서 해석한다."""
    for model in (Input, Output, CustomController, Function, PID, Trigger,
                  Conditional):
        cols = model.__table__.columns
        # L4 S3c(p7_08): 장치 좌표 컬럼은 사라졌다 — 좌표는 배치에서 푼다.
        for name in ('latitude', 'longitude'):
            assert name not in cols, (model, name)
        # L4 S3b-tz(p7_07): 장치 tz 캐시 컬럼은 사라졌다 — tz 는 배치에서 푼다.
        for name in ('timezone', 'tz_source'):
            assert name not in cols, (model, name)
        # L3(p7_04): 죽은 위치 컬럼 세 개는 모델에서 사라졌다.
        for name in ('location_source', 'map_config_id',
                     'location_updated_utc'):
            assert name not in cols, (model, name)


def _checker():
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts',
                        'check_device_kind_literals.py')
    spec = importlib.util.spec_from_file_location('_dk_check', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_checker_flags_and_passes_repo():
    chk = _checker()
    assert chk.check_source("m = {'input': Input, 'output': Output}\n", 'x.py')
    assert chk.check_source("t = 'aot_device'\n", 'x.py')
    assert not chk.check_source('"""aot_device"""\nx = {"a": 1}\n', 'x.py')
    assert chk.main() == 0


# ---------------------------------------------------------------------------
# 호출 자리의 실제 표현식을 소스에서 꺼내 전환 전 리터럴과 비교한다.
# ---------------------------------------------------------------------------
import ast  # noqa: E402

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def _namespace():
    from aot.databases.models import Camera, GeoProgram
    return {'models_for': models_for, 'Camera': Camera,
            'GeoProgram': GeoProgram, 'Input': Input, 'Output': Output,
            'CustomController': CustomController, 'Function': Function,
            'PID': PID}


def _site_values(relpath, target):
    """`relpath` 에서 이름이 target 인 대입의 우변(또는 target='models_for' 면
    모든 models_for 호출)을 평가해 리스트로."""
    with open(os.path.join(_ROOT, relpath), encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    ns = _namespace()
    exprs = []
    for node in ast.walk(tree):
        if target == 'models_for':
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'models_for'):
                exprs.append(node)
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if target in names:
                exprs.append(node.value)
    return [eval(compile(ast.Expression(e), relpath, 'eval'), ns)
            for e in sorted(exprs, key=lambda n: n.lineno)]


def test_site_member_models():
    (got,) = _site_values('aot/utils/device_blueprint.py',
                          '_MEMBER_MODELS_CACHE')[-1:]
    assert got == {'input': Input, 'output': Output,
                   'device': CustomController}


def test_site_device_connection():
    (got,) = _site_values('aot/aot_flask/utils/utils_device_connection.py',
                          'models_for')
    assert got == {'input': Input, 'output': Output,
                   'device': CustomController}


def test_site_tab_service():
    from aot.databases.models import Conditional, GeoProgram, Trigger
    one, = _site_values('aot/services/tab_service.py', 'models_for')[:1]
    assert one == {'input': Input, 'output': Output}
    (table,) = _site_values('aot/services/tab_service.py', 'TABLE_MAP')
    (model,) = _site_values('aot/services/tab_service.py', 'MODEL_MAP')
    base = {'input': Input, 'output': Output, 'trigger': Trigger,
            'conditional': Conditional, 'pid': PID,
            'custom_controller': CustomController, 'function': Function}
    assert table == dict(base, program=GeoProgram)
    assert model == dict(base, program=GeoProgram)
    assert list(table) == list(base) + ['program']


def test_site_device_tool():
    from aot.databases.models import Camera
    (got,) = _site_values('aot/tools/data_tools/device.py', 'models')
    assert got == {'input': Input, 'output': Output,
                   'device': CustomController, 'function': CustomController,
                   'camera': Camera}
    assert list(got) == ['input', 'output', 'device', 'function', 'camera']


def test_site_ai_action_service():
    first, second = _site_values('aot/ai/services/ai_action_service.py',
                                 'model_map')
    assert first == {'input': Input, 'output': Output, 'function': Function,
                     'custom_controller': CustomController}
    assert second == {'input': Input, 'output': Output, 'function': Function,
                      'custom_controller': CustomController, 'pid': PID}


def test_site_api_geo_and_overlays_real_expressions():
    (a,) = _site_values('aot/aot_flask/api/geo.py', 'model_map')
    (b,) = _site_values('aot/aot_flask/geo/geo_overlays.py', 'model_map')
    assert a['function'] is CustomController and a['generic_function'] is Function
    assert 'device' in a and 'device' not in b
    assert b['function'] is CustomController and b['custom'] is CustomController


def test_device_tables_match_pre_l1c_ddl():
    """Mixin 전환이 스키마를 바꾸지 않았다 — 전환 전 모델의 DDL(golden)로 만든
    DB 를 현재 메타데이터와 alembic compare_metadata 로 비교하면 차이가 없다."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine
    from aot.aot_flask.extensions import db

    tables = {'input', 'output', 'custom_controller', 'function',
              'conditional', 'trigger', 'pid'}
    with open(os.path.join(os.path.dirname(__file__),
                           'golden_device_tables.sql'), encoding='utf-8') as fh:
        ddl = fh.read()
    engine = create_engine('sqlite://')
    raw = engine.raw_connection()
    try:
        raw.executescript(ddl)
        # FK 참조 대상은 반영(reflect)만 되면 된다 — 빈 뼈대 테이블을 둔다.
        for name in sorted({fk.column.table.name
                            for t in db.metadata.sorted_tables
                            if t.name in tables
                            for fk in t.foreign_keys} - tables):
            raw.execute('CREATE TABLE IF NOT EXISTS "%s" (id INTEGER PRIMARY KEY, '
                        'unique_id VARCHAR(36))' % name)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={
                'compare_type': True, 'compare_server_default': True,
                'include_object': lambda obj, name, type_, reflected, other:
                    (name in tables) if type_ == 'table' else True})
            diff = compare_metadata(ctx, db.metadata)
    finally:
        raw.close()
    # 골든에 없는 나머지 테이블은 'add_table' 로 보이므로 7개 테이블 한정 diff 만 본다.
    diff = [d for d in diff
            if not (isinstance(d, tuple) and d[0] == 'add_table'
                    and d[1].name not in tables)]
    # L4 가 지운 컬럼(S3b-tz p7_07: timezone/tz_source, S3c p7_08: latitude/longitude)
    # 외에는 차이가 없어야 한다.
    _gone = ('timezone', 'tz_source', 'latitude', 'longitude')
    dropped = {(d[2], d[3].name) for d in diff
               if isinstance(d, tuple) and d[0] == 'remove_column'
               and d[3].name in _gone}
    assert dropped == {(t, c) for t in tables for c in _gone}
    diff = [d for d in diff
            if not (isinstance(d, tuple) and d[0] == 'remove_column'
                    and d[3].name in _gone)]
    assert diff == []
