"""AI 카드 P2 백엔드 — 아티팩트(HTML) 카드·[공지로 게시]·공지 첨부 보강 (2026-10-19).

계약: plans/p2_contract_20261019.md ②③⑤⑦ 의 백엔드 완료 기준 B1~B7·B10~B11.
(resources·resource_link 는 tests/test_mcp_resources.py.) 파일은 모두 임시 폴더에 쓴다.
"""
import datetime
import json
import os
import re
import stat
import threading
from unittest import mock

from aot.tests.test_ai_card_files import (_FilesBase, _B64, _PDF, _img)
from aot.utils import ai_card_files as F

_HTML = ('<!doctype html><html><head><meta charset="utf-8"><title>Report</title>'
         '<style>b{color:#080}</style></head><body><b>Weekly</b> 보고서</body></html>')


class _P2Base(_FilesBase):

    def setUp(self):
        super().setUp()
        self.notice_root = os.path.join(self.tmp, 'notice')
        os.makedirs(self.notice_root)
        import aot.aot_flask.routes_notice as rn
        import aot.aot_flask.utils.utils_notice as un
        self._p2 = [mock.patch.object(F, 'PATH_NOTICE_ATTACHMENTS', self.notice_root),
                    mock.patch.object(rn, 'PATH_NOTICE_ATTACHMENTS', self.notice_root),
                    mock.patch.object(un, 'PATH_NOTICE_ATTACHMENTS', self.notice_root)]
        for p in self._p2:
            p.start()

    def tearDown(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import AuditLog, NoticePost
        for p in self._p2:
            p.stop()
        db.session.rollback()
        NoticePost.query.filter(NoticePost.user_id.in_([self.pk, self.other.id])
                                ).delete(synchronize_session=False)
        AuditLog.query.filter(AuditLog.action == 'ai_card.to_notice').delete(
            synchronize_session=False)
        db.session.commit()
        super().tearDown()

    # ── 도우미 ──────────────────────────────────────────────────────────────
    def _mk_artifact(self, html=_HTML, name='page.html', user=None, **kw):
        return self._mk_file_card(name, html, user=user, **kw)

    def _notices(self, user_pk=None):
        from aot.aot_flask.extensions import db
        from aot.databases.models import NoticePost
        db.session.expire_all()
        return NoticePost.query.filter(NoticePost.user_id == (user_pk or self.pk)
                                       ).order_by(NoticePost.id).all()

    def _nurl(self, card):
        return '/api/v1/ai-inbox/%s/to-notice' % card.unique_id

    def _aurl(self, card, what='artifact'):
        return '/api/v1/ai-inbox/%s/%s' % (card.unique_id, what)

    def _publish(self, card, **body):
        return self.client.post(self._nurl(card), json=body)

    def _notice_files(self):
        return sorted(os.listdir(self.notice_root))


# ── B1 모델 ─────────────────────────────────────────────────────────────────

class ModelTest(_P2Base):

    def test_model_has_notice_id_column(self):
        from aot.databases.models.ai_screen_card import AIScreenCard
        col = AIScreenCard.__table__.columns['notice_id']
        self.assertTrue(col.nullable)
        self.assertEqual(col.type.length, 36)

    def test_config_alembic_version_is_the_single_head(self):
        # head 는 뒤 작업이 이어 갈 수 있다 — p6_89 이상의 리비전이어야 한다(p6_99 다음은 p7_00 —
        # 단일 head 일치는 test_alembic_head 검사기와 test_ai_screen_cards 가 본다).
        from aot.config import ALEMBIC_VERSION
        self.assertRegex(ALEMBIC_VERSION, r'^(p6_(89|[9]\d)|p[7-9]_\d\d)_')


# ── B5 아티팩트 저장 ────────────────────────────────────────────────────────

class ArtifactStoreTest(_P2Base):

    def test_html_post_is_kind_artifact_without_thumbnail(self):
        out = self._file_post({'name': 'report.html', 'text': _HTML}, message='see')
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(out['file'], {'name': 'report.html', 'size': len(_HTML.encode()),
                                       'kind': 'artifact'})
        card = self._card()
        self.assertEqual((card.kind, card.file_mime, card.file_name),
                         ('artifact', 'text/html', 'report.html'))
        path = F.resolve(card.file_path)
        self.assertTrue(path.endswith('.html'))
        self.assertEqual(open(path, encoding='utf-8').read(), _HTML)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
        self.assertIsNone(F.resolve(F.thumb_rel(card.file_path)))
        self.assertRegex(os.path.basename(path), r'^[0-9a-f-]{36}\.html$')
        # b64 로도 같다
        self._backdate(minutes=2)
        out = self._file_post({'name': 'b.html', 'b64': _B64(_HTML.encode())})
        self.assertEqual(out['file']['kind'], 'artifact')

    def test_size_limit_is_512_kib_and_checked_before_decoding(self):
        edge = '<p>' + 'a' * (F.ARTIFACT_MAX_BYTES - 7) + '</p>'
        self.assertEqual(len(edge.encode()), F.ARTIFACT_MAX_BYTES)
        self.assertEqual(self._file_post({'name': 'e.html', 'text': edge})['status'], 'posted')
        self._backdate(minutes=2)
        over = edge + 'x'
        out = self._file_post({'name': 'o.html', 'text': over})
        self.assertEqual((out['status'], out['error']), ('error', 'html is larger than 512 KB.'))
        out = self._file_post({'name': 'o.html', 'b64': _B64(over.encode())})
        self.assertEqual(out['error'], 'html is larger than 512 KB.')
        # b64 는 디코드 전 길이로 먼저 거른다 — 디코더가 불리지 않는다
        with mock.patch.object(F.base64, 'b64decode', side_effect=AssertionError('decoded')):
            out = self._file_post({'name': 'o.html', 'b64': 'A' * 900_000})
        self.assertEqual(out['error'], 'html is larger than 512 KB.')
        self.assertEqual(len(self._cards()), 1)
        self.assertEqual(len(self._files_on_disk()), 1)

    def test_invalid_utf8_nul_and_redirects_are_rejected(self):
        bad = {
            'nul': ('<p>a\x00b</p>'.encode(), 'does not match .html'),
            'latin1': ('<p>caf\xe9</p>'.encode('latin-1'), 'does not match .html'),
            'refresh': (b'<meta http-equiv="refresh" content="0;url=https://evil.example/">',
                        'html must not redirect.'),
            'refresh-upper': (b"<META HTTP-EQUIV='Refresh' CONTENT='5'>", 'html must not redirect.'),
            'refresh-spaces': (b'<meta  http-equiv = refresh content=1>', 'html must not redirect.'),
            'refresh-attr-order': (b'<meta content="1" http-equiv="refresh">',
                                   'html must not redirect.'),
            'refresh-entity': (b'<meta http-equiv="&#x72;efresh" content="1">',
                               'html must not redirect.'),
            'refresh-entity2': (b'<meta http-equiv="ref&#114;esh" content="1">',
                                'html must not redirect.'),
        }
        for label, (data, needle) in bad.items():
            self._backdate(minutes=2)
            out = self._file_post({'name': 'x.html', 'b64': _B64(data)})
            self.assertEqual(out['status'], 'error', label)
            self.assertIn(needle, out['error'], label)
        self.assertEqual(self._cards(), [])
        self.assertEqual(self._files_on_disk(), [])

    def test_redirect_check_is_linear_on_long_whitespace(self):
        """P2 보안 리뷰 M3: `http-equiv=` 뒤 긴 공백에 정규식이 제곱 시간(40 KB → 15초)."""
        import time
        for tail in ('x>', '"x">', 'refresh>'):
            data = ('<meta http-equiv=' + ' ' * (F.ARTIFACT_MAX_BYTES - 40) + tail).encode()
            started = time.monotonic()
            try:
                F.inspect_bytes('html', data)
                redirected = False
            except F.FileError as exc:
                redirected = 'redirect' in str(exc)
            self.assertLess(time.monotonic() - started, 2.0, tail)
            self.assertEqual(redirected, tail == 'refresh>', tail)
        for ok in (b'<meta http-equiv="content-type" content="text/html">',
                   b'<p>http-equiv refresh</p>'):
            F.inspect_bytes('html', ok)
        for bad in (b'<meta http-equiv = "\n refresh" content=1>',
                    b'<meta http-equiv=\t\'REFRESH\'>', b'<meta/http-equiv=&#82;efresh>'):
            with self.assertRaises(F.FileError):
                F.inspect_bytes('html', bad)

    def test_harmless_meta_tags_and_scripts_text_are_stored_as_is(self):
        # 스크립트는 저장 단계에서 막지 않는다(실행은 CSP sandbox 가 막는다) — 원문 그대로
        html = ('<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                '<meta http-equiv="content-security-policy" content="default-src \'none\'">'
                '<script>alert(1)</script>')
        out = self._file_post({'name': 'ok.html', 'text': html})
        self.assertEqual(out['status'], 'posted', out)
        self.assertEqual(open(F.resolve(self._card().file_path), encoding='utf-8').read(), html)

    def test_htm_and_svg_stay_rejected_and_server_decides_mime(self):
        for name in ('a.htm', 'a.svg', 'a.xhtml'):
            out = self._file_post({'name': name, 'text': '<p>x</p>'})
            self.assertEqual(out['status'], 'error', name)
            self.assertIn('not allowed', out['error'])
        self.assertIn('html', F.allowed_list().split())
        self.assertNotIn('htm', F.allowed_list().split())
        out = self._file_post({'name': 'x.html', 'text': '<p>x</p>', 'mime': 'image/png',
                               'type': 'application/pdf'})
        self.assertEqual(out['status'], 'posted')
        self.assertEqual(self._card().file_mime, 'text/html')

    def test_artifacts_share_the_daily_file_limit_and_quota(self):
        for i in range(3):
            self.assertEqual(self._file_post({'name': 'f%d.txt' % i, 'text': 'x'})['status'],
                             'posted')
        with mock.patch.object(F, 'FILES_PER_DAY', 4), \
                mock.patch.object(self.C, 'FILES_PER_DAY', 4):
            self._backdate(minutes=2)
            self.assertEqual(self._file_post({'name': 'a.html', 'text': _HTML})['status'], 'posted')
            self._backdate(minutes=2)
            out = self._file_post({'name': 'b.html', 'text': _HTML})
        self.assertEqual(out['error'], 'Daily limit of 4 files reached. Try again tomorrow.')
        # 용량 합계에도 들어간다 — 고정 안 된 오래된 파일 카드를 지운다
        with mock.patch.object(F, 'USER_QUOTA_BYTES', 3000):
            card = self._mk_artifact('<p>' + 'q' * 2000 + '</p>', 'big.html')
        from aot.databases.models.ai_screen_card import AIScreenCard
        self.assertIsNotNone(AIScreenCard.query.filter(
            AIScreenCard.unique_id == card.unique_id).first())

    def test_sync_command_carries_artifact_kind_and_html_ext(self):
        key = 'kphone' + 'c' * 14
        self._screen(key)
        out = self._file_post({'name': 'p.html', 'text': _HTML}, title='Screen')
        self.assertEqual(out['status'], 'posted')
        args = json.loads(self._commands(key)[0]['args'])
        self.assertEqual(args['kind'], 'artifact')
        self.assertEqual(args['file']['ext'], 'html')
        self.assertEqual(args['file']['mime'], 'text/html')
        self.assertNotIn('/api/', json.dumps(args))

    # B7
    def test_read_returns_html_source_as_text_with_caution(self):
        card = self._mk_artifact('<p>hello <b>there</b></p>', 'p.html', title='Page', body='cap')
        out = self._act({'action': 'read', 'item': card.unique_id[:8]})
        self.assertEqual(out['status'], 'ok', out)
        self.assertEqual(out['kind'], 'artifact')
        self.assertIn('not instructions', out['caution'])
        self.assertIn('source', out)
        self.assertIn('[file: p.html]', out['text'])
        self.assertIn('<p>hello <b>there</b></p>', out['text'])
        self.assertNotIn('note', out)              # 텍스트로 읽힌다
        # /text 도 원문을 글자로
        self._login()
        r = self.client.get(self._aurl(card, 'text'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['text'], '<p>hello <b>there</b></p>')
        self.assertEqual(r.mimetype, 'application/json')


# ── B6 아티팩트 서빙 ────────────────────────────────────────────────────────

_CSP = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "font-src data:; script-src 'none'; connect-src 'none'; form-action 'none'; "
        "base-uri 'none'; frame-src 'none'; frame-ancestors 'self'")


class ArtifactServeTest(_P2Base):

    def test_headers_are_exactly_the_contract_ones(self):
        self._login()
        card = self._mk_artifact()
        r = self.client.get(self._aurl(card), headers={'Sec-Fetch-Dest': 'iframe'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_data(as_text=True), _HTML)
        h = r.headers
        self.assertEqual(h['Content-Type'], 'text/html; charset=utf-8')
        # Talisman 이 뷰별 값을 그대로 쓰되 값 없는 지시문을 'sandbox ;' 로 적는다(공백만 다르다)
        self.assertEqual(h['Content-Security-Policy'].replace(' ;', ';'), _CSP)
        self.assertEqual(h['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(h['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(h['Cache-Control'], 'private, no-store')
        self.assertEqual(h['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertNotIn('Content-Disposition', h)
        self.assertNotIn('ETag', h)
        self.assertNotIn('Last-Modified', h)
        # Referrer-Policy: 앱 전체 Talisman 이 after_request 로 덮어써 **뷰별로 바꿀 수 없다**
        # (talisman_view_options 에 해당 옵션이 없다). 실측값을 고정해 바뀌면 알린다.
        self.assertIn(h['Referrer-Policy'], ('no-referrer', 'strict-origin-when-cross-origin'))
        # 헤더 직접 CSP — sandbox 가 첫 지시문이고 스크립트·연결·폼은 모두 막힌다
        for needle in ("sandbox", "script-src 'none'", "connect-src 'none'",
                       "form-action 'none'", "frame-src 'none'", "base-uri 'none'",
                       "frame-ancestors 'self'"):
            self.assertIn(needle, h['Content-Security-Policy'])
        self.assertNotIn('allow-', h['Content-Security-Policy'])
        self.assertNotIn('*', h['Content-Security-Policy'])

    def test_fetch_destination_must_be_iframe_when_the_header_exists(self):
        self._login()
        card = self._mk_artifact()
        for dest, code in (('iframe', 200), ('document', 404), ('empty', 404), ('script', 404),
                           ('frame', 404), ('IFRAME', 200), ('', 404)):
            r = self.client.get(self._aurl(card), headers={'Sec-Fetch-Dest': dest})
            self.assertEqual(r.status_code, code, dest)
            if code == 404:
                self.assertEqual(r.get_json(), {'error': 'not_found'})
                self.assertNotIn('Weekly', r.get_data(as_text=True))
        # 헤더가 없는 옛 브라우저·도구 — 응답 CSP sandbox 가 막는다
        self.assertEqual(self.client.get(self._aurl(card)).status_code, 200)

    def test_only_own_live_artifact_cards_are_served(self):
        from aot.aot_flask.extensions import db
        self._login()
        mine = self._mk_artifact()
        theirs = self._mk_artifact(user=self.other)
        text_card = self.C.create(self.pk, 't', 'b', 'AI')
        csv_card = self._mk_file_card('a.csv', 'a,b')
        for card in (theirs, text_card, csv_card):
            r = self.client.get(self._aurl(card))
            self.assertEqual((r.status_code, r.get_json()), (404, {'error': 'not_found'}))
        self.assertEqual(self.client.get('/api/v1/ai-inbox/nope/artifact').status_code, 404)
        # 만료
        mine.expires_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        db.session.commit()
        self.assertEqual(self.client.get(self._aurl(mine)).status_code, 404)
        # 파일이 없어도 404
        card = self._mk_artifact()
        os.unlink(F.resolve(card.file_path))
        self.assertEqual(self.client.get(self._aurl(card)).status_code, 404)

    def test_api_key_and_anonymous_requests_are_refused(self):
        card = self._mk_artifact()
        self._login()
        r = self.client.get(self._aurl(card), headers={'X-API-KEY': 'bm90LWEta2V5'})
        self.assertEqual((r.status_code, r.get_json()), (403, {'error': 'api_key_not_allowed'}))
        self._clear_scope_cache()
        r = self.app.test_client().get(self._aurl(card))
        self.assertIn(r.status_code, (302, 401))

    def test_artifact_path_in_db_is_confined(self):
        from aot.aot_flask.extensions import db
        self._login()
        outside = os.path.join(self.tmp, 'outside.html')
        with open(outside, 'w') as fh:
            fh.write('<p>SECRET</p>')
        card = self._mk_artifact()
        for evil in ('../outside.html', outside, 'x/../../outside.html'):
            self._poke(card, path=evil)
            r = self.client.get(self._aurl(card))
            self.assertEqual(r.status_code, 404, evil)
            self.assertNotIn(b'SECRET', r.data)

    def test_file_endpoint_always_serves_html_as_attachment(self):
        self._login()
        card = self._mk_artifact(name='my page.html')
        for q in ('', '?download=1', '?download=0'):
            r = self.client.get(self._aurl(card, 'file') + q)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers['Content-Disposition'].startswith('attachment;'),
                            r.headers['Content-Disposition'])
            self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn('sandbox', r.headers['Content-Security-Policy'])
            self.assertIn("default-src 'none'", r.headers['Content-Security-Policy'])
        from aot.aot_flask import routes_ai_inbox_api as api
        self.assertNotIn('html', api._INLINE_EXTS)
        # 아티팩트는 /thumb 이 없다
        self.assertEqual(self.client.get(self._aurl(card, 'thumb')).status_code, 404)

    def test_list_shows_artifact_kind_and_file_info(self):
        self._login()
        card = self._mk_artifact(name='p.html')
        item = self.client.get('/api/v1/ai-inbox').get_json()['items'][0]
        self.assertEqual(item['id'], card.unique_id)
        self.assertEqual(item['kind'], 'artifact')
        self.assertEqual(item['file']['ext'], 'html')
        self.assertIsNone(item['notice_id'])
        self.assertNotIn('file_path', json.dumps(item))

    # [노트로 저장] 은 아티팩트면 본문만 — html 파일을 노트로 복사하지 않는다
    def test_to_note_of_an_artifact_saves_text_only_and_never_copies_html(self):
        from aot.databases.models import Notes
        self._login()
        card = self._mk_artifact(title='Page', body='caption text')
        r = self.client.post('/api/v1/ai-inbox/%s/to-note' % card.unique_id, json={})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.note_ids.append(r.get_json()['note_id'])
        note = Notes.query.filter(Notes.unique_id == r.get_json()['note_id']).first()
        self.assertTrue(note.note.startswith('caption text'))
        self.assertFalse(note.files)
        self.assertEqual(os.listdir(self.notes_root), [])
        self.assertIsNone(F.copy_to_notes(card.file_path, card.file_name, self.C._now()))
        self.assertNotIn('html', F.COPY_SAFE_EXTS)
        self.assertIn('csv', F.COPY_SAFE_EXTS)


# ── B2·B3 [공지로 게시] ─────────────────────────────────────────────────────

class ToNoticeTest(_P2Base):

    def test_publishes_edited_title_body_with_ai_tail_and_audit(self):
        from aot.databases.models import AuditLog
        self._login()
        card = self.C.create(self.pk, 'Card title', 'card body', 'Claude')
        r = self._publish(card, title='  My   title ', body='Edited body\n\nline 2',
                          include_file=False)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        j = r.get_json()
        self.assertEqual(set(j), {'ok', 'notice_id'})
        self.assertTrue(j['ok'])
        posts = self._notices()
        self.assertEqual(len(posts), 1)
        p = posts[0]
        self.assertEqual(p.unique_id, j['notice_id'])
        self.assertEqual(p.title, 'My title')
        today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
        self.assertEqual(p.body, 'Edited body\n\nline 2\n\n— AI 초안: Claude, ' + today)
        self.assertEqual((p.user_id, p.pinned, p.publish_at, p.expire_at, p.category, p.files),
                         (self.pk, False, None, None, None, None))
        from aot.databases.models import NoticePoll
        self.assertEqual(NoticePoll.query.filter(NoticePoll.post_id == p.id).count(), 0)
        # 카드에 기록되고 목록에 나온다
        item = self.client.get('/api/v1/ai-inbox').get_json()
        self.assertEqual(item['items'][0]['notice_id'], j['notice_id'])
        self.assertIs(item['can_notice'], True)
        # 감사 한 줄
        rows = AuditLog.query.filter(AuditLog.action == 'ai_card.to_notice').all()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].target_type, rows[0].target_id, rows[0].user_id),
                         ('AICard', card.unique_id, self.pk))
        self.assertEqual(rows[0].detail, '%s · My title' % j['notice_id'])

    def test_tail_cannot_be_removed_and_empty_body_gets_only_the_tail(self):
        self._login()
        card = self.C.create(self.pk, 'T', 'b', 'Bot')
        self._publish(card, title='only title')
        p = self._notices()[0]
        today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
        self.assertEqual(p.body, '— AI 초안: Bot, ' + today)
        card2 = self.C.create(self.pk, 'T2', 'b', 'Bot')
        self._publish(card2, title='x', body='mine — AI 초안: Someone else, 2020-01-01')
        self.assertTrue(self._notices()[1].body.endswith('— AI 초안: Bot, ' + today))

    def test_title_falls_back_to_card_title_then_file_name_and_empty_is_400(self):
        self._login()
        c1 = self.C.create(self.pk, 'Card title', 'b', 'AI')
        self._publish(c1, body='text')
        c2 = self._mk_file_card('weekly.csv', 'a,b', title='')
        c2.title = ''
        from aot.aot_flask.extensions import db
        db.session.commit()
        self._publish(c2, body='text', title='   ')
        self.assertEqual([p.title for p in self._notices()], ['Card title', 'weekly.csv'])
        c3 = self.C.create(self.pk, 'T', 'b', 'AI')
        for body in ({}, {'title': '', 'body': ''}, {'title': '  \n ', 'body': ' \t'},
                     {'title': None, 'body': None}):
            r = self._publish(c3, **body)
            self.assertEqual((r.status_code, r.get_json()), (400, {'error': 'empty'}), body)
        self.assertEqual(len(self._notices()), 2)

    def test_length_and_type_validation(self):
        self._login()
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        for body, code in (({'title': 'a' * 121}, 'too_long'), ({'body': 'a' * 10001}, 'too_long'),
                           ({'title': 'a' * 5000}, 'too_long'),
                           ({'body': 'a' * 30000}, 'too_long'),
                           ({'title': 5, 'body': 'x'}, 'bad_request'),
                           ({'title': 'x', 'body': ['a']}, 'bad_request'),
                           ({'title': 'x', 'include_file': 'yes'}, 'bad_request'),
                           ({'title': 'x', 'include_file': 1}, 'bad_request')):
            r = self._publish(card, **body)
            self.assertEqual((r.status_code, r.get_json()), (400, {'error': code}), body)
        for raw in ('not json', '[1, 2]', '"s"'):
            r = self.client.post(self._nurl(card), data=raw, content_type='application/json')
            self.assertEqual((r.status_code, r.get_json()), (400, {'error': 'bad_request'}), raw)
        self.assertEqual(self._notices(), [])
        # 경계값은 통과
        r = self._publish(card, title='a' * 120, body='b' * 10000)
        self.assertEqual(r.status_code, 200)
        p = self._notices()[0]
        self.assertEqual(len(p.title), 120)
        self.assertTrue(p.body.startswith('b' * 10000 + '\n\n— AI 초안: '))

    def test_control_and_bidi_characters_are_cleaned(self):
        self._login()
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        self._publish(card, title='a‮b\x00c\nd', body='x⁦y\x07z')
        p = self._notices()[0]
        self.assertEqual(p.title, 'ab c d')       # 제어문자는 공백, 양방향 문자는 삭제
        self.assertTrue(p.body.startswith('xyz'))

    def test_permission_ownership_and_check_order(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Role, User
        mine = self.C.create(self.pk, 't', 'b', 'AI')
        theirs = self.C.create(self.other.id, 't', 'b', 'AI')
        role = Role(name=self.tag + '_n', edit_settings=False, edit_controllers=False,
                    edit_users=False, use_ai_chat=True)
        db.session.add(role)
        db.session.commit()
        nope = User(name=self.tag + '_n', role_id=role.id, is_enabled=True)
        db.session.add(nope)
        db.session.commit()
        try:
            weak = self.C.create(nope.id, 't', 'b', 'AI')
            self._login(nope)
            r = self._publish(weak, title='x')
            self.assertEqual((r.status_code, r.get_json()), (403, {'error': 'permission_denied'}))
            # 권한 검사가 카드 조회보다 먼저다 — 남의 카드여도 403(존재를 묻지 않는다)
            r = self._publish(theirs, title='x')
            self.assertEqual(r.status_code, 403)
            lst = self.client.get('/api/v1/ai-inbox').get_json()
            self.assertIs(lst['can_notice'], False)
            self.assertEqual(self._notices(nope.id), [])
            self._login()
            # API 키가 가장 먼저(권한·소유보다) — 403 api_key_not_allowed
            r = self.client.post(self._nurl(theirs), json={'title': 'x'},
                                 headers={'X-API-KEY': 'bm90LWEta2V5'})
            self.assertEqual((r.status_code, r.get_json()), (403, {'error': 'api_key_not_allowed'}))
            # 남의 카드·없는 카드는 404 not_found
            for url in (self._nurl(theirs), '/api/v1/ai-inbox/nope/to-notice',
                        '/api/v1/ai-inbox/%s/to-notice' % ('0' * 36)):
                r = self.client.post(url, json={'title': 'x'})
                self.assertEqual((r.status_code, r.get_json()), (404, {'error': 'not_found'}), url)
            # 만료된 카드
            mine.expires_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
            db.session.commit()
            r = self._publish(mine, title='x')
            self.assertEqual((r.status_code, r.get_json()), (404, {'error': 'not_found'}))
            self.assertEqual(self._notices(), [])
            self.assertEqual(self._notices(self.other.id), [])
            # 익명
            self._clear_scope_cache()
            r = self.app.test_client().post(self._nurl(theirs), json={'title': 'x'})
            self.assertIn(r.status_code, (302, 401))
        finally:
            db.session.rollback()
            from aot.databases.models.ai_screen_card import AIScreenCard
            from aot.databases.models.ai_card_attachment import AICardAttachment
            AICardAttachment.query.filter(AICardAttachment.user_id == nope.id).delete()
            AIScreenCard.query.filter(AIScreenCard.user_id == nope.id).delete()
            User.query.filter(User.id == nope.id).delete()
            Role.query.filter(Role.id == role.id).delete()
            db.session.commit()

    def test_csrf_is_enforced_for_post(self):
        self._login()
        card = self.C.create(self.pk, 't', 'b', 'AI')
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            r = self._publish(card, title='x')
            self.assertEqual(r.status_code, 400)
            self.assertEqual(self._notices(), [])
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    # B2 멱등
    def test_second_publish_is_already_with_the_same_notice_and_one_audit_row(self):
        from aot.databases.models import AuditLog
        self._login()
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        j1 = self._publish(card, title='one').get_json()
        r2 = self._publish(card, title='two', body='different')
        self.assertEqual((r2.status_code, r2.get_json()),
                         (200, {'ok': True, 'notice_id': j1['notice_id'], 'already': True}))
        self.assertEqual(len(self._notices()), 1)
        self.assertEqual(self._notices()[0].title, 'one')
        self.assertEqual(AuditLog.query.filter(AuditLog.action == 'ai_card.to_notice').count(), 1)

    def test_republish_after_the_notice_was_deleted(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import NoticePost
        self._login()
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        j1 = self._publish(card, title='one').get_json()
        NoticePost.query.filter(NoticePost.unique_id == j1['notice_id']).delete()
        db.session.commit()
        # 지워진 공지는 목록에 나오지 않는다(다시 게시 가능)
        item = self.client.get('/api/v1/ai-inbox').get_json()['items'][0]
        self.assertIsNone(item['notice_id'])
        r = self._publish(card, title='again')
        j2 = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('already', j2)
        self.assertNotEqual(j2['notice_id'], j1['notice_id'])
        self.assertEqual([p.title for p in self._notices()], ['again'])
        self.assertEqual(self.client.get('/api/v1/ai-inbox').get_json()['items'][0]['notice_id'],
                         j2['notice_id'])

    def test_losing_the_claim_race_returns_already_and_leaves_no_second_notice(self):
        """다른 워커가 검사와 UPDATE 사이에 먼저 게시했다 — 조건부 UPDATE 가 rowcount 0 이라
        이쪽은 INSERT 하지 않고 이긴 쪽의 공지를 already 로 돌려준다(복사한 첨부는 지운다)."""
        import sqlalchemy as sa
        from aot.aot_flask.extensions import db
        self._login()
        card = self._mk_file_card('w.csv', 'a,b', title='Weekly')
        winner = 'w' * 8 + '-0000-0000-0000-' + '0' * 12

        def other_worker_wins(*_a, **_k):
            with db.engine.begin() as conn:
                conn.execute(sa.text("UPDATE ai_screen_cards SET notice_id=:n WHERE id=:i"),
                             {'n': winner, 'i': card.id})
                conn.execute(sa.text(
                    "INSERT INTO notice_posts (unique_id, title, body, pinned, user_id, "
                    "date_time) VALUES (:n, 'won', 'b', 0, :u, CURRENT_TIMESTAMP)"),
                    {'n': winner, 'u': self.pk})
            return False                       # (rate_problem 의 값) — 제한에는 안 걸린다

        with mock.patch.object(self.C, '_notice_rate_problem', side_effect=other_worker_wins):
            r = self._publish(card, title='lost', include_file=True)
        self.assertEqual((r.status_code, r.get_json()),
                         (200, {'ok': True, 'notice_id': winner, 'already': True}))
        self.assertEqual([p.title for p in self._notices()], ['won'])
        self.assertEqual(self._notice_files(), [])           # 복사본 정리
        from aot.databases.models import AuditLog
        self.assertEqual(AuditLog.query.filter(AuditLog.action == 'ai_card.to_notice').count(), 0)

    def test_stale_notice_id_is_replaced_with_a_conditional_update(self):
        """카드 notice_id 가 지워진 공지를 가리키면 `notice_id = :old` 로 자리를 잡는다."""
        from aot.aot_flask.extensions import db
        self._login()
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        card.notice_id = 'gone-' + '0' * 31
        db.session.commit()
        r = self._publish(card, title='fresh')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('already', r.get_json())
        db.session.refresh(card)
        self.assertEqual(card.notice_id, r.get_json()['notice_id'])

    def test_two_threads_at_once_publish_exactly_one_notice(self):
        from aot.aot_flask.extensions import db
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        uid = self.user.get_id()
        url = self._nurl(card)
        barrier = threading.Barrier(2)
        results = []

        def worker(n):
            with self.app.app_context():
                client = self.app.test_client()
                with client.session_transaction() as sess:
                    sess['_user_id'] = uid
                    sess['_fresh'] = True
                barrier.wait()
                r = client.post(url, json={'title': 'race %d' % n})
                results.append((r.status_code, r.get_json()))
                db.session.remove()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(len(results), 2, results)
        self.assertTrue(all(code == 200 for code, _ in results), results)
        ids = {j['notice_id'] for _, j in results}
        self.assertEqual(len(ids), 1, results)
        self.assertEqual(sum(1 for _, j in results if j.get('already')), 1, results)
        self.assertEqual(len(self._notices()), 1)

    def test_hourly_limit_of_20_is_429_but_already_still_answers(self):
        self._login()
        made = [self.C.create(self.pk, 'T%d' % i, 'b', 'AI') for i in range(21)]
        for c in made[:20]:
            self.assertEqual(self._publish(c, title='n').status_code, 200)
        r = self._publish(made[20], title='n')
        self.assertEqual((r.status_code, r.get_json()), (429, {'error': 'rate_limited'}))
        self.assertEqual(len(self._notices()), 20)
        # 이미 게시한 카드의 재시도는 한도와 무관하게 already
        r = self._publish(made[0], title='n')
        self.assertEqual((r.status_code, r.get_json().get('already')), (200, True))
        # 한 시간이 지나면(감사 행이 1시간 이전이면) 다시 된다
        from aot.aot_flask.extensions import db
        from aot.databases.models import AuditLog
        for row in AuditLog.query.filter(AuditLog.action == 'ai_card.to_notice').all():
            row.timestamp = row.timestamp - datetime.timedelta(hours=2)
        db.session.commit()
        self.assertEqual(self._publish(made[20], title='n').status_code, 200)
        # 다른 사람의 한도는 따로
        self.assertEqual(len(self._notices(self.other.id)), 0)

    # B3 첨부
    def test_image_and_csv_attachments_are_copied_with_the_post_prefix(self):
        self._login()
        prep = F.prepare({'name': 'pic.png', 'b64': _B64(_img('PNG'))}, self.user, self.pk)
        rel = F.store(prep['ext'], prep['data'], prep['thumb'], self.C._now())
        img, _ = self.C.create_limited(self.pk, 'img', 'b', 'AI', None, file={
            'path': rel, 'name': prep['name'], 'mime': prep['mime'],
            'size': len(prep['data']), 'kind': 'image'})
        csv_card = self._mk_file_card('weekly report.csv', 'a,b\n1,2', title='Weekly')
        j1 = self._publish(img, title='Photo', include_file=True).get_json()
        j2 = self._publish(csv_card, title='Report', include_file=True).get_json()
        p1, p2 = self._notices()
        self.assertEqual(p1.files, '%s_pic.png' % j1['notice_id'])
        self.assertEqual(p2.files, '%s_weekly_report.csv' % j2['notice_id'])
        for name, src in ((p1.files, F.resolve(img.file_path)),
                          (p2.files, F.resolve(csv_card.file_path))):
            copy = os.path.join(self.notice_root, name)
            self.assertEqual(open(copy, 'rb').read(), open(src, 'rb').read())
            self.assertEqual(stat.S_IMODE(os.stat(copy).st_mode), 0o640)
            self.assertNotEqual(os.path.realpath(copy), os.path.realpath(src))
        self.assertEqual(len(self._notice_files()), 2)            # .part 조각 없음
        # 카드 쪽 파일이 지워져도 공지 첨부는 산다
        os.unlink(F.resolve(csv_card.file_path))
        self.assertTrue(os.path.isfile(os.path.join(self.notice_root, p2.files)))
        # 감사 detail 에 (+파일)
        from aot.databases.models import AuditLog
        d = AuditLog.query.filter(AuditLog.action == 'ai_card.to_notice',
                                  AuditLog.target_id == img.unique_id).first().detail
        self.assertEqual(d, '%s · Photo (+파일)' % j1['notice_id'])

    def test_pdf_is_copied_as_is_and_include_file_without_a_file_is_ignored(self):
        self._login()
        prep = F.prepare({'name': 'doc.pdf', 'b64': _B64(_PDF)}, self.user, self.pk)
        rel = F.store(prep['ext'], prep['data'], None, self.C._now())
        card, _ = self.C.create_limited(self.pk, 'pdf', 'b', 'AI', None, file={
            'path': rel, 'name': 'doc.pdf', 'mime': 'application/pdf',
            'size': len(_PDF), 'kind': 'file'})
        j = self._publish(card, title='P', include_file=True).get_json()
        self.assertEqual(self._notices()[0].files, '%s_doc.pdf' % j['notice_id'])
        text_card = self.C.create(self.pk, 'T', 'b', 'AI')
        r = self._publish(text_card, title='no file', include_file=True)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._notices()[1].files)

    def test_md_and_json_become_txt_and_html_is_refused(self):
        self._login()
        md = self._mk_file_card('notes.md', '# hi', title='M')
        js = self._mk_file_card('data.json', '{"a": 1}', title='J')
        html = self._mk_artifact(title='H')
        jm = self._publish(md, title='m', include_file=True).get_json()
        jj = self._publish(js, title='j', include_file=True).get_json()
        self.assertEqual([p.files for p in self._notices()],
                         ['%s_notes.txt' % jm['notice_id'], '%s_data.txt' % jj['notice_id']])
        self.assertEqual(open(os.path.join(self.notice_root, self._notices()[0].files)).read(),
                         '# hi')
        before = self._notice_files()
        r = self._publish(html, title='h', body='b', include_file=True)
        self.assertEqual((r.status_code, r.get_json()), (400, {'error': 'file_not_allowed'}))
        self.assertEqual(len(self._notices()), 2)
        self.assertEqual(self._notice_files(), before)
        from aot.aot_flask.extensions import db
        db.session.refresh(html)
        self.assertIsNone(html.notice_id)
        # 같은 아티팩트라도 첨부 없이는 본문만 게시된다
        r = self._publish(html, title='h', body='b', include_file=False)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._notices()[2].files)
        self.assertIsNone(F.notice_ext('html'))
        self.assertEqual(F.notice_ext('md'), 'txt')
        self.assertIsNone(F.notice_ext('exe'))

    def test_notice_file_names_never_escape_the_folder(self):
        for name in ('../../etc/passwd.csv', '/abs/path.csv', 'a b/../c.csv', '한글 이름.csv',
                     '..csv', '.csv', 'x' * 300 + '.csv'):
            out = F.notice_file_name('P' * 36, name, 'csv')
            self.assertTrue(out.startswith('P' * 36 + '_'), out)
            self.assertNotIn('/', out)
            self.assertNotIn('\\', out)
            self.assertEqual(os.path.basename(out), out)
            self.assertTrue(out.endswith('.csv'))
            self.assertLessEqual(len(out), 36 + 1 + 80 + 4)
        self.assertEqual(F.notice_file_name('P' * 36, '한글.csv', 'csv'), 'P' * 36 + '_ai-file.csv')

    def test_nothing_is_left_when_the_copy_or_the_database_fails(self):
        from aot.aot_flask.extensions import db
        self._login()
        card = self._mk_file_card('w.csv', 'a,b', title='W')
        # 복사 실패(디스크)
        with mock.patch.object(F.shutil, 'copyfile', side_effect=OSError('disk')):
            r = self._publish(card, title='x', include_file=True)
        self.assertEqual((r.status_code, r.get_json()), (500, {'error': 'notice_failed'}))
        self.assertEqual((self._notices(), self._notice_files()), ([], []))
        db.session.refresh(card)
        self.assertIsNone(card.notice_id)
        # 복사는 됐는데 공지 INSERT/commit 이 실패 — 복사본과 notice_id 모두 되돌린다
        with mock.patch('aot.databases.models.NoticePost', side_effect=RuntimeError('db')):
            r = self._publish(card, title='x', include_file=True)
        self.assertEqual((r.status_code, r.get_json()), (500, {'error': 'notice_failed'}))
        self.assertEqual((self._notices(), self._notice_files()), ([], []))
        db.session.refresh(card)
        self.assertIsNone(card.notice_id)
        # 원본이 사라졌으면 404, 공지도 파일도 없다
        os.unlink(F.resolve(card.file_path))
        r = self._publish(card, title='x', include_file=True)
        self.assertEqual(r.status_code, 404)
        self.assertEqual((self._notices(), self._notice_files()), ([], []))
        # 이후 정상 게시는 된다(상태가 깨끗하다)
        self.assertEqual(self._publish(card, title='ok').status_code, 200)

    def test_deleting_the_notice_removes_its_attachment_copy(self):
        """공지 삭제(notice_del)가 복사본 파일을 지운다 — AI 용량 한도 밖, 공지 수명."""
        from aot.aot_flask.utils import utils_notice
        self._login()
        card = self._mk_file_card('w.csv', 'a,b', title='W')
        j = self._publish(card, title='x', include_file=True).get_json()
        self.assertEqual(len(self._notice_files()), 1)
        with self.app.test_request_context('/'):
            from flask_login import login_user
            login_user(self.user)
            errors = utils_notice.notice_del(j['notice_id'])
        self.assertEqual(errors, [])
        self.assertEqual(self._notice_files(), [])

    def test_publishing_never_reads_the_files_body_into_the_notice(self):
        self._login()
        card = self._mk_file_card('secret.txt', 'TOP SECRET TEXT', title='S', body='visible')
        self._publish(card, title='x', body='mine', include_file=False)
        self.assertNotIn('TOP SECRET', self._notices()[0].body)


# ── B4 공지 첨부 서빙 ───────────────────────────────────────────────────────

class NoticeAttachmentTest(_P2Base):

    def setUp(self):
        super().setUp()
        self._login()
        self.secret = os.path.join(self.tmp, 'secret.txt')
        with open(self.secret, 'w') as fh:
            fh.write('SECRET')
        with open(os.path.join(self.notice_root, 'abc_note.txt'), 'w') as fh:
            fh.write('hello notice')
        with open(os.path.join(self.notice_root, 'abc_pic.png'), 'wb') as fh:
            fh.write(_img('PNG'))

    def _get(self, name):
        try:
            return self.client.get('/notice_attachment/' + name)
        except Exception as exc:       # 라우터 단계의 404 — 이 테스트 DB 엔 404 쪽 템플릿 값이 없다
            if getattr(exc, 'code', None) != 404 and 'custom_css' not in repr(exc) \
                    and 'NotFound' not in repr(exc):
                raise
            import types
            return types.SimpleNamespace(status_code=404, data=b'')

    def test_existing_attachments_are_served_with_nosniff(self):
        r = self._get('abc_note.txt')
        self.assertEqual((r.status_code, r.get_data(as_text=True)), (200, 'hello notice'))
        self.assertEqual(r.mimetype, 'text/plain')
        self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')
        r = self._get('abc_pic.png')
        self.assertEqual((r.status_code, r.mimetype), (200, 'image/png'))
        self.assertEqual(r.data, _img('PNG'))
        self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')

    def test_traversal_absolute_paths_and_symlinks_are_404(self):
        rel = os.path.relpath(self.secret, self.notice_root)       # ../secret.txt
        for name in (rel, '../' + 'secret.txt', 'sub/../../secret.txt', self.secret,
                     '/' + self.secret, '..%2Fsecret.txt', '%2e%2e/secret.txt', '..\\secret.txt',
                     'abc_note.txt/../../secret.txt', 'abc_note.txt%00.png', '', '.', 'nope.txt'):
            r = self._get(name)
            # 맨앞 `/` 는 라우터가 슬래시를 합치며 308 로 돌려보낸다 — 어느 쪽이든 내주지 않는다
            self.assertIn(r.status_code, (404, 308), name)
            self.assertNotIn(b'SECRET', r.data, name)
        # 폴더 안 심볼릭 링크가 밖을 가리킨다
        os.symlink(self.secret, os.path.join(self.notice_root, 'link.txt'))
        r = self._get('link.txt')
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b'SECRET', r.data)
        # 폴더 자체
        os.makedirs(os.path.join(self.notice_root, 'dir'))
        self.assertEqual(self._get('dir').status_code, 404)
        # 함수 직접 호출(라우팅 정규화를 거치지 않는다)
        from aot.aot_flask.routes_notice import send_notice_attachment
        with self.app.test_request_context('/'):
            from flask_login import login_user
            login_user(self.user)
            for name in ('../secret.txt', '../../secret.txt', self.secret, 'a\x00b'):
                body, code = send_notice_attachment(name)
                self.assertEqual(code, 404, name)

    def test_active_content_in_the_folder_is_only_downloaded(self):
        with open(os.path.join(self.notice_root, 'abc_x.html'), 'w') as fh:
            fh.write('<script>alert(1)</script>')
        with open(os.path.join(self.notice_root, 'abc_x.svg'), 'w') as fh:
            fh.write('<svg onload=alert(1)/>')
        for name in ('abc_x.html', 'abc_x.svg'):
            r = self._get(name)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers['Content-Disposition'].startswith('attachment'), name)
            self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')

    def test_login_is_still_required(self):
        self._clear_scope_cache()
        r = self.app.test_client().get('/notice_attachment/abc_note.txt')
        self.assertIn(r.status_code, (302, 401))


