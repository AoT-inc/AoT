# coding=utf-8
"""Regression check for the dashboard permission-denied toast.

Background: a read-only viewer (no edit_controllers) previously got the
GridStack autosave listener bound on any unlocked dashboard regardless of
their own permission (dashboard.js gated only on the dashboard's `locked`
column). A passive page load / window resize could fire an unauthorized
POST to /save_dashboard_layout; the server flashed a permission-denied
message and redirected, but since the call was AJAX the browser silently
followed the redirect and the flash sat queued in the session -- it only
surfaced later, on some unrelated next page load, as a global toast with
no apparent trigger.

This exercises the actual Flask routes (not just the permission-check
function in isolation) through create_app()'s real WSGI test client, using
the isolated sqlite DB conftest.py already sets up for the test session.
"""
import os
import sys
import unittest

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))

os.environ.setdefault('ALEMBIC_RUNNING', '1')


class DashboardPermissionToastFixture(unittest.TestCase):

    def setUp(self):
        from aot.aot_flask.app import create_app
        from aot.aot_flask.extensions import db
        from aot.databases.models import Role, User, Dashboard, Misc

        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Misc is a required singleton read on every page render.
        if not Misc.query.first():
            misc = Misc()
            db.session.add(misc)
            db.session.commit()

        viewer_role = Role.query.filter(Role.name == 'ToastTestViewer').first()
        if not viewer_role:
            viewer_role = Role()
            viewer_role.name = 'ToastTestViewer'
            viewer_role.edit_controllers = False
            viewer_role.view_settings = True
            db.session.add(viewer_role)
            db.session.commit()

        editor_role = Role.query.filter(Role.name == 'ToastTestEditor').first()
        if not editor_role:
            editor_role = Role()
            editor_role.name = 'ToastTestEditor'
            editor_role.edit_controllers = True
            editor_role.view_settings = True
            db.session.add(editor_role)
            db.session.commit()

        self.viewer = User.query.filter(User.name == 'toast_test_viewer').first()
        if not self.viewer:
            self.viewer = User()
            self.viewer.name = 'toast_test_viewer'
            self.viewer.email = 'viewer@example.com'
            self.viewer.is_enabled = True
            self.viewer.is_approved = True
            self.viewer.role_id = viewer_role.id
            self.viewer.set_password('correct horse battery staple')
            db.session.add(self.viewer)
            db.session.commit()

        self.editor = User.query.filter(User.name == 'toast_test_editor').first()
        if not self.editor:
            self.editor = User()
            self.editor.name = 'toast_test_editor'
            self.editor.email = 'editor@example.com'
            self.editor.is_enabled = True
            self.editor.is_approved = True
            self.editor.role_id = editor_role.id
            self.editor.set_password('correct horse battery staple')
            db.session.add(self.editor)
            db.session.commit()

        self.dashboard = Dashboard.query.filter(Dashboard.name == 'Toast Test Dashboard').first()
        if not self.dashboard:
            self.dashboard = Dashboard()
            self.dashboard.name = 'Toast Test Dashboard'
            self.dashboard.locked = False
            db.session.add(self.dashboard)
            db.session.commit()

        self.dashboard_id = self.dashboard.unique_id
        self.client = self.app.test_client()

    def tearDown(self):
        self.app_context.pop()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = user.get_id()
            sess['_fresh'] = True

    def _flashed_messages_left(self):
        """Peek at whatever is still queued in the session's flash store."""
        with self.client.session_transaction() as sess:
            return list(sess.get('_flashes', []))


class TestSaveDashboardLayoutPermission(DashboardPermissionToastFixture):
    """The endpoint the autosave listener actually calls."""

    def test_viewer_gets_403_json_not_a_redirect(self):
        self._login(self.viewer)
        resp = self.client.post(
            '/save_dashboard_layout',
            data='[]',
            content_type='application/json; charset=utf-8')
        # Old behavior: 302 redirect (the browser follows it silently for an
        # AJAX call, so the failure was invisible at the point of the request).
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json(), {'status': 'forbidden'})

    def test_viewer_denial_leaves_no_stale_flash(self):
        self._login(self.viewer)
        self.client.post(
            '/save_dashboard_layout',
            data='[]',
            content_type='application/json; charset=utf-8')
        # This is the actual bug: a queued flash surfaces as a toast on some
        # later, unrelated page load. Confirm nothing was queued.
        self.assertEqual(self._flashed_messages_left(), [])

    def test_editor_can_save(self):
        self._login(self.editor)
        resp = self.client.post(
            '/save_dashboard_layout',
            data='[]',
            content_type='application/json; charset=utf-8')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), 'success')


class TestDashboardPageReflectsPermission(DashboardPermissionToastFixture):
    """The page render must tell the client whether it may autosave."""

    def test_viewer_sees_can_edit_false_and_no_stray_toast(self):
        self._login(self.viewer)
        resp = self.client.get('/dashboard/{}'.format(self.dashboard_id))
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('window.AOT_CAN_EDIT_CONTROLLERS = false;', html)
        # No queued permission-denied toast should be present on a bare page load.
        self.assertNotIn('Insufficient permission', html)
        self.assertNotIn('showToast(', html.split('get_flashed_messages')[-1][:400]
                          if 'get_flashed_messages' not in html else '')

    def test_editor_sees_can_edit_true(self):
        self._login(self.editor)
        resp = self.client.get('/dashboard/{}'.format(self.dashboard_id))
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('window.AOT_CAN_EDIT_CONTROLLERS = true;', html)

    def test_viewer_page_load_after_denied_save_has_no_leftover_toast(self):
        """End-to-end reproduction of the reported bug: a denied autosave
        must not surface as a toast on the *next*, unrelated page load."""
        self._login(self.viewer)
        self.client.post(
            '/save_dashboard_layout',
            data='[]',
            content_type='application/json; charset=utf-8')
        resp = self.client.get('/dashboard/{}'.format(self.dashboard_id))
        html = resp.get_data(as_text=True)
        self.assertNotIn('Insufficient permission', html)
        self.assertNotIn('권한이 없습니다', html)


if __name__ == '__main__':
    unittest.main()
