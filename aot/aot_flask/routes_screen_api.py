# -*- coding: utf-8 -*-
"""화면 연동 동기화 — 외부 AI 의 화면 조작 명령을 그 화면이 가져가는 곳 (2026-10, P2).

서버가 브라우저로 먼저 보낼 길이 없어(SocketIO·Redis 없음, 워커 여럿) 화면의
JS(static/js/common/aot-screen-link.js)가 "이 기기에서 AI 화면 조작 허용" 이
켜져 있는 동안만 짧은 주기로 이곳을 부른다. 한 번의 요청이 세 가지를 한다:
화면 상태 보고, 지난 명령의 결과·화면 확인([허용]/[거절]) 반영, 새 명령 받기.

**로그인 쿠키로 들어온 브라우저만** 받는다. API 키로 부르면 스크립트가 화면인 척
화면 확인을 대신 누를 수 있다 — 화면 확인은 화면 앞의 사람이 눌러야 의미가 있다.
"""
import flask_login
from flask import Blueprint, current_app, jsonify, request

from aot.utils import bundle_manifest, web_presence

blueprint = Blueprint('routes_screen_api', __name__, url_prefix='/api/v1/screen')

#: 한 번에 받는 결과·확인 수 — 화면이 보낼 일이 거의 없는 크기.
_MAX_ITEMS = 20


@blueprint.route('/sync', methods=['POST'])
@flask_login.login_required
def screen_sync():
    from aot.aot_flask.app import _raw_api_keys_from_request
    if next(_raw_api_keys_from_request(request), None) is not None:
        return jsonify({'error': 'screen sync takes a browser session, not an API key'}), 403
    cookie = request.cookies.get(
        current_app.config.get('SESSION_COOKIE_NAME') or 'session')
    key = web_presence.browser_key(cookie)
    if key is None:
        return jsonify({'error': 'no session cookie'}), 400

    body = request.get_json(silent=True) or {}
    state = body.get('state') if isinstance(body.get('state'), dict) else {}
    results = [r for r in (body.get('results') or [])[:_MAX_ITEMS] if isinstance(r, dict)]
    answers = [a for a in (body.get('answers') or [])[:_MAX_ITEMS] if isinstance(a, dict)]
    user_id = flask_login.current_user.unique_id
    # 동기화 요청 자체도 "보는 중" 신호다 — 행이 아직 없으면(첫 요청) 만든다.
    ua = request.headers.get('User-Agent', '')
    web_presence.record(user_id, key, ua, request.path, 'poll')
    # visible·follow 는 예전 JS 가 보내지 않는다 — 없으면 None(저장된 값을 둔다).
    visible = body.get('visible')
    out = web_presence.sync(user_id, key, state=state,
                            allowed=bool(body.get('allowed')),
                            results=results, answers=answers,
                            visible=None if visible is None else bool(visible),
                            follow=body.get('follow'), tab=body.get('tab'))
    _audit_finished(out.pop('_finished', None) or (), key, ua)
    # AI 수신함 미읽음 수 — 페이지 첫 동기화가 inbox 를 true 로 보낼 때만 센다.
    # 평소 폴링에는 DB 조회가 없다(2026-10-19).
    if body.get('inbox') is True:
        from aot.utils import ai_screen_cards
        out['ai_unread'] = ai_screen_cards.unread_count(flask_login.current_user.id)
    # 현재 screen-link 번들 해시 — layout 의 asset('screen-link') 과 같은 매니페스트에서 읽는다. 오래 열어 둔 탭이
    # 자기 해시(window.AOT_BUNDLES)와 다르면 "화면이 오래됐습니다 — 새로고침" 을 띄운다(자동 새로고침 없음).
    h = bundle_manifest.hash_of('screen-link')
    if h:
        out['bundle'] = h
    return jsonify(out)


def _audit_finished(finished, key, ua):
    """AI 가 이 화면에서 한 일을 감사 기록에 남긴다 — 명령 행은 12시간 뒤 지워져
    "AI 가 내 화면에서 무엇을 했나" 를 나중에 되짚을 수 없었다(2026-10-11).
    기록 실패는 동기화를 막지 않는다(audit_log 가 예외를 삼킨다)."""
    if not finished:
        return
    from aot.utils import audit
    device, _form = web_presence.describe_device(ua)
    for f in finished:
        detail = '%s — %s' % (f.get('describe') or f.get('action') or '?',
                              f.get('status'))
        # 출처 — 읽기에 딸려 열린 것(follow)인지 AI 가 직접 부른 것(explicit)인지.
        # 둘이 기록에서 구분되지 않아 "왜 열렸나/안 열렸나" 를 시각을 맞춰 추정해야 했다
        # (2026-10-19 조사). 출처를 모르는 옛 명령은 붙이지 않는다.
        if f.get('source'):
            detail = '[%s] %s' % (f['source'], detail)
        if f.get('message') and f.get('status') != 'done':
            detail += ': %s' % f['message']
        audit.audit_log(audit.SCREEN_COMMAND, target_type='Screen',
                        target_id=key[:12], target_name=device,
                        result='success' if f.get('status') == 'done' else 'failure',
                        detail=detail[:500])
