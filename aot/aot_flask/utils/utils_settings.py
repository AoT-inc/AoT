# -*- coding: utf-8 -*-
import logging
import os
import re
import stat
import subprocess
import threading
import time
import traceback
from tempfile import NamedTemporaryFile

import bcrypt
import flask_login
import sqlalchemy
from flask import flash
from flask import redirect
from flask import session
from flask import url_for
from flask_babel import gettext
from sqlalchemy import and_
from sqlalchemy import or_

from aot.config import DAEMON_LOG_FILE
from aot.config import DEPENDENCY_INIT_FILE
from aot.config import DEPENDENCY_LOG_FILE
from aot.config import INSTALL_DIRECTORY
from aot.config import LANGUAGES
from aot.config import SQL_DATABASE_AOT
from aot.config import PATH_ACTIONS_CUSTOM
from aot.config import PATH_FUNCTIONS_CUSTOM
from aot.config import PATH_INPUTS_CUSTOM
from aot.config import PATH_OUTPUTS_CUSTOM
from aot.config import PATH_TEMPLATE_USER
from aot.config import PATH_WIDGETS_CUSTOM
from aot.config import UPGRADE_INIT_FILE
from aot.config_devices_units import MEASUREMENTS
from aot.config_devices_units import UNITS
from aot.config_translations import TRANSLATIONS
from aot.databases import set_api_key
from aot.utils import audit
from aot.utils.audit import audit_log
from aot.databases.models import AIGlobalSettings
from aot.databases.models import APIKey, Actions
from aot.databases.models import AIEntry
from aot.databases.models import Conditional
from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.databases.models import Dashboard
from aot.databases.models import DeviceMeasurements
from aot.databases.models import DisplayOrder
from aot.databases.models import Input, InputChannel
from aot.databases.models import Measurement
from aot.databases.models import Misc
from aot.databases.models import NoteTags
from aot.databases.models import Notes
from aot.databases.models import Output
from aot.databases.models import OutputChannel
from aot.databases.models import PID
from aot.databases.models import Role
from aot.databases.models import SMTP
from aot.databases.models import Unit
from aot.databases.models import User
from aot.databases.models import Widget
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.routes_static import invalidate_misc_cache
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils.utils_general import choices_measurements
from aot.aot_flask.utils.utils_general import choices_units
from aot.aot_flask.utils.utils_general import controller_activate_deactivate
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import flash_form_errors
from aot.aot_flask.utils.utils_general import flash_success_errors
from aot.utils.actions import parse_action_information
from aot.utils.database import db_retrieve_table
from aot.utils.functions import parse_function_information
from aot.utils.inputs import parse_input_information
from aot.utils.layouts import update_layout
from aot.utils.modules import load_module_from_file
from aot.utils.service_control import (reload_frontend, restart_daemon,
                                       restart_frontend)
from aot.utils.outputs import parse_output_information
from aot.utils.send_data import send_email
from aot.utils.system_pi import all_conversions
from aot.utils.system_pi import assure_path_exists
from aot.utils.system_pi import base64_encode_bytes
from aot.utils.system_pi import cmd_output
from aot.utils.system_pi import set_user_grp
from aot.utils.utils import test_password
from aot.utils.utils import test_username
from aot.utils.widget_generate_html import generate_widget_html
from aot.utils.widgets import parse_widget_information

logger = logging.getLogger(__name__)

#
# User manipulation
#

def user_roles(form):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    page_refresh = False

    if not messages["error"]:
        if form.user_role_add.data:
            new_role = Role()
            new_role.name = form.name.data
            new_role.view_logs = form.view_logs.data
            new_role.view_camera = form.view_camera.data
            new_role.view_stats = form.view_stats.data
            new_role.view_settings = form.view_settings.data
            new_role.edit_users = form.edit_users.data
            new_role.edit_settings = form.edit_settings.data
            new_role.edit_controllers = form.edit_controllers.data
            new_role.edit_plots = form.edit_plots.data
            new_role.reset_password = form.reset_password.data
            try:
                new_role.save()
                page_refresh = True
                messages["success"].append('{action} {controller}'.format(
                    action=TRANSLATIONS['add']['title'],
                    controller=gettext("User Role")))
            except sqlalchemy.exc.OperationalError as except_msg:
                messages["error"].append(except_msg)
            except sqlalchemy.exc.IntegrityError as except_msg:
                messages["error"].append(except_msg)
        elif form.user_role_save.data:
            mod_role = Role.query.filter(
                Role.unique_id == form.role_id.data).first()
            mod_role.view_logs = form.view_logs.data
            mod_role.view_camera = form.view_camera.data
            mod_role.view_stats = form.view_stats.data
            mod_role.view_settings = form.view_settings.data
            mod_role.edit_users = form.edit_users.data
            mod_role.edit_settings = form.edit_settings.data
            mod_role.edit_controllers = form.edit_controllers.data
            mod_role.edit_plots = form.edit_plots.data
            mod_role.reset_password = form.reset_password.data
            db.session.commit()
            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['modify']['title'],
                controller=gettext("User Role")))
        elif form.user_role_delete.data:
            user = User().query.filter(User.role_id == form.role_id.data)
            role = Role().query.filter(Role.unique_id == form.role_id.data).first()
            if role.id == 1:
                messages["error"].append("Cannot delete role: Admin role is protected")
            if user.count():
                messages["error"].append(
                    "Cannot delete role if it is assigned to a user. "
                    "Change the user to another role and try again.")
            else:
                delete_entry_with_id(Role, form.role_id.data)
                messages["success"].append('{action} {controller}'.format(
                    action=TRANSLATIONS['delete']['title'],
                    controller=gettext("User Role")))

    return messages, page_refresh


def user(form):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    misc = Misc.query.first()
    misc.default_login_page = form.default_login_page.data

    if not messages["error"]:
        try:
            db.session.commit()
            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['save']['title'],
                controller=TRANSLATIONS['user']['title']))
        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(except_msg)
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(except_msg)

    return messages


def user_add(form):
    action = '{action} {controller} {user}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['user']['title'],
        user=form.user_name.data.lower())
    error = []

    if form.validate():
        new_user = User()
        new_user.name = form.user_name.data.lower()
        if not test_username(new_user.name):
            error.append(gettext(
                "Invalid user name. Must be between 2 and 64 characters "
                "and only contain letters and numbers."))

        new_user.full_name = (form.full_name.data or '').strip() or None
        new_user.email = form.email.data
        if User.query.filter_by(email=new_user.email).count():
            error.append(gettext(
                "Another user already has that email address."))

        if not test_password(form.password_new.data):
            error.append(gettext(
                "Invalid password. Must be at least 8 characters, contain "
                "only letters, numbers, and symbols, and not be a commonly "
                "used password."))

        if form.password_new.data != form.password_repeat.data:
            error.append(gettext("Passwords do not match. Please try again."))

        if form.code.data:
            try:
                code_int = int(form.code.data)
                if len(str(code_int)) < 4:
                    error.append("Keypad code must be a numerical value of 4 or more digits")
                new_user.code = code_int
            except:
                error.append("Keypad code must be a numerical value of 4 or more digits")

        if not error:
            new_user.set_password(form.password_new.data)
            role = Role.query.filter(
                Role.name == form.addRole.data).first()
            new_user.role_id = role.id
            new_user.theme = form.theme.data
            try:
                new_user.save()
                audit_log(audit.USER_CREATE, target_type='User',
                          target_id=new_user.unique_id,
                          target_name=new_user.name,
                          after={'name': new_user.name,
                                 'email': new_user.email,
                                 'role_id': new_user.role_id})
            except sqlalchemy.exc.OperationalError as except_msg:
                error.append(except_msg)
            except sqlalchemy.exc.IntegrityError as except_msg:
                error.append(except_msg)

        flash_success_errors(
            error, action, url_for('routes_settings.settings_users'))
    else:
        flash_form_errors(form)


def generate_api_key(form):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    api_key = None

    try:
        mod_user = User.query.filter(
            User.unique_id == form.user_id.data).first()
        # 키를 **추가** 발급한다. 예전에는 users.api_key_hash 컬럼 하나에
        # 덮어썼기 때문에, 같은 사람이 두 번째 클라이언트를 붙이려고 발급하면
        # 첫 번째 연동이 아무 에러 없이 죽었다(p6_32).
        key_name = getattr(getattr(form, 'api_key_name', None), 'data', None)
        key_scope = getattr(getattr(form, 'api_key_scope', None), 'data', None)
        api_key = mod_user.issue_api_key(key_name, key_scope)
        db.session.commit()
        # The key itself is never written to the audit trail — only the fact
        # that one was issued, for whom, under what name, and with what scope.
        # 스코프는 특히 남겨야 한다 — "읽기 전용으로 줬다" 는 나중에 물어볼 일이
        # 생기는 사실이고, 키 행이 폐기돼도 이 기록은 남는다.
        audit_log(audit.API_KEY_ISSUE, target_type='User',
                  target_id=mod_user.unique_id, target_name=mod_user.name,
                  detail='{} [{}]'.format(
                      (key_name or '').strip()[:64] or '-',
                      key_scope or 'full'))
        messages["success"].append(gettext(
            "API key generated. Copy it now — it is shown only once and "
            "cannot be retrieved later."))
    except Exception as except_msg:
        # 저장이 실패했으면 키를 돌려주지 않는다. 화면에 보이는 키는 반드시 DB 에
        # 남은 키여야 한다 — 그렇지 않으면 사용자는 "발급했는데 인증이 안 된다" 를
        # 겪고, 원인이 발급 실패였다는 사실은 어디에도 드러나지 않는다.
        # 사용자 조회 단계에서 실패한 경우(api_key 가 아직 None)는 더 나빴다:
        # 아래 base64_encode_bytes(None) 이 TypeError 를 내며 이 try 밖으로
        # 튀어나가, 깔끔한 오류 메시지 대신 500 이 나갔다.
        # commit 이 실패한 세션은 rollback 하기 전까지 이후 쿼리를 전부 거부하므로
        # 같은 요청의 뒷단이 연쇄로 실패하지 않도록 여기서 되돌린다.
        db.session.rollback()
        api_key = None
        messages["error"].append(except_msg)

    return messages, base64_encode_bytes(api_key) if api_key else None


def revoke_api_key(form):
    """API 키 하나를 폐기한다(행은 남는다).

    키 단위로 끊을 수 있어야 하는 이유는, 예전처럼 사람 단위로만 끊으면 유출이
    의심되는 연동 하나 때문에 그 사람의 **모든** 연동을 끊어야 하기 때문이다.
    """
    from aot.databases.models import UserAPIKey

    messages = {"success": [], "info": [], "warning": [], "error": []}
    try:
        row = UserAPIKey.query.filter(
            UserAPIKey.unique_id == form.api_key_id.data).first()
        if row is None:
            messages["error"].append(gettext("API key not found."))
            return messages

        mod_user = User.query.filter(User.id == row.user_id).first()
        row.revoke()
        db.session.commit()
        audit_log(audit.API_KEY_REVOKE, target_type='User',
                  target_id=mod_user.unique_id if mod_user else None,
                  target_name=mod_user.name if mod_user else None,
                  detail=row.name or None)
        messages["success"].append(gettext("API key revoked."))
    except Exception as except_msg:
        db.session.rollback()
        messages["error"].append(except_msg)

    return messages


