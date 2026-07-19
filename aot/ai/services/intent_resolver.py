# coding=utf-8
"""
Deterministic intent interceptors — architecture-improvement Phase 2.

Extracted out of the ai_agent_service.py god-object (was ~400 lines of
detector/proposal-builder code mixed into a single 4000-line class). A CONTROL
or FUNCTION_CREATE request first passes through these interceptors so the
routine, unambiguous cases resolve deterministically (no LLM hallucination of
a device grab-bag or a stalled function_type) — only the genuinely ambiguous
cases fall through to the LLM-driven pipeline.

Single entry point: `resolve(command_text, thread_id, page_context, intent_override)`.
Returns a dispatch-ready result dict (already tagged `_intercept`) or None to
fall through. Callers should no longer call the individual detectors directly.

i18n: keyword tables below are the DATA a new locale extends — "new intent =
add a keyword", not new code. They intentionally mix Korean and English tokens
in the same tuple (both languages hit the same deterministic path); a future
locale is a new tuple entry, not a new `if`. See `_FUNCTION_TYPE_KEYWORDS`
`strong` flag below for why literal-word matching alone was insufficient for
English ("create a valve sequence for zone 3" never says the word "function").
"""
import json
import logging
import re

from aot.ai.services.ai_context_service import AIContextService

logger = logging.getLogger(__name__)


# =============================================================================
# Keyword data — the externalized glossary. Extend these tuples for a new
# language/phrasing; the predicate functions below never need to change.
# =============================================================================

# "Turn them all off/on" style references to the just-controlled devices.
_RECENT_REF_MARKERS = (
    '모두', '전부', '다 꺼', '다 켜', '다꺼', '다켜', '전체', '그것들', '그거', '그것',
    '방금', '위 장치', '방금 그', 'them', 'those', 'everything', 'all of', 'all off', 'all on',
)

# Scope qualifiers that turn "모두 꺼줘" into a FRESH scoped query rather than a
# reference to the just-controlled set: a site/zone location word, an explicit
# on/off-state filter, or a numeric location token like "3포장" / "1-4구역".
_SCOPE_QUALIFIER_RE = re.compile(
    r'(\d+\s*포장|\d+\s*[-–]\s*\d+\s*구역|포장|구역|사이트|site|zone|'
    r'켜져|꺼져|작동\s*중|가동\s*중|정지\s*중|on\s*인|off\s*인|현재\s*켜|현재\s*꺼)',
    re.IGNORECASE,
)

# LOCATION-only qualifier (no state words): the user named a place, so the
# control target is knowable deterministically. "1포장", "1-3구역", "site 2".
_LOCATION_QUALIFIER_RE = re.compile(
    r'(\d+\s*포장|\d+\s*[-–]\s*\d+\s*구역|\d+\s*[-–]\s*\d+|포장|구역|사이트|site|zone)',
    re.IGNORECASE,
)

# Device-type keywords for a vague area control ("밸브 다 열어줘"). Maps a keyword
# to (english_kind_key, output_type_hints) so the proposal can name the kind and
# the handler can filter the zone's devices to that type.
_DEVICE_KIND_KEYWORDS = (
    ('밸브', 'valves', ('valve', '밸브')),
    ('valve', 'valves', ('valve', '밸브')),
    ('펌프', 'pumps', ('pump', '펌프')),
    ('pump', 'pumps', ('pump', '펌프')),
    ('모터', 'motors', ('motor', '모터')),
    ('조명', 'lights', ('light', 'led', '조명', '전등')),
    ('전등', 'lights', ('light', 'led', '조명', '전등')),
    ('light', 'lights', ('light', 'led', '조명', '전등')),
)
_VAGUE_CTRL_VERBS = ('열어', '열', '개방', '켜', '작동', '가동', '닫아', '닫', '꺼', '끄',
                     '정지', 'open', 'close', 'on', 'off', 'start', 'stop', 'turn')
# A specifically-named device ("밸브3", "v141") is NOT a vague area command.
_SPECIFIC_DEVICE_RE = re.compile(r'(밸브|valve|펌프|pump|모터|motor)\s*\d|\bv\d{2,}\b', re.IGNORECASE)

