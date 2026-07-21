# coding=utf-8
"""
Structured calendar-event ⇄ AoT-schedule field spec (bidirectional, i18n).

A human-editable `키: 값` / `Key: Value` convention in an event's description so
an operator can create/edit an event in Google Calendar and AoT interprets it
(and vice-versa). Content round-trips: editing the fields in Google reflects
back into the AoT schedule on the next pull.

i18n (the system's base language is English; a user's configured language is
applied via Flask-Babel):
  - WRITING (push): field labels + state words are rendered with gettext, so a
    Korean operator sees `장치: 밸브1 / 상태: 켜짐` and an English one sees
    `Device: Valve1 / State: On`. The background sync service forces the
    connection user's locale around this (see calendar_sync_service).
  - READING (parse): labels/values are matched against a broad, language- and
    synonym-tolerant table PLUS the gettext translation of each canonical label
    in the active locale — so whatever language/wording the event was written in
    still parses. State synonyms are generous by design (see _STATE_SYNONYMS):
    켜짐/켜기/켬/켜/온/활성/활성화/on/enable… all normalize to the system's
    canonical Output state 'on' (canonical set: on/off/open/close, matching
    aot_data_tool_service.operate_device_tool's ALLOWED_STATES).

Category is inferred from the fields, not the calendar: a resolvable device ⇒
device control; otherwise a human task. The event's start/end supplies the time.
"""
import re

try:
    from flask_babel import gettext as _
except Exception:  # pragma: no cover - allows import outside app context
    def _(s):
        return s


# canonical field -> English gettext source string used for the WRITTEN label.
_FIELD_LABELS = {
    'location': 'Location',
    'device': 'Device',
    'content': 'Content',
    'state': 'State',
    'worker': 'Worker',
    'duration': 'Duration',
    'value': 'Value',
    'pid': 'PID',
    'setpoint': 'Setpoint',
    'setting': 'Setting',
    'function': 'Function',
    'activate': 'Activate',
    'deactivate': 'Deactivate',
}

# Hardcoded multilingual + synonym label aliases (lowercased) -> canonical field.
# Generous on purpose; the active-locale gettext label is added on top at parse
# time so any localized wording also resolves.
_FIELD_ALIASES = {
    # location
    '장소': 'location', '위치': 'location', '구역': 'location', 'place': 'location',
    'location': 'location', 'loc': 'location', 'zone': 'location', 'site': 'location',
    'area': 'location',
    # device
    '장치': 'device', '기기': 'device', '설비': 'device', '디바이스': 'device',
    'device': 'device', 'equipment': 'device', 'output': 'device', 'actuator': 'device',
    # content
    '내용': 'content', '작업': 'content', '업무': 'content', '할일': 'content', '할 일': 'content',
    '제목': 'content', 'content': 'content', 'task': 'content', 'work': 'content',
    'title': 'content', 'memo': 'content', 'note': 'content', 'desc': 'content',
    # state / control
    '상태': 'state', '제어': 'state', '동작': 'state', '작동': 'state', '조작': 'state',
    'state': 'state', 'status': 'state', 'action': 'state', 'control': 'state', 'command': 'state',
    # worker
    '담당': 'worker', '담당자': 'worker', '작업자': 'worker', '책임자': 'worker',
    'worker': 'worker', 'assignee': 'worker', 'person': 'worker', 'staff': 'worker', 'who': 'worker',
    # duration
    '지속': 'duration', '지속시간': 'duration', '시간': 'duration', '기간': 'duration', '동안': 'duration',
    'duration': 'duration', 'length': 'duration', 'time': 'duration', 'for': 'duration',
    # value (PWM duty / analog set_value / generic numeric)
    '값': 'value', '출력값': 'value', '듀티': 'value', '세기': 'value',
    'value': 'value', 'duty': 'value', 'amount': 'value', 'level': 'value',
    # pid target
    'pid': 'pid', '피드백제어': 'pid', 'pid제어기': 'pid',
    # pid setpoint (implies setting=setpoint)
    '목표값': 'setpoint', '목표': 'setpoint', '설정값': 'setpoint', '세트포인트': 'setpoint',
    'setpoint': 'setpoint', 'target': 'setpoint', 'sp': 'setpoint',
    # pid setting name (setpoint/kp/ki/kd/method/...)
    '설정': 'setting', '파라미터': 'setting', 'setting': 'setting', 'parameter': 'setting', 'param': 'setting',
    # function to trigger once
    '함수': 'function', '자동화': 'function', '시퀀스': 'function',
    'function': 'function', 'sequence': 'function', 'automation': 'function',
    # activate / deactivate an Input or controller (value = entity name)
    '활성화': 'activate', '활성': 'activate', '켜기제어': 'activate',
    'activate': 'activate', 'enable': 'activate',
    '비활성화': 'deactivate', '비활성': 'deactivate', '끄기제어': 'deactivate',
    'deactivate': 'deactivate', 'disable': 'deactivate',
}

