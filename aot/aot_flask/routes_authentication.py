# coding=utf-8
# Trigger Reload
"""flask views that deal with user authentication."""

import datetime
import logging
import os
import secrets
import socket
import time

import flask_login
from flask import (flash, jsonify, make_response, redirect, render_template,
                   request, session, url_for)
from flask.blueprints import Blueprint
from flask_babel import gettext
from sqlalchemy import func

from aot.config import (INSTALL_DIRECTORY, LANGUAGES, LOGIN_ATTEMPTS,
                           LOGIN_BAN_SECONDS, LOGIN_LOG_FILE, SQL_DATABASE_AOT)
from aot.config_translations import TRANSLATIONS
from aot.databases.models import AlembicVersion, Misc, Role, User
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_authentication
from aot.aot_flask.utils import utils_general
from aot.utils import google_oauth
from aot.utils.utils import test_password, test_username

_GOOGLE_LOGIN_STATE_KEY = 'google_login_oauth_state'

logger = logging.getLogger(__name__)

blueprint = Blueprint(
    'routes_authentication',
    __name__,
    static_folder='../static',
    template_folder='../templates'
)


@blueprint.route('/create_admin', methods=('GET', 'POST'))
def create_admin():
    if admin_exists():
        flash(gettext(
            "Cannot access admin creation form if an admin user "
            "already exists."), "error")
        return redirect(url_for('routes_general.home'))

    # If login token cookie from previous session exists, delete
    if request.cookies.get('remember_token'):
        response = clear_cookie_auth()
        return response

    form_create_admin = forms_authentication.CreateAdmin()
    form_notice = forms_authentication.InstallNotice()
    form_language = forms_authentication.LanguageSelect()

    language = None

    try:
        host = Misc.query.first().hostname_override
    except:
        host = None
    if not host:
        host = socket.gethostname()

    # Find user-selected language in AoT/.language
    try:
        lang_path = os.path.join(INSTALL_DIRECTORY, ".language")
        if os.path.exists(lang_path):
            with open(lang_path) as f:
                language_read = f.read().split(":")[0]
                if language_read and language_read in LANGUAGES:
                    language = language_read
    except:
        pass

    if session.get('language'):
        language = session['language']

    if request.method == 'POST':
        if form_notice.acknowledge.data:
            mod_misc = Misc.query.first()
            mod_misc.dismiss_notification = 1
            db.session.commit()
        elif form_language.language.data:
            session['language'] = form_language.language.data
            language = form_language.language.data
        elif form_create_admin.validate():
            username = form_create_admin.username.data.lower()
            error = False
            if form_create_admin.password.data != form_create_admin.password_repeat.data:
                flash(gettext("Passwords do not match. Please try again."),
                      "error")
                error = True
            if not test_username(username):
                flash(gettext(
                    "Invalid username. Must be between 3 and 64 characters "
                    "and only contain letters and numbers."),
                    "error")
                error = True
            if not test_password(form_create_admin.password.data):
                flash(gettext(
                    "Invalid password. Must be between 4 and 64 characters "
                    "and only contain letters and numbers."),
                      "error")
                error = True
            if error:
                return render_template('create_admin.html',
                                       dict_translation=TRANSLATIONS,
                                       dismiss_notification=1,
                                       form_create_admin=form_create_admin,
                                       form_language=form_language,
                                       form_notice=form_notice,
                                       host=host,
                                       language=language,
                                       languages=LANGUAGES)

            new_user = User()
            new_user.name = username
            new_user.email = form_create_admin.email.data
            new_user.set_password(form_create_admin.password.data)
            new_user.role_id = 1  # Admin
            new_user.theme = '/static/css/bootstrap-4-themes/aot.css'

            # Find user-selected language in AoT/.language
            lang_path = os.path.join(INSTALL_DIRECTORY, ".language")
            try:
                if os.path.exists(lang_path):
                    with open(lang_path) as f:
                        language = f.read().split(":")[0]
                        if language and language in LANGUAGES:
                            new_user.language = language
            finally:
                if os.path.exists(lang_path):
                    try:
                        os.remove(lang_path)
                    except:
                        pass

            try:
                new_user.save()
                flash(gettext("User '%(user)s' successfully created. Please "
                              "log in below.", user=username),
                      "success")
                return redirect(url_for('routes_authentication.login_check'))
            except Exception as except_msg:
                flash(gettext("Failed to create user '%(user)s': %(err)s",
                              user=username,
                              err=except_msg), "error")
        else:
            utils_general.flash_form_errors(form_create_admin)

    dismiss_notification = Misc.query.first().dismiss_notification

    return render_template('create_admin.html',
                           dict_translation=TRANSLATIONS,
                           dismiss_notification=dismiss_notification,
                           form_create_admin=form_create_admin,
                           form_language=form_language,
                           form_notice=form_notice,
                           host=host,
                           language=language,
                           languages=LANGUAGES)