# ── B10 어떤 screen 명령·도구도 공지 게시를 부르지 않는다 ───────────────────────

class NoAutoPublishTest(_P2Base):

    def test_only_the_web_route_references_publish_to_notice(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        hits = []
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ('tests', 'node_modules', '__pycache__',
                                                    'static', 'dist')]
            for n in names:
                if not n.endswith('.py'):
                    continue
                path = os.path.join(d, n)
                with open(path, encoding='utf-8', errors='replace') as fh:
                    found = re.search(r'publish_to_notice|ai_card\.to_notice|AI_CARD_TO_NOTICE',
                                      fh.read())
                if found:
                    hits.append(os.path.relpath(path, root))
        self.assertEqual(sorted(hits), ['aot_flask/routes_ai_inbox_api.py', 'utils/ai_screen_cards.py',
                                        'utils/audit.py'])
        # 도구·MCP·인앱 AI 쪽에는 이름도 없다
        for sub in ('tools', 'ai', 'mcp_server'):
            for d, _dirs, names in os.walk(os.path.join(root, sub)):
                for n in names:
                    if n.endswith('.py'):
                        with open(os.path.join(d, n), encoding='utf-8', errors='replace') as fh:
                            self.assertNotIn('to_notice', fh.read(), os.path.join(d, n))
        with open(os.path.join(root, 'aot_mcp_server.py'), encoding='utf-8') as fh:
            self.assertNotIn('to_notice', fh.read())

    def test_screen_action_calls_never_publish_or_create_notices(self):
        card = self.C.create(self.pk, 'T', 'b', 'AI')
        with mock.patch.object(self.C, 'publish_to_notice',
                               side_effect=AssertionError('published')) as pub:
            for args in ({'action': 'post', 'message': 'hi'},
                         {'action': 'post', 'message': 'x', 'attach': {'name': 'a.html',
                                                                      'text': _HTML}},
                         {'action': 'read'}, {'action': 'read', 'item': card.unique_id[:8]},
                         {'action': 'to_notice', 'item': card.unique_id[:8]},
                         {'action': 'publish', 'item': card.unique_id},
                         {'action': 'notice', 'item': card.unique_id, 'title': 'x'}):
                self._backdate(minutes=2)
                self._act(args)
            pub.assert_not_called()
        self.assertEqual(self._notices(), [])
        from aot.databases.models.ai_screen_card import AIScreenCard
        self.assertTrue(all(c.notice_id is None for c in AIScreenCard.query.filter(
            AIScreenCard.user_id == self.pk).all()))

    def test_no_notice_tool_exists_in_the_catalog(self):
        from aot.tools import tool_registry
        names = [t['tool_name'] for t in tool_registry._MCP_TOOL_PAYLOADS]
        self.assertFalse([n for n in names if 'to_notice' in n or n == 'publish_to_notice'])
        spec = next(t for t in tool_registry._MCP_TOOL_PAYLOADS
                    if t['tool_name'] == 'screen_action')
        enum = spec['input_schema']['properties']['action']['enum']
        self.assertFalse([a for a in enum if 'notice' in a or 'publish' in a])


