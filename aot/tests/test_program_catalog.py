# coding=utf-8
"""관리 프로그램(`GeoProgram`) **템플릿 카탈로그** — `aot/scripts/seed_programs.py`.

정본: docs/design/program-layer.md

이 카탈로그는 DB 에 미리 깔지 않는다(source='builtin' 시드가 없다) — 화면에서
"템플릿에서 시작" 을 고를 때 비로소 사용자 프로그램으로 복사된다. 카탈로그는
**카테고리(넓은 범주)** 와 **작물종** 두 층으로 이루어진다 — 카테고리 쪽이 먼저다.
관리 프로그램은 `kind`(`vegetation`·`livestock`·`facility`·`other`)로 대상 종류를
나누는데, 이 카탈로그는 `STAGE_DURATION_MAP`(작물 표) 하나만 읽으므로 **전부
`kind='vegetation'`** 이다.
"""
import importlib
import os
import statistics
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir,
                                              os.path.pardir)))

import aot.scripts.seed_programs as scp
from aot.ai.context.growth_stage_resolver import STAGE_DURATION_MAP

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class TestCatalogReadsTheHardcodedTable(unittest.TestCase):
    """단계·기간을 여기 다시 적지 않는다 — 두 곳에 적으면 반드시 갈린다."""

    def test_reads_stage_duration_map_and_presets(self):
        src = _read(os.path.join(_ROOT, 'scripts', 'seed_programs.py'))
        self.assertIn('from aot.ai.context.growth_stage_resolver import '
                      'STAGE_DURATION_MAP', src)
        self.assertIn('_CROP_PRESETS', src)
        # 토마토 육묘기 21일을 여기 리터럴로 다시 적으면 원본과 갈릴 수 있다.
        self.assertNotIn("'seedling', 21", src)

    def test_nothing_is_installed_by_default(self):
        src = _read(os.path.join(_ROOT, 'scripts', 'seed_programs.py'))
        self.assertNotIn("source='builtin'", src.split('def purge_builtin')[0])
        self.assertIn('def purge_builtin(', src)

    def test_cumulative_days_become_stage_lengths(self):
        stages = scp._stages_from_cumulative([
            ('seedling', 21), ('vegetative', 56), ('harvest', 999)])
        self.assertEqual([s['days'] for s in stages], [21, 35, None])
        self.assertIsNone(stages[-1]['days'])


class TestSpeciesEntries(unittest.TestCase):
    """작물종 항목 — 카테고리가 생겨도 그대로 남는다."""

    def setUp(self):
        importlib.reload(scp)
        self.items = scp.catalog()
        self.species = {it['key']: it for it in self.items if it['scope'] == 'species'}

    def test_all_stage_duration_map_crops_present(self):
        expected = {k for k in STAGE_DURATION_MAP if not k.startswith('_')}
        self.assertEqual(set(self.species), expected)

    def test_targets_only_where_a_source_says_so(self):
        """목표는 지어내지 않는다 — 빈 칸이 근거 없는 숫자보다 낫다.

        2026-08-20 부터 **출처가 있는 작물에는** 조사된 목표가 들어간다
        (`crop_target_sources.SPECIES_TARGETS`). 그 밖의 작물은 여전히 비어 있어야
        한다 — 사람은 채워진 값을 "조사된 추천값" 으로 읽는다.
        """
        from aot.scripts.crop_target_sources import SPECIES_TARGETS

        for key, item in self.species.items():
            if key in SPECIES_TARGETS:
                continue
            for st in item['stages']:
                self.assertNotIn('targets', st,
                                 '%s.%s 에 근거 없는 목표가 있습니다' % (key, st['key']))
            for d in (item.get('target_defs') or []):
                self.assertIsNone(d.get('default'), key)

    def test_tagged_with_parent_category(self):
        self.assertEqual(self.species['tomato']['category'], 'fruiting_vegetable')
        self.assertEqual(self.species['lettuce']['category'], 'leafy_vegetable')

    def test_cucumber_has_no_fruit_set_stage(self):
        keys = [s['key'] for s in self.species['cucumber']['stages']]
        self.assertNotIn('fruit_set', keys)

    def test_kind_is_vegetation(self):
        """이 카탈로그는 STAGE_DURATION_MAP(작물 표) 하나만 읽으므로 전부
        kind='vegetation' — 가축·시설물 종류를 여기서 지어내지 않는다."""
        for item in self.species.values():
            self.assertEqual(item['kind'], 'vegetation')


