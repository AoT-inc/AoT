# coding=utf-8
"""§6 계약 dict 를 Markdown·CSV·ODT·JSON 출력물로 바꾸는 렌더러."""
from ._shared import AVG_IS_TIME_WEIGHTED, CHANNEL_ZERO_ONLY
from .calc import (
    _display_avg, _gettext_safe, _target_kind_label, cover_material_label,
    fold_buckets, measurement_label, phase_delta_text, phase_target_text,
    stage_sections, unit_label, with_curve_deltas,
)


def glossary_terms(journal_data):
    """이 문서에 **실제로 나오는** 전문용어만 → `[{'term', 'text'}, …]`.

    GDD·DLI·VPD 는 시설원예 바깥에서는 통하지 않는 말이다. 문서를 받는 쪽이
    인증기관이나 다음 사람이면 더 그렇다 — 숫자는 있는데 그 숫자가 무엇을
    세는 것인지 문서 안에 없으면 물어볼 데가 없다.

    ⚠ **안 나오는 용어를 설명하지 않는다.** 용어집을 통째로 실으면 GDD 를
      쓰지 않는 노지 일지에도 적산온도 설명이 붙는다 — 안내가 길어질수록
      읽히지 않고, 읽히지 않는 안내는 없는 것과 같다.
    """
    present = set()
    for bucket in (journal_data.get('buckets') or []):
        for row in (bucket.get('env') or []):
            m = str(row.get('measurement') or '')
            if m in ('dli', 'vapor_pressure_deficit'):
                present.add(m)
    if (journal_data.get('gdd') or {}).get('total') is not None:
        present.add('gdd')

    out = []
    if 'gdd' in present:
        out.append({'term': _gettext_safe('GDD (growing degree days)'),
                    'text': _gettext_safe(
                        "A running total of warmth. Each day adds how much "
                        "the day's average temperature sat above the "
                        "temperature this crop needs to grow at all, so a "
                        "warm day adds more than a cool one. Crops move "
                        "through their stages on accumulated warmth rather "
                        "than on the calendar, which is why a stage can "
                        "arrive early in a hot season.")})
    if 'dli' in present:
        out.append({'term': _gettext_safe('DLI (daily light integral)'),
                    'text': _gettext_safe(
                        "How much light the crop received over a whole day, "
                        "added up rather than measured at one moment. "
                        "Brightness alone does not say much — a bright but "
                        "short day and a dim but long one can come to the "
                        "same total. Measured in mol/m2/day.")})
    if 'vapor_pressure_deficit' in present:
        out.append({'term': _gettext_safe('VPD (vapour pressure deficit)'),
                    'text': _gettext_safe(
                        "How dry the air feels to the plant, in kPa. It "
                        "combines temperature and humidity, because the same "
                        "humidity is drying on a warm day and not on a cool "
                        "one. High VPD pushes the plant to transpire; too "
                        "high and it closes up and stops growing.")})
    return out


