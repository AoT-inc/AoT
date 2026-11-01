# coding=utf-8
"""detail.device 는 요약이 기본이다 — 2026-10-30 claude.ai 체험 피드백 5-3.

MQTT 장치 하나가 측정 항목 전부와 접속·장치 옵션 전체를 한 번에 실어 길었다. 도메인 틀의 detail.device 는
이름·종류·켜짐·상태·위치·최근 수신·측정 채널(이름·단위)만 주고, 옵션·접속·측정 id 같은 나머지는 공통 어휘 `fields`
로 청할 때만 더한다. 안쪽 도구는 `fields` 를 안 주면 전과 같은 전체 응답이다 — 인앱 AI 와 직접 호출은 그대로.
"""
import json
from unittest import mock

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'detail_summary.db'}"
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


def _input(name='예보 시험', **cols):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import DeviceMeasurements, Input
    row = Input(unique_id=set_uuid())
    row.name = name
    row.device = 'OPEN_METEO_FORECAST'
    row.is_activated = True
    row.period = 3600.0
    row.custom_options = json.dumps({'api_key': 'secret-value'})
    for k, v in cols.items():
        setattr(row, k, v)
    db.session.add(row)
    db.session.commit()
    for i, (nm, meas, unit) in enumerate((('기온', 'temperature', 'C'), ('습도', 'humidity', 'percent'))):
        m = DeviceMeasurements(unique_id=set_uuid())
        m.device_id = row.unique_id
        m.name, m.measurement, m.unit, m.channel = nm, meas, unit, i
        db.session.add(m)
    db.session.commit()
    return row


def _seen():
    return mock.patch.object(_svc(), '_last_seen_seconds',
                             return_value=(42.0, '2026-10-30T09:00:00+09:00', 'temperature (ch0)'))


def test_without_fields_the_inner_tool_still_returns_everything(app):
    with app.test_request_context():
        inp = _input()
        out = _svc().get_device_detail(device_id=inp.unique_id)
        for key in ('what', 'location', 'measurements', 'communication', 'geo_bindings',
                    'constraints', 'options'):
            assert key in out
        assert 'last_seen' not in out and 'more' not in out


def test_the_brief_has_name_state_place_last_seen_and_channel_names_and_units(app):
    with app.test_request_context():
        inp = _input()
        with _seen():
            out = _svc().get_device_detail(device_id=inp.unique_id, fields=[])
        assert out['device_id'] == inp.unique_id
        assert out['what']['name'] == '예보 시험'
        assert out['what']['kind'] == 'input' and out['what']['active'] is True
        assert out['last_seen'] == {'at': '2026-10-30T09:00:00+09:00', 'age_s': 42}
        assert out['channels'] == [{'name': '기온', 'unit': 'C'}, {'name': '습도', 'unit': 'percent'}]
        assert 'place' in out
        for heavy in ('options', 'communication', 'measurements', 'geo_bindings', 'constraints', 'location'):
            assert heavy not in out, heavy
        assert 'secret-value' not in json.dumps(out, ensure_ascii=False)
        assert 'fields=[' in out['more'] and 'options' in out['more']


def test_the_brief_is_much_shorter_than_the_whole(app):
    from aot.tools import tool_execution as te
    with app.test_request_context():
        inp = _input()
        with _seen():
            full = _svc().get_device_detail(device_id=inp.unique_id)
            brief = _svc().get_device_detail(device_id=inp.unique_id, fields=[])
        n_full = te._estimate_tokens(json.dumps(full, ensure_ascii=False))
        n_brief = te._estimate_tokens(json.dumps(brief, ensure_ascii=False))
        assert n_brief < n_full * 0.5, (n_brief, n_full)


