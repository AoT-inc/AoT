# coding=utf-8
"""`site_summary.cached_build` — TTL 캐시 · 단일 비행 · **상한**.

이 캐시가 틀리는 방식은 전부 조용하다. 키가 좁으면 다른 창의 그림이 그대로
나오고(에러 없음), 상한이 없으면 프로세스가 며칠에 걸쳐 부푼다(증상은 느려짐
하나뿐). 그래서 여기 있는 것은 "값이 맞나" 가 아니라 **"어떤 조건에서 조용히
틀리나"** 다.

DB·Flask·InfluxDB 를 쓰지 않는다 — `cached_build` 는 순수 함수 하나다.
"""
import os
import threading
import time
import unittest

from aot.aot_flask.geo import site_summary as ss

_ROOT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding='utf-8') as f:
        return f.read()


class CachedBuildTest(unittest.TestCase):
    def setUp(self):
        self.cache = {}
        self.locks = {}
        self.calls = []

    def _build(self, value):
        def fn():
            self.calls.append(value)
            return value
        return fn

    def test_second_call_is_served_from_cache(self):
        for _ in range(3):
            got = ss.cached_build(self.cache, self.locks, 'k', 60,
                                  self._build('v'))
            self.assertEqual(got, 'v')
        self.assertEqual(self.calls, ['v'])

    def test_different_keys_do_not_share(self):
        """키가 다르면 답도 달라야 한다 — 창을 키에 담는 이유가 이것이다."""
        a = ss.cached_build(self.cache, self.locks, 'p|d7', 60, self._build('7일'))
        b = ss.cached_build(self.cache, self.locks, 'p|d31', 60, self._build('31일'))
        self.assertEqual((a, b), ('7일', '31일'))

    def test_none_is_not_cached(self):
        """'못 찾음' 을 기억하면 방금 만든 것이 그동안 없는 것이 된다."""
        for _ in range(2):
            self.assertIsNone(
                ss.cached_build(self.cache, self.locks, 'k', 60, lambda: None))
        self.assertEqual(len(self.cache), 0)

    def test_expired_entry_is_rebuilt(self):
        ss.cached_build(self.cache, self.locks, 'k', 60, self._build('old'))
        self.cache['k'] = (time.time() - 1, 'old')      # 만료시킨다
        got = ss.cached_build(self.cache, self.locks, 'k', 60, self._build('new'))
        self.assertEqual(got, 'new')

    def test_single_flight_collapses_concurrent_builds(self):
        """같은 키를 동시에 열면 계산은 **한 번**이어야 한다.

        이것이 풀리면 저사양 호스트에서 gunicorn 스레드풀이 같은 계산으로
        가득 찬다(모듈 독스트링의 실측).
        """
        started = threading.Event()
        release = threading.Event()
        ran = []

        def slow():
            ran.append(1)
            started.set()
            release.wait(2)
            return 'v'

        t = threading.Thread(target=lambda: ss.cached_build(
            self.cache, self.locks, 'k', 60, slow))
        t.start()
        self.assertTrue(started.wait(2))
        waiter = threading.Thread(target=lambda: ss.cached_build(
            self.cache, self.locks, 'k', 60, slow))
        waiter.start()
        release.set()
        t.join(2)
        waiter.join(2)
        self.assertEqual(len(ran), 1)

    # ── 상한 ────────────────────────────────────────────────────────────
    #
    # 상한이 없던 시절의 실패는 "느려진다" 하나로만 드러난다. 그래서 값이
    # 아니라 **사전이 자라지 않는가**를 본다.

    def test_cache_stays_under_the_cap(self):
        for i in range(50):
            ss.cached_build(self.cache, self.locks, 'k%d' % i, 60,
                            self._build(i), max_entries=10)
        self.assertLessEqual(len(self.cache), 10)

    def test_locks_do_not_outlive_their_entries(self):
        """잠금 사전도 함께 줄어야 한다 — 캐시만 비고 locks 가 자라면 같은 누수다."""
        for i in range(50):
            ss.cached_build(self.cache, self.locks, 'k%d' % i, 60,
                            self._build(i), max_entries=10)
        self.assertLessEqual(len(self.locks), 10)

    def test_expired_entries_are_dropped_even_under_the_cap(self):
        """상한에 안 걸려도 만료된 것은 버린다 — 안 그러면 영영 남는다.

        끝난 단계의 창은 날짜가 고정이라 **다시 조회되지 않는다.** 상한만
        믿으면 그런 항목이 상한을 채울 때까지 계속 쌓인다.
        """
        for i in range(5):
            ss.cached_build(self.cache, self.locks, 'old%d' % i, 60,
                            self._build(i))
        for k in list(self.cache):
            self.cache[k] = (time.time() - 1, self.cache[k][1])
        ss.cached_build(self.cache, self.locks, 'fresh', 60, self._build('f'))
        self.assertEqual(list(self.cache), ['fresh'])

    def test_a_held_lock_is_never_evicted(self):
        """쥐고 있는 잠금을 지우면 단일 비행이 조용히 풀린다."""
        self.locks['busy'] = threading.Lock()
        self.locks['busy'].acquire()
        try:
            for i in range(30):
                ss.cached_build(self.cache, self.locks, 'k%d' % i, 60,
                                self._build(i), max_entries=2)
            self.assertIn('busy', self.locks)
        finally:
            self.locks['busy'].release()

    def test_the_freshest_entry_survives_eviction(self):
        """방금 채운 것이 밀려나면 캐시가 있으나 마나다."""
        for i in range(30):
            ss.cached_build(self.cache, self.locks, 'k%d' % i, 60,
                            self._build(i), max_entries=3)
        self.assertIn('k29', self.cache)


