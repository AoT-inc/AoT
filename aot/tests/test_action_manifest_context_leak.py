# coding=utf-8
"""get_action_manifest 가 밀어 넣은 Flask 컨텍스트를 되돌리는가.

요청 컨텍스트 없이 부르면 함수가 가짜 요청 컨텍스트를 push 한다. pop 하지
않으면 그 스레드에 남아, 뒤이은 "사람 없는" 호출(예약 잡·Function)이
`requester_from_flask()` 에서 로그인하지 않은 사람의 요청으로 읽혀 쓰기가
거부된다. 같은 프로세스에서 이 함수를 부른 테스트 뒤의 무관한 테스트가
깨지던 원인(test_mcp_task24_integration → 예약 잡 테스트 5건).
"""
import pytest
from flask import has_app_context, has_request_context

from aot.ai import ai_request_context as ai_ctx
from aot.ai.services.ai_action_service import AIActionService


@pytest.fixture
def app():
    from aot.aot_flask.app import create_app
    return create_app()


def test_manifest_without_context_leaves_none_behind(app):
    assert not has_request_context() and not has_app_context()
    AIActionService.get_action_manifest()
    assert not has_request_context()
    assert not has_app_context()


def test_manifest_inside_app_context_pops_only_its_own_request(app):
    with app.app_context():
        AIActionService.get_action_manifest()
        assert has_app_context()
        assert not has_request_context()
        assert ai_ctx.current_requester() is None
