# coding=utf-8
"""collection of Notice board endpoints."""
import ipaddress
import logging
import mimetypes
import os
import socket
from functools import lru_cache
from urllib.parse import urlparse

import flask_login
import requests
from bs4 import BeautifulSoup
from flask import (Blueprint, current_app, flash, jsonify, redirect,
                    render_template, request, send_file, url_for)
from flask_babel import gettext
_ = gettext

from aot.config import PATH_NOTICE_ATTACHMENTS
from aot.databases.models import NoticePost
from aot.aot_flask.extensions import csrf
from aot.aot_flask.forms import forms_notice
from aot.aot_flask.utils import utils_general, utils_notice
from aot.utils.time_utils import utc_now

logger = logging.getLogger('aot.aot_flask.routes_notice')

LINK_PREVIEW_USER_AGENT = 'Mozilla/5.0 (compatible; AoTNoticeBot/1.0)'
LINK_PREVIEW_FETCH_TIMEOUT = 5
LINK_PREVIEW_MAX_BYTES = 200_000
LINK_PREVIEW_MAX_REDIRECTS = 3

blueprint = Blueprint('routes_notice',
                       __name__,
                       static_folder='../static',
                       template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_functions():
    return dict(utc_to_local_time=utils_general.utc_to_local_time)


def _visible_posts_query():
    now = utc_now()
    query = NoticePost.query.filter(
        (NoticePost.publish_at.is_(None)) | (NoticePost.publish_at <= now))
    query = query.filter(
        (NoticePost.expire_at.is_(None)) | (NoticePost.expire_at > now))
    return query


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

    query = _visible_posts_query().order_by(
        NoticePost.pinned.desc(), NoticePost.date_time.desc())
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
    if post.publish_at:
        form_notice_mod.publish_at.data = post.publish_at
    form_notice_mod.set_expire.data = post.expire_at is not None
    if post.expire_at:
        form_notice_mod.expire_at.data = post.expire_at
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


@blueprint.route('/notice_attachment/<path:filename>')
@flask_login.login_required
def send_notice_attachment(filename):
    """Return a file from the notice attachment directory."""
    file_path = os.path.join(PATH_NOTICE_ATTACHMENTS, filename)
    if not os.path.exists(file_path):
        return "File not found", 404
    try:
        mime_type, _enc = mimetypes.guess_type(file_path)
        return send_file(file_path, mimetype=mime_type)
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
        'publish_at': utils_general.utc_to_local_time(post.publish_at) if post.publish_at else None,
        'expire_at': utils_general.utc_to_local_time(post.expire_at) if post.expire_at else None,
        'files': post.files.split(',') if post.files else [],
        'poll': None if not poll else {
            'unique_id': poll.unique_id,
            'question': poll.question,
            'multi': poll.multi,
            'closed': bool(poll.closes_at and poll.closes_at <= utc_now()),
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


def _is_public_http_url(url):
    """Reject anything that isn't a plain http(s) URL resolving to a public
    address, to keep the link-preview fetch from being used as an SSRF probe
    against internal services (localhost, Docker/LAN ranges, cloud metadata, etc.)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return False
        for info in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or
                    ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False


def _resolve_safe_redirect_chain(url):
    """Follow redirects with HEAD requests, re-validating each hop against
    _is_public_http_url so a safe URL can't redirect to an internal address.
    Returns the final URL to GET, or None if unsafe/unreachable."""
    for _ in range(LINK_PREVIEW_MAX_REDIRECTS + 1):
        if not _is_public_http_url(url):
            return None
        try:
            resp = requests.head(
                url, timeout=LINK_PREVIEW_FETCH_TIMEOUT, allow_redirects=False,
                headers={'User-Agent': LINK_PREVIEW_USER_AGENT})
        except requests.RequestException:
            return url  # Some servers reject HEAD; try the GET directly.
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get('Location'):
            url = requests.compat.urljoin(url, resp.headers['Location'])
            continue
        return url
    return None


@lru_cache(maxsize=256)
def _fetch_link_preview(url):
    """Fetch and parse Open Graph / basic <title>/<meta> data for a URL.
    Cached for the process lifetime (link content is effectively static for
    preview purposes, and this keeps repeat post views from re-fetching)."""
    safe_url = _resolve_safe_redirect_chain(url)
    if not safe_url:
        return {'error': 'Invalid or unsafe URL'}

    try:
        resp = requests.get(
            safe_url, timeout=LINK_PREVIEW_FETCH_TIMEOUT, stream=True,
            headers={'User-Agent': LINK_PREVIEW_USER_AGENT})
        content = resp.raw.read(LINK_PREVIEW_MAX_BYTES, decode_content=True)
        resp.close()
    except requests.RequestException:
        return {'error': 'Fetch failed'}

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
        'image': image,
        'domain': domain,
    }


@blueprint.route('/notice/api/link_preview', methods=['GET'])
@flask_login.login_required
def api_notice_link_preview():
    url = (request.args.get('url') or '').strip()
    if not url or not _is_public_http_url(url):
        return jsonify({'error': 'Invalid or unsafe URL'}), 400
    return jsonify(_fetch_link_preview(url))


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
