# coding=utf-8
"""함수 상태 문장을 **뷰어의 언어로** 만든다.

데몬(`aot_daemon`)에는 요청 컨텍스트가 없다. `flask_babel.gettext` 는 요청의
`Accept-Language`/사용자 설정에서 로케일을 고르므로, 컨트롤러가 문장을 만들면
그것이 무슨 언어가 될지 아무도 정할 수 없다 — 실제로 예전에는 전부 영어였다.

그래서 **컨트롤러는 사실(`status_facts`)만 내보내고 문장은 여기서 만든다.**
이 모듈은 Flask 라우트(`/function_status_activated`)에서만 불리므로 요청
컨텍스트 안이고, 위젯과 함수 설정 페이지가 같은 번역을 함께 받는다.

⚠ **문장을 두 벌 만들지 말 것.** 컨트롤러에도 영어 문장을 남겨 두면 어느 쪽이
  화면에 나가는지 상황마다 달라지고, 한쪽만 고쳤을 때 조용히 갈린다. 컨트롤러
  쪽에는 `string_status` 를 만들지 않는다 — 만드는 곳은 여기 하나다.

⚠ **번역 문구에 리터럴 `%` 를 넣지 말 것**(CLAUDE.md). babel 이 python-format
  으로 읽어 `pybabel compile` 이 거부하고, 그러면 그 언어 **전체**가 영어로
  나온다. 퍼센트 기호는 msgid 가 아니라 **값 쪽**에 붙인다.
"""

from flask_babel import gettext as _

# 모드·액추에이터 종류·변수 이름 라벨.
#
# ⚠ **msgid 를 새로 만들지 말 것.** 여기 있는 영어 문자열은 지도 팝업
#   (`aot-map-popup.js` 의 `_MODE_LABELS`/`_KIND_LABELS`/`_LIMIT_LABELS`)이
#   이미 쓰는 것과 **같은 msgid** 라 카탈로그에 번역이 들어 있다. 다르게
#   적으면 같은 것을 가리키는 번역이 두 벌이 되고, 화면마다 다른 말이 나온다.
_MODE_LABELS = {
    'cooling': 'Cooling', 'heating': 'Heating', 'humidify': 'Humidify',
    'dehumidify': 'Dehumidify', 'co2_enrich': 'CO2 Enrichment',
    'conservation': 'Conservation', 'emergency': 'Emergency',
    'degraded': 'Partial Control', 'natural': 'Natural Ventilation',
    'unattainable': 'Target Unattainable',
}

_KIND_LABELS = {
    'opening': 'Opening', 'curtain': 'Curtain', 'shade': 'Shade',
    'heater': 'Heater', 'cooler': 'Cooler', 'fogger': 'Fogger',
    'co2_injector': 'CO2 Injector', 'lighting': 'Lighting',
    'circulation_fan': 'Circulation Fan', 'exhaust_fan': 'Exhaust Fan',
    'intake_fan': 'Intake Fan',
}

_VAR_LABELS = {
    'temperature': 'Temperature', 'humidity': 'Humidity',
    'co2': 'CO2', 'vpd': 'Water (VPD)', 'water': 'Water (VPD)',
    'light': 'Light Level',
}


def _label(table, code):
    """코드 → 번역된 라벨. 모르는 코드는 **그대로** 내보낸다.

    새 모드·새 액추에이터 종류가 생겼을 때 화면에서 조용히 사라지는 것보다
    영어 코드가 그대로 보이는 편이 낫다 — 후자는 눈에 띄어 고쳐진다.
    """
    name = table.get(code)
    return _(name) if name else str(code)


def _num(value, digits=0):
    """숫자를 자릿수 고정 문자열로. 숫자가 아니면 None."""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return None


def _signed(value):
    """편차용 부호 있는 짧은 숫자(`+8.52`, `-2.7`)."""
    try:
        return f"{float(value):+g}"
    except (TypeError, ValueError):
        return None


def _duration(seconds):
    """초 → `1:35:57` / `35:57`. 0 이하·비숫자는 None."""
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _seconds(seconds):
    """초 → "30 s". 단위까지 번역 대상이다(한국어는 "30초")."""
    text = _num(seconds)
    return _('%(n)s s') % {'n': text} if text is not None else None


