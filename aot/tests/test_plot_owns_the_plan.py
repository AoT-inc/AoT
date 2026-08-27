# coding=utf-8
"""**프로그램은 참고 계획, 구획이 실제 계획** (2026-08-27).

사용자 정리: *"프로그램이 구획에서 선택되면 구획에서는 프로그램을 내재화해
버리고, 내재화한 프로그램을 수정 편집하게 됨. 코디네이터는 구획에서 단계와
목표값을 받아야 사용자의 의도와 시간에 맞게 작동하게 됨."*

## 흐름

    GeoProgram (참고)          GeoPlot (실제)              코디네이터
      stages[].targets   ──→   stage_overrides.targets ──┐
      target_defs (어휘)        stage_plan (경계 날짜)     ├→ effective_stages
      targets_methods           program_version           │  → _stage_targets
      photosynthesis                                      │  → stage_of
                                                          └→ control_targets

## 고친 것

**목표를 구획이 못 고쳤다.** 근거는 *"제어로 흐르는 값이라 구획마다 손대기
시작하면 무엇을 목표로 길렀나 의 답이 흩어진다"* 였는데, 답이 반대였다 —
구획이 못 고치면 사람은 **프로그램을 고치고**, 그러면 그 프로그램을 쓰는
**다른 구획까지** 함께 바뀐다.
"""
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


class _Plot:
    """`stage_override_map` 만 있으면 되는 최소 대역."""

    def __init__(self, overrides):
        self.stage_overrides = overrides

    def stage_override_map(self):
        from aot.databases.models.geo_plot import GeoPlot
        return GeoPlot.stage_override_map(self)


class _Program:
    def __init__(self, stages):
        self._stages = stages

    def stage_list(self):
        return [dict(s) for s in self._stages]


_STAGES = [
    {'key': 'seed', 'name': '육묘', 'days': 20,
     'targets': {'vpd': 0.6, 'co2': 700}},
    {'key': 'grow', 'name': '생육', 'days': 40,
     'targets': {'vpd': 0.9, 'co2': 800}},
]


class TestThePlotCanRetuneTargets(unittest.TestCase):

    def _eff(self, overrides):
        from aot.aot_flask.geo.plot_context import effective_stages
        return effective_stages(_Plot(overrides), _Program(_STAGES))

    def test_an_override_wins(self):
        out = self._eff({'targets': {'grow': {'vpd': 1.2}}})
        grow = [s for s in out if s['key'] == 'grow'][0]
        self.assertEqual(grow['targets']['vpd'], 1.2)

    def test_untouched_items_still_come_from_the_program(self):
        """⚠ 단계의 dict 를 통째로 갈아치우면 손대지 않은 항목이 사라진다."""
        out = self._eff({'targets': {'grow': {'vpd': 1.2}}})
        grow = [s for s in out if s['key'] == 'grow'][0]
        self.assertEqual(grow['targets']['co2'], 800, 'CO₂ 가 사라졌다')

    def test_untouched_stages_are_left_alone(self):
        out = self._eff({'targets': {'grow': {'vpd': 1.2}}})
        seed = [s for s in out if s['key'] == 'seed'][0]
        self.assertEqual(seed['targets'], {'vpd': 0.6, 'co2': 700})

    def test_the_program_row_is_not_mutated(self):
        """구획 화면에서 템플릿을 건드리면 같은 프로그램을 쓰는 다른 구획이
        조용히 함께 바뀐다."""
        prog = _Program(_STAGES)
        from aot.aot_flask.geo.plot_context import effective_stages
        effective_stages(_Plot({'targets': {'grow': {'vpd': 1.2}}}), prog)
        self.assertEqual(_STAGES[1]['targets']['vpd'], 0.9,
                         '프로그램 원본이 바뀌었다')

    def test_no_override_returns_the_program_as_is(self):
        out = self._eff({})
        self.assertEqual([s['targets'] for s in out],
                         [s['targets'] for s in _STAGES])


