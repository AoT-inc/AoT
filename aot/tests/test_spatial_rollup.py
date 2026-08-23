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
import re
import unittest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()



def _strip_js_comments(src):
    """JS 소스에서 `//` 줄주석과 `/* */` 블록주석을 걷어낸다.

    소스에 낱말이 있는가가 아니라 **코드가 그것을 쓰는가**를 보기 위한 것이다.
    문자열 리터럴 안의 `//`(URL 등)까지 가르지는 않지만, 여기서 찾는 것은
    `descendants` 같은 식별자라 그 정도로 충분하다.
    """
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'(^|[^:])//[^\n]*', r'\1', src)

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
        self.assertIn('def _plot_ids_inside', self.src)

    def test_it_covers_every_identity(self):
        """한 대상 아래에는 정체성이 여러 벌이라 도형 uuid 만으로는 부족하다.
        하나라도 빠뜨리면 그 종류에 붙은 것만 조용히 사라진다."""
        body = _fn(self.src, 'descendant_target_ids')
        for key in ('shapes', 'facilities', 'devices', 'plots'):
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

    def test_plots_are_found_geometrically(self):
        """GeoPlot 은 GeoShape 가 아니라 자손 순회에 안 들어가고, 소속
        컬럼도 없다(설계상 소속은 저장하지 않고 파생한다)."""
        body = _fn(self.src, '_plot_ids_inside')
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

    def test_note_target_name_covers_plot_and_facility(self):
        """site 를 물으면 그 아래 전부가 돌아오므로, 어느 구획 것인지 구분이
        곧 답의 정확도다. 식생·시설은 GeoShape 가 아니라 이름이 비어 있었다."""
        body = _fn(self.src, '_note_target_name')
        self.assertIn('GeoPlot', body)
        self.assertIn('GeoFacility', body)


class TestNameResolutionReadsShapesOnce(unittest.TestCase):
    """이름 하나 해석에 `GeoShape.query.all()` 이 세 번 돌고 있었다.

    실측(2026-08-18, 도형 150): 그 조회 하나가 23.5ms 이고 feature 파싱은
    사실상 공짜다 — **비용은 파싱이 아니라 JSON 컬럼이 실린 행을 읽는 것**.
    공용 인덱스로 모은 뒤 `search_schedule('3포장')` 110.5 → 47.6ms,
    `search_notes('3-1')` 95.7 → 31.9ms.
    """

    def test_index_module_exists(self):
        self.assertTrue(os.path.exists(os.path.join(
            _ROOT, 'aot_flask', 'geo', 'shape_index.py')))

    def test_resolvers_use_the_shared_index(self):
        src = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')
        for fn in ('_resolve_note_target', '_resolve_note_target_ids'):
            body = _fn(src, fn)
            self.assertIn('shape_index.named_shapes()', body,
                          '%s 가 공용 인덱스를 안 쓴다' % fn)
            # 주석에는 그 문자열이 나온다(왜 안 쓰는지 적어 두었다) —
            # 코드 줄만 본다.
            code = [l for l in body.splitlines()
                    if not l.strip().startswith('#')]
            self.assertNotIn('GeoShape.query.all()', '\n'.join(code),
                             '%s 가 아직 전체 조회를 한다' % fn)

    def test_no_orm_rows_in_the_cache(self):
        """세션이 닫히면 detached 가 되고, 그때 로드되지 않은 속성을 건드리면
        캐시 히트일 때만 터진다 — 재현이 고약한 종류다."""
        src = _read('aot_flask', 'geo', 'shape_index.py')
        self.assertIn('namedtuple', src)
        # 레코드를 만드는 곳은 all_shapes() 다(named_shapes 는 그걸 거른다).
        self.assertIn('ShapeRec(', _fn(src, 'all_shapes'))

    def test_invalidation_is_wired_to_the_same_place(self):
        """무효화 배선을 두 벌로 늘리면 한쪽만 부르는 경로가 반드시 생긴다."""
        cc = _read('aot_flask', 'geo', 'containment_cache.py')
        self.assertIn('shape_index.invalidate()', _fn(cc, 'invalidate'))

    def test_scope_does_not_resolve_twice(self):
        """`_resolve_note_target_ids` 가 이미 `_resolve_note_target` 을 부른다."""
        src = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')
        body = _fn(src, '_scope_for_target')
        self.assertLess(body.index('_resolve_note_target_ids('),
                        body.index('_resolve_note_target('))


