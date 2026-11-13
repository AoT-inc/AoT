# coding=utf-8
"""MCP 공지 수정·삭제는 웹과 같은 규칙으로 판정한다 (2026-11-04).

MCP 프로세스에는 로그인 세션이 없다. 예전에는 `can_manage_post()` 가
`current_user` 로 판정해 승인 뒤 누구에게나 실패했다. 지금은 호출에 묶인
사용자(`write_scope`)로 판정한다.

규칙: Admin 이거나, 작성자 본인이면서 edit_settings 가 있을 때.
  - 작성자·관리자: 승인 뒤 실제로 바뀐다 / 지워진다.
  - 비작성자: 승인 큐에 들어가기 전에 거절된다.
"""
import json

from aot.aot_flask.extensions import db
from aot.databases.models import MCPConfirmation, NoticePost, User
from aot.tests import test_mcp_record_write_guard as rw
from aot.tools import mcp_safety_gate as gate

_TITLE = 'notice-perm-test'


class _NoticeFixture(rw._Fixture):

    def setUp(self):
        super().setUp()
        # 실제 Admin 역할(id 1)로 판정한다 — 웹 규칙이 role_id == 1 이다.
        admin = User(name=(rw._PREFIX + 'RealAdmin').lower(), role_id=1,
                     is_enabled=True)
        db.session.add(admin)
        db.session.commit()
        self.user_uuids['RealAdmin'] = admin.unique_id
        self.editor2 = User(name=(rw._PREFIX + 'Editor2').lower(),
                            role_id=self._user('Editor').role_id,
                            is_enabled=True)
        db.session.add(self.editor2)
        db.session.commit()
        self.user_uuids['Editor2'] = self.editor2.unique_id

    def tearDown(self):
        try:
            db.session.rollback()
            NoticePost.query.filter(NoticePost.title.like(_TITLE + '%')).delete(
                synchronize_session=False)
            db.session.commit()
        finally:
            super().tearDown()

    def _user(self, name):
        db.session.remove()
        return User.query.filter(User.name == (rw._PREFIX + name).lower()).first()

    def _as(self, who, tool, args):
        with self.app.test_request_context('/'):
            return self._call(tool, args, self._role(who),
                              scope_user_uuid=self.user_uuids[who])

    def _make(self, who):
        body = self._as(who, 'create_notice', {'title': _TITLE, 'body': 'b'})
        if body.get('status') == 'pending_approval':
            # 승인 실행은 승인자로 묶인다 — 만든 사람이 곧 작성자가 되게 본인이 승인.
            status, body = self._approve_and_run(body, who)
            self.assertEqual(status, 'executed', body)
        self.assertIsNotNone(body.get('notice_id'), body)
        return body['notice_id']

    def _post(self, nid):
        db.session.remove()
        return NoticePost.query.filter_by(unique_id=nid).first()

    def _approve_and_run(self, body, approver):
        cid = body['confirmation_id']
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        row.status = 'approved'
        row.user_id = self.user_uuids[approver]
        row.save()
        # 실제 MCP HTTP 서버는 요청 안에서 돈다(flash·url_for 가 요청 문맥을 쓴다).
        with self.app.test_request_context('/'):
            return gate.execute_approved(cid)


class TestAuthorRecorded(_NoticeFixture):

    def test_create_notice_records_the_connected_user(self):
        nid = self._make('Editor')
        self.assertEqual(self._post(nid).user_id, self._user('Editor').id)


class TestModify(_NoticeFixture):

    def _modify(self, who, nid, **kw):
        return self._as(who, 'modify_notice',
                        dict({'notice_id': nid, 'title': _TITLE + '-new'}, **kw))

    def test_author_edit_succeeds_after_approval(self):
        nid = self._make('Editor')
        body = self._modify('Editor', nid)
        if body.get('status') == 'pending_approval':
            status, result = self._approve_and_run(body, 'RealAdmin')
            self.assertEqual(status, 'executed', result)
        else:
            self.assertEqual(body.get('status'), 'modified', body)
        self.assertEqual(self._post(nid).title, _TITLE + '-new')

    def test_admin_edit_of_others_post_succeeds(self):
        nid = self._make('Editor')
        body = self._modify('RealAdmin', nid)
        if body.get('status') == 'pending_approval':
            status, result = self._approve_and_run(body, 'RealAdmin')
            self.assertEqual(status, 'executed', result)
        self.assertEqual(self._post(nid).title, _TITLE + '-new')

    def test_non_author_is_refused_before_approval(self):
        nid = self._make('Editor')
        before = self._mine_confirmations().count()
        body = self._modify('Editor2', nid)
        self.assertEqual(body.get('reason_code'), 'not_notice_owner', body)
        self.assertEqual(self._post(nid).title, _TITLE)
        db.session.remove()
        self.assertEqual(self._mine_confirmations().count(), before)


class TestDelete(_NoticeFixture):

    def _delete(self, who, nid):
        return self._as(who, 'delete_notice', {'notice_id': nid})

    def test_author_delete_succeeds_after_approval(self):
        nid = self._make('Editor')
        body = self._delete('Editor', nid)
        if body.get('status') == 'pending_approval':
            status, result = self._approve_and_run(body, 'RealAdmin')
            self.assertEqual(status, 'executed', result)
        self.assertIsNone(self._post(nid))

    def test_admin_delete_of_others_post_succeeds(self):
        nid = self._make('Editor')
        body = self._delete('RealAdmin', nid)
        if body.get('status') == 'pending_approval':
            status, result = self._approve_and_run(body, 'RealAdmin')
            self.assertEqual(status, 'executed', result)
        self.assertIsNone(self._post(nid))

    def test_non_author_is_refused_before_approval(self):
        nid = self._make('Editor')
        before = self._mine_confirmations().count()
        body = self._delete('Editor2', nid)
        self.assertEqual(body.get('reason_code'), 'not_notice_owner', body)
        self.assertIsNotNone(self._post(nid))
        db.session.remove()
        self.assertEqual(self._mine_confirmations().count(), before)
