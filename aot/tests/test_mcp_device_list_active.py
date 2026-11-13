# coding=utf-8
"""장치 목록의 켜짐 여부 — 2026-10-30 claude.ai 체험 피드백 5-1.

find.device_list 의 각 항목(입력·복합장치·카메라)에 `active` 를 싣고, 꺼진 것이 있으면 전체에서 센 수를 `inactive`
한 칸으로 알린다(쪽으로 잘려 첫 쪽에 안 보여도). 출력은 켜고 끄는 상태가 없어 칸이 없다.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'device_list.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _svc():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


def _add(model, **cols):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    row = model(unique_id=set_uuid())
    for k, v in cols.items():
        setattr(row, k, v)
    db.session.add(row)
    db.session.commit()
    return row


def test_inputs_and_cameras_carry_active_and_outputs_do_not(app):
    from aot.databases.models import Camera, Input, Output
    with app.test_request_context():
        _add(Input, name='켜진 센서', device='DHT22', is_activated=True)
        _add(Input, name='꺼진 센서', device='DHT22', is_activated=False)
        _add(Output, name='밸브', output_type='wired')
        _add(Camera, name='카메라', camera_type='x', library='opencv', is_activated=False)
        out = _svc().get_device_list_tool()
        by = {r['name']: r for r in out['results']}
        assert by['켜진 센서']['active'] is True
        assert by['꺼진 센서']['active'] is False
        assert by['카메라']['active'] is False
        assert 'active' not in by['밸브']
        assert out['inactive'] == 2


def test_no_summary_line_when_everything_is_on(app):
    from aot.databases.models import Input
    with app.test_request_context():
        _add(Input, name='센서', device='DHT22', is_activated=True)
        out = _svc().get_device_list_tool()
        assert 'inactive' not in out


def test_the_count_covers_every_page_not_just_the_one_shown(app):
    from aot.databases.models import Input
    with app.test_request_context():
        for i in range(45):
            _add(Input, name='센서%02d' % i, device='DHT22', is_activated=(i < 40))
        out = _svc().get_device_list_tool()
        assert out['count'] == 40                     # 첫 쪽(기본 40)
        assert out['inactive'] == 5                   # 다음 쪽에 있는 꺼진 5개도 센다
        assert out['page']['total'] == 45


def test_ai_excluded_devices_are_not_counted(app):
    from aot.databases.models import Input
    with app.test_request_context():
        _add(Input, name='보이는 꺼짐', device='DHT22', is_activated=False)
        _add(Input, name='AI 제외 꺼짐', device='DHT22', is_activated=False, is_ai_enabled=False)
        out = _svc().get_device_list_tool()
        assert out['inactive'] == 1


def test_the_domain_op_returns_it_within_its_budget(app):
    from aot.tools.domain.registry import find_op
    from aot.tools.domain.registry_data import OPS
    o = find_op(OPS, 'find', 'devices')        # device_list 는 devices 로 합쳐졌다(재설계 PR 3)
    assert o.budget == 6000
    from aot.databases.models import Input
    with app.test_request_context():
        for i in range(40):
            _add(Input, name='센서%02d' % i, device='DHT22', is_activated=bool(i % 2))
        from aot.tools import tool_execution as te
        text = json.dumps(_svc().get_device_list_tool(), ensure_ascii=False)
        assert te._estimate_tokens(text) < o.budget
