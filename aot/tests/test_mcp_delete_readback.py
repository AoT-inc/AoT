# coding=utf-8
"""삭제 승인 문구(되읽기) — 입력·출력·구획·프로그램·위젯·탭·AI 에이전트·지도 도형·GIS 입력·보관 문서.

예전에는 이 10종이 `_TOOL_ACTION_LABELS` 에 없어 승인 문구에 도구 이름 원문("delete_input")이 나왔다.
이제 동작 이름과 **서버가 id 로 찾은** 대상 이름·놓인 곳·영향을 되읽는다(노트 삭제와 같은 원칙).
- AI 가 보낸 `_title`·글은 문구에 쓰지 않는다. 못 찾으면 그렇다고 말한다. 조회가 깨지면 '확인하지 못했다'.
- 승인 흐름은 그대로다: 같은 도구가 늘 승인 대기이고 이 모듈은 읽기 전용이다.
"""
import json
from datetime import date, datetime
from unittest import mock

import pytest

from aot.config import ProdConfig
from aot.tools import delete_readback as DR
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_registry as R

@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'delete_readback.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


ID_ARG = {tool: spec[2] for tool, spec in DR.SPECS.items()}


def _uid():
    from aot.databases import set_uuid
    return set_uuid()


def _add(row):
    from aot.aot_flask.extensions import db
    db.session.add(row)
    db.session.commit()
    return row


def _make(tool):
    """도구마다 이름이 '시험-<종류>' 인 행을 하나 만들어 (id, 이름) 을 돌려준다."""
    from aot.databases.models import (
        GeoLayer, GeoPlot, GeoProgram, GeoShape, Input, Output, Tab, Widget)
    from aot.databases.models.ai import AIAgent
    name = '시험-' + DR.SPECS[tool][1]
    if tool == 'delete_input':
        row = _add(Input(unique_id=_uid(), name=name, device='LinuxCommand'))
    elif tool == 'delete_output':
        row = _add(Output(unique_id=_uid(), name=name, output_type='virtual_on_off_single'))
    elif tool == 'delete_plot':
        row = _add(GeoPlot(unique_id=_uid(), geo_id='m-rb', feature={}, subject='상추', name=name,
                           started_on=date(2026, 3, 1)))
    elif tool == 'delete_program':
        row = _add(GeoProgram(unique_id=_uid(), name=name, subject='토마토', stages=[]))
    elif tool == 'delete_widget':
        row = _add(Widget(unique_id=_uid(), name=name, graph_type='AoT_map', custom_options='{}'))
    elif tool == 'delete_tab':
        row = _add(Tab(unique_id=_uid(), name=name, page_type='input', position=999))
    elif tool == 'delete_ai_agent':
        row = _add(AIAgent(unique_id=_uid(), name=name))
    elif tool == 'delete_geo_shape':
        row = _add(GeoShape(unique_id=_uid(), geo_id='m-rb', type='zone',
                            feature={'type': 'Feature', 'properties': {'name': name}, 'geometry': None}))
    elif tool == 'delete_gis_input':
        row = _add(GeoLayer(unique_id=_uid(), name=name, type='gis_osm'))
    return row.unique_id, name


@pytest.mark.parametrize('tool', sorted(DR.SPECS))
def test_the_text_names_the_target_the_server_found_not_the_ai(app, tool):
    with app.test_request_context():
        target, name = _make(tool)
        args = {ID_ARG[tool]: target, '_title': 'AI 가 쓴 제목', 'title': 'AI 제목'}
        text = gate.read_back_text(tool, args)
        assert "'%s'" % name in text, text
        assert DR.SPECS[tool][0] in text                      # 동작 이름
        assert 'AI 가 쓴 제목' not in text and 'AI 제목' not in text
        assert tool not in text                               # 도구 이름 원문이 나오지 않는다
        assert '되돌릴 수 없습니다' in text


