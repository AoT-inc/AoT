# -*- coding: utf-8 -*-
import logging
import os

from flask import flash, request, url_for
from flask_babel import gettext
from flask_login import current_user
from werkzeug.utils import secure_filename

from aot.config import PATH_NOTICE_ATTACHMENTS
from aot.databases import set_uuid
from aot.databases.models import (NoticeAck, NoticePoll,
                                     NoticePollOption, NoticePollVote,
                                     NoticePost, NoticeReply)
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import (delete_entry_with_id,
                                                    flash_success_errors,
                                                    user_has_permission,
                                                    user_is_admin)
from aot.aot_flask.utils.utils_notes import (datetime_time_to_utc,
                                                  process_note_attachment)
from aot.utils.system_pi import assure_path_exists
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

_ = gettext

ALLOWED_ATTACHMENT_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'heic', 'heif',
    'mp4', 'mov', 'webm',
    'pdf', 'txt', 'csv', 'xls', 'xlsx', 'doc', 'docx',
}


#
# Visibility / permission helpers
#

def notice_is_visible(post, now=None):
    """A post is visible once publish_at has passed (or is unset) and before
    expire_at (if set)."""
    now = now or utc_now()
    if post.publish_at and post.publish_at > now:
        return False
    if post.expire_at and post.expire_at <= now:
        return False
    return True


def notice_category_list():
    """Distinct category labels currently in use, for autocomplete suggestions
    on the compose form and the widget's category-filter checkbox list."""
    rows = db.session.query(NoticePost.category).filter(
        NoticePost.category.isnot(None), NoticePost.category != '').distinct().order_by(NoticePost.category).all()
    return [r[0] for r in rows]


def can_manage_post(post):
    """Admin can manage any post. The author can manage their own post if they
    still hold write permission."""
    if user_is_admin():
        return True
    if (current_user.is_authenticated and post.user_id == current_user.id and
            user_has_permission('edit_settings', silent=True)):
        return True
    return False


#
# Attachments
#

def _save_notice_attachment(file_storage, post_unique_id):
    filename = secure_filename(file_storage.filename)
    if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in ALLOWED_ATTACHMENT_EXTENSIONS:
        return None
    assure_path_exists(PATH_NOTICE_ATTACHMENTS)
    # Reuse the Notes attachment pipeline (HEIC->JPG, resize >1920px, animated GIF passthrough).
    saved_filename = process_note_attachment(file_storage, post_unique_id)
    # process_note_attachment saves under PATH_NOTE_ATTACHMENTS; move it into the notice folder.
    from aot.config import PATH_NOTE_ATTACHMENTS
    src = os.path.join(PATH_NOTE_ATTACHMENTS, saved_filename)
    dst = os.path.join(PATH_NOTICE_ATTACHMENTS, saved_filename)
    if os.path.isfile(src):
        os.replace(src, dst)
    return saved_filename


#
# Poll
#

def _save_poll(post_id):
    question = (request.form.get('poll_question') or '').strip()
    if not question:
        return
    options = [o.strip() for o in request.form.getlist('poll_option') if o.strip()]
    if len(options) < 2:
        return
    poll = NoticePoll(
        post_id=post_id, question=question,
        multi=bool(request.form.get('poll_multi')))
    db.session.add(poll)
    db.session.flush()
    for i, label in enumerate(options):
        db.session.add(NoticePollOption(poll_id=poll.id, label=label, display_order=i))


def _replace_poll(post):
    existing = NoticePoll.query.filter_by(post_id=post.id).first()
    if existing:
        NoticePollVote.query.filter_by(poll_id=existing.id).delete()
        NoticePollOption.query.filter_by(poll_id=existing.id).delete()
        db.session.delete(existing)
        db.session.flush()
    _save_poll(post.id)


#
# Posts
#

