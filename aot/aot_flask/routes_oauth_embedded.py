# coding=utf-8
# @manual ai/overview#embedded-auth
"""내장 OAuth 인가 서버의 HTTP 경로(docs/design/mcp-embedded-oauth.md §4). 규칙은 `aot/tools/mcp_embedded.py`.

켜져 있지 않으면(설정 > 일반 > MCP 인증 설정에서 "이 AoT(내장)" 를 고르지 않았으면) 전부 404 — 존재 자체를 알리지 않는다.
토큰·등록·끊기는 브라우저가 아니라 AI 서비스(서버)가 부르므로 CSRF 를 면제하고, 사람이 보는 /authorize 의 동의 폼만 CSRF 를 쓴다.
"""
import json
import logging
from urllib.parse import urlencode, urlsplit

import flask_login
from flask import Blueprint, jsonify, make_response, redirect, render_template, request, session
from flask_babel import gettext

from aot.aot_flask.extensions import csrf
from aot.aot_flask.utils import utils_general
from aot.tools import mcp_central, mcp_embedded
from aot.tools.mcp_embedded import OAuthError
from aot.utils.audit import audit_log

logger = logging.getLogger('aot.aot_flask.oauth_embedded')

blueprint = Blueprint('routes_oauth_embedded', __name__, template_folder='templates')


def _cfg():
    """내장 모드로 켜져 있으면 설정, 아니면 None."""
    cfg = mcp_central.config()
    return cfg if mcp_central.is_embedded(cfg) and mcp_central.is_active(cfg) else None


def _detail(**values):
    """audit_log 의 detail 은 문자열 칸이다."""
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def _not_found():
    return jsonify({'error': 'not_found'}), 404


