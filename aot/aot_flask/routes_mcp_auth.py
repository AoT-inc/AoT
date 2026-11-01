# coding=utf-8
"""외부 MCP 인증 설정(설정 > 일반 > AI 서비스 > MCP 인증 설정 모달)과 계정 연결.

설정 저장·연결 점검은 설정 편집 권한(`edit_settings`)이 있어야 한다. 계정 연결은 **자기 계정**만 잇고 끊으므로
로그인만 요구한다 — 연결로 얻는 것은 그 사람의 역할 안에서만 도는 AI 연결이고, 누가 이 사이트에 들어올 수
있는지는 인가 서버의 접근 표가 정한다.
"""
import json
import logging
import secrets

import flask_login
from flask import Blueprint, flash, jsonify, redirect, request, session, url_for
from flask_babel import gettext
from flask_login import login_required

from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general
from aot.tools import mcp_central
from aot.utils import audit
from aot.utils.audit import audit_log

logger = logging.getLogger('aot.aot_flask.mcp_auth')

blueprint = Blueprint('routes_mcp_auth', __name__, static_folder='../static', template_folder='../templates')

_LINK_KEY = 'mcp_central_link'
_BACK = '/settings/general?mcp_auth=1'


def modal_context(user):
    """설정 > 일반 화면의 모달이 보여 줄 값."""
    cfg = mcp_central.config()
    from aot.databases.models import AIGlobalSettings, Misc
    row = AIGlobalSettings.query.first()
    misc = Misc.query.first()
    return {
        'cfg': cfg,
        'active': mcp_central.is_active(cfg),
        'can_link': mcp_central.can_link(cfg),
        # 입력칸에는 저장된 값 그대로(정규화에 실패한 값도 보여야 고칠 수 있다)
        'saved': {
            'issuer': (row.mcp_central_issuer if row is not None else '') or '',
            'public_url': (row.mcp_public_url if row is not None else '') or '',
            'link_client_id': (row.mcp_link_client_id if row is not None else '') or '',
            'has_secret': bool(row is not None and row.mcp_link_client_secret),
            'web_base_url': (misc.oauth_public_base_url if misc is not None else '') or '',
        },
        'redirect_uri': mcp_central.redirect_uri(cfg),
        'callback_path': mcp_central.CALLBACK_PATH,
        'metadata_url': mcp_central.resource_metadata_url(cfg) if cfg.public_url else '',
        'scopes': mcp_central.SCOPES,
        'linked': mcp_central.linked_account(cfg, user) if user is not None else None,
        'my_keys': _my_api_keys(user),
        'mode': cfg.mode,
        'saved_mode': (row.mcp_auth_mode if row is not None else '') or mcp_central.MODE_CENTRAL,
        'embedded': _embedded_context(cfg, user),
    }


def _embedded_context(cfg, user):
    """내장 인가 서버 칸이 보여 줄 값 — 허용 목록과 이 사용자가 내준 연결."""
    from aot.databases.models import OAuthGrant
    from aot.tools import mcp_embedded
    grants = []
    if user is not None and getattr(user, 'id', None):
        grants = (OAuthGrant.query.filter_by(user_id=user.id, status=OAuthGrant.ACTIVE)
                  .order_by(OAuthGrant.created_at.desc()).all())
    return {
        'allowlist': mcp_embedded.redirect_allowlist(),
        'grants': [{'gid': g.gid, 'name': g.client_name or g.client_id, 'scopes': g.scope.split(),
                    'created': g.created_at, 'used': g.last_used_at} for g in grants],
    }


def _my_api_keys(user):
    """이 사람의 살아 있는 API 키와 지금 도구 묶음 — 'AI 도구 목록' 모달용.

    키 발급 화면(설정 > 사용자)은 관리자 화면이라, 자기 키의 묶음을 보고 바꾸는
    자리가 따로 필요했다(2026-10-10 — 가벼움 묶음은 무료 요금제에서 대화 한도를
    아끼려고 고르는 것이라 사용자가 스스로 오갈 수 있어야 한다)."""
    if user is None or not getattr(user, 'id', None):
        return []
    from aot.databases.models import UserAPIKey
    rows = (UserAPIKey.query.filter(UserAPIKey.user_id == user.id,
                                    UserAPIKey.revoked_at.is_(None))
            .order_by(UserAPIKey.id).all())
    out = [{'kind': 'key', 'id': r.unique_id, 'name': r.name or '',
            'profile': r.effective_tool_profile,
            'spec': r.tool_profile_spec} for r in rows]
    # 인가 서버(OAuth)로 연결된 계정 — claude.ai 원격 커넥터처럼 키를 못 넣는 앱은
    # 이 연결로 들어온다(p6_83). 비어 있으면 토큰 범위로 정해진다('configuration'
    # 또는 'operations') — 화면에는 그 사실을 '토큰 범위' 로 보인다.
    from aot.databases.models import MCPExternalAccount
    from aot.tools.tool_registry import normalize_tool_profile
    for link in MCPExternalAccount.query.filter(
            MCPExternalAccount.user_id == user.id).order_by(MCPExternalAccount.id).all():
        spec = normalize_tool_profile(link.tool_profile) if link.tool_profile else ''
        out.append({'kind': 'link', 'id': str(link.id),
                    'name': link.label or link.issuer,
                    'profile': spec.split('+')[0] if spec else '',
                    'spec': spec})
    return out