def caveat_text(key):
    """`caveats` 의 키 하나 → 뷰어 언어의 문장. HTML(§10)·MD(§11) 이 함께 쓴다.

    키로 저장해 둔 이유(모듈 상단 상수 주석)와 같다 — 문장을 저장하면 생성
    시점의 언어로 굳는다. `gps-notes-skipped:<사유>` 처럼 접미사가 붙는 키는
    ':' 로 갈라 사유별 문장을 고른다.
    """
    base, _, suffix = key.partition(':')

    if base == AVG_IS_TIME_WEIGHTED:
        return _gettext_safe(
            "Daily averages are the mean of hourly means, not a true "
            "time-weighted average of every reading.")
    if base == CHANNEL_ZERO_ONLY:
        return _gettext_safe(
            "Runtime is read from the first channel only, even for "
            "multi-channel outputs.")
    if base == 'partial-query-failures':
        return _gettext_safe(
            "%(n)s channel(s) could not be read and are missing from "
            "this journal.") % {'n': suffix}
    if base == 'unassigned-areas':
        return _gettext_safe(
            "%(n)s device area(s) overlap this plot with no device "
            "assigned yet.") % {'n': suffix}
    if base == 'gps-notes-skipped':
        if suffix == 'facility-plot-derived-geometry':
            return _gettext_safe(
                "Notes pinned to a map location are not included for "
                "facility plots — their outline is derived from the "
                "facility, not their own.")
        return _gettext_safe("Notes pinned to a map location were not checked.")
    if base == 'sensor-from-zone':
        return _gettext_safe(
            "No sensor sits inside this plot, so the nearest one in the same "
            "zone was used — about %(m)s m away. It is the closest reading "
            "available, not a reading of this plot.") % {'m': suffix or '?'}
    if base == 'outputs-no-record':
        return _gettext_safe(
            "These devices belong to this target but left no record in this "
            "period, so they are not in the tables: %(names)s. That is not "
            "the same as running for zero hours — it means nothing was "
            "written.") % {'names': suffix.replace(',', ' · ')}
    if base == 'water-no-flow-basis':
        return _gettext_safe(
            "Water volume is only filled in for devices whose flow rate is "
            "known, and none here is — so this journal shows run times only. "
            "Facilities get flow from their piping layout; equipment drawn "
            "straight onto the map carries a flow rate but is not linked to "
            "the valve that opens it, so it cannot be attributed.")
    if base == 'water-estimated-map':
        return _gettext_safe(
            "Water volumes are estimated from the sprinklers drawn on the "
            "map inside the area each valve covers, and how long that valve "
            "ran — not measured by a flow meter. Only the part that overlaps "
            "this plot is counted, so no share is guessed.")
    if base == 'water-estimated':
        return _gettext_safe(
            "Water volumes are estimated from the designed nozzle flow and "
            "run time, and split by the plot's share of the bay — not "
            "measured by a flow meter.")
    if base == 'precipitation-not-summed':
        # ⚠ **합계를 지어내지 않는다.** 실측(기상청 채널, 2026-09-04):
        #   `rn_15m`(직전 15분 누적)을 **5분마다** 다시 적어 창이 겹친다 —
        #   그대로 더하면 같은 비를 세 번 센다. 그렇다고 3으로 나누면 그것은
        #   기록이 아니라 지어낸 계수다(이 파일의 DLI 환산 규칙과 같은 이유).
        #   시스템은 어떤 강수 채널이 겹치는 창인지 아닌지 알 방법이 없으므로,
        #   합계를 내지 않는다는 사실과 각 열이 무엇인지를 대신 말한다.
        return _gettext_safe(
            "No rainfall total is given. Each stored reading covers its own "
            "window, and this system cannot tell whether those windows "
            "overlap — the weather-station channel, for one, repeats a "
            "15-minute total every 5 minutes. Read the maximum as the "
            "wettest single window, and the average as the mean of those "
            "windows, not an hourly rate.")
    if base == 'water-partial-coverage':
        return _gettext_safe(
            "Some devices in this journal have no mapped coverage area, so "
            "their water column stays blank — that does not mean they used "
            "no water.")
    if base == 'dli-estimated':
        return _gettext_safe(
            "Daily light integral is estimated from solar radiation "
            "(W/m2), assuming sunlight. A PAR sensor would measure it "
            "directly.")
    if base == 'dli-outdoor':
        return _gettext_safe(
            "Light is measured outdoors, so the daily light integral is "
            "what reached the site — not what reached the crop under "
            "cover or supplemental lighting.")
    if base == 'dli-through-cover':
        material, _, tau = suffix.partition(':')
        return _gettext_safe(
            "Light is measured outdoors, so the daily light integral shown "
            "is what got through the cover: the outdoor figure multiplied "
            "by %(tau)s for %(material)s. The cover's material is used; its "
            "thickness, age and dust are not, so the real figure is usually "
            "a little lower.") % {
                'tau': tau or '?', 'material': cover_material_label(material)}
    if base == 'dli-shade-not-counted':
        return _gettext_safe(
            "This facility has a shade screen. Whether it was drawn on any "
            "given day is not recorded, so it is not counted — on days it "
            "was drawn, the crop got less light than shown.")
    if base == 'measurements-excluded-diagnostic':
        names = [measurement_label(k) for k in suffix.split(',') if k]
        return _gettext_safe(
            "Device diagnostics were left out of this journal: %(names)s."
        ) % {'names': ' · '.join(str(n) for n in names)}
    if base == 'measurements-excluded-chosen':
        # `<scope>:<name>` — 어느 쪽 센서의 것인지까지 말한다. 기상대 쪽은
        # 그 말을 앞에 붙인다("기상대 온도") — 안 붙이면 현장 온도가 빠진
        # 줄로 읽힌다.
        names = []
        for item in suffix.split(','):
            if not item:
                continue
            scope, _, name = item.rpartition(':')
            label = str(measurement_label(name, scope or None))
            if scope == 'outdoor':
                label = '%s %s' % (_gettext_safe('Weather Station'), label)
            names.append(label)
        return _gettext_safe(
            "These measurements were not selected when this journal was "
            "made, so they are not in it: %(names)s."
        ) % {'names': ' · '.join(names)}
    if base == 'measurements-excluded':
        # 옛 일지의 키 — 왜 빠졌는지가 갈라져 있지 않다. 그때 전부를 "장치
        # 진단 값" 이라 부른 것이 결함이었으므로, 여기서는 **이유를 말하지
        # 않는다**(문장은 열람 시점에 만들어지므로 옛 일지도 함께 고쳐진다).
        names = [measurement_label(k) for k in suffix.split(',') if k]
        return _gettext_safe(
            "These measurements were left out of this journal: %(names)s."
        ) % {'names': ' · '.join(str(n) for n in names)}
    if base == 'stored-weekly-too-large':
        return _gettext_safe(
            "This period was too large to store day by day, so it was saved "
            "in weekly buckets — daily detail is not available for it.")
    return key


def journal_to_jsonable(journal_data):
    """계약 dict → JSON-safe dict. date/datetime 만 isoformat 으로, 그 외 그대로.

    HTML(§10)·MD(§11)·MCP(§12) 가 전부 이 함수의 결과(또는 계약 dict 원본)를
    같은 스키마로 받아야 하므로, 여기서 하는 일은 **직렬화뿐**이다 — 값을
    고르거나 감추지 않는다.
    """
    from datetime import date as _date, datetime as _datetime

    def _walk(v):
        if isinstance(v, _datetime):
            return v.isoformat()
        if isinstance(v, _date):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_walk(x) for x in v]
        if isinstance(v, set):
            return sorted(_walk(x) for x in v)
        return v

    return _walk(journal_data)