@blueprint.route('/login', methods=('GET', 'POST'))
def login_check():
    """Authenticate users of the web-UI."""
    if not admin_exists():
        return redirect('/create_admin')
    elif flask_login.current_user.is_authenticated:
        flash(gettext("Cannot access login page if you're already logged in"),
              "error")
        return redirect(url_for('routes_general.home'))

    settings = Misc.query.first()
    if settings.default_login_page == "password":
        return redirect(url_for('routes_authentication.login_password'))
    elif settings.default_login_page == "keypad":
        return redirect(url_for('routes_authentication.login_keypad'))
    return redirect(url_for('routes_authentication.login_password'))


@blueprint.route('/login_password', methods=('GET', 'POST'))
def login_password():
    """Authenticate users of the web-UI."""
    if not admin_exists():
        return redirect('/create_admin')
    elif flask_login.current_user.is_authenticated:
        flash(gettext("Cannot access login page if you're already logged in"),
              "error")
        return redirect(url_for('routes_general.home'))

    form_login = forms_authentication.Login()
    form_language = forms_authentication.LanguageSelect()

    language = None

    try:
        host = Misc.query.first().hostname_override
    except:
        host = None
    if not host:
        host = socket.gethostname()

    # Find user-selected language in AoT/.language
    try:
        lang_path = os.path.join(INSTALL_DIRECTORY, ".language")
        if os.path.exists(lang_path):
            with open(lang_path) as f:
                language_read = f.read().split(":")[0]
                if language and language in LANGUAGES:
                    language = language_read
    except:
        pass

    if session.get('language'):
        language = session['language']

    # Check if the user is banned from logging in (too many incorrect attempts)
    if banned_from_login():
        flash(gettext(
            "Too many failed login attempts. Please wait %(min)s "
            "minutes before attempting to log in again",
            min=int((LOGIN_BAN_SECONDS - session['ban_time_left']) / 60) + 1),
                "info")
    else:
        if request.method == 'POST':
            if form_language.language.data:
                session['language'] = form_language.language.data
            else:
                username = form_login.aot_username.data.lower()
                user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', 'unknown address')
                user = User.query.filter(
                    func.lower(User.name) == username).first()

                if not user:
                    login_log(username, 'NA', user_ip, 'NOUSER')
                    failed_login()
                elif not user.password_hash:
                    # Google-signup accounts have no password set yet.
                    login_log(username, 'NA', user_ip, 'FAIL')
                    failed_login()
                elif form_login.validate_on_submit():
                    matched_hash = User().check_password(
                        form_login.aot_password.data, user.password_hash)

                    # Encode stored password hash if it's a str
                    password_hash = user.password_hash
                    if isinstance(user.password_hash, str):
                        password_hash = user.password_hash.encode('utf-8')

                    if matched_hash == password_hash:
                        user = User.query.filter(User.name == username).first()
                        if not user.is_approved:
                            flash(gettext(
                                "Your account is awaiting administrator "
                                "approval."), "info")
                            return redirect('/login')
                        role_name = Role.query.filter(Role.id == user.role_id).first().name
                        login_log(username, role_name, user_ip, 'LOGIN')

                        # flask-login user
                        login_user = User()
                        login_user.id = user.id
                        login_user.name = user.name
                        remember_me = True if form_login.remember.data else False
                        flask_login.login_user(login_user, remember=remember_me)

                        return redirect(url_for('routes_general.home'))
                    else:
                        user = User.query.filter(User.name == username).first()
                        role_name = Role.query.filter(Role.id == user.role_id).first().name
                        login_log(username, role_name, user_ip, 'FAIL')
                        failed_login()
                else:
                    login_log(username, 'NA', user_ip, 'FAIL')
                    failed_login()

            return redirect('/login')

    return render_template('login_password.html',
                           dict_translation=TRANSLATIONS,
                           form_language=form_language,
                           form_login=form_login,
                           host=host,
                           language=language,
                           languages=LANGUAGES)


