# -*- coding: utf-8 -*-
"""물 회로 사전 계산 — `measure.water_estimate` 와 `control` 승인 문구가 같은 숫자를 읽는다 (계획서 W5).

켜기 전에 "얼마나 나가나" 를 답한다. 계산은 새로 만들지 않는다: `water_net_link.planned_water` 가 작동 기록을 읽는
계산(`_live_span`)에 **가정한 구간** 만 넣어 푼다. 읽기 전용이다 — 장치를 움직이지 않고 저장하지 않는다.

## 가정 (응답과 승인 문구에 그대로 쓴다)

* 회로의 다른 Output 은 꺼져 있다.
* Output 에 연결된 펌프는 그 밸브와 함께 돈다.
* 탱크는 마지막 수위 측정에서 시작한다.
* 구간은 지금부터 ``seconds`` 초다.

## 실패

`planned_water` 는 실패를 예외로 올린다. 일지처럼 설계값으로 내려앉으면 공급 한계가 조용히 빠지므로, MCP 는 그 예외를 **오류
응답** 으로 바꾼다(`estimate_or_error`). 승인 문구는 실패해도 흐름을 깨지 않고 '예상 물량 없음' 으로 적는다(`approval_note`).
경고(`caveats`)는 알리기만 한다 — 실행을 막지 않는다.
"""
import logging
import time
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

ASSUMPTIONS = ("Other outputs on this circuit stay off; a pump linked to an output runs with its valve; "
               "a tank starts from its last level reading.")
#: 승인 문구가 풀어 볼 후보 구획 수의 상한(재배 중이고 이 Output 이 닿을 수 있는 것만 센다) — 승인은 드물지만 느려지면 안 된다.
MAX_PLOTS_SCANNED = 60
#: 승인 문구에 적는 경고 수
MAX_NOTE_CAVEATS = 3


class EstimateError(Exception):
    """사전 계산을 할 수 없다 — 메시지는 사용자에게 그대로 간다."""


def watering_outputs(plot) -> Dict[str, dict]:
    """구획에 물을 대는 Output → 유량 사실. 일지와 같은 판정(`irrigation_flow_for_plot`)이다."""
    from aot.aot_flask.geo.plot_journal import irrigation_flow_for_plot
    return {oid: flow for oid, flow in (irrigation_flow_for_plot(plot) or {}).items() if flow.get('lph')}


def _candidate_plots(output_ids: Sequence[str]) -> list:
    """Output 들에 물을 받을 수 있는 **재배 중** 구획 후보 — 끝난 작기는 보지 않는다(`plot_context.active_plots`).

    노지 구획은 Output 의 담당 폴리곤이 같은 지도에 있어야 후보가 된다(없으면 일지도 물을 대지 않는 장치로 본다). 시설 구획은
    배관 도면이 따로라 흐름을 풀어 봐야 알 수 있어 후보로 둔다. 물과 무관한 장치(조명·창)는 대개 후보가 없어 바로 끝난다."""
    from aot.space import plot_context
    from aot.aot_flask.geo.plot_journal.mapview import _device_area_shapes

    maps = {getattr(sh, 'geo_id', None) for oid in output_ids for sh in _device_area_shapes(oid)}
    return [plot for plot in plot_context.active_plots()
            if getattr(plot, 'facility_uuid', None) or getattr(plot, 'geo_id', None) in maps]


def plots_for_outputs(output_ids: Sequence[str]) -> List[tuple]:
    """Output 들 → ``[(재배 중인 구획, [그 구획에 물을 대는 Output])]``. 지도를 훑어 위치로 푼다(사람이 지정하지 않는다).

    후보가 `MAX_PLOTS_SCANNED` 를 넘으면 앞에서부터 그만큼만 푼다 — 상한이 물과 무관한 장치의 승인에 문구를 만들지 않는다."""
    wanted = {str(o) for o in output_ids}
    found = []
    for plot in _candidate_plots(list(wanted))[:MAX_PLOTS_SCANNED]:
        hit = [oid for oid in watering_outputs(plot) if oid in wanted]
        if hit:
            found.append((plot, hit))
    return found