# ── Markdown 출력 (§11) ──────────────────────────────────────────────────────
#
# **PDF는 별도 생성기를 만들지 않는다** — HTML(§10)이 브라우저 인쇄로 그
# 자리를 대신한다. Markdown 은 옮겨 적기·다른 도구에 붙여넣기용으로 셋째
# 형식만 낸다.
#
# 이 함수는 **순수 문자열 조립**이다(새 의존성 없음) — HTML(Jinja)이 이미
# 낸 것과 같은 구조(개요 → 단계별 요약 → 버킷 루프)를 파이프 테이블로 옮긴다.
# 값을 고르거나 새로 계산하지 않는다 — §6 계약 dict 를 그대로 읽는다.
#
# `journal_data` 는 이미 **jsonable** 이어야 한다(`GeoJournal.data`, 즉
# `journal_to_jsonable()` 을 거친 뒤의 dict) — 날짜가 문자열이라고 가정한다.

def _md_escape(v):
    """파이프 테이블 셀 안에서 `|`·개행이 표를 깨는 것만 막는다."""
    if v is None:
        return ''
    return str(v).replace('|', '\\|').replace('\n', ' ').strip()


def _md_target_value(t):
    """목표 항목 하나 → 표 셀 문자열. 곡선은 값이 없다는 사실을 그대로 말한다."""
    if t.get('source') == 'method':
        return 'curve: %s' % (t.get('method_name') or '—')
    if t.get('value') is None:
        return ''
    unit = t.get('unit') or ''
    return ('%s %s' % (t['value'], unit)).strip()


def _md_delta_value(e):
    """편차 셀 — §4-5 의 스킵 사유를 사람이 읽을 문구로. 지어내지 않는다."""
    if e.get('target_phases'):
        return phase_delta_text(e['target_phases'])
    if e.get('delta') is not None:
        return str(e['delta'])
    reason = {
        'when': 'day/night target',
        'daily-shape': 'cumulative target',
        'method': 'follows curve',
        'curve-phase': 'follows curve',
        'unobservable': 'no sensor',
        'no-reading': 'no reading',
        'no-target': '',
    }.get(e.get('delta_skipped'), '')
    return reason


def _note_attachment_url(filename):
    """첨부 파일명 → **절대 URL**(`/note_attachment/<filename>`).

    Markdown 은 앱 밖(다른 도구·나중 시점)에서 열릴 수 있으므로 상대 경로가
    아니라 절대 URL이어야 한다 — `render_plot_journal_markdown` 은 단일
    인자(`journal_data`)만 받는 순수 함수라는 계약(§11)이 있어, base URL 을
    인자로 받는 대신 요청 컨텍스트에서 직접 구한다(이 함수는 `format=md`
    라우트 안에서만 불린다 — 배경 스레드에서 부르지 않는다).
    """
    from flask import url_for

    return url_for('routes_general.send_note_attachment', filename=filename,
                   _external=True)