@blueprint.route('/login_keypad', methods=('GET', 'POST'))
def login_keypad():
    """Authenticate users of the web-UI (with keypad)"""
    if not admin_exists():
        return redirect('/create_admin')

    elif flask_login.current_user.is_authenticated:
        flash(gettext("Cannot access login page if you're already logged in"),
              "error")
        return redirect(url_for('routes_general.home'))

    try:
        host = Misc.query.first().hostname_override
    except:
        host = None
    if not host:
        host = socket.gethostname()

    # Check if the user is banned from logging in (too many incorrect attempts)
    if banned_from_login():
        flash(gettext(
            "Too many failed login attempts. Please wait %(min)s "
            "minutes before attempting to log in again",
            min=int((LOGIN_BAN_SECONDS - session['ban_time_left']) / 60) + 1),
                "info")

    return render_template('login_keypad.html',
                           dict_translation=TRANSLATIONS,
                           host=host)


@blueprint.route('/login_keypad_code/', methods=('GET', 'POST'))
def login_keypad_code_empty():
    """Forward to keypad when no code entered."""
    time.sleep(2)
    flash(gettext("Please enter a code"), "error")
    return redirect('/login_keypad')


@blueprint.route('/login_keypad_code/<code>', methods=('GET', 'POST'))
def login_keypad_code(code):
    """Check code from keypad."""
    if not admin_exists():
        return redirect('/create_admin')

    elif flask_login.current_user.is_authenticated:
        flash(gettext("Cannot access login page if you're already logged in"),
              "error")
        return redirect(url_for('routes_general.home'))

    try:
        host = Misc.query.first().hostname_override
    except:
        host = None
    if not host:
        host = socket.gethostname()

    # Check if the user is banned from logging in (too many incorrect attempts)
    if banned_from_login():
        flash(gettext(
            "Too many failed login attempts. Please wait %(min)s "
            "minutes before attempting to log in again",
            min=int((LOGIN_BAN_SECONDS - session['ban_time_left']) / 60) + 1),
                "info")
    else:
        user = User.query.filter(User.code == code).first()
        user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', 'unknown address')

        if not user:
            login_log(code, 'NA', user_ip, 'FAIL')
            failed_login()
            flash(gettext("Invalid Code"), "error")
            time.sleep(2)
        elif not user.is_approved:
            flash(gettext(
                "Your account is awaiting administrator approval."), "info")
            time.sleep(2)
        else:
            role_name = Role.query.filter(Role.id == user.role_id).first().name
            login_log(user.name, role_name, user_ip, 'LOGIN')

            # flask-login user
            login_user = User()
            login_user.id = user.id
            login_user.name = user.name
            remember_me = True
            flask_login.login_user(login_user, remember=remember_me)

            return redirect(url_for('routes_general.home'))

    return render_template('login_keypad.html',
                           dict_translation=TRANSLATIONS,
                           host=host)


@blueprint.route('/login/google/start', methods=['GET'])
def login_google_start():
    """Kick off 'Sign in with Google' from the login page (no session yet)."""
    if not admin_exists():
        return redirect('/create_admin')
    if flask_login.current_user.is_authenticated:
        return redirect(url_for('routes_general.home'))
    if not google_oauth.is_configured():
        flash(gettext("Google sign-in is not configured yet."), "warning")
        return redirect(url_for('routes_authentication.login_check'))

    # CSRF: random state stored in the session, verified on callback.
    state = secrets.token_urlsafe(24)
    session[_GOOGLE_LOGIN_STATE_KEY] = state
    consent_url = google_oauth.build_consent_url(state)
    if not consent_url:
        flash(gettext("Could not build the Google authorization URL."), "error")
        return redirect(url_for('routes_authentication.login_check'))
    return redirect(consent_url)