# Natural-language → function_type. Ordered; first keyword match wins. Covers the
# registered FUNCTION_INFO types a user would ask for by description.
#
# `strong=True` keywords unambiguously name an AUTOMATION FUNCTION concept
# (a sequence/conditional/PID/scheduled trigger isn't anything else) — a create
# verb + a strong keyword is function-create even without the literal word
# "함수"/"function". This is the i18n fix: English requests routinely omit the
# word "function" ("create a valve sequence for zone 3"), and requiring it
# left English function-create requests un-intercepted (falling through to the
# LLM, which meta-stalls — see project_ai_meta_stall memory).
# `strong=False` keywords (output/pwm/edge) are ambiguous with entity-CRUD
# vocabulary ("출력 만들어줘" = create an Output device, not a function) — those
# still require the literal "함수"/"function" word to avoid a false positive.
_FUNCTION_TYPE_KEYWORDS = (
    (('시퀀스', '순차', 'sequence', '차례'), 'trigger_sequence', '시퀀스', True),
    (('조건', 'conditional', '컨디셔널'), 'conditional_conditional', '조건', True),
    (('pid',), 'pid_pid', 'PID', True),
    (('일출', '일몰', 'sunrise', 'sunset'), 'trigger_sunrise_sunset', '일출/일몰', True),
    (('매일', 'daily', '특정시각', '특정 시각'), 'trigger_timer_daily_time_point', '매일 지정시각', True),
    (('타이머', '주기', 'duration', 'timer', '일정시간', '일정 시간'), 'trigger_timer_duration', '타이머', True),
    (('pwm',), 'trigger_output_pwm', 'PWM', False),
    (('엣지', 'edge'), 'trigger_edge', '엣지', False),
    (('출력', 'output'), 'trigger_output', '출력 트리거', False),
)
_FUNCTION_CREATE_VERBS = ('만들', '생성', '추가', '만들어', '새로', 'create', 'add', 'new')


# =============================================================================
# Pure predicates — no DB, no LLM. Directly unit-testable (see
# aot/tests/ai_eval/golden_set.py deterministic_control / function_create).
# =============================================================================

def is_recent_control_reference(command):
    """True if the command is a bare 'turn them all off/on' reference to the just-
    controlled devices (a control verb + an 'all/them/those' word) — and carries
    NO explicit scope of its own. A qualifier like '3포장' or '켜져있는' makes it a
    fresh scoped query (resolve by location/state), NOT a recent-set reference, so
    we must NOT blindly reuse the previously-controlled devices."""
    if not command:
        return False
    low = command.lower()
    has_ref = any(m in command or m.lower() in low for m in _RECENT_REF_MARKERS)
    has_ctrl = any(k in command or k in low for k in ('꺼', '끄', '켜', '작동', '가동', '정지', 'off', 'on', 'stop', 'start', 'turn'))
    if not (has_ref and has_ctrl):
        return False
    # A location/state qualifier means the user re-scoped -> not a recent reference.
    if _SCOPE_QUALIFIER_RE.search(command):
        return False
    return True


def is_vague_device_control(command):
    """True if the command is a control ("열어/꺼/turn on") of a DEVICE TYPE
    ("밸브"/"장치") with NO explicit location and NO specific device named — i.e.
    it only makes sense relative to what the user is currently looking at on the
    map. e.g. "밸브 다 열어줘", "장치 꺼줘". Used with the map viewport to scope the
    command to the on-screen site/zone."""
    if not command:
        return False
    low = command.lower()
    has_ctrl = any(v in command or v in low for v in _VAGUE_CTRL_VERBS)
    if not has_ctrl:
        return False
    has_kind = ('장치' in command or 'device' in low
                or any(k in command or k in low for k, _, _ in _DEVICE_KIND_KEYWORDS))
    if not has_kind:
        return False
    if _SCOPE_QUALIFIER_RE.search(command):
        return False  # user named a location -> not viewport-relative
    if _SPECIFIC_DEVICE_RE.search(command):
        return False  # user named a specific device -> not "all in the area"
    return True