def plot_label(plot) -> str:
    """구획을 사람이 부르는 이름 — 구획 이름, 없으면 작물(`subject`). uuid 는 내지 않는다."""
    return str(getattr(plot, 'name', None) or getattr(plot, 'subject', None) or '구획')


def estimate(plot, output_ids: Sequence[str], seconds: float, now: Optional[float] = None) -> dict:
    """``output_ids`` 를 지금부터 ``seconds`` 초 켜면 이 구획이 받는 물. 실패는 예외(`EstimateError` 나 계산 예외)로 올린다."""
    from aot.utils.water_net_link import planned_water

    seconds = float(seconds or 0)
    if seconds <= 0:
        raise EstimateError('a run time is needed (duration_seconds or duration_minutes)')
    is_active = getattr(plot, 'is_active', None)
    if callable(is_active) and not is_active():
        raise EstimateError('this plot is not being grown now (its crop has ended or has not started)')
    flows = watering_outputs(plot)
    ids = [str(o) for o in output_ids if str(o) in flows]
    if not ids:
        raise EstimateError('none of these outputs waters this plot')
    t0 = float(now if now is not None else time.time())
    spans = {oid: [(t0, t0 + seconds)] for oid in ids}
    from aot.utils.timekit import tz_of
    water = planned_water(plot, spans, tz_of(getattr(plot, 'unique_id', None)))                      # 실패는 그대로 올라온다
    res = water.result
    out: dict = {'plot': water.plot_id, 'basis': 'estimated', 'assumptions': ASSUMPTIONS,
                 'window': {'from': t0, 'to': t0 + seconds}, 'outputs': ids,
                 'area_m2': round(water.area_m2, 1) if water.area_m2 else None}
    if res is None or not res['runs']:
        out.update({'litres': None, 'caveats': water.caveats or ['water-no-flow-basis']})
        return out
    totals = res['totals']
    litres = totals['litres']
    out.update({'litres': litres, 'design_litres': totals['design_litres'],
                # 깊이는 실행별 mm 합이 아니라 합친 물량 ÷ 면적이다(반올림이 쌓이지 않는다).
                'mm': round(litres / water.area_m2, 2) if water.area_m2 else None,
                'kwh': totals['kwh'], 'kwh_basis': totals['kwh_basis'],
                'network_rev': res['network_rev'] or None, 'caveats': water.caveats})
    tanks = [c['tank'] for c in res['supply'] if c.get('tank')]
    if tanks:
        out['tank'] = [{k: t.get(k) for k in ('start_l', 'end_l', 'empty_at')} for t in tanks]
    return out


def estimate_or_error(plot, output_ids, seconds, now=None) -> dict:
    """MCP 용 — 예외를 오류 응답으로 바꾼다. 설계값으로 내려앉지 않는다."""
    try:
        return dict({'status': 'success'}, **estimate(plot, output_ids, seconds, now))
    except EstimateError as exc:
        return {'status': 'error', 'plot': getattr(plot, 'unique_id', None), 'message': str(exc)}
    except Exception as exc:                                            # noqa: BLE001
        logger.exception('물 사전 계산 실패 (%s)', getattr(plot, 'unique_id', None))
        return {'status': 'error', 'plot': getattr(plot, 'unique_id', None),
                'message': 'Estimate failed (%s); no design-value fallback was used.' % exc}


# ── 사전 계산 ↔ 실제 결과 ──────────────────────────────────────────────────

