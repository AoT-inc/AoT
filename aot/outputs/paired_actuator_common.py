# coding=utf-8
"""Shared definitions for paired-actuator outputs (open relay + close relay).

Two output modules implement the same "drive a position (0–100%) by running a
pair of relays for a calibrated travel time" contract:

  - ``actuator_paired``      — one actuator, its own dedicated open/close relays.
  - ``actuator_paired_bus``  — N actuators sharing one open/close relay pair,
                               each selected by its own selector relay.

Both expose ``output_types: ['value']`` and the same channel-option vocabulary
(``actuator_kind``, ``travel_time_open_sec``, ``move_step_pct``, …), so every
consumer — the environment coordinator's profile loader, the env-control
dispatch adapters, the geo 3-way actuator popup, the output form handler —
must treat them identically.

Those consumers used to test ``output_type == 'actuator_paired'`` as a bare
string literal in nine separate places. Adding a second module that way would
have meant nine more literals to keep in sync. They now test membership in
``PAIRED_ACTUATOR_OUTPUT_TYPES`` instead: a new paired-actuator module is
registered once, here.
"""
from flask_babel import lazy_gettext

# Output module unique names that implement the paired-actuator contract.
# Consumers must use this set rather than comparing against a single literal.
PAIRED_ACTUATOR_OUTPUT_TYPES = frozenset({
    'actuator_paired',
    'actuator_paired_bus',
})

ACTUATOR_KIND_OPTIONS = [
    ('side_vent',       lazy_gettext('Side Vent')),
    ('roof_vent',       lazy_gettext('Roof Vent')),
    ('thermal_curtain', lazy_gettext('Thermal Curtain')),
    ('shade_curtain',   lazy_gettext('Shade Curtain')),
    ('ball_valve',      lazy_gettext('Ball Valve')),
]

KIND_TO_PROFILE_KIND = {
    'side_vent':       'opening',
    'roof_vent':       'opening',
    'thermal_curtain': 'curtain',
    'shade_curtain':   'shade',
    'ball_valve':      'opening',
}


def is_paired_actuator(output_type):
    """True if the given Output.output_type implements the paired-actuator contract."""
    return output_type in PAIRED_ACTUATOR_OUTPUT_TYPES


# ---------------------------------------------------------------------------
# 밑단 on/off 다리 ↔ 짝 액추에이터 관계
# ---------------------------------------------------------------------------
#
# `output_open_id`/`output_close_id`/`selector_output_id` 는 짝 액추에이터가
# 자기 몫의 인터락(반대 릴레이를 먼저 끄고, 방향 전환 사이에 정지 시간을 둠)
# 을 적용하는 근거다. 하지만 그 인터락은 짝 액추에이터 드라이버 **안에서만**
# 걸린다 — 밑단 채널은 평범한 on/off 출력이라 출력 페이지·Conditional
# 액션·MCP `operate_device` 가 그 채널을 직접 켜면 아무도 막지 않는다
# (2026-09-25, actuator_paired.py/actuator_paired_bus.py 사용자 가이드 작성
# 중 발견 — `test_paired_actuator_leg_interlock_gap.py` 참조).
#
# 여기 있는 함수 둘은 그 관계를 **한 곳에서만** 읽는다 — 데몬 쪽 인터락 가드
# (`controller_output.py`)와 출력 페이지의 "짝 액추에이터가 사용 중" 표시
# (`routes_output.py`) 둘 다 이 파싱을 저마다 다시 구현하면, 언젠가 형식이
# 바뀔 때 한쪽만 따라가고 다른 쪽은 낡은 채로 남는다 — 이 파일 위쪽
# `PAIRED_ACTUATOR_OUTPUT_TYPES` 를 만든 것과 같은 이유다.

def parse_leg_ref(ref, channel_uid_to_number):
    """`output_open_id`/`output_close_id`/`selector_output_id` 값을
    `(output_id, channel_number)` 로 해석한다.

    저장 형식은 세 가지다 — 레거시 `'output_id'`(채널 0 취급),
    `'output_id,channel_uid'`(actuator_paired._parse_ref/actuator_paired_bus.
    parse_ref 와 같은 형식), 그리고 `select_channel` 폼이 읽을 때 만드는
    `{'device_id': ..., 'channel_id': ...}` dict.

    `channel_uid_to_number` 는 `OutputChannel.unique_id -> channel` 맵을
    **호출자가 준비해 넘긴다** — 여기서 DB 를 직접 조회하지 않아야 데몬
    프로세스(캐시된 스냅샷)와 Flask 프로세스(라우트가 이미 만들어 둔
    `output_channels_by_uid`) 양쪽에서 그대로 쓸 수 있다.
    """
    if not ref:
        return '', 0
    if isinstance(ref, dict):
        out_id = ref.get('device_id') or ''
        chan_uid = ref.get('channel_id') or ''
    elif isinstance(ref, str):
        if ',' in ref:
            out_id, _, chan_uid = ref.partition(',')
        else:
            out_id, chan_uid = ref, ''
    else:
        return '', 0
    if not out_id:
        return '', 0
    if not chan_uid:
        return out_id, 0
    return out_id, (channel_uid_to_number or {}).get(chan_uid, 0)


