# coding=utf-8
"""
AI 기록 "도구 호출" 제목 — 도구 이름 원문을 사람 말로 바꾸는지.

synthesize_title 의 표는 승인이 걸리는 쓰기 도구만 채워 두어, 조회 도구는 이름
원문(open_drawer, search_notes …)이 그대로 기록 화면에 나왔다(2026-09-10 실측).
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

import pytest
from flask import Flask
from flask_babel import Babel

from aot.aot_flask.routes_mcp_api import _audit_title


@pytest.fixture
def ctx():
    app = Flask(__name__)
    Babel(app)
    with app.test_request_context('/'):
        yield


@pytest.mark.parametrize('tool', ['open_drawer', 'search_notes', 'get_function_list',
                                  'search_devices', 'get_spatial_tree', 'get_device_list',
                                  'search_schedule', 'get_tool_detail',
                                  'list_pending_confirmations', 'respond_to_confirmation',
                                  'a_tool_nobody_registered'])
def test_the_raw_tool_name_never_comes_back(ctx, tool):
    assert _audit_title(tool, {}, 'read') != tool


def test_read_tools_are_named_by_what_they_looked_at(ctx):
    assert _audit_title('search_notes', {}, 'read') == 'Looked up notes and knowledge'
    assert _audit_title('open_drawer', {}, 'read') == 'Browsed the tool list'
    assert _audit_title('a_tool_nobody_registered', {}, 'read') == 'Looked something up'


def test_titles_written_by_the_tool_are_kept(ctx):
    """공지처럼 도구 인자에 사람이 쓴 제목이 있으면 그대로 쓴다."""
    assert _audit_title('create_notice', {'title': '테스트 공지'}, 'write') == '테스트 공지'


def test_unknown_write_tool_falls_back_to_a_plain_phrase(ctx):
    assert _audit_title('a_writer_nobody_registered', {}, 'write') == 'Made a change'
