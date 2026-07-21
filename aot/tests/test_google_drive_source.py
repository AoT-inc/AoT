# coding=utf-8
"""
Google Drive knowledge-library source tests.

Covers:
  - aot/utils/google_drive_api.py — export vs raw-download dispatch by
    mimeType (Google Docs/Sheets/Slides need export; everything else is a
    raw `alt=media` download), unsupported native-type error.
  - context_source_service._fetch_google_drive() — reuses the Calendar
    OAuth connection (no separate credential), partial-failure best-effort
    over a multi-file pick, and the required-config-json contract.
  - routes_ai_library._missing_config_error() for source_type='google_drive'.

In-memory sqlite, isolated app context — no live DB touched, no live Google
API call (mocked `requests`) — see feedback_never_test_against_live_db.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIGlobalSettings, AIKnowledgeChunk
from aot.databases.models.calendar_integration import UserCalendarConnection
from aot.databases.models.user import User
from aot.utils import google_drive_api


def _make_test_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestGoogleDriveApi(unittest.TestCase):
    """Pure HTTP-wrapper logic — no DB, mocked requests."""

    @patch('aot.utils.google_drive_api.requests.get')
    def test_regular_file_uses_raw_download_not_export(self, mock_get):
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 'f1', 'name': 'guide.pdf', 'mimeType': 'application/pdf'}
        media_resp = MagicMock(status_code=200, content=b'%PDF-1.4 fake bytes')
        mock_get.side_effect = [meta_resp, media_resp]

        content, filename, err = google_drive_api.fetch_file_content('TOKEN', 'f1')
        self.assertIsNone(err)
        self.assertEqual(filename, 'guide.pdf')
        self.assertEqual(content, b'%PDF-1.4 fake bytes')
        # second call must be the raw-media GET, not /export
        self.assertNotIn('/export', mock_get.call_args_list[1][0][0])
        self.assertEqual(mock_get.call_args_list[1][1]['params'], {'alt': 'media'})

    @patch('aot.utils.google_drive_api.requests.get')
    def test_google_doc_is_exported_as_text_plain_with_txt_extension(self, mock_get):
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 'd1', 'name': '재배 매뉴얼',
                                        'mimeType': 'application/vnd.google-apps.document'}
        export_resp = MagicMock(status_code=200, content='딸기 재배 안내 본문'.encode('utf-8'))
        mock_get.side_effect = [meta_resp, export_resp]

        content, filename, err = google_drive_api.fetch_file_content('TOKEN', 'd1')
        self.assertIsNone(err)
        self.assertEqual(filename, '재배 매뉴얼.txt')  # extension appended for downstream parser dispatch
        self.assertEqual(content.decode('utf-8'), '딸기 재배 안내 본문')
        export_call = mock_get.call_args_list[1]
        self.assertIn('/export', export_call[0][0])
        self.assertEqual(export_call[1]['params'], {'mimeType': 'text/plain'})

    @patch('aot.utils.google_drive_api.requests.get')
    def test_google_sheet_is_exported_as_csv(self, mock_get):
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 's1', 'name': '농가기록',
                                        'mimeType': 'application/vnd.google-apps.spreadsheet'}
        export_resp = MagicMock(status_code=200, content=b'date,value\n2026-07-01,12.3')
        mock_get.side_effect = [meta_resp, export_resp]

        content, filename, err = google_drive_api.fetch_file_content('TOKEN', 's1')
        self.assertIsNone(err)
        self.assertEqual(filename, '농가기록.csv')
        self.assertEqual(mock_get.call_args_list[1][1]['params'], {'mimeType': 'text/csv'})

    @patch('aot.utils.google_drive_api.requests.get')
    def test_unsupported_google_native_type_errors_clearly(self, mock_get):
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 'x1', 'name': '설문지', 'mimeType': 'application/vnd.google-apps.form'}
        mock_get.return_value = meta_resp

        content, filename, err = google_drive_api.fetch_file_content('TOKEN', 'x1')
        self.assertIsNone(content)
        self.assertIn('설문지', err)
        self.assertIn('form', err)

    @patch('aot.utils.google_drive_api.requests.get')
    def test_metadata_failure_propagates_as_error_not_exception(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404, text='Not Found')
        content, filename, err = google_drive_api.fetch_file_content('TOKEN', 'missing')
        self.assertIsNone(content)
        self.assertIn('404', err)


class TestFetchGoogleDrive(unittest.TestCase):
    """context_source_service._fetch_google_drive — the sync-time integration:
    resolves the connected user's OAuth connection (reusing Calendar sync's),
    downloads/exports each picked file, and best-effort concatenates text."""

    def setUp(self):
        self.app = _make_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.user = User(name='tester', role_id=1)
        self.user.save()
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _make_source(self, config):
        source = AIContextSource(
            facility_id='default', source_name='Google Drive', source_type='google_drive',
            parameter_name='google_drive.test', config_json=json.dumps(config),
            is_active=True, is_enabled=True,
        )
        source.save()
        return source

    def _connect_google(self, refresh_token='rt', access_token='at', expired=False, scope=None):
        from datetime import datetime, timedelta
        conn = UserCalendarConnection(user_id=self.user.id, provider='google', is_active=True)
        conn.set_refresh_token(refresh_token)
        conn.set_access_token(access_token)
        conn.token_expiry = datetime.utcnow() + (timedelta(minutes=-5) if expired else timedelta(hours=1))
        # Default includes drive.file — a connection made AFTER this feature
        # shipped. test_connection_predating_drive_scope_needs_reconnect
        # below covers the pre-existing-connection (no drive.file) case.
        conn.scope = scope if scope is not None else (
            'https://www.googleapis.com/auth/calendar '
            'https://www.googleapis.com/auth/userinfo.email '
            'https://www.googleapis.com/auth/drive.file openid')
        conn.save()
        return conn

    def test_errors_cleanly_with_no_connected_user(self):
        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'files': [{'id': 'f1', 'name': 'a.txt'}]})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(value)
        self.assertIn('connected', err.lower())

    def test_errors_cleanly_with_no_files_selected(self):
        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'connected_user_id': self.user.id, 'files': []})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(value)
        self.assertIn('file', err.lower())

    def test_errors_cleanly_when_google_account_not_connected(self):
        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'connected_user_id': self.user.id, 'files': [{'id': 'f1', 'name': 'a.txt'}]})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(value)
        self.assertIn('connect', err.lower())

    def test_connection_predating_drive_scope_needs_reconnect(self):
        """REGRESSION (found live 2026-07-21): a Calendar-only connection made
        before drive.file was added to SCOPES refreshes access_tokens fine —
        Google honors the old narrower grant — but every Drive call 403s.
        Confirmed against the real Google API with a real connected account
        before writing this test. Must be caught with a clear message, not
        surfaced as a raw Drive API error."""
        self._connect_google(scope='https://www.googleapis.com/auth/calendar '
                                    'https://www.googleapis.com/auth/userinfo.email openid')  # no drive.file
        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'connected_user_id': self.user.id, 'files': [{'id': 'f1', 'name': 'a.txt'}]})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(value)
        self.assertIn('reconnect', err.lower())

    @patch('aot.utils.google_drive_api.requests.get')
    def test_single_file_success_end_to_end(self, mock_get):
        self._connect_google()
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 'f1', 'name': 'guide.txt', 'mimeType': 'text/plain'}
        media_resp = MagicMock(status_code=200, content='딸기 재배 지침 본문입니다'.encode('utf-8'))
        mock_get.side_effect = [meta_resp, media_resp]

        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'connected_user_id': self.user.id,
                                    'files': [{'id': 'f1', 'name': 'guide.txt'}]})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(err)
        self.assertIn('guide.txt', value)
        self.assertIn('딸기 재배 지침 본문입니다', value)

    @patch('aot.utils.google_drive_api.requests.get')
    def test_partial_failure_still_yields_text_for_the_file_that_succeeded(self, mock_get):
        self._connect_google()

        def side_effect(url, headers=None, params=None, timeout=None):
            if 'good' in url:
                if params == {'alt': 'media'}:
                    return MagicMock(status_code=200, content=b'ok content')
                return MagicMock(status_code=200, json=lambda: {'id': 'good', 'name': 'ok.txt', 'mimeType': 'text/plain'})
            return MagicMock(status_code=404, text='Not Found')
        mock_get.side_effect = side_effect

        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({
            'connected_user_id': self.user.id,
            'files': [{'id': 'bad', 'name': 'missing.txt'}, {'id': 'good', 'name': 'ok.txt'}],
        })
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(err)  # one success is enough to not fail the whole sync
        self.assertIn('ok content', value)
        self.assertNotIn('missing.txt', value)  # the failing file contributes nothing to the digest

    @patch('aot.utils.google_drive_api.requests.get')
    def test_all_files_failing_returns_aggregate_error(self, mock_get):
        self._connect_google()
        mock_get.return_value = MagicMock(status_code=404, text='Not Found')

        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'connected_user_id': self.user.id,
                                    'files': [{'id': 'x', 'name': 'gone.txt'}]})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(value)
        self.assertIn('gone.txt', err)

    @patch('aot.ai.services.calendar_sync_service.google_oauth.refresh_access_token')
    @patch('aot.utils.google_drive_api.requests.get')
    def test_expired_access_token_is_refreshed_via_calendar_sync_service(self, mock_get, mock_refresh):
        """Confirms _fetch_google_drive reuses calendar_sync_service's
        get_valid_access_token (not a duplicate refresh implementation) —
        an expired token triggers exactly one refresh call."""
        self._connect_google(expired=True)
        mock_refresh.return_value = {'access_token': 'fresh-token', 'expires_at': 9999999999}
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 'f1', 'name': 'a.txt', 'mimeType': 'text/plain'}
        media_resp = MagicMock(status_code=200, content=b'content')
        mock_get.side_effect = [meta_resp, media_resp]

        from aot.ai.services.context_source_service import _fetch_google_drive
        source = self._make_source({'connected_user_id': self.user.id, 'files': [{'id': 'f1', 'name': 'a.txt'}]})
        value, err = _fetch_google_drive(source, json.loads(source.config_json))
        self.assertIsNone(err)
        mock_refresh.assert_called_once()
        # the refreshed token — not the stale stored one — must be what's used
        self.assertEqual(mock_get.call_args_list[0][1]['headers']['Authorization'], 'Bearer fresh-token')


class TestGoogleDriveSyncDispatch(unittest.TestCase):
    """sync_source()'s generic dispatch — google_drive routes through the
    SAME digest-hook branch as document/web_url (provenance defaults to
    'user_provided', unlike SmartFarmKorea's external_authority)."""

    def setUp(self):
        self.app = _make_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.user = User(name='tester', role_id=1)
        self.user.save()
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()
        conn = UserCalendarConnection(user_id=self.user.id, provider='google', is_active=True)
        conn.set_refresh_token('rt')
        conn.set_access_token('at')
        conn.scope = ('https://www.googleapis.com/auth/calendar '
                      'https://www.googleapis.com/auth/userinfo.email '
                      'https://www.googleapis.com/auth/drive.file openid')
        from datetime import datetime, timedelta
        conn.token_expiry = datetime.utcnow() + timedelta(hours=1)
        conn.save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('aot.utils.google_drive_api.requests.get')
    def test_sync_writes_knowledge_chunk_with_user_provided_provenance(self, mock_get):
        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {'id': 'f1', 'name': 'notes.txt', 'mimeType': 'text/plain'}
        media_resp = MagicMock(status_code=200, content='농가 자체 관측 기록'.encode('utf-8'))
        mock_get.side_effect = [meta_resp, media_resp]

        config = {'connected_user_id': self.user.id, 'files': [{'id': 'f1', 'name': 'notes.txt'}]}
        source = AIContextSource(
            facility_id='default', source_name='Google Drive', source_type='google_drive',
            parameter_name='google_drive.test', config_json=json.dumps(config),
            is_active=True, is_enabled=True,
        )
        source.save()

        from aot.ai.services.context_source_service import sync_source
        messages = sync_source(source.source_id)
        self.assertEqual(messages['error'], [])

        chunks = AIKnowledgeChunk.query.filter_by(source_id=source.source_id).all()
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].provenance, 'user_provided')  # not external_authority
        self.assertIn('농가 자체 관측 기록', chunks[0].digest_text)


