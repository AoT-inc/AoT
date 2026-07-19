# -*- coding: utf-8 -*-
#
# forms_notice.py - Notice board Flask forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DateTimeField
from wtforms import MultipleFileField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import TextAreaField
from wtforms import widgets


#
# Posts
#

class NoticeAdd(FlaskForm):
    title = StringField(lazy_gettext('Title'))
    body = TextAreaField(lazy_gettext('Content'))
    category = StringField(lazy_gettext('Category'))
    files = MultipleFileField(lazy_gettext('Attached Files'))

    publish_now = BooleanField(lazy_gettext('Publish Immediately'), default=True)
    publish_at = DateTimeField(lazy_gettext('Publish At'), format='%Y-%m-%d %H:%M:%S')
    set_expire = BooleanField(lazy_gettext('Set Expiration'))
    expire_at = DateTimeField(lazy_gettext('Expires At'), format='%Y-%m-%d %H:%M:%S')

    pinned = BooleanField(lazy_gettext('Pin to Top'))

    poll_question = StringField(lazy_gettext('Poll Question'))
    poll_multi = BooleanField(lazy_gettext('Allow Multiple Choices'))

    notice_add = SubmitField(lazy_gettext('Post'))


class NoticeMod(FlaskForm):
    notice_unique_id = StringField(widget=widgets.HiddenInput())
    title = StringField(lazy_gettext('Title'))
    body = TextAreaField(lazy_gettext('Content'))
    category = StringField(lazy_gettext('Category'))
    files = MultipleFileField(lazy_gettext('Attached Files'))

    publish_now = BooleanField(lazy_gettext('Publish Immediately'))
    publish_at = DateTimeField(lazy_gettext('Publish At'), format='%Y-%m-%d %H:%M:%S')
    set_expire = BooleanField(lazy_gettext('Set Expiration'))
    expire_at = DateTimeField(lazy_gettext('Expires At'), format='%Y-%m-%d %H:%M:%S')

    pinned = BooleanField(lazy_gettext('Pin to Top'))

    poll_question = StringField(lazy_gettext('Poll Question'))
    poll_multi = BooleanField(lazy_gettext('Allow Multiple Choices'))

    notice_save = SubmitField(lazy_gettext('Save'))


class NoticeOptions(FlaskForm):
    notice_unique_id = StringField(widget=widgets.HiddenInput())
    notice_pin = SubmitField(lazy_gettext('Pin'))
    notice_unpin = SubmitField(lazy_gettext('Unpin'))
    notice_del = SubmitField(lazy_gettext('Delete'))


#
# Replies
#

class NoticeReplyAdd(FlaskForm):
    post_unique_id = StringField(widget=widgets.HiddenInput())
    body = TextAreaField(lazy_gettext('Reply'))
    reply_add = SubmitField(lazy_gettext('Reply'))


class NoticeReplyOptions(FlaskForm):
    reply_unique_id = StringField(widget=widgets.HiddenInput())
    reply_del = SubmitField(lazy_gettext('Delete'))
