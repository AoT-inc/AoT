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
from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)
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
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

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
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))
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
@login_required
def oauth_google_callback():
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    error = request.args.get('error')
    if error:
        flash("Google authorization was denied or failed: {}".format(error), "error")
        return redirect(url_for('routes_integrations.settings_integrations'))

    # Verify CSRF state.
    expected = session.pop(_OAUTH_STATE_KEY, None)
    got = request.args.get('state')
    if not expected or expected != got:
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


@blueprint.route('/settings/integrations/sync', methods=['POST'])
@login_required
def oauth_google_sync_now():
    """Run a two-way sync immediately for the current user's connection."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))
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
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

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