def test_fields_add_only_what_was_asked(app):
    with app.test_request_context():
        inp = _input()
        with _seen():
            out = _svc().get_device_detail(device_id=inp.unique_id, fields=['options'])
        keys = {o['key']: o for o in out['options']}
        assert keys['api_key']['value'] == 'set'                 # 비밀 값은 set/unset
        assert 'secret-value' not in json.dumps(out, ensure_ascii=False)
        assert 'communication' not in out and 'measurements' not in out
        assert 'options' not in out.get('more', '')

        with _seen():
            out = _svc().get_device_detail(device_id=inp.unique_id,
                                           fields=['connection', 'measurements'])
        assert 'communication' in out and 'communication_note' in out
        assert out['measurements'][0]['select_value'].startswith(inp.unique_id)
        assert 'options' not in out


def test_all_is_the_whole_answer_and_unknown_names_are_reported(app):
    with app.test_request_context():
        inp = _input()
        with _seen():
            whole = _svc().get_device_detail(device_id=inp.unique_id)
            allf = _svc().get_device_detail(device_id=inp.unique_id, fields=['all'])
            odd = _svc().get_device_detail(device_id=inp.unique_id, fields=['Options', 'bogus'])
        assert set(allf) >= set(whole)
        assert 'options' in odd and odd['unknown_fields'] == ['bogus']      # 대소문자는 가리지 않는다


def test_an_output_brief_lists_its_channels_without_last_seen(app):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Output
    from aot.databases.models.output import OutputChannel
    with app.test_request_context():
        out_row = Output(unique_id=set_uuid())
        out_row.name = '밸브 8'
        out_row.output_type = 'wired'
        db.session.add(out_row)
        db.session.commit()
        ch = OutputChannel(unique_id=set_uuid())
        ch.output_id = out_row.unique_id
        ch.channel = 0
        ch.name = '1번'
        db.session.add(ch)
        db.session.commit()
        got = _svc().get_device_detail(device_id=out_row.unique_id, fields=[])
        assert got['what']['kind'] == 'output'
        assert got['output_channels'] == [{'channel': 0, 'name': '1번'}]
        assert 'last_seen' not in got


def test_last_seen_failure_does_not_break_the_brief(app):
    with app.test_request_context():
        inp = _input()
        with mock.patch.object(_svc(), '_last_seen_seconds', side_effect=RuntimeError('influx down')):
            got = _svc().get_device_detail(device_id=inp.unique_id, fields=[])
        assert got['what']['name'] == '예보 시험' and 'last_seen' not in got


def test_silent_input_says_none_within_a_week(app):
    with app.test_request_context():
        inp = _input()
        with mock.patch.object(_svc(), '_last_seen_seconds', return_value=(None, None, None)):
            got = _svc().get_device_detail(device_id=inp.unique_id, fields=[])
        assert got['last_seen'] == {'at': None, 'within': '7d'}


# ── 도메인 틀 ────────────────────────────────────────────────────────────────

def _plan(args, kind='input'):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan('detail', dict({'op': 'device', 'target': '예보'}, **args))


def test_the_domain_op_asks_for_the_brief_by_default():
    for kind in ('input', 'output', 'device'):
        v = _plan({}, kind=kind)
        assert v[0] == 'call' and v[1] == 'get_device_detail', v
        assert v[2]['fields'] == []


def test_fields_pass_through_as_a_list_or_as_comma_text():
    v = _plan({'fields': ['options']})
    assert v[2]['fields'] == ['options']
    v = _plan({'fields': 'options, connection'})
    assert v[2]['fields'] == ['options', 'connection']


def test_the_shared_word_is_in_the_detail_schema_and_help_explains_it():
    from aot.tools import tool_registry as R
    from aot.tools.domain import dispatch, surface
    from aot.tools.domain.registry_data import OPS
    ents = surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))
    detail = next(e for e in ents if e['name'] == 'detail')
    assert detail['inputSchema']['properties']['fields'] == surface.VOCAB_SCHEMA['fields']
    card = dispatch.help_card('detail.device')
    assert 'options' in card['shared_args']['fields']['here']
    assert 'secrets as set/unset' in card['shared_args']['fields']['here']


def test_no_new_vocabulary_word():
    from aot.tools.domain.registry import VOCAB
    assert 'fields' in VOCAB
