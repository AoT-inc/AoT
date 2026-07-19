# coding=utf-8
from flask_babel import lazy_gettext

from aot.actions.base_action import AbstractFunctionAction
from aot.config import AOT_DB_PATH
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.databases.utils import session_scope
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.note_factory import create_note_record


ACTION_INFORMATION = {
    'name_unique': 'create_note',
    'name': f"{TRANSLATIONS['create']['title']}: {TRANSLATIONS['note']['title']}",
    'message': lazy_gettext('Create a note with the selected options.'),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'usage': (
        'Executing <strong>self.run_action("ACTION_ID")</strong> will create a note with the configured options. '
        'Executing <strong>self.run_action("ACTION_ID", value={"tags": ["tag1"], "name": "Title", '
        '"note": "body", "category": "alarm", "priority": 1})</strong> will override the stored settings. '
        'Set <strong>auto_target</strong> to link the note automatically to the parent Function.'
    ),

    'custom_options': [
        {
            'id': 'tag',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': ['Tag'],
            'name': lazy_gettext('Tags'),
            'phrase': lazy_gettext('Select one or more tags')
        },
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Name'),
            'phrase': lazy_gettext('Title (if blank, auto-extracted from the first line of the body)')
        },
        {
            'id': 'note',
            'type': 'multiline_text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Note'),
            'phrase': lazy_gettext('Note body')
        },
        {
            'id': 'include_message',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Include action message in body'),
            'phrase': lazy_gettext('Append the message passed by the condition/trigger to the end of the note body')
        },
        {
            'id': 'auto_target',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Auto-link to parent Function'),
            'phrase': lazy_gettext('Automatically link the note to this action\'s parent Function (target_id/target_type)')
        },
        {
            'id': 'category',
            'type': 'select',
            'default_value': 'general',
            'options_select': [
                ('general', lazy_gettext('General')),
                ('observation', lazy_gettext('Observation')),
                ('alarm', lazy_gettext('Alarm')),
                ('maintenance', lazy_gettext('Maintenance')),
            ],
            'name': lazy_gettext('Category'),
            'phrase': lazy_gettext('Note category')
        },
        {
            'id': 'priority',
            'type': 'select',
            'default_value': '0',
            'options_select': [
                ('0', lazy_gettext('Normal')),
                ('1', lazy_gettext('High')),
                ('2', lazy_gettext('Urgent')),
            ],
            'name': lazy_gettext('Priority'),
            'phrase': lazy_gettext('Note priority')
        },
    ]
}


class ActionModule(AbstractFunctionAction):
    """Create a note using all fields of the new Notes model.

    @phase active
    @stability stable
    @dependency AbstractFunctionAction, note_factory
    """
    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.tag = None
        self.name = None
        self.note = None
        self.include_message = None
        self.auto_target = None
        self.category = None
        self.priority = None

        action = db_retrieve_table_daemon(Actions, unique_id=self.unique_id)
        self.setup_custom_options(ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        # -- Extract tags ------------------------------------------
        try:
            list_tags = dict_vars["value"]["tags"]
            use_ids = True
        except (KeyError, TypeError):
            # self.tag is select_multi_measurement -> list of "uuid,..." strings
            raw = self.tag or []
            if isinstance(raw, str):
                raw = [raw] if raw else []
            list_tags = [item.split(',')[0] for item in raw if item]
            use_ids = True

        # -- Title / body ------------------------------------------
        try:
            name = dict_vars["value"]["name"]
        except (KeyError, TypeError):
            name = self.name or ''

        try:
            note_body = dict_vars["value"]["note"]
        except (KeyError, TypeError):
            note_body = self.note or ''

        # -- Category / priority -----------------------------------
        try:
            category = dict_vars["value"]["category"]
        except (KeyError, TypeError):
            category = self.category or 'general'

        try:
            priority = int(dict_vars["value"].get("priority", self.priority or 0))
        except (KeyError, TypeError, ValueError):
            try:
                priority = int(self.priority or 0)
            except (TypeError, ValueError):
                priority = 0

        # -- Attach message ----------------------------------------
        append_text = None
        if self.include_message and dict_vars.get('message'):
            append_text = dict_vars['message']

        # -- Auto-link to parent Function --------------------------
        target_id = None
        target_type = None
        if self.auto_target:
            with session_scope(AOT_DB_PATH) as session:
                action_row = session.query(Actions).filter(
                    Actions.unique_id == self.unique_id).first()
                if action_row and action_row.function_id:
                    target_id = action_row.function_id
                    target_type = action_row.function_type or 'function'

        # -- GPS: fetch coordinates from the parent Function -------
        gps_lat = None
        gps_lng = None
        if target_id:
            try:
                from aot.databases.models import Function, CustomController
                with session_scope(AOT_DB_PATH) as session:
                    fn = session.query(Function).filter(
                        Function.unique_id == target_id).first()
                    if fn and fn.latitude is not None:
                        gps_lat = fn.latitude
                        gps_lng = fn.longitude
                    if gps_lat is None:
                        cc = session.query(CustomController).filter(
                            CustomController.unique_id == target_id).first()
                        if cc and cc.latitude is not None:
                            gps_lat = cc.latitude
                            gps_lng = cc.longitude
            except Exception:
                pass

        # -- Create note -------------------------------------------
        note_uid = create_note_record(
            note_body,
            name=name or None,
            tag_ids=list_tags if use_ids else None,
            tag_names=None if use_ids else list_tags,
            target_id=target_id,
            target_type=target_type,
            category=category,
            priority=priority,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            append_text=append_text,
        )

        if note_uid:
            dict_vars['message'] += f" Note created (id={note_uid[:8]}, category={category}, priority={priority})."
        else:
            dict_vars['message'] += " Note creation failed."

        self.logger.debug(f"Message: {dict_vars['message']}")
        return dict_vars

    def is_setup(self):
        return self.action_setup
