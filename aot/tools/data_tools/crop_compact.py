# -*- coding: utf-8 -*-
"""작물 현황의 기본형 — 구역·작물·경과일수만, 단계 지침·센서·일정은 상세로.

`overview.crops` 는 노지 구획 31건 중 10건만 실어도 10.9KB 였다(구획마다 단계 지침 문장·
종료 점검·프로그램 이름이 붙는다). "어느 구역에 무슨 작물이 며칠째인가" 가 대부분의 질문이라
기본을 그 세 가지로 줄이고, 줄어든 만큼 한 번에 더 많은 구획을 싣는다(상한 40).
단계·지침·센서는 `detail=true`(예전 모양) 또는 `detail` 도구의 plot 로 받는다.

원천은 그대로, 안쪽 도구가 만든 구획 요약에서 칸을 고를 뿐이다(새 값 없음).
"""

#: 접은 모양에서 목록 하나의 기본 상한(예전 10). 줄어든 행 크기에 맞춘다.
COMPACT_LIMIT = 40

_NOTE = ("Crop, place and days since planting only. Stage, programme guidance, sensors and "
         "dates: detail op=plot with the row's id, or this call with detail=true.")


def wants_compact(detail):
    """`detail` 이 명시적으로 False 일 때만 접는다. None(옛 호출)은 예전 모양 그대로."""
    return detail is False or str(detail).strip().lower() in ('false', '0', 'no')


def _place(p):
    if p.get('place'):
        return p['place']
    fac = p.get('facility_name')
    if fac:
        bay = p.get('bay_name')
        return "%s > %s" % (fac, bay) if bay and bay != fac else fac
    return p.get('zone_name')


def compact_plot(p):
    """구획 요약 하나 → {place, crop, [variety], days, id} (시작 전/종료는 날짜가 붙는다)."""
    if not isinstance(p, dict):
        return p
    row = {'place': _place(p), 'crop': p.get('subject') or p.get('name')}
    if p.get('variety'):
        row['variety'] = p['variety']
    if p.get('planned'):
        row['planned'] = True
        row['starts'] = p.get('started_on')
    else:
        row['days'] = p.get('days_since_planted')
    if p.get('ended_on'):
        row['ended_on'] = p['ended_on']
    row['id'] = p.get('unique_id')
    return row


def compact_list(out):
    """`list_plots` 응답 → 접은 모양. 짧은 앞 안내(note)·잘림 표지·summary 문장은 남긴다."""
    if not isinstance(out, dict) or not isinstance(out.get('plots'), list):
        return out
    res = {k: v for k, v in out.items() if k != '_reading'}
    res['plots'] = [compact_plot(p) for p in out['plots']]
    if out['plots']:
        res['_reading'] = [_NOTE]
    return res


#: 접은 모양에서 덜어내는 설명 칸 — 긴 문장(각 200~500자)이고 구획이 있을 때마다 되풀이된다.
_DROP = ('plot_detail', '_reading', 'facility_bay_plot_note', 'open_field_rest_note')


def compact_status(result):
    """`get_crop_status` 응답 → 접은 모양."""
    if not isinstance(result, dict) or result.get('status') != 'success':
        return result
    res = {k: v for k, v in result.items() if k not in _DROP}
    facs = []
    for f in result.get('facilities') or []:
        row = {'facility': f.get('facility_name'), 'crop': f.get('crop'), 'stage': f.get('stage')}
        if f.get('days_after_plot') is not None:
            row['days'] = f['days_after_plot']
        row['id'] = f.get('facility_id')
        facs.append(row)
    res['facilities'] = facs
    for key in ('open_field_plots', 'facility_bay_plots'):
        if isinstance(result.get(key), list):
            res[key] = [compact_plot(p) for p in result[key]]
    if result.get('open_field_plots') or result.get('facility_bay_plots') or facs:
        res['_reading'] = [_NOTE]
    return res