class EnvWeekKeyTest(unittest.TestCase):
    """주간 계열의 캐시 키 — **창을 가르는 것이 전부 들어 있어야 한다.**"""

    def test_window_axes_change_the_key(self):
        base = ss.env_week_key('p', 7)
        self.assertNotEqual(base, ss.env_week_key('p', 31))
        self.assertNotEqual(base, ss.env_week_key('p', 7, end='2026-09-01'))
        self.assertNotEqual(base, ss.env_week_key('p', 7, unit='week'))
        self.assertNotEqual(base, ss.env_week_key('other', 7))

    def test_same_window_is_the_same_key(self):
        self.assertEqual(ss.env_week_key('p', 7), ss.env_week_key('p', 7))

    def test_hidden_rows_change_the_key(self):
        """감춘 목록도 **답을 가른다** — 계열이 그만큼 줄어든다.

        키에 안 담으면 상위에서 항목을 감춰도 감추기 전 계열이 10분간 그대로
        나온다(에러 없이).
        """
        self.assertNotEqual(ss.env_week_key('p', 7),
                            ss.env_week_key('p', 7, hidden=['T']))

    def test_hidden_order_does_not_change_the_key(self):
        """같은 집합이 다른 키가 되면 캐시가 그만큼 헛돈다."""
        self.assertEqual(ss.env_week_key('p', 7, hidden=['T', 'RH']),
                         ss.env_week_key('p', 7, hidden=['RH', 'T']))

    def test_plot_and_facility_share_one_rule(self):
        """두 라우트가 각자 조립하면 한쪽만 고쳐도 아무 신호가 없다.

        시설 키는 대상 부분이 `시설uuid|동id` 일 뿐 창을 붙이는 규칙은 같다.
        """
        src_plot = _read('aot_flask/routes_geo_plot.py')
        src_fac = _read('aot_flask/routes_geo_iec.py')
        for src in (src_plot, src_fac):
            self.assertIn('env_week_key(', src)
        # 창을 손으로 이어붙이던 옛 모양이 되살아나면 잡는다.
        self.assertNotIn("'%s|%s|d%s' % (facility_uuid", src_fac)


class HiddenKeyVocabularyTest(unittest.TestCase):
    """감춘 줄을 조회에서 빼는 일 — **어휘가 갈리면 조용히 줄이 사라진다.**

    카드의 줄(`readings`)은 `channel_meta_for_dm(dm)['key']` 로 만들어지고
    (`site_summary.env_for_devices`), 조회를 거르는 쪽도 **같은 함수**를 써야
    한다. 여기서 measurement 이름(`temperature`)으로 번역하는 코드가 생기면
    매핑에 없는 채널(토양수분 등 — 사람이 붙인 이름이 곧 키다)에서 어긋나고,
    그 어긋남은 "그 줄만 안 나온다" 로만 드러난다.
    """

    def test_series_filter_uses_the_same_key_function_as_the_card(self):
        src = _read('aot_flask/geo/plot_journal.py')
        body = src.split('def env_channel_series', 1)[1].split(
            '\ndef ', 1)[0]
        self.assertIn('channel_meta_for_dm', body,
                      '카드가 줄을 만들 때 쓰는 그 함수로 키를 구해야 한다.')
        card = _read('aot_flask/geo/site_summary.py')
        self.assertIn('channel_meta_for_dm(dm)', card)

    def test_hidden_keys_reach_the_query_from_both_routes(self):
        """구획·시설 두 라우트가 **같은 규칙**을 쓴다 — 한쪽만 고치면 갈린다."""
        for rel in ('aot_flask/routes_geo_plot.py',
                    'aot_flask/routes_geo_iec.py'):
            src = _read(rel)
            self.assertIn('hidden_keys=', src, rel)
            self.assertIn('hidden=_hidden', src, rel)

    def test_unreadable_channel_is_kept_not_dropped(self):
        """판정에 실패하면 **안 감춘 것으로 본다.**

        반대로 두면(못 읽으면 뺀다) 매핑이 깨진 채널이 카드에는 있는데
        그래프에서만 사라진다 — 원인에 닿을 실마리가 없다.
        """
        src = _read('aot_flask/geo/plot_journal.py')
        body = src.split('def env_channel_series', 1)[1].split('\ndef ', 1)[0]
        guard = body.split('if hidden:', 1)[1].split('_t0 =', 1)[0]
        # except 절에 continue 가 있으면 "못 읽으면 뺀다" 가 된다.
        self.assertIn('except Exception', guard)
        self.assertNotIn('continue', guard.split('except Exception', 1)[1])