def paired_leg_relations(paired_channel_rows, channel_uid_to_number, output_names=None):
    """밑단 `(output_id, channel)` 다리마다, 그것을 쓰는 짝 액추에이터 목록.

    :param paired_channel_rows: `(owner_output_id, custom_options_dict)` 쌍의
        이터러블 — 짝 액추에이터 타입(Output.output_type 이
        `PAIRED_ACTUATOR_OUTPUT_TYPES` 에 속함) Output 이 소유한 OutputChannel
        행들의 `custom_options` 를 이미 파싱해 넘긴다.
    :param channel_uid_to_number: `parse_leg_ref` 로 그대로 넘기는 맵.
    :param output_names: `{owner_output_id: name}` — 표시용. 없으면 id 그대로.
    :returns: `{(output_id, channel): [{'owner_id', 'owner_name', 'leg', 'partners'}]}`.
        `leg` 는 `'open'`/`'close'`/`'selector'`. `partners` 는 이 다리를 켜기
        전에 먼저 꺼야 할 다른 `(output_id, channel)` 목록이다 — open/close
        는 서로가 서로의 partner, selector 는 **같은 버스(같은 open/close
        릴레이 쌍)를 공유하는 다른 selector 들**이 partner 다.
    """
    output_names = output_names or {}
    legs_by_owner = {}  # owner_id -> {'open': leg, 'close': leg, 'selector': leg}
    for owner_id, opts in paired_channel_rows:
        if not isinstance(opts, dict):
            continue
        slot = legs_by_owner.setdefault(owner_id, {})
        for kind, key in (('open', 'output_open_id'),
                         ('close', 'output_close_id'),
                         ('selector', 'selector_output_id')):
            leg = parse_leg_ref(opts.get(key), channel_uid_to_number)
            if leg[0]:
                slot[kind] = leg

    relations = {}
    # (open_leg, close_leg) -> [(owner_id, owner_name, selector_leg), ...] —
    # actuator_paired_bus 에서 여러 액추에이터가 같은 open/close 릴레이 쌍을
    # 공유하고 각자의 selector 로 구분된다. 그 "같은 버스" 를 셀렉터 사이의
    # 상호배제 그룹으로 쓴다.
    bus_selectors = {}
    for owner_id, legs in legs_by_owner.items():
        open_leg = legs.get('open')
        close_leg = legs.get('close')
        selector_leg = legs.get('selector')
        owner_name = output_names.get(owner_id, owner_id)

        if open_leg and close_leg:
            relations.setdefault(open_leg, []).append({
                'owner_id': owner_id, 'owner_name': owner_name,
                'leg': 'open', 'partners': [close_leg]})
            relations.setdefault(close_leg, []).append({
                'owner_id': owner_id, 'owner_name': owner_name,
                'leg': 'close', 'partners': [open_leg]})
        elif open_leg:
            relations.setdefault(open_leg, []).append({
                'owner_id': owner_id, 'owner_name': owner_name,
                'leg': 'open', 'partners': []})
        elif close_leg:
            relations.setdefault(close_leg, []).append({
                'owner_id': owner_id, 'owner_name': owner_name,
                'leg': 'close', 'partners': []})

        if selector_leg:
            bus_selectors.setdefault((open_leg, close_leg), []).append(
                (owner_id, owner_name, selector_leg))

    for _bus_key, entries in bus_selectors.items():
        siblings = [leg for (_oid, _name, leg) in entries]
        for owner_id, owner_name, leg in entries:
            partners = [sib for sib in siblings if sib != leg]
            relations.setdefault(leg, []).append({
                'owner_id': owner_id, 'owner_name': owner_name,
                'leg': 'selector', 'partners': partners})

    return relations


def fetch_paired_leg_relations():
    """`paired_leg_relations` 를 DB 에서 직접 읽어 구성한다 (데몬 쪽 전용).

    Flask 라우트는 이미 전체 Output/OutputChannel 을 한 번에 읽어 두므로
    `paired_leg_relations` 를 그 결과로 바로 부르면 되지만, 데몬의 인터락
    가드는 명령마다 자기 몫의 조회가 필요하다 — 그래서 이 얇은 래퍼가
    따로 있다. 호출 빈도가 명령 단위라 캐싱은 호출자(`controller_output.py`)
    책임으로 남긴다.
    """
    from aot.databases.models import Output, OutputChannel
    from aot.utils.database import db_retrieve_table_daemon
    import json as _json

    outputs = db_retrieve_table_daemon(Output, entry='all') or []
    paired_ids = {o.unique_id for o in outputs
                 if o.output_type in PAIRED_ACTUATOR_OUTPUT_TYPES}
    if not paired_ids:
        return {}

    channels = db_retrieve_table_daemon(OutputChannel, entry='all') or []
    channel_uid_to_number = {c.unique_id: c.channel for c in channels}

    paired_channel_rows = []
    for ch in channels:
        if ch.output_id not in paired_ids or not ch.custom_options:
            continue
        try:
            opts = _json.loads(ch.custom_options)
        except Exception:
            continue
        paired_channel_rows.append((ch.output_id, opts))

    return paired_leg_relations(paired_channel_rows, channel_uid_to_number)
