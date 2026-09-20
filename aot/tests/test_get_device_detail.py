# coding=utf-8
"""get_device_detail — 장치 하나의 정체·위치·측정·제어·통신·담당구역·제약을
**한 번에** 낸다(2026-09-21).

지금까지는 search_devices(무엇인지) → get_device_measurements(무엇을 재는지)
→ get_device_location(어디인지) 을 잇달아 불러야 했다. 이 파일은 그 조합이
7개 키를 빠짐없이 내는지, 이름이 겹칠 때 하나를 고르지 않는지, 없는 id 는
에러로 떨어지는지, 그리고 무엇보다 **비밀 필드(비밀번호·토큰)가 응답 어디로도
새지 않는지** 를 고정한다.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "device_detail.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


# ---------------------------------------------------------------------------
# 픽스처 헬퍼 — 라이브 DB 를 건드리지 않는 임시 sqlite (app fixture) 위에서만 쓴다.
# ---------------------------------------------------------------------------

def _input(name, device='DHT22', is_activated=True):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Input

    row = Input(unique_id=set_uuid())
    row.name = name
    row.device = device
    row.is_activated = is_activated
    db.session.add(row)
    db.session.commit()
    return row


def _output(name, output_type='wired', parent_device_id=None):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Output

    row = Output(unique_id=set_uuid())
    row.name = name
    row.output_type = output_type
    row.parent_device_id = parent_device_id
    db.session.add(row)
    db.session.commit()
    return row


def _controller(name, device, parent_device_id=None, custom_options=None,
               is_activated=False):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import CustomController

    row = CustomController(unique_id=set_uuid())
    row.name = name
    row.device = device
    row.parent_device_id = parent_device_id
    row.is_activated = is_activated
    row.custom_options = json.dumps(custom_options or {})
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------------
# 1) unique_id 로 부르면 7개 키가 전부 있다.
# ---------------------------------------------------------------------------

class TestSevenKeysAlwaysPresent:
    def test_output_lookup_has_all_seven_keys(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            out = _output('밸브1')
            result = S.get_device_detail(device_id=out.unique_id)

            for key in ('what', 'location', 'measurements', 'output_channels',
                       'communication', 'geo_bindings', 'constraints'):
                assert key in result, f"missing key: {key}"

            assert result['what']['kind'] == 'output'
            assert result['what']['name'] == '밸브1'
            # 값이 비어도 키는 있어야 한다 — "없음" 과 "모름" 을 구분하기 위한
            # note 쌍도 함께. Output 은 get_device_location 이 알긴 하지만
            # 아직 지도에 배치되지 않아 lat/lng 가 비어 있다.
            assert result['location']['lat'] is None
            assert result['location']['lng'] is None
            assert result['location_note']
            assert result['measurements'] == []
            assert result['measurements_note']
            db.session.remove()

    def test_input_lookup_has_all_seven_keys_and_is_read_only(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            inp = _input('토양수분1')
            result = S.get_device_detail(device_id=inp.unique_id)

            for key in ('what', 'location', 'measurements', 'output_channels',
                       'communication', 'geo_bindings', 'constraints'):
                assert key in result

            assert result['what']['kind'] == 'input'
            assert result['what']['active'] is True
            # 센서는 OutputChannel 대상이 아니다 — 빈 목록 + 이유.
            assert result['output_channels'] == []
            assert result['output_channels_note']
            # 제어 도구가 없다는 사실이 constraints 에 남는다.
            assert result['constraints']['controlling_tools'] == []
            assert any('읽기 전용' in n for n in result['constraints']['notes'])
            db.session.remove()

    def test_function_kind_resolves_and_reports_active_flag(self, app):
        """CustomController 중 is_device 아닌 모듈은 kind='function' 이다."""
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            fn = _controller('환경제어기', 'env_coordinator', is_activated=False)
            result = S.get_device_detail(device_id=fn.name)

            assert result['what']['kind'] == 'function'
            assert result['what']['active'] is False
            assert result['constraints']['controlling_tools'] == [
                'activate_function', 'deactivate_function']
            # 비활성이면 그 사실이 constraints 에 남는다.
            assert any('비활성' in n for n in result['constraints']['notes'])
            db.session.remove()


# ---------------------------------------------------------------------------
# 2) 이름이 여러 개에 걸리면 needs_disambiguation 과 후보가 온다.
# ---------------------------------------------------------------------------

class TestDisambiguation:
    def test_colliding_name_across_kinds_is_not_guessed(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            out = _output('v11')
            inp = _input('v11')
            result = S.get_device_detail(device_id='v11')

            assert result.get('needs_disambiguation') is True
            assert 'error' in result
            assert result['candidates_total'] == 2
            ids = {c['id'] for c in result['candidates']}
            assert {out.unique_id, inp.unique_id} <= ids
            kinds = {c['kind'] for c in result['candidates']}
            assert kinds == {'output', 'input'}
            db.session.remove()

    def test_an_exact_id_wins_even_when_names_collide(self, app):
        """id 로 정확히 지목하면 동명이인 때문에 막히면 안 된다."""
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            a = _output('v11')
            _output('v11')
            result = S.get_device_detail(device_id=a.unique_id)
            assert 'needs_disambiguation' not in result
            assert result['device_id'] == a.unique_id
            db.session.remove()


# ---------------------------------------------------------------------------
# 3) 없는 id 면 error.
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_unknown_id_is_an_error(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            result = S.get_device_detail(device_id='no-such-device-ever')
            assert 'error' in result
            assert 'needs_disambiguation' not in result
            db.session.remove()

    def test_empty_device_id_is_an_error(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            result = S.get_device_detail(device_id=None)
            assert 'error' in result
            db.session.remove()


# ---------------------------------------------------------------------------
# 4) 비밀 필드가 새지 않는다.
# ---------------------------------------------------------------------------

class TestSecretsNeverLeak:
    def test_owning_device_password_and_token_come_back_as_set_only(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            plc = _controller(
                '온실1 PLC', 'device_modbus_plc_generic',
                custom_options={
                    'host': '192.168.0.50',
                    'port': 502,
                    # 값은 일부러 '비밀처럼 안 보이게' 둔다 — 공개본 gitleaks 가
                    # 무작위처럼 생긴 가짜 토큰을 진짜 유출로 잡는다(2026-09-21 실제).
                    'password': 'FAKE-PASSWORD-FOR-TEST',
                    'api_token': 'FAKE-TOKEN-FOR-TEST',
                    'cs_api_token': '',   # 빈 문자열은 unset 이어야 한다.
                })
            out = _output('밸브A', output_type='modbus_relay',
                          parent_device_id=plc.unique_id)

            result = S.get_device_detail(device_id=out.unique_id)
            dumped = json.dumps(result, ensure_ascii=False)

            assert 'FAKE-PASSWORD-FOR-TEST' not in dumped
            assert 'FAKE-TOKEN-FOR-TEST' not in dumped

            fields = result['communication']['fields']
            assert fields['password'] == 'set'
            assert fields['api_token'] == 'set'
            assert fields['cs_api_token'] == 'unset'
            # 비밀이 아닌 연결 필드는 그대로 나온다.
            assert fields['host'] == '192.168.0.50'
            assert fields['port'] == 502
            assert result['communication']['module'] == 'device_modbus_plc_generic'
            db.session.remove()

    def test_no_owning_device_reports_null_with_note(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.aot_data_tool_service import AoTDataToolService as S

        with app.app_context():
            out = _output('독립밸브')
            result = S.get_device_detail(device_id=out.unique_id)
            assert result['communication'] is None
            assert result['communication_note']
            db.session.remove()


# ---------------------------------------------------------------------------
# 5) 레지스트리에 등록돼 있고 build_tool_map() 으로 디스패치된다.
# ---------------------------------------------------------------------------

class TestRegistryWiring:
    def test_registered_in_virtual_tool_registry_and_tier(self):
        from aot.tools.tool_registry import (
            _TIER_ASSIGNMENT, virtual_tool_registry, manifest_system_tools)

        assert 'get_device_detail' in virtual_tool_registry()
        assert _TIER_ASSIGNMENT['get_device_detail'] == ('device', 'core', False)
        names = {m['tool_name'] for m in manifest_system_tools()
                if 'tool_name' in m}
        assert 'get_device_detail' in names

    def test_dispatched_via_build_tool_map(self, app):
        from aot.aot_flask.extensions import db
        from aot.tools.tool_registry import build_tool_map

        with app.app_context():
            out = _output('밸브2')
            tool_map = build_tool_map()
            assert 'get_device_detail' in tool_map
            result = tool_map['get_device_detail'](device_id=out.unique_id)
            assert result['what']['kind'] == 'output'
            db.session.remove()

    def test_read_only_not_mutating_or_physical(self):
        from aot.tools.tool_registry import TOOLS

        entry = next(t for t in TOOLS if t.name == 'get_device_detail')
        assert entry.mutating is False
        assert entry.physical is False