class EnvSeriesRouteTest(unittest.TestCase):
    """`/env_series` 배선 — **창을 가르는 축이 키와 조회 둘 다에 닿아야 한다.**

    한쪽만 닿으면 조용히 틀린다: 조회에만 닿으면 캐시가 옛 창을 주고, 키에만
    닿으면 캐시는 갈리는데 계산이 같은 창을 본다. 둘 다 소스로 고정한다.
    """

    def setUp(self):
        self.src = _read('aot_flask/routes_geo_plot.py')
        self.body = self.src.split('def api_plot_env_week', 1)[1].split(
            '\ndef ', 1)[0]

    def test_window_axes_reach_the_query(self):
        for arg in ('days=days', 'end_date=end', 'unit=unit',
                    'hidden_keys=_hidden'):
            self.assertIn(arg, self.body, arg)

    def test_window_axes_reach_the_cache_key(self):
        # 괄호를 세어 호출 전체를 떼어낸다 — 첫 `)` 로 자르면
        # `end.isoformat()` 의 괄호에서 잘린다.
        rest = self.body.split('env_week_key(', 1)[1]
        depth, out = 1, []
        for ch in rest:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    break
            out.append(ch)
        key = ''.join(out)
        for arg in ('days', 'end=', 'unit=', 'hidden='):
            self.assertIn(arg, key, '%s 가 캐시 키에 안 들어간다: %s' % (arg, key))

    def test_future_stage_returns_without_querying(self):
        """아직 오지 않은 단계에 빈 그래프를 그리면 '고장' 으로 읽힌다.

        조회도 하지 않아야 한다 — 없는 기간을 묻는 것은 그 자체로 낭비다.
        """
        head = self.body.split("state == 'future'", 1)[1].split(
            'def _build', 1)[0]
        self.assertIn('return jsonify', head)
        self.assertIn("'state': 'future'", head)
        self.assertNotIn('recent_env_trends', head)

    def test_old_name_still_answers(self):
        """`/env_week` 는 옛 이름이다 — 두 벌 만들면 계산이 갈린다."""
        self.assertIn("/env_series'", self.src)
        self.assertIn("/env_week'", self.src)
        # 같은 핸들러에 붙어 있어야 한다(데코레이터 두 줄이 연달아).
        self.assertIn("env_series', methods=['GET'])\n@blueprint.route(",
                      self.src.replace('<string:plot_uuid>', 'P'))

    def test_stage_window_uses_the_schedule_as_the_source(self):
        """축의 구간과 그래프의 창이 갈리면 안 된다 — 날짜 산술을 다시 하지 않는다."""
        win = self.src.split('def _stage_window', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('stage_schedule_view', win)
        # 진행 중인 단계는 끝이 미래다 — 오늘로 잘라야 빈 꼬리가 안 붙는다.
        self.assertIn('min(ends, today)', win)


class FoldOrderTest(unittest.TestCase):
    """접기는 **목표를 붙인 뒤**여야 한다.

    `attach_targets` 는 그날의 단계 목표를 붙인다(`stage_at(stages, key)`).
    접고 나면 그 버킷이 며칠을 대표하는지만 남아 "어느 날의 목표인가" 를 물을
    수 없다 — 순서를 바꾸면 단계 경계를 걸친 주가 한쪽 목표만 갖게 된다.
    """

    def test_fold_comes_after_attach_targets(self):
        src = _read('aot_flask/geo/plot_journal.py')
        body = src.split('def recent_env_trends', 1)[1].split('\ndef ', 1)[0]
        self.assertLess(body.index('attach_targets('), body.index('fold_buckets('))

    def test_fold_reuses_the_journal_function(self):
        """단위 전환을 다시 짜면 같은 구획을 일지와 위젯이 다르게 접는다."""
        src = _read('aot_flask/geo/plot_journal.py')
        body = src.split('def recent_env_trends', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('fold_buckets(', body)


if __name__ == '__main__':
    unittest.main()