@pytest.mark.parametrize('tool', sorted(DR.SPECS))
def test_a_missing_target_is_said_not_guessed(app, tool):
    with app.test_request_context():
        text = gate.read_back_text(tool, {ID_ARG[tool]: 'no-such-id'})
        assert '찾지 못했습니다' in text and '지워질 것이 없습니다' in text
        assert DR.SPECS[tool][0] in text and tool not in text


@pytest.mark.parametrize('tool', sorted(DR.SPECS))
def test_no_target_id_is_said_too(app, tool):
    with app.test_request_context():
        text = gate.read_back_text(tool, {})
        assert '정해지지 않았습니다' in text and tool not in text


@pytest.mark.parametrize('tool', sorted(DR.SPECS))
def test_a_broken_lookup_says_unverified_and_does_not_block_the_flow(app, tool):
    with app.test_request_context():
        with mock.patch.dict(DR._FINDERS, {tool: mock.Mock(side_effect=RuntimeError('db'))}):
            text = gate.read_back_text(tool, {ID_ARG[tool]: 'x'})
        assert '확인하지 못했습니다' in text and '승인하지 마세요' in text
        assert tool not in text


@pytest.mark.parametrize('tool', sorted(DR.SPECS))
def test_the_fallback_title_is_never_the_tool_name(tool):
    assert gate.synthesize_title(tool, {ID_ARG[tool]: 'x'}) == DR.SPECS[tool][0]
    assert gate._TOOL_ACTION_LABELS[tool] == DR.SPECS[tool][0]


@pytest.mark.parametrize('tool', sorted(DR.SPECS))
def test_the_approval_policy_is_unchanged(tool):
    # 읽기 전용 되읽기만 더했다: 모두 그대로 쓰기이자 승인 대상이다.
    assert tool in R.approval_required_tools()
    assert tool in R.write_tools()
    assert tool not in gate.config_only_tools()
    assert tool not in gate.CONDITIONAL_APPROVAL_TOOLS


def test_the_note_delete_readback_is_untouched():
    assert 'delete_note' not in DR.TOOLS
    assert DR.readback('delete_note', {'note_id': 'x'}) is None
    assert '노트 삭제' in gate.read_back_text('delete_note', {'note_id': 'nope'})


def test_every_domain_delete_kind_with_an_inner_tool_is_covered():
    # remove.delete 의 종류 14개 중 노트·공지·일정·함수는 이미 동작 이름이 나오고, 나머지 10개는 이 모듈이 맡는다.
    from aot.tools.domain.registry import find_op
    from aot.tools.domain.registry_data import OPS
    inner = set(find_op(OPS, 'remove', 'delete').inner.values())
    assert set(DR.SPECS) <= inner
    for t in inner - set(DR.SPECS):
        assert gate._TOOL_ACTION_LABELS.get(t), t


# ── 영향 ────────────────────────────────────────────────────────────────────

def test_input_lists_who_reads_it_and_the_widgets(app):
    from aot.databases.models import PID, Widget
    with app.test_request_context():
        target, _ = _make('delete_input')
        _add(PID(unique_id=_uid(), name='관수 PID', measurement='%s,m' % target, is_activated=True))
        _add(Widget(unique_id=_uid(), name='w', graph_type='g', input_ids_measurements='%s,m' % target))
        text = gate.read_back_text('delete_input', {'input_id': target})
        assert "PID '관수 PID'" in text and '값을 잃습니다' in text
        assert '위젯 1개' in text


def test_input_with_no_users_says_none_found(app):
    with app.test_request_context():
        target, _ = _make('delete_input')
        assert '찾지 못했습니다' in gate.read_back_text('delete_input', {'input_id': target})


def test_output_lists_pid_actions_functions_and_widgets(app):
    from aot.databases.models import Actions, CustomController, PID, Widget
    with app.test_request_context():
        target, _ = _make('delete_output')
        _add(PID(unique_id=_uid(), name='온도 PID', raise_output_id=target))
        _add(Actions(unique_id=_uid(), do_unique_id=target))
        _add(CustomController(unique_id=_uid(), name='환기 함수', device='x',
                              custom_options=json.dumps({'out': target})))
        _add(Widget(unique_id=_uid(), name='w', graph_type='g', output_ids='%s,m' % target))
        text = gate.read_back_text('delete_output', {'output_id': target})
        assert "PID '온도 PID'" in text and "함수 '환기 함수'" in text
        assert '동작 1건' in text and '위젯 1개' in text