def change_preferences(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['theme']['title'])
    error = []

    try:
        mod_user = User.query.filter(
            User.id == flask_login.current_user.id).first()
        mod_user.theme = form.theme.data
        mod_user.language = form.language.data
        # Personal display timezone (IANA). Store only a valid zone; blank or
        # invalid → None (fall back to system default). (timezone-management.md §7)
        if hasattr(form, 'timezone'):
            tz_val = (form.timezone.data or '').strip()
            if tz_val:
                try:
                    import pytz
                    pytz.timezone(tz_val)
                    mod_user.timezone = tz_val
                except Exception:
                    pass  # invalid zone — leave unchanged
            else:
                mod_user.timezone = None
        db.session.commit()
        # 세션 로케일도 동기화: <html lang> 표기·JS 번역 카탈로그 캐시(Vary: Cookie)가
        # DB 변경만으로는 갱신되지 않아, 선언 lang 과 콘텐츠 언어가 어긋나면서
        # 브라우저 자동번역 팝업이 뜨는 문제를 방지한다.
        if form.language.data in LANGUAGES:
            session['language'] = form.language.data
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_users'))


def account_self_update(form):
    """Self-service update of the logged-in user's own name/email/password/
    language (nav-bar 'User Settings' modal). No role/permission fields —
    those stay admin-only in Settings > Users (see user_mod() below). All
    fields are validated up front; nothing is written unless every changed
    field passes."""
    error = []
    logout = False

    try:
        user = User.query.filter(
            User.id == flask_login.current_user.id).first()

        new_name = (form.name.data or '').strip().lower()
        rename = new_name and new_name != user.name
        if rename:
            if not test_username(new_name):
                error.append(gettext(
                    "Invalid username. Must be between 3 and 64 characters "
                    "and only contain letters and numbers."))
            elif User.query.filter(User.name == new_name, User.id != user.id).count():
                error.append(gettext("That username is already taken."))

        new_email = (form.email.data or '').strip()
        change_email = new_email and new_email != user.email
        if change_email and User.query.filter(
                User.email == new_email, User.id != user.id).count():
            error.append(gettext("Another user already has that email address."))

        change_password = bool(form.password_new.data)
        if change_password:
            if not test_password(form.password_new.data):
                error.append(gettext("Invalid password"))
            elif form.password_new.data != form.password_repeat.data:
                error.append(gettext(
                    "Passwords do not match. Please try again."))

        if not error:
            if rename:
                user.name = new_name
            if change_email:
                user.email = new_email
            if change_password:
                user.set_password(form.password_new.data)
                # Force re-login so the session is confirmed against the new
                # password rather than continuing to ride the old one.
                logout = True
            if form.language.data in LANGUAGES or not form.language.data:
                user.language = form.language.data or None
                # "Browser Default" 를 고르면 세션 키를 **지운다**. None 을 넣어
                # 두면 get_locale() 이 `session.get("language") and ...` 로 걸러
                # 내긴 하지만, 세션에 죽은 키가 남아 다음에 읽는 코드가 "언어가
                # 설정돼 있다" 로 오해할 여지를 남긴다.
                if user.language:
                    session['language'] = user.language
                else:
                    session.pop('language', None)
            # 사용자 지정 이름을 UI 언어로 번역해 보여줄지. 체크박스라 두 상태만
            # 오지만, 저장하는 순간 NULL(미지정)이 명시값이 된다.
            # (docs/design/user-string-live-translation.md)
            #
            # 전역 기능이 꺼져 있으면 모달에 이 칸이 없어 폼에도 값이 실리지
            # 않는다 — 그때 False 로 덮으면 나중에 전역을 켰을 때 사용자가
            # 끈 적도 없이 꺼진 채로 남으므로, 그 경우는 손대지 않는다.
            if hasattr(form, 'translate_user_strings'):
                try:
                    from aot.ai.services.user_string_translator import is_enabled
                    if is_enabled():
                        user.translate_user_strings = bool(
                            form.translate_user_strings.data)
                except Exception:
                    pass

            # Personal display timezone (IANA). Valid zone stored; blank/invalid
            # → None (system default). (timezone-management.md §7)
            if hasattr(form, 'timezone'):
                tz_val = (form.timezone.data or '').strip()
                if tz_val:
                    try:
                        import pytz
                        pytz.timezone(tz_val)
                        user.timezone = tz_val
                    except Exception:
                        pass
                else:
                    user.timezone = None
            db.session.commit()
    except Exception as except_msg:
        error.append(except_msg)

    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['user']['title'])
    flash_success_errors(error, action, url_for('routes_general.home'))

    return logout


def user_mod(form):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    logout = False

    try:
        mod_user = User.query.filter(
            User.unique_id == form.user_id.data).first()
        # Captured before any mutation so the audit entry can show the change.
        previous_role_id = mod_user.role_id
        previous_email = mod_user.email
        password_changed = bool(form.password_new.data)
        mod_user.email = form.email.data
        mod_user.full_name = (form.full_name.data or '').strip() or None

        if form.code.data == "0":
            mod_user.code = None
        elif form.code.data:
            try:
                code_int = int(form.code.data)
                if len(str(code_int)) < 4:
                    messages["error"].append("Keypad code must be a numerical value of 4 or more digits")
                mod_user.code = code_int
            except:
                messages["error"].append("Keypad code must be a numerical value of 4 or more digits")

        # Only change the password if it's entered in the form
        if form.password_new.data != '':
            if not utils_general.user_has_permission('reset_password'):
                messages["error"].append("Cannot change user password")
            if not test_password(form.password_new.data):
                messages["error"].append(gettext("Invalid password"))
            if form.password_new.data != form.password_repeat.data:
                messages["error"].append(gettext(
                    "Passwords do not match. Please try again."))
            mod_user.password_hash = bcrypt.hashpw(
                form.password_new.data.encode('utf-8'),
                bcrypt.gensalt())
            if flask_login.current_user.id == form.user_id.data:
                logout = True

        current_user_name = User.query.filter(
            User.unique_id == form.user_id.data).first().name
        if (mod_user.role_id == 1 and
                mod_user.role_id != form.role_id.data and
                flask_login.current_user.name == current_user_name):
            messages["error"].append(
                "Cannot change currently-logged in user's role from Admin")

        # 계정 사용 여부. 자기 자신을 끄면 다음 요청에서 로그아웃되고, 마지막
        # 관리자를 끄면 아무도 설정에 들어올 수 없게 되므로 둘 다 막는다.
        # (권한 강등에 이미 같은 성격의 가드가 있다 — 아래 last Admin 검사)
        previous_enabled = mod_user.is_enabled
        if not form.is_enabled.data:
            if flask_login.current_user.unique_id == form.user_id.data:
                messages["error"].append(gettext(
                    "Cannot disable the currently logged-in account."))
            elif mod_user.role_id == 1:
                active_admins = User.query.filter(
                    User.role_id == 1, User.is_enabled.is_(True)).count()
                if active_admins <= 1:
                    messages["error"].append(gettext(
                        "Cannot disable the last Administrator."))

        if not messages["error"]:
            # [Security] Prevent demoting the last Admin
            if mod_user.role_id == 1 and form.role_id.data != 1:
                admin_count = User.query.filter_by(role_id=1).count()
                if admin_count <= 1:
                     messages["error"].append(gettext("Cannot demote the last Administrator."))
                     return messages, logout

            mod_user.role_id = form.role_id.data
            mod_user.is_enabled = bool(form.is_enabled.data)
            mod_user.theme = form.theme.data
            db.session.commit()
            # Role changes are the security-relevant part here — record the
            # role transition explicitly rather than dumping the whole row
            # (which would put the password hash in the audit trail).
            audit_log(audit.USER_MODIFY, target_type='User',
                      target_id=mod_user.unique_id, target_name=mod_user.name,
                      before={'role_id': previous_role_id,
                              'email': previous_email,
                              'is_enabled': previous_enabled},
                      after={'role_id': mod_user.role_id,
                             'email': mod_user.email,
                             'is_enabled': mod_user.is_enabled},
                      detail='password changed' if password_changed else None)
            messages["success"].append('{action} {controller} {user}'.format(
                action=TRANSLATIONS['modify']['title'],
                controller=TRANSLATIONS['user']['title'],
                user=mod_user.name))
    except Exception as except_msg:
        messages["error"].append(except_msg)

    return messages, logout


