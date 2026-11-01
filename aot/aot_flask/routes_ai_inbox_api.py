# -*- coding: utf-8 -*-
"""AI 수신함 API — 외부 AI 가 남긴 카드(자막)의 목록·읽음·닫기·고정·파일 (2026-10-19, P0·P1·P2).

카드는 screen_action(action='post')가 만든다(aot/utils/ai_screen_cards.py). 이 API 는
**로그인 쿠키로 들어온 브라우저만** 쓴다(화면 동기화와 같은 규칙 — API 키로 AI 가
자기가 쓴 카드를 읽음 처리하거나 지우면 안 된다). 모든 질의는 current_user.id 로
거르고, 남의 카드 id 는 404 다. CSRF 보호는 그대로다(전역 fetch 가 X-CSRFToken 을 붙인다).
끄기 엔드포인트는 없다 — 끄기는 settings/general 의 "AI 메시지 숨기기"(Misc.hide_ai_messages).

P1: 남의 것·없는 것·만료·파일 없음은 모두 404 `not_found`(존재를 알리지 않는다, 403 아님).
파일은 DB 의 상대경로를 realpath 로 풀어 저장 디렉터리 안인지 확인한 뒤에만 보낸다
(ai_card_files.resolve) — 요청 값으로 경로를 만들지 않는다.

P2: `/artifact`(아티팩트=정적 HTML 카드를 **iframe 안에서만** 보낸다 — 응답 CSP 가
sandbox 라 주소로 직접 열어도 불투명 출처·스크립트 없음), `/to-notice`([공지로 게시] —
사람이 뷰어에서 두 번 눌러야만 오는 웹 경로 전용, API 키 403·edit_settings 403·남의 카드 404).
"""
import re
from urllib.parse import quote

import flask_login
from flask import Blueprint, Response, jsonify, request, send_file

from aot.utils import ai_card_files as card_files
from aot.utils import ai_screen_cards as cards

blueprint = Blueprint('routes_ai_inbox_api', __name__, url_prefix='/api/v1/ai-inbox')


def _api_key_request():
    from aot.aot_flask.app import _raw_api_keys_from_request
    return next(_raw_api_keys_from_request(request), None) is not None


def _guard():
    """API 키 요청이면 403 응답, 아니면 None."""
    if _api_key_request():
        return jsonify({'error': 'api_key_not_allowed'}), 403
    return None


def _not_found():
    return jsonify({'error': 'not_found'}), 404


@blueprint.route('', methods=['GET'])
@blueprint.route('/', methods=['GET'])
@flask_login.login_required
def inbox_list():
    denied = _guard()
    if denied:
        return denied
    uid = flask_login.current_user.id
    limit = request.args.get('limit', cards.LIST_DEFAULT, type=int)
    found = cards.list_cards(uid, limit=limit, before=request.args.get('before') or None,
                             q=request.args.get('q', '')[:200],
                             pinned=request.args.get('pinned') == '1')
    if found is None:
        return _not_found()
    rows, more = found
    live = cards.live_notice_ids(rows)
    amap = cards.attachments_map(rows)
    return jsonify({'items': [cards.to_item(c, live, amap[c.id]) for c in rows],
                    'unread': cards.unread_count(uid), 'more': more,
                    'can_notice': cards.can_notice()})


@blueprint.route('/<card_id>/read', methods=['POST'])
@flask_login.login_required
def inbox_read(card_id):
    denied = _guard()
    if denied:
        return denied
    uid = flask_login.current_user.id
    if not cards.mark_read(uid, card_id):
        return _not_found()
    return jsonify({'ok': True, 'unread': cards.unread_count(uid)})


@blueprint.route('/read-all', methods=['POST'])
@flask_login.login_required
def inbox_read_all():
    denied = _guard()
    if denied:
        return denied
    cards.read_all(flask_login.current_user.id)
    return jsonify({'ok': True, 'unread': 0})


@blueprint.route('/<card_id>/dismiss', methods=['POST'])
@flask_login.login_required
def inbox_dismiss(card_id):
    denied = _guard()
    if denied:
        return denied
    uid = flask_login.current_user.id
    if not cards.dismiss(uid, card_id):
        return _not_found()
    return jsonify({'ok': True, 'unread': cards.unread_count(uid)})


