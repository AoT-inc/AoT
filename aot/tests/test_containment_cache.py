# coding=utf-8
"""공간 포함 관계 **파생 캐시** (Phase B).

계층 질의가 매번 기하를 다시 계산하고 있었다. 실측(2026-08-18 로컬,
도형 150 · 활성 구획 22):

    build_geo_parent_map(전체)     42.5 ms  →  0.9 ms
    search_schedule('3포장')      197.3 ms  → 107.8 ms
    search_notes('3-1')          150.1 ms  →  90.8 ms

**`GeoShape.parent_id` 를 백필하지 않았다.** 그 컬럼은 파생값이 아니라 정본
이다 — 시간대 상속(`resolve_timezone` 2단계)·좌표 상속·`facility_bay` 삭제
트리거가 그 체인을 읽는다. 지금 전부 NULL 이라 그 경로들이 잠들어 있는데,
기하 파생값을 거기 채우면 tz 해석이 **조용히** 바뀐다. 사람이 정한 값과
기계가 추측한 값이 같은 칸에 섞이면 나중에 둘을 가를 수도 없다.

계획서: .local/plans/geo-hierarchy-persistence-phaseB-20260818.md
"""
import os
import unittest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _fn(src, name):
    for head in ('def %s' % name, 'function %s' % name):
        if head in src:
            body = src.split(head, 1)[1]
            break
    else:
        raise AssertionError('함수를 찾지 못했습니다: %s' % name)
    for sep in ('\ndef ', '\n    def ', '\nfunction '):
        body = body.split(sep, 1)[0]
    return body


class TestCacheIsNotTheSourceOfTruth(unittest.TestCase):

    def test_parent_id_is_untouched(self):
        """정본 컬럼에 기계 추측을 섞지 않는다."""
        for parts in (('utils', 'geo_hierarchy.py'),
                      ('aot_flask', 'geo', 'containment_cache.py')):
            src = _read(*parts)
            self.assertNotIn('.parent_id =', src)
            self.assertNotIn('parent_id=', src.replace('s.parent_id', ''))

    def test_no_backfill_script_for_parent_id(self):
        self.assertFalse(os.path.exists(
            os.path.join(_ROOT, 'scripts', 'backfill_geo_parent.py')))

    def test_cache_writes_live_in_the_geo_package(self):
        """지도 데이터는 geo 패키지가 소유한다(check_geo_writes). 캐시도
        지도 데이터라, 밖에서 각자 채우면 무효화 시점을 여러 벌 기억하게 된다."""
        self.assertTrue(os.path.exists(os.path.join(
            _ROOT, 'aot_flask', 'geo', 'containment_cache.py')))
        gh = _read('utils', 'geo_hierarchy.py')
        # geo_hierarchy 는 소유자를 **경유**한다 — 직접 모델을 쓰지 않는다
        self.assertNotIn('GeoContainmentCache(', gh)
        self.assertIn('containment_cache', gh)


class TestCacheSemantics(unittest.TestCase):

    def setUp(self):
        self.cc = _read('aot_flask', 'geo', 'containment_cache.py')
        self.gh = _read('utils', 'geo_hierarchy.py')

    def test_null_parent_is_a_computed_answer(self):
        """"계산했고 부모가 없다" 와 "미계산" 이 구분되지 않으면 루트 도형은
        영원히 캐시 미스라 매번 기하를 돈다."""
        self.assertIn('미계산', self.cc)
        body = _fn(self.gh, '_parent_map_from_cache')
        self.assertIn('if key not in cached:', body)
        self.assertIn('if puid is None:', body)

    def test_partial_hits_are_refused(self):
        """빠진 것을 채우려면 어차피 기하를 파싱해야 하고, 그러면 아낀 것이 없다."""
        body = _fn(self.gh, '_parent_map_from_cache')
        self.assertIn('return None', body)

    def test_cached_parent_is_absolute_not_query_scoped(self):
        """후보를 이번 질의 범위로 잡으면, '3-2' 만 물어 본 순간 3-1 의
        구획들이 "부모 없음" 으로 캐시되고 그 뒤 '3포장' 질의가 캐시 히트로
        그것들을 통째로 빠뜨린다 — 에러 없이 결과만 줄어든다."""
        body = _fn(self.gh, '_plot_ids_inside')
        self.assertIn("GeoShape.type.in_(('site', 'zone'))", body)
        self.assertIn('parent in want', body)

    def test_cache_failure_never_breaks_the_query(self):
        """캐시를 못 적는 것 때문에 조회가 실패하면, 캐시가 성능 개선이 아니라
        새로운 고장 지점이 된다."""
        store = _fn(self.cc, 'store')
        self.assertIn('except Exception:', store)
        self.assertIn('return 0', store)
        load = _fn(self.cc, 'load')
        self.assertIn('return {}', load)

    def test_ttl_exists_as_a_safety_net(self):
        """무효화를 빠뜨린 경로가 있어도 스스로 낫는다 — 이 레포는 "정리해야
        할 경로가 17곳인데 실제로 정리하는 곳은 4곳" 을 이미 겪었다."""
        self.assertIn('_TTL_S', self.cc)
        self.assertIn('_naive_utc(r.computed_at) >= floor', _fn(self.cc, 'load'))


