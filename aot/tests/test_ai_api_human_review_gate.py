# coding=utf-8
"""
AI API 가드(check_ai_enabled)가 사람의 검토 경로까지 막지 않는지.

AI → 요청 화면은 AI 가 사람의 결정을 기다리는 것을 모은다. 그중 조언 원장은
외부 AI(MCP)·하위 노드도 의견을 내고 **사람이** 채택·기각하는 곳이라, 내장 AI
모델이 돌지 않아도 열려 있어야 한다. 그런데 AI API 블루프린트 전체에 걸린
before_request 가 "모델이 아직 안 돌아간다" 며 403 을 주어, 화면이 "기다리는
조언이 없습니다" 로 보였다(2026-09-10 실측).

DB·로그인 없이 가드 함수만 부른다 — 설정·런타임 상태는 바꿔 끼운다.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

import pytest
from flask import Flask

from aot.aot_flask import routes_ai_api
from aot.ai.services import ai_runtime_state


class _Settings:
    def __init__(self, ai_enabled):
        self.ai_enabled = ai_enabled


class _Query:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _SettingsModel:
    def __init__(self, ai_enabled):
        self.query = _Query(_Settings(ai_enabled))


@pytest.fixture
def app():
    a = Flask(__name__)
    a.register_blueprint(routes_ai_api.blueprint)
    return a


def _guard(app, monkeypatch, path, method='GET', ai_enabled=True, model_running=False):
    monkeypatch.setattr(routes_ai_api, 'AI_AGENT_ENABLED', True)
    monkeypatch.setattr(routes_ai_api, 'AIGlobalSettings', _SettingsModel(ai_enabled))
    monkeypatch.setattr(ai_runtime_state, 'ai_autonomy_enabled', lambda *a, **k: model_running)
    with app.test_request_context(path, method=method):
        return routes_ai_api.check_ai_enabled()


@pytest.mark.parametrize('path,method', [
    # AI → 요청: 조언 검토
    ('/api/v1/ai/advice', 'GET'),
    ('/api/v1/ai/advice/abc/accept', 'POST'),
    ('/api/v1/ai/advice/abc/reject', 'POST'),
    # AI → 기록: 오류 보고 목록 · 지식에 반영(DB 기록만 한다)
    ('/api/v1/ai/feedback/errors', 'GET'),
    ('/api/v1/ai/feedback/error/abc/knowledge', 'POST'),
    # 일정 화면의 장치 타임라인 — AI 기능이 아니다
    ('/api/scheduler/device_timeline', 'GET'),
])
def test_advice_review_is_open_while_the_builtin_model_is_off(app, monkeypatch, path, method):
    assert _guard(app, monkeypatch, path, method) is None


def test_model_running_endpoints_are_still_gated(app, monkeypatch):
    """예외는 사람 검토 셋뿐이다 — 내장 모델을 실행하는 경로는 여전히 막힌다."""
    resp = _guard(app, monkeypatch, '/api/v1/ai/discovery')
    assert resp is not None and resp[1] == 403


def test_advice_is_blocked_when_the_ai_feature_is_turned_off(app, monkeypatch):
    """AI 메뉴 자체를 끈 설치(ai_enabled=False)에서는 조언도 닫힌다."""
    resp = _guard(app, monkeypatch, '/api/v1/ai/advice', ai_enabled=False)
    assert resp is not None and resp[1] == 403
