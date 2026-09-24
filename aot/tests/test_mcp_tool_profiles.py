# coding=utf-8
"""API 키별 도구 묶음(operations / configuration) — 1단계 기구.

고정하는 계약:

  1. 분류는 tool_registry 의 표 하나(_MCP_PROFILE)다. MCP 표면의 도구마다
     정확히 한 번 배정돼 있고, 운영 ⊆ 설정이다.
  2. 외부 키의 tools/list 는 그 키의 묶음만 싣는다(역할·읽기 전용 숨김과 함께).
     인앱 AI(묶음 None)는 제한이 없다.
  3. 묶음 밖 호출은 외부 전송(stdio·HTTP·REST)에서만 거절한다 — 승인 큐에
     들어가지 않고, 감사에 call_state=refused·reason_code=tool_profile 로 남으며,
     메시지가 묶음 이름과 바꾸는 곳을 말한다. 인앱 AI 는 막지 않는다.
  4. 서버 안내문과 get_system_brief 가 묶음을 알린다(표준 호스트는 목록에 없는
     도구를 모델에게 주지 않으므로 거절 메시지에 기대지 않는다).
  5. 운영 도구의 설명·응답 문자열은 운영 밖 도구 이름을 부르지 않는다(R6).
  6. 기존 키는 기동 때 한 번, 최근 90일 사용 기록으로 배정된다.
  7. AOT_MCP_TOOL_PROFILES=0 이면 예전과 같다(되돌리기).
  8. 마이그레이션 p6_75 는 멱등이고 앱이 기대하는 머리다.
  9. (2026-09-24 후속) 실행 가능한 도구는 전부 표에 명시된다. 서비스 계정
     키(인앱 물리 제어의 stdio 경로)는 제한이 없다. get_tool_detail·
     open_drawer 도 묶음 밖이면 같은 거절로 답한다. 묶음 밖 승인 요청은
     이름을 가리고 거절만 받는다. knowledge_shelve 안내는 쓸 수 있는
     연결의 knowledge_search 응답에만 있다. 묶음 변경은 폐기와 같은 문턱.

라이브 DB 를 쓰지 않는다(conftest 의 임시 DB, 마이그레이션은 임시 sqlite).
"""
import ast
import base64
import collections
import inspect
import io
import json
import os
import re
import textwrap
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

import pytest

from aot.tests.test_api_key_generate_route import _UsersSubmitAppFixture
from aot.tools import tool_registry as R

_PREFIX = 'ProfTest'

OPS = R.TOOL_PROFILE_OPERATIONS
CFG = R.TOOL_PROFILE_CONFIGURATION
_SWITCH_PLACE = 'Settings > Users > API keys'


def _catalog_names():
    """MCP 표면 전량(서랍 끔) — 카탈로그 + 네이티브 + 특수 디스패치."""
    from aot.tools import tool_execution as te
    return ({t['tool_name'] for t in R.virtual_tools()}
            | set(te._NATIVE_TOOLS)
            | {t['name'] for t in te._EXTRA_TOOLS})


def _executable_names():
    """실행층이 실제로 부를 수 있는 이름 — 처리기가 있는 선언 도구 + 네이티브 +
    특수 디스패치. 카탈로그(tools/list)에 없어도 use_tool 로 닿는다."""
    from aot.tools import tool_execution as te
    return (set(R.build_tool_map()) | set(te._NATIVE_TOOLS)
            | {t['name'] for t in te._EXTRA_TOOLS})


def _catalog_definitions():
    """이름 → MCP 도구 정의(앱 없이). 네이티브 스키마는 장치 목록을 싣지
    않는다(R1, 2026-09-24) — 그래서 앱 없이 잰 크기가 현장의 크기와 같다
    (TestSchemaRules.test_native_schemas_do_not_grow_with_devices)."""
    from aot.tools import tool_execution as te
    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
    out = {t['tool_name']: {'name': t['tool_name'],
                            'description': t['description'],
                            'inputSchema': t['input_schema']}
           for t in R.virtual_tools()}
    out['get_sensor_reading'] = N._schema_get_sensor_reading([])
    out['list_available_devices'] = N._schema_list_available_devices([])
    out['set_output_state'] = N._schema_set_output_state([])
    for t in te._EXTRA_TOOLS:
        out[t['name']] = dict(t)
    return out


def _name_pattern(names):
    return re.compile(r'\b(' + '|'.join(
        sorted((re.escape(n) for n in names), key=len, reverse=True)) + r')\b')


# ---------------------------------------------------------------------------
# 1. 분류표 (앱 불필요)
# ---------------------------------------------------------------------------

class TestClassificationTable(unittest.TestCase):

    def test_every_mcp_tool_has_exactly_one_profile(self):
        table = R.mcp_profile_table()
        catalog = _catalog_names()
        self.assertEqual(sorted(catalog - set(table)), [],
                         'MCP 표면에 있는데 묶음 배정이 없는 도구')
        known = catalog | _executable_names()
        self.assertEqual(sorted(n for n in set(table) - known
                                if not R.is_declared_tool(n)), [],
                         '묶음 표에 있는데 선언도 실행도 안 되는 이름')
        allowed = {OPS, CFG, 'retired', 'drawer'}
        for name, value in table.items():
            self.assertIn(value, allowed, name)
        # 운영 집합과 설정 전용 집합은 서로소이고, retired·서랍 기구와 합치면
        # 표 전부다 — 한 도구가 두 곳에서 "처음 등장" 하지 않는다.
        ops, cfg = R.profile_tools(OPS), R.profile_tools(CFG)
        cfg_only = cfg - ops
        self.assertTrue(ops <= cfg, '운영은 설정에 포함돼야 한다')
        self.assertEqual(ops & cfg_only, frozenset())
        rest = {n for n, v in table.items() if v in ('retired', 'drawer')}
        self.assertEqual(set(ops) | set(cfg_only) | rest, set(table))

    def test_every_callable_tool_is_classified(self):
        """실행할 수 있는 도구는 전부 표에 명시돼 있다(D2, 2026-09-24).

        "표에 없으면 설정" 규칙은 안전장치로 남지만, 거기에 기대는 도구가
        있으면 안 된다 — 배정은 사람이 본 판단이어야 한다."""
        missing = sorted(_executable_names() - set(R.mcp_profile_table()))
        self.assertEqual(missing, [], '실행되는데 묶음 표에 없는 도구')

    def test_decided_assignments(self):
        """설계 확인(2026-09-23 검증 반영)으로 정한 자리."""
        ops = R.profile_tools(OPS)
        cfg_only = R.profile_tools(CFG) - ops
        for name in ('submit_advice', 'list_advice', 'search_archives',
                     'modify_function_options', 'modify_sequence_schedule',
                     'confirm_plot_stage', 'reschedule_plot_stage',
                     'undo_plot_stage', 'apply_plot_resources', 'end_plot',
                     'respond_to_confirmation', 'get_local_time',
                     'operate_device', 'get_sensor_reading',
                     'read_manual', 'list_unbound_slots',
                     # 프로필 벤치마크(26-09-24) lat_19 — 운영 안내문이
                     # 약속하는 "시퀀스 운전 시간" 조정.
                     'modify_sequence_step'):
            self.assertIn(name, ops, name)
        for name in ('configure_sequence_day', 'create_sequence_function',
                     'distance_between', 'nearest',
                     'list_programs', 'get_program', 'get_address',
                     'list_device_types', 'list_ai_agents', 'create_function',
                     'create_input', 'create_plot', 'modify_plot',
                     'rebind_device'):
            self.assertIn(name, cfg_only, name)
        for name in ('set_output_state', 'list_available_devices'):
            self.assertTrue(R.is_retired_from_mcp(name), name)
            self.assertNotIn(name, R.profile_tools(CFG))
        for name in ('open_drawer', 'get_tool_detail', 'use_tool'):
            self.assertTrue(R.is_drawer_machinery(name), name)

    def test_profile_values_match_the_model(self):
        from aot.databases.models import user_api_key as model
        self.assertEqual(tuple(model.TOOL_PROFILES), tuple(R.TOOL_PROFILES))

    def test_unknown_values_narrow_to_operations(self):
        self.assertEqual(R.normalize_tool_profile(None), OPS)
        self.assertEqual(R.normalize_tool_profile(''), OPS)
        self.assertEqual(R.normalize_tool_profile('Configuration'), OPS)
        self.assertEqual(R.normalize_tool_profile(CFG), CFG)

    def test_membership_rules(self):
        self.assertTrue(R.tool_in_profile('create_function', None))
        self.assertTrue(R.tool_in_profile('set_output_state', None))
        self.assertFalse(R.tool_in_profile('create_function', OPS))
        self.assertTrue(R.tool_in_profile('create_function', CFG))
        self.assertFalse(R.tool_in_profile('set_output_state', CFG))
        self.assertTrue(R.tool_in_profile('open_drawer', OPS))
        # 표에 없는 이름은 설정으로 친다 — 운영 표면이 조용히 커지지 않게.
        self.assertFalse(R.tool_in_profile('get_function_doc', OPS))
        self.assertTrue(R.tool_in_profile('get_function_doc', CFG))
        # 서비스 계정 표지는 저장값이 아니다 — 좁히면 운영이다.
        self.assertEqual(R.normalize_tool_profile(R.TOOL_PROFILE_UNRESTRICTED),
                         OPS)


