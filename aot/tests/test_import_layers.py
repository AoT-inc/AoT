# coding=utf-8
"""패키지 간 import 방향 검사(ARCHITECTURE.md §4) — CI/훅과 같은 진입점.

실제 검사 로직은 aot/scripts/check_import_layers.py 하나뿐이다(pre-commit
훅과 Import Layers CI 워크플로가 그 스크립트를 직접 부른다). 이 테스트는
그 모듈을 import 해서 워킹트리에 baseline 을 벗어나는 새 위반이 없는지만
확인한다 — 네트워크도 DB 도 필요 없다. 실제 규칙(무엇이 금지되는가)이나
baseline 값 자체를 다시 구현하지 않는다: 그러면 로직이 두 곳에 생겨
드리프트만 는다(test_env_summary.py 가 check_alembic_head 를 부르는 것과
같은 이유). 아래 판정 테스트도 검사기의 `rule_hits` 를 그대로 부른다.
"""
from aot.scripts import check_import_layers as _import_layers


def test_no_new_import_layer_violations():
    new, _resolved = _import_layers.run_checks()
    assert not new, (
        'baseline 에 없는 새 import 방향 위반: '
        f'{sorted(new)} — ARCHITECTURE.md §4 참고, 되돌릴 수 없다면 검토 후 '
        'import_layers_baseline.txt 를 갱신하세요.'
    )


def _hits(src, rule_id):
    rule = next(r for r in _import_layers.RULES if r['id'] == rule_id)
    return _import_layers.rule_hits(src, 'x.py', rule)


def test_wildcard_catches_every_route_module():
    # `routes*` 는 점 경계 없이 — routes_geo_iec 도 걸린다.
    assert _hits('from aot.aot_flask.routes_geo_iec import f',
                 'twin-no-routes') == {'aot.aot_flask.routes_geo_iec'}
    # 이름으로 가져오는 형태도 펼쳐서 잡는다.
    assert _hits('from aot.aot_flask import routes_api',
                 'twin-no-routes') == {'aot.aot_flask.routes_api'}
    # 라우트가 아닌 것은 통과(트윈의 지연 앱·geo 차용은 허용).
    assert _hits('from aot.aot_flask.app import create_app\n'
                 'from aot.aot_flask.geo import plot_io',
                 'twin-no-routes') == set()


def test_dot_boundary_rules_ignore_expanded_names():
    # 금지 모듈 자체가 걸리면 펼친 이름은 따로 세지 않는다 — baseline 이 흔들리지 않게.
    assert _hits('from aot.aot_flask.geo import plot_io',
                 'daemon-no-flask') == {'aot.aot_flask.geo'}
    assert _hits('import flask_babel', 'daemon-no-flask') == set()


def test_dot_boundary_rules_catch_forbidden_module_imported_by_name():
    # 금지 모듈을 부모 패키지에서 이름으로 가져와도 잡는다.
    assert _hits('from aot.aot_flask import app',
                 'services-no-web') == {'aot.aot_flask.app'}
    assert _hits('from aot import ai', 'daemon-no-ai') == {'aot.ai'}
    assert _hits('from aot import aot_flask',
                 'daemon-no-flask') == {'aot.aot_flask'}
    # 금지와 이름만 비슷한 별개 모듈은 통과.
    assert _hits('from aot.aot_flask import extensions',
                 'services-no-web') == set()


def test_services_may_not_reach_routes_or_app():
    assert _hits('from aot.aot_flask.app import create_app',
                 'services-no-web') == {'aot.aot_flask.app'}
    assert _hits('from aot.aot_flask.extensions import db',
                 'services-no-web') == set()


def test_space_may_not_reach_the_web_layer():
    assert _hits('from aot.aot_flask.extensions import db',
                 'space-no-web') == {'aot.aot_flask.extensions'}
    # Flask 의 앱 컨텍스트 원시 기능과 gettext 는 허용한다(아키텍처 4c-1).
    assert _hits('from flask import current_app', 'space-no-web') == set()
    assert _hits('from flask_babel import gettext', 'space-no-web') == set()
    assert _hits('from flask_login import current_user', 'space-no-web') \
        == {'flask_login'}
    assert _hits('from aot.tools.data_tools import x', 'space-no-web') \
        == {'aot.tools.data_tools'}
    assert _hits('from aot.databases.models import GeoFacility\n'
                 'from aot.utils.timekit import utc_now', 'space-no-web') == set()


def test_daemon_may_not_import_ai():
    assert _hits('from aot.ai.services.x import y',
                 'daemon-no-ai') == {'aot.ai.services.x'}