@blueprint.route('/<card_id>/pin', methods=['POST'])
@flask_login.login_required
def inbox_pin(card_id):
    denied = _guard()
    if denied:
        return denied
    result = cards.pin(flask_login.current_user.id, card_id)
    if result is None:
        return _not_found()
    if result == 'limit':
        return jsonify({'error': 'pin_limit', 'limit': cards.PIN_MAX}), 409
    return jsonify({'ok': True, 'pinned': True})


@blueprint.route('/<card_id>/unpin', methods=['POST'])
@flask_login.login_required
def inbox_unpin(card_id):
    denied = _guard()
    if denied:
        return denied
    if not cards.unpin(flask_login.current_user.id, card_id):
        return _not_found()
    return jsonify({'ok': True, 'pinned': False})


# ── 파일·섬네일·텍스트 ──────────────────────────────────────────────────────

_INLINE_EXTS = ('png', 'jpg', 'jpeg', 'gif', 'webp')


def _ascii_name(name, ext):
    out = re.sub(r'[^A-Za-z0-9._ -]', '_', name.encode('ascii', 'ignore').decode())
    out = out.strip(' .') or 'download'
    return out if '.' in out else '%s.%s' % (out, ext)


def _disposition(kind, name):
    """filename 은 ASCII 대체, filename* 은 RFC 5987. 따옴표·CR/LF·세미콜론은 뗀다."""
    name = re.sub(r'[\r\n"\\;]', '', name or 'download')
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else 'bin'
    return '%s; filename="%s"; filename*=UTF-8\'\'%s' % (
        kind, _ascii_name(name, ext), quote(name, safe=''))


#: 파일 응답의 CSP. 앱 전체 Talisman 이 after_request 로 CSP 를 덮어쓰므로(느슨한 사이트
#: 정책) 응답 헤더에 직접 쓰는 것만으로는 남지 않는다 — Talisman 이 뷰별로 받는
#: `talisman_view_options` 로도 같은 값을 건다(아래 `_FILE_VIEWS`).
_FILE_CSP = "default-src 'none'; img-src 'self'; sandbox"


