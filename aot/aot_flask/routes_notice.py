# coding=utf-8
"""collection of Notice board endpoints."""
import logging
import mimetypes
import os
import threading
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import flask_login
from bs4 import BeautifulSoup
from flask import (Blueprint, current_app, flash, jsonify, redirect,
                    render_template, request, send_file, url_for)
from flask_babel import gettext
from sqlalchemy import or_
_ = gettext

from aot.config import PATH_NOTICE_ATTACHMENTS
from aot.databases.models import NoticePost
from aot.aot_flask.extensions import csrf
from aot.aot_flask.forms import forms_notice
from aot.aot_flask.utils import utils_general, utils_notice
from aot.aot_flask.utils.utils_notes import utc_to_wall, utc_to_wall_str
from aot.utils.timekit import naive_utc, utc_now

logger = logging.getLogger('aot.aot_flask.routes_notice')

LINK_PREVIEW_TOTAL_SECONDS = 8
LINK_PREVIEW_MAX_BYTES = 200_000

blueprint = Blueprint('routes_notice',
                       __name__,
                       static_folder='../static',
                       template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_functions():
    return dict(utc_to_local_time=utils_general.utc_to_local_time)


# @manual Notices#list
def _visible_posts_query():
    now = utc_now()
    query = NoticePost.query.filter(
        (NoticePost.publish_at.is_(None)) | (NoticePost.publish_at <= now))
    query = query.filter(
        (NoticePost.expire_at.is_(None)) | (NoticePost.expire_at > now))
    return query


# @manual Notices#list
@blueprint.route('/notice', methods=('GET', 'POST'))
@flask_login.login_required
def page_notice():
    """Notice board: list + create."""
    form_notice_add = forms_notice.NoticeAdd()
    form_notice_options = forms_notice.NoticeOptions()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_notice.page_notice'))

        if form_notice_add.notice_add.data:
            utils_notice.notice_add(form_notice_add)
        elif form_notice_options.notice_pin.data:
            utils_notice.notice_pin(form_notice_options.notice_unique_id.data, True)
        elif form_notice_options.notice_unpin.data:
            utils_notice.notice_pin(form_notice_options.notice_unique_id.data, False)
        elif form_notice_options.notice_del.data:
            utils_notice.notice_del(form_notice_options.notice_unique_id.data)

        return redirect(url_for('routes_notice.page_notice'))

    page = request.args.get('page', 1, type=int)
    per_page = 15

    # 검색어 하나로 좁힌다(2026-09-11 사용자 지시: 제목 아래에 검색창) —
    # /notes·/plots 와 같은 방식. 제목·본문·분류를 한 번에 훑는다. 검색이
    # 없으면 목록 전부(기존 동작 그대로).
    q = (request.args.get('q') or '').strip()

    query = _visible_posts_query()
    if q:
        like = '%{0}%'.format(q)
        query = query.filter(or_(
            NoticePost.title.ilike(like),
            NoticePost.body.ilike(like),
            NoticePost.category.ilike(like),
        ))
    query = query.order_by(NoticePost.pinned.desc(), NoticePost.date_time.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    posts_info = []
    for post in pagination.items:
        _, ack_count = utils_notice.notice_ack_status(post)
        posts_info.append({
            'post': post,
            'ack_count': ack_count,
            'has_poll': post.id in [
                p.post_id for p in
                utils_notice.NoticePoll.query.filter_by(post_id=post.id).all()],
            'reply_count': utils_notice.NoticeReply.query.filter_by(post_id=post.id).count(),
        })

    return render_template('tools/notice.html',
                            posts_info=posts_info,
                            form_notice_add=form_notice_add,
                            form_notice_options=form_notice_options,
                            pagination=pagination,
                            page=page,
                            q=q,
                            category_list=utils_notice.notice_category_list(),
                            can_create=utils_general.user_has_permission('edit_settings', silent=True),
                            is_admin=utils_general.user_is_admin())


@blueprint.route('/notice/<unique_id>', methods=('GET',))
@flask_login.login_required
def page_notice_detail(unique_id):
    """View a single notice post: content (links auto-detected in the body),
    poll, replies, ack."""
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        flash(_("Notice not found"), "error")
        return redirect(url_for('routes_notice.page_notice'))

    replies = utils_notice.NoticeReply.query.filter_by(
        post_id=post.id).order_by(utils_notice.NoticeReply.date_time.asc()).all()
    poll, poll_results, user_selected, voter_count = utils_notice.notice_poll_results(post)
    has_acked, ack_count = utils_notice.notice_ack_status(post)

    form_reply_add = forms_notice.NoticeReplyAdd()
    form_reply_add.post_unique_id.data = post.unique_id
    form_reply_options = forms_notice.NoticeReplyOptions()

    return render_template('tools/notice_detail.html',
                            post=post,
                            replies=replies,
                            poll=poll,
                            poll_results=poll_results,
                            user_selected=user_selected,
                            voter_count=voter_count,
                            has_acked=has_acked,
                            ack_count=ack_count,
                            form_reply_add=form_reply_add,
                            form_reply_options=form_reply_options,
                            can_manage=utils_notice.can_manage_post(post),
                            is_admin=utils_general.user_is_admin())


@blueprint.route('/notice/<unique_id>/edit', methods=('GET', 'POST'))
@flask_login.login_required
def page_notice_edit(unique_id):
    """Edit an existing notice post."""
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        flash(_("Notice not found"), "error")
        return redirect(url_for('routes_notice.page_notice'))

    if not utils_notice.can_manage_post(post):
        flash(_("Insufficient permission to edit this notice"), "error")
        return redirect(url_for('routes_notice.page_notice_detail', unique_id=unique_id))

    form_notice_mod = forms_notice.NoticeMod()

    if request.method == 'POST':
        if form_notice_mod.notice_save.data:
            utils_notice.notice_mod(form_notice_mod)
            return redirect(url_for('routes_notice.page_notice_detail', unique_id=unique_id))
        return redirect(url_for('routes_notice.page_notice_edit', unique_id=unique_id))

    form_notice_mod.notice_unique_id.data = post.unique_id
    form_notice_mod.title.data = post.title
    form_notice_mod.body.data = post.body
    form_notice_mod.category.data = post.category
    form_notice_mod.publish_now.data = post.publish_at is None
    # 저장(utils_notice → datetime_time_to_utc)이 해석하는 시간대의 벽시계로
    # 채운다 — UTC 원값을 채우면 저장할 때마다 오프셋만큼 밀린다.
    if post.publish_at:
        form_notice_mod.publish_at.data = utc_to_wall(post.publish_at)
    form_notice_mod.set_expire.data = post.expire_at is not None
    if post.expire_at:
        form_notice_mod.expire_at.data = utc_to_wall(post.expire_at)
    form_notice_mod.pinned.data = post.pinned

    poll = utils_notice.NoticePoll.query.filter_by(post_id=post.id).first()
    poll_options = []
    if poll:
        poll_options = utils_notice.NoticePollOption.query.filter_by(
            poll_id=poll.id).order_by(utils_notice.NoticePollOption.display_order).all()

    return render_template('tools/notice_edit.html',
                            post=post,
                            form_notice_mod=form_notice_mod,
                            poll=poll,
                            poll_options=poll_options,
                            category_list=utils_notice.notice_category_list(),
                            is_admin=utils_general.user_is_admin())


#: 공지 첨부로 서빙하지 않는 능동 콘텐츠 — 올릴 수 없는 형식이지만(허용 목록 밖) 혹시 폴더에
#: 들어와 있어도 화면에 그리지 않고 내려받게만 한다.
_ACTIVE_ATTACHMENT_EXTS = frozenset({'html', 'htm', 'xhtml', 'svg', 'xml', 'js', 'mjs'})


@blueprint.route('/notice_attachment/<path:filename>')
@flask_login.login_required
def send_notice_attachment(filename):
    """Return a file from the notice attachment directory.

    P2 보강: 요청 값을 그대로 이어 붙이지 않고 realpath 로 풀어 첨부 폴더 **안의 파일**
    인지(commonpath) 확인한다 — `..`·절대경로·심볼릭 링크로 폴더 밖을 가리키면 404.
    응답에는 nosniff 를 건다(확장자로 정한 MIME 을 브라우저가 바꾸지 못하게)."""
    root = os.path.realpath(PATH_NOTICE_ATTACHMENTS)
    try:
        file_path = os.path.realpath(os.path.join(root, filename))
        inside = os.path.commonpath([file_path, root]) == root
        is_file = inside and file_path != root and os.path.isfile(file_path)
    except ValueError:                 # NUL 문자 등
        is_file = False
    if not is_file:
        return "File not found", 404
    try:
        mime_type, _enc = mimetypes.guess_type(file_path)
        ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
        resp = send_file(file_path, mimetype=mime_type,
                         as_attachment=ext in _ACTIVE_ATTACHMENT_EXTS)
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        return resp
    except Exception:
        logger.exception("Send notice attachment failed")
        return "Internal error", 500


#
# JSON API (used by both the notice detail page and the dashboard widget)
#

@blueprint.route('/notice/api/latest', methods=['GET'])
@flask_login.login_required
def api_notice_latest():
    """Compact list for the dashboard widget: title + timestamp only.
    Full content (body, poll, replies, ack) is fetched on demand via
    api_notice_detail() when the user opens a post."""
    limit = request.args.get('limit', 5, type=int)
    limit = max(1, min(limit, 20))
    categories = [c for c in (request.args.get('categories') or '').split(',') if c]

    query = _visible_posts_query()
    if categories:
        query = query.filter(NoticePost.category.in_(categories))
    posts = query.order_by(
        NoticePost.pinned.desc(), NoticePost.date_time.desc()).limit(limit).all()

    result = [{
        'unique_id': post.unique_id,
        'title': post.title,
        'date_time': utils_general.utc_to_local_time(post.date_time),
        'pinned': post.pinned,
        'category': post.category,
    } for post in posts]

    return jsonify({'posts': result})


@blueprint.route('/notice/api/<unique_id>', methods=['GET'])
@flask_login.login_required
def api_notice_detail(unique_id):
    """Full post content (body, poll, replies, ack) for the widget's modal popup."""
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        return jsonify({'error': 'Notice not found'}), 404

    replies = utils_notice.NoticeReply.query.filter_by(
        post_id=post.id).order_by(utils_notice.NoticeReply.date_time.asc()).all()
    poll, poll_results, user_selected, voter_count = utils_notice.notice_poll_results(post)
    has_acked, ack_count = utils_notice.notice_ack_status(post)

    return jsonify({
        'unique_id': post.unique_id,
        'title': post.title,
        'body': post.body,
        'category': post.category,
        'date_time': utils_general.utc_to_local_time(post.date_time),
        'author': post.author.name if post.author else '?',
        'pinned': post.pinned,
        'has_acked': has_acked,
        'ack_count': ack_count,
        'can_manage': utils_notice.can_manage_post(post),
        # 편집 칸을 채우는 값 — 라벨 없는 벽시계, 저장이 읽는 시계와 같은 시계.
        'publish_at': utc_to_wall_str(post.publish_at) if post.publish_at else None,
        'expire_at': utc_to_wall_str(post.expire_at) if post.expire_at else None,
        'files': post.files.split(',') if post.files else [],
        'poll': None if not poll else {
            'unique_id': poll.unique_id,
            'question': poll.question,
            'multi': poll.multi,
            'closed': bool(poll.closes_at and poll.closes_at <= naive_utc()),
            'voter_count': voter_count,
            'options': [{
                'unique_id': r['option'].unique_id,
                'label': r['option'].label,
                'count': r['count'],
                'selected': r['option'].id in user_selected,
            } for r in poll_results],
        },
        'replies': [{
            'unique_id': reply.unique_id,
            'body': reply.body,
            'author': reply.author.name if reply.author else '?',
            'date_time': utils_general.utc_to_local_time(reply.date_time),
            'user_id': reply.user_id,
        } for reply in replies],
    })


@blueprint.route('/notice/api/create', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_create():
    """Create a post from the dashboard widget's compose modal (multipart form,
    same field names/handling as the classic page form — reuses notice_add())."""
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'error': 'Permission denied'}), 403

    form = forms_notice.NoticeAdd()
    errors, post = utils_notice.notice_add(form)
    if errors:
        return jsonify({'error': '; '.join(errors)}), 400
    return jsonify({'ok': True, 'unique_id': post.unique_id})


@blueprint.route('/notice/api/<unique_id>/edit', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_edit(unique_id):
    """Update a post from the dashboard widget's compose modal (reuses notice_mod())."""
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        return jsonify({'error': 'Notice not found'}), 404
    if not utils_notice.can_manage_post(post):
        return jsonify({'error': 'Permission denied'}), 403

    form = forms_notice.NoticeMod()
    form.notice_unique_id.data = unique_id  # trust the URL, not a client-supplied hidden field
    errors, updated_post = utils_notice.notice_mod(form)
    if errors:
        return jsonify({'error': '; '.join(errors)}), 400
    return jsonify({'ok': True, 'unique_id': updated_post.unique_id})


@blueprint.route('/notice/api/<unique_id>/delete', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_delete(unique_id):
    """Delete a post from the dashboard widget (reuses notice_del())."""
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        return jsonify({'error': 'Notice not found'}), 404
    if not utils_notice.can_manage_post(post):
        return jsonify({'error': 'Permission denied'}), 403

    errors = utils_notice.notice_del(unique_id)
    if errors:
        return jsonify({'error': '; '.join(errors)}), 400
    return jsonify({'ok': True})


#: 미리보기 실패는 이유를 가리지 않고 이 한 가지로만 답한다(차단·연결 실패·시간 초과를 구분하면
#: 내부망 존재를 알아내는 오라클이 된다). 상태 코드도 항상 200 이다.
_PREVIEW_UNAVAILABLE = {'error': 'Preview unavailable'}
#: 동시에 외부로 나가는 미리보기 수 — 공지 한 장에 링크가 많아도 웹 스레드를 다 쥐지 못하게 한다.
_PREVIEW_SLOTS = threading.BoundedSemaphore(3)


class _PreviewUnavailable(Exception):
    pass


def _fetch_link_preview(url):
    """링크 미리보기(제목·설명·og:image). 성공한 것만 캐시하고, 실패는 일반 응답을 돌려준다."""
    try:
        return _cached_link_preview(url)
    except _PreviewUnavailable:
        return dict(_PREVIEW_UNAVAILABLE)


@lru_cache(maxsize=256)
def _cached_link_preview(url):
    """Open Graph / <title> / <meta> 를 가져와 파싱한다. 실패는 예외라 캐시되지 않는다.

    SSRF 방어는 전부 aot.utils.ai_card_fetch.fetch_public 이 한다(https 만, 해석된 모든 주소가 공인,
    검증한 IP 로 직접 연결해 리바인딩 차단, 리다이렉트는 수동 3회·홉마다 재검증, 프록시 환경변수
    무시, 크기·총 시간 상한). 여기서 requests 를 쓰지 않는다."""
    from aot.utils import ai_card_fetch
    if not _PREVIEW_SLOTS.acquire(blocking=False):
        raise _PreviewUnavailable()
    try:
        content, safe_url = ai_card_fetch.fetch_public(
            url, LINK_PREVIEW_MAX_BYTES, truncate=True, total_s=LINK_PREVIEW_TOTAL_SECONDS)
    except ai_card_fetch.FetchError:
        raise _PreviewUnavailable() from None
    finally:
        _PREVIEW_SLOTS.release()

    title = description = image = None
    try:
        soup = BeautifulSoup(content, 'html.parser')

        def meta(*names):
            for name in names:
                tag = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
                if tag and tag.get('content'):
                    return tag['content'].strip()
            return None

        title = meta('og:title', 'twitter:title')
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        description = meta('og:description', 'twitter:description', 'description')
        image = meta('og:image', 'twitter:image')
    except Exception:
        logger.exception("Link preview HTML parse failed for %s", url)

    domain = urlparse(url).netloc
    return {
        'title': (title or domain)[:200],
        'description': (description or '')[:300] or None,
        'image': _safe_preview_image(safe_url, image),
        'domain': domain,
    }


_fetch_link_preview.cache_clear = _cached_link_preview.cache_clear     # 테스트·운영 도구 호환

#: og:image 로 받아 줄 수 없는 글자 — 따옴표·꺾쇠·공백이 있으면 화면의 <img src="…"> 속성을
#: 벗어날 수 있다(2026-10-19 P2 보안 리뷰: 남의 페이지 og:image 가 공지 화면에 onerror 를 심음).
_PREVIEW_IMAGE_BAD = frozenset('"\'<>`\\ \t\r\n\f\v')


def _safe_preview_image(page_url, image):
    """og:image 값을 페이지 주소 기준 절대 http(s) 주소로 바꾼다. 그 밖의 모양·위험 글자는 None."""
    if not image or not isinstance(image, str):
        return None
    try:
        absolute = urljoin(page_url, image.strip())
        parsed = urlparse(absolute)
    except Exception:
        return None
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or len(absolute) > 2048:
        return None
    if any(ch in _PREVIEW_IMAGE_BAD for ch in absolute):
        return None
    return absolute


@blueprint.route('/notice/api/link_preview', methods=['GET'])
@flask_login.login_required
def api_notice_link_preview():
    url = (request.args.get('url') or '').strip()
    if not url:
        return jsonify(dict(_PREVIEW_UNAVAILABLE))
    return jsonify(_fetch_link_preview(url))


# @manual Notices#poll
@blueprint.route('/notice/api/<unique_id>/vote', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_vote(unique_id):
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        return jsonify({'error': 'Notice not found'}), 404

    data = request.get_json(silent=True) or {}
    option_ids = data.get('option_ids') or []
    if not isinstance(option_ids, list):
        return jsonify({'error': 'option_ids must be a list'}), 400

    ok, err = utils_notice.notice_vote(post, option_ids)
    if not ok:
        return jsonify({'error': err}), 400

    _, results, user_selected, voter_count = utils_notice.notice_poll_results(post)
    return jsonify({
        'ok': True,
        'voter_count': voter_count,
        'options': [{
            'unique_id': r['option'].unique_id,
            'label': r['option'].label,
            'count': r['count'],
            'selected': r['option'].id in user_selected,
        } for r in results],
    })


# @manual Notices#acknowledge
@blueprint.route('/notice/api/<unique_id>/ack', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_ack(unique_id):
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        return jsonify({'error': 'Notice not found'}), 404
    utils_notice.notice_ack_add(post)
    _, ack_count = utils_notice.notice_ack_status(post)
    return jsonify({'ok': True, 'ack_count': ack_count})


# @manual Notices#replies
@blueprint.route('/notice/api/<unique_id>/reply', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_reply(unique_id):
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        return jsonify({'error': 'Notice not found'}), 404

    data = request.get_json(silent=True) or {}
    body = (data.get('body') or '').strip()
    if not body:
        return jsonify({'error': 'Reply cannot be empty'}), 400

    reply = utils_notice.NoticeReply(
        post_id=post.id, unique_id=utils_notice.set_uuid(), body=body,
        user_id=flask_login.current_user.id)
    utils_notice.db.session.add(reply)
    utils_notice.db.session.commit()

    return jsonify({
        'ok': True,
        'reply': {
            'unique_id': reply.unique_id,
            'body': reply.body,
            'author': flask_login.current_user.name,
            'date_time': utils_general.utc_to_local_time(reply.date_time),
        },
    })


# @manual Notices#replies
@blueprint.route('/notice/api/reply/<reply_unique_id>/delete', methods=['POST'])
@flask_login.login_required
@csrf.exempt
def api_notice_reply_delete(reply_unique_id):
    reply = utils_notice.NoticeReply.query.filter(
        utils_notice.NoticeReply.unique_id == reply_unique_id).first()
    if not reply:
        return jsonify({'error': 'Reply not found'}), 404

    is_own = flask_login.current_user.is_authenticated and reply.user_id == flask_login.current_user.id
    if not (utils_general.user_is_admin() or is_own):
        return jsonify({'error': 'Permission denied'}), 403

    utils_notice.db.session.delete(reply)
    utils_notice.db.session.commit()
    return jsonify({'ok': True})