def user_approve(form):
    """Approve a pending Google-signup account (see routes_authentication.py
    login_google_callback), allowing it to log in."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        user = User.query.filter(
            User.unique_id == form.user_id.data).first()
        if user is None:
            messages["error"].append(gettext("User not found"))
        elif user.is_approved:
            messages["info"].append(gettext(
                "%(user)s is already approved", user=user.name))
        else:
            user.is_approved = True
            db.session.commit()
            messages["success"].append(gettext(
                "Approved %(user)s", user=user.name))
    except Exception as except_msg:
        messages["error"].append(except_msg)

    return messages


def user_del(form):
    """Delete user from SQL database"""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if form.user_id.data == flask_login.current_user.id:
        messages["error"].append("Cannot delete the currently-logged in user")

    if not messages["error"]:
        try:
            user = User.query.filter(
                User.unique_id == form.user_id.data).first()
            
            # [Security] Prevent deleting the last Admin
            if user.role_id == 1:
                admin_count = User.query.filter_by(role_id=1).count()
                if admin_count <= 1:
                    messages["error"].append(gettext("Cannot delete the last Administrator."))
                    return messages

            deleted_name = user.name
            deleted_uid = user.unique_id
            deleted_role = user.role_id
            user.delete()
            audit_log(audit.USER_DELETE, target_type='User',
                      target_id=deleted_uid, target_name=deleted_name,
                      before={'name': deleted_name, 'role_id': deleted_role})
            messages["success"].append('{action} {controller} {user}'.format(
                action=TRANSLATIONS['delete']['title'],
                controller=TRANSLATIONS['user']['title'],
                user=deleted_name))
        except Exception as except_msg:
            messages["error"].append(except_msg)

    return messages


#
# API Key Management
#

def api_key_add(form):
    messages = {
        "success": [], "info": [], "warning": [], "error": []
    }
    if form.validate():
        new_key = APIKey()
        new_key.name = form.name.data
        new_key.provider = form.provider.data
        new_key.key = form.key.data
        new_key.url = form.url.data
        new_key.tag = form.tag.data
        new_key.description = form.description.data
        try:
            new_key.save()
            messages["success"].append(_("API Key '{}' has been added.").format(new_key.name))
        except Exception as e:
            messages["error"].append(str(e))
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages["error"].append(f"{getattr(form, field).label.text}: {error}")
    return messages


def api_key_mod(form):
    messages = {
        "success": [], "info": [], "warning": [], "error": []
    }
    try:
        mod_key = APIKey.query.filter(APIKey.unique_id == form.api_key_id.data).first()
        if mod_key:
            mod_key.name = form.name.data
            mod_key.provider = form.provider.data
            mod_key.key = form.key.data
            mod_key.url = form.url.data
            mod_key.tag = form.tag.data
            mod_key.description = form.description.data
            db.session.commit()
            messages["success"].append(_("API Key '{}' has been modified.").format(mod_key.name))
        else:
            messages["error"].append(_("Could not find the API key to modify."))
    except Exception as e:
        messages["error"].append(str(e))
    return messages


def api_key_del(form):
    messages = {
        "success": [], "info": [], "warning": [], "error": []
    }
    try:
        key_to_del = APIKey.query.filter(APIKey.unique_id == form.api_key_id.data).first()
        if key_to_del:
            name = key_to_del.name
            key_to_del.delete()
            messages["success"].append(_("API Key '{}' has been deleted.").format(name))
        else:
            messages["error"].append(_("Could not find the API key to delete."))
    except Exception as e:
        messages["error"].append(str(e))
    return messages


def auto_register_api_key(value, name, provider, tag=None, url=None, description=None):
    """
    Automatically register an API key if it doesn't already exist.
    """
    try:
        # Check if key already exists (search by value)
        existing = APIKey.query.filter_by(key=value).first()
        if existing:
            return False
            
        new_key = APIKey()
        new_key.name = name
        new_key.provider = provider
        new_key.key = value
        new_key.tag = tag
        new_key.url = url
        new_key.description = description or f"Automatically registered from {provider}"
        new_key.save()
        return True
    except Exception as e:
        logger.error(f"Failed to auto-register API key: {e}")
        return False



def get_api_key_usage(api_key_val):
    """
    Search for API key usage across various modules options.
    Returns a list of dictionaries with usage details.
    """
    if not api_key_val:
        return []

    usage = []

    # 1. Inputs
    for item in Input.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            usage.append({'type': 'Input', 'name': item.name, 'id': item.unique_id})

    # 2. Outputs
    for item in Output.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            usage.append({'type': 'Output', 'name': item.name, 'id': item.unique_id})

    # 3. Output Channels
    for item in OutputChannel.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            parent = Output.query.filter(Output.unique_id == item.output_id).first()
            p_name = parent.name if parent else "Unknown Output"
            usage.append({'type': 'Channel', 'name': f"{p_name} - {item.name}", 'id': item.unique_id})

    # 4. Custom Controllers (Functions)
    for item in CustomController.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            usage.append({'type': 'Function', 'name': item.name, 'id': item.unique_id})

    # 5. Actions
    for item in Actions.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            usage.append({'type': 'Action', 'name': f"Action ({item.action_type})", 'id': item.unique_id})

    # 6. Input Channels
    for item in InputChannel.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            parent = Input.query.filter(Input.unique_id == item.input_id).first()
            p_name = parent.name if parent else "Unknown Input"
            usage.append({'type': 'Input Channel', 'name': f"{p_name} - {item.name}", 'id': item.unique_id})

    # 7. Conditionals
    for item in Conditional.query.all():
        if item.custom_options and api_key_val in item.custom_options:
            usage.append({'type': 'Conditional', 'name': item.name, 'id': item.unique_id})

    # 8. AI Entries
    try:
        for item in AIEntry.query.all():
            if item.api_key and api_key_val in item.api_key:
                usage.append({'type': 'AI', 'name': item.name, 'id': item.unique_id})
    except Exception:
        pass

    return usage


#
# Settings modifications
#


def settings_general_mod(form):
    """Modify General settings."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if form.validate():
        if (form.output_usage_report_span.data == 'monthly' and
                not 0 < form.output_usage_report_day.data < 29):
            messages["error"].append("Day Options: Daily: 1-7 (1=Monday), Monthly: 1-28")
        elif (form.output_usage_report_span.data == 'weekly' and
                not 0 < form.output_usage_report_day.data < 8):
            messages["error"].append("Day Options: Daily: 1-7 (1=Monday), Monthly: 1-28")

        if not messages["error"]:
            try:
                reload_frontend = False
                mod_misc = Misc.query.first()

                # Security-relevant settings are recorded individually rather
                # than dumping the whole Misc row (which holds credentials).
                _audit_before = {
                    'force_https': mod_misc.force_https,
                    'hostname_override': mod_misc.hostname_override,
                }

                if mod_misc.force_https != form.force_https.data:
                    mod_misc.force_https = form.force_https.data
                    reload_frontend = True

                mod_misc.rpyc_timeout = form.rpyc_timeout.data
                mod_misc.daemon_debug_mode = form.daemon_debug_mode.data
                mod_misc.hide_alert_success = form.hide_success.data
                mod_misc.hide_alert_info = form.hide_info.data
                mod_misc.hide_alert_warning = form.hide_warning.data
                mod_misc.hide_tooltips = form.hide_tooltips.data

                mod_misc.sample_rate_controller_conditional = form.sample_rate_controller_conditional.data
                mod_misc.sample_rate_controller_function = form.sample_rate_controller_function.data
                mod_misc.sample_rate_controller_input = form.sample_rate_controller_input.data
                mod_misc.sample_rate_controller_output = form.sample_rate_controller_output.data
                mod_misc.sample_rate_controller_pid = form.sample_rate_controller_pid.data
                mod_misc.sample_rate_controller_widget = form.sample_rate_controller_widget.data

                if form.use_database.data == "influxdb_1":
                    mod_misc.measurement_db_name = "influxdb"
                    mod_misc.measurement_db_version = "1"
                elif form.use_database.data == "influxdb_2":
                    mod_misc.measurement_db_name = "influxdb"
                    mod_misc.measurement_db_version = "2"

                mod_misc.measurement_db_retention_policy = form.measurement_db_retention_policy.data
                mod_misc.measurement_db_host = form.measurement_db_host.data
                mod_misc.measurement_db_port = form.measurement_db_port.data
                mod_misc.measurement_db_dbname = form.measurement_db_dbname.data
                if form.measurement_db_user.data:
                    mod_misc.measurement_db_user = form.measurement_db_user.data
                if (form.measurement_db_password.data and
                        form.measurement_db_password.data.strip() != '' and
                        form.measurement_db_password.data != mod_misc.measurement_db_password):
                    mod_misc.measurement_db_password = form.measurement_db_password.data

                mod_misc.grid_cell_height = form.grid_cell_height.data
                mod_misc.max_amps = form.max_amps.data
                mod_misc.output_usage_volts = form.output_stats_volts.data
                mod_misc.output_usage_cost = form.output_stats_cost.data
                mod_misc.output_usage_currency = form.output_stats_currency.data
                mod_misc.output_usage_dayofmonth = form.output_stats_day_month.data
                mod_misc.output_usage_report_gen = form.output_usage_report_gen.data
                mod_misc.output_usage_report_span = form.output_usage_report_span.data
                mod_misc.output_usage_report_day = form.output_usage_report_day.data
                mod_misc.output_usage_report_hour = form.output_usage_report_hour.data
                mod_misc.stats_opt_out = form.stats_opt_out.data
                mod_misc.enable_upgrade_check = form.enable_upgrade_check.data
                mod_misc.net_test_ip = form.net_test_ip.data
                mod_misc.net_test_port = form.net_test_port.data
                mod_misc.net_test_timeout = form.net_test_timeout.data

                mod_ai_settings = AIGlobalSettings.query.first()
                if mod_ai_settings is None:
                    mod_ai_settings = AIGlobalSettings()
                    db.session.add(mod_ai_settings)
                mod_ai_settings.ai_enabled = form.ai_enabled.data
                mod_ai_settings.mcp_http_enabled = form.mcp_http_enabled.data
                mod_ai_settings.user_string_translation_enabled = \
                    form.user_string_translation_enabled.data

                mod_user = User.query.filter(
                    User.id == flask_login.current_user.id).first()
                mod_user.landing_page = form.landing_page.data
                mod_user.index_page = form.index_page.data
                mod_user.language = form.language.data

                db.session.commit()
                audit_log(audit.SETTINGS_CHANGE, target_type='Misc',
                          target_name='General Settings',
                          before=_audit_before,
                          after={'force_https': mod_misc.force_https,
                                 'hostname_override': mod_misc.hostname_override})
                invalidate_misc_cache()
                control = DaemonControl()
                control.refresh_daemon_misc_settings()
                messages["success"].append('{action} {controller}'.format(
                    action=TRANSLATIONS['modify']['title'],
                    controller=gettext("General Settings")))

                if reload_frontend:
                    # Reload web server
                    logger.info("Reloading frontend in 10 seconds")
                    reload_frontend(delay_sec=10, logger=logger)

            except Exception as except_msg:
                messages["error"].append(except_msg)
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages["error"].append(
                    gettext("Error in the %(field)s field - %(err)s",
                        field=getattr(form, field).label.text,
                        err=error))

    return messages