class TestDescendantsAreReadLightweight(unittest.TestCase):
    """자손을 ORM 으로 읽던 마지막 조회를 지웠다.

    `_resolve_note_target_ids('3포장')` 22.6ms 중 거의 전부가
    `GeoShape.query.all()`(16.8ms/150행) 하나였다. 자손에서 실제로 읽는 것은
    uuid · device_id · type · geo_id · name 뿐이라, 부모 관계가 캐시돼 있으면
    그 조회가 통째로 불필요하다.

        _geo_shape_descendants   23.4 → 0.8 ms
        search_schedule('3포장')  47.6 → 3.6 ms
        search_notes('3-1')      31.9 → 9.1 ms
    """

    def test_lightweight_variant_exists(self):
        gh = _read('utils', 'geo_hierarchy.py')
        self.assertIn('def geo_descendant_recs', gh)

    def test_orm_variant_is_kept_for_geometry(self):
        """`geo_descendant_shapes` 는 계약을 바꾸지 않는다 — 자손의 폴리곤이
        필요한 호출자가 있고, 경량 레코드에는 기하가 없다."""
        gh = _read('utils', 'geo_hierarchy.py')
        self.assertIn('def geo_descendant_shapes', gh)
        # 레코드 **필드 목록**으로 본다 — 주석·docstring 에는 왜 안 담는지가
        # 적혀 있어서 본문 문자열 검사로는 늘 걸린다.
        idx = _read('aot_flask', 'geo', 'shape_index.py')
        fields = idx.split("'id unique_id", 1)[1].split("'", 1)[0]
        for banned in ('feature', 'geometry', 'geom'):
            self.assertNotIn(banned, fields)

    def test_cache_miss_falls_back_to_orm(self):
        """첫 호출·무효화 직후에는 기하로 파생해야 한다. 그때도 결과는 같고
        비용만 옛날과 같다 — 폴백이 없으면 캐시가 빈 순간 답이 비어버린다."""
        body = _fn(_read('utils', 'geo_hierarchy.py'), 'geo_descendant_recs')
        self.assertIn('geo_descendant_shapes(root_shape', body)
        self.assertIn('ShapeRec(', body)

    def test_hot_paths_use_the_lightweight_variant(self):
        gh = _read('utils', 'geo_hierarchy.py')
        self.assertIn('geo_descendant_recs(root_shape',
                      _fn(gh, 'descendant_target_ids'))
        svc = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')
        self.assertIn('geo_descendant_recs(root_shape)',
                      _fn(svc, '_geo_shape_descendants'))

    def test_names_survive_the_lightweight_path(self):
        """자손에서 `feature` 를 읽던 곳은 전부 **이름**만 뽑았다. 레코드가
        이름을 들지 않으면 컨테이너의 children 이 통째로 비어 버린다."""
        idx = _read('aot_flask', 'geo', 'shape_index.py')
        self.assertIn("'id unique_id type parent_id device_id geo_id name'", idx)
        svc = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')
        body = _fn(svc, 'resolve_target_tool')
        self.assertIn('c.name', body)
        self.assertNotIn('c.feature', body)


