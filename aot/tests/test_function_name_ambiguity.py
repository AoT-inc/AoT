# coding=utf-8
"""이름이 겹치는 함수를 AI 도구가 이름으로 찾을 때 고르지 않는지 검사한다.

실제 사고(2026-09-25): 로컬 서버에 활성 하나·비활성 하나, 이름이 똑같은
"Env Coordinator" 커스텀 컨트롤러가 있었다. 함수 이름에는 DB 유일성 제약이
없고(`duplicate_function_name_warning` 은 저장을 막지 않고 경고만 한다),
`get_function_detail`/`activate_function_tool`/`deactivate_function_tool`/
`configure_sequence_day`/`modify_sequence_schedule`(그리고 schedule.py 의
`_set_entity_activation`)은 예전에 `(unique_id == x) | (name == x)).first()`
로 네 테이블을 따로 짚어, 이름이 겹치면 행 순서로 아무거나 하나를 집었다 —
꺼져 있는 쪽을 다시 "꺼서" 성공을 보고하는 동안 진짜 켜져 있는 쪽은 그대로
돌 수 있었다. 이 파일은 겹치면 `needs_disambiguation` 으로 멈추는지, 데몬이
그동안 아예 불리지 않는지, 그리고 unique_id 로 직접 지목하면 여전히 정상
동작하는지를 검사한다.
"""
import pytest

from aot.config import ProdConfig


class _DaemonRecorder:
    def __init__(self):
        self.calls = []

    def controller_activate(self, controller_id):
        self.calls.append(('controller_activate', controller_id))
        return 0, 'ok'

    def controller_deactivate(self, controller_id):
        self.calls.append(('controller_deactivate', controller_id))
        return 0, 'ok'

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append((name, args))
            return 0, 'ok'
        return _record

    @property
    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "function_name_ambiguity.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


@pytest.fixture
def daemon(monkeypatch):
    import aot.aot_client as aot_client

    rec = _DaemonRecorder()
    monkeypatch.setattr(aot_client, 'DaemonControl', lambda *a, **kw: rec)
    return rec


def _make_custom_controller(name, is_activated=False, device='env_coordinator'):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models.controller import CustomController

    uid = set_uuid()
    row = CustomController(unique_id=uid)
    row.name = name
    row.device = device
    row.is_activated = is_activated
    db.session.add(row)
    db.session.commit()
    return uid


def _make_conditional(name, is_activated=False):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models.function import Conditional

    uid = set_uuid()
    row = Conditional(unique_id=uid)
    row.name = name
    row.is_activated = is_activated
    db.session.add(row)
    db.session.commit()
    return uid


def test_duplicate_name_refuses_activation(app, daemon):
    """실제 사고 재현: 이름이 같은 CustomController 둘 — 이름으로 켜라고
    하면 고르지 않고 needs_disambiguation, 데몬은 아예 불리지 않는다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        active_id = _make_custom_controller("Env Coordinator", is_activated=True)
        inactive_id = _make_custom_controller("Env Coordinator", is_activated=False)

        res = AoTDataToolService.activate_function_tool("Env Coordinator")

        assert res.get('error'), res
        assert res.get('needs_disambiguation') is True, res
        ids_in_candidates = {c['id'] for c in res['candidates']}
        assert ids_in_candidates == {active_id, inactive_id}
        assert not daemon.calls, daemon.calls

        # 데몬을 안 불렀을 뿐 아니라 DB 상태도 그대로여야 한다.
        from aot.databases.models.controller import CustomController
        still_active = CustomController.query.filter_by(unique_id=active_id).first()
        still_inactive = CustomController.query.filter_by(unique_id=inactive_id).first()
        assert still_active.is_activated is True
        assert still_inactive.is_activated is False


def test_duplicate_name_refuses_get_function_detail(app, daemon):
    from aot.tools.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        _make_custom_controller("Env Coordinator", is_activated=True)
        _make_custom_controller("Env Coordinator", is_activated=False)

        res = AoTDataToolService.get_function_detail("Env Coordinator")

        assert res.get('needs_disambiguation') is True, res
        assert len(res['candidates']) == 2


def test_duplicate_name_across_different_types_also_refuses(app, daemon):
    """겹치는 이름이 **다른 종류**(Trigger 대신 Conditional)일 때도 잡아낸다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        _make_conditional("Shared Name")
        _make_custom_controller("Shared Name")

        res = AoTDataToolService.get_function_detail("Shared Name")

        assert res.get('needs_disambiguation') is True, res
        kinds = {c['function_type'] for c in res['candidates']}
        assert kinds == {'conditional', 'custom'}