def render_plot_journal_markdown(journal_data, granularity=None):
    """§6 계약 dict → Markdown 문자열(CommonMark 파이프 테이블).

    HTML(§10)과 같은 구조를 따른다: 캐비어트 → 개요 → 단계별 요약(plot만)
    → 버킷 루프(환경/제어/노트). 사진은 `/note_attachment/<filename>` 절대
    URL 링크로 낸다 — 서버가 살아있는 동안만 유효하다는 사실을 문구로 밝힌다.

    `granularity` 를 주면 그 단위로 접어서 낸다(HTML 의 단위 전환과 같은
    `fold_buckets`) — 화면에서 월간으로 보다가 내려받았는데 파일만 일간이면
    같은 문서의 두 판본이 생긴다.
    """
    # 곡선 목표의 주야 Δ 는 **열람 시점 계산**이다(저장 스냅샷은 불변).
    journal_data = with_curve_deltas(journal_data)
    t = journal_data.get('target') or {}
    lines = []

    title = t.get('name') or t.get('unique_id') or _gettext_safe('Journal')
    period = t.get('period') or {}
    lines.append('# %s' % title)
    lines.append('')
    lines.append('%s – %s%s' % (
        period.get('start'), period.get('end'),
        (' (%s)' % _gettext_safe('ongoing')) if period.get('ongoing') else ''))
    lines.append('')

    caveats = journal_data.get('caveats') or []
    if caveats:
        # ⚠ **번역 대상이다.** 예전에는 이 함수 안의 문구가 전부 영어로
        #   고정돼 있었다 — HTML(§10)은 뷰어 언어로 나가는데 MD·ODT 만
        #   영어로 굳었다(실사용 검토). `_gettext_safe` 는 HTTP 열람에서는
        #   뷰어 언어로, 요청 컨텍스트가 없는 MCP 경로에서는 원문(영어)으로
        #   떨어진다 — 기존 규칙 그대로다.
        lines.append('> %s' % _gettext_safe(
            'Photo links below point to `/note_attachment/...` and stay '
            'valid only while the server is running.'))
        for key in caveats:
            lines.append('> - %s' % caveat_text(key))
        lines.append('')

    # ── 용어 ─────────────────────────────────────────────────────────────
    # HTML 은 안내 페이지에서 설명하는데, 내보낸 문서를 받는 쪽에는 그 페이지가
    # 없다 — 여기 없으면 GDD·DLI 가 설명 없는 숫자로만 건너간다.
    _terms = glossary_terms(journal_data)
    if _terms:
        lines.append('## %s' % _gettext_safe('Terms used here'))
        lines.append('')
        for g in _terms:
            lines.append('- **%s** — %s' % (g['term'], g['text']))
        lines.append('')

    # ── 개요 ─────────────────────────────────────────────────────────────
    # 표 왼쪽 열(Type/Item/...)은 HTML(§10)이 이미 쓰는 것과 **같은 msgid**
    # 를 재사용한다 — 각자 새 문구를 만들면 두 판본이 같은 항목을 다른
    # 말로 부르게 된다.
    lines.append('## %s' % _gettext_safe('Overview'))
    lines.append('')
    lines.append('| | |')
    lines.append('|---|---|')
    lines.append('| %s | %s |' % (_gettext_safe('Type'), _md_escape(
        _target_kind_label(t.get('type'), t.get('kind')))))
    if t.get('subject'):
        item = t['subject'] + (' — %s' % t['variety'] if t.get('variety') else '')
        lines.append('| %s | %s |' % (_gettext_safe('Item'), _md_escape(item)))
    loc = t.get('location') or {}
    loc_parts = [v for v in (loc.get('zone_name'), loc.get('facility_name'),
                             loc.get('bay_name')) if v]
    if loc_parts:
        lines.append('| %s | %s |' % (_gettext_safe('Location'),
                                      _md_escape(' · '.join(loc_parts))))
    prog = t.get('program') or {}
    if prog.get('name'):
        lines.append('| %s | %s |' % (_gettext_safe('Program'), _md_escape(
            prog['name'] + (' (v%s)' % prog['version'] if prog.get('version') else ''))))
    if t.get('area_m2') is not None:
        lines.append('| %s | %.1f m² |' % (_gettext_safe('Area'), t['area_m2']))
    lines.append('| %s | %s |' % (_gettext_safe('Time zone'),
                                  _md_escape(t.get('tz_name'))))
    lines.append('')

    # ── 단계별 요약 (plot만) ─────────────────────────────────────────────
    # 단계 절 — HTML(§10)과 **같은 것**을 낸다. 예전에는 여기도 계획표만
    # 옮겨 놓아, 기간과 상관없는 미래 단계까지 전부 실리고 정작 그 기간에
    # 무슨 일이 있었는지는 없었다. 두 출력이 다른 내용을 내면 같은 문서가
    # 아니게 되므로 같은 `stage_sections()` 를 쓴다.
    sections = stage_sections(journal_data)
    if sections:
        lines.append('## %s' % _gettext_safe('Program stages'))
        lines.append('')
        for sec in sections:
            st = sec['stage']
            if not sec['in_period']:
                # 기간 밖(계획) — 있다는 것만 한 줄로.
                lines.append('- %s (%s – %s) — %s' % (
                    _md_escape(st.get('name') or st.get('key')),
                    st.get('starts_on') or '—',
                    st.get('ends_on') or _gettext_safe('ongoing'),
                    _gettext_safe('planned')))
                continue
            lines.append('### %s (%s – %s)' % (
                _md_escape(st.get('name') or st.get('key')),
                sec['starts_on'], sec['ends_on']))
            lines.append('')
            if st.get('guidance'):
                lines.append(_md_escape(st['guidance']))
                lines.append('')

            if sec['env_groups']:
                lines.append('| %s | %s | %s | %s | %s | %s |' % (
                    _gettext_safe('Sensor'), _gettext_safe('Measurement'),
                    _gettext_safe('Min'), _gettext_safe('Max'),
                    _gettext_safe('Avg'), _gettext_safe('Target')))
                lines.append('|---|---|---|---|---|---|')
                for grp in sec['env_groups']:
                    row = grp.get('summary') or grp['sensors'][0]
                    who = ((_gettext_safe('%(n)s sensors')
                           % {'n': grp['summary']['sensor_count']})
                           if grp.get('summary') else grp['sensors'][0].get('sensor'))
                    if row.get('target_phases'):
                        target = phase_target_text(row['target_phases'])
                    elif row.get('follows_curve'):
                        target = (_gettext_safe('curve: %(name)s')
                                  % {'name': row['follows_curve']})
                    else:
                        target = (row.get('target')
                                  if row.get('target') is not None else '')
                    lines.append('| %s | %s | %s | %s | %s | %s |' % (
                        _md_escape(who),
                        _md_escape(grp.get('measurement_label') or grp.get('measurement')),
                        _md_escape(row.get('min')), _md_escape(row.get('max')),
                        _md_escape(row.get('avg')), _md_escape(target)))
                lines.append('')

            missing = [t.get('label') for t in (st.get('targets') or [])
                       if t.get('observable') is False]
            if missing:
                lines.append('_%s %s_' % (_gettext_safe('No sensor for:'),
                                          _md_escape(' · '.join(
                                              str(m) for m in missing))))
                lines.append('')

            if sec['control']:
                lines.append('| %s | %s |' % (_gettext_safe('Device'),
                                              _gettext_safe('Runtime (h)')))
                lines.append('|---|---|')
                for c in sec['control']:
                    lines.append('| %s | %s |' % (_md_escape(c.get('name')),
                                                  _md_escape(c.get('hours'))))
                lines.append('')

            for n in sec['notes']:
                time_str = (n.get('time') or '')[:16].replace('T', ' ')
                head = ('**%s**' % time_str) if time_str else ''
                # 장치에 붙은 기록이면 어느 장치인지 밝힌다 — 화면과 같은 규칙.
                if n.get('anchor_name'):
                    head += (' ' if head else '') + n['anchor_name']
                if n.get('title'):
                    head += (' ' if head else '') + n['title']
                body = n.get('body') or ''
                lines.append('- %s%s' % (head, (' — ' + body) if head and body else body))
            for photo in sec['photos']:
                lines.append('  ![](%s)' % _note_attachment_url(photo['file']))
            if sec['notes'] or sec['photos']:
                lines.append('')

    # ── 버킷 루프 ────────────────────────────────────────────────────────
    #
    # 목표·Δ 는 plot 에서만 값을 가진다(대지·구역은 프로그램이 없다) — HTML
    # 과 같은 판정으로 열을 뺀다. 두 출력이 다른 표를 내면 같은 문서가 아니다.
    show_target = (t.get('type') == 'plot')
    stored = journal_data.get('granularity') or 'day'
    buckets = fold_buckets(journal_data.get('buckets') or [],
                           to=(granularity or stored), granularity=stored,
                           stages=journal_data.get('stages'))

    lines.append('## %s' % _gettext_safe('Daily log'))
    lines.append('')
    for b in buckets:
        lines.append('### %s' % b.get('date_label'))
        lines.append('')
        if b.get('empty'):
            gaps = b.get('gap_count') or 1
            # HTML(§10)과 **같은 msgid** 를 쓴다(줄임표 위치까지) — 각자
            # 새 문구를 지으면 결측 안내가 두 판본에서 다른 말이 된다.
            if gaps > 1:
                lines.append('_%s_' % (_gettext_safe(
                    'No data recorded — %(n)s periods skipped.')
                    % {'n': gaps}))
            else:
                lines.append('_%s_' % _gettext_safe(
                    'No data recorded for this period.'))
            lines.append('')
            continue

        env = b.get('env') or []
        if env:
            headers = [_gettext_safe('Sensor'), _gettext_safe('Measurement'),
                      _gettext_safe('Min'), _gettext_safe('Max'),
                      _gettext_safe('Avg')]
            if show_target:
                headers += [_gettext_safe('Target'), 'Δ']
                lines.append('| %s |' % ' | '.join(headers))
                lines.append('|---|---|---|---|---|---|---|')
            else:
                lines.append('| %s |' % ' | '.join(headers))
                lines.append('|---|---|---|---|---|')
            for e in env:
                # 방위는 방위로, 단위는 사람이 읽는 기호로 — `_display_avg`
                # 가 HTML 과 같은 규칙을 쓴다(방위 오독·원문 단위 키 노출
                # 둘 다 이 한 곳에서 막는다).
                avg_cell = _display_avg(e)
                if e.get('coverage_low'):
                    avg_cell += ' (%s)' % _gettext_safe('partial coverage')
                if e.get('target_phases'):
                    target_cell = phase_target_text(e['target_phases'])
                elif e.get('follows_curve'):
                    target_cell = (_gettext_safe('curve: %(name)s')
                                   % {'name': e['follows_curve']})
                else:
                    target_cell = (str(e['target'])
                                   if e.get('target') is not None else '')
                usage_suffix = ''
                if e.get('usage'):
                    usage_suffix = ' (%s: %s %s)' % (
                        _gettext_safe('usage'), e['usage'].get('amount'),
                        unit_label(e['usage'].get('unit')))
                label = measurement_label(e.get('measurement'), e.get('scope'))
                if show_target:
                    lines.append('| %s | %s%s | %s | %s | %s | %s | %s |' % (
                        _md_escape(e.get('sensor')), _md_escape(label),
                        usage_suffix, _md_escape(e.get('min')), _md_escape(e.get('max')),
                        _md_escape(avg_cell), _md_escape(target_cell),
                        _md_escape(_md_delta_value(e))))
                else:
                    lines.append('| %s | %s%s | %s | %s | %s |' % (
                        _md_escape(e.get('sensor')), _md_escape(label),
                        usage_suffix, _md_escape(e.get('min')), _md_escape(e.get('max')),
                        _md_escape(avg_cell)))
            lines.append('')

        control = b.get('control') or []
        if control:
            lines.append('| %s | %s |' % (_gettext_safe('Device'),
                                          _gettext_safe('Runtime (h)')))
            lines.append('|---|---|')
            for c in control:
                lines.append('| %s | %s |' % (_md_escape(c.get('name')),
                                              _md_escape(c.get('hours'))))
            lines.append('')

        notes = b.get('notes') or []
        for n in notes:
            time_str = (n.get('time') or '')[11:16]
            head = ('**%s**' % time_str) if time_str else ''
            if n.get('anchor_name'):
                head += (' ' if head else '') + n['anchor_name']
            if n.get('title'):
                head += (' ' if head else '') + n['title']
            body = n.get('body') or ''
            lines.append('- %s%s' % (head, (' — ' + body) if head and body else body))
            for fn in (n.get('image_files') or []):
                lines.append('  ![](%s)' % _note_attachment_url(fn))
            for fn in (n.get('other_files') or []):
                lines.append('  [%s](%s)' % (fn, _note_attachment_url(fn)))
        if notes:
            lines.append('')

    lines.append('---')
    lines.append('_%s: %s_' % (_gettext_safe('Generated'),
                               journal_data.get('generated_at')))
    return '\n'.join(lines)