@blueprint.route('/login/google/callback', methods=['GET'])
def login_google_callback():
    """Complete 'Sign in with Google'. Matches the Google account's email to
    an existing User (logs in) or, if none matches, self-registers a new,
    unapproved User for an admin to review in Settings > Users."""
    if not admin_exists():
        return redirect('/create_admin')
    if flask_login.current_user.is_authenticated:
        return redirect(url_for('routes_general.home'))

    error = request.args.get('error')
    if error:
        flash(gettext(
            "Google sign-in was denied or failed: %(err)s", err=error), "error")
        return redirect(url_for('routes_authentication.login_check'))

    expected = session.pop(_GOOGLE_LOGIN_STATE_KEY, None)
    got = request.args.get('state')
    if not expected or expected != got:
        flash(gettext(
            "Authorization state mismatch — please try signing in again."),
              "error")
        return redirect(url_for('routes_authentication.login_check'))

    code = request.args.get('code')
    if not code:
        flash(gettext("No authorization code returned by Google."), "error")
        return redirect(url_for('routes_authentication.login_check'))

    tokens = google_oauth.exchange_code(code)
    if tokens.get('error'):
        flash(gettext(
            "Google sign-in failed: %(err)s", err=tokens['error']), "error")
        return redirect(url_for('routes_authentication.login_check'))

    email = google_oauth.fetch_account_email(tokens.get('access_token'))
    if not email:
        flash(gettext("Could not read your Google account's email address."),
              "error")
        return redirect(url_for('routes_authentication.login_check'))

    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', 'unknown address')
    user = User.query.filter(func.lower(User.email) == email.lower()).first()

    if user is not None:
        if not user.is_approved:
            flash(gettext(
                "Your account is awaiting administrator approval."), "info")
            return redirect(url_for('routes_authentication.login_check'))

        role = Role.query.filter(Role.id == user.role_id).first()
        login_log(user.name, role.name if role else 'NA', user_ip, 'LOGIN (Google)')

        login_user = User()
        login_user.id = user.id
        login_user.name = user.name
        flask_login.login_user(login_user, remember=True)

        _link_google_calendar_connection(user.id, tokens, email)
        return redirect(url_for('routes_general.home'))

    # No matching account by email — self-register, pending admin approval.
    guest_role = Role.query.filter_by(name='Guest').first()
    base_name = (email.split('@')[0] or 'google_user').lower()
    candidate = base_name
    suffix = 1
    while User.query.filter(func.lower(User.name) == candidate).first() is not None:
        suffix += 1
        candidate = "{}{}".format(base_name, suffix)

    new_user = User()
    new_user.name = candidate
    new_user.email = email
    new_user.role_id = guest_role.id if guest_role else None
    new_user.auth_provider = 'google'
    new_user.is_approved = False

    try:
        new_user.save()
    except Exception as except_msg:
        flash(gettext(
            "Failed to create your account: %(err)s", err=except_msg), "error")
        return redirect(url_for('routes_authentication.login_check'))

    login_log(candidate, 'NA', user_ip, 'SIGNUP (Google, pending approval)')
    flash(gettext(
        "Your Google account (%(email)s) was registered as '%(user)s' and is "
        "awaiting administrator approval before you can log in.",
        email=email, user=candidate), "info")
    return redirect(url_for('routes_authentication.login_check'))


def _link_google_calendar_connection(user_id, tokens, email):
    """Best-effort: if Google returned a refresh token during login, also
    establish/refresh this user's UserCalendarConnection (the same row used
    by Settings > Integrations) so signing in with Google also connects
    calendar sync, instead of requiring a second, separate connect step."""
    if not tokens.get('refresh_token'):
        return
    try:
        from datetime import timezone
        from aot.databases.models import UserCalendarConnection

        connection = (UserCalendarConnection.query
                      .filter_by(user_id=user_id, provider='google')
                      .first())
        if connection is None:
            connection = UserCalendarConnection(user_id=user_id, provider='google')
            db.session.add(connection)

        connection.set_refresh_token(tokens['refresh_token'])
        connection.set_access_token(tokens.get('access_token'))
        connection.token_expiry = datetime.datetime.fromtimestamp(
            tokens['expires_at'], tz=timezone.utc).replace(tzinfo=None)
        connection.scope = tokens.get('scope')
        connection.account_email = email
        connection.is_active = True
        if not connection.google_calendar_id:
            connection.google_calendar_id = 'primary'
        db.session.commit()
    except Exception:
        logger.exception("Failed to link Google calendar connection for user %s", user_id)