def _harden(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Content-Security-Policy'] = _FILE_CSP
    resp.headers['Cache-Control'] = 'private, max-age=300'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    return resp


_INDEX = re.compile(r'[0-7]')


def _attachment(card_id, want_file=True):
    """이 사람의 만료되지 않은 카드의 `?i=` 번째 첨부 + 실제 파일 경로 → (카드, 첨부, 경로).

    `i` 는 `[0-7]` 한 글자만(없으면 0 — 옛 클라이언트 호환), 그 밖은 없는 것과 같다. 경로는 요청
    값이 아니라 **DB 행의 상대경로**를 `ai_card_files.resolve` 로만 푼다. want_file=True 면 파일형
    첨부만(영상 행은 파일이 없다) 돌려준다. 실패는 모두 (None, None, None) — 남의 카드·없는 칸·
    만료·파일 없음을 구분해 알리지 않는다."""
    raw = request.args.get('i')
    if raw is None:
        idx = 0
    elif _INDEX.fullmatch(raw):
        idx = int(raw)
    else:
        return None, None, None
    card = cards.get_alive_card(flask_login.current_user.id, card_id)
    if card is None:
        return None, None, None
    att = cards.attachment_at(card, idx)
    if att is None:
        return None, None, None
    if not want_file:
        return card, att, None
    if att.kind == 'video' or not att.path:
        return None, None, None
    path = card_files.resolve(att.path)
    return (card, att, path) if path else (None, None, None)


def _ext_of(att):
    name = att.name or ''
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


@blueprint.route('/<card_id>/file', methods=['GET'])
@flask_login.login_required
def inbox_file(card_id):
    denied = _guard()
    if denied:
        return denied
    card, att, path = _attachment(card_id)
    if card is None:
        return _not_found()
    ext = _ext_of(att)
    mime = card_files.ALLOWED.get(ext, (None,))[0]
    if mime is None:         # 허용 밖 확장자가 DB 에 있다면(손으로 고친 값) 보내지 않는다
        return _not_found()
    inline = ext in _INLINE_EXTS and request.args.get('download') != '1'
    resp = send_file(path, mimetype=mime, conditional=True, max_age=300)
    resp.headers['Content-Disposition'] = _disposition(
        'inline' if inline else 'attachment', att.name)
    return _harden(resp)


@blueprint.route('/<card_id>/thumb', methods=['GET'])
@flask_login.login_required
def inbox_thumb(card_id):
    """이미지 첨부의 섬네일 또는 영상 첨부의 포스터(둘 다 서버가 다시 인코딩한 JPEG)."""
    denied = _guard()
    if denied:
        return denied
    card, att, _path = _attachment(card_id, want_file=False)
    if card is None or att.kind not in ('image', 'video') or not att.thumb:
        return _not_found()
    thumb = card_files.resolve(att.thumb)
    if thumb is None:
        return _not_found()
    resp = send_file(thumb, mimetype='image/jpeg', conditional=True, max_age=300)
    resp.headers['Content-Disposition'] = 'inline'
    return _harden(resp)


@blueprint.route('/<card_id>/text', methods=['GET'])
@flask_login.login_required
def inbox_text(card_id):
    denied = _guard()
    if denied:
        return denied
    card, att, _path = _attachment(card_id)
    if card is None or _ext_of(att) not in card_files.TEXT_EXTS:
        return _not_found()
    start = max(0, request.args.get('from', 0, type=int) or 0)
    length = request.args.get('len', cards.READ_MAX, type=int) or cards.READ_MAX
    length = max(1, min(length, cards.READ_MAX))
    text, total, stop, _clipped = cards.card_text(card, start, start + length,
                                                  include_body=False, atts=[att])
    resp = jsonify({'text': text, 'total': total, 'from': start, 'more': stop < total})
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


for _view in (inbox_file, inbox_thumb, inbox_text):
    _view.talisman_view_options = {'content_security_policy': _FILE_CSP}


# ── 아티팩트(정적 HTML 카드) ────────────────────────────────────────────────

#: 아티팩트 응답의 CSP. `sandbox`(값 없음) = 모든 샌드박스 제한(불투명 출처·스크립트·폼·
#: 팝업 없음) — 이 헤더가 있어 주소창으로 직접 열어도 같은 출처 권한이 생기지 않는다.
#: 스타일 인라인과 data: 이미지·글꼴만 허용하고 그 밖의 연결·프레임은 모두 막는다.
#: 앱 전체 Talisman 이 after_request 로 CSP 를 덮어쓰므로 뷰별 옵션으로도 같은 값을 건다.
_ARTIFACT_CSP = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                 "font-src data:; script-src 'none'; connect-src 'none'; form-action 'none'; "
                 "base-uri 'none'; frame-src 'none'; frame-ancestors 'self'")


@blueprint.route('/<card_id>/artifact', methods=['GET'])
@flask_login.login_required
def inbox_artifact(card_id):
    """아티팩트 카드의 HTML 을 iframe 에 싣는다(뷰어가 `sandbox=""` 로 연다). kind artifact 만.
    `Sec-Fetch-Dest` 가 있고 iframe 이 아니면(주소창·링크·fetch) 404 — 헤더가 없는 옛 브라우저는
    응답 CSP sandbox 가 막아 준다."""
    denied = _guard()
    if denied:
        return denied
    if request.args.get('i', '0') != '0':           # 아티팩트는 단독이라 position 0 뿐
        return _not_found()
    card, att, path = _attachment(card_id)
    if card is None or att.kind != 'artifact' or _ext_of(att) != 'html':
        return _not_found()
    dest = request.headers.get('Sec-Fetch-Dest')
    if dest is not None and dest.strip().lower() != 'iframe':
        return _not_found()
    try:
        with open(path, 'rb') as fh:             # ≤512 KiB — 검증된 파일을 그대로(변형 없음)
            data = fh.read(card_files.ARTIFACT_MAX_BYTES + 1)
    except OSError:
        return _not_found()
    if len(data) > card_files.ARTIFACT_MAX_BYTES:
        return _not_found()
    # send_file 을 쓰지 않는다 — ETag·Last-Modified·Expires 같은 캐시 검증 헤더를 붙인다.
    resp = Response(data, mimetype='text/html')
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Content-Security-Policy'] = _ARTIFACT_CSP
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    resp.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    resp.headers.pop('Content-Disposition', None)
    return resp


