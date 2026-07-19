# coding=utf-8
from aot.utils.time_utils import utc_now

from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class NoticePost(CRUDMixin, db.Model):
    """
    A notice board post. Supports an optional poll, replies, and
    read-acknowledgement tracking. Links/videos/images inside the body are
    auto-detected at render time (see aot-notice-render.js), not stored
    separately. Visibility can be scheduled (publish_at) and time-limited
    (expire_at).

    @phase active
    """
    __tablename__ = "notice_posts"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    date_time = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    title = db.Column(db.Text, default=None)
    body = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default=None)
    files = db.Column(db.Text, default=None)
    category = db.Column(db.String(100), default=None)

    pinned = db.Column(db.Boolean, default=False)
    publish_at = db.Column(db.DateTime, default=None)
    expire_at = db.Column(db.DateTime, default=None)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), default=None)
    author = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoticePoll(CRUDMixin, db.Model):
    """
    A single poll attached to a notice post (single or multiple choice).

    @phase active
    """
    __tablename__ = "notice_polls"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    post_id = db.Column(db.Integer, db.ForeignKey('notice_posts.id'), nullable=False, unique=True, index=True)

    question = db.Column(db.Text, default=None)
    multi = db.Column(db.Boolean, default=False)
    closes_at = db.Column(db.DateTime, default=None)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoticePollOption(CRUDMixin, db.Model):
    """
    A selectable option belonging to a NoticePoll.

    @phase active
    """
    __tablename__ = "notice_poll_options"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    poll_id = db.Column(db.Integer, db.ForeignKey('notice_polls.id'), nullable=False, index=True)

    label = db.Column(db.Text, default=None)
    display_order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoticePollVote(CRUDMixin, db.Model):
    """
    One user's vote for one poll option. Single-choice polls are enforced at the
    application layer (prior votes for the same poll are cleared before insert).

    @phase active
    """
    __tablename__ = "notice_poll_votes"
    __table_args__ = (
        db.UniqueConstraint('option_id', 'user_id', name='uq_notice_poll_vote_option_user'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('notice_polls.id'), nullable=False, index=True)
    option_id = db.Column(db.Integer, db.ForeignKey('notice_poll_options.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    date_time = db.Column(db.DateTime, default=utc_now)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoticeReply(CRUDMixin, db.Model):
    """
    A reply/comment on a notice post.

    @phase active
    """
    __tablename__ = "notice_replies"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    post_id = db.Column(db.Integer, db.ForeignKey('notice_posts.id'), nullable=False, index=True)
    date_time = db.Column(db.DateTime, default=utc_now)

    body = db.Column(db.Text, default=None)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), default=None)
    author = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoticeAck(CRUDMixin, db.Model):
    """
    Tracks which users have acknowledged ("필독 확인") a notice post.

    @phase active
    """
    __tablename__ = "notice_acks"
    __table_args__ = (
        db.UniqueConstraint('post_id', 'user_id', name='uq_notice_ack_post_user'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('notice_posts.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    date_time = db.Column(db.DateTime, default=utc_now)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