def summarize_for_card(journal_data):
    """완성된 계약 dict → `(title, summary_json)`. 카드 목록이 쓴다.

    ## 왜 완성된 문장을 저장하지 않는가

    계획 초안은 `"{대상명} 일지 ({start}~{end})"` 같은 **완성된 문구**를
    저장하라고 했다. 그러면 그 문구가 **생성 시점의 언어로 굳는다** — 이 앱은
    22개 로케일로 나가고 한 농장을 여러 언어 사용자가 함께 보는 일이 정상이라,
    작년에 한국어로 만든 일지가 일본어 사용자 화면에서도 한국어로 남는다.

    그래서 여기서는 **번역이 필요 없는 것만** 저장한다.

    - `title` : **대상 이름 그대로**(사람이 지은 고유명사라 번역 대상이 아니다).
      "일지 (기간)" 같은 수식은 화면이 붙인다.
    - `summary`: 숫자만 담은 **JSON 문자열**. 화면이 읽어 자기 언어로 문장을
      만든다. 사람이 읽는 문자열을 저장해 두고 화면이 파싱하는 것보다 안전하다
      (구분자·어순이 언어마다 다르다).
    """
    import json as _json

    buckets = journal_data.get('buckets') or []
    target = journal_data.get('target') or {}
    payload = {
        'granularity': journal_data.get('granularity') or 'day',
        'buckets': len(buckets),
        'notes': sum(len(b.get('notes') or []) for b in buckets),
        'empty_buckets': sum(1 for b in buckets if b.get('empty')),
    }
    return (target.get('name') or ''), _json.dumps(payload)


