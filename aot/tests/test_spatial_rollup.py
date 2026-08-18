# coding=utf-8
"""공간 계층 롤업 — "그 안에서 일어나는 일" 을 한 번에 답한다.

"3포장의 예정을 요약해" 는 3포장 **안에서** 일어나는 일을 묻는 것이지 3포장
도형에 붙은 것만 묻는 것이 아니다. 그런데 조회는 `target_id ==` 정확 일치였다.

2026-08-18 실측(김제):
    search_schedule('3포장') → 0건   (실제로는 구역 1건 + 그 안 식생 2건)
    search_schedule('장풍')  → 0건   (그 식생 자신의 예정 2건이 있는데도)
    search_notes('3-1')     → 그 안 식생 노트 0건

**에러가 아니라 0건** 이라는 점이 최악이다. AI 는 그것을 "예정 없음" 으로 읽고
"충돌 없습니다" 라고 답한다 — 없는 것과 못 찾는 것이 같은 응답이라 틀린 답이
확신에 찬 문장으로 나온다.

조사 보고서: .local/reports/spatial-hierarchy-rollup-gap-20260818.md
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
    for sep in ('\ndef ', '\n    def ', '\n  function ', '\nfunction '):
        body = body.split(sep, 1)[0]
    return body


class TestDescendantHelper(unittest.TestCase):
    """자손 확장의 정본은 geo_hierarchy 하나다."""

    def setUp(self):
        self.src = _read('utils', 'geo_hierarchy.py')

    def test_helper_exists(self):
        self.assertIn('def descendant_target_ids', self.src)
        self.assertIn('def _planting_ids_inside', self.src)

    def test_it_covers_every_identity(self):
        """한 대상 아래에는 정체성이 여러 벌이라 도형 uuid 만으로는 부족하다.
        하나라도 빠뜨리면 그 종류에 붙은 것만 조용히 사라진다."""
        body = _fn(self.src, 'descendant_target_ids')
        for key in ('shapes', 'facilities', 'devices', 'plantings'):
            self.assertIn("'%s'" % key, body)
        # 시설: 노트·일정은 GeoFacility uuid 에 붙는데 기하는 도형 쪽이다
        self.assertIn('GeoFacility', body)
        # 장치 마커: 노트는 마커가 아니라 그 Input/Output uuid 에 붙는다
        self.assertIn('device_id', body)

    def test_it_returns_a_breakdown(self):
        """결과가 0건일 때 "정말 없다" 와 "못 찾았다" 를 구분할 근거가
        훑은 개수뿐이다."""
        body = _fn(self.src, 'descendant_target_ids')
        self.assertIn('return uniq, breakdown', body)

    def test_plantings_are_found_geometrically(self):
        """GeoPlanting 은 GeoShape 가 아니라 자손 순회에 안 들어가고, 소속
        컬럼도 없다(설계상 소속은 저장하지 않고 파생한다)."""
        body = _fn(self.src, '_planting_ids_inside')
        self.assertIn('containment_point', body)
        self.assertIn('ended_on.is_(None)', body)   # 끝난 작기는 제외


class TestToolsExpandAndReport(unittest.TestCase):

    def setUp(self):
        self.src = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')

    def test_shared_scope_helper(self):
        """두 도구가 같은 규칙을 쓴다 — 따로 두면 노트와 일정이 서로 다른
        범위를 답하고, 사용자는 그 차이를 데이터 차이로 읽는다."""
        self.assertIn('def _scope_for_target', self.src)
        self.assertIn('_scope_for_target(', _fn(self.src, 'search_schedule_tool'))
        self.assertIn('_scope_for_target(', _fn(self.src, 'search_notes_tool'))

    def test_schedule_search_uses_in_not_equals(self):
        body = _fn(self.src, 'search_schedule_tool')
        self.assertIn('SchedulerJobMeta.target_id.in_(ids)', body)
        self.assertNotIn('SchedulerJobMeta.target_id == target_id', body)

    def test_unresolved_name_does_not_return_everything(self):
        """필터를 안 걸면 **전체 일정**이 그 대상의 것인 양 돌아간다."""
        body = _fn(self.src, 'search_schedule_tool')
        self.assertIn("target_id == '\\x00none'", body)

    def test_unresolved_name_warns(self):
        """0건을 "예정 없음" 으로 읽으면 "충돌 없습니다" 라는 틀린 답이
        확신에 찬 문장으로 나간다."""
        body = _fn(self.src, 'search_schedule_tool')
        self.assertIn('warning', body)
        self.assertIn("NOT evidence", body)
        notes = _fn(self.src, 'search_notes_tool')
        self.assertIn('NOT evidence', notes)

    def test_scope_is_reported_even_on_hits(self):
        """무엇을 훑고 나온 답인지 항상 말한다."""
        for fn in ('search_schedule_tool', 'search_notes_tool'):
            self.assertIn('"scope"', _fn(self.src, fn))

    def test_note_target_name_covers_planting_and_facility(self):
        """site 를 물으면 그 아래 전부가 돌아오므로, 어느 구획 것인지 구분이
        곧 답의 정확도다. 식생·시설은 GeoShape 가 아니라 이름이 비어 있었다."""
        body = _fn(self.src, '_note_target_name')
        self.assertIn('GeoPlanting', body)
        self.assertIn('GeoFacility', body)


class TestCropNameResolvesToThePlot(unittest.TestCase):
    """작물 이름은 그 **구획**으로 풀린다 — 예전에는 구역으로 접혔다."""

    def setUp(self):
        self.src = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')

    def test_resolver_returns_planting(self):
        body = _fn(self.src, '_resolve_target_by_crop')
        self.assertIn("'planting'", body)
        self.assertIn('plot_id', body)

    def test_plots_outside_a_zone_are_kept(self):
        """구획이 쓰기 대상이 아니던 시절에는 버렸다. 지금은 노트의 선택
        구간이 구획에 붙은 예정이 되므로, 버리면 방금 만든 것에 도달하지
        못한다."""
        body = _fn(self.src, '_active_crop_plots')
        self.assertIn("'plot_id': row.unique_id", body)
        self.assertNotIn('if zone is None:\n                    continue', body)

    def test_ambiguity_still_returns_none(self):
        """5-tuple 에 '모호함' 을 담을 자리가 없고, 이 리졸버는 쓰기 도구도
        쓴다 — 하나를 골라 버리면 엉뚱한 구획에 조용히 쓰인다."""
        body = _fn(self.src, '_resolve_target_by_crop')
        self.assertIn('len(plot_ids) == 1', body)

    def test_containers_list_their_plots(self):
        """구역도 컨테이너다 — 작업을 구획별로 나눠 걸어야 할 때 AI 가 그
        존재를 알아야 한다."""
        body = _fn(self.src, 'resolve_target_tool')
        self.assertIn("target_type in ('site', 'zone')", body)
        self.assertIn('"type": "planting"', body)


if __name__ == '__main__':
    unittest.main()