class TestInvalidationIsWired(unittest.TestCase):
    """기하를 바꾸는 경로는 캐시를 버려야 한다. 안 버리면 화면과 AI 가 낡은
    소속을 보고, 증상은 에러가 아니라 "왜 저 구획이 저 구역에 잡히지" 다."""

    def test_plot_writes_invalidate(self):
        body = _fn(_read('aot_flask', 'geo', 'plot_io.py'),
                   '_invalidate_caches')
        self.assertIn('containment_cache.invalidate()', body)

    def test_shape_writes_invalidate(self):
        for parts in (('aot_flask', 'geo', 'geo_overlays.py'),
                      ('aot_flask', 'geo', 'geo_design.py'),
                      ('aot_flask', 'geo', 'device_placement.py')):
            src = _read(*parts)
            self.assertIn('containment_cache', src,
                          '%s 가 포함 캐시를 안 버린다' % parts[-1])

    def test_name_index_is_scoped_per_database(self):
        """프로세스 전역이면 각자 임시 DB 를 만드는 테스트끼리 서로의 도형을
        본다 — 단독 실행은 통과하고 스위트로 돌리면 깨지는, 원인을 찾기 어려운
        실패다(2026-08-18 실제로 그렇게 잡았다)."""
        src = _read('aot_flask', 'geo', 'shape_index.py')
        self.assertIn('def _scope_key', src)
        self.assertIn('db.engine.url', src)

    def test_invalidate_only_deletes(self):
        """지우는 방향으로만 동작하므로 과하게 불러도 손해는 재계산 비용뿐이다."""
        body = _fn(_read('aot_flask', 'geo', 'containment_cache.py'),
                   'invalidate')
        self.assertIn('.delete(', body)
        self.assertNotIn('db.session.add(', body)


class TestTimezoneNaiveComparison(unittest.TestCase):
    """TTL 비교가 캐시를 통째로 죽인 적이 있다.

    SQLite 는 `computed_at` 을 naive 로 저장하는데 `utc_now()` 는 aware 라
    그대로 빼면 TypeError 가 난다. 그 예외를 `load()` 의 `except` 가 삼켜
    **캐시가 항상 빈 dict 를 돌려주고 있었다** — 결과는 맞고 성능만 나빠지는,
    아무도 눈치채지 못하는 실패다. 실측에서 캐시를 켠 쪽이 오히려 느려
    (25.6ms → 114.5ms) 그때 발견했다.
    """

    def setUp(self):
        self.src = _read('aot_flask', 'geo', 'containment_cache.py')

    def test_helper_exists_and_is_used_on_both_sides(self):
        self.assertIn('def _naive_utc', self.src)
        load = _fn(self.src, 'load')
        self.assertIn('_naive_utc(utc_now())', load)
        self.assertIn('_naive_utc(r.computed_at)', load)
        self.assertIn('_naive_utc(utc_now())', _fn(self.src, 'store'))

    def test_swallowed_exception_is_logged_loudly(self):
        """조용히 지나가면 캐시가 죽은 줄 모른다."""
        load = _fn(self.src, 'load')
        self.assertIn('logger.exception', load)
        self.assertIn('성능', load)

    def test_ttl_is_long_because_invalidation_is_the_normal_path(self):
        """짧게 잡으면 만료마다 전량 재계산 + 재저장이라 캐시 없을 때보다
        느려진다(실측 25.6ms → 114.5ms)."""
        self.assertIn('_TTL_S = 86400', self.src)

    def test_cache_can_be_switched_off_for_measurement(self):
        """캐시 켬/끔을 같은 조건에서 재지 못하면, 워밍업이 캐시를 채워
        cold 측정이 사실상 warm 이 된다 — 실제로 그렇게 재다가 "캐시가 더
        느리다" 는 반대 결론이 나왔다."""
        gh = _read('utils', 'geo_hierarchy.py')
        for fn in ('build_geo_parent_map', 'geo_descendant_shapes',
                   'descendant_target_ids', '_plot_ids_inside'):
            self.assertIn('use_cache', _fn(gh, fn), '%s 에 스위치 없음' % fn)


class TestIntegrityCheckSeesDrift(unittest.TestCase):

    def setUp(self):
        self.src = _read('scripts', 'check_geo_integrity.py')

    def test_check_exists_and_is_wired(self):
        self.assertIn('def _check_containment_cache', self.src)
        self.assertIn('_check_containment_cache(findings', self.src)
        self.assertIn("'containment-cache-drift'", self.src)

    def test_geometry_wins(self):
        """정본은 기하다 — 캐시가 틀린 것이지 그 반대가 아니다."""
        body = _fn(self.src, '_check_containment_cache')
        self.assertIn('use_cache=False', body)
        self.assertIn("'geometry_says'", body)

    def test_read_only(self):
        """검사기가 데이터를 건드리기 시작하면 운영 서버에 돌릴 수 없게 된다."""
        body = _fn(self.src, '_check_containment_cache')
        for w in ('db.session.commit', 'delete(', '.add('):
            self.assertNotIn(w, body)

    def test_missing_rows_are_not_drift(self):
        body = _fn(self.src, '_check_containment_cache')
        self.assertIn('continue', body)
        self.assertIn('not in cached', body)


if __name__ == '__main__':
    unittest.main()
