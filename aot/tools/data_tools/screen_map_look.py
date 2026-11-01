# coding=utf-8
"""지도 위젯이 **지금 화면에 그린 것**(도형 색·기상 표현)을 AI 가 쓸 말로 푼다.

사용자가 "파란 도형이 뭐야", "저 파란 선은 뭐야" 라고 물으면 AI 는 색 이름과 도형 종류, 지도에서 날씨를
나타내는 표현(빗줄기·바람선·구름 그림자·주야 음영)을 이어서 답해야 한다. 값의 출처는 화면 JS 가 보고하는
`client_state.maps[*]` 의 세 칸뿐이다 — 서버는 색이나 기상 상태를 **짐작하지 않는다**.

* ``colors``  지도에 실제로 올라간 도형 레이어의 선 색(화면이 `map.getPaintProperty` 와 화면 안 피처에서 읽는다).
              끈 종류·줌에서 컬링된 종류·화면 밖의 종류는 애초에 빠져 온다. 테마(`AoTGeoTheme`)는 화면이 풀었다.
* ``auto``    화면이 자동으로 켠 기상 레이어 이름(저장된 선택에는 없다).
* ``wx``      기상 표현의 지금 상태 — 연출 계획(`AoTMapAmbientFx.info`), 독의 기상 칸, 유효 태양, 시간 슬라이더.

여기서 하는 일은 풀이뿐이다: 16진 색 → 기본 색 이름, 같은 색의 종류 묶기, 구획 색별 이름 묶기, 연출 → 한 줄 설명.
기상 수치는 화면이 받은 `/api/geo/weather_state` 값 그대로(단위는 `AMBIENT_ITEM_UNITS`)이며 다시 계산하지 않는다.
"""
import colorsys
import re

_HEX = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')

#: 화면의 도형 토글 이름(`shapes_hidden`)과 같은 종류 키 → AI 가 도형 종류를 말할 때 쓰는 이름.
#: 대지 선은 굵은 실선, 구역은 점선이라 색이 같아도 선 모양으로 가를 수 있다(위젯이 그리는 그대로).
_KIND_ORDER = ('land', 'zone', 'facility', 'plot', 'equipment', 'input', 'output', 'function', 'device', 'drawn')
_KIND_LABEL = {'land': 'site', 'zone': 'zone', 'facility': 'facility', 'plot': 'plot', 'equipment': 'equipment',
               'input': 'input', 'output': 'output', 'function': 'function', 'device': 'device', 'drawn': 'drawn shape'}
_KIND_HINT = {
    'land': 'site boundary, thick solid outline',
    'zone': 'zone boundary, dashed outline',
    'facility': 'facility footprint (greenhouse, barn), thin solid outline',
    'plot': 'plot (cultivation unit); each plot may have its own chosen color',
    'equipment': 'equipment outline',
    'input': 'area of an input (sensor) device',
    'output': 'area of an output (actuator) device',
    'function': 'area of a function (control) device',
    'device': 'area of another device',
    'drawn': 'free-drawn annotation shape',
}
_DEVICE_KINDS = ('input', 'output', 'function', 'device')
#: 화면의 `shapes_hidden` 이름 → 종류 키(위젯 토글 `land` 가 대지다).
_HIDDEN_ALIAS = {'site': 'land'}


def normalize_hex(value):
    """'#2E7D32' / '2e7d32' / '#2e7' → '#2e7d32'. 알아볼 수 없으면 None(투명도 8자리는 색만 쓴다)."""
    m = _HEX.match(str(value or '').strip())
    if not m:
        return None
    h = m.group(1).lower()
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return '#' + h[:6]


def color_name(value):
    """16진 색 → 기본 색 이름(red/orange/yellow/green/teal/blue/purple/pink/brown/gray/white/black).

    밝기가 뚜렷하면 'dark'/'light' 를 앞에 붙인다(어두운 초록 → 'dark green'). 색을 읽지 못하면 None."""
    h = normalize_hex(value)
    if not h:
        return None
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    hue *= 360.0
    if light < 0.08 or (light < 0.15 and sat < 0.3):
        return 'black'
    if light > 0.93 or (light > 0.88 and sat < 0.3):
        return 'white'
    if sat < 0.2:
        return 'gray'
    if hue < 15 or hue >= 345:
        # 채도가 낮고 어두운 붉은색은 사람 눈에 갈색이다(#a24e39 — 8084 대지 테마색).
        base = 'brown' if (hue < 15 and sat < 0.6 and light < 0.5) else 'red'
    elif hue < 45:
        base = 'brown' if (light < 0.4 and sat < 0.85) else 'orange'
    elif hue < 70:
        base = 'brown' if light < 0.32 else 'yellow'
    elif hue < 165:
        base = 'green'
    elif hue < 200:
        base = 'teal'
    elif hue < 255:
        base = 'blue'
    elif hue < 300:
        base = 'purple'
    else:
        base = 'pink'
    if base != 'brown' and light < 0.25:
        return 'dark ' + base
    if light > 0.8:
        return 'light ' + base
    return base