# ---------------------------------------------------------------------------
# 2. R6 — 운영 도구는 운영 밖 도구를 가리키지 않는다
# ---------------------------------------------------------------------------

def _handler_strings(fn, service, seen, depth, out):
    """처리기와 그것이 부르는 aot.* 함수(깊이 제한)의 문자열 상수.

    docstring 은 뺀다(응답이 아니다). `self.`/`cls.` 호출은 처리기 클래스의
    메서드로, 이름 호출은 그 함수의 전역에서 찾는다."""
    fn = inspect.unwrap(fn)
    code = getattr(fn, '__code__', None)
    if code is None or code in seen:
        return
    seen.add(code)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(getattr(node.body[0], 'value', None), ast.Constant):
            docs.add(id(node.body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docs:
            out.append((fn.__qualname__, node.value))
    if depth <= 0:
        return
    env = getattr(fn, '__globals__', {})
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f, target = node.func, None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id in ('self', 'cls', service.__name__):
                target = getattr(service, f.attr, None)
            else:
                owner = env.get(f.value.id)
                if isinstance(owner, (types.ModuleType, type)):
                    target = getattr(owner, f.attr, None)
        elif isinstance(f, ast.Name):
            target = env.get(f.id)
        if target is not None and callable(target) and \
                (getattr(target, '__module__', '') or '').startswith('aot.'):
            _handler_strings(target, service, seen, depth - 1, out)


class TestNoPointersOutsideTheProfile(unittest.TestCase):
    """목록에 없는 도구를 가리키는 문구는 모델이 주입으로 오인했다."""

    @classmethod
    def setUpClass(cls):
        import aot.ai  # noqa: F401 — providers 바인딩
        table = R.mcp_profile_table()
        cls.ops = R.profile_tools(OPS)
        cls.listed_cfg = R.profile_tools(CFG)
        cls.retired = {n for n, v in table.items() if v == 'retired'}
        # 서랍 기구는 서랍 스위치가 켜져 있으면 목록에 있다.
        cls.outside_ops = set(table) - cls.ops - {
            n for n, v in table.items() if v == 'drawer'}
        cls.defs = _catalog_definitions()

    def test_operations_descriptions(self):
        pat = _name_pattern(self.outside_ops)
        hits = []
        for name in sorted(self.ops & set(self.defs)):
            text = json.dumps(self.defs[name], ensure_ascii=False)
            hits += ['%s -> %s' % (name, m) for m in sorted(set(pat.findall(text)))]
        self.assertEqual(hits, [], '운영 도구 설명이 운영 밖 도구를 가리킨다')

    def test_no_listed_description_points_to_a_retired_tool(self):
        pat = _name_pattern(self.retired)
        hits = []
        for name in sorted(self.listed_cfg & set(self.defs)):
            text = json.dumps(self.defs[name], ensure_ascii=False)
            hits += ['%s -> %s' % (name, m) for m in sorted(set(pat.findall(text)))]
        self.assertEqual(hits, [])

    def test_operations_handler_responses(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        tool_map = R.build_tool_map()
        pat = _name_pattern(self.outside_ops)
        hits = collections.defaultdict(set)
        scanned = 0
        for name in sorted(self.ops):
            fn = tool_map.get(name)
            if fn is None:
                continue
            scanned += 1
            strings = []
            _handler_strings(fn, AoTDataToolService, set(), 3, strings)
            for where, text in strings:
                for m in set(pat.findall(text)):
                    hits['%s -> %s' % (name, m)].add(where)
        self.assertGreater(scanned, 40, '처리기를 거의 못 찾았다 — 검사가 헛돈다')
        self.assertEqual(dict(hits), {},
                         '운영 도구의 응답 문자열이 운영 밖 도구를 가리킨다')

    def test_scanner_catches_a_pointer(self):
        """검사가 실제로 잡는지 — 가짜 처리기로 확인한다."""
        class Fake:
            @classmethod
            def handler(cls):
                """docstring 의 create_function 은 응답이 아니다."""
                return cls._helper()

            @classmethod
            def _helper(cls):
                return {"hint": "call create_function first"}

        strings = []
        _handler_strings(Fake.handler, Fake, set(), 3, strings)
        found = {m for _w, s in strings
                 for m in _name_pattern({'create_function'}).findall(s)}
        self.assertEqual(found, {'create_function'})
        self.assertEqual(len(strings), 2)   # docstring 빼고 두 문자열


# ---------------------------------------------------------------------------
# 3. 크기 — 묶음별 상한 (2단계, 2026-09-24)
# ---------------------------------------------------------------------------

#: 크기는 **호스트가 받는 것**으로 잰다(26-09-24 결정): 그 키로 부른
#: `_get_all_tools(role, profile)` 의 결과 + 그 묶음의 서버 안내문, 저장소
#: 추정기 `_estimate_tokens`. 기준선도 같은 방법으로 쟀다 — 바뀌기 전 main
#: (7ddc96ccf, 서랍 켬 기본)의 Admin 전체 키, 실제 장치가 든 DB 사본
#: (입력 37·출력 106): 도구 34개 목록 17,454 + 안내문 881 = **18,335**.
#: 그때는 네이티브 스키마가 장치 id 를 선택지로 실어 장치 수만큼 커졌다(R1).
BASELINE_HOST_TOKENS = 18_335
#: 운영 묶음 상한 = 기준선의 115%.
OPERATIONS_TOKEN_CEILING = BASELINE_HOST_TOKENS * 115 // 100      # 21,085
#: 운영 + 설정 묶음 상한(안내문 포함) — 줄이기 전 전량(서랍 끔, 136개,
#: 62,679)의 약 72%.
CONFIGURATION_TOKEN_CEILING = 45_000
#: 래칫 — 지금 잰 크기. 넘으면(3% 여유) 멈춘다. 늘리는 것이 맞다면 **이 숫자를
#: 일부러 고친다**(리뷰에서 보이게). 줄었으면 같이 내린다. 26-09-24, 같은 DB
#: 사본으로 잰 값과 테스트 DB 로 잰 값이 같다(스키마가 장치 수와 무관, R1).
#:
#: 26-09-24 두 번째 기록(21,004 / 44,000): 프로필 벤치마크(432회,
#: .local/bench/runs/*_prof_*) lat_19 "관수 5분 늘려" 가 운영 키에서 실패했다 —
#: 운영 안내문은 "시퀀스 운전 시간" 을 약속하는데 modify_sequence_step 이 설정
#: 에만 있었다. 그대로 옮기면 +1,089 라 설명·인자 설명을 줄여 옮겼고(목록
#: 19,492 → 20,084, modify_function_options 의 키 포인터 포함), 안내문에 "묶음
#: 전환은 tool_profile 거절에만" 한 줄을 더했다(882 → 920). 같은 DB 사본(입력
#: 37·출력 106)으로 쟀다 — 상한까지 81 남는다.
#: 설정 묶음은 같은 설명 축약으로 줄었다(44,497 → 44,000).
OPERATIONS_MEASURED_TOKENS = 21_004
CONFIGURATION_MEASURED_TOKENS = 44_000
RATCHET_SLACK = 1.03
#: 서랍을 다시 켰을 때(AOT_MCP_TOOL_TIERING=1) 운영 키의 상시 노출(카탈로그
#: 추정, 안내문 제외 — 선택 기능이라 예전 방법 그대로 둔다).
TIERED_OPERATIONS_TOKEN_CEILING = 11_500


class TestOperationsBudget(unittest.TestCase):
    """카탈로그로 재는 비교(앱 불필요). 상한은 TestHostSurfaceBudget 이 본다."""

    @staticmethod
    def _tokens(names):
        from aot.tools.tool_execution import _estimate_tokens
        defs = _catalog_definitions()
        # 표에는 카탈로그 밖의 실행 가능 도구도 있다 — 목록에 실리는 것만 잰다.
        return _estimate_tokens(json.dumps(
            [defs[n] for n in sorted(names) if n in defs], ensure_ascii=False))

    def test_configuration_is_larger_than_operations(self):
        ops = self._tokens(R.profile_tools(OPS))
        cfg = self._tokens(R.profile_tools(CFG))
        self.assertGreater(ops, 0)
        self.assertGreater(cfg, ops)

    def test_ceilings_follow_the_baseline(self):
        self.assertEqual(21_085, OPERATIONS_TOKEN_CEILING)
        self.assertLessEqual(OPERATIONS_MEASURED_TOKENS, OPERATIONS_TOKEN_CEILING)
        self.assertLessEqual(CONFIGURATION_MEASURED_TOKENS,
                             CONFIGURATION_TOKEN_CEILING)

    def test_tiered_operations_surface_within_budget(self):
        """서랍 켬(선택 기능)의 운영 키 상시 노출 = core ∩ 운영 + 승인 응답·
        서랍 기구."""
        from aot.tools import tool_execution as te
        names = ({n for n in R.profile_tools(OPS) if R.tier_of(n)[1] == 'core'}
                 | set(te._TIER_EXEMPT_TOOLS))
        tokens = self._tokens(names)
        self.assertLessEqual(tokens, TIERED_OPERATIONS_TOKEN_CEILING,
                             '서랍 켬 운영 표면이 %d 추정 토큰이다' % tokens)


class TestSchemaRules(unittest.TestCase):
    """줄이기 규칙(설계 §4.1) — 되돌아오면 크기가 조용히 다시 불어난다."""

    def test_native_schemas_do_not_grow_with_devices(self):
        """R1: 장치 id 를 선택지로 싣지 않는다. 장치 140대 현장에서
        get_sensor_reading 하나가 약 3천 추정 토큰이었다."""
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        ids = ['%08d-0000-4000-8000-000000000000' % i for i in range(140)]
        for name in ('get_sensor_reading', 'set_output_state'):
            build = getattr(N, '_schema_' + name)
            self.assertEqual(json.dumps(build(ids)), json.dumps(build([])), name)

    def test_no_large_or_uuid_enums(self):
        """R1: 20개 넘는 선택지나 UUID 모양 값은 카탈로그 어디에도 없다."""
        uuid_re = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-')
        hits = []

        def walk(name, node):
            if isinstance(node, dict):
                enum = node.get('enum')
                if isinstance(enum, list) and (
                        len(enum) > 20 or any(isinstance(v, str) and uuid_re.match(v)
                                              for v in enum)):
                    hits.append(name)
                for v in node.values():
                    walk(name, v)
            elif isinstance(node, list):
                for v in node:
                    walk(name, v)
        for name, d in _catalog_definitions().items():
            walk(name, d.get('inputSchema'))
        self.assertEqual(hits, [])

    def test_operations_descriptions_are_short(self):
        """R2: 운영 도구 설명은 300자. 예외는 설계 '검증 1회 반영' 6항의 안전·
        의미 문구(승인 응답의 자가 승인 방지)뿐이다."""
        exempt = {'respond_to_confirmation'}
        defs = _catalog_definitions()
        long_ = sorted('%s(%d)' % (n, len(defs[n]['description']))
                       for n in R.profile_tools(OPS)
                       if n in defs and n not in exempt
                       and len(defs[n]['description']) > 300)
        self.assertEqual(long_, [])

    def test_parameter_descriptions_are_short(self):
        """R3: 인자 설명 100자. 예외는 안전·의미 문구로 남긴 것(target_name 의
        한 개체 규칙, get_plot 의 식재량 계산 인자)과 선택 기준이 되는 측정 이름
        목록이다."""
        exempt = {('add_schedule', 'target_name'), ('create_note', 'target_name'),
                  ('get_plot', 'row_spacing_cm'), ('get_plot', 'plant_spacing_cm'),
                  ('get_plot', 'edge_margin_cm'), ('get_plot', 'bed_pitch_cm'),
                  ('get_plot', 'rows_per_bed'),
                  ('search_devices', 'measurement_type'),
                  ('respond_to_confirmation', 'confirmation_ids')}
        defs = _catalog_definitions()
        long_ = []
        for n in sorted(R.profile_tools(OPS)):
            props = ((defs.get(n) or {}).get('inputSchema') or {}).get('properties') or {}
            for k, v in props.items():
                d = v.get('description') or ''
                if len(d) > 100 and (n, k) not in exempt:
                    long_.append('%s.%s(%d)' % (n, k, len(d)))
        self.assertEqual(long_, [])

    def test_reading_pointer_where_replies_carry_reading(self):
        """B′: 응답에 `_reading` 을 싣는 도구는 설명에 따르라는 한 줄을 둔다 —
        응답에만 있으면 모델이 쓰지 않는다는 기록된 실패가 있다."""
        carriers = {'list_plots', 'get_plot', 'get_zone_sensor_summary',
                    'search_devices', 'get_device_list', 'get_map_equipment',
                    'get_output_state', 'get_crop_status', 'apply_plot_resources',
                    'get_spatial_tree'}
        defs = _catalog_definitions()
        missing = sorted(n for n in carriers if '_reading' not in defs[n]['description'])
        self.assertEqual(missing, [])

    def test_stage_tools_share_one_rule(self):
        """P3: 두 단계 도구가 같은 기준(이미 일어났나)을 말하고 서로를 가리킨다."""
        defs = _catalog_definitions()
        confirm = defs['confirm_plot_stage']['description']
        resched = defs['reschedule_plot_stage']['description']
        self.assertIn('reschedule_plot_stage', confirm)
        self.assertIn('already happened', confirm)
        self.assertIn('confirm_plot_stage', resched)
        self.assertIn('AHEAD', resched)
        self.assertNotIn('nothing to confirm', confirm,
                         'stage_proposal 이 null 이어도 재배자가 말한 전환은 확인한다')
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        self.assertIn('confirm_plot_stage', S.STAGE_TOOL_RULE)
        self.assertIn('reschedule_plot_stage', S.STAGE_TOOL_RULE)

    def test_multi_target_arguments_are_capped(self):
        """3-F: 여러 대상 인자는 목록이고, 상한을 설명이 말한다."""
        defs = _catalog_definitions()
        for tool, arg in (('get_output_state', 'device_ids'),
                          ('get_sensor_detail', 'loc_ids'),
                          ('get_plot', 'plot_ids'),
                          ('search_notes', 'target_names'),
                          ('get_sensor_reading', 'device_ids')):
            prop = defs[tool]['inputSchema']['properties'][arg]
            self.assertEqual('array', prop['type'], tool)
            self.assertIn('10', prop['description'], tool)


# ---------------------------------------------------------------------------
# 4. 서버 안내문·거절 본문 (앱 불필요)
# ---------------------------------------------------------------------------

class TestServerInstructions(unittest.TestCase):

    def setUp(self):
        from aot.tools import tool_execution as te
        self.te = te

    def test_operations_note_names_the_profile_and_where_to_switch(self):
        text = self.te._server_instructions(OPS)
        self.assertIn("'operations' tool profile", text)
        self.assertIn(_SWITCH_PLACE, text)
        # 분야만 말하고 도구 이름은 싣지 않는다.
        cfg_only = R.profile_tools(CFG) - R.profile_tools(OPS)
        self.assertEqual(_name_pattern(cfg_only).findall(text), [])

    def test_drawer_switch_accepts_common_true_values(self):
        for v, on in (('1', True), ('true', True), ('YES', True), (' On ', True),
                      ('0', False), ('false', False), ('off', False), ('', False),
                      ('2', False)):
            with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_TIERING': v}):
                self.assertIs(on, self.te._tiering_enabled(), repr(v))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AOT_MCP_TOOL_TIERING', None)
            self.assertFalse(self.te._tiering_enabled())

    def test_unrestricted_has_no_profile_note(self):
        self.assertNotIn('TOOL PROFILE', self.te._server_instructions())
        self.assertNotIn('TOOL PROFILE', self.te._server_instructions(None))

    def test_switch_off_drops_the_note(self):
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '0'}):
            self.assertNotIn('TOOL PROFILE', self.te._server_instructions(OPS))

    def test_drawer_list_follows_the_profile(self):
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_TIERING': '1'}):
            ops = self.te._server_instructions(OPS)
            cfg = self.te._server_instructions(CFG)
        # 장치 정의 서랍은 설정 묶음에만 도구가 있다.
        self.assertNotIn('definition (', ops)
        self.assertIn('definition (', cfg)

    def test_refusal_body(self):
        from aot.tools import mcp_auth
        te = self.te
        editor = mcp_auth.RoleInfo(name='Editor', can_write=True, user_id='u',
                                   can_edit_settings=True, can_use_ai_chat=True,
                                   can_edit_plots=True, tool_profile=OPS)
        body = te._profile_refusal('create_function', OPS, 'mcp_http',
                                   role=editor)
        self.assertEqual(body['reason_code'], 'tool_profile')
        self.assertIn('(operations)', body['message'])
        self.assertIn(_SWITCH_PLACE, body['message'])
        # 바꾸는 사람은 키 소유자가 아니라 사용자 편집 권한을 가진 관리자다(F4).
        self.assertIn('administrator (user-edit permission)', body['message'])
        self.assertNotIn('key owner', body['message'])
        self.assertNotIn('key owner', te._server_instructions(OPS))
        # 쓰기 도구의 performed:false 는 실행층이 해석 규칙과 함께 붙인다.
        self.assertNotIn('performed', body)
        self.assertIs(te._profile_refusal('list_device_types', OPS,
                                          'rest')['performed'], False)
        self.assertIsNone(te._profile_refusal('create_function', OPS, 'in_app'))
        self.assertIsNone(te._profile_refusal('create_function', None, 'mcp_http'))
        self.assertIsNone(te._profile_refusal('operate_device', OPS, 'mcp_http'))
        self.assertIsNone(te._profile_refusal('open_drawer', OPS, 'mcp_http'))
        # 모르는 이름은 실행층의 "Unknown tool" 이 답한다.
        self.assertIsNone(te._profile_refusal('no_such_tool_x', OPS, 'mcp_http'))
        self.assertIn('operate_device', te._profile_refusal(
            'set_output_state', CFG, 'mcp_stdio')['message'])

    def test_switch_hint_only_for_profile_refusals(self):
        """조언 전용 모드(write_disabled)는 서버 전체 설정이다 — 묶음을 바꾸라고
        하지 않고, 바꿔도 안 된다고 말한다. 프로필 벤치마크(26-09-24) lat_24:
        운영 키의 모델이 이 거절을 보고 설정 묶음으로 바꾸라고 안내했다."""
        from aot.tools import mcp_auth
        from aot.tools import mcp_safety_gate as gate
        editor = mcp_auth.RoleInfo(name='Editor', can_write=True, user_id='u',
                                   can_edit_settings=True, can_use_ai_chat=True,
                                   can_edit_plots=True, tool_profile=OPS)
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            for tool in ('operate_device', 'create_note'):
                body = gate.role_refusal(tool, editor)
                self.assertEqual('write_disabled', body['reason_code'], tool)
                self.assertNotIn(_SWITCH_PLACE, body['message'], tool)
                self.assertIn('not this key', body['message'], tool)
                self.assertIn('would not change it', body['message'], tool)
        # 전환 안내는 tool_profile 거절에만 있다.
        self.assertIn(_SWITCH_PLACE, self.te._profile_refusal(
            'create_function', OPS, 'mcp_http', role=editor)['message'])
        # 서버 안내문도 전환 안내를 그 경우로 좁힌다.
        text = self.te._server_instructions(OPS)
        self.assertIn("'tool_profile' refusal", text)
        self.assertIn('never for other refusals', text)

    def test_no_switch_hint_when_permissions_block_it_anyway(self):
        """읽기 전용 키의 쓰기 도구 — 묶음을 바꿔도 못 쓰므로 바꾸라고 하지 않는다."""
        from aot.tools import mcp_auth
        readonly = mcp_auth.RoleInfo(name='Editor', can_write=False, user_id='u',
                                     can_edit_settings=False,
                                     can_use_ai_chat=True, can_edit_plots=False,
                                     tool_profile=OPS)
        body = self.te._profile_refusal('create_function', OPS, 'mcp_http',
                                        role=readonly)
        self.assertEqual(body['reason_code'], 'tool_profile')
        self.assertNotIn(_SWITCH_PLACE, body['message'])
        self.assertIn('would not help', body['message'])
        # 읽기 도구는 바꾸면 풀리므로 안내가 붙는다.
        body = self.te._profile_refusal('list_device_types', OPS, 'mcp_http',
                                        role=readonly)
        self.assertIn(_SWITCH_PLACE, body['message'])


# ---------------------------------------------------------------------------
# 5. 앱이 필요한 경로 — 인증·목록·실행·백필
# ---------------------------------------------------------------------------

class _AppFixture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.aot_flask.app import create_app
        cls.app = create_app()
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.config import USER_ROLES
        from aot.databases.models import Role, User
        self.db = db
        self._env = mock.patch.dict(os.environ, {
            'AOT_MCP_WRITE_ENABLED': '1', 'AOT_MCP_REQUIRE_AUTH': '1',
            'AOT_MCP_TOOL_PROFILES': '1'})
        self._env.start()
        self._wipe()
        roles = {}
        for spec in USER_ROLES:
            fields = {k: v for k, v in spec.items() if k not in ('id', 'name')}
            role = Role(name=_PREFIX + spec['name'], **fields)
            db.session.add(role)
            roles[spec['name']] = role
        db.session.commit()
        for name in ('Admin', 'Editor', 'Monitor'):
            db.session.add(User(name=(_PREFIX + name).lower(),
                                role_id=roles[name].id, is_enabled=True))
        db.session.commit()

    def tearDown(self):
        try:
            self._wipe()
        finally:
            self._env.stop()
            self.db.session.remove()

    def _wipe(self):
        from aot.databases.models import (MCPAuditLog, MCPConfirmation, Role,
                                          User, UserAPIKey)
        db = self.db
        db.session.rollback()
        ids = [u.id for u in User.query.filter(
            User.name.like(_PREFIX.lower() + '%')).all()]
        if ids:
            UserAPIKey.query.filter(UserAPIKey.user_id.in_(ids)).delete(
                synchronize_session=False)
        MCPAuditLog.query.delete(synchronize_session=False)
        MCPConfirmation.query.delete(synchronize_session=False)
        User.query.filter(User.name.like(_PREFIX.lower() + '%')).delete(
            synchronize_session=False)
        Role.query.filter(Role.name.like(_PREFIX + '%')).delete(
            synchronize_session=False)
        db.session.commit()

    def _user(self, who):
        from aot.databases.models import User
        return User.query.filter(User.name == (_PREFIX + who).lower()).first()

    def _issue(self, who, scope='full', profile=OPS):
        raw = self._user(who).issue_api_key('client', scope, tool_profile=profile)
        self.db.session.commit()
        return base64.b64encode(raw).decode()

    def _auth(self, key):
        from aot.tools import mcp_auth
        ok, _agent, role, err = mcp_auth.authenticate_http({'X-API-KEY': key})
        self.assertTrue(ok, err)
        return role

    def _listed(self, role, tiered=False):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        return {t['name'] for t in te._get_all_tools(
            self.app, role=role, tiered=tiered,
            profile=mcp_auth.tool_profile_of(role))}


class TestHostSurfaceBudget(_AppFixture):
    """호스트가 받는 크기 — 그 키의 tools/list 결과 + 그 묶음의 서버 안내문."""

    def _host_tokens(self, profile):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Admin', 'full', profile))
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_TIERING': '0'}):
            tools = te._get_all_tools(self.app, role=role, profile=profile)
            text = te._server_instructions(profile)
        return (te._estimate_tokens(json.dumps(tools, ensure_ascii=False))
                + te._estimate_tokens(text))

    def test_operations_within_ceiling(self):
        tokens = self._host_tokens(OPS)
        self.assertLessEqual(
            tokens, OPERATIONS_TOKEN_CEILING,
            '운영 키가 받는 목록+안내문이 %d 추정 토큰이다(상한 %d = 기준선 %d 의 '
            '115%%). 도구를 운영으로 올렸거나 설명이 길어졌다 — 도구가 아니라 '
            '설명을 줄일 것: 결과 읽는 법은 응답의 _reading 으로(B′), 설명에는 '
            '고르는 기준과 포인터 한 줄만'
            % (tokens, OPERATIONS_TOKEN_CEILING, BASELINE_HOST_TOKENS))

    def test_configuration_within_ceiling(self):
        tokens = self._host_tokens(CFG)
        self.assertLessEqual(tokens, CONFIGURATION_TOKEN_CEILING,
                             '운영 + 설정 키가 받는 목록+안내문이 %d 추정 토큰이다'
                             % tokens)

    def test_ratchet(self):
        """지금 크기에서 3% 넘게 늘면 멈춘다 — 상한 아래라도 조금씩 불어나는
        것을 리뷰에서 보이게 한다. 늘리는 것이 맞으면 *_MEASURED_TOKENS 를
        고친다."""
        for profile, measured in ((OPS, OPERATIONS_MEASURED_TOKENS),
                                  (CFG, CONFIGURATION_MEASURED_TOKENS)):
            tokens = self._host_tokens(profile)
            self.assertLessEqual(
                tokens, int(measured * RATCHET_SLACK),
                '%s 키 표면이 %d 추정 토큰으로 기록값 %d 의 3%% 를 넘었다 — '
                '의도한 것이면 test_mcp_tool_profiles 의 *_MEASURED_TOKENS 를 '
                '고칠 것' % (profile, tokens, measured))


class TestAuthenticationCarriesTheProfile(_AppFixture):

    def test_key_profile_reaches_the_role(self):
        for profile in (OPS, CFG):
            with self.subTest(profile=profile):
                role = self._auth(self._issue('Editor', profile=profile))
                self.assertEqual(role.tool_profile, profile)

    def test_unassigned_key_is_operations(self):
        from aot.databases.models import UserAPIKey
        key = self._issue('Editor', profile=CFG)
        UserAPIKey.query.update({UserAPIKey.tool_profile: None},
                                synchronize_session=False)
        self.db.session.commit()
        self.assertEqual(self._auth(key).tool_profile, OPS)

    def test_stdio_env_key_carries_the_profile(self):
        from aot.tools import mcp_auth
        key = self._issue('Editor', profile=CFG)
        with mock.patch.dict(os.environ, {'AOT_MCP_API_KEY': key}):
            ok, _agent, role, err = mcp_auth.authenticate_stdio('client')
        self.assertTrue(ok, err)
        self.assertEqual(role.tool_profile, CFG)

    def test_service_account_and_legacy_keys(self):
        from aot.tools import mcp_auth
        service = types.SimpleNamespace(
            auth_provider=mcp_auth.SERVICE_ACCOUNT_PROVIDER)
        person = types.SimpleNamespace(auth_provider='local')
        # 서비스 계정은 행이 없어도(레거시 칸) 제한 없음, 사람의 레거시 키는 운영.
        self.assertEqual(mcp_auth.key_tool_profile(service, None),
                         R.TOOL_PROFILE_UNRESTRICTED)
        self.assertEqual(mcp_auth.key_tool_profile(
            service, types.SimpleNamespace(tool_profile=OPS)),
            R.TOOL_PROFILE_UNRESTRICTED)
        unrestricted = mcp_auth.RoleInfo(
            name='Admin', can_write=True, user_id=None,
            tool_profile=R.TOOL_PROFILE_UNRESTRICTED)
        self.assertIsNone(mcp_auth.tool_profile_of(unrestricted))
        self.assertEqual(mcp_auth.key_tool_profile(person, None), OPS)
        row = types.SimpleNamespace(tool_profile='everything')
        self.assertEqual(mcp_auth.key_tool_profile(person, row), OPS)

    def test_in_app_snapshot_is_unrestricted(self):
        from aot.tools import mcp_auth
        role = mcp_auth._role_for(mcp_auth.ensure_service_account())
        self.assertIsNone(role.tool_profile)

    def test_auth_off_uses_the_default_profile(self):
        from aot.tools import mcp_auth
        self.assertEqual(mcp_auth.tool_profile_of(None), OPS)
        with mock.patch.dict(os.environ, {'AOT_MCP_DEFAULT_TOOL_PROFILE': CFG}):
            self.assertEqual(mcp_auth.tool_profile_of(None), CFG)
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '0'}):
            self.assertIsNone(mcp_auth.tool_profile_of(None))