def _form_value(name):
    return (request.form.get(name) or '').strip()


# @manual ai/overview#central-auth
@blueprint.route('/settings/mcp_auth/config', methods=['POST'])
@login_required
def mcp_auth_config():
    if not utils_general.user_has_permission('edit_settings'):
        flash(gettext("Your permissions do not allow this action"), "error")
        return redirect(_BACK)

    from aot.databases.models import AIGlobalSettings, Misc
    from aot.utils.crypto import encrypt_secret

    row = AIGlobalSettings.query.first()
    if row is None:
        row = AIGlobalSettings()
        db.session.add(row)
    misc = Misc.query.first()

    # 환경변수로 정해진 칸은 화면에서 비활성이라 폼에 오지 않는다 — 오지 않은 칸은 그대로 둔다.
    form = request.form
    enabled = (form.get('mcp_central_enabled') in ('y', 'on', '1', 'true')
               if 'mcp_central_enabled_shown' in form else bool(row.mcp_central_enabled))
    # 인증 서버 종류 — 환경변수로 정해졌으면 화면에서 비활성이라 폼에 오지 않는다(오지 않으면 그대로)
    mode = _form_value('mcp_auth_mode') if 'mcp_auth_mode' in form else (row.mcp_auth_mode or mcp_central.MODE_CENTRAL)
    if mode not in (mcp_central.MODE_CENTRAL, mcp_central.MODE_EMBEDDED):
        mode = mcp_central.MODE_CENTRAL
    embedded = mode == mcp_central.MODE_EMBEDDED
    issuer = _form_value('mcp_central_issuer').rstrip('/') if 'mcp_central_issuer' in form else (row.mcp_central_issuer or '')
    public_url = _form_value('mcp_public_url') if 'mcp_public_url' in form else (row.mcp_public_url or '')
    web_base = _form_value('oauth_public_base_url').rstrip('/') if 'oauth_public_base_url' in form else None

    errors = []
    if issuer and not embedded and mcp_central.normalize_issuer(issuer) is None:
        errors.append(gettext("The authorization server address must start with https:// (http only for localhost)."))
    if public_url and mcp_central.normalize_public_url(public_url) is None:
        errors.append(gettext("The public MCP address must be a full address with a path, such as https://farm.example.com/mcp."))
    if embedded and public_url and mcp_central.normalize_public_url(public_url) and not mcp_central.embedded_issuer(public_url):
        errors.append(gettext("This AoT can act as the authorization server only at an https address (http only for localhost)."))
    if web_base and mcp_central.normalize_web_base(web_base) is None:
        errors.append(gettext("The public web address must be a full address such as https://farm.example.com."))
    effective = mcp_central.config()
    if enabled and embedded and not (public_url or effective.from_env['public_url']):
        errors.append(gettext("To turn on authentication, enter the public MCP address."))
    elif enabled and not embedded and not ((issuer or effective.from_env['issuer']) and (public_url or effective.from_env['public_url'])):
        errors.append(gettext("To turn on central authentication, enter both the authorization server address and the public MCP address."))
    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(_BACK)

    before = {'enabled': bool(row.mcp_central_enabled), 'mode': row.mcp_auth_mode or mcp_central.MODE_CENTRAL,
              'issuer': row.mcp_central_issuer or '',
              'public_url': row.mcp_public_url or '', 'link_client_id': row.mcp_link_client_id or ''}
    row.mcp_central_enabled = enabled
    row.mcp_auth_mode = mode
    row.mcp_central_issuer = issuer
    row.mcp_public_url = public_url
    if 'mcp_link_client_id' in form:
        row.mcp_link_client_id = _form_value('mcp_link_client_id')
    secret = _form_value('mcp_link_client_secret')
    if secret:
        row.mcp_link_client_secret = encrypt_secret(secret)
    if misc is not None and web_base is not None:
        misc.oauth_public_base_url = web_base
    db.session.commit()

    audit_log(audit.SETTINGS_CHANGE, target_type='AIGlobalSettings', target_name='MCP Authentication',
              before=before,
              after={'enabled': enabled, 'mode': mode, 'issuer': issuer, 'public_url': public_url,
                     'link_client_id': row.mcp_link_client_id,
                     'link_client_secret': 'changed' if secret else 'kept'})
    if enabled and embedded:
        # 서명 키는 처음 켤 때 만든다(권한 600, 설치마다 따로). 못 만들면 지금 알려야 한다.
        from aot.tools import mcp_embedded
        try:
            mcp_embedded.ensure_key()
        except OSError as exc:
            logger.error("[MCP] 내장 인가 서버 서명 키를 만들지 못했다: %s", exc)
            flash(gettext("Settings were saved, but the signing key could not be created. Check that the data folder is writable."), "error")
            return redirect(_BACK)
    flash(gettext("MCP authentication settings saved."), "success")
    return redirect(_BACK)


