# coding=utf-8
"""External integrations settings + OAuth flow (Google Calendar).

Kept in its own blueprint (not routes_settings) because it owns cross-cutting
OAuth concerns — a public callback route, CSRF-state in the session, per-user
token rows — that don't belong in the general settings module. Mirrors the
settings-page conventions (login_required + user_has_permission, layout-settings
template, active_settings highlight) so it slots into the same sidebar.

Phase B: connect/disconnect + admin config only. The actual push/pull sync
(Phase C/D) lives in a separate sync service; this module just establishes and
tears down the connection.
"""
import logging
import secrets
from datetime import datetime, timezone

import flask_login
from flask import (Blueprint, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_babel import gettext
from flask_login import login_required

from aot.databases.models import db, Misc, UserCalendarConnection
from aot.aot_flask.utils import utils_general
from aot.utils import google_oauth

logger = logging.getLogger('aot.aot_flask.integrations')

blueprint = Blueprint('routes_integrations',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')

_OAUTH_STATE_KEY = 'google_oauth_state'


def _epoch_to_naive_utc(epoch):
    """google_oauth returns absolute epoch seconds; SchedulerJobMeta-style
    columns store naive-UTC datetimes (project convention)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


@blueprint.route('/settings/integrations', methods=['GET'])
@login_required
def settings_integrations():
    # No permission gate beyond login: this page's own-connection section
    # (status/sync/disconnect) is self-scoped by current_user.id and must
    # stay reachable regardless of role (e.g. a Guest-role Google signup) —
    # only the admin-only client credential form is further gated, via
    # is_admin inside settings/integrations.html.
    misc = Misc.query.first()
    is_admin = getattr(flask_login.current_user, 'role_id', None) == 1
    connection = (UserCalendarConnection.query
                  .filter_by(user_id=flask_login.current_user.id, provider='google')
                  .first())

    return render_template(
        'settings/integrations.html',
        active_settings='integrations',
        misc=misc,
        is_admin=is_admin,
        google_configured=google_oauth.is_configured(),
        google_redirect_uri=google_oauth.redirect_uri(),
        config_source=google_oauth.config_source(),
        connection=connection,
    )


@blueprint.route('/settings/integrations/config', methods=['POST'])
@login_required
def settings_integrations_config():
    """Admin-only: save instance-wide Google OAuth client credentials + public
    base URL."""
    if not utils_general.user_has_permission('edit_settings') or \
            getattr(flask_login.current_user, 'role_id', None) != 1:
        flash("Your permissions do not allow this action", "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    misc = Misc.query.first()
    misc.google_oauth_client_id = (request.form.get('google_oauth_client_id') or '').strip()
    misc.google_oauth_client_secret = (request.form.get('google_oauth_client_secret') or '').strip()
    misc.oauth_public_base_url = (request.form.get('oauth_public_base_url') or '').strip().rstrip('/')
    # Google Picker API key (AI Library's Google Drive source) — a separate,
    # non-secret client-side key, not part of the OAuth client credential
    # pair above. See Misc.google_picker_api_key docstring.
    misc.google_picker_api_key = (request.form.get('google_picker_api_key') or '').strip()
    db.session.commit()
    flash("Google OAuth configuration saved.", "success")
    return redirect(url_for('routes_integrations.settings_integrations'))


@blueprint.route('/oauth/google/start', methods=['GET'])
@login_required
def oauth_google_start():
    # Self-scoped (connects the caller's own account) — no view_settings gate.
    if not google_oauth.is_configured():
        flash("Google OAuth is not configured yet (admin must set client credentials).", "warning")
        return redirect(url_for('routes_integrations.settings_integrations'))

    # CSRF: random state stored in the session, verified on callback.
    state = secrets.token_urlsafe(24)
    session[_OAUTH_STATE_KEY] = state
    consent_url = google_oauth.build_consent_url(state)
    if not consent_url:
        flash("Could not build the Google authorization URL.", "error")
        return redirect(url_for('routes_integrations.settings_integrations'))
    return redirect(consent_url)


@blueprint.route('/oauth/google/callback', methods=['GET'])
def oauth_google_callback():
    """Single physical OAuth callback. Google OAuth accepts only one
    registered redirect_uri per client (google_oauth.redirect_uri() is a
    single fixed value built from Misc.oauth_public_base_url), so both flows
    that start a Google consent round-trip land here:
      - 'connect my Google account' (oauth_google_start below — already
        logged in, session key _OAUTH_STATE_KEY)
      - 'sign in with Google' (routes_authentication.login_google_start —
        not logged in yet, session key _GOOGLE_LOGIN_STATE_KEY)
    Which one this request belongs to is told apart by which state-key
    round-trips, not by login status (checked first, before any
    @login_required-equivalent gate)."""
    got_state = request.args.get('state')

    from aot.aot_flask import routes_authentication
    login_expected = session.pop(routes_authentication._GOOGLE_LOGIN_STATE_KEY, None)
    if login_expected and login_expected == got_state:
        error = request.args.get('error')
        if error:
            flash(gettext(
                "Google sign-in was denied or failed: %(err)s", err=error), "error")
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
        return routes_authentication.complete_google_login(tokens, email)

    # Connect-flow: linking Google to the currently logged-in user's account.
    # Self-scoped — no view_settings gate beyond being logged in.
    if not flask_login.current_user.is_authenticated:
        flash(gettext("Please log in to access this page"), "error")
        return redirect(url_for('routes_authentication.login_check'))

    error = request.args.get('error')
    if error:
        flash("Google authorization was denied or failed: {}".format(error), "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    # Verify CSRF state.
    expected = session.pop(_OAUTH_STATE_KEY, None)
    if not expected or expected != got_state:
        flash("Authorization state mismatch — please try connecting again.", "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    code = request.args.get('code')
    if not code:
        flash("No authorization code returned by Google.", "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    tokens = google_oauth.exchange_code(code)
    if tokens.get('error'):
        flash("Google token exchange failed: {}".format(tokens['error']), "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    if not tokens.get('refresh_token'):
        # Without a refresh_token we can't sync unattended. Happens when the
        # account previously granted access and Google skipped re-consent;
        # prompt=consent should prevent this, but guard anyway.
        flash("Google did not return a refresh token. Remove AoT from your "
              "Google account's third-party access and try connecting again.", "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    email = google_oauth.fetch_account_email(tokens.get('access_token'))

    connection = (UserCalendarConnection.query
                  .filter_by(user_id=flask_login.current_user.id, provider='google')
                  .first())
    if connection is None:
        connection = UserCalendarConnection(
            user_id=flask_login.current_user.id, provider='google')
        db.session.add(connection)

    connection.set_refresh_token(tokens['refresh_token'])
    connection.set_access_token(tokens.get('access_token'))
    connection.token_expiry = _epoch_to_naive_utc(tokens['expires_at'])
    connection.scope = tokens.get('scope')
    connection.account_email = email
    connection.is_active = True
    connection.last_sync_status = None
    connection.last_sync_error = None
    if not connection.google_calendar_id:
        connection.google_calendar_id = 'primary'
    db.session.commit()

    # Start syncing now (first run ~10s out) instead of waiting for a restart.
    try:
        from aot.ai.services.ai_scheduler_service import ensure_calendar_sync_job
        ensure_calendar_sync_job(connection.id, connection.sync_interval_min or 15)
    except Exception:
        logger.exception("Failed to register calendar sync job for connection %s", connection.id)

    flash("Google Calendar connected{}.".format(
        " ({})".format(email) if email else ""), "success")
    return redirect(url_for('routes_integrations.settings_integrations'))


@blueprint.route('/api/v1/integrations/calendars', methods=['GET'])
@login_required
def api_available_calendars():
    """Calendars the current user can toggle in the calendar widget:
      - AoT native sources split by category (AI / User / Device) — the SAME
        buckets the Google category calendars mirror, and
      - the user's Google calendars EXCLUDING the AoT-managed category calendars
        (those are already represented by the native AoT sources, so offering
        them would double-show the same events).
    Returns {aot:[...], google:[...]}; google is [] if not connected/authorized.
    Domain-neutral: no 'farm' assumption — this runs at any kind of site."""
    from flask_babel import gettext
    from aot.utils.calendar_event_providers import _BUCKET_COLOR
    result = {'aot': [
        {'key': 'ai', 'name': gettext('AI'), 'color': _BUCKET_COLOR['ai']},
        {'key': 'user', 'name': gettext('User'), 'color': _BUCKET_COLOR['user']},
        {'key': 'device', 'name': gettext('Device'), 'color': _BUCKET_COLOR['device']},
    ], 'google': []}

    connection = (UserCalendarConnection.query
                  .filter_by(user_id=flask_login.current_user.id, provider='google')
                  .first())
    if connection is None or not connection.is_active:
        return jsonify(result)

    from aot.ai.services.calendar_sync_service import get_valid_access_token
    from aot.utils import google_calendar_api
    token = get_valid_access_token(connection)
    if not token:
        return jsonify(result)

    managed = set()
    for entry in (connection.category_calendars or {}).values():
        if isinstance(entry, dict) and entry.get('calendar_id'):
            managed.add(entry['calendar_id'])

    items, err = google_calendar_api.list_calendars(token)
    if not err:
        for it in items:
            cid = it.get('id')
            if not cid or cid in managed:
                continue
            result['google'].append({
                'id': cid,
                'name': it.get('summaryOverride') or it.get('summary') or cid,
                'color': it.get('backgroundColor') or '#4285F4',
                'primary': bool(it.get('primary')),
            })
    return jsonify(result)


@blueprint.route('/api/v1/integrations/google/events', methods=['GET'])
@login_required
def api_google_calendar_events():
    """Proxy a Google calendar's events to the widget (the browser has no token).
    calendar_id/start/end from FullCalendar. Read-only, mapped to FC shape."""
    calendar_id = request.args.get('calendar_id')
    if not calendar_id:
        return jsonify([])
    connection = (UserCalendarConnection.query
                  .filter_by(user_id=flask_login.current_user.id, provider='google')
                  .first())
    if connection is None or not connection.is_active:
        return jsonify([])

    from aot.ai.services.calendar_sync_service import get_valid_access_token
    from aot.utils import google_calendar_api
    token = get_valid_access_token(connection)
    if not token:
        return jsonify([])

    data, err = google_calendar_api.list_events(
        token, calendar_id, time_min=request.args.get('start'), time_max=request.args.get('end'))
    if err or not data:
        return jsonify([])

    events = []
    for e in data.get('items', []):
        if e.get('status') == 'cancelled':
            continue
        start = (e.get('start') or {})
        end = (e.get('end') or {})
        s = start.get('dateTime') or start.get('date')
        if not s:
            continue
        events.append({
            'id': 'gcal-{}-{}'.format(calendar_id, e.get('id')),
            'title': e.get('summary') or '(no title)',
            'start': s,
            'end': end.get('dateTime') or end.get('date'),
            'allDay': 'date' in start,
            'sourceType': 'google',
            'deepLink': e.get('htmlLink'),
            'readOnly': True,
        })
    return jsonify(events)


@blueprint.route('/settings/integrations/sync', methods=['POST'])
@login_required
def oauth_google_sync_now():
    """Run a two-way sync immediately for the current user's connection.
    Self-scoped — no view_settings gate beyond being logged in."""
    connection = (UserCalendarConnection.query
                  .filter_by(user_id=flask_login.current_user.id, provider='google')
                  .first())
    if connection is None:
        flash("No Google Calendar connection to sync.", "warning")
        return redirect(url_for('routes_integrations.settings_integrations'))
    from aot.ai.services.calendar_sync_service import sync_connection
    result = sync_connection(connection.id)
    if result.get('error'):
        flash("Sync failed: {}".format('; '.join(result['error'])), "error")
    else:
        push = result.get('push', {})
        pull = result.get('pull', {})
        flash("Synced. Pushed +{}/~{}/-{}, pulled +{}/~{}/-{}.".format(
            push.get('inserted', 0), push.get('updated', 0), push.get('deleted', 0),
            pull.get('imported', 0), pull.get('updated', 0), pull.get('cancelled', 0)), "success")
    return redirect(url_for('routes_integrations.settings_integrations'))


@blueprint.route('/settings/integrations/disconnect', methods=['POST'])
@login_required
def oauth_google_disconnect():
    """Self-scoped — no view_settings gate beyond being logged in."""
    connection = (UserCalendarConnection.query
                  .filter_by(user_id=flask_login.current_user.id, provider='google')
                  .first())
    if connection is not None:
        # Stop the sync job, best-effort revoke at Google, then drop our row + links.
        try:
            from aot.ai.services.ai_scheduler_service import remove_calendar_sync_job
            remove_calendar_sync_job(connection.id)
        except Exception:
            logger.exception("Failed to remove calendar sync job for connection %s", connection.id)
        google_oauth.revoke_token(connection.get_refresh_token())
        from aot.databases.models import CalendarEventLink
        CalendarEventLink.query.filter_by(connection_id=connection.id).delete()
        db.session.delete(connection)
        db.session.commit()
        flash("Google Calendar disconnected.", "success")
    return redirect(url_for('routes_integrations.settings_integrations'))