class TestListing(_AppFixture):
    """운영/설정 × 전체/읽기 전용 키."""

    _MACHINERY = {'open_drawer', 'get_tool_detail', 'use_tool'}

    def test_operations_full_key(self):
        names = self._listed(self._auth(self._issue('Editor', 'full', OPS)))
        extra = names - self._MACHINERY - R.profile_tools(OPS)
        self.assertEqual(sorted(extra), [])
        for n in ('operate_device', 'modify_function_options', 'submit_advice',
                  'respond_to_confirmation', 'confirm_plot_stage',
                  'modify_sequence_step'):
            self.assertIn(n, names)
        for n in ('create_function', 'list_device_types', 'set_output_state',
                  'list_available_devices', 'configure_sequence_day'):
            self.assertNotIn(n, names)

    def test_configuration_full_key(self):
        names = self._listed(self._auth(self._issue('Editor', 'full', CFG)))
        for n in ('operate_device', 'create_function', 'list_device_types',
                  'modify_sequence_step', 'create_plot'):
            self.assertIn(n, names)
        for n in ('set_output_state', 'list_available_devices'):
            self.assertNotIn(n, names)

    def test_operations_readonly_key(self):
        from aot.tools import mcp_safety_gate as gate
        names = self._listed(self._auth(self._issue('Editor', 'readonly', OPS)))
        self.assertEqual(sorted(names & gate.write_tools()), [])
        self.assertIn('submit_advice', names)   # 조언은 읽기 전용 키에도 열려 있다
        self.assertIn('get_sensor_detail', names)
        self.assertNotIn('list_device_types', names)

    def test_configuration_readonly_key(self):
        from aot.tools import mcp_safety_gate as gate
        names = self._listed(self._auth(self._issue('Editor', 'readonly', CFG)))
        self.assertEqual(sorted(names & gate.write_tools()), [])
        self.assertIn('list_device_types', names)   # 설정 쪽 읽기는 보인다
        self.assertNotIn('create_function', names)

    def test_configuration_adds_to_operations(self):
        ops = self._listed(self._auth(self._issue('Editor', 'full', OPS)))
        cfg = self._listed(self._auth(self._issue('Editor', 'full', CFG)))
        self.assertTrue(ops < cfg)

    def test_tiered_listing_and_drawers_stay_inside_the_profile(self):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_TIERING': '1'}):
            listed = self._listed(role, tiered=None)
            index = te._open_drawer(self.app, {}, role=role, profile=OPS)
            inside = {n for d in index['drawers'] for n in d['tools']}
            opened = te._open_drawer(self.app, {'drawer': 'function'},
                                     role=role, profile=OPS)
            detail = te._get_tool_detail(
                self.app, {'tool_name': 'create_function'}, role=role,
                profile=OPS)
        cfg_only = R.profile_tools(CFG) - R.profile_tools(OPS)
        self.assertEqual(sorted((listed | inside) & cfg_only), [])
        self.assertIn('use_tool', listed)
        opened_names = {t['name'] for t in opened['tools']}
        self.assertIn('modify_function_options', opened_names)
        self.assertNotIn('create_function', opened_names)
        # 묶음 밖 도구의 정의는 "Unknown tool" 이 아니라 호출과 같은 거절이다(F3).
        self.assertEqual(detail['reason_code'], 'tool_profile')
        self.assertIn('administrator (user-edit permission)', detail['message'])

    def test_lookups_outside_the_profile_say_so(self):
        """get_tool_detail·open_drawer 가 묶음 밖을 조용히 비우지 않는다(F3)."""
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        drawer = te._open_drawer(self.app, {'drawer': 'definition'}, role=role,
                                 profile=OPS)
        self.assertEqual(drawer['reason_code'], 'tool_profile')
        self.assertIn("'definition' drawer", drawer['message'])
        self.assertIn(_SWITCH_PLACE, drawer['message'])
        retired = te._get_tool_detail(self.app, {'tool_name': 'set_output_state'},
                                      role=role, profile=OPS)
        self.assertIn('operate_device', retired['message'])
        # 모르는 이름은 그대로 Unknown tool.
        unknown = te._get_tool_detail(self.app, {'tool_name': 'no_such_tool_x'},
                                      role=role, profile=OPS)
        self.assertIn('Unknown tool', unknown['error'])
        # 읽기 전용 키 + 쓰기 도구 — 바꿔도 못 쓰니 안내 없이 거절.
        ro = self._auth(self._issue('Editor', 'readonly', OPS))
        body = te._get_tool_detail(self.app, {'tool_name': 'create_function'},
                                   role=ro, profile=OPS)
        self.assertEqual(body['reason_code'], 'tool_profile')
        self.assertNotIn(_SWITCH_PLACE, body['message'])
        # 설정 묶음이면 그대로 연다.
        cfg = self._auth(self._issue('Editor', 'full', CFG))
        opened = te._open_drawer(self.app, {'drawer': 'definition'}, role=cfg,
                                 profile=CFG)
        self.assertGreater(opened['count'], 0)

    def test_in_app_listing_is_unrestricted(self):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        role = mcp_auth._role_for(mcp_auth.ensure_service_account())
        names = {t['name'] for t in te._get_all_tools(self.app, role=role,
                                                      tiered=False)}
        for n in ('create_function', 'set_output_state', 'list_available_devices'):
            self.assertIn(n, names)
        with mock.patch.dict(os.environ, {'AOT_AI_BUILTIN_MCP_TIERING': '0'}):
            agent_names = {t['name'] for t in te.tools_for_agent(self.app)}
        self.assertIn('create_function', agent_names)

    def test_in_app_listing_keeps_drawers_when_mcp_default_flips(self):
        """외부 MCP 의 서랍 기본값(끔)이 인앱 AI 의 내장 목록을 바꾸지 않는다 —
        인앱은 AOT_AI_BUILTIN_MCP_TIERING(기본 켬)을 따른다(설계 §3.7)."""
        from aot.tools import tool_execution as te
        env = {k: v for k, v in os.environ.items()
               if k not in ('AOT_MCP_TOOL_TIERING', 'AOT_AI_BUILTIN_MCP_TIERING')}
        with mock.patch.dict(os.environ, env, clear=True):
            names = {t['name'] for t in te.tools_for_agent(self.app)}
        self.assertIn('open_drawer', names)
        self.assertIn('use_tool', names)
        self.assertNotIn('create_function', names, '서랍 도구가 상시 목록에 올라왔다')
        with mock.patch.dict(os.environ, dict(env, AOT_MCP_TOOL_TIERING='1'),
                             clear=True):
            same = {t['name'] for t in te.tools_for_agent(self.app)}
        self.assertEqual(names, same, '외부 MCP 스위치가 인앱 목록을 바꿨다')

    def test_external_listing_has_no_drawer_machinery_by_default(self):
        """서랍을 끈(기본) 외부 목록에는 open_drawer·get_tool_detail·use_tool 이
        없다. 켜면 돌아온다."""
        role = self._auth(self._issue('Editor', 'full', OPS))
        env = {k: v for k, v in os.environ.items() if k != 'AOT_MCP_TOOL_TIERING'}
        with mock.patch.dict(os.environ, env, clear=True):
            names = self._listed(role, tiered=None)
        for n in ('open_drawer', 'get_tool_detail', 'use_tool'):
            self.assertNotIn(n, names)
        self.assertIn('respond_to_confirmation', names)
        self.assertIn('get_plot', names)
        with mock.patch.dict(os.environ, dict(env, AOT_MCP_TOOL_TIERING='1'),
                             clear=True):
            tiered = self._listed(role, tiered=None)
        self.assertIn('open_drawer', tiered)
        self.assertIn('use_tool', tiered)

    def test_switch_off_restores_the_full_surface(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '0'}):
            names = self._listed(role)
        self.assertIn('create_function', names)
        self.assertIn('set_output_state', names)