class TestScreenAndAiAgree(unittest.TestCase):
    """화면과 AI 가 **같은 범위**를 답해야 한다.

    2026-08-18 실측(김제) — 둘이 달랐다:

        구역 '3-1'  화면 일정 0건 / AI 2건   (사용자가 방금 만든 예정이 안 보임)
        필지 '3포장' 화면 일정 1건 / AI 7건
        필지 '3포장' 화면 노트 0건 / AI 16건

    화면은 site 만 직속 자식 도형까지 봤고 zone 은 자기 것만 봤으며, 식생은
    `GeoShape` 가 아니라 어느 층위에서도 빠졌다. 노트는 어느 계층에서도
    자기 것만이었다.
    """

    def test_schedule_uses_the_shared_descendant_helper(self):
        """두 벌로 두면 한쪽만 고쳐지고, 그 어긋남은 "AI 는 아는데 화면은
        모른다" 로 나타난다."""
        body = _fn(_read('aot_flask', 'routes_geo.py'), '_schedule_payload')
        self.assertIn('descendant_target_ids(', body)
        self.assertNotIn('_direct_children(', body)

    def test_notes_can_include_descendants(self):
        src = _read('aot_flask', 'routes_notes_api.py')
        body = _fn(src, 'api_notes_target_get')
        self.assertIn("request.args.get('descendants')", body)
        self.assertIn('descendant_target_ids(', body)
        self.assertIn('Notes.target_id.in_(target_ids)', body)

    def test_facility_notes_resolve_through_its_shape(self):
        """시설은 정체성이 둘이다 — 노트는 GeoFacility uuid 에 붙는데 기하는
        도형 쪽이라, 도형으로 옮겨야 자손이 나온다."""
        body = _fn(_read('aot_flask', 'routes_notes_api.py'),
                   'api_notes_target_get')
        self.assertIn('GeoFacility', body)
        self.assertIn('shape_uuid', body)

    def test_each_note_says_where_it_came_from(self):
        """합쳐 놓고 출처가 없으면 오히려 혼란이 된다."""
        src = _read('aot_flask', 'routes_notes_api.py')
        self.assertIn('def _display_name_for_target', src)
        body = _fn(src, '_display_name_for_target')
        for model in ('GeoShape', 'GeoPlot', 'GeoFacility'):
            self.assertIn(model, body)
        js = _read('aot_flask', 'static', 'js', 'common', 'sensor-label.js')
        self.assertIn('n.target_name', js)

    def test_containers_ask_for_descendants(self):
        """대지·구역·시설은 컨테이너다. 구획은 최하위라 자기 것만.

        ⚠ **주석은 빼고 본다.** 예전에는 파일 전체에서 낱말을 찾아, "여기서는
        자손을 켜지 않는다" 고 **적어 두는 것 자체**가 이 검사를 깨뜨렸다.
        규칙을 설명하는 글이 규칙 위반이 되면 다음 사람은 설명을 지운다.
        """
        js = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                   'aot-map-widget-vector.js')
        self.assertGreaterEqual(js.count('descendants: true'), 3)
        veg = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                    'aot-map-plot.js')
        self.assertNotIn('descendants', _strip_js_comments(veg))

    def test_area_for_descendants_always_includes_the_root(self):
        """`include_self` 는 결과 목록에 root 를 넣을지만 정한다. 판정 영역까지
        같이 묶었더니 `include_self=False` 로 부른 화면에서 **root 안에 직접
        있는 구획이 통째로 빠졌다**(구역 모달 예정 0건)."""
        body = _fn(_read('utils', 'geo_hierarchy.py'), 'descendant_target_ids')
        self.assertIn('if root_shape.unique_id:', body)
        self.assertIn('if include_self:', body)

    def test_truncated_list_says_so(self):
        """5건만 보여주고 더 있다는 말이 없으면 사용자는 그것이 전부라고 읽는다
        — "없는 것" 과 "안 보여준 것" 이 같은 화면이 되면 안 된다."""
        body = _fn(_read('aot_flask', 'geo', 'site_summary.py'),
                   'upcoming_schedule')
        self.assertIn("'total': len(rows)", body)
        popup = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                      'aot-map-popup.js')
        rec = _fn(popup, 'buildRecordBlock')
        self.assertIn("_t('%(n)s more')", rec)
        self.assertIn('total > items.length', rec)


class TestSubjectNameResolvesToThePlot(unittest.TestCase):
    """작물 이름은 그 **구획**으로 풀린다 — 예전에는 구역으로 접혔다."""

    def setUp(self):
        self.src = _read('..', 'aot', 'ai', 'services', 'aot_data_tool_service.py')

    def test_resolver_returns_plot(self):
        body = _fn(self.src, '_resolve_target_by_subject')
        self.assertIn("'plot'", body)
        self.assertIn('plot_id', body)

    def test_plots_outside_a_zone_are_kept(self):
        """구획이 쓰기 대상이 아니던 시절에는 버렸다. 지금은 노트의 선택
        구간이 구획에 붙은 예정이 되므로, 버리면 방금 만든 것에 도달하지
        못한다."""
        body = _fn(self.src, '_active_subject_plots')
        self.assertIn("'plot_id': row.unique_id", body)
        self.assertNotIn('if zone is None:\n                    continue', body)

    def test_ambiguity_still_returns_none(self):
        """5-tuple 에 '모호함' 을 담을 자리가 없고, 이 리졸버는 쓰기 도구도
        쓴다 — 하나를 골라 버리면 엉뚱한 구획에 조용히 쓰인다."""
        body = _fn(self.src, '_resolve_target_by_subject')
        self.assertIn('len(plot_ids) == 1', body)

    def test_containers_list_their_plots(self):
        """구역도 컨테이너다 — 작업을 구획별로 나눠 걸어야 할 때 AI 가 그
        존재를 알아야 한다."""
        body = _fn(self.src, 'resolve_target_tool')
        self.assertIn("target_type in ('site', 'zone')", body)
        self.assertIn('"type": "plot"', body)


if __name__ == '__main__':
    unittest.main()