def is_device_control(command):
    """True if the command is an on/off control of one or more DEVICES-BY-TYPE (a
    control verb + a device word / quantifier), NOT a single specifically-named
    device. Used with a location qualifier to decide a deterministic
    location-scoped (batch) proposal — a specifically-named device ("밸브 3-1",
    "v141") must fall through to normal single-device resolution instead, since
    _LOCATION_QUALIFIER_RE's bare digit-dash-digit alternative would otherwise
    misread the device's own number as a zone token and batch-propose the whole
    zone."""
    if not command:
        return False
    low = command.lower()
    if not any(v in command or v in low for v in _VAGUE_CTRL_VERBS):
        return False
    if _SPECIFIC_DEVICE_RE.search(command):
        return False  # user named a specific device -> not "all in the area"
    return ('장치' in command or 'device' in low
            or any(q in command or q in low for q in ('모두', '전부', '전체', '다 ', 'all'))
            or any(k in command or k in low for k, _, _ in _DEVICE_KIND_KEYWORDS))


def command_has_location(command):
    """True if the command explicitly names a site/zone location."""
    return bool(command and _LOCATION_QUALIFIER_RE.search(command))


def kind_for_command(command):
    """Return (english_kind_key, output_type_hints) for the device type named in
    the command, or ('devices', None) when only a generic word ("장치") is used."""
    low = (command or '').lower()
    for kw, key, hints in _DEVICE_KIND_KEYWORDS:
        if kw in (command or '') or kw in low:
            return key, hints
    return 'devices', None


def is_function_create_request(command):
    """True if the command asks to CREATE a function ("... 함수 만들어줘", or
    "create a valve sequence" — see _FUNCTION_TYPE_KEYWORDS `strong` docstring
    for why a literal "함수"/"function" word isn't required for every phrasing)."""
    if not command:
        return False
    low = command.lower()
    has_verb = any(v in command or v in low for v in _FUNCTION_CREATE_VERBS)
    if not has_verb:
        return False
    if '함수' in command or 'function' in low:
        return True
    return any(k in command or k in low
               for kws, _, _, strong in _FUNCTION_TYPE_KEYWORDS if strong
               for k in kws)


def infer_function_type(command):
    """Map a natural-language function request → (function_type, label), or
    (None, None) when the type can't be determined from keywords."""
    low = (command or '').lower()
    for kws, ftype, label, _strong in _FUNCTION_TYPE_KEYWORDS:
        if any(k in (command or '') or k in low for k in kws):
            return ftype, label
    return None, None


# =============================================================================
# Conversation memory — devices controlled in this thread's recent turns.
# =============================================================================

def recent_controlled_devices(thread_id, limit=6):
    """Devices controlled in the recent conversation (from the control actions
    recorded on this thread's recent AI turns). Lets a follow-up like "모두 꺼줘"
    / "그거 꺼" / "turn them off" resolve to what was JUST acted on, instead of
    defaulting to some generic 'all outputs' set. Returns [{name, device_id}]."""
    if not thread_id:
        return []
    try:
        from aot.databases.models import AIHistory, Output
        _CTRL = {'operate_device', 'output_on', 'output_off', 'set_output', 'control_output', 'output'}
        rows = (AIHistory.query.filter_by(thread_id=thread_id, message_type='ai')
                .order_by(AIHistory.id.desc()).limit(limit).all())
        seen, out = set(), []
        for h in rows:
            try:
                acts = json.loads(h.actions_json or '[]')
            except Exception:
                acts = []
            for a in acts:
                p = a.get('params', {}) or {}
                args = p.get('arguments', {}) if isinstance(p.get('arguments'), dict) else {}
                tn = (p.get('tool_name') or args.get('tool_name')
                      or a.get('tool_name') or a.get('action_type'))
                if tn in _CTRL:
                    did = p.get('device_id') or args.get('device_id') or a.get('target_id')
                    if did and did not in seen:
                        o = Output.query.filter_by(unique_id=did).first()
                        if o:
                            seen.add(did)
                            out.append({"name": o.name, "device_id": did})
        return out
    except Exception as e:
        logger.debug(f"[RecentControlled] failed: {e}")
        return []


def _get_dispatch_agent():
    """Local import to avoid a module-level circular import with
    ai_agent_service (which imports this module)."""
    from aot.ai.services.ai_agent_service import AIAgentService
    from aot.databases.models.ai import AIAgent
    wk = (AIAgentService.get_cached_agent('worker')
          or AIAgentService.get_cached_agent('executor')
          or AIAgent.query.filter_by(is_activated=True).first())
    return AIAgentService, (wk.unique_id if wk else 'system')


