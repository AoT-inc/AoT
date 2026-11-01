# coding=utf-8
"""날씨·장소 요약 카드는 서버가 올린다 — 카드 결정 A(사용자 2026-10-29), 설계 plans/mcp_act_say_split_design.md §8.

고정하는 계약:
  1. 외부 연결의 overview.place · weather.now · weather.forecast 조회가 성공하면 서버가 그 값으로 카드 한 장을 올린다.
     응답에는 `card`(올렸음) 와 선택 호출(`next.optional`, 결론 한 줄)만 남고 `card_hint` 는 없다.
  2. 같은 카드는 두 번 오르지 않는다(DUPLICATE_WINDOW) — 두 번째는 `already_shown`.
  3. 설정 '자동 카드'가 꺼져 있으면 올리지 않는다. 인앱(외부가 아닌) 호출·실패한 조회·`_show_on_screen='off'` 도 올리지 않는다.
  4. 성공한 응답에는 언제나 `card` 한 칸(`state` posted|already_shown|skipped, `reason`, `title`)이 있다. 서버가 일부러 올리지
     않았으면 까닭을 적고 AI 에게 카드를 만들라고 하지 않는다. 올리려다 못 했을 때만 `next.call` 이 남는다(2026-10-30).
  5. 카드 글은 사용자 언어다(웹 화면과 같은 번역, 언어는 그 사용자의 언어 설정). 값·단위는 그대로.
"""
import json
import unittest
from unittest import mock

from aot.tests.test_ai_screen_cards import _AGENT, _Base
from aot.tools.domain import server_card

_FORECAST = {
    "status": "success", "card_hint": "Summary or weather answer: show one card now.",
    "answered_for": {"name": "영양"},
    "period": {"start": "2026-10-29T00:00", "end": "2026-10-30T00:00", "hours": 24},
    "summary": {
        "relative_humidity (%)": {"min": 40, "max": 90, "max_at": "10-29 05:00", "min_at": "", "avg": 60},
        "temperature (°C)": {"min": 4.25, "max": 17.0, "max_at": "10-29 14:00", "min_at": "", "avg": 10},
        "precipitation (mm)": {"min": 0, "max": 1.2, "sum": 3.4, "first_at": "10-29 17:00", "avg": 0.1},
    },
}


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}]


class ComposeTest(unittest.TestCase):

    def test_forecast_card_is_short_values_first(self):
        title, msg = server_card.compose('forecast', dict(_FORECAST))
        self.assertEqual('영양 forecast', title)
        lines = msg.splitlines()
        self.assertLessEqual(len(lines), server_card.MAX_LINES)
        self.assertIn('model forecast', lines[0])
        self.assertTrue(lines[1].startswith('Temperature 4.2–17 °C') or lines[1].startswith('Temperature 4.3–17 °C'),
                        lines[1])
        self.assertIn('Precipitation total 3.4 mm, from 10-29 17:00', lines[2])

    def test_fanned_out_forecast_is_one_card_with_a_line_per_place(self):
        body = {"status": "success", "results": [
            {"target": {"name": "영양"}, "result": dict(_FORECAST)},
            {"target": {"name": "김제"}, "result": dict(_FORECAST)}]}
        title, msg = server_card.compose('forecast', body)
        self.assertEqual('Forecast', title)
        self.assertEqual(2, len(msg.splitlines()))
        self.assertTrue(msg.startswith('영양: Temperature'))

    def test_observed_and_place_cards(self):
        title, msg = server_card.compose('now', {"read_as": {"target": {"name": "김제"}}, "summary": [
            {"measurement": "temperature", "unit": "°C", "latest": 12.3, "min": 8, "max": 14}]})
        self.assertEqual(('김제 weather now', 'Temperature 12.3 °C (8–14)'), (title, msg))
        title, msg = server_card.compose('place', {
            "place": {"name": "3포장"},
            "sensors": {"temperature": {"avg": 21.3, "unit": "°C", "n": 2},
                        "soil": {"moisture": {"avg": 31, "unit": "%", "n": 1}}},
            "alert": {"count": 2}, "stale_sensors": {"count": 1, "names": ["a"]}})
        self.assertEqual('3포장 summary', title)
        self.assertEqual(['Air: Temperature 21.3 °C', 'Soil: Moisture 31 %', 'Alerts: 2', 'Silent sensors: 1'],
                         msg.splitlines())

    def test_nothing_to_fold_is_no_card(self):
        self.assertIsNone(server_card.compose('forecast', {"status": "success"}))
        self.assertIsNone(server_card.compose('place', {"place": {"name": "x"}}))