@blueprint.route("/logout")
@flask_login.login_required
def logout():
    """Log out of the web-ui."""
    user = User.query.filter(User.name == flask_login.current_user.name).first()
    role_name = Role.query.filter(Role.id == user.role_id).first().name
    login_log(user.name,
              role_name,
              request.environ.get('REMOTE_ADDR', 'unknown address'),
              'LOGOUT')
    # flask-login logout
    flask_login.logout_user()

    response = clear_cookie_auth()

    flash(gettext("Successfully logged out"), 'success')
    return response


@blueprint.route('/newremote/')
def newremote():
    """Verify authentication as a client computer to the remote admin."""
    username = request.args.get('user')
    pass_word = request.args.get('passw')

    user = User.query.filter(
        User.name == username).first()

    if user:
        if User().check_password(
                pass_word, user.password_hash) == user.password_hash:
            try:
                with open('/opt/AoT/aot/aot_flask/ssl_certs/cert.pem', 'r') as cert:
                    certificate_data = cert.read()
            except Exception:
                certificate_data = None
            return jsonify(status=0,
                           error_msg=None,
                           hash=str(user.password_hash),
                           certificate=certificate_data)
    return jsonify(status=1,
                   error_msg="Unable to authenticate with user and password.",
                   hash=None,
                   certificate=None)


@blueprint.route('/remote_login', methods=('GET', 'POST'))
def remote_admin_login():
    """Authenticate Remote Admin login."""
    password_hash = request.form.get('password_hash', None)
    username = request.form.get('username', None)

    if username and password_hash:
        user = User.query.filter(
            func.lower(User.name) == username).first()
    else:
        user = None

    if user and str(user.password_hash) == str(password_hash):
        login_user = User()
        login_user.id = user.id
        login_user.name = user.name
        flask_login.login_user(login_user, remember=False)
        return "Logged in via Remote Admin"
    else:
        return "ERROR"


@blueprint.route('/auth/')
@flask_login.login_required
def remote_auth():
    """Checks authentication for remote admin."""
    return "authenticated"


def admin_exists():
    """Verify that at least one admin user exists."""
    return User.query.filter_by(role_id=1).count()


def check_database_version_issue():
    if len(AlembicVersion.query.all()) > 1:
        flash(gettext(
            "A check of your database indicates there is an issue with your"
            " database version number. To resolve this issue, move"
            " your aot.db from %(path)s to a "
            "different location (or delete it) and a new database will be "
            "generated in its place.", path=SQL_DATABASE_AOT), "error")


def banned_from_login():
    """Check if the person at the login prompt is banned form logging in."""
    if not session.get('failed_login_count'):
        session['failed_login_count'] = 0
    if not session.get('failed_login_ban_time'):
        session['failed_login_ban_time'] = 0
    elif session['failed_login_ban_time']:
        session['ban_time_left'] = time.time() - session['failed_login_ban_time']
        if session['ban_time_left'] < LOGIN_BAN_SECONDS:
            return 1
        else:
            session['failed_login_ban_time'] = 0
    return 0


def failed_login():
    """Count the number of failed login attempts."""
    try:
        session['failed_login_count'] += 1
    except KeyError:
        session['failed_login_count'] = 1

    if session['failed_login_count'] > LOGIN_ATTEMPTS - 1:
        session['failed_login_ban_time'] = time.time()
        session['failed_login_count'] = 0
    else:
        flash(gettext('Failed Login (%(count)s/%(max)s)',
                      count=session['failed_login_count'],
                      max=LOGIN_ATTEMPTS), "error")


def login_log(user, group, ip, status):
    """Write to login log (timestamp in user-local timezone)."""
    from aot.utils.time_utils import utc_now, to_local
    with open(LOGIN_LOG_FILE, 'a+') as log_file:
        log_file.write(
            '{dt:%Y-%m-%d %H:%M:%S%z}: {stat} {user} ({grp}), {ip}\n'.format(
                dt=to_local(utc_now()), stat=status,
                user=user, grp=group, ip=ip))


def clear_cookie_auth():
    """Delete authentication cookies."""
    response = make_response(redirect('/login'))
    session.clear()
    response.set_cookie('remember_token', '', expires=0)
    return response