class TestCategoryEntries(unittest.TestCase):
    """카테고리 — 소속이 있어야 만든다. 스켈레톤은 소속 작물의 중앙값이다."""

    def setUp(self):
        importlib.reload(scp)
        self.items = scp.catalog()
        self.categories = {it['key']: it for it in self.items if it['scope'] == 'category'}

    def test_fruiting_and_leafy_categories_exist(self):
        self.assertIn('cat_fruiting_vegetable', self.categories)
        self.assertIn('cat_leafy_vegetable', self.categories)

    def test_categories_come_before_species_in_list_order(self):
        scopes = [it['scope'] for it in self.items]
        first_species = scopes.index('species')
        self.assertNotIn('species', scopes[:first_species])

    def test_no_category_without_members(self):
        """소속이 STAGE_DURATION_MAP 에 하나도 없으면 만들지 않는다."""
        for cat_key, cat in scp._CATEGORY_MAP.items():
            members = [m for m in cat['members'] if m in STAGE_DURATION_MAP]
            has_entry = ('cat_%s' % cat_key) in self.categories
            self.assertEqual(bool(members), has_entry)

    def test_reserved_categories_stay_out_until_species_data_exists(self):
        """근채류·허브류·화훼류는 이름만 예약돼 있다 — STAGE_DURATION_MAP 에
        대표 작물이 하나도 없어 카탈로그에 나타나면 안 된다(점검 2026-08-19)."""
        for cat_key in ('root_vegetable', 'herb', 'ornamental'):
            self.assertIn(cat_key, scp._CATEGORY_MAP)
            self.assertEqual(scp._CATEGORY_MAP[cat_key]['members'], [])
            self.assertNotIn('cat_%s' % cat_key, self.categories)

    def test_exactly_two_categories_are_buildable_today(self):
        """지금 실측 자료로 만들 수 있는 카테고리는 정확히 2개다 — 늘어나면
        STAGE_DURATION_MAP 에 대표 작물이 추가됐다는 뜻이어야 한다."""
        self.assertEqual(len(self.categories), 2)

    def test_members_are_real_stage_duration_map_keys(self):
        for cat in self.categories.values():
            for m in cat['members']:
                self.assertIn(m, STAGE_DURATION_MAP)

    def test_subject_defaults_to_category_name_not_blank(self):
        for cat in self.categories.values():
            self.assertTrue(cat['subject'])
            self.assertEqual(cat['subject'], cat['name'])

    def test_no_invented_targets(self):
        for cat in self.categories.values():
            for st in cat['stages']:
                self.assertNotIn('targets', st)

    def test_kind_is_vegetation(self):
        for cat in self.categories.values():
            self.assertEqual(cat['kind'], 'vegetation')

    def test_notes_disclose_the_median_derivation(self):
        """대표값이지 정답이 아니라는 사실이 데이터에 남아야 한다."""
        for cat in self.categories.values():
            self.assertIn('중앙값', cat['notes'])

    def test_last_stage_is_open_ended(self):
        for cat in self.categories.values():
            self.assertIsNone(cat['stages'][-1]['days'])

    def test_stage_order_follows_canonical_growth_order(self):
        for cat in self.categories.values():
            indices = [scp._STAGE_ORDER.get(s['key'], 999) for s in cat['stages']]
            self.assertEqual(indices, sorted(indices))

    def test_fruiting_vegetable_union_includes_strawberry_only_stage(self):
        """딸기만 가진 화아분화기도 과채류 카테고리 스켈레톤에 나타나야 한다."""
        keys = [s['key'] for s in self.categories['cat_fruiting_vegetable']['stages']]
        self.assertIn('flower_initiation', keys)

    def test_stage_days_is_the_real_median_of_members(self):
        """카테고리 일수가 실제로 소속 작물들의 중앙값인지 — 지어낸 숫자가 아닌지."""
        cat = self.categories['cat_fruiting_vegetable']
        members = cat['members']
        per_member = {
            m: {st['key']: st['days']
                for st in scp._stages_from_cumulative(STAGE_DURATION_MAP[m])
                if st['days'] is not None}
            for m in members
        }
        for st in cat['stages']:
            if st['key'] == 'harvest':
                continue
            lengths = [per_member[m][st['key']] for m in members if st['key'] in per_member[m]]
            self.assertEqual(st['days'], int(round(statistics.median(lengths))),
                             '단계 %s' % st['key'])


if __name__ == '__main__':
    unittest.main()