inbox_artifact.talisman_view_options = {'content_security_policy': _ARTIFACT_CSP,
                                        'frame_options': 'SAMEORIGIN'}


# ── 노트로 저장 ─────────────────────────────────────────────────────────────

@blueprint.route('/<card_id>/to-note', methods=['POST'])
@flask_login.login_required
def inbox_to_note(card_id):
    """사용자가 [노트로 저장] 을 눌렀을 때만 — 자동 저장은 없다. 권한은 노트 만들기
    (routes_notes_api.api_notes_create)와 같다: edit_settings + 대상의 write_scope."""
    denied = _guard()
    if denied:
        return denied
    from aot.aot_flask.routes_notes_api import _note_target_denial
    from aot.aot_flask.utils import utils_general
    from aot.utils import audit
    uid = flask_login.current_user.id
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'error': 'permission_denied'}), 403
    card = cards.get_alive_card(uid, card_id)
    if card is None:
        return _not_found()
    body = request.get_json(silent=True) or {}
    target_id = body.get('target_id') if isinstance(body, dict) else None
    target_type = None
    if target_id not in (None, ''):
        if not isinstance(target_id, str) or len(target_id) > 36:
            return jsonify({'error': 'target_denied'}), 403
        if _note_target_denial(target_id, 'create_note'):
            return jsonify({'error': 'target_denied'}), 403
        from aot.aot_flask.geo.device_membership import normalize_facility_note_target
        target_id, target_type = normalize_facility_note_target(target_id.strip(), None)
    else:
        target_id = None
    note_id, already = cards.save_as_note(card, uid, target_id=target_id,
                                          target_type=target_type)
    if note_id is None:
        return jsonify({'error': 'note_failed'}), 500
    if not already:
        audit.audit_log(audit.AI_CARD_TO_NOTE, target_type='AICard',
                        target_id=card.unique_id, target_name=card.source_label,
                        detail=note_id, user_id=uid,
                        username=flask_login.current_user.name)
    out = {'ok': True, 'note_id': note_id}
    if already:
        out['already'] = True
    return jsonify(out)


# ── 공지로 게시 (P2) ────────────────────────────────────────────────────────

@blueprint.route('/<card_id>/to-notice', methods=['POST'])
@flask_login.login_required
def inbox_to_notice(card_id):
    """사용자가 뷰어의 확인 단계에서 [게시] 를 눌렀을 때만 — 자동 게시는 없고 어떤 MCP
    도구도 이 경로를 부르지 않는다. 순서: API 키 403 → edit_settings(공지 만들기와 같은
    권한) 403 → 카드(본인·살아 있음) 404 → 검사 → 게시. POST 라 CSRF 는 그대로 걸린다."""
    denied = _guard()
    if denied:
        return denied
    from aot.aot_flask.utils import utils_general
    from aot.databases.models import User
    from aot.utils import audit
    uid = flask_login.current_user.id
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'error': 'permission_denied'}), 403
    card = cards.get_alive_card(uid, card_id)
    if card is None:
        return _not_found()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'bad_request'}), 400
    user = User.query.filter(User.id == uid).first()
    if user is None:
        return _not_found()
    out = cards.publish_to_notice(card, user, body.get('title'), body.get('body'),
                                  body.get('include_file', False))
    if 'error' in out:
        return jsonify({'error': out['error']}), out['http']
    if not out['already']:
        audit.audit_log(
            audit.AI_CARD_TO_NOTICE, target_type='AICard', target_id=card.unique_id,
            target_name=card.source_label,
            detail='%s · %s%s' % (out['notice_id'], out['title'][:80],
                                      ' (+파일)' if out['with_file'] else ''),
            user_id=uid, username=flask_login.current_user.name)
    resp = {'ok': True, 'notice_id': out['notice_id']}
    if out['already']:
        resp['already'] = True
    return jsonify(resp)