def test_output_long_lists_are_cut_to_four_and_a_count(app):
    from aot.databases.models import PID
    with app.test_request_context():
        target, _ = _make('delete_output')
        for i in range(6):
            _add(PID(unique_id=_uid(), name='P%d' % i, lower_output_id=target))
        text = gate.read_back_text('delete_output', {'output_id': target})
        assert '외 2' in text and 'P5' not in text


def test_plot_names_subject_dates_and_the_schedules_that_go_with_it(app):
    from aot.databases.models.scheduler import SchedulerJobMeta
    with app.test_request_context():
        target, _ = _make('delete_plot')
        _add(SchedulerJobMeta(action_type='output', target_id=target, state='PENDING'))
        text = gate.read_back_text('delete_plot', {'plot_id': target})
        assert '상추' in text and '2026-03-01 시작' in text and '재배 중' in text
        assert '일정 1건' in text and '삭제 말고 종료' in text


def test_program_in_use_says_it_will_be_refused(app):
    from aot.databases.models import GeoPlot
    with app.test_request_context():
        target, _ = _make('delete_program')
        assert '쓰는 구획 없음' in gate.read_back_text('delete_program', {'program_id': target})
        _add(GeoPlot(unique_id=_uid(), geo_id='m', feature={}, subject='s', started_on=date(2026, 1, 1),
                     program_uuid=target))
        text = gate.read_back_text('delete_program', {'program_id': target})
        assert '쓰는 구획 1건' in text and '거절됩니다' in text


def test_widget_names_its_dashboard(app):
    from aot.databases.models import Dashboard
    with app.test_request_context():
        dash = _add(Dashboard(unique_id=_uid(), name='온실 대시보드'))
        target, _ = _make('delete_widget')
        from aot.databases.models import Widget
        w = Widget.query.filter_by(unique_id=target).first()
        w.tab_id = dash.unique_id
        _add(w)
        assert '대시보드 온실 대시보드' in gate.read_back_text('delete_widget', {'widget_id': target})


def test_tab_lists_the_entries_that_are_deleted_with_it(app):
    from aot.databases.models import Input
    with app.test_request_context():
        target, _ = _make('delete_tab')
        _add(Input(unique_id=_uid(), name='안쪽 센서', device='LinuxCommand', tab_id=target))
        text = gate.read_back_text('delete_tab', {'tab_id': target})
        assert '입력 페이지의 탭' in text and "안의 입력 1개도 함께 지워집니다: '안쪽 센서'" in text


def test_empty_tab_says_so(app):
    with app.test_request_context():
        target, _ = _make('delete_tab')
        assert '안에 항목 없음' in gate.read_back_text('delete_tab', {'tab_id': target})


def test_shape_counts_inner_shapes(app):
    from aot.databases.models import GeoShape
    with app.test_request_context():
        target, _ = _make('delete_geo_shape')
        parent = GeoShape.query.filter_by(unique_id=target).first()
        _add(GeoShape(unique_id=_uid(), geo_id='m-rb', type='zone', parent_id=parent.id,
                      feature={'type': 'Feature', 'properties': {'name': '안쪽'}, 'geometry': None}))
        text = gate.read_back_text('delete_geo_shape', {'shape_id': target})
        assert '종류 zone' in text and '안쪽 도형 1개' in text


def test_agent_and_gis_input_state_whether_they_are_on(app):
    with app.test_request_context():
        target, _ = _make('delete_gis_input')
        assert '종류 gis_osm' in gate.read_back_text('delete_gis_input', {'layer_id': target})
        target, _ = _make('delete_ai_agent')
        assert 'MCP 접근 설정도 함께' in gate.read_back_text('delete_ai_agent', {'agent_id': target})