def color_label(value, with_hex=True):
    """'green (#2e7d32)' — 이름을 모르면 16진만, 16진도 아니면 받은 글자 그대로(40자)."""
    h = normalize_hex(value)
    if not h:
        return str(value or '')[:40]
    name = color_name(h)
    return '%s (%s)' % (name, h) if with_hex else name


def _clean_colors(colors):
    """화면이 보낸 {종류: 색} 에서 알아볼 수 있는 것만 — 모르는 종류 키·이상한 값은 버린다."""
    out = {}
    if not isinstance(colors, dict):
        return out
    for kind in _KIND_ORDER:
        h = normalize_hex(colors.get(kind))
        if h:
            out[kind] = h
    return out


def shape_groups(colors, hidden=None, plots=None):
    """지금 그려진 도형 색 → 같은 색끼리 묶은 목록 ``[(hex, [(종류, [이름…])…])…]``.

    * ``colors``  화면이 보고한 종류별 선 색. 여기 없는 종류는 안 그려진 것(끔·줌·화면 밖)이라 싣지 않는다.
    * ``hidden``  화면의 ``shapes_hidden`` — 보고가 엇갈려도 사용자가 끈 종류는 뺀다.
    * ``plots``   ``[(이름, 색 또는 None)…]`` — 지금 범위 안의 구획. 구획은 ``GeoPlot.color`` 가 테마 기본색을
                  이기므로 색이 없는 구획만 화면이 보고한 기본색(``colors['plot']``)을 쓴다.
    같은 색이 여러 종류에 쓰이면 한 묶음에 함께 나온다(초록 구역과 초록으로 고른 구획이 한 줄)."""
    colors = _clean_colors(colors)
    off = {_HIDDEN_ALIAS.get(k, k) for k in (hidden if isinstance(hidden, list) else []) if isinstance(k, str)}
    if 'device' in off:
        off |= set(_DEVICE_KINDS)
    groups = {}
    order = []

    def add(hex_, kind, names=None):
        if hex_ not in groups:
            groups[hex_] = []
            order.append(hex_)
        for entry in groups[hex_]:
            if entry[0] == kind:
                entry[1].extend(n for n in (names or []) if n not in entry[1])
                return
        groups[hex_].append((kind, list(names or [])))

    for kind in _KIND_ORDER:
        if kind in off or kind not in colors:
            continue
        if kind != 'plot':
            add(colors[kind], kind)
            continue
        default = colors['plot']
        by_color = {}
        for name, color in plots or []:
            if not name:
                continue
            by_color.setdefault(normalize_hex(color) or default, []).append(name)
        if not by_color:
            add(default, 'plot')           # 레이어는 그려졌으나 어느 구획인지 모를 때: 종류만
        for hex_, names in by_color.items():
            add(hex_, 'plot', names)
    return [(h, groups[h]) for h in order]


def _kind_text(entries, max_names, hint=False, seen=None):
    """한 색 묶음의 종류 글 — 'zone', 'plot(감자밭, 딸기하우스)', 'input/output device areas'."""
    parts = []
    devices = [k for k, _n in entries if k in _DEVICE_KINDS]
    for kind, names in entries:
        if kind in _DEVICE_KINDS:
            continue
        txt = _KIND_LABEL[kind]
        if kind == 'plot' and names:
            shown = names[:max_names]
            txt += '(%s%s)' % (', '.join(shown), ', …' if len(names) > len(shown) else '')
        if hint and (seen is None or kind not in seen):
            txt += ' = ' + _KIND_HINT[kind]
            if seen is not None:
                seen.add(kind)
        parts.append(txt)
    if devices:
        names = ['other' if d == 'device' else d for d in devices]
        txt = ('%s device area' % names[0]) if len(names) == 1 else 'device areas (%s)' % '/'.join(names)
        if hint:
            txt += ' = ' + (_KIND_HINT[devices[0]] if len(devices) == 1 else
                            'areas of devices (input = sensor, output = actuator, function = control)')
        parts.append(txt)
    return '; '.join(parts) if hint else ', '.join(parts)