class GateTest(unittest.TestCase):
    _CTX = {'scope_user_uuid': 'u', 'transport': 'mcp_http', 'tool_profile': None}

    def _post_for(self, body, ctx=None, show=None, auto=True, posted=None, tool=('weather', 'forecast')):
        calls = []

        def fake_execute(app, name, args, **kw):
            calls.append((name, dict(args)))
            return _out(posted if posted is not None else {"status": "posted", "card": "abcd1234"})
        with mock.patch('aot.tools.tool_execution._execute_tool', fake_execute), \
                mock.patch('aot.utils.ai_screen_cards.card_auto_enabled', lambda: auto):
            got = server_card.post_for(None, tool[0], tool[1], _out(body), ctx or self._CTX, show)
        return json.loads(got[0]['text']), calls

    def test_posts_once_and_drops_the_hint(self):
        body, calls = self._post_for(dict(_FORECAST))
        self.assertEqual(1, len(calls))
        self.assertEqual(('screen_action', 'post'), (calls[0][0], calls[0][1]['action']))
        self.assertEqual('영양 forecast', calls[0][1]['title'])
        self.assertNotIn('card_hint', body)
        self.assertEqual({'state': 'posted', 'title': '영양 forecast'}, body['card'])
        self.assertIn("screen(op='card'", body['next']['optional'])

    def test_setting_off_posts_nothing_and_says_why(self):
        body, calls = self._post_for(dict(_FORECAST), auto=False)
        self.assertEqual([], calls)
        self.assertEqual({'state': 'skipped', 'reason': 'card_auto_off'}, body['card'])
        self.assertNotIn('card_hint', body)
        self.assertNotIn('next', body)

    def test_hidden_screen_and_failed_lookup_post_nothing(self):
        """`_show_on_screen=off` 는 서버가 일부러 올리지 않는다 — 까닭을 적고 AI 에게 카드를 만들라고 하지 않는다(10-30 점검 3-1)."""
        body, calls = self._post_for(dict(_FORECAST), show='off')
        self.assertEqual([], calls)
        self.assertEqual({'state': 'skipped', 'reason': 'screen_off'}, body['card'])
        self.assertNotIn('card_hint', body)
        self.assertNotIn('next', body)
        body, calls = self._post_for({"status": "error", "message": "x", "card_hint": "Summary or weather answer: show one card now."})
        self.assertEqual([], calls)
        self.assertNotIn('card', body)
        self.assertNotIn('card_hint', body)                  # 실패한 조회에 카드를 만들라고 남기지 않는다

    def test_in_app_and_other_ops_are_not_this_exit(self):
        for kw in ({'ctx': {'scope_user_uuid': 'u', 'transport': None}}, {'tool': ('overview', 'failure')}):
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                body, calls = self._post_for(dict(_FORECAST), **kw)
                self.assertEqual([], calls)
                self.assertNotIn('card', body)
                self.assertIn('card_hint', body)              # 인앱 AI 는 옛 안내를 그대로 받는다

    def test_nothing_to_fold_says_so(self):
        body, calls = self._post_for({"status": "success", "card_hint": "x", "answered_for": {"name": "영양"}})
        self.assertEqual([], calls)
        self.assertEqual({'state': 'skipped', 'reason': 'nothing_to_show'}, body['card'])
        self.assertNotIn('card_hint', body)
        self.assertNotIn('next', body)

    def test_a_failed_post_says_why_and_leaves_the_ai_a_call(self):
        body, calls = self._post_for(dict(_FORECAST), posted={"status": "error", "error": "Which screen? Several are open."})
        self.assertEqual(1, len(calls))
        self.assertEqual('skipped', body['card']['state'])
        self.assertTrue(body['card']['reason'].startswith('post_failed: Which screen?'), body['card'])
        self.assertEqual('영양 forecast', body['card']['title'])
        self.assertNotIn('card_hint', body)
        self.assertIn("title='영양 forecast'", body['next']['call'])
        self.assertNotIn('optional', body['next'])

    def test_every_success_of_the_three_ops_carries_the_same_card_shape(self):
        place = {"status": "success", "place": {"name": "3포장"}, "sensors": {"temperature": {"avg": 21.3, "unit": "°C"}}}
        now = {"status": "success", "read_as": {"target": {"name": "3포장"}},
               "summary": [{"measurement": "temperature", "unit": "°C", "latest": 12.3}]}
        for tool, body_in in ((('weather', 'forecast'), _FORECAST), (('weather', 'now'), now), (('overview', 'place'), place)):
            for kw in ({}, {'show': 'off'}, {'auto': False}):
                with self.subTest(tool=tool, **{k: str(v) for k, v in kw.items()}):
                    body, _c = self._post_for(dict(body_in), tool=tool, **kw)
                    self.assertEqual({'state', 'reason'} if kw else {'state', 'title'}, set(body['card']))

    def test_the_same_question_gets_the_same_title(self):
        """한 곳을 펼친 읽기도, 그릇(김제)을 펼친 읽기도 제목이 데이터가 아니라 사용자가 말한 이름에서 나온다(10-30 점검 3-4)."""
        one = {"target": {"name": "김제"}, "results": [{"target": {"name": "3포장"}, "result": dict(_FORECAST)}]}
        many = {"target": {"name": "김제"}, "results": [{"target": {"name": "3포장"}, "result": dict(_FORECAST)},
                                                         {"target": {"name": "1포장"}, "result": dict(_FORECAST)}]}
        self.assertEqual('김제 forecast', server_card.compose('forecast', one)[0])
        self.assertEqual('김제 forecast', server_card.compose('forecast', many)[0])
        no_container = {"results": [{"target": {"name": "3포장"}, "result": dict(_FORECAST)}]}
        self.assertEqual('3포장 forecast', server_card.compose('forecast', no_container)[0])
        now_one = {"summary": [{"measurement": "temperature", "unit": "°C", "latest": 1}]}
        got = server_card.compose('now', {"target": {"name": "김제"}, "results": [
            {"target": {"name": "3포장"}, "result": now_one}, {"target": {"name": "1포장"}, "result": now_one}]})
        self.assertEqual(('김제 weather now', '3포장: Temperature 1 °C\n1포장: Temperature 1 °C'), got)

    def test_the_domain_exit_posts_before_the_contract_shapes_it(self):
        """dispatch 출구 순서 — 서버 카드가 card_hint 를 떼면 계약(act_say)은 카드 호출을 next.call 로 만들지 않는다."""
        from aot.tools.domain import dispatch
        with mock.patch.object(dispatch, '_run_call_inner', lambda *a, **k: _out(dict(_FORECAST))), \
                mock.patch('aot.tools.tool_execution._execute_tool',
                           lambda *a, **k: _out({"status": "posted"})), \
                mock.patch('aot.utils.ai_screen_cards.card_auto_enabled', lambda: True):
            out = dispatch._run(None, 'weather', {'op': 'forecast', 'target': '영양'}, dict(self._CTX))
        body = json.loads(out[0]['text'])
        self.assertEqual(['status', 'next', 'card'], list(body)[:3])
        self.assertNotIn('call', body['next'])
        self.assertIn('optional', body['next'])
        self.assertEqual({'state': 'posted', 'title': '영양 forecast'}, body['card'])


    def test_weather_now_with_the_screen_off_never_tells_the_ai_to_make_a_card(self):
        """10-30 점검 3-1: `_show_on_screen=off` 의 weather.now 가 `card` 도 없이 next.call(카드를 만들라)만 돌려줬다."""
        from aot.tools.domain import dispatch
        now = {"status": "success", "card_hint": "Summary or weather answer: show one card now.",
               "summary": [{"measurement": "temperature", "unit": "°C", "latest": 12.3}]}
        for extra, want in (({'_show_on_screen': 'off'}, {'state': 'skipped', 'reason': 'screen_off'}),
                            ({}, {'state': 'posted', 'title': 'Weather now'})):
            with self.subTest(**extra), \
                    mock.patch.object(dispatch, '_run_call_inner', lambda *a, **k: _out(dict(now))), \
                    mock.patch('aot.tools.tool_execution._execute_tool',
                               lambda *a, **k: _out({"status": "posted"})), \
                    mock.patch('aot.utils.ai_screen_cards.card_auto_enabled', lambda: True):
                out = dispatch._run(None, 'weather', dict({'op': 'now', 'target': '3포장'}, **extra), dict(self._CTX))
            body = json.loads(out[0]['text'])
            self.assertEqual(want, body['card'])
            self.assertNotIn('card_hint', body)
            self.assertNotIn('call', body.get('next') or {})