def notice_add(form):
    """Create a post. Returns (errors, post) — post is None if errors is non-empty.
    Also flashes + is consumed by the classic page route (which ignores the
    return value); the return value exists so the widget's JSON API can reuse
    this same logic without duplicating it."""
    error = []

    if not form.title.data and not form.body.data:
        error.append(_("Title or content must be present"))

    new_post = NoticePost()
    new_post.unique_id = set_uuid()
    new_post.user_id = current_user.id if current_user.is_authenticated else None
    new_post.title = (form.title.data or '').strip() or _("Untitled")
    new_post.body = (form.body.data or '').strip()
    new_post.category = (form.category.data or '').strip() or None

    if not form.publish_now.data and form.publish_at.data:
        try:
            new_post.publish_at = datetime_time_to_utc(form.publish_at.data)
        except Exception as msg:
            error.append(_("Error parsing publish date/time: %(msg)s", msg=msg))

    if form.set_expire.data and form.expire_at.data:
        try:
            new_post.expire_at = datetime_time_to_utc(form.expire_at.data)
        except Exception as msg:
            error.append(_("Error parsing expiration date/time: %(msg)s", msg=msg))

    if form.pinned.data and user_is_admin():
        new_post.pinned = True

    if form.files.data:
        filename_list = []
        for each_file in form.files.data:
            if not hasattr(each_file, 'filename') or not each_file.filename:
                continue
            saved = _save_notice_attachment(each_file, new_post.unique_id)
            if saved:
                filename_list.append(saved)
        if filename_list:
            new_post.files = ",".join(filename_list)

    if not error:
        db.session.add(new_post)
        db.session.flush()
        _save_poll(new_post.id)
        db.session.commit()

    flash_success_errors(error, _("Post Notice"), url_for('routes_notice.page_notice'))
    return error, (new_post if not error else None)


def notice_mod(form):
    """Update a post. Returns (errors, post) — see notice_add()'s docstring."""
    error = []

    post = NoticePost.query.filter(NoticePost.unique_id == form.notice_unique_id.data).first()
    if not post:
        error.append(_("Notice not found"))
        flash_success_errors(error, _("Edit Notice"), url_for('routes_notice.page_notice'))
        return error, None

    if not can_manage_post(post):
        error = [_("Insufficient permission to edit this notice")]
        flash(error[0], "error")
        return error, None

    if not form.title.data and not form.body.data:
        error.append(_("Title or content must be present"))

    post.title = (form.title.data or '').strip() or _("Untitled")
    post.body = (form.body.data or '').strip()
    post.category = (form.category.data or '').strip() or None

    if form.publish_now.data:
        post.publish_at = None
    elif form.publish_at.data:
        try:
            post.publish_at = datetime_time_to_utc(form.publish_at.data)
        except Exception as msg:
            error.append(_("Error parsing publish date/time: %(msg)s", msg=msg))

    if not form.set_expire.data:
        post.expire_at = None
    elif form.expire_at.data:
        try:
            post.expire_at = datetime_time_to_utc(form.expire_at.data)
        except Exception as msg:
            error.append(_("Error parsing expiration date/time: %(msg)s", msg=msg))

    if user_is_admin():
        post.pinned = bool(form.pinned.data)

    deleted_files_str = request.form.get('deleted_files', '')
    if deleted_files_str:
        deleted_list = [f for f in deleted_files_str.split(',') if f]
        current_files = post.files.split(',') if post.files else []
        remaining = []
        for f in current_files:
            if f in deleted_list:
                file_path = os.path.join(PATH_NOTICE_ATTACHMENTS, f)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error("Failed to delete notice attachment %s: %s", file_path, e)
            else:
                remaining.append(f)
        post.files = ",".join(remaining) if remaining else None

    if form.files.data:
        filename_list = post.files.split(",") if post.files else []
        for each_file in form.files.data:
            if not hasattr(each_file, 'filename') or not each_file.filename:
                continue
            saved = _save_notice_attachment(each_file, post.unique_id)
            if saved:
                filename_list.append(saved)
        if filename_list:
            post.files = ",".join(filename_list)

    if not error:
        _replace_poll(post)
        db.session.commit()

    flash_success_errors(error, _("Edit Notice"), url_for('routes_notice.page_notice_detail', unique_id=post.unique_id))
    return error, (post if not error else None)


def notice_del(unique_id):
    """Delete a post. Returns errors (empty list on success)."""
    error = []
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        error.append(_("Notice not found"))
    elif not can_manage_post(post):
        error.append(_("Insufficient permission to delete this notice"))

    if not error:
        if post.files:
            for f in post.files.split(','):
                file_path = os.path.join(PATH_NOTICE_ATTACHMENTS, f)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error("Failed to delete notice attachment %s: %s", file_path, e)

        poll = NoticePoll.query.filter_by(post_id=post.id).first()
        if poll:
            NoticePollVote.query.filter_by(poll_id=poll.id).delete()
            NoticePollOption.query.filter_by(poll_id=poll.id).delete()
        NoticePoll.query.filter_by(post_id=post.id).delete()
        NoticeReply.query.filter_by(post_id=post.id).delete()
        NoticeAck.query.filter_by(post_id=post.id).delete()
        delete_entry_with_id(NoticePost, unique_id, flash_message=False)

    flash_success_errors(error, _("Delete Notice"), url_for('routes_notice.page_notice'))
    return error