# ── 내보내기: 열린 형식 ──────────────────────────────────────────────────
#
# HTML(화면·인쇄)·Markdown·JSON 에 더해 **표 계산용 CSV** 와 **편집 가능한
# 개방 문서 ODT** 를 낸다.
#
# ⚠ **서버에서 PDF 를 만들지 않는다.** `reportlab` 이 이미 의존성에 있지만,
#   PDF 는 브라우저 인쇄 경로가 이미 담당한다(§10 의 `@media print`). 서버에
#   두 번째 레이아웃을 두면 같은 문서가 경로마다 달라지고, 그 차이는 인쇄해
#   보기 전까지 아무도 모른다 — 이 저장소가 반복해서 겪은 모양이다.

def render_plot_journal_csv(journal_data, granularity=None):
    """§6 계약 dict → CSV 문자열(표 계산·통계용).

    한 줄이 **한 버킷의 한 측정값**이다. 가동시간도 같은 표에 `kind='runtime'`
    으로 넣는다 — 파일을 둘로 나누면 사람이 둘을 맞춰 보아야 하고, 그 맞춤은
    대개 안 된다.

    ⚠ 헤더를 번역하지 않는다. CSV 는 사람이 읽는 문서가 아니라 **다른 도구가
      읽는 자료**라, 열 이름이 로케일마다 바뀌면 그 도구의 수식이 깨진다.
      값 쪽의 이름(센서·측정값)은 저장된 원문 키를 쓴다.
    """
    import csv
    import io as _io

    # 곡선 목표의 주야 Δ 는 **열람 시점 계산**이다(저장 스냅샷은 불변).
    journal_data = with_curve_deltas(journal_data)
    journal_data = journal_data or {}
    stored = journal_data.get('granularity') or 'day'
    buckets = fold_buckets(journal_data.get('buckets') or [],
                           to=(granularity or stored), granularity=stored,
                           stages=journal_data.get('stages'))
    target = journal_data.get('target') or {}

    out = _io.StringIO()
    writer = csv.writer(out)
    # ⚠ 곡선 목표의 주야 값은 **열을 새로 만들어** 낸다. `target` 칸에
    #   '주간 0.79 · 야간 0.44' 같은 문자열을 넣으면 표 계산이 그 열을 통째로
    #   글자로 읽어, 곡선을 안 쓰는 다른 행의 숫자까지 못 쓰게 된다.
    #   새 열은 **뒤에 붙인다** — 기존 열의 자리가 그대로라 지금 이 파일을
    #   읽고 있는 수식이 깨지지 않는다.
    writer.writerow([
        'period', 'kind', 'scope', 'device', 'measurement', 'unit',
        'min', 'max', 'avg', 'target', 'delta', 'samples', 'expected',
        'coverage', 'usage', 'water_l', 'water_estimated',
        'target_day', 'delta_day', 'target_night', 'delta_night',
    ])

    def _phase(row, phase, field):
        return ((row.get('target_phases') or {}).get(phase) or {}).get(field)

    for bucket in buckets:
        label = bucket.get('date_label')
        for row in (bucket.get('env') or []):
            usage = (row.get('usage') or {}).get('amount')
            writer.writerow([
                label, 'env', row.get('scope') or 'indoor',
                row.get('sensor'), row.get('measurement'), row.get('unit'),
                row.get('min'), row.get('max'), row.get('avg'),
                row.get('target'), row.get('delta'),
                row.get('samples'), row.get('expected'), row.get('coverage'),
                usage, '', '',
                _phase(row, 'day', 'target'), _phase(row, 'day', 'delta'),
                _phase(row, 'night', 'target'), _phase(row, 'night', 'delta'),
            ])
        for row in (bucket.get('control') or []):
            # ⚠ **관수량이 빠져 있었다.** HTML·MD·ODT 는 관수량 열을 내는데
            #   CSV 만 없었다 — 표계산으로 물 사용량을 못 뽑는 파일이 됐다.
            #   `scope` 도 밸브에 무의미한 고정값('indoor')이 찍혀 있었다
            #   (제어 행의 `scope` 는 담당 대상 단위 — plot/zone/site — 라
            #   env 행의 '현장/기상대' 와 다른 어휘다. 섞으면 같은 열이 두
            #   뜻을 갖게 되므로 여기서는 비워 둔다).
            water = row.get('water') or {}
            writer.writerow([
                label, 'runtime', '', row.get('name'),
                'runtime', 'h', '', '', row.get('hours'),
                '', '', '', '', '', '',
                water.get('litres', ''),
                ('yes' if water.get('estimated') else '') if water else '',
                '', '', '', '',
            ])
        for note in (bucket.get('notes') or []):
            # ⚠ 장치에 붙은 기록의 **장치 이름은 여기 싣지 않는다.** 이 행은
            #   `device` 칸에 제목, `measurement` 칸에 본문을 넣는 기존 배치를
            #   쓰는데, 이름을 끼우면 그 두 칸의 뜻이 밀린다 — 지금 이 파일을
            #   읽고 있는 수식이 조용히 어긋난다. 이름은 화면·MD·ODT 가 낸다.
            writer.writerow([
                label, 'note', '', note.get('title') or '',
                (note.get('body') or '').replace('\n', ' '),
                '', '', '', '', '', '', '', '', '', '', '', '',
                '', '', '', '',
            ])
    # 대상 정보는 맨 뒤에 한 줄 — 파일만 받아도 무엇에 대한 자료인지 안다.
    writer.writerow([])
    writer.writerow(['# target', target.get('type'), target.get('name'),
                     (target.get('period') or {}).get('start'),
                     (target.get('period') or {}).get('end'),
                     target.get('tz_name')])
    return out.getvalue()