class TestTheOverrideMapIsForgiving(unittest.TestCase):
    """깨진 값은 조용히 버린다 — 그 구획은 프로그램 그대로 동작할 뿐이다."""

    def _map(self, raw):
        return _Plot(raw).stage_override_map()

    def test_broken_shapes_do_not_raise(self):
        for raw in (None, [], 'x', {'targets': 'x'}, {'targets': {'a': 'x'}},
                    {'targets': {'a': None}}):
            self.assertEqual(self._map(raw)['targets'], {}, repr(raw))

    def test_none_values_are_dropped(self):
        """`None` 은 "안 정했다" 다 — 담아 두면 프로그램 값을 `None` 으로
        덮어 목표가 통째로 사라진다."""
        got = self._map({'targets': {'grow': {'vpd': None, 'co2': 900}}})
        self.assertEqual(got['targets'], {'grow': {'co2': 900}})


class TestItIsWrittenAndReadBackByTheSameKeys(unittest.TestCase):
    """⚠ 읽는 쪽이 아는 키를 쓰는 쪽이 빠뜨리면, 화면에서 고친 것이 저장은
    되는 듯 보이고 다시 열면 사라진다 — 에러가 없어서 어디를 봐야 할지
    알 수 없다."""

    def test_the_writer_persists_every_key_the_reader_knows(self):
        model = _read('databases', 'models', 'geo_plot.py')
        reader = model.split('def stage_override_map', 1)[1].split('\n    def ', 1)[0]
        writer = _read('aot_flask', 'geo', 'plot_io.py')
        writer = writer.split('def _save_overrides', 1)[1].split('\ndef ', 1)[0]
        import re
        keys = set(re.findall(r"raw\.get\('(\w+)'\)", reader))
        self.assertTrue(keys, '읽는 키를 못 찾았다')
        for k in keys:
            self.assertIn("'%s'" % k, writer,
                          '_save_overrides 가 %s 를 저장하지 않는다' % k)


