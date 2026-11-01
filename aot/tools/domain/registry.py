# -*- coding: utf-8 -*-
"""operation 명부 — 설계 docs/design/mcp-domain-surface.md §3-2.

명부 한 줄(`Op`)이 도메인 도구의 operation 하나다. 실행은 언제나 안쪽 도구
(`inner`)를 지금 실행층(`_execute_tool`)으로 부르는 것이고, 승인·권한·그룹
스코프·감사는 안쪽 도구 이름으로 일어난다. 그래서 명부에는 **승인 칸이 없다** —
승인 요구는 안쪽 도구에서 물려받으며(`approval_of`), 명부가 낮출 수 없다.

데이터(`OPS`)는 `registry_data.py` 에 있다. 형식 검사와 지금 도구와의 대조는
`contract.py` 가 하고, 실패하면 쓰기 operation 이 켜지지 않는다(fail-closed).
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

#: 도메인 도구 — 설계 §4. 읽기 8 · 쓰기 6.
READ_TOOLS = ('overview', 'measure', 'weather', 'find', 'detail', 'records',
              'screen_view', 'help')
WRITE_TOOLS = ('control', 'record', 'cultivate', 'configure', 'screen', 'remove')
#: 자료를 지우는 도구 — 이것만 MCP `destructiveHint: true` 다(2026-10-14 사용자 결정).
#: claude.ai 는 표시로 허락 창을 정해 파괴적인 도구는 늘 묻는다. 지우기를 한 도구에 모아
#: 나머지 쓰기 도구에 '항상 허용' 이 먹게 한다. 지우는 operation 은 여기에만 둔다(계약 검사).
DESTRUCTIVE_TOOLS = ('remove',)
DOMAIN_TOOLS = READ_TOOLS + WRITE_TOOLS

#: 대상 종류 — 설계 §2-1. `none` 은 "대상 없이 부를 수 있다".
KINDS = ('map', 'site', 'zone', 'facility', 'plot', 'input', 'output',
         'device', 'function', 'program', 'note', 'notice', 'schedule',
         'widget', 'dashboard', 'tab', 'shape', 'gis_layer', 'ai_agent',
         'archive', 'journal', 'confirmation', 'none')
PLACE_KINDS = ('map', 'site', 'zone', 'facility', 'plot')
#: id 로만 가리키는 종류 — 대상 해석기(장소·장치·화면)가 모르는 기록·설정 행이다. 이 종류를
#: 하나만 받는 operation 에 해석기가 못 찾은 값이 오면 그 종류의 id 로 안쪽 도구에 넘긴다 —
#: 있는지는 안쪽 도구가 본다(2026-10-14 사용자 시험: 승인 번호를 대상으로 못 찾아 승인할
#: 길이 없었다. 메모·공지·일정 고치기·지우기 22개 operation 이 같은 상태였다).
ID_ONLY_KINDS = ('note', 'notice', 'schedule', 'journal', 'archive', 'confirmation',
                 'program', 'shape', 'gis_layer', 'ai_agent')

#: 효과 종류 — 설계 §3-2. 읽기 도구의 operation 은 모두 'read'.
EFFECTS = ('read', 'record', 'config', 'automation', 'physical', 'permission',
           'screen')

#: 공통 인자 어휘 — 설계 §3. operation 고유 인자는 `extra_args` 에 이유와 함께.
VOCAB = ('op', 'target', 'period', 'at', 'measurement', 'value', 'query',
         'limit', 'fields')


@dataclass(frozen=True)
class Op:
    tool: str                    # 도메인 도구(DOMAIN_TOOLS)
    op: str                      # operation 이름(도구 안에서 고유, 소문자_밑줄)
    use: str                     # "언제 쓰나" 한 줄(영어, 90자 안) — 목록에 실린다
    inner: Dict[str, str]        # 대상 종류 → 안쪽 도구 이름. 대상 없이도 되면 'none' 키
    effect: str                  # EFFECTS
    #: 공통 어휘·고유 인자 → 안쪽 도구 인자 이름. 'target' 은 종류별로 다를 수
    #: 있어 `target_arg` 로 따로 둔다.
    args: Dict[str, str] = field(default_factory=dict)
    #: 대상 종류 → 그 종류일 때 해석된 id 를 넣을 안쪽 인자 이름
    target_arg: Dict[str, str] = field(default_factory=dict)
    #: 공통 어휘에 없는 인자 → 이유. 안쪽 인자 이름 그대로 넘긴다.
    extra_args: Dict[str, str] = field(default_factory=dict)
    #: `args` 에 공통 어휘가 아닌 이름을 쓸 때(안쪽 이름이 도메인의 `op`·`target`
    #: 과 겹칠 때) 그 이유. 예: 화면 조작의 지도 동작 `op` → `map_op`.
    renamed: Dict[str, str] = field(default_factory=dict)
    #: 쓰기에서 대상 여럿을 한 번에 받는가(설계 §2-3). 기본은 받지 않는다.
    expand_write: bool = False
    #: 쓰기에서 대상 목록을 받아 대상마다 같은 안쪽 호출을 따로 거는가 — 안쪽 도구가 목록 인자를
    #: 받지 못하는 물리 제어(device_set). 승인 대기는 대상마다 하나씩 생기되 응답은 하나다: 대상을
    #: 풀어 되읽는 줄 하나, 사용자의 승인 한 번, 승인 호출 한 번(`control.confirm` 의 confirmation_ids).
    #: 그릇(구역·시설)은 여전히 펼치지 않는다 — 대상은 호출자가 이름·id 로 하나하나 지목한다(설계 §2-3).
    fan_write: bool = False
    #: 읽기에서 그릇을 펼칠 때 상한(설계 §2-3). fan_write 에서는 한 번에 받는 대상 수의 상한.
    max_targets: int = 5
    #: 응답 상한(추정 토큰, 설계 §5).
    budget: int = 2500
    #: 목록에 싣는 필수 인자(쓰기는 설계 §3-2 대로 위험과 함께 싣는다).
    required: Tuple[str, ...] = ()
    #: 필수는 아니지만 스키마에 싣는 고유 인자 — 동작에 꼭 필요한 것(화면 조작의
    #: action·page, 고치기의 바꿀 내용). 모델은 스키마에 없는 인자를 넣지 않는다
    #: (2026-10-14 사용자 시험: action 이 없어 화면 이동이 끝내 안 됐다).
    shown: Tuple[str, ...] = ()
    #: 대상 종류 → 안쪽 인자 기본값(호출이 그 인자를 주지 않았을 때만). 화면 조작에
    #: 대상만 주면 종류로 동작을 정한다 — 장소는 지도 창, 위젯은 강조, 대시보드는 이동
    #: (2026-10-14 사용자: 보여 달라고 해도 텍스트로만 답했다 — action·page·kind 를
    #: 맞춰야 하는 호출을 모델이 포기했다).
    defaults_by_kind: Dict[str, Dict[str, str]] = field(default_factory=dict)
    #: 안쪽 도구가 기간 인자를 받지 못할 때, 틀이 `period` 로 거를 결과 칸
    #: (`rows_key` 목록의 각 행에서 시각이 든 칸). 예: 일정의 'when'.
    period_field: str = ''
    rows_key: str = ''
    #: 안쪽 도구가 기간 인자를 받을 때 그 모양(vocab.PERIOD_FORMS). `args` 에
    #: 'period' 가 있으면 반드시 있어야 한다 — 낱말을 그대로 넘기지 않는다(계약 검사).
    period_form: str = ''
    #: 인자 값이 받는 대상 종류를 정한다 — {인자: {값: 받는 종류들}}. 화면 조작은 action
    #: 마다 받는 대상이 다르다(navigate = 대시보드·페이지 탭, open_map_item = 지도 위의 것,
    #: modal_tab = 열린 지도 창의 탭 이름이라 틀이 푸는 대상이 아니다). 표에 없는 값이면
    #: 좁히지 않는다. 종류가 비면 그 값은 대상을 받지 않고, 대상 칸 이름(`tab` …)은 안쪽
    #: 도구가 그대로 읽는 글자다(2026-10-14 사용자 시험: modal_tab '영양' 이 입력 탭으로
    #: 풀려 그 id 가 창 탭 이름 칸에 들어갔다).
    kinds_by_arg: Dict[str, Dict[str, Tuple[str, ...]]] = field(default_factory=dict)

    @property
    def inner_tools(self):
        return tuple(sorted(set(self.inner.values())))

    @property
    def accepts(self):
        return tuple(k for k in self.inner)


def by_tool(ops):
    out = {}
    for o in ops:
        out.setdefault(o.tool, []).append(o)
    return out


def find_op(ops, tool, op) -> Optional[Op]:
    for o in ops:
        if o.tool == tool and o.op == op:
            return o
    return None