def shapes_short(groups, max_names=3):
    """기본 응답의 한 줄 — 'red=site · green=zone, plot(감자밭) · pink=plot(딸기하우스)'. 그려진 것이 없으면 ''."""
    merged = {}                                             # 색 이름이 같으면 한 칸 — 16진은 focus='map' 에 있다
    for h, entries in groups:
        slot = merged.setdefault(color_name(h) or h, [])
        for kind, names in entries:
            hit = next((e for e in slot if e[0] == kind), None)
            if hit:
                hit[1].extend(n for n in names if n not in hit[1])
            else:
                slot.append((kind, list(names)))
    return ' · '.join('%s=%s' % (n, _kind_text(e, max_names)) for n, e in merged.items())


def shapes_detail(groups, max_names=6):
    """focus='map' — 색별 한 줄: 'green (#28a745): zone = zone boundary, dashed outline'."""
    seen = set()                                            # 뜻은 종류마다 한 번만
    return ['%s: %s' % (color_label(h), _kind_text(e, max_names, hint=True, seen=seen)) for h, e in groups]


# ── 기상 표현 ────────────────────────────────────────────────────────────────

_WIND_NAMES = ('N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW')
_PHASE_TEXT = {'day': 'day', 'golden': 'sunrise/sunset glow', 'twilight': 'twilight', 'night': 'night'}
_PRECIP_KINDS = ('rain', 'snow', 'sleet', 'hail')
_DRAWN_ORDER = ('cloud', 'wind', 'rain', 'snow', 'sleet', 'hail', 'fog', 'lightning')
_DRAWN_SHORT = {'cloud': 'cloud shadows', 'wind': 'wind lines', 'fog': 'fog veil', 'lightning': 'lightning flash',
                'rain': 'rain', 'snow': 'snow', 'sleet': 'sleet', 'hail': 'hail'}
#: 임계 등은 화면(AoTMapAmbientFx.plan)이 이미 적용했다 — 여기서는 보이는 모양과 뜻만 적는다.
_VALUE_ORDER = ('precip', 'wind_speed', 'wind_dir', 'cloud', 'visibility', 'temp')
_VALUE_LABEL = {'precip': 'precip', 'wind_speed': 'wind', 'wind_dir': 'wind from', 'cloud': 'cloud cover',
                'visibility': 'visibility', 'temp': 'temp'}