def settings_map_mod(form):
    """Modify common map location settings."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if not form.validate():
        for field, errors in form.errors.items():
            for error in errors:
                messages["error"].append(
                    gettext("Error in the %(field)s field - %(err)s",
                            field=getattr(form, field).label.text,
                            err=error))
        return messages

    lat = form.map_latitude.data
    lng = form.map_longitude.data
    label = form.map_location_label.data

    # Require both or neither
    if (lat is None) ^ (lng is None):
        messages["error"].append(gettext("Enter both latitude and longitude, or leave both empty."))
        return messages

    try:
        mod_misc = Misc.query.first()
        if mod_misc is None:
            messages["error"].append(gettext("Misc settings row not found"))
            return messages

        mod_misc.map_latitude = lat
        mod_misc.map_longitude = lng
        mod_misc.map_location_label = label or ''

        db.session.commit()
        messages["success"].append(gettext("Default map location has been saved."))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def settings_diagnostic_mod(form):
    """
    Placeholder for diagnostic settings handler.
    Currently no diagnostic settings are persisted, so just validate and return.
    """
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if not form.validate():
        for field, errors in form.errors.items():
            for error in errors:
                messages["error"].append(
                    gettext("Error in the %(field)s field - %(err)s",
                            field=getattr(form, field).label.text,
                            err=error))
        return messages

    # Regenerate widget HTML (settings/diagnostic button)
    if getattr(form, "regenerate_widget_html", None) and form.regenerate_widget_html.data:
        try:
            settings_regenerate_widget_html()
            flash(gettext("Widget HTML regeneration started."), "success")
        except Exception as exc:
            logger.exception("Error while regenerating widget HTML")
            flash(gettext("Failed to regenerate widget HTML: %(err)s", err=exc), "error")
        return messages

    # Dispatch each button to its handler (one action per submit)
    if getattr(form, "delete_dashboard_elements", None) and form.delete_dashboard_elements.data:
        settings_diagnostic_delete_dashboard_elements()
        return messages
    if getattr(form, "delete_inputs", None) and form.delete_inputs.data:
        settings_diagnostic_delete_inputs()
        return messages
    if getattr(form, "delete_notes_tags", None) and form.delete_notes_tags.data:
        settings_diagnostic_delete_notes_tags()
        return messages
    if getattr(form, "delete_outputs", None) and form.delete_outputs.data:
        settings_diagnostic_delete_outputs()
        return messages
    if getattr(form, "delete_functions", None) and form.delete_functions.data:
        settings_diagnostic_delete_functions()
        return messages
    if getattr(form, "delete_settings_database", None) and form.delete_settings_database.data:
        settings_diagnostic_delete_settings_database()
        return messages
    if getattr(form, "delete_file_dependency", None) and form.delete_file_dependency.data:
        settings_diagnostic_delete_file('dependency')
        return messages
    if getattr(form, "delete_file_upgrade", None) and form.delete_file_upgrade.data:
        settings_diagnostic_delete_file('upgrade')
        return messages
    if getattr(form, "recreate_influxdb_db_1", None) and form.recreate_influxdb_db_1.data:
        settings_diagnostic_recreate_influxdb_db_1()
        return messages
    if getattr(form, "recreate_influxdb_db_2", None) and form.recreate_influxdb_db_2.data:
        settings_diagnostic_recreate_influxdb_db_2()
        return messages
    if getattr(form, "reset_email_counter", None) and form.reset_email_counter.data:
        settings_diagnostic_reset_email_counter()
        return messages
    if getattr(form, "install_dependencies", None) and form.install_dependencies.data:
        settings_diagnostic_install_dependencies()
        return messages
    if getattr(form, "upgrade_master", None) and form.upgrade_master.data:
        settings_diagnostic_upgrade_master()
        return messages

    messages["info"].append(gettext("No diagnostic settings to save."))
    return messages


def settings_function_import(form):
    """
    Receive a function module file, check it for errors, add it to AoT controller list
    """
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['controller']['title'])
    error = []

    controller_info = None

    try:
        install_dir = os.path.abspath(INSTALL_DIRECTORY)
        tmp_directory = os.path.join(install_dir, 'aot/functions/tmp_functions')
        assure_path_exists(tmp_directory)
        assure_path_exists(PATH_FUNCTIONS_CUSTOM)
        tmp_name = 'tmp_function_testing.py'
        full_path_tmp = os.path.join(tmp_directory, tmp_name)

        if not form.import_controller_file.data:
            error.append('No file present')
        elif form.import_controller_file.data.filename == '':
            error.append('No file name')
        else:
            form.import_controller_file.data.save(full_path_tmp)

        try:
            controller_info, status = load_module_from_file(full_path_tmp, 'functions')
            if not controller_info or not hasattr(controller_info, 'FUNCTION_INFORMATION'):
                error.append("Could not load FUNCTION_INFORMATION dictionary from "
                             "the uploaded controller module")
        except Exception:
            error.append("Could not load uploaded file as a python module:\n"
                         "{}".format(traceback.format_exc()))

        dict_controllers = parse_function_information()
        list_controllers = []
        for each_key in dict_controllers.keys():
            list_controllers.append(each_key.lower())

        if not error:
            if 'function_name_unique' not in controller_info.FUNCTION_INFORMATION:
                error.append(
                    "'function_name_unique' not found in "
                    "FUNCTION_INFORMATION dictionary")
            elif controller_info.FUNCTION_INFORMATION['function_name_unique'] == '':
                error.append("'function_name_unique' is empty")
            elif controller_info.FUNCTION_INFORMATION['function_name_unique'].lower() in list_controllers:
                error.append(
                    "'function_name_unique' is not unique, there "
                    "is already an controller with that name ({})".format(
                        controller_info.FUNCTION_INFORMATION['function_name_unique'].lower()))

            if 'function_name' not in controller_info.FUNCTION_INFORMATION:
                error.append("'function_name' not found in FUNCTION_INFORMATION dictionary")
            elif controller_info.FUNCTION_INFORMATION['function_name'] == '':
                error.append("'function_name' is empty")

            if 'dependencies_module' in controller_info.FUNCTION_INFORMATION:
                if not isinstance(controller_info.FUNCTION_INFORMATION['dependencies_module'], list):
                    error.append("'dependencies_module' must be a list of tuples")
                else:
                    for each_dep in controller_info.FUNCTION_INFORMATION['dependencies_module']:
                        if not isinstance(each_dep, tuple):
                            error.append("'dependencies_module' must be a list of tuples")
                        elif len(each_dep) != 3:
                            error.append("'dependencies_module': tuples in list must have 3 items")
                        elif not each_dep[0] or not each_dep[1] or not each_dep[2]:
                            error.append(
                                "'dependencies_module': tuples in list must "
                                "not be empty")
                        elif each_dep[0] not in ['internal', 'pip-pypi', 'apt']:
                            error.append(
                                "'dependencies_module': first in tuple "
                                "must be 'internal', 'pip-pypi', "
                                "or 'apt'")

        if not error:
            # Determine filename
            unique_name = '{}.py'.format(controller_info.FUNCTION_INFORMATION['function_name_unique'].lower())

            # Move module from temp directory to function directory
            full_path_final = os.path.join(PATH_FUNCTIONS_CUSTOM, unique_name)
            os.rename(full_path_tmp, full_path_final)

            # Reload frontend to refresh the controllers
            reload_frontend(logger=logger)
            flash(gettext('Frontend reloaded to scan for new Controller Modules'), 'success')

    except Exception as err:
        logger.exception("Function Import")
        error.append("Exception: {}".format(err))

    flash_success_errors(error, action, url_for('routes_settings.settings_function'))


def settings_function_delete(form):
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['controller']['title'])
    error = []

    controller_device_name = form.controller_id.data
    file_name = '{}.py'.format(form.controller_id.data.lower())
    full_path_file = os.path.join(PATH_FUNCTIONS_CUSTOM, file_name)

    if not error:
        # Check if any Controller entries exist
        controller_dev = CustomController.query.filter(
            CustomController.device == controller_device_name).count()
        if controller_dev:
            error.append("Cannot delete Controller Module if there are still "
                         "Controller entries using it. Deactivate and delete all "
                         "Controller entries that use this module before deleting "
                         "the module.")

    if not error:
        os.remove(full_path_file)

        # Reload frontend to refresh the controllers
        reload_frontend(logger=logger)
        flash(gettext('Frontend reloaded to scan for new Controller Modules'), 'success')

    flash_success_errors(error, action, url_for('routes_settings.settings_function'))


def settings_action_import(form):
    """
    Receive an action module file, check it for errors, add it to AoT controller list
    """
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['actions']['title'])
    error = []

    action_info = None

    try:
        install_dir = os.path.abspath(INSTALL_DIRECTORY)
        tmp_directory = os.path.join(install_dir, 'aot/actions/tmp_actions')
        assure_path_exists(tmp_directory)
        assure_path_exists(PATH_ACTIONS_CUSTOM)
        tmp_name = 'tmp_action_testing.py'
        full_path_tmp = os.path.join(tmp_directory, tmp_name)

        if not form.import_action_file.data:
            error.append('No file present')
        elif form.import_action_file.data.filename == '':
            error.append('No file name')
        else:
            form.import_action_file.data.save(full_path_tmp)

        try:
            action_info, status = load_module_from_file(full_path_tmp, 'actions')
            if not action_info or not hasattr(action_info, 'ACTION_INFORMATION'):
                error.append("Could not load ACTION_INFORMATION dictionary from "
                             "the uploaded action module")
        except Exception:
            error.append("Could not load uploaded file as a python module:\n"
                         "{}".format(traceback.format_exc()))

        dict_actions = parse_action_information()
        list_actions = []
        for each_key in dict_actions.keys():
            list_actions.append(each_key.lower())

        if not error:
            if 'name_unique' not in action_info.ACTION_INFORMATION:
                error.append(
                    "'name_unique' not found in "
                    "ACTION_INFORMATION dictionary")
            elif action_info.ACTION_INFORMATION['name_unique'] == '':
                error.append("'name_unique' is empty")
            elif action_info.ACTION_INFORMATION['name_unique'].lower() in list_actions:
                error.append(
                    "'name_unique' is not unique, there "
                    "is already an action with that name ({})".format(
                        action_info.ACTION_INFORMATION['name_unique'].lower()))

            if 'name' not in action_info.ACTION_INFORMATION:
                error.append("'name' not found in ACTION_INFORMATION dictionary")
            elif action_info.ACTION_INFORMATION['name'] == '':
                error.append("'name' is empty")

            if 'dependencies_module' in action_info.ACTION_INFORMATION:
                if not isinstance(action_info.ACTION_INFORMATION['dependencies_module'], list):
                    error.append("'dependencies_module' must be a list of tuples")
                else:
                    for each_dep in action_info.ACTION_INFORMATION['dependencies_module']:
                        if not isinstance(each_dep, tuple):
                            error.append("'dependencies_module' must be a list of tuples")
                        elif len(each_dep) != 3:
                            error.append("'dependencies_module': tuples in list must have 3 items")
                        elif not each_dep[0] or not each_dep[1] or not each_dep[2]:
                            error.append(
                                "'dependencies_module': tuples in list must "
                                "not be empty")
                        elif each_dep[0] not in ['internal', 'pip-pypi', 'apt']:
                            error.append(
                                "'dependencies_module': first in tuple "
                                "must be 'internal', 'pip-pypi', "
                                "or 'apt'")

        if not error:
            # Determine filename
            unique_name = '{}.py'.format(action_info.ACTION_INFORMATION['name_unique'].lower())

            # Move module from temp directory to function directory
            full_path_final = os.path.join(PATH_ACTIONS_CUSTOM, unique_name)
            os.rename(full_path_tmp, full_path_final)

            # Reload frontend to refresh the actions
            reload_frontend(logger=logger)
            flash(gettext('Frontend reloaded to scan for new Action Modules'), 'success')

    except Exception as err:
        logger.exception("Action Import")
        error.append("Exception: {}".format(err))

    flash_success_errors(error, action, url_for('routes_settings.settings_action'))


def settings_action_delete(form):
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['actions']['title'])
    error = []

    action_device_name = form.action_id.data
    file_name = '{}.py'.format(form.action_id.data.lower())
    full_path_file = os.path.join(PATH_ACTIONS_CUSTOM, file_name)

    # Check if any action entries exist
    action_dev = Actions.query.filter(
        Actions.action_type == action_device_name).count()
    if action_dev:
        error.append("Cannot delete Action Module if there are still "
                     "Action entries using it. Delete all "
                     "Action entries that use this module before deleting "
                     "the module.")

    if not error:
        os.remove(full_path_file)

        # Reload frontend to refresh the actions
        reload_frontend(logger=logger)
        flash(gettext('Frontend reloaded to scan for new Action Modules'), 'success')

    flash_success_errors(error, action, url_for('routes_settings.settings_function'))


def settings_input_import(form):
    """
    Receive an input module file, check it for errors, add it to AoT input list
    """
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['input']['title'])
    error = []

    input_info = None

    try:
        # correct_format = 'AoT_AOTVERSION_Settings_DBVERSION_HOST_DATETIME.zip'
        install_dir = os.path.abspath(INSTALL_DIRECTORY)
        tmp_directory = os.path.join(install_dir, 'aot/inputs/tmp_inputs')
        assure_path_exists(tmp_directory)
        assure_path_exists(PATH_INPUTS_CUSTOM)
        tmp_name = 'tmp_input_testing.py'
        full_path_tmp = os.path.join(tmp_directory, tmp_name)

        if not form.import_input_file.data:
            error.append('No file present')
        elif form.import_input_file.data.filename == '':
            error.append('No file name')
        else:
            form.import_input_file.data.save(full_path_tmp)

        try:
            input_info, status = load_module_from_file(full_path_tmp, 'inputs')
            if not input_info and status != "success":
                error.append(status)
            if input_info and not hasattr(input_info, 'INPUT_INFORMATION'):
                error.append("Could not load INPUT_INFORMATION dictionary from "
                             "the uploaded input module")
        except Exception:
            error.append("Could not load uploaded file as a python module:\n"
                         "{}".format(traceback.format_exc()))

        dict_inputs = parse_input_information()
        list_inputs = []
        for each_key in dict_inputs.keys():
            list_inputs.append(each_key.lower())

        if not error:
            if 'input_name_unique' not in input_info.INPUT_INFORMATION:
                error.append(
                    "'input_name_unique' not found in "
                    "INPUT_INFORMATION dictionary")
            elif input_info.INPUT_INFORMATION['input_name_unique'] == '':
                error.append("'input_name_unique' is empty")
            elif input_info.INPUT_INFORMATION['input_name_unique'].lower() in list_inputs:
                error.append(
                    "'input_name_unique' is not unique, there "
                    "is already an input with that name ({})".format(
                        input_info.INPUT_INFORMATION['input_name_unique'].lower()))

            if 'input_manufacturer' not in input_info.INPUT_INFORMATION:
                error.append(
                    "'input_manufacturer' not found in "
                    "INPUT_INFORMATION dictionary")
            elif input_info.INPUT_INFORMATION['input_manufacturer'] == '':
                error.append("'input_manufacturer' is empty")

            if 'input_name' not in input_info.INPUT_INFORMATION:
                error.append("'input_name' not found in INPUT_INFORMATION dictionary")
            elif input_info.INPUT_INFORMATION['input_name'] == '':
                error.append("'input_name' is empty")

            if 'measurements_name' not in input_info.INPUT_INFORMATION:
                error.append(
                    "'measurements_name' not found in "
                    "INPUT_INFORMATION dictionary")
            elif input_info.INPUT_INFORMATION['measurements_name'] == '':
                error.append("'measurements_name' list is empty")

            if 'measurements_dict' not in input_info.INPUT_INFORMATION:
                error.append(
                    "'measurements_dict' not found in "
                    "INPUT_INFORMATION dictionary")
            elif not input_info.INPUT_INFORMATION['measurements_dict']:
                if ('measurements_variable_amount' in input_info.INPUT_INFORMATION and
                   input_info.INPUT_INFORMATION['measurements_variable_amount']):
                    pass
                else:
                    error.append("'measurements_dict' list is empty")
            else:
                # Check that units and measurements exist in database
                for _, each_unit_measure in input_info.INPUT_INFORMATION['measurements_dict'].items():
                    if (each_unit_measure['unit'] not in UNITS and
                            not Unit.query.filter(Unit.name_safe == each_unit_measure['unit']).count()):
                        error.append(
                            "Unit not found in database. "
                            "Add the unit '{}' to the database before importing.".format(
                                each_unit_measure['unit']))
                    if (each_unit_measure['measurement'] not in MEASUREMENTS and
                            not Measurement.query.filter(Measurement.name_safe == each_unit_measure['measurement']).count()):
                        error.append(
                            "Measurement not found in database. "
                            "Add the measurement '{}' to the database before importing.".format(
                                each_unit_measure['measurement']))

            if 'dependencies_module' in input_info.INPUT_INFORMATION:
                if not isinstance(input_info.INPUT_INFORMATION['dependencies_module'], list):
                    error.append("'dependencies_module' must be a list of tuples")
                else:
                    for each_dep in input_info.INPUT_INFORMATION['dependencies_module']:
                        if not isinstance(each_dep, tuple):
                            error.append("'dependencies_module' must be a list of tuples")
                        elif len(each_dep) != 3:
                            error.append("'dependencies_module': tuples in list must have 3 items")
                        elif not each_dep[0] or not each_dep[1] or not each_dep[2]:
                            error.append("'dependencies_module': tuples in list must not be empty")
                        elif each_dep[0] not in ['internal', 'pip-pypi', 'apt']:
                            error.append(
                                "'dependencies_module': first in tuple "
                                "must be 'internal', 'pip-pypi', "
                                "or 'apt'")

        if not error:
            # Determine filename
            unique_name = '{}.py'.format(input_info.INPUT_INFORMATION['input_name_unique'].lower())

            # Move module from temp directory to custom_input directory
            full_path_final = os.path.join(PATH_INPUTS_CUSTOM, unique_name)
            os.rename(full_path_tmp, full_path_final)

            # Reload frontend to refresh the inputs
            reload_frontend(logger=logger)
            flash(gettext('Frontend reloaded to scan for new Input Modules'), 'success')

    except Exception as err:
        error.append("Exception: {}".format(err))

    flash_success_errors(error, action, url_for('routes_settings.settings_input'))


def settings_input_delete(form):
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['input']['title'])
    error = []

    input_device_name = form.input_id.data
    file_name = '{}.py'.format(form.input_id.data.lower())
    full_path_file = os.path.join(PATH_INPUTS_CUSTOM, file_name)

    if not error:
        # Check if any Input entries exist
        input_dev = Input.query.filter(Input.device == input_device_name).count()
        if input_dev:
            error.append("Cannot delete Input Module if there are still "
                         "Input entries using it. Deactivate and delete all "
                         "Input entries that use this module before deleting "
                         "the module.")

    if not error:
        os.remove(full_path_file)

        # Reload frontend to refresh the inputs
        reload_frontend(logger=logger)
        flash(gettext('Frontend reloaded to scan for new Input Modules'), 'success')

    flash_success_errors(error, action, url_for('routes_settings.settings_input'))


def settings_output_import(form):
    """
    Receive an output module file, check it for errors, add it to AoT output list
    """
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['output']['title'])
    error = []

    output_info = None

    try:
        # correct_format = 'AoT_AOTVERSION_Settings_DBVERSION_HOST_DATETIME.zip'
        install_dir = os.path.abspath(INSTALL_DIRECTORY)
        tmp_directory = os.path.join(install_dir, 'aot/outputs/tmp_outputs')
        assure_path_exists(tmp_directory)
        assure_path_exists(PATH_OUTPUTS_CUSTOM)
        tmp_name = 'tmp_output_testing.py'
        full_path_tmp = os.path.join(tmp_directory, tmp_name)

        if not form.import_output_file.data:
            error.append('No file present')
        elif form.import_output_file.data.filename == '':
            error.append('No file name')
        else:
            form.import_output_file.data.save(full_path_tmp)

        try:
            output_info, status = load_module_from_file(full_path_tmp, 'outputs')
            if not output_info or not hasattr(output_info, 'OUTPUT_INFORMATION'):
                error.append("Could not load OUTPUT_INFORMATION dictionary from "
                             "the uploaded output module")
        except Exception:
            error.append("Could not load uploaded file as a python module:\n"
                         "{}".format(traceback.format_exc()))

        dict_outputs = parse_output_information()
        list_outputs = []
        for each_key in dict_outputs.keys():
            list_outputs.append(each_key.lower())

        if not error:
            if 'output_name_unique' not in output_info.OUTPUT_INFORMATION:
                error.append(
                    "'output_name_unique' not found in "
                    "OUTPUT_INFORMATION dictionary")
            elif output_info.OUTPUT_INFORMATION['output_name_unique'] == '':
                error.append("'output_name_unique' is empty")
            elif output_info.OUTPUT_INFORMATION['output_name_unique'].lower() in list_outputs:
                error.append(
                    "'output_name_unique' is not unique, there "
                    "is already an output with that name ({})".format(
                        output_info.OUTPUT_INFORMATION['output_name_unique'].lower()))

            if 'output_name' not in output_info.OUTPUT_INFORMATION:
                error.append("'output_name' not found in OUTPUT_INFORMATION dictionary")
            elif output_info.OUTPUT_INFORMATION['output_name'] == '':
                error.append("'output_name' is empty")

            if 'measurements_dict' not in output_info.OUTPUT_INFORMATION:
                error.append("'measurements_dict' not found in OUTPUT_INFORMATION dictionary")
            elif not output_info.OUTPUT_INFORMATION['measurements_dict']:
                if ('measurements_variable_amount' in output_info.OUTPUT_INFORMATION and
                   output_info.OUTPUT_INFORMATION['measurements_variable_amount']):
                    pass
                else:
                    error.append("'measurements_dict' list is empty")
            else:
                # Check that units and measurements exist in database
                for _, each_unit_measure in output_info.OUTPUT_INFORMATION['measurements_dict'].items():
                    if (each_unit_measure['unit'] not in UNITS and
                            not Unit.query.filter(Unit.name_safe == each_unit_measure['unit']).count()):
                        error.append(
                            "Unit not found in database. "
                            "Add the unit '{}' to the database before importing.".format(
                                each_unit_measure['unit']))
                    if (each_unit_measure['measurement'] not in MEASUREMENTS and
                            not Measurement.query.filter(Measurement.name_safe == each_unit_measure['measurement']).count()):
                        error.append(
                            "Measurement not found in database. "
                            "Add the measurement '{}' to the database before importing.".format(
                                each_unit_measure['measurement']))

            if 'dependencies_module' in output_info.OUTPUT_INFORMATION:
                if not isinstance(output_info.OUTPUT_INFORMATION['dependencies_module'], list):
                    error.append("'dependencies_module' must be a list of tuples")
                else:
                    for each_dep in output_info.OUTPUT_INFORMATION['dependencies_module']:
                        if not isinstance(each_dep, tuple):
                            error.append("'dependencies_module' must be a list of tuples")
                        elif len(each_dep) != 3:
                            error.append("'dependencies_module': tuples in list must have 3 items")
                        elif not each_dep[0] or not each_dep[1] or not each_dep[2]:
                            error.append("'dependencies_module': tuples in list must not be empty")
                        elif each_dep[0] not in ['internal', 'pip-pypi', 'apt']:
                            error.append(
                                "'dependencies_module': first in tuple "
                                "must be 'internal', 'pip-pypi', "
                                "or 'apt'")

        if not error:
            # Determine filename
            unique_name = '{}.py'.format(output_info.OUTPUT_INFORMATION['output_name_unique'].lower())

            # Move module from temp directory to custom_output directory
            full_path_final = os.path.join(PATH_OUTPUTS_CUSTOM, unique_name)
            os.rename(full_path_tmp, full_path_final)

            # Reload frontend to refresh the outputs
            reload_frontend(logger=logger)
            flash(gettext('Frontend reloaded to scan for new Output Modules'), 'success')

    except Exception as err:
        error.append("Exception: {}".format(err))

    flash_success_errors(error, action, url_for('routes_settings.settings_output'))


def settings_output_delete(form):
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['output']['title'])
    error = []

    output_device_name = form.output_id.data
    file_name = '{}.py'.format(form.output_id.data.lower())
    full_path_file = os.path.join(PATH_OUTPUTS_CUSTOM, file_name)

    if not error:
        # Check if any Output entries exist
        output_dev = Output.query.filter(Output.output_type == output_device_name).count()
        if output_dev:
            error.append("Cannot delete Output Module if there are still "
                         "Output entries using it. Delete all Output entries "
                         "that use this module before deleting the module.")

    if not error:
        os.remove(full_path_file)

        # Reload frontend to refresh the outputs
        reload_frontend(logger=logger)
        flash(gettext('Frontend reloaded to scan for new Output Modules'), 'success')

    flash_success_errors(error, action, url_for('routes_settings.settings_output'))


def settings_widget_import(form):
    """
    Receive an widget module file, check it for errors, add it to AoT widget list
    """
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['widget']['title'])
    error = []

    widget_info = None

    try:
        # correct_format = 'AoT_AOTVERSION_Settings_DBVERSION_HOST_DATETIME.zip'
        install_dir = os.path.abspath(INSTALL_DIRECTORY)
        tmp_directory = os.path.join(install_dir, 'aot/widgets/tmp_widgets')
        assure_path_exists(tmp_directory)
        assure_path_exists(PATH_WIDGETS_CUSTOM)
        tmp_name = 'tmp_widget_testing.py'
        full_path_tmp = os.path.join(tmp_directory, tmp_name)

        if not form.import_widget_file.data:
            error.append('No file present')
        elif form.import_widget_file.data.filename == '':
            error.append('No file name')
        else:
            form.import_widget_file.data.save(full_path_tmp)

        try:
            widget_info, status = load_module_from_file(full_path_tmp, 'widgets')
            if not widget_info or not hasattr(widget_info, 'WIDGET_INFORMATION'):
                error.append("Could not load WIDGET_INFORMATION dictionary from "
                             "the uploaded widget module")
        except Exception:
            error.append("Could not load uploaded file as a python module:\n"
                         "{}".format(traceback.format_exc()))

        dict_widgets = parse_widget_information()
        list_widgets = []
        for each_key in dict_widgets.keys():
            list_widgets.append(each_key.lower())

        if not error:
            if 'widget_name_unique' not in widget_info.WIDGET_INFORMATION:
                error.append("'widget_name_unique' not found in WIDGET_INFORMATION dictionary")
            elif widget_info.WIDGET_INFORMATION['widget_name_unique'] == '':
                error.append("'widget_name_unique' is empty")
            elif widget_info.WIDGET_INFORMATION['widget_name_unique'].lower() in list_widgets:
                error.append(
                    "'widget_name_unique' is not unique, there "
                    "is already an widget with that name ({})".format(
                        widget_info.WIDGET_INFORMATION['widget_name_unique'].lower()))

            if 'widget_name' not in widget_info.WIDGET_INFORMATION:
                error.append("'widget_name' not found in WIDGET_INFORMATION dictionary")
            elif widget_info.WIDGET_INFORMATION['widget_name'] == '':
                error.append("'widget_name' is empty")

            if 'dependencies_module' in widget_info.WIDGET_INFORMATION:
                if not isinstance(widget_info.WIDGET_INFORMATION['dependencies_module'], list):
                    error.append("'dependencies_module' must be a list of tuples")
                else:
                    for each_dep in widget_info.WIDGET_INFORMATION['dependencies_module']:
                        if not isinstance(each_dep, tuple):
                            error.append("'dependencies_module' must be a list of tuples")
                        elif len(each_dep) != 3:
                            error.append("'dependencies_module': tuples in list must have 3 items")
                        elif not each_dep[0] or not each_dep[1] or not each_dep[2]:
                            error.append("'dependencies_module': tuples in list must not be empty")
                        elif each_dep[0] not in ['internal', 'pip-pypi', 'apt']:
                            error.append(
                                "'dependencies_module': first in tuple "
                                "must be 'internal', 'pip-pypi', "
                                "or 'apt'")

        if not error:
            # Determine filename
            unique_name = '{}.py'.format(widget_info.WIDGET_INFORMATION['widget_name_unique'].lower())

            # Move module from temp directory to custom_widget directory
            full_path_final = os.path.join(PATH_WIDGETS_CUSTOM, unique_name)
            os.rename(full_path_tmp, full_path_final)

            generate_widget_html()

            # Reload frontend to refresh the widgets
            reload_frontend(logger=logger)
            flash(gettext('Frontend reloaded to scan for new Widget Modules'), 'success')

    except Exception as err:
        error.append("Exception: {}".format(err))

    flash_success_errors(error, action, url_for('routes_settings.settings_widget'))


def settings_widget_delete(form):
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['widget']['title'])
    error = []

    widget_device_name = form.widget_id.data
    file_name = '{}.py'.format(form.widget_id.data.lower())
    full_path_file = os.path.join(PATH_WIDGETS_CUSTOM, file_name)

    if not error:
        # Check if any Widget entries exist
        widget_dev = Widget.query.filter(Widget.graph_type == widget_device_name).count()
        if widget_dev:
            error.append("Cannot delete Widget Module if there are still "
                         "Widget entries using it. Delete all Widget entries "
                         "that use this module before deleting the module.")

    if not error:
        os.remove(full_path_file)

        # Reload frontend to refresh the widgets
        reload_frontend(logger=logger)
        flash(gettext('Frontend reloaded to scan for new Widget Modules'), 'success')

    flash_success_errors(error, action, url_for('routes_settings.settings_widget'))


def settings_measurement_add(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['measurement']['title'])
    error = []
    choices_meas = choices_measurements(Measurement.query.all())

    new_measurement = Measurement()
    new_measurement.name = form.name.data
    new_measurement.units = ",".join(form.units.data)

    name_safe = re.sub('[^0-9a-zA-Z]+', '_', form.id.data)
    if name_safe.endswith('_'):
        name_safe = name_safe[:-1]
    if name_safe in choices_meas:
        error.append("Measurement name already exists: {name}".format(
            name=name_safe))

    new_measurement.name_safe = name_safe

    try:
        if not error:
            new_measurement.save()
            flash(gettext(
                "Measurement with ID %(id)s (%(uuid)s) successfully added",
                id=new_measurement.id,
                uuid=new_measurement.unique_id),
                  "success")
    except sqlalchemy.exc.OperationalError as except_msg:
        error.append(except_msg)
    except sqlalchemy.exc.IntegrityError as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def settings_measurement_mod(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['measurement']['title'])
    error = []
    try:
        mod_measurement = Measurement.query.filter(
            Measurement.unique_id == form.measurement_id.data).first()
        mod_measurement.name = form.name.data
        mod_measurement.units = ",".join(form.units.data)

        name_safe = re.sub('[^0-9a-zA-Z]+', '_', form.id.data)
        if name_safe.endswith('_'):
            name_safe = name_safe[:-1]

        if name_safe != mod_measurement.name_safe:  # Change measurement name
            # Ensure no Inputs depend on this measurement
            for _, each_data in parse_input_information().items():
                if 'measurements_dict' in each_data:
                    for _, each_channel_data in each_data['measurements_dict'].items():
                        if ('measurement' in each_channel_data and
                                each_channel_data['measurement'] == mod_measurement.name_safe):
                            error.append(
                                "Cannot change the name of this measurement "
                                "because an Input depends on it.")
            # Ensure a measurement doesn't already exist with the new name
            if (Measurement.query.filter(
                    and_(Measurement.name_safe == name_safe,
                         Measurement.unique_id != mod_measurement.unique_id)).count() or
                    name_safe in MEASUREMENTS):
                error.append("Measurement name already exists: {name}".format(
                    name=name_safe))
            else:
                mod_measurement.name_safe = name_safe

        if not error:
            db.session.commit()
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def settings_measurement_del(unique_id):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['measurement']['title'])
    error = []

    measurement = Measurement.query.filter(
        Measurement.unique_id == unique_id).first()

    # Ensure no Inputs depend on this measurement
    for _, each_data in parse_input_information().items():
        if 'measurements_dict' in each_data:
            for _, each_channel_data in each_data['measurements_dict'].items():
                if ('measurement' in each_channel_data and
                        each_channel_data['measurement'] == measurement.name_safe):
                    error.append("Cannot delete this measurement because "
                                 "an Input depends on it.")

    try:
        if not error:
            delete_entry_with_id(Measurement, unique_id)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def settings_unit_add(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=gettext("Unit"))
    error = []
    choices_unit = choices_units(Unit.query.all())

    if form.validate():
        name_safe = re.sub('[^0-9a-zA-Z]+', '_', form.id.data)
        if name_safe.endswith('_'):
            name_safe = name_safe[:-1]

        if name_safe in choices_unit:
            error.append("Unit name already exists: {name}".format(
                name=name_safe))

        new_unit = Unit()
        new_unit.name_safe = name_safe
        new_unit.name = form.name.data
        new_unit.unit = form.unit.data

        try:
            if not error:
                new_unit.save()
                flash(gettext(
                    "Unit with ID %(id)s (%(uuid)s) successfully added",
                    id=new_unit.id,
                    uuid=new_unit.unique_id),
                    "success")
        except sqlalchemy.exc.OperationalError as except_msg:
            error.append(except_msg)
        except sqlalchemy.exc.IntegrityError as except_msg:
            error.append(except_msg)

        flash_success_errors(
            error, action, url_for('routes_settings.settings_measurement'))
    else:
        flash_form_errors(form)


def settings_unit_mod(form, *_args, **_kwargs):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=gettext("Unit"))
    error = []
    try:
        mod_unit = Unit.query.filter(
            Unit.unique_id == form.unit_id.data).first()

        name_safe = re.sub('[^0-9a-zA-Z]+', '_', form.id.data)
        if name_safe.endswith('_'):
            name_safe = name_safe[:-1]

        conversions = Conversion.query.filter(or_(
            Conversion.convert_unit_from == mod_unit.name_safe,
            Conversion.convert_unit_to == mod_unit.name_safe
        )).count()

        if (Unit.query.filter(
                and_(Unit.name_safe == name_safe,
                     Unit.unique_id != form.unit_id.data)).count() or
                name_safe in UNITS):
            error.append("Unit name already exists: {name}".format(
                name=name_safe))
        elif mod_unit.name_safe != name_safe:
            if conversions:
                error.append(
                    "Unit belongs to a conversion."
                    "Delete conversion(s) before changing unit.")
            else:
                # Ensure no Inputs depend on this measurement
                for _, each_data in parse_input_information().items():
                    if 'measurements_dict' in each_data:
                        for _, each_channel_data in each_data['measurements_dict'].items():
                            if ('unit' in each_channel_data and
                                    each_channel_data['unit'] == mod_unit.name_safe):
                                error.append(
                                    "Cannot change the name of this unit "
                                    "because an Input depends on it.")

        mod_unit.name = form.name.data
        mod_unit.unit = form.unit.data
        mod_unit.name_safe = name_safe

        if not error:
            db.session.commit()
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def settings_unit_del(unique_id):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=gettext("Unit"))
    error = []

    del_unit = Unit.query.filter(
        Unit.unique_id == unique_id).first()

    conversions = Conversion.query.filter(or_(
        Conversion.convert_unit_from == del_unit.name_safe,
        Conversion.convert_unit_to == del_unit.name_safe
    )).count()

    if conversions:
        error.append(
            "Unit belongs to a conversion."
            "Delete conversion(s) before deleting unit.")

    # Ensure no Inputs depend on this unit
    for _, each_data in parse_input_information().items():
        if 'measurements_dict' in each_data:
            for _, each_channel_data in each_data['measurements_dict'].items():
                if ('unit' in each_channel_data and
                        each_channel_data['unit'] == del_unit.name_safe):
                    error.append("Cannot delete this unit because an "
                                 "Input depends on it.")

    try:
        if not error:
            delete_entry_with_id(Unit, unique_id)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def settings_convert_add(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=gettext("Conversion"))
    error = []

    conversion = Conversion.query.all()

    conversion_str = '{fr}_to_{to}'.format(
        fr=form.convert_unit_from.data, to=form.convert_unit_to.data)
    if conversion_str in all_conversions(conversion):
        error.append("Conversion '{cs}' already exists.".format(
            cs=conversion_str))

    if 'x' not in form.equation.data:
        error.append("'x' must appear in the equation.")

    if form.validate():
        new_conversion = Conversion()
        new_conversion.convert_unit_from = form.convert_unit_from.data
        new_conversion.convert_unit_to = form.convert_unit_to.data
        new_conversion.equation = form.equation.data

        try:
            if not error:
                new_conversion.save()
                flash(gettext(
                    "Conversion with ID %(id)s (%(uuid)s) successfully added",
                    id=new_conversion.id,
                    uuid=new_conversion.unique_id),
                    "success")
        except sqlalchemy.exc.OperationalError as except_msg:
            error.append(except_msg)
        except sqlalchemy.exc.IntegrityError as except_msg:
            error.append(except_msg)

        flash_success_errors(
            error, action, url_for('routes_settings.settings_measurement'))
    else:
        flash_form_errors(form)


def settings_convert_mod(form, *_args, **_kwargs):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=gettext("Conversion"))
    error = []

    if 'x' not in form.equation.data:
        error.append("'x' must appear in the equation")

    try:
        mod_conversion = Conversion.query.filter(
            Conversion.unique_id == form.conversion_id.data).first()

        # Don't allow conversion to be changed for an active controller
        error = check_conversion_being_used(mod_conversion, error, state='active')

        if not error:
            # Don't allow from conversion to be changed for an inactive controller
            if mod_conversion.convert_unit_from != form.convert_unit_from.data:
                error = check_conversion_being_used(mod_conversion, error, state='inactive')

            if not mod_conversion.protected:
                mod_conversion.convert_unit_from = form.convert_unit_from.data
                mod_conversion.convert_unit_to = form.convert_unit_to.data
            mod_conversion.equation = form.equation.data
            db.session.commit()
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def settings_conversion_add(form, *_args, **_kwargs):
    """
    Compatibility wrapper for routes that still call the legacy name.
    """
    return settings_convert_add(form)


def settings_conversion_mod(form, *_args, **_kwargs):
    """
    Compatibility wrapper for routes that still call the legacy name.
    """
    return settings_convert_mod(form)


def choices_conversions(conversions, units):
    """
    Return a list of conversion choices for templates expecting this helper.
    Format matches other choice helpers: [{'item': 'C_to_F', 'value': 'uuid'}, ...]
    """
    unit_lookup = {u.name_safe: u.name for u in units} if units else {}
    choices = []
    for conv in conversions:
        from_label = unit_lookup.get(conv.convert_unit_from, conv.convert_unit_from)
        to_label = unit_lookup.get(conv.convert_unit_to, conv.convert_unit_to)
        label = f"{from_label}_to_{to_label}"
        choices.append({
            'item': label,
            'value': conv.unique_id
        })
    return choices


def settings_convert_del(unique_id):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=gettext("Conversion"))
    error = []

    try:
        conv = Conversion.query.filter(
            Conversion.unique_id == unique_id).first()

        # Don't allow conversion to be changed for an active controller
        error = check_conversion_being_used(conv, error, state='active')

        if not error:
            # Delete conversion from any controllers
            remove_conversion_from_controllers(unique_id)
            delete_entry_with_id(Conversion, unique_id)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_measurement'))


def check_conversion_being_used(conv, error, state=None):
    """
    Check if a controller is currently active/inactive and using the conversion
    If so, cannot edit the database/modify the conversion
    """
    try:
        device_measurements = DeviceMeasurements.query.all()

        list_measurements = [Input, PID,]

        for each_device_type in list_measurements:
            for each_device in each_device_type.query.all():
                for each_meas in device_measurements:
                    if (each_device.unique_id == each_meas.device_id and
                            conv.unique_id == each_meas.conversion_id):

                        detected_device = each_device_type.query.filter(
                            each_device_type.unique_id == each_meas.device_id).first()

                        if ((state == 'active' and detected_device.is_activated) or
                                (state == 'inactive' and not detected_device.is_activated)):
                            error.append(
                                "Conversion [{cid}] ({conv}): "
                                "Currently in use for measurement {meas}, "
                                "for device {dev}".format(
                                    cid=conv.id,
                                    conv=conv.unique_id,
                                    meas=each_meas.unique_id,
                                    dev=each_meas.device_id))
    except Exception as except_msg:
        error.append(except_msg)
    return error


def remove_conversion_from_controllers(conv_id):
    """
    Find measurements using the conversion and delete the reference to the conversion_id
    """
    device_measurements = DeviceMeasurements.query.all()

    for each_meas in device_measurements:
        if each_meas.conversion_id == conv_id:
            each_meas.conversion_id = ''

    db.session.commit()


def settings_pi_mod(form):
    """
    Change Pi Settings
    Commands found at
    https://github.com/raspberrypi-ui/rc_gui/blob/master/src/rc_gui.c
    """
    error = []
    status = None
    action_str = None

    if form.enable_i2c.data:
        _, _, status = cmd_output("raspi-config nonint do_i2c 0", user='root')
        action_str = "Enable I2C"
    elif form.disable_i2c.data:
        _, _, status = cmd_output("raspi-config nonint do_i2c 1", user='root')
        action_str = "Disable I2C"
    elif form.enable_one_wire.data:
        _, _, status = cmd_output("raspi-config nonint do_onewire 0", user='root')
        action_str = "Enable 1-Wire"
    elif form.disable_one_wire.data:
        _, _, status = cmd_output("raspi-config nonint do_onewire 1", user='root')
        action_str = "Disable 1-Wire"
    elif form.enable_serial.data:
        _, _, status = cmd_output("raspi-config nonint do_serial 0", user='root')
        action_str = "Enable Serial"
    elif form.disable_serial.data:
        _, _, status = cmd_output("raspi-config nonint do_serial 1", user='root')
        action_str = "Disable Serial"
    elif form.enable_spi.data:
        _, _, status = cmd_output("raspi-config nonint do_spi 0", user='root')
        action_str = "Enable SPI"
    elif form.disable_spi.data:
        _, _, status = cmd_output("raspi-config nonint do_spi 1", user='root')
        action_str = "Disable SPI"
    elif form.enable_ssh.data:
        _, _, status = cmd_output("raspi-config nonint do_ssh 0", user='root')
        action_str = "Enable SSH"
    elif form.disable_ssh.data:
        _, _, status = cmd_output("raspi-config nonint do_ssh 1", user='root')
        action_str = "Disable SSH"
    elif form.change_hostname.data:
        if is_valid_hostname(form.hostname.data):
            _, _, status = cmd_output(
                "raspi-config nonint do_hostname {host}".format(
                    host=form.hostname.data))
        else:
            error.append(
                "Invalid hostname. Hostnames are composed of series of "
                "labels concatenated with dots, as are all domain names. "
                "Hostnames must be 1 to 63 characters and may contain only "
                "the ASCII letters 'a' through 'z' (in a case-insensitive "
                "manner), the digits '0' through '9', and the hyphen ('-').")
        action_str = "Change Hostname to '{host}'".format(
            host=form.hostname.data)
    elif form.change_pigpiod_sample_rate.data:
        if form.pigpiod_sample_rate.data not in ['low', 'high', 'disabled', 'uninstalled']:
            error.append(
                "Valid pigpiod options: Uninstall, Disable, 1 ms, or 5 ms. "
                "Invalid option: {op}".format(
                    op=form.pigpiod_sample_rate.data))
        else:
            # Stop the AoT daemon
            cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper daemon_stop" \
                  f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
            stop_daemon = subprocess.Popen(cmd, shell=True)
            stop_daemon.wait()

            if (form.pigpiod_sample_rate.data != 'uninstalled' and
                    form.pigpiod_state.data == 'uninstalled'):
                # Install pigpiod (sample rate of 1 ms)
                cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper install_pigpiod" \
                      f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
                install_pigpiod = subprocess.Popen(cmd, shell=True)
                install_pigpiod.wait()

            # Disable pigpiod
            cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper disable_pigpiod" \
                  f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
            disable_pigpiod = subprocess.Popen(cmd, shell=True)
            disable_pigpiod.wait()

            if form.pigpiod_sample_rate.data == 'low':
                # Install pigpiod (sample rate of 1 ms)
                cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper enable_pigpiod_low" \
                      f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
                enable_pigpiod_1ms = subprocess.Popen(cmd, shell=True)
                enable_pigpiod_1ms.wait()
            elif form.pigpiod_sample_rate.data == 'high':
                # Install pigpiod (sample rate of 5 ms)
                cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper enable_pigpiod_high" \
                      f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
                enable_pigpiod_5ms = subprocess.Popen(cmd, shell=True)
                enable_pigpiod_5ms.wait()
            elif form.pigpiod_sample_rate.data == 'disabled':
                # Disable pigpiod (user selected disable)
                cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper enable_pigpiod_disabled" \
                      f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
                disable_pigpiod = subprocess.Popen(cmd, shell=True)
                disable_pigpiod.wait()
            elif form.pigpiod_sample_rate.data == 'uninstalled':
                # Uninstall pigpiod (user selected disable)
                cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper uninstall_pigpiod" \
                      f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
                uninstall_pigpiod = subprocess.Popen(cmd, shell=True)
                uninstall_pigpiod.wait()

            # Start the AoT daemon
            cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper daemon_start" \
                  f" | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) 2>&1"
            start_daemon = subprocess.Popen(cmd, shell=True)
            start_daemon.wait()

    if status:
        error.append("Unknown error executing command to {action}".format(
            action=action_str))

    action = '{controller}: {action}'.format(
        controller=gettext("Pi Settings"),
        action=action_str)

    flash_success_errors(error, action, url_for('routes_settings.settings_pi'))


def settings_alert_mod(form_mod_alert):
    """Modify Alert settings."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=gettext("Alert Settings"))
    error = []

    try:
        if form_mod_alert.validate():
            mod_smtp = SMTP.query.one()
            if form_mod_alert.send_test.data:
                try:
                    rc = send_email(
                        mod_smtp.host, mod_smtp.protocol, mod_smtp.port,
                        mod_smtp.user, mod_smtp.passw, mod_smtp.email_from,
                        form_mod_alert.send_test_to_email.data,
                        "This is a test email from AoT")
                    if rc == 0:
                        flash(gettext("Test email sent to %(recip)s. Check your "
                                      "inbox to see if it was successful.",
                                      recip=form_mod_alert.send_test_to_email.data),
                              "success")
                    else:
                        flash(gettext("Test email failed. Please check SMTP host/port, protocol, and credentials."), "error")
                    return redirect(url_for('routes_settings.settings_alerts'))
                except Exception as exc:
                    logger.exception("Test email failed")
                    flash(gettext("Test email failed: %(err)s", err=exc), "error")
                    return redirect(url_for('routes_settings.settings_alerts'))
            else:
                mod_smtp.host = form_mod_alert.smtp_host.data
                if form_mod_alert.smtp_port.data:
                    mod_smtp.port = form_mod_alert.smtp_port.data
                else:
                    mod_smtp.port = None
                mod_smtp.protocol = form_mod_alert.smtp_protocol.data
                mod_smtp.user = form_mod_alert.smtp_user.data
                if form_mod_alert.smtp_password.data:
                    mod_smtp.passw = form_mod_alert.smtp_password.data
                mod_smtp.email_from = form_mod_alert.smtp_from_email.data
                mod_smtp.hourly_max = form_mod_alert.smtp_hourly_max.data
                # Gmail 호환을 위한 기본 포트/프로토콜 권장값 자동 설정 및 경고
                if mod_smtp.host and 'gmail.com' in mod_smtp.host:
                    if not mod_smtp.port:
                        mod_smtp.port = 587  # STARTTLS
                    if not mod_smtp.protocol:
                        mod_smtp.protocol = 'tls'
                    if mod_smtp.email_from and mod_smtp.user and mod_smtp.email_from != mod_smtp.user:
                        flash(gettext("For Gmail, the From email usually needs to match the login email. If needed, set From to %(user)s.", user=mod_smtp.user), "warning")
                if mod_smtp.protocol in ['unencrypted', 'unencrypted_no_login']:
                    flash(gettext("Insecure SMTP protocol configured. Use TLS/SSL if possible."), "warning")
                db.session.commit()
        else:
            flash_form_errors(form_mod_alert)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_alerts'))