# @manual ai/overview#central-auth
@blueprint.route('/settings/mcp_auth/check', methods=['POST'])
@login_required
def mcp_auth_check():
    """저장하기 전의 값으로 인가 서버에 닿아 본다."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'error': gettext("Your permissions do not allow this action")}), 403
    saved = mcp_central.config()
    mode = _form_value('mcp_auth_mode')
    if mode not in (mcp_central.MODE_CENTRAL, mcp_central.MODE_EMBEDDED):
        mode = saved.mode
    public_url = mcp_central.normalize_public_url(_form_value('mcp_public_url')) or ''
    issuer = mcp_central.normalize_issuer(_form_value('mcp_central_issuer')) or ''
    if mode == mcp_central.MODE_EMBEDDED:
        issuer = mcp_central.embedded_issuer(public_url)
    cfg = saved._replace(
        mode=mode, issuer=issuer, public_url=public_url,
        link_client_id=_form_value('mcp_link_client_id') or saved.link_client_id,
        link_client_secret=_form_value('mcp_link_client_secret') or saved.link_client_secret,
        web_base_url=mcp_central.normalize_web_base(_form_value('oauth_public_base_url')) or '')
    labels = {
        'issuer': gettext("Authorization server"),
        'public_url': gettext("Public MCP address"),
        'metadata': gettext("Authorization server metadata"),
        'jwks': gettext("Signing keys"),
        'link': gettext("Account linking"),
    }
    return jsonify({'results': [{'name': labels.get(name, name), 'ok': ok, 'message': message}
                                for name, ok, message in mcp_central.check(cfg, gettext)]})


# @manual ai/overview#central-auth
@blueprint.route('/settings/mcp_auth/link', methods=['POST'])
@login_required
def mcp_auth_link():
    cfg = mcp_central.config()
    if not mcp_central.can_link(cfg):
        flash(gettext("Account linking is not set up yet. Ask an administrator to finish the MCP authentication settings."), "error")
        return redirect(_BACK)
    code_verifier, challenge = mcp_central.new_pkce()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(16)
    session[_LINK_KEY] = {'state': state, 'verifier': code_verifier, 'nonce': nonce,
                          'user_id': flask_login.current_user.id, 'issuer': cfg.issuer}
    return redirect(mcp_central.authorize_url(cfg, state=state, code_challenge=challenge, nonce=nonce))


# @manual ai/overview#central-auth
@blueprint.route(mcp_central.CALLBACK_PATH, methods=['GET'])
@login_required
def mcp_auth_callback():
    pending = session.pop(_LINK_KEY, None)
    cfg = mcp_central.config()
    if (not pending or pending.get('state') != request.args.get('state')
            or pending.get('user_id') != flask_login.current_user.id or pending.get('issuer') != cfg.issuer):
        flash(gettext("The account link request expired or does not match. Try linking again."), "error")
        return redirect(_BACK)
    if request.args.get('error') or not request.args.get('code'):
        flash(gettext("The authorization server did not approve the account link."), "error")
        return redirect(_BACK)
    try:
        claims = mcp_central.exchange_link_code(
            cfg, code=request.args['code'], code_verifier=pending['verifier'], nonce=pending['nonce'])
        mcp_central.link_account(cfg, flask_login.current_user, claims)
    except mcp_central.LinkError as exc:
        logger.warning("[MCP] 계정 연결 실패: %s", exc)
        db.session.rollback()
        flash(gettext("Could not link the account: %(err)s", err=str(exc)), "error")
        return redirect(_BACK)
    audit_log('mcp.account_link', target_type='User', target_id=flask_login.current_user.id,
              target_name=flask_login.current_user.name, detail=json.dumps({'issuer': cfg.issuer}, ensure_ascii=False))
    flash(gettext("Your account is linked. AI connections signed in with this account now act as you."), "success")
    return redirect(_BACK)


# @manual ai/overview#central-auth
@blueprint.route('/settings/mcp_auth/unlink', methods=['POST'])
@login_required
def mcp_auth_unlink():
    from aot.databases.models import MCPExternalAccount
    rows = MCPExternalAccount.query.filter_by(user_id=flask_login.current_user.id).all()
    for row in rows:
        db.session.delete(row)
    db.session.commit()
    if rows:
        audit_log('mcp.account_unlink', target_type='User', target_id=flask_login.current_user.id,
                  target_name=flask_login.current_user.name, detail=json.dumps({'issuers': [r.issuer for r in rows]}, ensure_ascii=False))
    flash(gettext("Your account is unlinked. AI connections signed in with it can no longer act here."), "success")
    return redirect(_BACK)


# @manual ai/overview#central-auth
@blueprint.route('/settings/mcp_auth/disconnect', methods=['POST'])
@login_required
def mcp_auth_disconnect():
    """내장 인가 서버로 내준 **자기** 연결을 끊는다(남의 연결은 사용자를 끄거나 비밀번호를 바꿔 끊는다)."""
    from aot.databases.models import OAuthGrant
    from aot.tools import mcp_embedded
    user = flask_login.current_user
    gid = _form_value('gid')
    grant = OAuthGrant.query.filter_by(gid=gid, user_id=user.id, status=OAuthGrant.ACTIVE).first() if gid else None
    if grant is None:
        flash(gettext("That connection was not found."), "error")
        return redirect(_BACK)
    mcp_embedded.revoke_grant(grant.gid, 'user_disconnect')
    audit_log('mcp.oauth_disconnect', target_type='User', target_id=user.id, target_name=user.name,
              detail=grant.client_name or grant.client_id)
    flash(gettext("The connection was closed. That AI app has to be authorized again to use this AoT."), "success")
    return redirect(_BACK)


@blueprint.route('/settings/mcp_key_profile', methods=['POST'])
@login_required
def mcp_key_profile():
    """자기 API 키의 도구 묶음 바꾸기(가벼움·운영·설정). 남의 키는 사용자 편집
    권한이 있어야 한다(설정 > 사용자 와 같은 문턱). 바뀐 목록은 AI 앱이 다시
    연결하거나 새 대화를 열 때부터 보인다."""
    from aot.databases.models import UserAPIKey
    from aot.databases.models.user_api_key import tool_profile_columns
    from aot.tools.tool_registry import parse_tool_profile
    user = flask_login.current_user
    new_value = parse_tool_profile(_form_value('tool_profile'))
    if _form_value('link_id'):
        return _link_profile(user, _form_value('link_id'), new_value)
    row = UserAPIKey.query.filter(
        UserAPIKey.unique_id == _form_value('api_key_id')).first()
    if row is None or row.revoked_at is not None:
        flash(gettext("API key not found."), "error")
        return redirect('/settings/general')
    if row.user_id != user.id and not utils_general.user_has_permission('edit_users'):
        flash(gettext("Your permissions do not allow this action"), "error")
        return redirect('/settings/general')
    if new_value is None:
        flash(gettext("Choose a tool set for this key."), "error")
        return redirect('/settings/general')
    before = row.tool_profile_spec
    row.tool_profile, row.tool_modules = tool_profile_columns(new_value)
    db.session.commit()
    audit_log(audit.API_KEY_PROFILE_CHANGE, target_type='User',
              target_id=user.unique_id, target_name=user.name,
              detail=row.name or None, before={'tool_profile': before},
              after={'tool_profile': row.tool_profile_spec})
    flash(gettext("Tool list changed. Reconnect the AI app or start a new chat to see it."),
          "success")
    return redirect('/settings/general')


def _link_profile(user, link_id, new_value):
    """인가 서버로 연결된 **자기** 계정의 도구 묶음(p6_83). 남의 연결은 바꾸지 않는다."""
    from aot.databases.models import MCPExternalAccount
    link = MCPExternalAccount.query.filter(MCPExternalAccount.id == link_id).first() \
        if str(link_id).isdigit() else None
    if link is None or link.user_id != user.id:
        flash(gettext("Your permissions do not allow this action"), "error")
        return redirect('/settings/general')
    if new_value is None:
        flash(gettext("Choose a tool set for this key."), "error")
        return redirect('/settings/general')
    before = link.tool_profile or ''
    link.tool_profile = new_value
    db.session.commit()
    audit_log(audit.API_KEY_PROFILE_CHANGE, target_type='User',
              target_id=user.unique_id, target_name=user.name,
              detail='linked account: %s' % (link.label or link.issuer),
              before={'tool_profile': before}, after={'tool_profile': new_value})
    flash(gettext("Tool list changed. Reconnect the AI app or start a new chat to see it."),
          "success")
    return redirect('/settings/general')