# =============================================================================
# Proposal builders — resolve devices deterministically and dispatch a
# human-approval-gated proposal. Each returns a dispatch-ready result dict, or
# None to fall through to the LLM-driven pipeline (nothing resolved).
# =============================================================================

def _recent_control_proposal(command_text, thread_id):
    recent = recent_controlled_devices(thread_id)
    if not recent:
        return None
    AIAgentService, agent_id = _get_dispatch_agent()
    off = any(k in command_text for k in ('꺼', '끄', '정지', 'off', 'stop'))
    acts = [{
        'tool_name': 'operate_device',
        'params': {'device_id': d['device_id'], 'state': (not off),
                   'display_summary': f"{d['name']} {'OFF' if off else 'ON'}"},
    } for d in recent]
    ins = f"방금 제어한 {len(recent)}개 장치({', '.join(d['name'] for d in recent)})를 {'끄' if off else '켜'}도록 준비했습니다."
    disp = AIAgentService._dispatch_actions(
        agent_id=agent_id, goal=command_text,
        insight=ins, actions=acts, thread_id=thread_id, message_type='ai',
        metadata={'intent': 'CONTROL', 'recent_control_ref': True})
    logger.info(f"[RecentControl] '{command_text}' → recent devices {[d['name'] for d in recent]}")
    return {
        "status": "success", "insight": ins, "intent": "CONTROL",
        "proposed_actions": disp['proposed'],
        "immediate_results": disp.get('immediate_results', []),
        "draft_job_ids": disp.get('draft_ids', []),
        "history_id": disp['history_id'],
        "_intercept": "recent_control",
    }


def propose_map_scoped_control(raw_cmd, mapctx, thread_id):
    """Build a control PROPOSAL scoped to the site/zone under the map viewport.

    Resolves the viewport center → site/zone by spatial containment, collects the
    devices located there (optionally filtered to the named device type), and
    proposes turning them on/off — naming the location so the user confirms
    exactly what's being controlled. Returns the proposal dict, or None to fall
    through to the normal pipeline (no location resolved / no devices there)."""
    from aot.databases.models import Output
    loc = AIContextService.resolve_point_to_location(mapctx.get('lat'), mapctx.get('lng'))
    zone, site = loc.get('zone'), loc.get('site')
    if not zone and not site:
        return None

    zmap = AIContextService.get_device_zone_map()  # {device_id: zone_name}
    target_zone = zone  # scope to the most-specific zone when available
    dids = [d for d, z in zmap.items() if z == target_zone] if target_zone else []
    if not dids:
        return None

    outs = [o for o in (Output.query.filter_by(unique_id=d).first() for d in dids) if o]
    return build_location_proposal(outs, site, zone, raw_cmd, thread_id, 'map')


def propose_location_scoped_control(raw_cmd, thread_id):
    """Build a control PROPOSAL for a command that NAMES a location
    ("1포장 1-3구역 모든 장치 켜줘"). Resolves the devices DETERMINISTICALLY via the
    location-aware search (zone/site intersection), so the LLM never freelances a
    grab-bag of unrelated / previously-mentioned devices. Returns the proposal, or
    None to fall through when nothing resolves."""
    from aot.databases.models import Output
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    res = AoTDataToolService.search_devices(raw_cmd) or {}
    rows = [r for r in res.get('results', []) if r.get('type') == 'output']
    if not rows:
        return None
    outs, zones = [], []
    for r in rows:
        o = Output.query.filter_by(unique_id=r['id']).first()
        if o:
            outs.append(o)
            zones.append(r.get('zone'))
    if not outs:
        return None
    # Location label: the shared zone (if all devices are in one) + its site.
    uniq_zones = {z for z in zones if z}
    zone = next(iter(uniq_zones)) if len(uniq_zones) == 1 else None
    site = AIContextService.get_zone_site_map().get(zone) if zone else None
    if not site:
        m = re.search(r'(\d+\s*포장)', raw_cmd)
        if m:
            site = m.group(1).replace(' ', '')
    return build_location_proposal(outs, site, zone, raw_cmd, thread_id, 'location')