#: ODT 안에 넣는 고정 파일들. `.odt` 는 **ZIP 안의 XML** 이라 새 의존성 없이
#: 표준 라이브러리만으로 만들 수 있다(ISO/IEC 26300 · OpenDocument).
_ODT_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

_ODT_STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
 office:version="1.2">
 <office:styles>
  <style:style style:name="Title" style:family="paragraph">
   <style:text-properties fo:font-size="24pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-bottom="0.4cm"/>
  </style:style>
  <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph">
   <style:text-properties fo:font-size="15pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-top="0.6cm" fo:margin-bottom="0.2cm"/>
  </style:style>
  <style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph">
   <style:text-properties fo:font-size="12pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-top="0.4cm" fo:margin-bottom="0.15cm"/>
  </style:style>
  <style:style style:name="Muted" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:color="#666666"/>
  </style:style>
 </office:styles>
</office:document-styles>
"""


def _odt_esc(value):
    """ODT 본문에 넣을 문자열 — XML 특수문자를 막는다.

    ⚠ 이스케이프를 빠뜨리면 작물 이름의 `&` 하나로 **파일이 통째로 안 열린다**
      (ZIP 은 멀쩡한데 XML 파서가 죽는다). 실패가 "문서가 손상됨" 으로만
      보여서 원인에 닿기 어렵다.
    """
    from xml.sax.saxutils import escape
    return escape('' if value is None else str(value))


def _odt_p(text, style=None):
    style_attr = (' text:style-name="%s"' % style) if style else ''
    return '<text:p%s>%s</text:p>' % (style_attr, _odt_esc(text))


def _odt_table(name, header, rows):
    """머리글 + 행 목록 → ODT 표 XML."""
    cols = len(header)
    out = ['<table:table table:name="%s">' % _odt_esc(name),
           '<table:table-column table:number-columns-repeated="%d"/>' % cols]

    def _row(cells, bold=False):
        parts = ['<table:table-row>']
        for cell in cells:
            parts.append('<table:table-cell office:value-type="string">')
            parts.append(_odt_p(cell, 'Heading_20_2' if bold else None))
            parts.append('</table:table-cell>')
        parts.append('</table:table-row>')
        return ''.join(parts)

    out.append(_row(header, bold=True))
    for row in rows:
        # 열 수를 머리글에 맞춘다 — 짧으면 뒤가 밀리고 길면 파서가 거부한다.
        cells = list(row)[:cols] + [''] * max(0, cols - len(row))
        out.append(_row(cells))
    out.append('</table:table>')
    return ''.join(out)


def render_plot_journal_odt(journal_data, granularity=None):
    """§6 계약 dict → ODT 바이트(OpenDocument Text).

    ## 왜 ODT 인가

    HTML 은 화면, PDF 는 고정본, Markdown 은 옮겨 적기, JSON 은 기계용이다.
    빠진 것은 **받는 사람이 이어서 쓰는 문서**다 — 인증기관이 소견을 덧붙이고
    다음 담당자가 메모를 남기는 자리. ODT 는 ISO/IEC 26300 표준이고
    LibreOffice·Word·Google Docs 가 모두 연다.

    ⚠ **새 의존성을 만들지 않는다.** `.odt` 는 ZIP 안의 XML 이라 표준
      라이브러리(`zipfile`)만으로 만든다. 문서 생성 라이브러리를 하나 더
      들이면 저사양 배포의 설치 목록이 그만큼 길어지고, 그 설치가 깨지면
      일지 전체가 안 나온다.

    ⚠ `mimetype` 은 **첫 항목**이고 **압축하지 않아야** 한다(ODF 규격). 이걸
      어기면 일부 프로그램이 파일 종류를 못 알아본다 — 열리는 데도 있어서
      테스트를 한 곳에서만 하면 통과한다.
    """
    import io as _io
    import zipfile

    # 곡선 목표의 주야 Δ 는 **열람 시점 계산**이다(저장 스냅샷은 불변).
    journal_data = with_curve_deltas(journal_data)
    journal_data = journal_data or {}
    stored = journal_data.get('granularity') or 'day'
    view = granularity or stored
    buckets = fold_buckets(journal_data.get('buckets') or [],
                           to=view, granularity=stored,
                           stages=journal_data.get('stages'))
    t = journal_data.get('target') or {}
    period = t.get('period') or {}

    body = []
    body.append(_odt_p(t.get('name') or t.get('unique_id') or 'Journal', 'Title'))
    body.append(_odt_p('%s – %s' % (period.get('start'), period.get('end'))))

    # ── 개요 ────────────────────────────────────────────────────────────
    body.append(_odt_p('Overview', 'Heading_20_1'))
    overview = [('Type', _target_kind_label(t.get('type'), t.get('kind')))]
    if t.get('subject'):
        item = t['subject'] + ((' — %s' % t['variety']) if t.get('variety') else '')
        overview.append(('Item', item))
    loc = t.get('location') or {}
    where = ' · '.join([v for v in (loc.get('zone_name'), loc.get('facility_name'),
                                    loc.get('bay_name')) if v])
    if where:
        overview.append(('Location', where))
    if t.get('program'):
        overview.append(('Program', t['program'].get('name')))
    if t.get('area_m2') is not None:
        overview.append(('Area', '%.1f m2' % t['area_m2']))
    overview.append(('Time zone', t.get('tz_name')))
    body.append(_odt_table('overview', ['', ''], overview))

    # ── 단계 ────────────────────────────────────────────────────────────
    for sec in stage_sections(journal_data):
        st = sec['stage']
        head = '%s (%s – %s)%s' % (
            st.get('name') or st.get('key'),
            sec['starts_on'] or st.get('starts_on') or '—',
            sec['ends_on'] or st.get('ends_on') or 'ongoing',
            '' if sec['in_period'] else ' · planned')
        body.append(_odt_p(head, 'Heading_20_1'))
        if st.get('guidance'):
            body.append(_odt_p(st['guidance']))
        if sec['in_period'] and sec['env_groups']:
            rows = []
            for grp in sec['env_groups']:
                row = grp.get('summary') or grp['sensors'][0]
                who = ('%d sensors' % grp['summary']['sensor_count']
                       if grp.get('summary') else grp['sensors'][0].get('sensor'))
                rows.append([who,
                             grp.get('measurement_label') or grp.get('measurement'),
                             row.get('min'), row.get('max'),
                             _display_avg(row)])
            body.append(_odt_table('stage-env',
                                   ['Sensor', 'Measurement', 'Min', 'Max', 'Avg'],
                                   rows))
        elif st.get('targets'):
            rows = [[tg.get('label'), _md_target_value(tg)]
                    for tg in st['targets']]
            body.append(_odt_table('stage-targets', ['Target', 'Value'], rows))
        for note in sec.get('notes') or []:
            body.append(_odt_p('%s  %s %s' % (
                (note.get('time') or '')[:16].replace('T', ' '),
                ' '.join(x for x in (note.get('anchor_name'),
                                     note.get('title')) if x),
                note.get('body') or ''), 'Muted'))

    # ── 일자별 기록 ─────────────────────────────────────────────────────
    body.append(_odt_p('Log', 'Heading_20_1'))
    for bucket in buckets:
        body.append(_odt_p(bucket.get('date_label'), 'Heading_20_2'))
        if bucket.get('empty'):
            gaps = bucket.get('gap_count') or 1
            body.append(_odt_p(
                'No data recorded%s.'
                % ((' — %d periods skipped' % gaps) if gaps > 1 else ''), 'Muted'))
            continue
        env = bucket.get('env') or []
        if env:
            rows = [[e.get('sensor'),
                     measurement_label(e.get('measurement'), e.get('scope')),
                     e.get('min'), e.get('max'), _display_avg(e),
                     (phase_target_text(e['target_phases'])
                      if e.get('target_phases') else e.get('target')),
                     (phase_delta_text(e['target_phases'])
                      if e.get('target_phases') else e.get('delta'))]
                    for e in env]
            body.append(_odt_table(
                'env', ['Sensor', 'Measurement', 'Min', 'Max', 'Avg',
                        'Target', 'Delta'], rows))
        control = bucket.get('control') or []
        if control:
            body.append(_odt_table(
                'runtime', ['Device', 'Runtime (h)'],
                [[c.get('name'), c.get('hours')] for c in control]))
        for note in (bucket.get('notes') or []):
            body.append(_odt_p('%s  %s %s' % (
                (note.get('time') or '')[:16].replace('T', ' '),
                ' '.join(x for x in (note.get('anchor_name'),
                                     note.get('title')) if x),
                note.get('body') or ''), 'Muted'))

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content'
        ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
        ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
        ' office:version="1.2">'
        '<office:body><office:text>%s</office:text></office:body>'
        '</office:document-content>' % ''.join(body))

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # ⚠ 첫 항목 · 무압축(ODF 규격). 순서를 바꾸면 파일 종류 판별이 깨진다.
        z.writestr(zipfile.ZipInfo('mimetype'),
                   'application/vnd.oasis.opendocument.text',
                   compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/manifest.xml', _ODT_MANIFEST)
        z.writestr('styles.xml', _ODT_STYLES)
        z.writestr('content.xml', content)
    return buf.getvalue()