def test_unique_id_still_resolves_when_name_is_ambiguous(app, daemon):
    """이름이 겹쳐도 **unique_id 로 직접 지목**하면 정상 동작한다 — 앞
    도구 호출이 낸 id 를 이름 검색으로 새게 하지 않는다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        active_id = _make_custom_controller("Env Coordinator", is_activated=False)
        _make_custom_controller("Env Coordinator", is_activated=False)

        res = AoTDataToolService.activate_function_tool(active_id)

        assert res.get('status') == 'success', res
        assert ('controller_activate', active_id) in daemon.calls


def test_unambiguous_name_still_works(app, daemon):
    """이름이 하나뿐이면 예전처럼 바로 동작한다(회귀 확인)."""
    from aot.tools.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        _make_custom_controller("Only One", is_activated=False)

        res = AoTDataToolService.activate_function_tool("Only One")

        assert res.get('status') == 'success', res
        assert 'controller_activate' in daemon.names


def test_schedule_set_entity_activation_also_refuses_duplicate(app, daemon):
    """schedule.py::_set_entity_activation 도 같은 리졸버를 쓴다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        _make_custom_controller("Env Coordinator", is_activated=True)
        _make_custom_controller("Env Coordinator", is_activated=False)

        res = AoTDataToolService._set_entity_activation("Env Coordinator", True)

        assert res.get('error'), res
        assert res.get('needs_disambiguation') is True, res
        assert not daemon.calls, daemon.calls


# ── 웹 UI 저장 시 경고(3단계) ────────────────────────────────────────────
#
# 사용자 결정(26-09-25): 이름이 겹쳐도 저장은 막지 않고 경고만 표시한다.
# `duplicate_function_name_warning` 은 utils_controller/utils_function/
# utils_trigger/utils_conditional/utils_pid 의 *_mod 가 공유하는 순수
# DB 조회 헬퍼라, 폼 배관 없이 이 helper 자체를 직접 검사한다.

def test_duplicate_name_warning_none_when_unique(app):
    """`exclude_id` 로 자기 자신을 뺀 채 이름이 하나뿐이면 경고가 없다."""
    from aot.aot_flask.utils.utils_function import duplicate_function_name_warning

    with app.test_request_context():
        uid = _make_custom_controller("Solo Name")
        assert duplicate_function_name_warning("Solo Name", exclude_id=uid) is None
        assert duplicate_function_name_warning("Nonexistent Name") is None


def test_duplicate_name_warning_excludes_self(app):
    """이름을 그대로 두고 저장할 때 자기 자신과는 겹친다고 하지 않는다."""
    from aot.aot_flask.utils.utils_function import duplicate_function_name_warning

    with app.test_request_context():
        uid = _make_custom_controller("Keep This Name")
        assert duplicate_function_name_warning("Keep This Name", exclude_id=uid) is None


def test_duplicate_name_warning_fires_across_tables(app):
    """같은 테이블은 물론, 다른 종류(Conditional vs CustomController)에도
    같은 이름이 있으면 경고한다 — 저장은 여전히 허용(None 이 아니라 문구만)."""
    from aot.aot_flask.utils.utils_function import duplicate_function_name_warning

    with app.test_request_context():
        _make_conditional("Cross Table Dup")
        warning = duplicate_function_name_warning("Cross Table Dup")
        assert warning, "경고가 없다"

        # 같은 테이블 안의 중복도 잡는다.
        first_id = _make_custom_controller("Same Table Dup")
        _make_custom_controller("Same Table Dup")
        warning2 = duplicate_function_name_warning(
            "Same Table Dup", exclude_id=first_id)
        assert warning2, "같은 테이블 중복 경고가 없다"
