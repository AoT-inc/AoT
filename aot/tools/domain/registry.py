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
         'journal', 'confirmation', 'none')
PLACE_KINDS = ('map', 'site', 'zone', 'facility', 'plot')
#: id 로만 가리키는 종류 — 대상 해석기(장소·장치·화면)가 모르는 기록·설정 행이다. 이 종류를
#: 하나만 받는 operation 에 해석기가 못 찾은 값이 오면 그 종류의 id 로 안쪽 도구에 넘긴다 —
#: 있는지는 안쪽 도구가 본다(2026-10-14 사용자 시험: 승인 번호를 대상으로 못 찾아 승인할
#: 길이 없었다. 메모·공지·일정 고치기·지우기 22개 operation 이 같은 상태였다).
ID_ONLY_KINDS = ('note', 'notice', 'schedule', 'journal', 'confirmation',
                 'program', 'shape', 'gis_layer', 'ai_agent')

#: 효과 종류 — 설계 §3-2. 읽기 도구의 operation 은 모두 'read'.
EFFECTS = ('read', 'record', 'config', 'automation', 'physical', 'permission',
           'screen')

#: 공통 인자 어휘 — 설계 §3. operation 고유 인자는 `extra_args` 에 이유와 함께.
VOCAB = ('op', 'target', 'period', 'at', 'measurement', 'value', 'query',
         'limit', 'fields', 'text', 'title', 'duration', 'state', 'offset', 'samples')
#: 접두사로 뜻이 정해진 공통 어휘 — `include_<x>` 는 덧붙이는 행, `only_<x>` 는 한정(재설계 §2-1 규칙 6).
VOCAB_PREFIXES = ('include_', 'only_')


def is_vocab(word):
    return word in VOCAB or str(word).startswith(VOCAB_PREFIXES)


@dataclass(frozen=True)
class Pick:
    """같은 종류 안에서 **인자 값**으로 안쪽 도구를 고르는 훅(재설계 PR 6) — `Op.pick_by_arg`.

    `Op.inner` 는 "대상 종류 → 안쪽 도구"만 안다. 함수 켜기·끄기(`state`)·구획 단계 다섯 동작(`action`)·일정 하나/여럿
    (`entries` 의 유무)은 같은 종류에서 값이 안쪽 도구를 정한다. 값마다 **완전한 `Op`**(안쪽 도구·인자 이름·필수·여럿 받기)를
    지녀, 고른 뒤의 실행은 그 가지 Op 하나로 평소처럼 돈다 — 가지마다 필수 인자와 받는 인자가 따로라 어느 동작에 안 맞는
    인자는 `unknown_argument` 로 거절된다. 승인·권한·감사는 고른 안쪽 도구 이름으로 일어난다(계약 검사: 한 op 의 모든 가지가
    같은 승인 요구·같은 효과, 쓰기 도구는 가지 전체에서 한 번만 매핑).

    `branches` 의 키는 정규화한 값(`normalize` 로 소문자 글자 또는 'on'/'off'), `'*'` = 인자가 어떤 값으로든 왔다,
    `''` = 인자가 안 왔다. `consume`=True 면 고른 인자는 안쪽에 넘기지 않는다(`state`·`action` — 안쪽 도구가 모르는 인자)."""
    arg: str
    branches: Dict[str, 'Op']
    consume: bool = True
    normalize: str = ''             # '' = 소문자 글자, 'onoff' = on|off
    #: 값이 없을 때 합친 op 자신이 가지다 — 대상 종류(`kind`)를 말하면 그 종류로 좁히고, 안 말하면 평소처럼 대상에서 종류를 알아낸다
    #: (대상이 모호하면 되묻는다). 지우기·고치기의 `kind`.
    infer: bool = False
    #: 값의 다른 말 → 가지 키(예 'gis_input' → 'gis_layer').
    synonyms: Dict[str, str] = field(default_factory=dict)


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
    #: 도메인 층 응답 줄이기·쪽 나누기(slim.SLIMMERS 의 이름). 있으면 `args` 의 fields·limit·offset 은 안쪽 도구로
    #: 넘기지 않고 이 층이 처리한다 — 안쪽 도구(인앱 AI 가 쓴다)는 그대로 두고 도메인 표면의 응답만 줄인다.
    slim: str = ''
    #: 날짜 범위 두 칸을 받는 안쪽 도구(date_from/date_to · start/end)를 `period`(FROM/TO) 하나로 부르게 한다 —
    #: ('첫 칸', '끝 칸') 안쪽 인자 이름. 'FROM/' 은 끝 없이, '/TO' 는 시작 없이. 시각 창은 이 낱말이 아니라 window_start/window_end.
    period_pair: Tuple[str, str] = ()
    #: 값으로 안쪽 도구를 고르는 훅. 있으면 이 Op 는 **목록용 합집합**이고 실행은 고른 가지 Op 가 한다(`merge_branches`).
    pick_by_arg: Optional[Pick] = None
    #: 대상 없이 도는 목록 op 가 장소 대상을 받을 때 행을 거르는 칸 — 행의 이 칸이 그 장소(또는 안의 시설)의 id 와 같은 행만 남긴다.
    #: 비어 있으면 행의 장치 id 칸으로 거르고, 그런 칸이 없는 목록은 거르지 못했다고 응답에 적는다(조용히 전체를 주지 않는다).
    place_filter: str = ''
    #: help(target='tool.op') 응답에만 싣는 추가 칸 — 형식·예시처럼 **정의**는 목록 설명이 아니라
    #: help 로 간다(표면 규칙). tools/list 고정비에는 들어가지 않는다. {칸이름: 값} 그대로 help 카드에 병합.
    help_extra: Dict[str, object] = field(default_factory=dict)

    @property
    def inner_tools(self):
        names = set(self.inner.values())
        if self.pick_by_arg is not None:           # 값으로 고르는 가지의 안쪽 도구까지(목록·help·권한 판정용 합집합)
            for b in self.pick_by_arg.branches.values():
                names |= set(b.inner.values())
        return tuple(sorted(names))

    @property
    def accepts(self):
        return tuple(k for k in self.inner)


