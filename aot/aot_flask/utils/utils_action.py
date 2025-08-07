# -*- coding: utf-8 -*-
import logging

import sqlalchemy
from flask import current_app

from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.utils.actions import parse_action_information
from aot.utils.actions import which_controller

logger = logging.getLogger(__name__)


def action_add(form):
    """액션 추가."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    action_id = None
    list_unmet_deps = []
    dep_name = ""
    page_refresh = False

    if not current_app.config['TESTING']:
        dep_unmet, _, dep_message = return_dependencies(form.action_type.data)
        if dep_unmet:
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
            messages["error"].append(
                f"{form.action_type.data}에 충족되지 않은 종속성이 있습니다. 액션을 추가하기 전에 반드시 설치되어야 합니다.")
            dep_name = form.action_type.data

            return messages, dep_name, list_unmet_deps, dep_message, None

    dict_actions = parse_action_information()
    controller_type, controller_table, _ = which_controller(form.device_id.data)

    if controller_type not in ['Conditional', 'Trigger', 'Function', 'Input']:
        messages["error"].append(f"잘못된 컨트롤러 유형: {controller_type}")

    if controller_type:
        controller = controller_table.query.filter(
            controller_table.unique_id == form.device_id.data).first()
        try:
            if controller and controller.is_activated:
                messages["error"].append("액션 추가 전에 컨트롤러를 비활성화하세요.")
        except:
            pass  # is_activated doesn't exist

    if form.action_type.data == '':
        messages["error"].append("액션을 선택해야 합니다.")

    try:
        new_action = Actions()
        new_action.function_id = form.device_id.data
        new_action.function_type = form.function_type.data
        new_action.action_type = form.action_type.data

        #
        # Custom Options
        #

        # Generate string to save from custom options
        messages["error"], custom_options = custom_options_return_json(
            messages["error"], dict_actions, device=form.action_type.data, use_defaults=True)
        new_action.custom_options = custom_options

        if not messages["error"]:
            new_action.save()
            action_id = new_action.unique_id
            page_refresh = True
            messages["success"].append(f"{TRANSLATIONS['add']['title']} {TRANSLATIONS['actions']['title']}")

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, dep_name, list_unmet_deps, action_id, page_refresh


def action_mod(form, request_form):
    """액션 수정."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    mod_action = Actions.query.filter(
        Actions.unique_id == form.action_id.data).first()

    if not mod_action:
        messages["error"].append("액션을 찾을 수 없습니다.")
    else:
        # Parse custom options for action
        dict_actions = parse_action_information()
        if mod_action.action_type in dict_actions:
            messages["error"], custom_options = custom_options_return_json(
                messages["error"], dict_actions, request_form, mod_dev=mod_action, device=mod_action.action_type)
            mod_action.custom_options = custom_options

    if not messages["error"]:
        try:
            db.session.commit()
            messages["success"].append(f"{TRANSLATIONS['modify']['title']} {TRANSLATIONS['actions']['title']}")
        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(str(except_msg))
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(str(except_msg))
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    return messages


def action_del(form):
    """액션 삭제."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    controller_type, _, controller_entry = which_controller(form.device_id.data)

    if (controller_type in ['conditional', 'function', 'input'] and  # Note: trigger controller types are not activated
            controller_entry and controller_entry.is_activated):
        messages["error"].append(
            "액션 삭제 전에 조건부 컨트롤러를 비활성화하세요.")

    if not messages["error"]:
        try:
            action_id = Actions.query.filter(
                Actions.unique_id == form.action_id.data).first().unique_id
            delete_entry_with_id(
                Actions, action_id, flash_message=False)
            messages["success"].append(f"{TRANSLATIONS['delete']['title']} {TRANSLATIONS['actions']['title']}")
        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(str(except_msg))
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(str(except_msg))
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    return messages