def _ago(seconds):
    """경과 초 → "45초 전" 류.

    복수형을 쓰지 않는다 — 시간은 소수 한 자리로 내보내므로(`1.5 h`)
    `ngettext` 의 정수 전제가 깨지고, 위젯 한 줄에는 축약 단위가 더 맞다.
    """
    try:
        seconds = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return None
    if seconds < 90:
        return _('%(n)s s ago') % {'n': f"{seconds:.0f}"}
    if seconds < 5400:
        return _('%(n)s min ago') % {'n': f"{seconds / 60:.0f}"}
    return _('%(n)s h ago') % {'n': f"{seconds / 3600:.1f}"}


# ── env_coordinator ──────────────────────────────────────────────────────────

_PAUSE_LINES = {
    'no_actuators': lambda: _('Paused — no actuators registered'),
    'outside_time_window': lambda: _('Paused — outside the operating time window'),
}


def _env_coordinator_lines(facts):
    paused = facts.get('paused')
    summary = facts.get('summary') or {}

    head = None
    if paused:
        builder = _PAUSE_LINES.get(paused)
        head = builder() if builder else _('Paused (%(reason)s)') % {'reason': paused}

    if not summary:
        return [head or _('Waiting for the first control cycle.')]

    lines = []
    if head:
        lines.append(head)
    else:
        modes = [_label(_MODE_LABELS, m) for m in (summary.get('modes') or [])]
        if modes:
            lines.append(_('Mode: %(modes)s') % {'modes': ', '.join(modes)})

    # 현재 환경. 단위 기호와 VPD·CO2 는 번역하지 않는다 — 숫자에 붙는 기호이자
    # 어느 언어에서도 그대로 쓰는 약어라, 번역 대상으로 만들면 어긋날 여지만 생긴다.
    # ⚠ VPD·CO2 의 앞 라벨을 빼지 말 것. 온도·습도는 단위(°C·%)로 무엇인지
    #   알 수 있지만 `1.25 kPa` 는 그것만으로 무슨 값인지 알 수 없다.
    photo = summary.get('photo') or {}
    values = []
    for key, digits, prefix, unit in (('temp', 1, '', ' °C'), ('rh', 0, '', '%'),
                                      ('vpd', 2, 'VPD ', ' kPa'),
                                      ('co2', 0, 'CO2 ', ' ppm')):
        text = _num(photo.get(key), digits) if photo.get(key) is not None else None
        if text is not None:
            values.append(f"{prefix}{text}{unit}")
    if values:
        lines.append(_('Environment: %(values)s') % {'values': ' / '.join(values)})

    deviation = []
    for var, value in (summary.get('deviation') or {}).items():
        text = _signed(value)
        if text is not None:
            deviation.append(f"{_label(_VAR_LABELS, var)} {text}")
    if deviation:
        lines.append(_('Deviation: %(values)s') % {'values': ', '.join(deviation)})

    actuators = []
    for kind, pct in (summary.get('outputs_by_kind') or {}).items():
        text = _num(pct)
        if text is not None:
            actuators.append(f"{_label(_KIND_LABELS, kind)} {text}%")
    if actuators:
        lines.append(_('Actuators: %(values)s') % {'values': ', '.join(actuators)})

    vent = summary.get('vent') or {}
    ratio = _num(vent.get('open_ratio_pct'))
    if ratio is not None:
        lines.append(_('Ventilation: %(ratio)s open (%(area)s)') % {
            'ratio': f"{ratio}%",
            'area': f"{_num(vent.get('effective_area_m2')) or '0'} / "
                    f"{_num(vent.get('total_area_m2')) or '0'} m²"})

    # ⚠ `triggered` 와 `description` 은 함께 움직이지 않는다 — 부분 게이트는 사유만
    #   남기고 제어는 계속 돈다. 한 문구로 합치면 "지금 제어가 멈췄다" 는 거짓이 된다.
    gate = summary.get('gate') or {}
    reason = gate.get('description') or ''
    if gate.get('triggered'):
        lines.append(_('Safety gate: %(reason)s — control stopped') % {
            'reason': reason or _('triggered')})
    elif reason:
        lines.append(_('Safety gate (partial): %(reason)s') % {'reason': reason})

    strain = summary.get('strain')
    if strain:
        target = _label(_VAR_LABELS, strain.get('var'))
        if strain.get('reason') == 'no_actuator':
            lines.append(_('No actuator to control %(target)s') % {'target': target})
        else:
            detail = f"{target} {_signed(strain.get('dev')) or ''}".strip()
            lines.append(
                (_('Equipment at its limit: %(detail)s')
                 if strain.get('reason') == 'saturated'
                 else _('Beyond the set limit: %(detail)s')) % {'detail': detail})

    when = _ago(facts.get('age_s'))
    if when:
        lines.append(_('Last cycle: %(when)s') % {'when': when})
    return lines


