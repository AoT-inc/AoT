# coding=utf-8
"""입출력 옵션의 키·지금 값과 수정 — 2026-10-28 claude.ai 점검(세션 A 항목 3).

AI 가 매뉴얼의 옵션 이름(사람 말)만 보고 input_edit 의 params 에 무엇을 넣을지
몰랐다. 장치 상세가 옵션 키·이름·지금 값을 싣고(비밀 값은 set/unset), 수정은
그 키만 받는다 — 주기·사전 출력은 Input 칸에 적고, 정의 밖 키는 승인 앞에서
거절한다(예전엔 custom_options 에 적고 성공했다 — 아무도 읽지 않는 키였다).
"""
import json

import pytest

from aot.config import ProdConfig

_TYPE = 'OPEN_METEO_FORECAST'


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'device_options.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _input():
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Input

    row = Input(unique_id=set_uuid())
    row.name = '예보 시험'
    row.device = _TYPE
    row.is_activated = False
    row.period = 3600.0
    row.custom_options = json.dumps({'api_key': 'secret-value'})
    db.session.add(row)
    db.session.commit()
    return row


def _svc():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


def test_detail_lists_option_keys_and_current_values_without_secrets(app):
    # 실행층은 처리기를 test_request_context 안에서 부른다(옵션 이름이 번역 문자열이다).
    with app.test_request_context():
        inp = _input()
        # 기본 응답에는 옵션·연결 값을 싣지 않는다(2026-11-03) — fields 로 청한다.
        plain = _svc().get_device_detail(device_id=inp.unique_id)
        assert 'options' not in plain and 'more' in plain
        result = _svc().get_device_detail(device_id=inp.unique_id, fields=['options'])
        by_key = {o['key']: o for o in result['options']}
        assert by_key['period']['value'] == 3600.0
        assert 'pre_output_duration' in by_key
        assert by_key['api_key']['value'] == 'set'
        assert 'secret-value' not in json.dumps(result, ensure_ascii=False)


def test_edit_writes_period_to_the_column_not_custom_options(app):
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input()
        out = _svc().modify_input(input_id=inp.unique_id, params={'period': 120})
        assert out.get('status') == 'modified', out
        row = Input.query.filter_by(unique_id=inp.unique_id).first()
        assert row.period == 120.0
        assert 'period' not in json.loads(row.custom_options)


def test_unknown_key_is_refused_before_approval_and_nothing_changes(app):
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input()
        problem = _svc().validate_device_options(input_id=inp.unique_id,
                                                 params={'periodd': 60})
        assert 'unknown option key(s): periodd' in problem['error']
        assert 'period' in problem['valid_keys']
        out = _svc().modify_input(input_id=inp.unique_id, name='바뀌면 안 됨',
                                  params={'periodd': 60})
        assert 'Nothing was changed' in out['error']
        row = Input.query.filter_by(unique_id=inp.unique_id).first()
        assert row.name == '예보 시험'


def test_bad_value_is_refused(app):
    with app.test_request_context():
        inp = _input()
        problem = _svc().validate_device_options(input_id=inp.unique_id,
                                                 params={'period': 'often'})
        assert 'period expects a number' in problem['error']


def test_pre_gate_runs_the_device_validator():
    from aot.tools import tool_execution as te
    assert te._PRE_GATE_VALIDATORS['modify_input'] == 'validate_device_options'
    assert te._PRE_GATE_VALIDATORS['modify_output'] == 'validate_device_options'