def settings_diagnostic_delete_inputs():
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['input']['title'])
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    inputs = db_retrieve_table(Input)
    device_measurements = db_retrieve_table(DeviceMeasurements)
    display_order = db_retrieve_table(DisplayOrder, entry='first')

    if not messages["error"]:
        try:
            for each_input in inputs:
                # Deactivate any active controllers using the input
                if each_input.is_activated:
                    # messages = input_deactivate_associated_controllers(
                    #     messages, each_input.unique_id)
                    messages = controller_activate_deactivate(
                        messages, 'deactivate', 'Input', each_input.unique_id)

                # Delete all measurements associated with the input
                for each_measurement in device_measurements:
                    if each_measurement.device_id == each_input.unique_id:
                        db.session.delete(each_measurement)

                # [Phase C] 장치가 사라지면 바인딩을 끝낸다 — 도형은 미배정 슬롯으로
                # 남는다(위치 마커만 예외). 이 일괄 삭제는 raw db.session.delete 라
                # 예전에는 도형·바인딩을 하나도 정리하지 않았다.
                from aot.aot_flask.geo.device_binding import end_all_for_device
                end_all_for_device(each_input.unique_id)
                from aot.utils.code_verification import delete_python_file
                delete_python_file('input', each_input.unique_id)
                # Delete the input
                db.session.delete(each_input)
            display_order.input = ''  # Clear the order
            db.session.commit()
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    flash_success_errors(
        messages["error"],
        action,
        url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_delete_dashboard_elements():
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    dashboard = db_retrieve_table(Dashboard)
    widget = db_retrieve_table(Widget)

    if not error:
        try:
            for each_dash in dashboard:
                db.session.delete(each_dash)
                db.session.commit()

            for each_widget in widget:
                db.session.delete(each_widget)
                db.session.commit()

            Dashboard(id=1, name='Default').save()
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_delete_notes_tags():
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller='{}/{}'.format(TRANSLATIONS['tag']['title'],
                                  TRANSLATIONS['note']['title']))
    error = []

    if not error:
        try:
            for each_tag in db_retrieve_table(NoteTags):
                db.session.delete(each_tag)
                db.session.commit()
            for each_note in db_retrieve_table(Notes):
                db.session.delete(each_note)
                db.session.commit()
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_delete_outputs():
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['output']['title'])
    error = []

    output = db_retrieve_table(Output)
    output_channels = db_retrieve_table(OutputChannel)
    display_order = db_retrieve_table(DisplayOrder, entry='first')

    if not error:
        try:
            for each_output in output:
                channels = output_channels.filter(
                    OutputChannel.output_id == each_output.unique_id)
                for each_output_channel in channels:
                    db.session.delete(each_output_channel)

                # [Phase C] 장치가 사라지면 바인딩을 끝낸다 — 도형은 미배정 슬롯으로
                # 남는다(위치 마커만 예외). 이 일괄 삭제는 raw db.session.delete 라
                # 예전에는 도형·바인딩을 하나도 정리하지 않았다.
                from aot.aot_flask.geo.device_binding import end_all_for_device
                end_all_for_device(each_output.unique_id)
                from aot.utils.code_verification import delete_python_file
                delete_python_file('output', each_output.unique_id)
                db.session.delete(each_output)
                db.session.commit()
            display_order.output = ''
            db.session.commit()
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_delete_functions():
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['controller']['title'])
    error = []

    display_order = db_retrieve_table(DisplayOrder, entry='first')

    if not error:
        try:
            for each_func in db_retrieve_table(CustomController):
                # [Phase C] 장치가 사라지면 바인딩을 끝낸다 — 도형은 미배정 슬롯으로
                # 남는다(위치 마커만 예외). 이 일괄 삭제는 raw db.session.delete 라
                # 예전에는 도형·바인딩을 하나도 정리하지 않았다.
                from aot.aot_flask.geo.device_binding import end_all_for_device
                end_all_for_device(each_func.unique_id)
                db.session.delete(each_func)
                db.session.commit()
            display_order.function = ''
            db.session.commit()
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_delete_settings_database():
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller='Settings Database')
    error = []

    if not error:
        try:
            # Use the config-resolved live DB path, not a hardcoded /opt/AoT path.
            # The old literal '/opt/AoT/databases/aot.db' existed on no deployment
            # (GIS uses aot/databases; Docker uses the aot_data volume via
            # AOT_LOCAL_DIR), so this delete silently failed everywhere.
            os.remove(SQL_DATABASE_AOT)
            reload_frontend(logger=logger)
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_delete_file(delete_type):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=gettext("File"))
    error = []

    if not error:
        try:
            file_remove = None
            if delete_type == 'dependency':
                file_remove = os.path.abspath(DEPENDENCY_INIT_FILE)
            elif delete_type == 'upgrade':
                file_remove = os.path.abspath(UPGRADE_INIT_FILE)
            if file_remove:
                if os.path.isfile(file_remove):
                    os.remove(file_remove)
                else:
                    error.append("File not found: {}".format(file_remove))
            else:
                error.append("Unknown file: {}".format(delete_type))
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_recreate_influxdb_db_1():
    action = gettext("Recreate InfluxDB 1.x Database")
    error = []

    if not error:
        try:
            command = f'/bin/bash {INSTALL_DIRECTORY}/aot/scripts/upgrade_commands.sh recreate-influxdb-1-db'
            p = subprocess.Popen(command, shell=True)
            p.communicate()
        except Exception:
            logger.exception()
    
    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_recreate_influxdb_db_2():
    action = gettext("Recreate InfluxDB 2.x Database")
    error = []

    if not error:
        try:
            command = f'/bin/bash {INSTALL_DIRECTORY}/aot/scripts/upgrade_commands.sh recreate-influxdb-2-db'
            p = subprocess.Popen(command, shell=True)
            p.communicate()
        except Exception:
            logger.exception()
    
    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_reset_email_counter():
    action = gettext("Reset Email Counter")
    error = []

    if not error:
        try:
            smtp_settings = SMTP.query.first()
            smtp_settings.email_count = 0
            smtp_settings.smtp_wait_timer = time.time() + 3600
            db.session.commit()
        except Exception as except_msg:
            error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_diagnostic_install_dependencies():
    action = gettext("Install Dependencies")
    error = []

    if not error:
        try:
            def install_dependencies():
                cmd = "{pth}/aot/scripts/aot_wrapper update_dependencies" \
                      " | ( while IFS= read -r line; do echo \"[$(date +'%Y-%m-%d %H:%M:%S')] $line\"; done ) >> {log} 2>&1".format(
                    pth=INSTALL_DIRECTORY,
                    log=DEPENDENCY_LOG_FILE)
                _, _, _ = cmd_output(cmd, user="root")

                # Daemon first: in Docker the frontend restart terminates
                # this very thread, so it must be the last action.
                restart_daemon(logger=logger)
                restart_frontend(delay_sec=3, logger=logger)

            install_deps = threading.Thread(target=install_dependencies)
            install_deps.start()
        except Exception as except_msg:
            error.append(except_msg)

    flash(gettext(
        "Installation of dependencies has been initiated. "
        "This can take a while. You can view the progress in the Dependency Log. "
        "At completion, the frontend and backend will be restarted."), "success")
    flash_success_errors(
        error, action, url_for('routes_settings.settings_diagnostic'))