class ServerCardLiveTest(_Base):
    """실제 카드 저장 — AI 가 쓰는 길(`screen_action` post)과 같은 감사·한도·중복 방지를 지난다."""

    def _set_auto(self, value):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Misc
        misc = Misc.query.first()
        if misc is None:
            misc = Misc()
            db.session.add(misc)
        before = misc.ai_card_auto
        misc.ai_card_auto = value
        db.session.commit()
        return before

    def _lookup(self):
        ctx = {'agent_id': _AGENT, 'scope_user_uuid': self.uid, 'transport': 'mcp_http'}
        out = server_card.post_for(self.app, 'weather', 'forecast', _out(dict(_FORECAST)), ctx)
        return json.loads(out[0]['text'])

    def test_posts_one_card_and_never_the_same_one_twice(self):
        self._screen('kserver' + 'a' * 14)
        before = self._set_auto(True)
        try:
            first = self._lookup()
            self.assertEqual({'state': 'posted', 'title': '영양 forecast'}, first['card'])
            self.assertEqual(1, len(self._cards()))
            again = self._lookup()                          # 같은 질문을 다시 — 같은 카드는 쌓지 않는다
            self.assertEqual({'state': 'already_shown', 'title': '영양 forecast'}, again['card'])
            self.assertNotIn('card_hint', again)
            self.assertEqual(1, len(self._cards()))
            self.assertIn('Temperature', self._cards()[0].body)
        finally:
            self._set_auto(before)

    def test_setting_off_posts_nothing(self):
        self._screen('kserver' + 'b' * 14)
        before = self._set_auto(False)
        try:
            got = self._lookup()
            self.assertEqual({'state': 'skipped', 'reason': 'card_auto_off'}, got['card'])
            self.assertEqual(0, len(self._cards()))
        finally:
            self._set_auto(before)


    def _set_language(self, lang):
        from aot.aot_flask.extensions import db
        self.user.language = lang
        db.session.commit()

    def test_the_card_is_in_the_users_language(self):
        """2026-10-29 관리 세션: 서버 카드가 영어면 AI 가 사용자 언어로 올리던 카드보다 퇴보다."""
        self._screen('kserver' + 'c' * 14)
        before = self._set_auto(True)
        self._set_language('ko')
        try:
            got = self._lookup()
            self.assertEqual({'state': 'posted', 'title': '영양 예보'}, got['card'])
            card = self._cards()[0]
            self.assertEqual('영양 예보', card.title)
            lines = card.body.splitlines()
            self.assertEqual('10-29 00:00 → 10-30 00:00, 모델 예보', lines[0])
            self.assertRegex(lines[1], r'^온도 4\.[23]–17 °C \(최고 10-29 14:00\)$')
            self.assertEqual('강수량 합계 3.4 mm, 10-29 17:00부터', lines[2])
            self.assertTrue(lines[3].startswith('습도 40–90 %'), lines[3])
        finally:
            self._set_language('')
            self._set_auto(before)

    def test_place_and_now_cards_in_korean(self):
        place = {"place": {"name": "3포장"},
                 "sensors": {"temperature": {"avg": 21.3, "unit": "°C", "n": 2},
                             "soil": {"moisture": {"avg": 31, "unit": "%", "n": 1}}},
                 "alert": {"count": 2}, "stale_sensors": {"count": 1}}
        self._set_language('ko')
        try:
            title, msg = server_card.in_user_locale(self.app, self.uid, lambda: server_card.compose('place', place))
            self.assertEqual('3포장 현황', title)
            self.assertEqual(['공기: 온도 21.3 °C', '흙: 수분 31 %', '알림 2건', '소식 없는 센서 1개'], msg.splitlines())
            title, _m = server_card.in_user_locale(self.app, self.uid, lambda: server_card.compose(
                'now', {"summary": [{"measurement": "temperature", "unit": "°C", "latest": 1}]}))
            self.assertEqual('지금 날씨', title)
            title, msg = server_card.in_user_locale(self.app, self.uid, lambda: server_card.compose('now', {
                "read_as": {"target": {"name": "2포장"}, "period": {"asked": "yesterday"}},
                "summary": [{"measurement": "rain", "unit": "mm", "last": 0, "sum": 0.6}]}))
            self.assertEqual(('2포장 날씨 · 어제', '비 합계 0.6 mm'), (title, msg))
        finally:
            self._set_language('')


if __name__ == '__main__':
    unittest.main()