class TestOutOfProfileCalls(_AppFixture):

    def _call(self, tool, role, transport, args=None):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        out = te._execute_tool(self.app, tool, dict(args or {}),
                               agent_id='user:%s' % _PREFIX.lower(), role=role,
                               scope_user_uuid=getattr(role, 'user_id', None),
                               transport=transport,
                               tool_profile=mcp_auth.tool_profile_of(role))
        return json.loads(out[0]['text'])

    def _last_audit(self):
        from aot.databases.models import MCPAuditLog
        self.db.session.remove()
        return MCPAuditLog.query.order_by(MCPAuditLog.id.desc()).first()

    def test_refused_on_every_external_transport(self):
        from aot.databases.models import MCPConfirmation
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            for transport in ('mcp_stdio', 'mcp_http', 'rest'):
                for tool, permission in (('create_function', 'write'),
                                         ('list_device_types', 'read')):
                    with self.subTest(transport=transport, tool=tool):
                        body = self._call(tool, role, transport,
                                          {'name': 'x', 'function_type': 'y'})
                        self.assertEqual(body['status'], 'refused', body)
                        self.assertEqual(body['reason_code'], 'tool_profile')
                        self.assertEqual(body['call_state'], 'refused')
                        self.assertIs(body['performed'], False)
                        self.assertEqual(body['tool_profile'], OPS)
                        self.assertIn('(operations)', body['message'])
                        self.assertIn(_SWITCH_PLACE, body['message'])
                        row = self._last_audit()
                        self.assertEqual(row.tool_name, tool)
                        self.assertEqual(row.call_state, 'refused')
                        self.assertEqual(row.result_summary, 'tool_profile')
                        self.assertEqual(row.transport, transport)
                        self.assertEqual(row.permission, permission)
            run.assert_not_called()
        self.assertEqual(MCPConfirmation.query.count(), 0)

    def test_retired_tool_is_refused_for_keys(self):
        role = self._auth(self._issue('Editor', 'full', CFG))
        with mock.patch('aot.tools.aot_native_tool_engine.AoTNativeToolEngine'
                        '.execute') as run:
            body = self._call('set_output_state', role, 'mcp_http',
                              {'device_id': 'x', 'state': 'on'})
            run.assert_not_called()
        self.assertEqual(body['reason_code'], 'tool_profile')
        self.assertIn('operate_device', body['message'])

    def test_use_tool_does_not_bypass(self):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            body = self._call('use_tool', role, 'mcp_http',
                              {'tool_name': 'list_device_types', 'arguments': {}})
            run.assert_not_called()
        self.assertEqual(body['reason_code'], 'tool_profile')
        self.assertTrue(self._last_audit().via_drawer)

    def test_inside_the_profile_runs(self):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', CFG))
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'types': []}) as run:
            body = self._call('list_device_types', role, 'mcp_http')
            run.assert_called_once()
        self.assertEqual(body['call_state'], 'executed')

    def test_in_app_is_not_refused(self):
        """인앱 AI 는 같은 실행층을 지나도 묶음으로 막지 않는다."""
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'types': []}) as run:
            body = self._call('list_device_types', role, 'in_app')
            run.assert_called_once()
        self.assertEqual(body['call_state'], 'executed')
        # 실제 인앱 진입점 — 묶음을 넘기지 않는다.
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'types': []}) as run:
            res = te.execute_for_agent(self.app, 'list_device_types', {})
            run.assert_called_once()
        self.assertEqual(res['status'], 'success', res)

    def test_switch_off_does_not_refuse(self):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '0'}), \
                mock.patch.object(te, '_dispatch_virtual_tool',
                                  return_value={'types': []}) as run:
            body = self._call('list_device_types', role, 'mcp_http')
            run.assert_called_once()
        self.assertEqual(body['call_state'], 'executed')

    def test_system_brief_names_the_profile(self):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               side_effect=lambda *a, **k: {'status': 'ok'}):
            body = self._call('get_system_brief', role, 'mcp_http')
            res = te.execute_for_agent(self.app, 'get_system_brief', {})
        self.assertEqual(body['tool_profile']['name'], OPS)
        self.assertIn(_SWITCH_PLACE, body['tool_profile']['note'])
        # 인앱 진입점은 묶음을 넘기지 않으므로 싣지 않는다.
        self.assertNotIn('tool_profile', res['result'])

    def test_stdio_transport_end_to_end(self):
        from aot import aot_mcp_server as srv
        from aot.tools import tool_execution as te
        key = self._issue('Editor', 'full', OPS)
        out = io.StringIO()
        server = srv.StdioMCPServer(self.app, out=out)
        with mock.patch.dict(os.environ, {'AOT_MCP_API_KEY': key}), \
                mock.patch.object(te, '_dispatch_virtual_tool') as run:
            server._handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                            'params': {'clientInfo': {'name': 'test'}}})
            server._handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            server._handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                            'params': {'name': 'create_function',
                                       'arguments': {}}})
            run.assert_not_called()
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertIn("'operations' tool profile",
                      lines[0]['result']['instructions'])
        listed = {t['name'] for t in lines[1]['result']['tools']}
        self.assertNotIn('create_function', listed)
        self.assertIn('operate_device', listed)
        body = json.loads(lines[2]['result']['content'][0]['text'])
        self.assertEqual(body['reason_code'], 'tool_profile')


    # --- F1: 인앱 물리 제어가 지나는 서비스 계정 stdio ----------------------

    def _stdio_call(self, key, tool, args):
        from aot import aot_mcp_server as srv
        out = io.StringIO()
        server = srv.StdioMCPServer(self.app, out=out)
        # 서랍을 꺼서 전체 표면을 본다(서랍 안이냐 밖이냐가 아니라 묶음을 본다).
        with mock.patch.dict(os.environ, {'AOT_MCP_API_KEY': key,
                                          'AOT_MCP_TOOL_TIERING': '0'}):
            server._handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                            'params': {'clientInfo': {'name': 'test'}}})
            server._handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            server._handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                            'params': {'name': tool, 'arguments': args}})
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        listed = {t['name'] for t in lines[1]['result']['tools']}
        body = json.loads(lines[2]['result']['content'][0]['text'])
        return lines[0]['result']['instructions'], listed, body

    def test_service_account_stdio_can_call_set_output_state(self):
        """PhysicalControlResolver → MCPBridgeService 는 서비스 계정 키로 stdio
        하위 프로세스에 붙어 set_output_state 를 부른다. 묶음이 이 길을 끊으면
        인앱 물리 제어가 통째로 멈춘다(2026-09-24 검토 F1)."""
        from aot.databases.models import UserAPIKey
        from aot.tools import mcp_auth
        from aot.tools import mcp_safety_gate as gate
        service = mcp_auth.ensure_service_account()
        service_id = service.id
        key = base64.b64encode(service.issue_api_key('internal')).decode()
        self.db.session.commit()
        self.addCleanup(lambda: (
            self.db.session.rollback(),
            UserAPIKey.query.filter(UserAPIKey.user_id == service_id).delete(
                synchronize_session=False),
            self.db.session.commit()))
        run = mock.patch('aot.tools.aot_native_tool_engine.AoTNativeToolEngine'
                         '.execute', return_value={'status': 'success'})
        # 승인 게이트는 이 검사의 대상이 아니다(묶음이 먼저 막는지를 본다).
        with run as execute, mock.patch.object(gate, 'gate', return_value=None):
            text, listed, body = self._stdio_call(
                key, 'set_output_state', {'device_id': 'x', 'state': 'on'})
            execute.assert_called_once()
        self.assertNotIn('TOOL PROFILE', text)
        self.assertIn('set_output_state', listed)
        self.assertIn('create_function', listed)
        self.assertNotEqual(body.get('reason_code'), 'tool_profile', body)

        # 사람의 키(운영·설정)는 여전히 못 부른다.
        for profile in (OPS, CFG):
            with self.subTest(profile=profile), run as execute, \
                    mock.patch.object(gate, 'gate', return_value=None):
                _t, listed, body = self._stdio_call(
                    self._issue('Editor', 'full', profile), 'set_output_state',
                    {'device_id': 'x', 'state': 'on'})
                execute.assert_not_called()
                self.assertNotIn('set_output_state', listed)
                self.assertEqual(body['reason_code'], 'tool_profile')

    # --- F3: 묶음 밖 조회는 거절로 기록된다 -----------------------------------

    def test_out_of_profile_lookup_is_audited_as_refused(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        body = self._call('get_tool_detail', role, 'mcp_http',
                          {'tool_name': 'create_function'})
        self.assertEqual(body['reason_code'], 'tool_profile')
        self.assertEqual(body['call_state'], 'refused')
        self.assertEqual(self._last_audit().result_summary, 'tool_profile')

    # --- F2: 묶음 밖 도구의 승인 요청 ----------------------------------------

    def _pending(self, tool_name, params):
        from aot.databases.models import MCPConfirmation
        row = MCPConfirmation(
            expires_at=datetime.utcnow() + timedelta(seconds=300),
            tool_name=tool_name, params_json=json.dumps(params),
            agent_id='test-agent', status='pending')
        row.save()
        return row.unique_id

    def _status(self, cid):
        from aot.databases.models import MCPConfirmation
        self.db.session.remove()
        return MCPConfirmation.query.filter_by(unique_id=cid).first().status

    def test_pending_list_hides_out_of_profile_tool_names(self):
        cfg_id = self._pending('create_function', {'name': 'x'})
        ops_id = self._pending('operate_device', {'device_id': 'y'})
        role = self._auth(self._issue('Editor', 'full', OPS))
        body = self._call('list_pending_confirmations', role, 'mcp_http')
        items = {i['confirmation_id']: i for i in body['pending']}
        masked, kept = items[cfg_id], items[ops_id]
        self.assertNotIn('tool_name', masked)
        self.assertNotIn('params', masked)
        self.assertEqual(masked['domain'], 'function')
        self.assertIs(masked['can_approve_with_this_key'], False)
        self.assertEqual(kept['tool_name'], 'operate_device')
        self.assertNotIn('create_function', json.dumps(body))
        self.assertIn('out_of_profile_note', body)
        # 설정 묶음 키와 인앱은 가리지 않는다.
        cfg = self._auth(self._issue('Editor', 'full', CFG))
        body = self._call('list_pending_confirmations', cfg, 'mcp_http')
        self.assertEqual({i.get('tool_name') for i in body['pending']},
                         {'create_function', 'operate_device'})
        body = self._call('list_pending_confirmations', role, 'in_app')
        self.assertIn('create_function', json.dumps(body))

    def test_out_of_profile_request_can_be_rejected_not_approved(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        cid = self._pending('create_function', {'name': 'x'})
        body = self._call('respond_to_confirmation', role, 'mcp_http',
                          {'confirmation_id': cid, 'decision': 'approve'})
        self.assertEqual(body['reason_code'], 'tool_profile', body)
        self.assertEqual(body['call_state'], 'refused')
        self.assertNotIn('create_function', body['message'])
        self.assertIn(_SWITCH_PLACE, body['message'])
        self.assertEqual(self._status(cid), 'pending')
        body = self._call('respond_to_confirmation', role, 'mcp_http',
                          {'confirmation_id': cid, 'decision': 'reject'})
        self.assertEqual(body['status'], 'success', body)
        self.assertEqual(self._status(cid), 'rejected')

    def test_batch_approval_refuses_only_out_of_profile_items(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        cfg_id = self._pending('create_function', {'name': 'x'})
        ops_id = self._pending('create_note', {'content': 'y'})
        with mock.patch('aot.tools.mcp_safety_gate.approve',
                        return_value={'status': 'success'}) as approve:
            body = self._call('respond_to_confirmation', role, 'mcp_http',
                              {'confirmation_ids': [cfg_id, ops_id],
                               'decision': 'approve'})
        approve.assert_called_once()
        results = {r['confirmation_id']: r for r in body['results']}
        self.assertEqual(results[cfg_id]['reason_code'], 'tool_profile')
        self.assertEqual(results[ops_id]['status'], 'success')

    # --- D1: 보관 안내는 보관할 수 있는 연결에만 -----------------------------

    def _shelve_hint(self, body):
        from aot.tools.tool_execution import KNOWLEDGE_SHELVE_READING
        return KNOWLEDGE_SHELVE_READING in (body.get('_reading') or [])

    def test_knowledge_search_shelve_hint_follows_the_profile(self):
        from aot.tools import tool_execution as te
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               side_effect=lambda *a, **k: {'result': 'none'}):
            ops = self._call('knowledge_search', self._auth(
                self._issue('Editor', 'full', OPS)), 'mcp_http', {'query': 'q'})
            cfg = self._call('knowledge_search', self._auth(
                self._issue('Editor', 'full', CFG)), 'mcp_http', {'query': 'q'})
            cfg_ro = self._call('knowledge_search', self._auth(
                self._issue('Editor', 'readonly', CFG)), 'mcp_http',
                {'query': 'q'})
            monitor = self._call('knowledge_search', self._auth(
                self._issue('Monitor', 'full', CFG)), 'mcp_http', {'query': 'q'})
            in_app = te.execute_for_agent(self.app, 'knowledge_search',
                                          {'query': 'q'})
        self.assertFalse(self._shelve_hint(ops))
        self.assertTrue(self._shelve_hint(cfg))
        self.assertFalse(self._shelve_hint(cfg_ro))
        self.assertFalse(self._shelve_hint(monitor))
        self.assertTrue(self._shelve_hint(in_app['result']), in_app)
        # 설명은 늘리지 않는다 — 이름은 응답에만 있다.
        desc = _catalog_definitions()['knowledge_search']['description']
        self.assertNotIn('knowledge_shelve', desc)


class TestBackfill(_AppFixture):

    def _audit(self, agent_id, tool, days_ago):
        from aot.databases.models import MCPAuditLog
        self.db.session.add(MCPAuditLog(
            agent_id=agent_id, tool_name=tool,
            timestamp=datetime.utcnow() - timedelta(days=days_ago)))
        self.db.session.commit()

    def _null_all(self):
        from aot.databases.models import UserAPIKey
        UserAPIKey.query.update({UserAPIKey.tool_profile: None},
                                synchronize_session=False)
        self.db.session.commit()

    def _profiles_of(self, who):
        from aot.databases.models import UserAPIKey
        self.db.session.remove()
        user = self._user(who)
        return {r.tool_profile for r in
                UserAPIKey.query.filter(UserAPIKey.user_id == user.id)}

    def test_agent_id_mapping(self):
        from aot.tools.mcp_auth import agent_id_belongs_to as match
        self.assertTrue(match('user:alice', 'alice'))
        self.assertTrue(match('user:alice/Claude Desktop', 'alice'))
        self.assertFalse(match('user:alice2', 'alice'))
        self.assertFalse(match('user:alic', 'alice'))
        self.assertFalse(match('unauthenticated:alice', 'alice'))
        self.assertFalse(match('alice', 'alice'))
        self.assertFalse(match(None, 'alice'))
        self.assertFalse(match('user:', ''))

    def test_assigns_by_recent_configuration_use(self):
        from aot.tools import mcp_auth
        admin, editor, monitor = (
            (_PREFIX + n).lower() for n in ('Admin', 'Editor', 'Monitor'))
        for who in ('Admin', 'Admin', 'Editor', 'Monitor'):   # Admin 은 키 둘
            self._issue(who)
        self._null_all()
        self._audit('user:%s/Claude' % admin, 'create_function', 10)   # 설정·최근
        self._audit('user:%s' % editor, 'create_input', 120)           # 설정·오래됨
        self._audit('user:%s' % editor, 'operate_device', 5)           # 운영
        self._audit('user:%sx' % monitor, 'create_plot', 3)            # 다른 사람
        self._audit('unauthenticated:%s' % monitor, 'create_plot', 3)  # 자기 신고
        counts = mcp_auth.backfill_key_tool_profiles()
        self.assertEqual(self._profiles_of('Admin'), {CFG})
        self.assertEqual(self._profiles_of('Editor'), {OPS})
        self.assertEqual(self._profiles_of('Monitor'), {OPS})
        self.assertEqual(counts[CFG], 2)
        self.assertGreaterEqual(counts[OPS], 2)

    def test_service_account_keys_become_configuration(self):
        from aot.databases.models import UserAPIKey
        from aot.tools import mcp_auth
        service = mcp_auth.ensure_service_account()
        service_id = service.id
        service.issue_api_key('internal')
        self.db.session.commit()
        self._null_all()
        mcp_auth.backfill_key_tool_profiles()
        self.db.session.remove()
        values = {r.tool_profile for r in
                  UserAPIKey.query.filter(UserAPIKey.user_id == service_id)}
        self.assertEqual(values, {CFG})

    def test_is_idempotent_and_keeps_assigned_values(self):
        from aot.databases.models import UserAPIKey
        from aot.tools import mcp_auth
        self._issue('Editor', profile=CFG)             # 이미 배정된 키
        self._issue('Monitor', profile=OPS)
        UserAPIKey.query.filter(UserAPIKey.tool_profile == OPS).update(
            {UserAPIKey.tool_profile: None}, synchronize_session=False)
        self.db.session.commit()
        first = mcp_auth.backfill_key_tool_profiles()
        second = mcp_auth.backfill_key_tool_profiles()
        self.assertEqual(self._profiles_of('Editor'), {CFG})
        self.assertEqual(self._profiles_of('Monitor'), {OPS})
        self.assertGreaterEqual(first[OPS], 1)
        self.assertEqual(second, {OPS: 0, CFG: 0})


# ---------------------------------------------------------------------------
# 6. 화면 — 발급 선택과 키별 바꾸기
# ---------------------------------------------------------------------------

class TestKeyProfileRoutes(_UsersSubmitAppFixture):

    def setUp(self):
        super().setUp()
        from aot.databases.models import Role, User
        with self.app.app_context():
            role = Role()
            role.name = 'Viewer'
            role.edit_users = False
            role.view_settings = True
            self.db.session.add(role)
            self.db.session.commit()
            viewer = User()
            viewer.name = 'viewer'
            viewer.email = 'viewer@example.com'
            viewer.is_enabled = True
            viewer.is_approved = True
            viewer.role_id = role.id
            viewer.set_password('another correct horse')
            self.db.session.add(viewer)
            self.db.session.commit()
            self._viewer_login = viewer.get_id()

    def _post(self, data, login=None, fresh=True):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = login or self._login_id
            sess['_fresh'] = fresh
        body = {'user_id': self.user_unique_id}
        body.update(data)
        return self.client.post('/settings/users_submit', data=body).get_json()

    def _generate(self, profile=None):
        data = {'api_key_name': 'Client', 'api_key_scope': 'full',
                'user_generate_api_key': 'Generate'}
        if profile is not None:
            data['api_key_tool_profile'] = profile
        return self._post(data)

    def _change(self, key_uid, value, login=None, fresh=True):
        return self._post({'api_key_id': key_uid, 'api_key_profile_value': value,
                           'user_api_key_profile_save': '1'},
                          login=login, fresh=fresh)

    def test_new_key_defaults_to_operations(self):
        payload = self._generate()
        self.assertEqual(payload['data']['messages']['error'], [])
        self.assertEqual(self._active_keys()[0].tool_profile, OPS)

    def test_new_key_can_be_configuration(self):
        self._generate(CFG)
        self.assertEqual(self._active_keys()[0].tool_profile, CFG)

    def test_issue_api_key_narrows_unknown_values(self):
        from aot.databases.models import User
        with self.app.app_context():
            user = User.query.get(self.user_id)
            user.issue_api_key('a', 'full', tool_profile='everything')
            user.issue_api_key('b', 'full')
            self.db.session.commit()
        self.assertEqual({k.tool_profile for k in self._active_keys()}, {OPS})

    def test_change_profile_without_reissuing(self):
        from aot.databases.models import AuditLog
        self._generate()
        key = self._active_keys()[0]
        payload = self._change(key.unique_id, CFG)
        self.assertEqual(payload['data']['messages']['error'], [])
        after = self._active_keys()[0]
        self.assertEqual(after.tool_profile, CFG)
        self.assertEqual(after.key_hash, key.key_hash)      # 같은 키 그대로
        with self.app.app_context():
            row = AuditLog.query.filter(
                AuditLog.action == 'apikey.profile_change').one()
            self.assertIn(OPS, row.before_json)
            self.assertIn(CFG, row.after_json)

    def test_change_requires_user_edit_permission(self):
        self._generate()
        key = self._active_keys()[0]
        payload = self._change(key.unique_id, CFG, login=self._viewer_login)
        self.assertTrue(payload['data']['messages']['error'])
        self.assertEqual(self._active_keys()[0].tool_profile, OPS)

    def test_change_does_not_require_a_fresh_login(self):
        """키 폐기와 같은 문턱(D3) — 발급만 신선한 로그인을 요구한다."""
        self._generate()
        key = self._active_keys()[0]
        payload = self._change(key.unique_id, CFG, fresh=False)
        self.assertEqual(payload['data']['messages']['error'], [])
        self.assertEqual(self._active_keys()[0].tool_profile, CFG)
        issued = self._post({'api_key_name': 'Other', 'api_key_scope': 'full',
                             'user_generate_api_key': 'Generate'}, fresh=False)
        self.assertTrue(issued['data']['messages']['error'])
        self.assertEqual(len(self._active_keys()), 1)


    def test_change_rejects_unknown_values(self):
        self._generate()
        key = self._active_keys()[0]
        payload = self._change(key.unique_id, 'everything')
        self.assertTrue(payload['data']['messages']['error'])
        self.assertEqual(self._active_keys()[0].tool_profile, OPS)

    def test_template_offers_both_profiles(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                            'aot_flask', 'templates', 'settings',
                            'user_detail.html')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('api_key_tool_profile', src)
        self.assertIn('user_api_key_profile_save', src)
        self.assertIn("_('Operations + configuration')", src)
        # 줄마다 있는 select 에 name 을 주면 모든 줄의 값이 함께 전송된다.
        select = re.search(r'<select[^>]*data-profile-select[^>]*>', src).group(0)
        self.assertNotIn('name=', select)


class TestServiceAccountKeyScreen(_AppFixture):
    """서비스 계정의 키는 묶음과 무관하다 — 고르는 칸을 숨긴다(F5)."""

    def _render(self, user, service_account):
        from aot.aot_flask.forms import forms_settings
        # 앱 전역 context processor(대시보드·테마 행)는 이 검사와 무관해 건너뛴다.
        with self.app.test_request_context():
            return self.app.jinja_env.get_template(
                'settings/user_detail.html').render(
                user=user, themes=[],
                user_roles=[], user_api_keys=user.active_api_keys(),
                form_mod_user=forms_settings.UserMod(),
                service_account=service_account)

    def test_selector_hidden_for_service_account_keys(self):
        from aot.aot_flask import routes_settings
        self._issue('Editor')
        user = self._user('Editor')
        html = self._render(user, True)
        self.assertNotIn('data-profile-select', html)
        self.assertNotIn('api_key_tool_profile', html)
        self.assertIn('All tools (built-in AI)', html)
        html = self._render(user, False)
        self.assertIn('data-profile-select', html)
        self.assertIn('api_key_tool_profile', html)
        self.assertIn('service_account=is_service_account(user)',
                      inspect.getsource(routes_settings.settings_user_detail))


# ---------------------------------------------------------------------------
# 7. 마이그레이션 p6_75
# ---------------------------------------------------------------------------

_P6_75 = 'p6_75_api_key_tool_profile_20260924'


def _load_p6_75():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions',
                        _P6_75 + '.py')
    spec = importlib.util.spec_from_file_location(_P6_75, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_migration(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(mod, fn)()


def test_p6_75_upgrade_downgrade_is_idempotent(tmp_path):
    import sqlalchemy as sa
    from aot.databases.models import UserAPIKey

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as conn:
        # p6_74 시점의 모양 — 묶음 칸이 없다.
        conn.execute(sa.text(
            "CREATE TABLE user_api_key (id INTEGER PRIMARY KEY, "
            "unique_id VARCHAR(36) NOT NULL UNIQUE, user_id INTEGER NOT NULL, "
            "name VARCHAR(64), key_hash VARCHAR(64) NOT NULL UNIQUE, "
            "scope VARCHAR(16) NOT NULL DEFAULT 'full', created_at DATETIME, "
            "revoked_at DATETIME)"))
        conn.execute(sa.text(
            "INSERT INTO user_api_key (unique_id, user_id, key_hash) "
            "VALUES ('k1', 1, 'h1')"))

    def cols():
        return {c['name'] for c in sa.inspect(engine).get_columns('user_api_key')}

    base = cols()
    mod = _load_p6_75()
    for _ in range(2):
        _run_migration(mod, 'upgrade', engine)
        _run_migration(mod, 'upgrade', engine)          # 두 번 올려도 그대로
        assert cols() == base | {'tool_profile'}
        _run_migration(mod, 'downgrade', engine)
        _run_migration(mod, 'downgrade', engine)
        assert cols() == base
    _run_migration(mod, 'upgrade', engine)

    assert cols() == {c.name for c in UserAPIKey.__table__.columns}
    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT key_hash, scope, tool_profile FROM user_api_key")).one()
    # 옛 키는 살아 있고 묶음은 비어 있다 — 기동 때 백필이 채운다.
    assert tuple(row) == ('h1', 'full', None)


def test_p6_75_is_the_head_the_app_expects():
    from aot.config import ALEMBIC_VERSION
    mod = _load_p6_75()
    assert mod.revision == ALEMBIC_VERSION == _P6_75
    assert mod.down_revision == 'p6_74_mcp_audit_quality_20260923'