def build_location_proposal(outs, site, zone, raw_cmd, thread_id, source):
    """Shared builder for map- and location-scoped control proposals. Filters to
    the named device type, derives on/off state and a localized message, and
    dispatches a proposal whose actions carry location_label/kind_label so the
    message names the place ("'1포장' '1-3'에 배치된 밸브 N개를 열까요?")."""
    if not outs:
        return None
    kind_key, hints = kind_for_command(raw_cmd)
    if hints:
        filtered = [o for o in outs
                    if any(h in (o.name or '').lower() or h in (o.output_type or '').lower()
                           for h in hints)]
        if filtered:
            outs = filtered  # keep only the named type; else fall back to all
    outs.sort(key=lambda o: (o.name or ''))

    off = any(k in raw_cmd or k in raw_cmd.lower()
              for k in ('닫', '꺼', '끄', '정지', 'off', 'close', 'stop'))
    state = not off

    try:
        from flask_babel import gettext as _
        kind_label = _(kind_key)
    except Exception:
        kind_label = kind_key
    location_label = (f"'{site}' '{zone}'" if (site and zone)
                      else (f"'{zone or site}'" if (zone or site) else ''))

    acts = [{
        'tool_name': 'operate_device',
        'params': {
            'device_id': o.unique_id, 'state': state,
            'display_summary': f"{o.name} {'OFF' if off else 'ON'}",
            'location_label': location_label, 'kind_label': kind_label,
        },
    } for o in outs]

    AIAgentService, agent_id = _get_dispatch_agent()
    ins = f"{location_label} — {kind_label} {len(outs)}"
    disp = AIAgentService._dispatch_actions(
        agent_id=agent_id, goal=raw_cmd,
        insight=ins, actions=acts, thread_id=thread_id, message_type='ai',
        metadata={'intent': 'CONTROL', f'{source}_scoped': True, 'zone': zone, 'site': site})
    logger.info(f"[{source.capitalize()}ScopedControl] '{raw_cmd}' @ {location_label} → "
                f"{[o.name for o in outs]} state={'on' if state else 'off'}")
    return {
        "status": "success", "insight": ins, "intent": "CONTROL",
        "proposed_actions": disp['proposed'],
        "immediate_results": disp.get('immediate_results', []),
        "draft_job_ids": disp.get('draft_ids', []),
        "history_id": disp['history_id'],
    }