def notice_pin(unique_id, pinned):
    if not user_is_admin():
        flash(_("Insufficient permission"), "error")
        return
    post = NoticePost.query.filter(NoticePost.unique_id == unique_id).first()
    if not post:
        flash(_("Notice not found"), "error")
        return
    post.pinned = bool(pinned)
    db.session.commit()


#
# Poll voting
#

def notice_vote(post, option_unique_ids):
    """Record the current user's vote(s) for this post's poll.
    Enforces single-choice by clearing prior votes before inserting new ones.
    """
    poll = NoticePoll.query.filter_by(post_id=post.id).first()
    if not poll:
        return False, _("This notice has no poll")
    if poll.closes_at and poll.closes_at <= utc_now():
        return False, _("This poll is closed")

    options = NoticePollOption.query.filter_by(poll_id=poll.id).all()
    valid_ids = {o.unique_id: o.id for o in options}
    selected = [valid_ids[u] for u in option_unique_ids if u in valid_ids]
    if not poll.multi:
        selected = selected[:1]
    if not selected:
        return False, _("No valid option selected")

    NoticePollVote.query.filter_by(poll_id=poll.id, user_id=current_user.id).delete()
    for option_id in selected:
        db.session.add(NoticePollVote(poll_id=poll.id, option_id=option_id, user_id=current_user.id))
    db.session.commit()
    return True, None


def notice_poll_results(post):
    """Return (poll, [{option, count}], user_selected_option_ids, total_voters)."""
    poll = NoticePoll.query.filter_by(post_id=post.id).first()
    if not poll:
        return None, [], set(), 0

    options = NoticePollOption.query.filter_by(poll_id=poll.id).order_by(NoticePollOption.display_order).all()
    results = []
    voter_ids = set()
    for option in options:
        votes = NoticePollVote.query.filter_by(option_id=option.id).all()
        for v in votes:
            voter_ids.add(v.user_id)
        results.append({'option': option, 'count': len(votes)})

    user_selected = set()
    if current_user.is_authenticated:
        my_votes = NoticePollVote.query.filter_by(poll_id=poll.id, user_id=current_user.id).all()
        user_selected = {v.option_id for v in my_votes}

    return poll, results, user_selected, len(voter_ids)


#
# Replies
#

def notice_reply_add(form):
    error = []
    post = NoticePost.query.filter(NoticePost.unique_id == form.post_unique_id.data).first()
    if not post:
        error.append(_("Notice not found"))
    elif not form.body.data or not form.body.data.strip():
        error.append(_("Reply cannot be empty"))

    if not error:
        reply = NoticeReply(
            post_id=post.id,
            unique_id=set_uuid(),
            body=form.body.data.strip(),
            user_id=current_user.id if current_user.is_authenticated else None)
        db.session.add(reply)
        db.session.commit()

    flash_success_errors(
        error, _("Add Reply"),
        url_for('routes_notice.page_notice_detail', unique_id=form.post_unique_id.data))


def notice_reply_del(form):
    reply = NoticeReply.query.filter(NoticeReply.unique_id == form.reply_unique_id.data).first()
    if not reply:
        flash(_("Reply not found"), "error")
        return
    post = NoticePost.query.filter(NoticePost.id == reply.post_id).first()
    is_own = current_user.is_authenticated and reply.user_id == current_user.id
    if not (user_is_admin() or is_own):
        flash(_("Insufficient permission to delete this reply"), "error")
        return
    db.session.delete(reply)
    db.session.commit()


#
# Read acknowledgement ("필독 확인")
#

def notice_ack_add(post):
    if not current_user.is_authenticated:
        return False
    existing = NoticeAck.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if existing:
        return True
    db.session.add(NoticeAck(post_id=post.id, user_id=current_user.id))
    db.session.commit()
    return True


def notice_ack_status(post):
    """Return (has_acked, ack_count)."""
    ack_count = NoticeAck.query.filter_by(post_id=post.id).count()
    has_acked = False
    if current_user.is_authenticated:
        has_acked = NoticeAck.query.filter_by(post_id=post.id, user_id=current_user.id).first() is not None
    return has_acked, ack_count