# ── 시퀀스 ────────────────────────────────────────────────────────────────────

_SEQUENCE_STATES = {
    'running': lambda: _('Running'),
    'idle': lambda: _('Idle'),
    'outside_window': lambda: _('Outside the time window'),
    'activated': lambda: _('Activated'),
    'initializing': lambda: _('Initializing'),
    'standby': lambda: _('Standby'),
    'ready': lambda: _('Ready'),
}


def _sequence_lines(facts, data):
    state = facts.get('state')
    if state == 'waiting':
        label = _('Waiting (%(time)s)') % {
            'time': _seconds(facts.get('wait_s')) or ''}
    else:
        builder = _SEQUENCE_STATES.get(state)
        label = builder() if builder else str(state or '')
    lines = [_('Sequence: %(state)s') % {'state': label}]

    start, end = facts.get('window_start'), facts.get('window_end')
    if start and end:
        period = _duration(facts.get('period_s'))
        params = {'start': start, 'end': end, 'period': period}
        lines.append((_("Today's window: %(start)s – %(end)s (cycle %(period)s)")
                      if period else _("Today's window: %(start)s – %(end)s")) % params)

    elapsed = _duration(facts.get('elapsed_s')) if facts.get('in_cycle') else None
    if elapsed:
        lines.append(_('Elapsed in cycle: %(elapsed)s') % {'elapsed': elapsed})

    # ⚠ 스텝은 **응답의 것**을 센다. 라우트가 데몬 응답에 정적 스텝을 나중에
    #   합쳐 넣는 경로가 있어(`function_status_activated`), 컨트롤러가 셈해 둔
    #   수를 그대로 쓰면 합쳐진 뒤와 어긋난다.
    steps = (data or {}).get('steps') or []
    if steps:
        lines.append(_('Steps: %(running)s of %(total)s running') % {
            'running': sum(1 for step in steps if step.get('is_active')),
            'total': len(steps)})
    return lines


# ── Conditional ──────────────────────────────────────────────────────────────

def _conditional_lines(facts):
    lines = [_('Conditional: %(state)s') % {
        'state': _('Activated') if facts.get('is_activated') else _('Deactivated')}]

    period = _seconds(facts.get('period_s'))
    if period:
        lines.append(_('Period: %(period)s') % {'period': period})

    when = _ago(facts.get('last_run_age_s')) if facts.get('last_run_age_s') is not None else None
    if when:
        lines.append(_('Last check: %(when)s') % {'when': when})
        lines.append(_('The last check ran an action.') if facts.get('action_fired')
                     else _('The last check ran no action.'))
    else:
        lines.append(_('Not checked yet.'))

    next_check = _seconds(facts.get('next_check_s'))
    if next_check:
        lines.append(_('Next check in: %(time)s') % {'time': next_check})
    return lines


_RENDERERS = {
    'env_coordinator': lambda facts, data: _env_coordinator_lines(facts),
    'sequence': _sequence_lines,
    'conditional': lambda facts, data: _conditional_lines(facts),
}


def localize(data):
    """응답에 `status_facts` 가 있으면 그것으로 `string_status` 를 쓴다.

    없으면 손대지 않는다 — PID·카메라·사용자가 직접 쓴 Conditional 상태 코드는
    자기 `string_status` 를 이미 들고 오고, 그것은 이 모듈의 어휘가 아니다.
    """
    if not isinstance(data, dict):
        return data
    facts = data.get('status_facts')
    if not isinstance(facts, dict):
        return data
    renderer = _RENDERERS.get(facts.get('kind'))
    if renderer is None:
        return data
    lines = [line for line in renderer(facts, data) if line]
    if lines:
        data['string_status'] = "\n".join(lines)
    return data