# PID setting-name synonyms -> canonical daemon setting (aot_daemon.pid_set).
_PID_SETTING_SYNONYMS = {
    'setpoint': {'setpoint', '목표값', '목표', '설정값', 'sp', 'target'},
    'kp': {'kp', '비례', '비례게인', 'p'},
    'ki': {'ki', '적분', '적분게인', 'i'},
    'kd': {'kd', '미분', '미분게인', 'd'},
    'method': {'method', '방식'},
    'integrator': {'integrator', '적분기'},
    'derivator': {'derivator', '미분기'},
}

# canonical state -> gettext source word (WRITTEN value)
_STATE_LABELS = {'on': 'On', 'off': 'Off', 'open': 'Open', 'close': 'Close'}

# canonical state -> generous synonym set (whitespace removed, lowercased).
# Covers inflections/spellings the user asked for and their natural opposites.
_STATE_SYNONYMS = {
    'on': {
        'on', 'ｏｎ', '켜짐', '켜기', '켬', '켜', '켠다', '켤것', '킴', '킬것', '킬', '키기',
        '온', '활성', '활성화', '가동', '작동', '구동', '시작', '개시', '동작',
        'enable', 'enabled', 'activate', 'activated', 'active', 'start', 'run', 'true', '1',
    },
    'off': {
        'off', '꺼짐', '끄기', '끔', '꺼', '끈다', '끌것', '끌', '오프',
        '비활성', '비활성화', '정지', '중지', '중단', '멈춤', '멈춰', '종료',
        'disable', 'disabled', 'deactivate', 'deactivated', 'inactive', 'stop', 'halt', 'false', '0',
    },
    'open': {
        'open', 'opened', '열림', '열기', '열어', '연다', '개방', '오픈', '개',
    },
    'close': {
        'close', 'closed', '닫힘', '닫기', '닫아', '닫는다', '폐쇄', '클로즈', '차단',
    },
}

# `키: 값` — ASCII or fullwidth colon, optional leading bullets/spaces.
_LINE_RE = re.compile(r'^\s*[-*•]?\s*([^:：]{1,24})[:：]\s*(.+?)\s*$')


def _marker():
    # literal so pybabel can extract it (a variable arg to _() is not extractable)
    return _("Keep the 'Key: Value' lines so AoT can apply your edits.")


def _norm(s):
    return re.sub(r'\s+', '', str(s).strip().lower())


def normalize_state(value):
    """Map a free-text control word (any supported language/synonym) to a
    canonical Output state: 'on' | 'off' | 'open' | 'close', or None if
    unrecognized. Whitespace-insensitive ('킬 것' == '킬것'). Also matches the
    active-locale gettext state words."""
    if value is None:
        return None
    n = _norm(value)
    if not n:
        return None
    # active-locale written words (e.g. gettext('On') -> '켜짐') first
    for canon, src in _STATE_LABELS.items():
        try:
            if _norm(_(src)) == n:
                return canon
        except Exception:
            pass
    for canon, syns in _STATE_SYNONYMS.items():
        if n in syns:
            return canon
    # last resort: containment (handles "켜기(ON)" etc.)
    for canon, syns in _STATE_SYNONYMS.items():
        if any(s and s in n for s in syns):
            return canon
    return None


def state_display(state):
    """Localized written form of a canonical state ('on' -> gettext('On'))."""
    src = _STATE_LABELS.get(state)
    return _(src) if src else (state or '')


def normalize_pid_setting(value):
    """Map a free-text PID setting name to a canonical daemon setting
    (setpoint/kp/ki/kd/method/integrator/derivator), default 'setpoint'."""
    n = _norm(value)
    for canon, syns in _PID_SETTING_SYNONYMS.items():
        if n == canon or n in {_norm(s) for s in syns}:
            return canon
    return 'setpoint'


def _parse_number(val):
    """First number in a string as float (handles '60', '25.5', '60%', '25도')."""
    m = re.search(r'-?\d+(?:\.\d+)?', str(val))
    return float(m.group()) if m else None


