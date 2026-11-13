# coding=utf-8
"""공간 도메인 패키지(`aot/space/`, 아키텍처 3단계)의 두 약속.

1. 옮긴 모듈의 정본은 `aot.space.<이름>` 하나다. 옛 경로 `aot.aot_flask.geo.<이름>`
   별칭은 아키텍처 4d 에서 지웠다 — 되살아나면 사본이 생겨 한쪽을 patch 한 시험이
   다른 쪽을 놓칠 수 있다(9월 P1-1b 에서 겪음).
2. `aot.space` 를 쓰는 쪽(데몬·트윈)은 웹 계층을 띄우지 않는다. 이 시험은 새
   프로세스에서 import 해서 실제로 올라온 모듈을 본다 — 소스만 세는 가드
   (`space-no-web`)와 다른 방법으로 같은 것을 확인한다.
"""
import importlib
import subprocess
import sys

import pytest

MOVED = ['facility_calc', 'facility_geo_helpers', 'facility_wind', 'facility_bays',
         'facility_layout', 'irrigation_topology', 'irrigation_nozzles']

# 아키텍처 4c 에서 옮긴 것 — DB 세션(Flask-SQLAlchemy)을 쓰므로 `flask` 는 올라온다.
# 웹 패키지·로그인·AI·도구층은 여전히 올라오면 안 된다.
MOVED_4C = ['device_membership', 'device_binding', 'plot_context', 'facility_sensors',
            'facility_integration', 'device_location', 'forecast_series', 'plot_geometry',
            'device_kind', 'containment_cache', 'shape_index', 'facility_io',
            'plot_accumulation', 'plot_sources', 'program_io', 'weather_state']


@pytest.mark.parametrize('name', MOVED + MOVED_4C)
def test_old_geo_path_is_gone(name):
    importlib.import_module(f'aot.space.{name}')
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f'aot.aot_flask.geo.{name}')


def test_routes_still_expose_the_coordinator_link_helpers():
    from aot.aot_flask import routes_geo_iec
    from aot.space import coordinator_link
    for fn in ('_find_facility_env_coordinator', '_function_belongs_to_facility',
               '_function_facility_uuid'):
        assert getattr(routes_geo_iec, fn) is getattr(coordinator_link, fn)


def test_importing_space_does_not_load_the_web_layer():
    mods = ', '.join(f'aot.space.{m}' for m in MOVED + [
        'coordinator_link', 'measurement_names', 'site_parent'])
    code = (f'import sys, {mods}\n'
            "bad = sorted(m for m in sys.modules if m == 'flask' or "
            "m.startswith(('flask', 'aot.aot_flask', 'aot.ai', 'aot.tools')))\n"
            'print(",".join(bad))')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == '', f'aot.space 가 웹 계층을 올렸다: {out}'


@pytest.mark.parametrize('name', MOVED_4C)
def test_db_bound_space_modules_do_not_load_the_web_package(name):
    """모듈마다 새 프로세스에서 따로 띄운다 — 순서가 바뀌면 숨은 순환 import 가
    드러나고, 다른 모듈이 먼저 웹 계층을 올려 이 모듈의 잘못을 가리지 않게 한다."""
    # `flask_login` 은 보지 않는다 — 모델(`User` 의 `UserMixin`)이 올리는 것이라 모델을
    # 쓰는 프로세스면 어디서나 올라온다. 공간 모듈이 직접 import 하는 것은 가드가 막는다.
    code = (f'import sys, aot.space.{name}\n'
            "bad = sorted(m for m in sys.modules if m.startswith(("
            "'aot.aot_flask', 'aot.ai', 'aot.tools')))\n"
            'print(",".join(bad))')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == '', f'aot.space.{name} 가 웹 계층을 올렸다: {out}'