def compare(estimated: dict, actual: dict) -> dict:
    """사전 계산(`estimate`)과 같은 구간의 실제 실행 한 건(`delivered_summary` 의 ``recent_runs`` 항목)을 나란히 놓는다.

    ``same_network`` 는 같은 ``network_rev`` 면 True, 다르면 False(그 사이 도면이 바뀐 것이라 비교를 믿지 않는다)다. 둘 중 하나라도
    회로 해시가 없으면(공급 부품이 없는 지도) 모르는 것이라 ``None`` 이다 — False 로 내면 도면이 바뀐 것처럼 읽힌다."""
    a, b = estimated.get('network_rev') or None, actual.get('network_rev') or None
    same = None if a is None or b is None else a == b
    out = {'same_network': same}
    for key in ('litres', 'mm'):
        e, r = estimated.get(key), actual.get(key)
        out[key] = {'estimated': e, 'actual': r,
                    'diff': round(r - e, 2) if e is not None and r is not None else None}
    return out


# ── 승인 문구 ──────────────────────────────────────────────────────────────

def _fmt_l(value) -> str:
    return '{:,.0f}'.format(value)


def _seconds_of(tool_name, args) -> Optional[float]:
    """즉시 켜는 호출의 켜는 시간(초). 모르면(끌 때까지 켬·예약) None."""
    if args.get('state') != 'on':
        return None
    if tool_name == 'operate_device':
        sec = args.get('duration_seconds')
        if not sec and args.get('duration_minutes'):
            sec = float(args['duration_minutes']) * 60
    elif tool_name == 'set_output_state':
        sec = args.get('duration') or args.get('duration_seconds')
    else:
        return None
    try:
        return float(sec) if sec and float(sec) > 0 else None
    except (TypeError, ValueError):
        return None


def approval_note(tool_name, args) -> str:
    """승인 되읽기에 붙이는 한 줄 — 예상 물량, mm, 탱크, 경고. 물 회로와 무관한 장치면 빈 문자열.

    승인 흐름은 바꾸지 않는다: 이 줄은 되읽기 글에 더해질 뿐이고, 실패해도 흐름이 깨지지 않는다('예상 물량 없음')."""
    args = args or {}
    if tool_name not in ('operate_device', 'set_output_state') or args.get('state') != 'on' \
            or not args.get('device_id'):
        return ''
    try:
        plots = plots_for_outputs([str(args['device_id'])])
    except Exception:                                           # noqa: BLE001
        from flask import has_app_context
        if not has_app_context():
            return ''                                           # 앱 밖(단위 시험)에서는 되읽기가 예전 그대로다
        logger.exception('승인 문구: 구획을 찾지 못함')
        return ' — 예상 물량 없음'
    if not plots:
        return ''                                               # 구획에 물을 대지 않는 장치(조명·환기 등)
    seconds = _seconds_of(tool_name, args)
    if seconds is None:
        return ' — 예상 물량 없음(켜는 시간이 정해지지 않음)'
    return ' — ' + '; '.join(_plot_note(plot, ids, seconds) for plot, ids in plots[:2])


def _plot_note(plot, ids, seconds) -> str:
    label = plot_label(plot)
    try:
        est = estimate(plot, ids, seconds)
    except Exception:                                           # noqa: BLE001
        logger.exception('승인 문구: 사전 계산 실패 (%s)', getattr(plot, 'unique_id', None))
        return '%s 예상 물량 없음' % label
    if est.get('litres') is None:
        return '%s 예상 물량 없음' % label
    text = '%s 예상 약 %s L' % (label, _fmt_l(est['litres']))
    if est.get('mm') is not None:
        text += '(%.1f mm)' % est['mm']
    tanks = est.get('tank') or []
    if tanks and tanks[0].get('end_l') is not None:
        text += ', 탱크 남는 물 약 %s L' % _fmt_l(tanks[0]['end_l'])
    text += ' [추정]'
    codes = [c for c in (est.get('caveats') or []) if isinstance(c, str)][:MAX_NOTE_CAVEATS]
    if codes:
        text += ', 경고: ' + ', '.join(codes)
    return text