def propose_function_create(raw_cmd, thread_id):
    """Deterministically handle "X 함수 만들어줘": infer the function_type and
    PROPOSE a create_function action (approval-gated). If the type can't be
    inferred, return a concrete question listing the valid types — never a stall.
    Create-then-configure: the function is created with its type; steps/devices
    are configured afterward."""
    ftype, label = infer_function_type(raw_cmd)
    AIAgentService, agent_id = _get_dispatch_agent()

    if not ftype:
        # Can't infer the type — ask, listing the real options (deterministic).
        try:
            from aot.config import FUNCTION_INFO
            types_str = ", ".join(sorted(FUNCTION_INFO.keys()))
        except Exception:
            types_str = "trigger_sequence, conditional_conditional, pid_pid, ..."
        ins = (f"어떤 종류의 함수를 만들까요? 사용 가능한 타입: {types_str}. "
               f"예: '시퀀스 함수', '조건 함수', 'PID 함수'.")
        disp = AIAgentService._dispatch_actions(
            agent_id=agent_id, goal=raw_cmd, insight=ins, actions=[],
            thread_id=thread_id, message_type='ai',
            metadata={'intent': 'CLARIFY', 'function_create': True})
        return {
            "status": "success", "insight": ins, "intent": "CLARIFY",
            "proposed_actions": [], "immediate_results": [],
            "draft_job_ids": [], "history_id": disp['history_id'],
        }

    # Derive a concise name from the command (strip the create verb tail).
    name = (raw_cmd or '').strip()
    for v in ('를 만들어줘', '을 만들어줘', '만들어줘', '만들어 줘', '생성해줘', '만들어', '생성', '추가해줘', '추가'):
        if name.endswith(v):
            name = name[: -len(v)].strip()
            break
    name = name or f"{label} 함수"

    # For a SEQUENCE, try to resolve the target devices from the command (e.g.
    # "3포장 밸브" → the 8 valves) so the sequence is CREATED WITH ITS STEPS —
    # not an empty shell that then gets activated. Uses the same location-aware
    # search as control. Falls back to an empty create only when nothing resolves.
    if ftype == 'trigger_sequence':
        try:
            from aot.ai.services.aot_data_tool_service import AoTDataToolService as _T
            res = _T.search_devices(raw_cmd) or {}
            outs = [r for r in res.get('results', []) if r.get('type') == 'output']
            outs.sort(key=lambda r: (r.get('name') or ''))
            dev_ids = [r['id'] for r in outs]
            dev_names = [r.get('name') for r in outs]
        except Exception:
            dev_ids, dev_names = [], []
        if dev_ids:
            acts = [{
                'tool_name': 'create_sequence_function',
                'params': {
                    'tool_name': 'create_sequence_function',
                    'arguments': {'name': name, 'device_ids': dev_ids, 'state': 'on'},
                },
                'display_summary': f"Create sequence '{name}' controlling {len(dev_ids)} devices",
            }]
            ins = (f"'{name}' 시퀀스 함수를 만들고 {len(dev_ids)}개 장치"
                   f"({', '.join(dev_names)})를 순서대로 제어 스텝으로 구성할까요?")
            disp = AIAgentService._dispatch_actions(
                agent_id=agent_id, goal=raw_cmd, insight=ins, actions=acts,
                thread_id=thread_id, message_type='ai',
                metadata={'intent': 'FUNCTION_CREATE', 'function_type': ftype,
                          'sequence_devices': dev_ids})
            logger.info(f"[FunctionCreate] '{raw_cmd}' → sequence name={name!r} "
                        f"devices={dev_names}")
            return {
                "status": "success", "insight": ins, "intent": "FUNCTION_CREATE",
                "proposed_actions": disp['proposed'],
                "immediate_results": disp.get('immediate_results', []),
                "draft_job_ids": disp.get('draft_ids', []),
                "history_id": disp['history_id'],
            }
        # no devices resolved → fall through to empty create with a note

    acts = [{
        'tool_name': 'create_function',
        'params': {
            'tool_name': 'create_function',
            'arguments': {'function_type': ftype, 'name': name},
        },
        'display_summary': f"Create {label} function: {name}",
    }]
    note = ("" if ftype != 'trigger_sequence'
            else " 대상 장치를 찾지 못해 빈 시퀀스로 생성합니다(스텝은 이후 구성).")
    ins = (f"'{name}' ({label}) 함수를 생성할까요?"
           f"{note or ' 생성 후 장치·스텝을 구성합니다.'}")
    disp = AIAgentService._dispatch_actions(
        agent_id=agent_id, goal=raw_cmd, insight=ins, actions=acts,
        thread_id=thread_id, message_type='ai',
        metadata={'intent': 'FUNCTION_CREATE', 'function_type': ftype})
    logger.info(f"[FunctionCreate] '{raw_cmd}' → type={ftype} name={name!r} (empty)")
    return {
        "status": "success", "insight": ins, "intent": "FUNCTION_CREATE",
        "proposed_actions": disp['proposed'],
        "immediate_results": disp.get('immediate_results', []),
        "draft_job_ids": disp.get('draft_ids', []),
        "history_id": disp['history_id'],
    }


# =============================================================================
# Single entry point.
# =============================================================================

def resolve(command_text, thread_id=None, page_context=None, intent_override=None):
    """Try each deterministic interceptor in order. Returns a dispatch-ready
    result dict (tagged `_intercept`) the first one that fires, or None if
    nothing resolved — the caller falls through to the LLM-driven pipeline.
    Replaces 4 separate inline call sites in ai_agent_service.py."""
    if intent_override == 'CONTROL':
        if is_recent_control_reference(command_text):
            result = _recent_control_proposal(command_text, thread_id)
            if result:
                return result

        pc = page_context or {}
        raw_cmd = pc.get('raw_command') or command_text
        mapctx = pc.get('map_context') or {}
        if command_has_location(raw_cmd) and is_device_control(raw_cmd):
            prop = propose_location_scoped_control(raw_cmd, thread_id)
            if prop:
                prop['_intercept'] = 'location_control'
                return prop
        elif mapctx and is_vague_device_control(raw_cmd):
            prop = propose_map_scoped_control(raw_cmd, mapctx, thread_id)
            if prop:
                prop['_intercept'] = 'map_control'
                return prop

    raw_fc = (page_context or {}).get('raw_command') or command_text

    if is_function_create_request(raw_fc):
        prop = propose_function_create(raw_fc, thread_id)
        if prop:
            prop['_intercept'] = 'function_create'
            return prop

    return None