def settings_regenerate_widget_html():
    try:
        logger.info("Starting widget HTML regeneration...")
        errors = generate_widget_html()
        
        if errors:
            logger.error(f"Widget HTML regeneration completed with errors: {errors}")
            raise Exception("; ".join(errors))
        
        logger.info("Widget HTML regeneration completed successfully.")

        logger.info("Reloading frontend in 10 seconds")
        reload_frontend(delay_sec=10, logger=logger)
        
    except Exception:
        logger.exception("Regenerating widget HTML")
        raise


def settings_diagnostic_upgrade_master():
    action = gettext("Set to Upgrade to Master")
    error = []

    if not error:
        try:
            # config is a package now (aot/config/__init__.py); the old single
            # module path aot/config.py no longer exists, which made this
            # "Set to Upgrade to Master" toggle a silent no-op.
            path_config = os.path.join(INSTALL_DIRECTORY, "aot/config/__init__.py")

            if not os.path.exists(path_config):
                logger.error(f"Path doesn't exist: {path_config}")
                return

            with open(path_config) as fin, NamedTemporaryFile(dir='.', delete=False) as fout:
                for line in fin:
                    if line.startswith("FORCE_UPGRADE_MASTER = False"):
                        line = "FORCE_UPGRADE_MASTER = True\n"
                    fout.write(line.encode('utf8'))
                os.rename(fout.name, path_config)
            os.chmod(path_config, stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
            set_user_grp(path_config, 'aot', 'aot')
            flash_success_errors(
                error, action, url_for('routes_settings.settings_diagnostic'))
            return
        except Exception as except_msg:
            error.append(except_msg)
            flash_success_errors(
                error, action, url_for('routes_settings.settings_diagnostic'))
            return
        finally:
            command = '/bin/bash {path}/aot/scripts/upgrade_commands.sh web-server-restart'.format(
                path=INSTALL_DIRECTORY)
            subprocess.Popen(command, shell=True)


def is_valid_hostname(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1] # strip exactly one dot from the right, if present
    allowed = re.compile("(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))


def settings_map_mod(form):
    """Modify common map location settings."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if not form.validate():
        for field, errors in form.errors.items():
            for error in errors:
                messages["error"].append(
                    gettext("Error in the %(field)s field - %(err)s",
                            field=getattr(form, field).label.text,
                            err=error))
        return messages

    lat = form.map_latitude.data
    lng = form.map_longitude.data
    label = form.map_location_label.data

    # Require both or neither
    if (lat is None) ^ (lng is None):
        messages["error"].append(gettext("Please enter both latitude and longitude, or leave both empty."))
        return messages

    try:
        mod_misc = Misc.query.first()
        if mod_misc is None:
            messages["error"].append(gettext("Misc settings row not found"))
            return messages

        mod_misc.map_latitude = lat
        mod_misc.map_longitude = lng
        mod_misc.map_location_label = label or ''

        db.session.commit()
        messages["success"].append(gettext("Map default location saved."))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages

import json

def settings_custom_ui_mod(form):
    from flask import request
    import re
    messages = {"success": [], "info": [], "warning": [], "error": []}
    try:
        mod_misc = Misc.query.first()
        try:
            theme_dict = json.loads(mod_misc.custom_theme_json or '{}')
        except Exception:
            theme_dict = {}

        from aot.aot_flask.forms.forms_settings import THEME_COLOR_FIELDS, migrate_theme_dict
        # 저장 전에 구 필드명(2026-07 통합 이전)을 정리 — 이후 for 루프가 신규
        # 필드셋만으로 채우므로, 여기서 마이그레이션해두면 이번 저장으로
        # theme_dict 에서 구 키가 영구히 사라진다(자연 치유).
        theme_dict = migrate_theme_dict(theme_dict)
        color_fields = THEME_COLOR_FIELDS
        color_re = re.compile(r'^#[0-9a-fA-F]{6}$')

        # Read color values directly from request.form — bypasses WTForms
        # field validation (e.g. IntegerField errors) that would block the save.
        # CSRF is already enforced at app level via CSRFProtect().
        for field in color_fields:
            val = request.form.get(field, '').strip()
            if val:
                if not color_re.match(val):
                    messages["error"].append(f"Invalid color format for {field}: {val}. Must be #RRGGBB")
                else:
                    theme_dict[field] = val
            else:
                # Field submitted blank (e.g. reset-to-default) — drop the stale
                # stored value instead of silently keeping the old custom color.
                theme_dict.pop(field, None)

        if not messages["error"]:
            mod_misc.custom_theme_json = json.dumps(theme_dict)
            mod_misc.custom_css = request.form.get('custom_css', '')

            new_layout = request.form.get('custom_layout', '') or ''
            # Guard: never write 'None' or garbage to layout file
            current_layout = mod_misc.custom_layout or ''
            if current_layout != new_layout:
                mod_misc.custom_layout = new_layout
                assure_path_exists(PATH_TEMPLATE_USER)
                update_layout(new_layout)

            mod_misc.brand_display = request.form.get('brand_display', '') or ''
            mod_misc.title_display = request.form.get('title_display', '') or ''
            val_override = request.form.get('hostname_override', '').strip()
            mod_misc.hostname_override = '' if val_override.lower() in ('none', '') else val_override
            if getattr(form, 'brand_image', None) and form.brand_image.data:
                mod_misc.brand_image = form.brand_image.data.read()
            height_str = request.form.get('brand_image_height', '').strip()
            if height_str.isdigit():
                mod_misc.brand_image_height = int(height_str)
            mod_misc.favicon_display = request.form.get('favicon_display', '')
            if getattr(form, 'brand_favicon', None) and form.brand_favicon.data:
                mod_misc.brand_favicon = form.brand_favicon.data.read()

            db.session.commit()
            # inject_variables()의 Misc 캐시(TTL 10초)를 즉시 만료시킨다. 이걸
            # 빼면 저장 직후 렌더되는 페이지가 최대 10초 동안 옛 테마를 들고
            # 있고, /custom.css 의 캐시 버전 토큰도 옛 값으로 나가 링크가
            # 그대로라 브라우저가 새 CSS 를 받지 않는다.
            invalidate_misc_cache()
            messages["success"].append("Custom UI and theme colors saved successfully.")
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def settings_chirpstack_mod(form):
    """Save the global ChirpStack LNS connection (gRPC server + API token + MQTT broker)."""
    messages = {"success": [], "info": [], "warning": [], "error": []}
    try:
        mod_misc = Misc.query.first()
        mod_misc.chirpstack_grpc_server = (form.chirpstack_grpc_server.data or '').strip()

        # form.chirpstack_api_token.data is the APIKey's unique_id (the SelectField
        # choices are built from APIKey.unique_id/name, not the raw key -- see
        # settings_chirpstack()). Resolve it to the actual key string here; storing
        # the unique_id directly (the prior bug) made every saved ChirpStack
        # connection authenticate with a UUID instead of the real token.
        selected_id = (form.chirpstack_api_token.data or '').strip()
        if selected_id:
            api_key = APIKey.query.filter_by(unique_id=selected_id).first()
            mod_misc.chirpstack_api_token = (api_key.key or '').strip() if api_key else ''
        else:
            mod_misc.chirpstack_api_token = ''

        mod_misc.chirpstack_mqtt_host = (form.chirpstack_mqtt_host.data or '').strip()
        try:
            mod_misc.chirpstack_mqtt_port = int(form.chirpstack_mqtt_port.data or 1883)
        except (TypeError, ValueError):
            mod_misc.chirpstack_mqtt_port = 1883
        db.session.commit()
        messages["success"].append(gettext("ChirpStack connection saved."))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))
    return messages