class TestTheSetterGuardsTheVocabulary(unittest.TestCase):
    """목표 **항목**은 프로그램이 정한다. 구획이 새 항목을 만들 수 있으면
    시설·화면·제어가 각자 다른 어휘를 갖는다."""

    def test_it_rejects_an_unknown_target_key(self):
        src = _read('aot_flask', 'geo', 'plot_io.py')
        body = src.split('def set_stage_target', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('target_def_list', body)
        self.assertIn('이 프로그램에 없는 목표 항목입니다', body)

    def test_it_does_not_touch_the_program(self):
        src = _read('aot_flask', 'geo', 'plot_io.py')
        body = src.split('def set_stage_target', 1)[1].split('\ndef ', 1)[0]
        for bad in ('prog.stages', 'prog.target_defs =', 'prog.version'):
            self.assertNotIn(bad, body, '프로그램을 고친다: %s' % bad)

    def test_clearing_falls_back_to_the_program(self):
        src = _read('aot_flask', 'geo', 'plot_io.py')
        body = src.split('def set_stage_target', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("value in (None, '')", body)
        self.assertIn('pop(target_key, None)', body)


class TestTheVersionPinIsNotAContentPin(unittest.TestCase):
    """⚠ **`program_version` 은 내용을 고정하지 않는다.**

    컬럼 주석은 *"버전을 함께 고정한다 … 진행 중인 작기의 해석이 바뀌면 '그때
    무엇을 목표로 길렀나' 의 답이 조용히 달라진다"* 라고 적혀 있지만,
    `program_summary` 는 `row.stage_list()` — **라이브 프로그램**을 읽는다.
    버전 스냅샷 테이블이 없으므로 고정할 대상 자체가 없다.

    즉 프로그램을 고치면 **진행 중인 구획의 해석이 지금도 바뀐다.** 이 검사는
    그 사실을 고정한다 — 스냅샷을 만드는 날 이 검사가 깨지고, 그때가 주석과
    구현이 처음으로 맞는 날이다.
    """

    def test_there_is_no_version_snapshot_table(self):
        import os
        models = os.listdir(os.path.join(_ROOT, 'databases', 'models'))
        self.assertNotIn('geo_program_version.py', models,
                         '스냅샷이 생겼다 — 위 주석과 이 검사를 함께 고칠 것')

    def test_the_summary_reads_the_live_program(self):
        src = _read('aot_flask', 'geo', 'plot_context.py')
        body = src.split('pinned = getattr(plot', 1)[1][:400]
        self.assertIn('row.stage_list()', body)
        self.assertIn('newer_version', body,
                      '적어도 "새 버전이 있다" 는 말은 해야 한다')


if __name__ == '__main__':
    unittest.main()


class TestTheEditorReachesTheSameContract(unittest.TestCase):
    """화면이 고친 것이 제어까지 가야 한다 — 저장 경로가 한 벌이어야 한다."""

    def _js(self):
        return _read('aot_flask', 'static', 'js', 'common', 'aot-plot-stages.js')

    def test_the_view_carries_targets(self):
        """편집기는 `stage_schedule` 만 받는다. 거기 목표가 없으면 화면이 고칠
        대상 자체가 없다."""
        src = _read('aot_flask', 'geo', 'plot_context.py')
        body = src.split('def stage_schedule_view', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("'targets': _view_targets(", body)

    def test_the_view_reuses_the_one_target_builder(self):
        """⚠ 항목 어휘·단위·곡선 처리가 `_stage_targets` 에 못 박혀 있다.
        화면용으로 다시 조립하면 항목을 늘릴 때 한쪽만 늘어난다."""
        src = _read('aot_flask', 'geo', 'plot_context.py')
        body = src.split('def _view_targets', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_stage_targets(', body)

    def test_a_curve_backed_target_is_not_editable(self):
        """숫자를 받아도 곡선이 이긴다 — 고칠 수 있는 것처럼 보이면 사람이
        값을 넣고 왜 안 먹는지 묻는다."""
        src = _read('aot_flask', 'geo', 'plot_context.py')
        body = src.split('def _view_targets', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("t.get('source') != 'method'", body)

    def test_a_fixed_definition_is_still_editable(self):
        """⚠ `fixed` 는 "이 **정의**가 시스템 소유"(라벨·단위·범위)라는 뜻이지
        값을 못 고친다는 뜻이 아니다. 온도·습도·CO₂·DLI·VPD 가 전부 `fixed`
        정의라, 그것으로 막으면 **고칠 수 있는 항목이 하나도 남지 않는다** —
        2026-08-27 실측으로 그렇게 됐다.
        """
        from aot.aot_flask.geo.plot_context import _view_targets
        import aot.aot_flask.geo.plot_context as pc
        real = pc._stage_targets
        pc._stage_targets = lambda st, pr: [
            {'key': 'co2', 'label': 'CO2', 'unit': 'ppm', 'value': 700,
             'source': 'stage', 'fixed': True},
            {'key': 'vpd', 'label': 'VPD', 'unit': 'kPa', 'value': None,
             'source': 'method', 'fixed': True, 'method_name': '곡선'},
        ]
        try:
            got = {t['key']: t['editable']
                   for t in _view_targets({'key': 'x'}, None)}
        finally:
            pc._stage_targets = real
        self.assertTrue(got['co2'], 'fixed 정의라고 값까지 막혔다')
        self.assertFalse(got['vpd'], '곡선 항목이 고칠 수 있다고 나온다')

    def test_the_editor_copies_targets_deeply(self):
        """원본을 그대로 고치면 무엇이 바뀌었는지 가릴 기준이 사라진다."""
        js = self._js()
        body = js.split('function _copy(', 1)[1].split('\n  function ', 1)[0]
        self.assertIn('targets:', body)
        self.assertIn('.map(function (t)', body)

    def test_only_changed_targets_are_sent(self):
        js = self._js()
        body = js.split("'/stage-target'", 1)[0][-700:]
        self.assertIn('wasBy[t.key]', body, '바뀐 것만 보내지 않는다')

    def test_clearing_sends_null(self):
        """비운 것은 "프로그램 값으로 돌아가라" 는 뜻이다 — 빈 문자열을 보내면
        서버가 0 으로 읽을 수 있다."""
        js = self._js()
        self.assertIn("value: t.value === '' ? null : t.value", js)

    def test_dirty_counts_targets(self):
        """⚠ 빠뜨리면 목표만 고친 사람이 [프로그램으로 등록] 을 눌렀을 때
        저장되지 않은 채 등록된다(무에러)."""
        js = self._js()
        body = js.split('function dirty(', 1)[1]
        self.assertIn('targets', body)

    def test_the_route_exists_and_guards_edit(self):
        src = _read('aot_flask', 'routes_geo_plot.py')
        self.assertIn("/stage-target'", src)
        body = src.split('def api_plot_stage_target', 1)[1].split('\n@blueprint', 1)[0]
        self.assertIn('_require_edit()', body, '권한 검사가 없다')
        self.assertIn('set_stage_target', body)
        self.assertIn('invalidate_plot_contents', body, '요약 캐시를 안 비운다')