def _label_lookup():
    """label(normalized) -> canonical field, combining hardcoded aliases with
    the active-locale gettext translation of each canonical label."""
    lut = {_norm(k): v for k, v in _FIELD_ALIASES.items()}
    for field, src in _FIELD_LABELS.items():
        try:
            lut[_norm(_(src))] = field
        except Exception:
            pass
    return lut


def parse_event_fields(summary, description):
    """Extract structured fields from an event's summary + description. Returns
    a dict with any of: location, device, content, state, worker, duration
    (duration = int minutes). Falls back to the summary as `content` when no
    explicit content field is present and the summary isn't itself a labeled
    line."""
    lut = _label_lookup()
    fields = {}
    text = "{}\n{}".format(summary or '', description or '')
    for raw_line in text.splitlines():
        m = _LINE_RE.match(raw_line)
        if not m:
            continue
        canon = lut.get(_norm(m.group(1)))
        if not canon:
            continue
        val = m.group(2).strip()
        if canon == 'duration':
            num = re.search(r'\d+', val)
            if num:
                fields['duration'] = int(num.group())
        elif canon in ('value', 'setpoint'):
            num = _parse_number(val)
            if num is not None:
                fields[canon] = num
        elif canon == 'state':
            st = normalize_state(val)
            if st:
                fields['state'] = st
        else:
            fields[canon] = val

    if 'content' not in fields:
        s = (summary or '').strip()
        if s and not _LINE_RE.match(s):
            fields['content'] = s
    return fields


def _num(v):
    """Render a value without a trailing .0 (60.0 -> '60', 25.5 -> '25.5')."""
    if v is None:
        return ''
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except Exception:
        return str(v)


def format_job_description(category, content=None, location=None, worker=None,
                           device=None, state=None, duration_min=None,
                           value=None, pid=None, setpoint=None, setting=None,
                           function=None, target=None):
    """Build the localized, editable description block AoT writes on push.
    `category`: 'device' | 'pid' | 'function' | 'activate' | 'deactivate' |
    'user' | 'ai'."""
    L = _FIELD_LABELS
    lines = []
    if category in ('activate', 'deactivate'):
        lines.append("{}: {}".format(_(L[category]), target or ''))
    elif category == 'pid':
        if pid:
            lines.append("{}: {}".format(_(L['pid']), pid))
        if setting and setting != 'setpoint':
            lines.append("{}: {}".format(_(L['setting']), setting))
            lines.append("{}: {}".format(_(L['value']), _num(value if value is not None else setpoint)))
        else:
            lines.append("{}: {}".format(_(L['setpoint']), _num(setpoint if setpoint is not None else value)))
    elif category == 'function':
        if function:
            lines.append("{}: {}".format(_(L['function']), function))
        lines.append("{}: {}".format(_(L['state']), _('Run')))
    elif category == 'device':
        if device:
            lines.append("{}: {}".format(_(L['device']), device))
        if value is not None:   # value/PWM set
            lines.append("{}: {}".format(_(L['value']), _num(value)))
        if state:
            lines.append("{}: {}".format(_(L['state']), state_display(state)))
        if duration_min:
            lines.append("{}: {}{}".format(_(L['duration']), duration_min, _('min')))
    else:
        if location:
            lines.append("{}: {}".format(_(L['location']), location))
        if content:
            lines.append("{}: {}".format(_(L['content']), content))
        if worker:
            lines.append("{}: {}".format(_(L['worker']), worker))
    lines.append("")
    lines.append("— {} —".format(_marker()))
    return "\n".join(lines)


def format_job_summary(category, content=None, location=None, device=None, state=None,
                       value=None, pid=None, setpoint=None, setting=None, function=None,
                       target=None):
    """The event title shown in Google Calendar (concise, still informative)."""
    if category in ('activate', 'deactivate'):
        return "{} · {}".format(target or '', _(_FIELD_LABELS[category]))
    if category == 'pid':
        tgt = pid or _('PID')
        if setting and setting != 'setpoint':
            return "{} {} {}".format(tgt, setting, _num(value if value is not None else setpoint))
        return "{} → {}".format(tgt, _num(setpoint if setpoint is not None else value))
    if category == 'function':
        return "{} · {}".format(function or _('Function'), _('Run'))
    if category == 'device':
        if value is not None and not state:
            return "{} {}".format(device or _('Device control'), _num(value))
        parts = [p for p in (device, state_display(state)) if p]
        return " ".join(parts) or (content or _('Device control'))
    title = content or _('Schedule')
    if location:
        title = "{} · {}".format(title, location)
    return title