class TestLibraryCatalogIncludesGoogleDrive(unittest.TestCase):
    """list_library_source_types_tool (the fix for the AI only ever
    recommending SmartFarmKorea) must include Google Drive now that it
    exists — otherwise it's the same blind spot, one source later."""

    def test_google_drive_appears_in_custom_types(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        r = T.list_library_source_types_tool()
        cust_keys = {e['key'] for e in r['custom_types']}
        self.assertIn('google_drive', cust_keys)


class TestMissingConfigError(unittest.TestCase):
    """routes_ai_library._missing_config_error for source_type='google_drive'
    — the two-part check (connected account AND files), not the generic
    single-string-field pattern the other custom types use."""

    def test_missing_connected_user_id(self):
        from aot.aot_flask.routes_ai_library import _missing_config_error
        source = MagicMock(source_type='google_drive',
                           config_json=json.dumps({'files': [{'id': 'f1'}]}))
        err = _missing_config_error(source)
        self.assertIsNotNone(err)
        self.assertIn('Connect', err)

    def test_missing_files(self):
        from aot.aot_flask.routes_ai_library import _missing_config_error
        source = MagicMock(source_type='google_drive',
                           config_json=json.dumps({'connected_user_id': 1, 'files': []}))
        err = _missing_config_error(source)
        self.assertIsNotNone(err)
        self.assertIn('Pick', err)

    def test_fully_configured_passes(self):
        from aot.aot_flask.routes_ai_library import _missing_config_error
        source = MagicMock(source_type='google_drive',
                           config_json=json.dumps({'connected_user_id': 1, 'files': [{'id': 'f1', 'name': 'a.txt'}]}))
        self.assertIsNone(_missing_config_error(source))


if __name__ == '__main__':
    unittest.main()