def merge_branches(tool, op, use, arg, branches, *, arg_why='', arg_word=False, consume=True,
                   normalize='', required=(), shown=(), extra_why=None, infer=False, synonyms=None, effect=''):
    """가지 Op 들의 합집합으로 목록용 Op 를 만든다 — 인자 이름·뜻이 가지마다 어긋나지 않게 손으로 쓰지 않는다.

    branches: {값: Op(...)} — 가지 Op 의 `tool`·`op` 는 합친 것과 같게 맞춘다(use·effect 는 가지 것 — 효과가 다르면 `effect=` 로 표시할 하나를 고른다).
    arg_word: 고르는 인자가 공통 어휘(`state`)면 True — `args` 에 올라 스키마 어휘로 실린다. 아니면 고유 인자(`action`)라
    `arg_why` 와 함께 `extra_args` 에 올라 필수로 실린다.
    required: 합친 Op 의 필수(대상 포함). 가지마다의 필수는 가지 Op 가 갖는다.
    infer / synonyms: `Pick` 참고. effect: 가지의 효과가 서로 다를 때(지우기: 기록·설정) 목록에 표시할 하나 — 가지 효과 중 하나여야 한다
    (계약 검사). 비우면 첫 가지의 것.
    extra_why: 합집합 인자의 뜻을 가지 것 대신 이 글로(같은 이름이 가지마다 뜻이 조금 다를 때 — 먼저 나온 가지 것이 남는 것을 막는다)."""
    leaves = [b for b in branches.values()]
    inner, target_arg, args, extra, shown_l = {}, {}, {}, {}, []
    for b in leaves:
        for kind, name in b.inner.items():
            inner.setdefault(kind, name)
        for kind, name in b.target_arg.items():
            target_arg.setdefault(kind, name)
        for word, name in b.args.items():
            args.setdefault(word, name)
        for name, why in b.extra_args.items():
            extra.setdefault(name, why)
        for name in b.shown:
            if name not in shown_l:
                shown_l.append(name)
    if arg_word:
        args.setdefault(arg, arg)
    else:
        extra.setdefault(arg, arg_why)
    for name, why in (extra_why or {}).items():
        if name in extra:
            extra[name] = why
    shown_l = [x for x in shown_l if x in extra]
    for x in shown:
        if x in extra and x not in shown_l:
            shown_l.append(x)
    fixed = [dict(b.__dict__, tool=tool, op=op) for b in leaves]       # 가지의 use 는 그대로(help 의 값별 표에 실린다)
    leaf_map = {k: Op(**dict(f, pick_by_arg=None)) for k, f in zip(branches, fixed)}
    return Op(tool=tool, op=op, use=use, inner=inner, effect=effect or leaves[0].effect, args=args,
              target_arg=target_arg, extra_args=extra, expand_write=False,
              max_targets=max(b.max_targets for b in leaves),
              required=tuple(required), shown=tuple(shown_l),
              pick_by_arg=Pick(arg, leaf_map, consume, normalize, infer, dict(synonyms or {})))


def leaves(o):
    """실행·검사 단위의 Op 들 — 훅이 없으면 자기 하나, 있으면 가지마다 (값, 가지 Op)."""
    if o.pick_by_arg is None:
        return [(None, o)]
    return list(o.pick_by_arg.branches.items())


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