def _no_store(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


def _json_error(exc):
    body = {'error': exc.error}
    if exc.description:
        body['error_description'] = exc.description
    return _no_store(jsonify(body)), exc.status


def _public(response):
    """공개 정보(메타데이터·JWKS)는 브라우저 기반 점검 도구도 읽을 수 있게 한다."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


# ── 메타데이터·JWKS ─────────────────────────────────────────────────────────

@blueprint.route('/.well-known/oauth-authorization-server', methods=['GET'])
def authorization_server_metadata():
    cfg = _cfg()
    if cfg is None:
        return _not_found()
    return _public(jsonify(mcp_embedded.authorization_server_metadata(cfg.issuer)))


@blueprint.route('/.well-known/jwks.json', methods=['GET'])
def jwks():
    cfg = _cfg()
    if cfg is None:
        return _not_found()
    mcp_embedded.ensure_key()
    return _public(jsonify(mcp_embedded.jwks()))


# ── 동적 클라이언트 등록 ────────────────────────────────────────────────────

@blueprint.route('/register', methods=['POST'])
@csrf.exempt
def register():
    if _cfg() is None:
        return _not_found()
    try:
        info = mcp_embedded.register_client(request.get_json(silent=True))
    except OAuthError as exc:
        return _json_error(exc)
    audit_log('mcp.oauth_register', target_type='OAuthClient', target_name=info['client_name'],
              detail=_detail(client_id=info['client_id'], redirect_uris=info['redirect_uris']),
              username='oauth-client')
    return _no_store(jsonify(info)), 201


# ── 인가 ────────────────────────────────────────────────────────────────────

def _farm_name(cfg):
    """동의 화면의 가장 큰 글자 — 관리자가 정한 이름(hostname_override), 없으면 공개 주소의 호스트."""
    from aot.databases.models import Misc
    misc = Misc.query.first()
    named = (getattr(misc, 'hostname_override', '') or '').strip() if misc is not None else ''
    return named or urlsplit(cfg.issuer).hostname or cfg.issuer


def _page(cfg, status=200, **context):
    from aot.config import THEMES_DARK
    context.setdefault('error_message', None)
    html = render_template('oauth_consent.html', farm_name=_farm_name(cfg), issuer_host=urlsplit(cfg.issuer).netloc,
                           dark_themes=THEMES_DARK, **context)
    response = _no_store(make_response(html, status))
    # 다른 사이트가 이 화면을 프레임에 넣고 "허용" 을 누르게 속이는 것을 막는다.
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
    return response


def _back_to_client(req, **params):
    """되돌림 주소로 결과(code 또는 error)를 돌려준다. 어느 인가 서버가 답했는지(iss)도 싣는다(RFC 9207)."""
    if req.state:
        params['state'] = req.state
    params['iss'] = req.issuer
    joiner = '&' if urlsplit(req.redirect_uri).query else '?'
    return redirect(req.redirect_uri + joiner + urlencode(params), code=302)


def _role_allows(name, role):
    """이 역할이 그 범위의 일을 할 수 있는가 — 못 하면 동의 화면에서 꺼 둔다(어차피 restrict_role 이 좁힌다)."""
    if name == mcp_central.SCOPE_CONTROL:
        return bool(role is not None and role.can_write)
    if name == mcp_central.SCOPE_CONFIG:
        return bool(role is not None and (role.can_edit_settings or role.can_edit_plots))
    return True


def _scope_rows(req, role):
    help_text = {
        mcp_central.SCOPE_READ: gettext('Look at sensors, devices, schedules and notes.'),
        mcp_central.SCOPE_CONTROL: gettext('Turn devices and functions on and off.'),
        mcp_central.SCOPE_CONFIG: gettext('Change settings, plots and records.'),
    }
    label = {
        mcp_central.SCOPE_READ: gettext('Read'),
        mcp_central.SCOPE_CONTROL: gettext('Control'),
        mcp_central.SCOPE_CONFIG: gettext('Configure'),
    }
    rows = []
    for name in req.scopes:
        required = name == mcp_central.SCOPE_READ
        allowed = _role_allows(name, role)
        rows.append({'name': name, 'label': label.get(name, name), 'help': help_text.get(name, ''),
                     'disabled': required or not allowed, 'checked': required or allowed})
    return rows


@blueprint.route('/authorize', methods=['GET', 'POST'])
def authorize():
    cfg = _cfg()
    if cfg is None:
        return _not_found()
    values = request.values
    req = mcp_embedded.parse_authorize(values, cfg.public_url)
    req.issuer = cfg.issuer

    if req.error is not None:
        if not req.redirect_ok:
            # 클라이언트나 되돌림 주소를 믿을 수 없으면 그리로 보내지 않고 이 화면에서 알린다.
            return _page(cfg, status=400, error_message=gettext(
                'This AI app\'s request is not valid (%(reason)s). Go back to the app and try again.',
                reason=req.error.description or req.error.error))
        return _back_to_client(req, error=req.error.error, error_description=req.error.description)

    user = flask_login.current_user
    if not user.is_authenticated:
        # 로그인 뒤 같은 요청으로 돌아온다(routes_authentication 의 로그인 성공 지점들이 이 값을 본다).
        query = request.query_string.decode('utf-8') if request.method == 'GET' else urlencode(
            {key: value for key, value in values.items() if key not in ('csrf_token', 'decision', 'scope')})
        session[utils_general.OAUTH_RETURN_KEY] = '/authorize?' + query
        return redirect('/login')
    if not getattr(user, 'is_enabled', True) or not getattr(user, 'is_approved', True):
        return _back_to_client(req, error='access_denied', error_description='This account cannot be used.')

    from aot.tools import mcp_auth
    role = mcp_auth._role_for(user)
    if not mcp_auth.role_can_use_mcp(role):
        # AI 채팅 권한이 없는 역할 — 동의 화면 없이 이유만 알린다(읽기 범위도 주지 않는다).
        audit_log('mcp.oauth_deny', target_type='OAuthClient', target_name=req.client.client_name,
                  detail=_detail(client_id=req.client.client_id, reason='role_without_ai_chat'))
        return _page(cfg, status=403, error_message=gettext("This account's role is not allowed to use AI connections. Ask an administrator."))
    hidden = {key: values.get(key, '') for key in (
        'response_type', 'client_id', 'redirect_uri', 'code_challenge', 'code_challenge_method', 'state', 'scope',
        'resource') if values.get(key)}

    if request.method == 'GET':
        return _page(cfg, client_name=req.client.client_name or 'MCP client', user_name=user.name,
                     hidden=hidden, scopes=_scope_rows(req, role))

    if request.form.get('decision') != 'allow':
        audit_log('mcp.oauth_deny', target_type='OAuthClient', target_name=req.client.client_name,
                  detail=_detail(client_id=req.client.client_id))
        return _back_to_client(req, error='access_denied', error_description='The user denied the request.')

    # 사용자가 고른 범위 — 요청한 것 안에서, 역할이 못 하는 것은 뺀다. 읽기는 언제나 들어간다.
    picked = set(request.form.getlist('grant'))
    scopes = [name for name in req.scopes
              if name == mcp_central.SCOPE_READ or (name in picked and _role_allows(name, role))]
    code = mcp_embedded.create_code(req, user, scopes)
    audit_log('mcp.oauth_allow', target_type='OAuthClient', target_name=req.client.client_name,
              detail=_detail(client_id=req.client.client_id, scopes=scopes))
    return _back_to_client(req, code=code)


# ── 토큰·끊기 ───────────────────────────────────────────────────────────────

@blueprint.route('/token', methods=['POST'])
@csrf.exempt
def token():
    cfg = _cfg()
    if cfg is None:
        return _not_found()
    form = request.form
    grant_type = form.get('grant_type')
    try:
        if grant_type == 'authorization_code':
            body, grant = mcp_embedded.exchange_code(
                issuer=cfg.issuer, public_url=cfg.public_url, client_id=form.get('client_id'),
                code=form.get('code'), redirect_uri=form.get('redirect_uri'),
                code_verifier=form.get('code_verifier'), resource=form.get('resource'))
            audit_log('mcp.oauth_token', target_type='OAuthGrant', target_name=grant.client_name,
                      detail=_detail(gid=grant.gid, user_id=grant.user_id, scope=grant.scope),
                      user_id=grant.user_id)
        elif grant_type == 'refresh_token':
            body, grant = mcp_embedded.refresh_grant(
                issuer=cfg.issuer, public_url=cfg.public_url, client_id=form.get('client_id'),
                refresh_token=form.get('refresh_token'), scope=form.get('scope'), resource=form.get('resource'))
        else:
            raise OAuthError('unsupported_grant_type', 'grant_type must be authorization_code or refresh_token.')
    except OAuthError as exc:
        return _json_error(exc)
    return _no_store(jsonify(body))


@blueprint.route('/revoke', methods=['POST'])
@csrf.exempt
def revoke():
    cfg = _cfg()
    if cfg is None:
        return _not_found()
    gid = mcp_embedded.revoke_token(request.form.get('token'), request.form.get('client_id'), cfg.issuer)
    if gid:
        audit_log('mcp.oauth_revoke', target_type='OAuthGrant', detail=_detail(gid=gid), username='oauth-client')
    return _no_store(jsonify({})), 200