def compass(deg):
    """각도(0~360) → 16방위 'W'. 기상 풍향은 바람이 **불어 오는** 쪽이다."""
    return _WIND_NAMES[int(round((float(deg) % 360) / 22.5)) % 16]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _s(v, n=40):
    return str(v)[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ''


def _values_text(vals):
    """화면이 받은 기상 값 그대로 — 'precip 2.4 mm/h, wind 3.4 m/s, wind from W (270°)'."""
    try:
        from aot.inputs_gis.ambient_roles import AMBIENT_ITEM_UNITS as units
    except Exception:                                       # noqa: BLE001
        units = {}
    parts = []
    for k in _VALUE_ORDER:
        v = _num((vals or {}).get(k))
        if v is None:
            continue
        if k == 'wind_dir':
            parts.append('wind from %s (%d°)' % (compass(v), round(v) % 360))
        else:
            parts.append('%s %s%s' % (_VALUE_LABEL[k], ('%g' % v), (' ' + units[k]) if units.get(k) else ''))
    return ', '.join(parts)


def time_text(wx):
    """시간 슬라이더가 지금이 아닐 때 'forecast +3h' / 'history -5h'. 지금이면 ''."""
    wx = _clean_wx(wx)
    shift = wx.get('shift')
    dmin = _num(wx.get('dmin'))
    if shift not in ('forecast', 'history') or dmin is None:
        return ''
    mins = abs(int(dmin))
    span = '%dh' % (mins // 60) if mins % 60 == 0 else ('%dmin' % mins if mins < 60 else '%.1fh' % (mins / 60.0))
    return '%s %s%s' % (shift, '+' if dmin >= 0 else '-', span)


def _clean_wx(wx):
    """화면 보고(위조·버그 포함)를 믿지 않고 칸마다 모양을 맞춘다 — 아래 풀이는 이 모양만 읽는다."""
    if not isinstance(wx, dict) or not wx:
        return {}
    out = {k: (wx[k] if isinstance(wx.get(k), str) else None) for k in ('mode', 'fx', 'phase', 'shift')}
    out['forced'] = bool(wx.get('forced'))
    out['zoom_fade'] = _num(wx.get('zoom_fade'))
    out['dmin'] = _num(wx.get('dmin'))
    for k in ('drawn', 'dock', 'src', 'legend'):
        out[k] = wx[k] if isinstance(wx.get(k), list) else []
    for k in ('wind', 'precip', 'vals'):
        out[k] = wx[k] if isinstance(wx.get(k), dict) else {}
    return out


def _drawn_name(kind, wx):
    """짧은 줄의 표현 이름 — 입자는 색까지('rain (blue)'): "파란 선이 뭐야" 가 도형인지 비인지 가르는 단서다."""
    name = _DRAWN_SHORT[kind]
    src = wx['wind'] if kind == 'wind' else wx['precip'] if kind in _PRECIP_KINDS else {}
    col = src.get('f') if kind in ('snow', 'hail') and src.get('f') else src.get('c')
    col = color_name(col) if col else None
    return '%s (%s)' % (name, col) if col else name


def weather_short(wx, auto=None):
    """기본 응답의 한 줄 — 'rain, wind lines drawn · night shading · forecast +3h'.

    ``wx`` 가 없으면(옛 화면 번들) ''. 안 보이는 것을 보인다고 말하지 않는다: 연출이 꺼져 있거나 그릴 것이
    없으면 그렇다고 적는다."""
    wx = _clean_wx(wx)
    if not wx:
        return ''
    parts = []
    drawn = [k for k in _DRAWN_ORDER if k in wx['drawn']]
    fade = _num(wx.get('zoom_fade'))
    if wx.get('fx') == 'off':
        parts.append('weather effects off')
    elif drawn:
        txt = ', '.join(_drawn_name(k, wx) for k in drawn) + ' drawn'
        parts.append(txt + (' (faded out at this zoom)' if fade is not None and fade < 0.2 else ''))
    else:
        parts.append('no weather effect drawn' + ('' if wx.get('vals') else ' (no weather data)'))
    mode = wx.get('mode')
    if mode == 'off':
        parts.append('day/night shading off')
    elif wx.get('phase') in _PHASE_TEXT:
        parts.append('%s%s shading' % (_PHASE_TEXT[wx['phase']], ' (forced)' if wx.get('forced') else ''))
    names = [_s(n, 30) for n in (auto if isinstance(auto, list) else []) if _s(n, 30)]
    if names:
        parts.append('auto weather layers: ' + ', '.join(names[:3]))
    t = time_text(wx)
    if t:
        parts.append('time slider on %s (not now)' % t)
    return ' · '.join(parts)


def weather_detail(wx, auto=None):
    """focus='map' — 켜진 표현마다 한 줄: 어떻게 보이고 무엇을 뜻하는가. 꺼진 것은 꺼졌다고 적는다."""
    wx = _clean_wx(wx)
    if not wx:
        return []
    lines = []
    drawn = [k for k in _DRAWN_ORDER if k in wx['drawn']]
    vals = wx['vals']
    v = lambda k: _num(vals.get(k))                          # noqa: E731
    wind = wx['wind']
    precip = wx['precip']
    if wx.get('fx') == 'off':
        lines.append('weather effects: OFF (widget option) - nothing animated is drawn for rain, wind, clouds, fog '
                     'or lightning, whatever the weather is')
    else:
        if 'cloud' in drawn:
            lines.append('cloud shadows: soft dark patches drifting with the wind; darker = more cloud cover%s'
                         % (' (cloud cover %g %%)' % v('cloud') if v('cloud') is not None else ''))
        if 'wind' in drawn:
            col = color_label(wind.get('c'))
            lines.append('wind lines: thin moving lines with a V arrowhead, %s%s; the arrowhead points where the wind '
                         'blows to, more lines = stronger%s' % (
                             col, ' (strong wind)' if wind.get('strong') else '',
                             ' (wind %g m/s from %s)' % (v('wind_speed'), compass(v('wind_dir')))
                             if v('wind_speed') is not None and v('wind_dir') is not None
                             else (' (wind %g m/s)' % v('wind_speed') if v('wind_speed') is not None else '')))
        for kind in _PRECIP_KINDS:
            if kind not in drawn:
                continue
            col = color_label(precip.get('c'))
            if kind == 'rain':
                shape = 'short slanted %s lines with small ripple rings where they land' % col
            elif kind == 'snow':
                shape = 'drifting %s flakes' % color_label(precip.get('f') or precip.get('c'))
            elif kind == 'sleet':
                shape = '%s rain lines mixed with flakes' % col
            else:
                shape = 'small %s grains' % color_label(precip.get('f') or precip.get('c'))
            lines.append('%s: %s; more = heavier%s' % (kind, shape, ' (precip %g mm/h)' % v('precip')
                                                       if v('precip') is not None else ''))
        if 'fog' in drawn:
            lines.append('fog veil: pale haze over the map, denser = shorter visibility%s'
                         % (' (visibility %g km)' % v('visibility') if v('visibility') is not None else ''))
        if 'lightning' in drawn:
            lines.append('lightning flash: the whole map brightens briefly; recent lightning reported')
        if not drawn:
            lines.append('weather effects: on (%s) but none is drawn now%s' % (
                _s(wx.get('fx'), 10) or 'subtle',
                ' - no weather data for this map' if not vals else
                ' - values are below the drawing thresholds (no rain, calm wind, clear sky, good visibility)'))
        fade = _num(wx.get('zoom_fade'))
        if drawn and fade is not None and fade < 1:
            lines.append('effects fade out when zoomed out (visible %d%% at this zoom)' % round(fade * 100))
    mode = wx.get('mode')
    if mode == 'off':
        lines.append('day/night shading: OFF (widget option) - the ground is never darkened or warmed')
    elif wx.get('phase') in _PHASE_TEXT:
        lines.append('day/night shading: %s%s - ground darkens and loses color toward night, warms at sunrise/sunset%s' % (
            _PHASE_TEXT[wx['phase']], ' (mode forced, not the real sun)' if wx.get('forced') else '',
            ', particles turn pale blue/white' if wx['phase'] in ('twilight', 'night') else ''))
    dock = [_s(k, 20) for k in wx['dock'] if _s(k, 20)]
    if dock:
        lines.append('measurement dock weather cells: %s' % ', '.join(dock[:10]))
    names = [_s(n, 30) for n in (auto if isinstance(auto, list) else []) if _s(n, 30)]
    if names:
        lines.append('weather layers switched on automatically (this screen only, not saved): %s' % ', '.join(names[:6]))
    t = time_text(wx)
    if t:
        lines.append('time slider is on %s, not now: effects, dock and legend show values for that time' % t)
    for lg in wx['legend'][:2]:
        if not isinstance(lg, dict):
            continue
        cs = [color_name(c) or _s(c, 12) for c in (lg.get('c') if isinstance(lg.get('c'), list) else [])[:3]]
        rng = ''
        if _num(lg.get('lo')) is not None and _num(lg.get('hi')) is not None:
            rng = ' %g-%g %s' % (lg['lo'], lg['hi'], _s(lg.get('u'), 8))
        lines.append('time-axis overlay "%s"%s%s%s' % (
            _s(lg.get('t'), 40), ' (%s)' % _s(lg.get('q'), 40) if lg.get('q') else '', rng,
            ': colors ' + ' -> '.join(cs) if cs else ''))
    vt = _values_text(vals)
    if vt:
        lines.append('map weather values%s: %s (source: %s)' % (
            ' for that time' if t else '', vt, '/'.join(_s(x, 8) for x in wx['src']) or '?'))
    return lines


# ── 호출 쪽이 쓰는 두 진입점 ────────────────────────────────────────────────────

def look_short(m, plots=None):
    """기본 응답의 지도 위젯 줄에 덧붙일 한 마디 ``'shapes: red site · green zone · weather: rain drawn'``.

    ``m`` 은 화면이 보고한 지도 한 개(`client_state.maps[i]`). 보고에 색이 없으면(옛 번들) 도형 부분은 빠진다."""
    parts = []
    if isinstance(m.get('colors'), dict):
        txt = shapes_short(shape_groups(m['colors'], m.get('shapes_hidden'), plots))
        parts.append('shapes: ' + (txt or 'none drawn in view'))
    wx = weather_short(m.get('wx'), m.get('auto'))
    if wx:
        parts.append('weather: ' + wx)
    return ' · '.join(parts)


def look_detail(m, plots=None):
    """``focus='map'`` — ``{'shape_colors': [...], 'weather': [...]}`` (비면 그 칸은 없다)."""
    out = {}
    if isinstance(m.get('colors'), dict):
        out['shape_colors'] = shapes_detail(shape_groups(m['colors'], m.get('shapes_hidden'), plots)) \
            or ['no shapes drawn in the current view']
    lines = weather_detail(m.get('wx'), m.get('auto'))
    if lines:
        out['weather'] = lines
    return out
