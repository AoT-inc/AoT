"""AI 자막·수신함 카드 백엔드 (2026-10-19, P0).

screen_action(action='post') → ai_screen_cards 한 줄 + 허용된 화면별 ai_card 명령 →
sync 확장(ai_unread) → /api/v1/ai-inbox → 감사 'ai_card.post'. 계약:
plans/p0_contract_20261019.md ③⑤.
"""
import datetime
import importlib.util
import json
import os
import unittest
import uuid
from unittest import mock

from aot.utils import web_presence as wp

_AGENT = 'test:ai_screen_cards'

_IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) '
           'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 '
           'Mobile/15E148 Safari/604.1')
_WIN_CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
_ANDROID = ('Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
_IPAD = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
         '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')


def _wipe_presence():
    conn = wp._connect()
    try:
        with conn:
            conn.execute('DELETE FROM presence')
            conn.execute('DELETE FROM command')
    finally:
        conn.close()
    wp._last_write.clear()


class _Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        from aot.aot_flask.app import create_app
        cls.app = create_app()
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def _make_user(self, tag):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Role, User
        role = Role(name=tag, edit_settings=True, edit_controllers=True,
                    edit_users=False, use_ai_chat=True)
        db.session.add(role)
        db.session.commit()
        user = User(name=tag, role_id=role.id, is_enabled=True)
        db.session.add(user)
        db.session.commit()
        return user

    def setUp(self):
        _wipe_presence()
        from aot.utils import ai_card_fetch
        ai_card_fetch._pending.clear()      # 앞 시험이 finish 하지 않은 성공 시도가 상한을 세지 않게
        self.tag = 'zz_aicard_' + uuid.uuid4().hex[:6]
        self.user = self._make_user(self.tag)
        self.other = self._make_user(self.tag + '_o')
        self.uid = self.user.unique_id
        self.pk = self.user.id
        self.client = self.app.test_client()
        self.key_ids = []

    def tearDown(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Role, User, UserAPIKey
        from aot.databases.models.ai_screen_card import AIScreenCard
        from aot.databases.models import AuditLog
        from aot.databases.models.mcp_audit import MCPAuditLog
        db.session.rollback()
        ids = [self.user.id, self.other.id]
        from aot.databases.models.ai_card_attachment import AICardAttachment
        AICardAttachment.query.filter(AICardAttachment.user_id.in_(ids)).delete(
            synchronize_session=False)
        AIScreenCard.query.filter(AIScreenCard.user_id.in_(ids)).delete(
            synchronize_session=False)
        AuditLog.query.filter(AuditLog.action == 'ai_card.post',
                              AuditLog.user_id.in_(ids)).delete(
            synchronize_session=False)
        UserAPIKey.query.filter(UserAPIKey.user_id.in_(ids)).delete(
            synchronize_session=False)
        MCPAuditLog.query.filter(MCPAuditLog.agent_id == _AGENT).delete()
        User.query.filter(User.name.in_([self.tag, self.tag + '_o'])).delete(
            synchronize_session=False)
        Role.query.filter(Role.name.in_([self.tag, self.tag + '_o'])).delete(
            synchronize_session=False)
        db.session.commit()
        db.session.remove()
        _wipe_presence()

    # ── helpers ────────────────────────────────────────────────────────────
    def _screen(self, key, ua=_IPHONE, allowed=True, visible=True, uid=None):
        uid = uid or self.uid
        wp.record(uid, key, ua, '/dashboard', 'page')
        wp.sync(uid, key, state={}, allowed=allowed, visible=visible)

    def _post(self, args=None, role=None, user=None):
        from aot.tools.tool_execution import _execute_tool
        body = {'action': 'post', 'message': 'Hello **farm**'}
        body.update(args or {})
        content = _execute_tool(self.app, 'screen_action', body, agent_id=_AGENT,
                                role=role, scope_user_uuid=user or self.uid,
                                transport='mcp_http')
        return json.loads(content[0]['text'])

    def _cards(self, user_pk=None):
        from aot.databases.models.ai_screen_card import AIScreenCard
        return AIScreenCard.query.filter(
            AIScreenCard.user_id == (user_pk or self.pk)).order_by(
            AIScreenCard.id).all()

    def _commands(self, key=None):
        conn = wp._connect()
        try:
            q = 'SELECT * FROM command WHERE action=?'
            a = ['ai_card']
            if key:
                q += ' AND browser_key=?'
                a.append(key)
            return [dict(r) for r in conn.execute(q + ' ORDER BY created_at', a)]
        finally:
            conn.close()

    def _login(self, user=None):
        from flask import g
        for name in ('_aot_scope_cache', '_login_user'):
            if hasattr(g, name):
                delattr(g, name)
        with self.client.session_transaction() as sess:
            sess['_user_id'] = (user or self.user).get_id()
            sess['_fresh'] = True

    def _backdate(self, minutes=0, days=0):
        """내 카드의 만든 시각을 과거로 옮겨 분당/일 제한 창을 지나게 한다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models.ai_screen_card import AIScreenCard
        delta = datetime.timedelta(minutes=minutes, days=days)
        from aot.databases.models.ai_card_attachment import AICardAttachment
        for c in AIScreenCard.query.filter(AIScreenCard.user_id == self.pk).all():
            c.created_at = c.created_at - delta
        for a in AICardAttachment.query.filter(AICardAttachment.user_id == self.pk).all():
            a.created_at = a.created_at - delta
        db.session.commit()


class PostTest(_Base):

    # 완료 기준 ①
    def test_post_saves_card_and_sends_ai_card_to_allowed_screens_only(self):
        self._screen('kphone' + 'a' * 14)
        self._screen('kpc' + 'b' * 17, ua=_WIN_CHROME)
        self._screen('koff' + 'c' * 16, ua=_ANDROID, allowed=False)
        # 화면이 둘 이상이면 지정해야 한다(없으면 test_several_screens_need_a_choice).
        out = self._post({'title': 'Report', 'screen': 'kphone' + 'a' * 14})
        self.assertEqual(out['status'], 'posted', out)
        self.assertFalse(out['truncated'])
        self.assertEqual(out['shown_on'], ['iPhone · Safari'])
        self.assertNotIn('note', out)
        cards = self._cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(out['card'], cards[0].unique_id[:8])
        self.assertEqual((cards[0].title, cards[0].body), ('Report', 'Hello **farm**'))
        self.assertEqual(cards[0].kind, 'text')
        self.assertEqual(cards[0].source_label, 'AI')
        self.assertGreater(cards[0].expires_at, cards[0].created_at +
                           datetime.timedelta(days=29))
        cmds = self._commands()
        self.assertEqual(len(cmds), 1)
        self.assertEqual({c['browser_key'] for c in cmds}, {'kphone' + 'a' * 14})
        self.assertEqual(self._commands('kpc' + 'b' * 17), [])
        self.assertEqual(self._commands('koff' + 'c' * 16), [])
        # 화면이 가져가는 모양.
        got = wp.sync(self.uid, 'kphone' + 'a' * 14, allowed=True)['commands']
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]['action'], 'ai_card')
        self.assertIs(got[0]['ask'], False)
        a = got[0]['args']
        self.assertEqual(a['card'], cards[0].unique_id)
        self.assertEqual((a['title'], a['message'], a['source']),
                         ('Report', 'Hello **farm**', 'AI'))
        self.assertTrue(a['at'].endswith('Z'))
        self.assertEqual(a['describe'], 'show an AI card')

    def test_several_screens_need_a_choice_and_nothing_is_posted(self):
        for i in range(4):
            self._screen('k%02d' % i + 'x' * 17)
        out = self._post()
        self.assertEqual(out['status'], 'error', out)
        self.assertIn('Which screen should show the card', out['error'])
        self.assertIn('k00' + 'x' * 9, out['error'])      # 화면 목록이 함께 온다
        self.assertEqual(self._cards(), [])
        self.assertEqual(self._commands(), [])

    def test_hidden_screen_is_open_and_still_gets_it_but_away_does_not(self):
        self._screen('khid' + 'a' * 16, visible=False)
        out = self._post()
        self.assertEqual(out['shown_on'], ['iPhone · Safari'])

    # 완료 기준 ②
    def test_a_named_screen_gets_the_card_even_with_several_open(self):
        self._screen('ks1' + 'a' * 17)
        self._screen('ks2' + 'b' * 17, ua=_WIN_CHROME)
        out = self._post({'screen': 'ks2' + 'b' * 17})
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(out['shown_on'], ['Windows PC · Chrome'])
        self.assertNotIn('confirm_token', out)
        bad = self._post({'screen': 'zzz', 'message': 'second card'})
        self.assertEqual(bad['status'], 'error')

    # 완료 기준 ③
    def test_all_off_is_refused_and_no_presence_saves_only(self):
        self._screen('koff' + 'a' * 16, allowed=False)
        out = self._post()
        self.assertEqual(out['status'], 'error')
        self.assertIn('AI control is off on all of the user', out['error'])
        self.assertIn('AI settings', out['error'])
        self.assertEqual(self._cards(), [])
        _wipe_presence()
        out = self._post()
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(out['shown_on'], [])
        self.assertIn("Saved to the user's AoT AI inbox", out['note'])
        self.assertEqual(len(self._cards()), 1)
        self.assertEqual(self._commands(), [])

    # 완료 기준 ④
    def test_title_and_body_limits_and_title_derivation(self):
        out = self._post({'title': 'T' * 200, 'message': 'x' * 2500})
        self.assertTrue(out['truncated'])
        c = self._cards()[0]
        self.assertEqual(len(c.title), 80)
        self.assertEqual(len(c.body), 2000)
        # 제목이 없으면 본문 첫 비지 않은 줄에서 '#' 을 뗀다.
        self._post({'message': '\n\n## Greenhouse 2 is hot\nbody'})
        self.assertEqual(self._cards()[-1].title, 'Greenhouse 2 is hot')
        self._post({'title': '  \n ', 'message': '# ' + 'L' * 100})
        self.assertEqual(self._cards()[-1].title, 'L' * 80)
        # 제목은 한 줄·제어문자 제거.
        self._post({'title': 'a\nb\x07c', 'message': 'm'})
        self.assertEqual(self._cards()[-1].title, 'a b c')
        for bad in ('', '   \n', None):
            args = {'message': bad}
            out = self._post(args)
            self.assertEqual((out['status'], out['error']),
                             ('error', 'message is required.'))
        n = len(self._cards())
        self.assertEqual(self._post({'message': 'ok'})['status'], 'posted')
        self.assertEqual(len(self._cards()), n + 1)

    def test_html_is_stored_verbatim(self):
        raw = '<img src=x onerror=alert(1)> [x](javascript:alert(1))'
        self._post({'message': raw})
        self.assertEqual(self._cards()[0].body, raw)

    # 완료 기준 ⑤
    def test_rate_limit_six_per_minute_and_hundred_per_day(self):
        for i in range(6):
            self.assertEqual(self._post({'message': 'm%d' % i})['status'], 'posted')
        err = self._post()
        self.assertEqual(err['status'], 'error')
        self.assertIn('Too many AI inbox messages', err['error'])
        self.assertEqual(len(self._cards()), 6)
        # 남의 한도는 따로.
        self.assertEqual(self._post(user=self.other.unique_id)['status'], 'posted')
        # 분 창이 지나면 다시 가능, 하루 100 에서 멈춘다.
        self._backdate(minutes=2)
        for i in range(94):
            from aot.utils import ai_screen_cards as C
            C.create(self.pk, 't', 'b', 'AI', now=C._now() - datetime.timedelta(hours=2))
        self.assertEqual(len(self._cards()), 100)
        err = self._post()
        self.assertEqual(err['status'], 'error')
        self.assertIn('Daily limit of 100', err['error'])
        self._backdate(days=1)
        self.assertEqual(self._post()['status'], 'posted')

    # 보안 리뷰 M2 — 양방향 제어문자는 제목·본문·출처 모두에서 떨어진다.
    def test_bidi_control_characters_are_stripped_from_title_body_and_source(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import UserAPIKey
        from aot.tools.mcp_auth import RoleInfo
        bidi = '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u061c'
        key = UserAPIKey(user_id=self.pk, name='Cl' + bidi + 'aude',
                         key_hash=uuid.uuid4().hex + uuid.uuid4().hex)
        db.session.add(key)
        db.session.commit()
        role = RoleInfo('r', True, self.pk, True, True, True, None, key.unique_id)
        self._post({'title': 'Ti' + bidi + 'tle',
                    'message': '\u202e[gol](https://rk.toa.evil.com)\nline' + bidi + '2'},
                   role=role)
        c = self._cards()[-1]
        self.assertEqual((c.title, c.source_label), ('Title', 'Claude'))
        self.assertEqual(c.body, '[gol](https://rk.toa.evil.com)\nline2')
        # 제목이 없어 본문에서 따올 때도 마찬가지.
        self._post({'message': '## He' + bidi + 'llo\nbody'})
        self.assertEqual(self._cards()[-1].title, 'Hello')
        for ch in bidi:
            self.assertNotIn(ch, c.title + c.body + c.source_label)

    # 보안 리뷰 L1 — 검사와 저장 사이의 경쟁: 동시에 10개가 와도 분당 6장을 넘지 않는다.
    def test_concurrent_posts_cannot_exceed_the_per_minute_limit(self):
        import threading
        import time
        from aot.utils import ai_screen_cards as C

        real, real_create = C.check_rate, C.create
        results, creates, app, pk = [], [], self.app, self.pk

        def counting_create(*a, **kw):
            creates.append(1)
            return real_create(*a, **kw)

        def slow_check(*a, **kw):
            out = real(*a, **kw)
            time.sleep(0.05)   # 검사~저장 사이를 벌려 락이 없으면 거의 확실히 겹치게 한다
            return out

        def worker(i):
            with app.app_context():
                try:
                    card, problem = C.create_limited(pk, 't%d' % i, 'b', 'AI')
                    results.append((card is not None, problem))
                finally:
                    from aot.aot_flask.extensions import db
                    db.session.remove()

        with mock.patch.object(C, 'check_rate', side_effect=slow_check), \
                mock.patch.object(C, 'create', side_effect=counting_create):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        from aot.aot_flask.extensions import db
        db.session.rollback()
        self.assertEqual(len(results), 10)
        self.assertEqual(sum(1 for ok, _ in results if ok), C.RATE_PER_MIN)
        # 락 덕에 넘칠 요청은 저장까지 가지도 않는다(저장 뒤 재계수는 다른 워커용 2차 방어).
        self.assertEqual(len(creates), C.RATE_PER_MIN)
        self.assertTrue(all('Too many AI inbox messages' in p
                            for ok, p in results if not ok))
        self.assertEqual(len(self._cards()), C.RATE_PER_MIN)

    def test_after_save_recount_rolls_back_an_overflowing_card(self):
        """다른 워커가 락 바깥에서 먼저 채웠다면(재계수) 방금 넣은 카드를 도로 지운다."""
        from aot.utils import ai_screen_cards as C
        real = C.create

        def create_then_sneak_one_in(*a, **kw):
            card = real(*a, **kw)
            real(self.pk, 'other worker', 'b', 'AI')   # 락 밖의 다른 프로세스가 끼어든 것처럼
            return card

        for i in range(C.RATE_PER_MIN - 1):
            C.create(self.pk, 't%d' % i, 'b', 'AI')
        with mock.patch.object(C, 'create', side_effect=create_then_sneak_one_in):
            card, problem = C.create_limited(self.pk, 'mine', 'b', 'AI')
        self.assertIsNone(card)
        self.assertIn('Too many AI inbox messages', problem)
        titles = [c.title for c in self._cards()]
        self.assertNotIn('mine', titles)
        self.assertEqual(len(titles), C.RATE_PER_MIN)

    # 완료 기준 ⑥
    def test_toast_is_a_hidden_alias_for_post(self):
        from aot.tools import tool_registry
        spec = next(t for t in tool_registry._MCP_TOOL_PAYLOADS
                    if t['tool_name'] == 'screen_action')
        enum = spec['input_schema']['properties']['action']['enum']
        self.assertIn('post', enum)
        self.assertNotIn('toast', enum)
        self.assertEqual(list(spec['input_schema']['properties']).count('title'), 1)
        self._screen('kt' + 'a' * 18)
        out = self._post({'action': 'toast', 'message': 'old style'})
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(self._cards()[0].body, 'old style')
        self.assertEqual(self._commands()[0]['action'], 'ai_card')

    # 완료 기준 ⑦
    def test_ignored_arguments_are_reported(self):
        out = self._post({'page': 'map', 'widget': 'w', 'center': True,
                          'op': 'zoom', 'value': 3})
        self.assertEqual(out['status'], 'posted')
        names = out['ignored']['args']
        for n in ('page', 'widget', 'center', 'op', 'value'):
            self.assertIn(n, names)
        self.assertNotIn('title', names)
        self.assertNotIn('ignored', self._post({'message': 'plain'}))

    def test_source_comes_from_the_authenticated_key_not_arguments(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import UserAPIKey
        from aot.tools.mcp_auth import RoleInfo
        key = UserAPIKey(user_id=self.pk, name='Claude Desktop',
                         key_hash=uuid.uuid4().hex + uuid.uuid4().hex)
        theirs = UserAPIKey(user_id=self.other.id, name='Evil',
                            key_hash=uuid.uuid4().hex + uuid.uuid4().hex)
        db.session.add_all([key, theirs])
        db.session.commit()
        role = RoleInfo('r', True, self.pk, True, True, True, None, key.unique_id)
        self._post({'ai_key_id': theirs.unique_id, 'ai_link_id': 99, 'message': 'from the key'}, role=role)
        c = self._cards()[-1]
        self.assertEqual((c.source_label, c.source_key_id),
                         ('Claude Desktop', key.unique_id))
        # 키 없는 연결에서 인자로 남의 키를 대도 'AI'.
        self._post({'ai_key_id': theirs.unique_id}, role=None)
        self.assertEqual(self._cards()[-1].source_label, 'AI')
        self.assertIsNone(self._cards()[-1].source_key_id)

    # 완료 기준 ⑫
    def test_audit_log_row(self):
        from aot.databases.models import AuditLog
        self._screen('ka' + 'a' * 18)
        out = self._post({'title': 'Audit me', 'message': 'twelve chars'})
        rows = AuditLog.query.filter(AuditLog.action == 'ai_card.post',
                                     AuditLog.user_id == self.pk).all()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r.target_type, r.target_name, r.username),
                         ('AICard', 'AI', self.tag))
        self.assertEqual(r.target_id, self._cards()[0].unique_id)
        self.assertTrue(r.target_id.startswith(out['card']))
        self.assertEqual(r.detail, 'Audit me (12 chars) → 1 screens')
        # 거부·검증 실패는 기록하지 않는다.
        self._post({'message': ''})
        self.assertEqual(AuditLog.query.filter(
            AuditLog.action == 'ai_card.post', AuditLog.user_id == self.pk).count(), 1)


class ServiceTest(_Base):
    """완료 기준 ⑨ — 목록·읽음·모두읽음·닫기·만료 제외·purge·300 상한."""

    def setUp(self):
        super().setUp()
        from aot.utils import ai_screen_cards as C
        self.C = C

    def _mk(self, n, user=None, **kw):
        return [self.C.create((user or self.user).id, 't%d' % i, 'b', 'AI', **kw)
                for i in range(n)]

    def test_list_read_all_dismiss_and_expiry(self):
        C = self.C
        cards = self._mk(5)
        rows, more = C.list_cards(self.pk, limit=3)
        self.assertEqual([c.title for c in rows], ['t4', 't3', 't2'])
        self.assertTrue(more)
        rows, more = C.list_cards(self.pk, limit=3, before=rows[-1].unique_id)
        self.assertEqual([c.title for c in rows], ['t1', 't0'])
        self.assertFalse(more)
        self.assertEqual(C.unread_count(self.pk), 5)
        self.assertTrue(C.mark_read(self.pk, cards[0].unique_id))
        self.assertEqual(C.unread_count(self.pk), 4)
        self.assertTrue(C.dismiss(self.pk, cards[1].unique_id))     # 읽음 포함
        self.assertEqual(C.unread_count(self.pk), 3)
        self.assertNotIn('t1', [c.title for c in C.list_cards(self.pk)[0]])
        self.assertFalse(C.dismiss(self.pk, cards[1].unique_id))    # 이미 닫힘
        # 만료는 목록·미읽음에서 빠진다.
        from aot.aot_flask.extensions import db
        cards[4].expires_at = C._now() - datetime.timedelta(seconds=1)
        db.session.commit()
        self.assertEqual(C.unread_count(self.pk), 2)
        self.assertNotIn('t4', [c.title for c in C.list_cards(self.pk)[0]])
        self.assertEqual(C.read_all(self.pk), 2)
        self.assertEqual(C.unread_count(self.pk), 0)
        # 알 수 없는 before 는 None(404 용).
        self.assertIsNone(C.list_cards(self.pk, before=str(uuid.uuid4())))

    def test_other_users_cards_do_not_exist_for_me(self):
        C = self.C
        theirs = self._mk(2, user=self.other)
        self.assertEqual(C.list_cards(self.pk)[0], [])
        self.assertEqual(C.unread_count(self.pk), 0)
        for fn in (C.mark_read, C.dismiss):
            self.assertFalse(fn(self.pk, theirs[0].unique_id))
        self.assertIsNone(C.list_cards(self.pk, before=theirs[0].unique_id))
        self.assertEqual(C.read_all(self.pk), 0)
        self.assertEqual(C.unread_count(self.other.id), 2)    # 남의 것은 그대로

    def test_purge_expired_globally_and_cap_300_oldest_first(self):
        C = self.C
        from aot.aot_flask.extensions import db
        from aot.databases.models.ai_screen_card import AIScreenCard
        old = self._mk(2, user=self.other)
        for c in old:
            c.expires_at = C._now() - datetime.timedelta(days=1)
        db.session.commit()
        self._mk(1)                         # 다른 사람의 post 가 만료를 전역으로 지운다
        self.assertEqual(len(self._cards(self.other.id)), 0)
        self.assertEqual(C.AI_CARD_KEEP_DAYS, 30)
        # 300 상한: 301번째를 만들면 가장 오래된 것이 사라진다.
        db.session.bulk_save_objects([AIScreenCard(
            user_id=self.pk, expires_at=C._now() + datetime.timedelta(days=5),
            title='bulk%d' % i, body='b') for i in range(299)])
        db.session.commit()
        self.assertEqual(len(self._cards()), 300)
        C.create(self.pk, 'newest', 'b', 'AI')
        cards = self._cards()
        self.assertEqual(len(cards), 300)
        titles = [c.title for c in cards]
        self.assertNotIn('t0', titles)              # 가장 오래된 것
        self.assertEqual(titles[-1], 'newest')

    def test_item_shape(self):
        c = self._mk(1)[0]
        item = self.C.to_item(c)
        self.assertEqual(set(item), {'id', 'title', 'message', 'source',
                                     'created_at', 'read', 'kind', 'pinned',
                                     'note_id', 'notice_id', 'file', 'files'})  # P1·P2·P5 추가 칸
        self.assertTrue(item['created_at'].endswith('Z'))
        self.assertFalse(item['read'])
        self.assertEqual((item['kind'], item['pinned'], item['note_id'], item['file']),
                         ('text', False, None, None))


class SyncAndApiTest(_Base):

    def _sync(self, **body):
        body.setdefault('allowed', True)
        return self.client.post('/api/v1/screen/sync', json=body,
                                headers={'User-Agent': _IPHONE})

    def _with_cards(self, n=3, user=None):
        from aot.utils import ai_screen_cards as C
        return [C.create((user or self.user).id, 'T%d' % i, 'body %d' % i, 'Bot')
                for i in range(n)]

    # 완료 기준 ⑩
    def test_sync_returns_ai_unread_only_when_asked(self):
        self._login()
        self._with_cards(3)
        with mock.patch('aot.utils.ai_screen_cards.unread_count',
                        wraps=__import__('aot.utils.ai_screen_cards', fromlist=['x']
                                         ).unread_count) as spy:
            plain = self._sync().get_json()
            self.assertNotIn('ai_unread', plain)
            self.assertEqual(spy.call_count, 0)         # 평소 폴링엔 DB 조회 없음
            first = self._sync(inbox=True).get_json()
            self.assertEqual(first['ai_unread'], 3)
            self.assertEqual(spy.call_count, 1)
            self.assertNotIn('ai_unread', self._sync(inbox=False).get_json())
            self.assertNotIn('ai_unread', self._sync(inbox='yes').get_json())
        self.assertIn('commands', first)

    # P3 — 오래 열어 둔 탭 대응: sync 응답이 현재 screen-link 번들 해시를 싣는다(layout 의 asset() 과 같은 출처)
    def test_sync_carries_the_current_screen_link_bundle_hash(self):
        from aot.utils import bundle_manifest
        self._login()
        want = bundle_manifest.hash_of('screen-link')
        self.assertTrue(want)
        got = self._sync().get_json()
        self.assertEqual(got.get('bundle'), want)
        # layout 이 내보내는 값(asset()?v=, window.AOT_BUNDLES)과 같은 해시다
        proc = [f for f in self.app.template_context_processors[None]
                if f.__name__ == 'inject_bundle_asset'][0]
        with self.app.test_request_context('/'):
            ctx = proc()
            self.assertIn('?v=' + want, ctx['asset']('screen-link'))
            self.assertEqual(ctx['bundle_manifest']()['screen-link'], want)
        # 매니페스트에서 해시를 못 읽으면 키를 싣지 않는다(화면은 비교를 건너뛴다)
        with mock.patch('aot.utils.bundle_manifest.hash_of', return_value=None):
            self.assertNotIn('bundle', self._sync().get_json())

    # 완료 기준 ⑧(수신함 API) + 기본 동작
    def test_inbox_api_round_trip(self):
        self._login()
        self._with_cards(3)
        r = self.client.get('/api/v1/ai-inbox?limit=2')
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertEqual([i['title'] for i in j['items']], ['T2', 'T1'])
        self.assertEqual((j['unread'], j['more']), (3, True))
        item = j['items'][0]
        self.assertEqual(set(item), {'id', 'title', 'message', 'source',
                                     'created_at', 'read', 'kind', 'pinned',
                                     'note_id', 'notice_id', 'file', 'files'})
        self.assertIs(j['can_notice'], True)       # P2 — 최상위 can_notice
        self.assertEqual((item['message'], item['source'], item['read']),
                         ('body 2', 'Bot', False))
        j2 = self.client.get('/api/v1/ai-inbox?before=' + j['items'][-1]['id']
                             ).get_json()
        self.assertEqual([i['title'] for i in j2['items']], ['T0'])
        self.assertFalse(j2['more'])
        self.assertEqual(self.client.get('/api/v1/ai-inbox?limit=999'
                                         ).get_json()['more'], False)
        r = self.client.post('/api/v1/ai-inbox/%s/read' % item['id'])
        self.assertEqual(r.get_json(), {'ok': True, 'unread': 2})
        r = self.client.post('/api/v1/ai-inbox/%s/dismiss' % j['items'][1]['id'])
        self.assertEqual(r.get_json(), {'ok': True, 'unread': 1})
        titles = [i['title'] for i in self.client.get('/api/v1/ai-inbox').get_json()['items']]
        self.assertEqual(titles, ['T2', 'T0'])
        r = self.client.post('/api/v1/ai-inbox/read-all')
        self.assertEqual(r.get_json(), {'ok': True, 'unread': 0})
        self.assertTrue(all(i['read'] for i in
                            self.client.get('/api/v1/ai-inbox').get_json()['items']))

    # 완료 기준 ⑧
    def test_other_users_cards_are_404_and_invisible(self):
        self._login()
        theirs = self._with_cards(2, user=self.other)
        self.assertEqual(self.client.get('/api/v1/ai-inbox').get_json()['items'], [])
        for path in ('/%s/read', '/%s/dismiss'):
            r = self.client.post('/api/v1/ai-inbox' + path % theirs[0].unique_id)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.get_json(), {'error': 'not_found'})
        r = self.client.get('/api/v1/ai-inbox?before=' + theirs[0].unique_id)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.post('/api/v1/ai-inbox/nope/read').status_code, 404)
        self.client.post('/api/v1/ai-inbox/read-all')
        from aot.utils import ai_screen_cards as C
        self.assertEqual(C.unread_count(self.other.id), 2)
        self.assertFalse(C.get_card(self.other.id, theirs[0].unique_id).dismissed_at)

    def test_inbox_requires_login(self):
        from flask import g
        for name in ('_aot_scope_cache', '_login_user'):
            if hasattr(g, name):
                delattr(g, name)
        self.assertIn(self.client.get('/api/v1/ai-inbox').status_code, (401, 302))

    # 완료 기준 ⑪
    def test_api_key_requests_get_403(self):
        self._login()
        cards = self._with_cards(1)
        h = {'X-API-KEY': 'bm90LWEta2V5'}
        for method, path in (('get', '/api/v1/ai-inbox'),
                             ('post', '/api/v1/ai-inbox/%s/read' % cards[0].unique_id),
                             ('post', '/api/v1/ai-inbox/%s/dismiss' % cards[0].unique_id),
                             ('post', '/api/v1/ai-inbox/read-all')):
            r = getattr(self.client, method)(path, headers=h)
            self.assertEqual(r.status_code, 403, path)
            self.assertEqual(r.get_json(), {'error': 'api_key_not_allowed'})
        from aot.utils import ai_screen_cards as C
        self.assertEqual(C.unread_count(self.pk), 1)

    # 끝에서 끝까지: post → sync 로 화면이 가져감 → 회신 → 수신함
    def test_end_to_end_post_then_screen_fetch_and_reply(self):
        self._login()
        self.assertEqual(self._sync(state={}).status_code, 200)
        out = self._tool_post()
        self.assertEqual(out['shown_on'], ['iPhone · Safari'])
        j = self._sync().get_json()
        cmd = [c for c in j['commands'] if c['action'] == 'ai_card'][0]
        self.assertEqual(cmd['args']['message'], 'e2e **body**')
        from aot.databases.models import AuditLog
        self.assertEqual(AuditLog.query.filter(
            AuditLog.action == 'screen.command',
            AuditLog.detail.like('show an AI card%')).count(), 0)
        self._sync(results=[{'id': cmd['id'], 'ok': True, 'message': 'inbox'}])
        self.assertEqual(wp.get_command(cmd['id'])['status'], 'done')
        self.assertEqual(AuditLog.query.filter(
            AuditLog.action == 'screen.command',
            AuditLog.detail.like('show an AI card%')).count(), 1)
        AuditLog.query.filter(AuditLog.action == 'screen.command',
                              AuditLog.detail.like('show an AI card%')).delete(
            synchronize_session=False)
        from aot.aot_flask.extensions import db
        db.session.commit()
        self.assertEqual(self.client.get('/api/v1/ai-inbox').get_json()['unread'], 1)

    def _tool_post(self):
        from aot.tools.tool_execution import _execute_tool
        content = _execute_tool(self.app, 'screen_action',
                                {'action': 'post', 'message': 'e2e **body**'},
                                agent_id=_AGENT, role=None,
                                scope_user_uuid=self.uid, transport='mcp_http')
        return json.loads(content[0]['text'])


class SettingsTest(_Base):
    """Misc.hide_ai_messages — settings/general 저장 왕복 (2026-10-19 결정 4).
    폼 필드 이름 `hide_ai_messages`, 템플릿 변수 `settings.hide_ai_messages`."""

    def setUp(self):
        super().setUp()
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc
        self._made_misc = Misc.query.first() is None
        if self._made_misc:
            db.session.add(Misc())
            db.session.commit()
        self._orig = Misc.query.first().hide_ai_messages
        # settings_general_mod 는 AIGlobalSettings 도 같이 쓴다 — 폼에 없는 체크박스는 꺼짐으로
        # 저장되어 mcp_http_enabled=False 가 같은 프로세스의 뒤 시험(MCP http 503)으로 샌다.
        from aot.databases.models.ai_settings import AIGlobalSettings
        row = AIGlobalSettings.query.first()
        self._ai_row_made = row is None
        self._ai_orig = None if row is None else {
            k: getattr(row, k) for k in
            ('ai_enabled', 'mcp_http_enabled', 'user_string_translation_enabled')}

    def tearDown(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc
        from aot.databases.models.ai_settings import AIGlobalSettings
        db.session.rollback()
        if self._ai_row_made:
            AIGlobalSettings.query.delete()
        else:
            row = AIGlobalSettings.query.first()
            for k, v in self._ai_orig.items():
                setattr(row, k, v)
        if self._made_misc:
            Misc.query.delete()
        else:
            Misc.query.first().hide_ai_messages = self._orig
        db.session.commit()
        super().tearDown()

    def _save_general(self, **fields):
        from aot.aot_flask.forms import forms_settings
        from aot.aot_flask.utils import utils_settings
        from aot.databases.models import Misc
        data = {'rpyc_timeout': '30', 'output_usage_report_span': 'monthly',
                'output_usage_report_day': '15', 'output_usage_report_hour': '3', 'use_database': 'influxdb_1',
                'force_https': 'y'}   # 같은 값 — 바뀌면 프런트 재시작 경로를 탄다
        data.update(fields)
        with self.app.test_request_context('/settings/general', method='POST',
                                           data=data), \
                mock.patch.object(utils_settings, 'DaemonControl'):   # 데몬은 없다
            import flask_login
            flask_login.login_user(self.user)
            form = forms_settings.SettingsGeneral()
            messages = utils_settings.settings_general_mod(form)
        self.assertEqual(messages['error'], [], messages)
        from aot.aot_flask.extensions import db
        db.session.expire_all()
        return Misc.query.first()

    def test_form_field_saves_and_reads_back(self):
        from aot.databases.models import Misc
        self.assertFalse(bool(Misc.query.first().hide_ai_messages))   # 기본: 숨기지 않음
        self.assertTrue(self._save_general(hide_ai_messages='y').hide_ai_messages)
        # 시스템 메시지 숨기기와 별개다.
        misc = Misc.query.first()
        self.assertFalse(bool(misc.hide_alert_success or misc.hide_alert_info
                              or misc.hide_alert_warning))
        # 체크를 풀어 저장하면(필드 없음) 꺼진다.
        self.assertFalse(self._save_general().hide_ai_messages)

    def test_post_still_stores_when_hidden(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc
        Misc.query.first().hide_ai_messages = True
        db.session.commit()
        self._screen('kh' + 'a' * 18)
        out = self._post()
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(len(self._cards()), 1)


class AutoCardTest(_Base):
    """AI 결과 카드 자동(2026-10-22): 지침 규칙·설정·같은 카드 중복 방지."""

    def _set_auto(self, value):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc
        misc = Misc.query.first()
        if misc is None:
            misc = Misc()
            db.session.add(misc)
        misc.ai_card_auto = value
        db.session.commit()

    def test_the_rule_is_in_the_instructions_by_default_and_follows_the_setting(self):
        from aot.tools.tool_execution import _server_instructions
        from aot.utils import ai_screen_cards as cards
        self._set_auto(None)                                  # 옛 행(NULL)도 켬
        self.assertIn(cards.AUTO_CARD_RULE, _server_instructions(None))
        self._set_auto(True)
        self.assertIn('AI CARDS', _server_instructions(None))
        self._set_auto(False)
        self.assertNotIn('AI CARDS', _server_instructions(None))
        self.assertFalse(cards.card_auto_enabled())
        self._set_auto(True)

    def test_the_rule_names_the_key_result_kinds_and_stays_short(self):
        from aot.tools.tool_execution import _estimate_tokens
        from aot.utils import ai_screen_cards as cards
        rule = cards.AUTO_CARD_RULE
        for word in ('recommendation', 'summary', 'comparison', 'plan', 'report', 'image', 'link list',
                     'card op', 'once'):
            self.assertIn(word, rule)
        self.assertLessEqual(_estimate_tokens(rule), 160)    # 지침 토큰 예산(상한 인상 금지)

    def test_the_same_title_and_body_just_posted_is_not_stacked_again(self):
        self._screen('kdup' + 'a' * 16)
        first = self._post({'title': 'Plan', 'message': 'Water at 6am.'})
        self.assertEqual(first['status'], 'posted', first)
        n = len(self._cards())
        again = self._post({'title': ' plan ', 'message': 'Water   at 6am.'})       # 대소문자·공백만 다름
        self.assertEqual(again['status'], 'skipped', again)
        self.assertIn('not posted again', again['note'])
        self.assertEqual(len(self._cards()), n)
        other = self._post({'title': 'Plan', 'message': 'Water at 7am.'})            # 본문이 다르면 새 카드
        self.assertEqual(other['status'], 'posted', other)

    def test_screen_op_card_plans_a_post_without_naming_an_action(self):
        from aot.tools.domain import dispatch
        v = dispatch.plan('screen', {'op': 'card', 'title': 'Summary', 'message': 'Soil moisture 61%.'})
        self.assertEqual(('call', 'screen_action'), v[:2], v)
        self.assertEqual(('post', 'Summary', 'Soil moisture 61%.'),
                         (v[2]['action'], v[2]['title'], v[2]['message']))

    def test_screen_act_with_action_post_points_to_op_card_and_runs_nothing(self):
        from aot.tools.domain import dispatch
        v = dispatch.plan('screen', {'op': 'act', 'action': 'post', 'title': 'T', 'message': 'M'})
        self.assertEqual('refuse', v[0], v)
        self.assertIn('op=card', json.dumps(v[1], ensure_ascii=False))

    def test_the_card_op_is_listed_with_its_use_line_and_needs_a_message(self):
        from aot.tools.domain.registry_data import OPS
        from aot.tools.domain.registry import find_op
        o = find_op(OPS, 'screen', 'card')
        self.assertIn('card', o.use)
        self.assertEqual(o.required, ('message',))
        self.assertEqual(o.defaults_by_kind, {'none': {'action': 'post'}})

    def test_lookup_responses_carry_one_card_hint_per_conversation_window(self):
        from aot.tools import tool_execution as te
        from aot.utils import ai_screen_cards as cards
        cards._card_hint_seen.clear()
        self._set_auto(True)

        def finish(tool, result=None, key='s1'):
            out = {'status': 'success'} if result is None else dict(result)
            te._attach_card_hint(out, tool, key, 'u1')
            return out
        first = finish('list_plots')
        self.assertEqual(cards.AUTO_CARD_HINT, first.get('card_hint'))
        self.assertEqual(['card_hint', 'status'], list(first))                   # 맨 앞 — 끝에 두면 묻힌다(10-28)
        self.assertNotIn('card_hint', finish('list_plots'))                       # 같은 대화, 창 안
        self.assertNotIn('card_hint', finish('get_sensor_reading'))
        self.assertIn('card_hint', finish('list_plots', key='s2'))                # 다른 대화는 따로
        self.assertNotIn('card_hint', finish('screen_action', key='s3'))         # 조회 도구가 아님
        self.assertNotIn('card_hint', finish('get_local_time', key='s4'))        # 정리해 줄 일이 아님
        # 창이 지나면 다시
        for k in list(cards._card_hint_seen):
            cards._card_hint_seen[k] -= cards.CARD_HINT_EVERY + 1
        self.assertIn('card_hint', finish('list_plots'))

    def test_summary_and_weather_reads_carry_the_hint_every_time(self):
        """요약·날씨 질문은 같은 턴에 카드를 띄우는 것이 규칙이다 — 5분 창 안의 두 번째 질문에도 안내가 간다(2026-10-26)."""
        from aot.tools import tool_execution as te
        from aot.utils import ai_screen_cards as cards
        cards._card_hint_seen.clear()
        self._set_auto(True)
        for tool in ('get_place_overview', 'get_weather', 'get_weather_forecast'):
            for _ in range(3):
                out = {'status': 'success'}
                te._attach_card_hint(out, tool, 's-always', 'u1')
                self.assertEqual(cards.AUTO_CARD_HINT, out.get('card_hint'), tool)
        for tool in ('get_system_update_status', 'get_storage_tier_status'):
            self.assertNotIn(tool, cards.card_hint_always_tools())
        self._set_auto(False)                                                       # 설정이 꺼지면 어느 쪽도 주지 않는다
        out = {'status': 'success'}
        te._attach_card_hint(out, 'get_weather_forecast', 's-always', 'u1')
        self.assertNotIn('card_hint', out)

    def test_the_hint_reaches_a_real_tool_response_once(self):
        from aot.tools.tool_execution import _execute_tool
        from aot.utils import ai_screen_cards as cards
        cards._card_hint_seen.clear()
        self._set_auto(True)

        def call():
            got = _execute_tool(self.app, 'list_plots', {}, agent_id=_AGENT, role=None,
                                scope_user_uuid=self.uid, transport='mcp_http', session_key='sess-hint')
            return json.loads(got[0]['text'])
        first, second = call(), call()
        self.assertEqual(cards.AUTO_CARD_HINT, first.get('card_hint'), first)
        self.assertNotIn('card_hint', second)

    def test_the_hint_is_off_when_the_auto_setting_is_off_and_names_the_card_op(self):
        from aot.tools import tool_execution as te
        from aot.utils import ai_screen_cards as cards
        self.assertIn('op=card', cards.AUTO_CARD_HINT)
        cards._card_hint_seen.clear()
        self._set_auto(False)
        out = {'status': 'success'}
        te._attach_card_hint(out, 'get_place_overview', 's9', 'u1')
        self.assertNotIn('card_hint', out)
        self._set_auto(True)

    def test_every_hinted_tool_is_a_domain_read_tool_and_none_is_a_screen_tool(self):
        from aot.utils import ai_screen_cards as cards
        tools = cards.card_hint_tools()
        self.assertIn('get_place_overview', tools)
        self.assertTrue(tools.isdisjoint({'screen_action', 'get_screen', 'operate_device'}))
        self.assertTrue(tools.isdisjoint(cards._CARD_HINT_SKIP))

    def test_a_card_with_an_attachment_or_after_the_window_is_not_treated_as_a_duplicate(self):
        from aot.utils import ai_screen_cards as cards
        self._screen('kdup2' + 'a' * 15)
        self.assertEqual(self._post({'title': 'T', 'message': 'B'})['status'], 'posted')
        with_file = self._post({'title': 'T', 'message': 'B',
                                'attach': {'name': 'a.txt', 'text': 'hello'}})
        self.assertEqual(with_file['status'], 'posted', with_file)
        later = cards._now() + cards.DUPLICATE_WINDOW + cards.datetime.timedelta(seconds=1)
        self.assertFalse(cards.recent_duplicate(self.pk, 'T', 'B', now=later + cards.datetime.timedelta(minutes=5)))


class AutoCardMigrationTest(unittest.TestCase):

    def test_p6_93_adds_and_drops_the_column_and_is_rerun_safe(self):
        import importlib.util
        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'alembic_db', 'alembic', 'versions',
                            'p6_93_ai_card_auto_20261022.py')
        spec = importlib.util.spec_from_file_location('p6_93', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.down_revision, 'p6_92_twin_options_20261022')
        eng = sa.create_engine('sqlite://')
        with eng.begin() as conn:
            conn.execute(sa.text('create table misc (id integer primary key)'))
            conn.execute(sa.text('insert into misc (id) values (1)'))
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
                mod.upgrade()                                     # 재실행 안전
                self.assertIn('ai_card_auto', [c['name'] for c in sa.inspect(conn).get_columns('misc')])
                self.assertEqual(conn.execute(sa.text('select ai_card_auto from misc')).scalar(), 1)   # 옛 행도 켬
                mod.downgrade()
                mod.downgrade()
                self.assertNotIn('ai_card_auto', [c['name'] for c in sa.inspect(conn).get_columns('misc')])


class AutoCardSettingsWiringTest(unittest.TestCase):

    def test_form_save_template_and_context_are_wired(self):
        root = os.path.join(os.path.dirname(__file__), '..', 'aot_flask')
        read = lambda *p: open(os.path.join(root, *p), encoding='utf-8').read()
        self.assertIn('ai_card_auto = BooleanField', read('forms', 'forms_settings.py'))
        self.assertIn('mod_misc.ai_card_auto = form.ai_card_auto.data', read('utils', 'utils_settings.py'))
        tpl = read('templates', 'settings', 'general.html')
        self.assertIn('name="ai_card_auto"', tpl)
        self.assertIn('{{ ai_card_rule }}', tpl)
        self.assertIn('ai_card_rule=ai_screen_cards.AUTO_CARD_RULE', read('routes_settings.py'))


class MigrationTest(unittest.TestCase):
    """완료 기준 ⑬ — 단일 head(P5 에서 p6_89), 모델·마이그레이션 칸 일치.
    p6_86 이 테이블을, p6_87 이 P1 칸(첨부·고정·노트)을, p6_88 이 P2 칸(공지)을, p6_89 가 다중 첨부
    테이블을 더한다."""

    _BASE = 'p6_86_ai_screen_cards_20261019'
    _P1 = 'p6_87_ai_card_files_20261019'
    _NAME = 'p6_88_ai_card_notice_20261019'
    _HEAD = 'p6_89_ai_card_attachments_20261021'

    def _versions(self):
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions')

    def _load(self, name):
        path = os.path.join(self._versions(), name + '.py')
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_single_head_is_p6_89(self):
        revs, downs = {}, set()
        for f in os.listdir(self._versions()):
            if not f.endswith('.py'):
                continue
            mod = self._load(f[:-3])
            if getattr(mod, 'revision', None):
                revs[mod.revision] = mod.down_revision
                for d in (mod.down_revision if isinstance(mod.down_revision, (tuple, list))
                          else [mod.down_revision]):
                    downs.add(d)
        heads = [r for r in revs if r not in downs]
        # head 는 뒤 작업이 이어 갈 수 있다 — 단일 head 가 config 값과 같은지, 그리고
        # 이 작업의 사슬(p6_89 → … → p6_85)이 그대로인지를 본다.
        from aot.config import ALEMBIC_VERSION
        self.assertEqual(heads, [ALEMBIC_VERSION])
        self.assertIn(self._HEAD, revs)
        self.assertEqual(revs[self._HEAD], self._NAME)
        self.assertEqual(revs[self._NAME], self._P1)
        self.assertEqual(revs[self._P1], self._BASE)
        self.assertEqual(revs[self._BASE], 'p6_85_input_device_status_20261013')

    def _run(self, mod, fn, engine):
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                getattr(mod, fn)()

    def test_migration_matches_model_and_is_rerunnable(self):
        import sqlalchemy as sa
        import tempfile
        from aot.databases.models.ai_screen_card import AIScreenCard
        from aot.databases.models import Misc
        with tempfile.TemporaryDirectory() as d:
            engine = sa.create_engine('sqlite:///%s' % os.path.join(d, 'm.db'))
            with engine.begin() as c:
                c.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
                c.execute(sa.text('CREATE TABLE misc (id INTEGER PRIMARY KEY,'
                                  ' hide_tooltips BOOLEAN)'))
                c.execute(sa.text('INSERT INTO misc (hide_tooltips) VALUES (0)'))
            base, p1 = self._load(self._BASE), self._load(self._P1)
            mod = self._load(self._NAME)
            self._run(base, 'upgrade', engine)
            self._run(p1, 'upgrade', engine)
            self._run(mod, 'upgrade', engine)
            self._run(base, 'upgrade', engine)
            self._run(p1, 'upgrade', engine)
            self._run(mod, 'upgrade', engine)           # 재실행 안전
            insp = sa.inspect(engine)
            model_cols = {c.name: c for c in AIScreenCard.__table__.columns}
            mig_cols = {c['name']: c for c in insp.get_columns('ai_screen_cards')}
            self.assertEqual(set(model_cols), set(mig_cols))
            for name, col in model_cols.items():
                self.assertEqual(col.nullable, mig_cols[name]['nullable'], name)
            self.assertEqual({i['name'] for i in insp.get_indexes('ai_screen_cards')},
                             {i.name for i in AIScreenCard.__table__.indexes})
            self.assertIn('hide_ai_messages', {c['name'] for c in insp.get_columns('misc')})
            self.assertIn('hide_ai_messages', Misc.__table__.columns)
            with engine.begin() as c:
                self.assertEqual(c.execute(sa.text(
                    'SELECT hide_ai_messages FROM misc')).scalar(), 0)
            # p6_88 만 내리면 notice_id 만 빠지고 P1 칸은 남는다.
            self._run(mod, 'downgrade', engine)
            self._run(mod, 'downgrade', engine)
            cols = {c['name'] for c in sa.inspect(engine).get_columns('ai_screen_cards')}
            self.assertNotIn('notice_id', cols)
            self.assertIn('note_id', cols)
            self._run(mod, 'upgrade', engine)           # 다시 올려도 된다
            self.assertIn('notice_id', {c['name'] for c in
                                        sa.inspect(engine).get_columns('ai_screen_cards')})
            self._run(mod, 'downgrade', engine)
            # p6_87 까지 내리면 P1 칸·인덱스가 빠지고 P0 테이블은 남는다.
            self._run(p1, 'downgrade', engine)
            self._run(p1, 'downgrade', engine)
            insp = sa.inspect(engine)
            cols = {c['name'] for c in insp.get_columns('ai_screen_cards')}
            self.assertFalse(cols & {'file_path', 'file_name', 'file_mime', 'file_size',
                                     'pinned_at', 'note_id', 'notice_id'})
            self.assertNotIn('ix_ai_screen_cards_user_pinned',
                             {i['name'] for i in insp.get_indexes('ai_screen_cards')})
            self._run(p1, 'upgrade', engine)           # 다시 올려도 된다
            self._run(p1, 'downgrade', engine)
            self._run(base, 'downgrade', engine)
            self._run(base, 'downgrade', engine)
            insp = sa.inspect(engine)
            self.assertFalse(insp.has_table('ai_screen_cards'))
            self.assertNotIn('hide_ai_messages', {c['name'] for c in insp.get_columns('misc')})
            with engine.begin() as c:
                self.assertEqual(c.execute(sa.text('SELECT COUNT(*) FROM misc')).scalar(), 1)


class CostTest(unittest.TestCase):
    """완료 기준 ⑭·P1 ⑯ — screen_action 은 카탈로그에서 783토큰 이하(계약 ① 상쇄안).
    전체 예산(카탈로그·운영·lite)은 test_tool_cost_budget·test_mcp_tool_profiles 가 잰다."""

    #: 749(post 흡수 전) → 744(post 흡수) → 783(P1 read·attach, 1,566자, +39). 늘어난
    #: 몫은 같은 변경에서 get_plot 인자 설명의 중복 문장(row_spacing_cm·rows_per_bed)을
    #: 줄여 상쇄했다(카탈로그 43,344 → 43,333, 운영 21,888 → 21,877).
    #: P4(10-20): attach 에 url 을 더하고(+4자) 같은 설명의 `their` 를 지워(-6자) 782 로 내려왔다.
    BEFORE_TOKENS = 782

    def test_screen_action_does_not_grow(self):
        from aot.scripts.measure_ai_tool_cost import _tok
        from aot.tools import tool_registry
        spec = next(t for t in tool_registry._MCP_TOOL_PAYLOADS
                    if t['tool_name'] == 'screen_action')
        chars, tokens = _tok({'name': spec['tool_name'],
                              'description': spec['description'],
                              'inputSchema': spec['input_schema']})
        self.assertLessEqual(tokens, self.BEFORE_TOKENS, (chars, tokens))
        props = spec['input_schema']['properties']
        for key in ('kind', 'center', 'title', 'message'):
            self.assertIn(key, props)       # test_web_presence 가 kind·center 를 본다


if __name__ == '__main__':
    unittest.main()
