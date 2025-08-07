# -*- coding: utf-8 -*-
#
# forms_notes.py - Notes Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DateTimeField
from wtforms import FileField
from wtforms import SelectField
from wtforms import SelectMultipleField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import TextAreaField
from wtforms import widgets

from aot.config_translations import TRANSLATIONS


#
# Notes
#

class NoteAdd(FlaskForm):
    name = StringField('이름')
    note_tags = SelectMultipleField('태그')
    files = FileField('첨부 파일')
    enter_custom_date_time = BooleanField('사용자 지정 날짜/시간 사용')
    date_time = DateTimeField('사용자 지정 날짜/시간', format='%Y-%m-%d %H:%M:%S')
    note = TextAreaField('노트')
    note_add = SubmitField('저장')


class NoteOptions(FlaskForm):
    note_unique_id = StringField(widget=widgets.HiddenInput())
    note_mod = SubmitField('수정')
    note_del = SubmitField('삭제')


class NoteMod(FlaskForm):
    note_unique_id = StringField(widget=widgets.HiddenInput())
    file_selected = StringField(widget=widgets.HiddenInput())
    name = StringField('이름')
    note_tags = SelectMultipleField('태그')
    files = FileField('첨부 파일')
    enter_custom_date_time = BooleanField('사용자 지정 날짜/시간 사용')
    date_time = DateTimeField('사용자 지정 날짜/시간', format='%Y-%m-%d %H:%M:%S')
    note = TextAreaField('노트')
    file_del = SubmitField('삭제')
    note_cancel = SubmitField('취소')
    rename_name = StringField()
    file_rename = SubmitField('이름 변경')
    note_del = SubmitField('삭제')
    note_save = SubmitField('저장')


class NotesShow(FlaskForm):
    sort_by_choices = [
        ('id', 'ID'),
        ('name', '이름'),
        ('date', '날짜/시간'),
        ('tag', '태그'),
        ('file', '파일'),
        ('note', '노트')
    ]
    sort_direction_choices = [
        ('desc', '내림차순'),
        ('asc', '오름차순')
    ]
    filter_names = StringField('이름 필터')
    filter_tags = StringField('태그 필터')
    filter_files = StringField('파일 필터')
    filter_notes = StringField('노트 필터')
    sort_by = SelectField('정렬 기준', choices=sort_by_choices)
    sort_direction = SelectField('정렬 방향', choices=sort_direction_choices)
    notes_show = SubmitField('노트 표시')
    notes_export = SubmitField('노트 내보내기')
    notes_import_file = FileField('노트 ZIP 파일')
    notes_import_upload = SubmitField('노트 가져오기')



#
# Tags
#

class TagAdd(FlaskForm):
    tag_name = StringField('태그')
    tag_add = SubmitField('생성')


class TagOptions(FlaskForm):
    tag_unique_id = StringField('태그', widget=widgets.HiddenInput())
    rename = StringField()
    tag_rename = SubmitField('이름 변경')
    tag_del = SubmitField('삭제')