# ── B11 토큰 ────────────────────────────────────────────────────────────────

class CostTest(_P2Base):

    def test_screen_action_description_and_schema_are_unchanged(self):
        from aot.scripts.measure_ai_tool_cost import _tok
        from aot.tools import tool_registry
        spec = next(t for t in tool_registry._MCP_TOOL_PAYLOADS
                    if t['tool_name'] == 'screen_action')
        chars, tokens = _tok({'name': spec['tool_name'], 'description': spec['description'],
                              'inputSchema': spec['input_schema']})
        self.assertEqual((chars, tokens), (1551, 775))   # orbit 이름 변경 -5자. P5: 배열(+3)·+attach/동의 문구 줄임(-10-8+3)
        self.assertNotIn('html', spec['description'].lower())
        self.assertNotIn('notice', spec['description'].lower())
        self.assertNotIn('resource', json.dumps(spec['input_schema']).lower())


class NoticeLinkPreviewImageTest(_P2Base):
    """P2 보안 리뷰 M1 — AI 초안 공지의 링크 미리보기가 남의 페이지 og:image 를 그대로 돌려줘
    공지 화면이 <img src="…"> 에 이어 붙였다(따옴표로 onerror 주입). 서버는 절대 http(s) 주소만."""

    def _preview(self, og_image):
        import aot.aot_flask.routes_notice as rn
        page = ('<html><head><meta property="og:title" content="t">'
                '<meta property="og:image" content="%s"></head></html>' % og_image)
        rn._fetch_link_preview.cache_clear()
        with mock.patch('aot.utils.ai_card_fetch.fetch_public',
                        return_value=(page.encode('utf-8'), 'https://evil.example/page')):
            out = rn._fetch_link_preview('https://evil.example/page')
        rn._fetch_link_preview.cache_clear()
        return out['image']

    def test_attribute_breakout_and_non_http_images_are_dropped(self):
        for bad in ('x&quot; onerror=&quot;alert(document.cookie)',
                    'https://evil.example/a.png&quot; onerror=&quot;x',
                    "https://evil.example/a.png' onerror='x",
                    'https://evil.example/a b.png', 'https://evil.example/a<b>.png',
                    'javascript:alert(1)', 'data:image/png;base64,AAAA',
                    'https://' + 'a' * 2100 + '.example/x.png'):
            self.assertIsNone(self._preview(bad), bad)

    def test_normal_and_relative_images_become_absolute_http(self):
        self.assertEqual(self._preview('https://cdn.example/i.png?a=1&amp;b=2'),
                         'https://cdn.example/i.png?a=1&b=2')
        self.assertEqual(self._preview('/img/og.jpg'), 'https://evil.example/img/og.jpg')
        self.assertEqual(self._preview('//cdn.example/x.webp'), 'https://cdn.example/x.webp')
