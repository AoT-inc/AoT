# coding=utf-8
"""보정 저장·알림 — SQLite `fc_calibration*` 와 Influx `fc_cal_score` (설계 §4.3·§4.4).

- **판(rev)**: 쓰는 보정이 **실제로 달라질 때만** 새 판을 쓴다 — 어떤 (종류, 변수, 리드대)의 사용 여부가 바뀌거나, 쓰는 계수가
  의미 있게 바뀌었을 때(`material_change`). 매일 새벽 계수를 다시 맞추지만 거의 같으면 판이 늘지 않는다. 판은 지우지 않는다.
- **성적**은 점검 때마다 `fc_cal_score`(`aot_hist`)에 쓴다(판이 같아도). 태그 `var`·`lead_band`·`cal_rev`·`kind`·`l0_kind`,
  `device_id` = 대지 id, 채널 = `common.SCORE_CHANNELS` 순서.
- **알림**: 채택·되돌림마다 `fc_cal_event` 한 줄 + 로그, SMTP 가 설정돼 있으면 관리자에게 메일(기존 경로와 같은 `send_email`).
"""
import json
import logging
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .common import SCORE_CHANNELS, STATUS_CODE, USED_STATES
from .methods import method_for
from aot.utils.timekit import naive_utc, parse_utc, utc_now

logger = logging.getLogger('aot.fc_cal')

Key = Tuple[str, str, str]                       # (kind, var, band)


def _row_model():
    from aot.databases.models import FcCalEvent, FcCalibration, FcCalibrationSite
    return FcCalibrationSite, FcCalibration, FcCalEvent


def site_row(site_id, create=False):
    from aot.aot_flask.extensions import db
    Site, _Cal, _Ev = _row_model()
    row = Site.query.filter_by(site_id=site_id).first()
    if row is None and create:
        row = Site(site_id=site_id, mode='auto', active_rev=0)
        db.session.add(row)
        db.session.flush()
    return row


def site_mode(site_id):
    row = site_row(site_id)
    return row.mode if row is not None and row.mode in ('auto', 'on', 'off') else 'auto'


def set_site_mode(site_id, mode):
    """대지별 자동/항상 켬/끔 (대지 창의 '예보 보정' 줄이 부른다).

    방식이 바뀌면 점검을 곧 다시 하도록 마지막 점검 시각을 비운다(데몬이 매시간 보고 차례가 된 대지를 점검한다 — 새벽까지
    기다리지 않는다). 읽는 쪽(`forecast_series`)은 `off` 를 바로 원본으로 취급하므로 끈 직후에도 값은 원본이다."""
    from aot.aot_flask.extensions import db
    if mode not in ('auto', 'on', 'off'):
        raise ValueError('보정 방식은 auto·on·off 중 하나')
    row = site_row(site_id, create=True)
    changed = row.mode != mode
    row.mode = mode
    if changed:
        row.last_run_at = None
    row.updated_at = naive_utc(utc_now())
    db.session.commit()
    try:
        from aot.space import forecast_series
        forecast_series.clear_cache()                      # 바뀐 방식이 슬라이더·AI·트윈에 바로 보이게
    except Exception:                                       # noqa: BLE001
        logger.debug('예보 계열 캐시 비우기 실패', exc_info=True)
    return row


def entries_of_rev(site_id, rev) -> Dict[Key, dict]:
    """한 판의 모든 항목 → {(kind, var, band): {status, reason, coef, meta, rev …}}."""
    _Site, Cal, _Ev = _row_model()
    if not rev:
        return {}
    out = {}
    for r in Cal.query.filter_by(site_id=site_id, rev=rev).all():
        out[(r.kind, r.var, r.band)] = {
            'kind': r.kind, 'var': r.var, 'band': r.band, 'status': r.status, 'reason': r.reason,
            'method': r.method, 'coef': r.coef_dict() or None, 'meta': r.meta_dict(), 'rev': r.rev,
            'window_start': r.window_start, 'window_end': r.window_end}
    return out


def active_entries(site_id) -> Dict[Key, dict]:
    row = site_row(site_id)
    return entries_of_rev(site_id, row.active_rev) if row is not None else {}


def has_used(site_id) -> bool:
    """쓰는 판에 실제로 쓰는 보정이 하나라도 있나."""
    return any(_used(e) for e in active_entries(site_id).values())


def _used(e):
    return bool(e) and e.get('status') in USED_STATES and bool(e.get('coef'))


def changed_effect(prev: Dict[Key, dict], new: Iterable[dict]) -> bool:
    """사용하는 보정이 달라졌나 — 사용 여부가 바뀌었거나, 쓰는 계수가 의미 있게 바뀌었다."""
    new_by = {(e['kind'], e['var'], e['band']): e for e in new}
    for key in set(prev) | set(new_by):
        a, b = prev.get(key), new_by.get(key)
        ua, ub = _used(a), _used(b)
        if ua != ub:
            return True
        if ua and ub and method_for(key[0], key[1]).material_change(a['coef'], b['coef']):
            return True
    return False


def write_rev(site_id, entries: List[dict], now, l0_kind='actual') -> int:
    """새 판을 쓴다 → 판 번호. 대지 행의 `active_rev` 를 올린다."""
    from aot.aot_flask.extensions import db
    _Site, Cal, _Ev = _row_model()
    row = site_row(site_id, create=True)
    top = db.session.query(db.func.max(Cal.rev)).filter(Cal.site_id == site_id).scalar() or 0
    rev = int(top) + 1
    stamp = naive_utc(parse_utc(now))
    for e in entries:
        db.session.add(Cal(
            site_id=site_id, rev=rev, kind=e['kind'], var=e['var'], band=e['band'], status=e['status'],
            reason=e.get('reason'), method=e.get('method'),
            coef=json.dumps(e['coef'], ensure_ascii=False) if e.get('coef') else None,
            meta=json.dumps(e.get('meta') or {}, ensure_ascii=False, default=_json_default),
            window_start=e.get('window_start'), window_end=e.get('window_end'), l0_kind=l0_kind,
            created_at=stamp))
    row.active_rev = rev
    row.updated_at = stamp
    db.session.flush()
    return rev


def _json_default(o):
    if isinstance(o, float) and (o != o or o in (float('inf'), float('-inf'))):
        return None
    return str(o)


def save_run(site_id, now, summary: dict):
    """마지막 점검 시각·요약을 대지 행에 남긴다(판은 건드리지 않는다)."""
    from aot.aot_flask.extensions import db
    row = site_row(site_id, create=True)
    row.last_run_at = float(now)
    row.last_result = json.dumps(summary, ensure_ascii=False, default=_json_default)
    row.updated_at = naive_utc(parse_utc(now))
    db.session.commit()
    return row


# ── 성적 → Influx ────────────────────────────────────────────────────────────

def _score_value(entry, name):
    m = (entry.get('meta') or {}).get('metrics') or {}
    meta = entry.get('meta') or {}
    if name == 'status':
        return float(STATUS_CODE.get(entry['status'], 0))
    if name == 'ci_lo':
        return meta.get('ci_lo')
    if name == 'ci_hi':
        return meta.get('ci_hi')
    if name == 'recent_skill':
        return (meta.get('recent') or {}).get('skill')
    if name == 'days':
        return meta.get('days')
    return m.get(name)


def score_points(site_id, entries: Iterable[dict], rev, now, l0_kind='actual'):
    from aot.utils.fc_store import Pt
    pts = []
    for e in entries:
        tags = {'var': e['var'], 'lead_band': e['band'], 'cal_rev': str(int(rev)), 'kind': e['kind'],
                'l0_kind': l0_kind}
        for ch, name in enumerate(SCORE_CHANNELS):
            v = _score_value(e, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float('inf'), float('-inf')):
                continue
            pts.append(Pt('fc_cal_score', site_id, ch, float(now), float(v), tags))
    return pts


def write_scores(site_id, entries, rev, now, l0_kind='actual', writer: Optional[Callable] = None) -> int:
    """성적 점을 쓴다. 실패는 삼킨다(보정 자체를 막지 않는다)."""
    pts = score_points(site_id, entries, rev, now, l0_kind)
    if not pts:
        return 0
    try:
        if writer is None:
            from aot.utils import influx
            writer = influx.write_influxdb_points
        return int(writer(pts))
    except Exception:                                       # noqa: BLE001
        logger.warning('보정 성적 쓰기 실패 — 건너뜀 (%s)', site_id, exc_info=True)
        return 0


# ── 알림 ─────────────────────────────────────────────────────────────────────

def _fmt(x, d=2):
    return '—' if x is None else ('%.*f' % (d, x))


def event_text(site_name, ev: dict) -> Tuple[str, str]:
    """사람이 읽는 제목·본문. 성적은 대표성 차이를 항상 붙인다(설계 §4.3 표시)."""
    d = ev['detail']
    word = '채택' if ev['event'] == 'adopted' else '되돌림'
    unit = '일별' if ev['kind'] == 'd' else '시간별'
    subject = '[AoT] 예보 보정 %s — %s %s %s %s' % (word, site_name, unit, ev['var'], ev['band'])
    m = d.get('metrics') or {}
    lines = ['대지: %s' % site_name, '대상: %s 예보 %s, 리드 %s' % (unit, ev['var'], ev['band']),
             '보정 판: %s' % ev['rev'], '이유: %s' % d.get('reason')]
    if m.get('n'):
        lines.append('전진 검증(%s일, %s쌍): 오차 %s → %s, 개선율 %s (신뢰구간 하한 %s)' % (
            d.get('days'), m['n'], _fmt(m.get('mae_raw')), _fmt(m.get('mae_cal')), _fmt(m.get('skill'), 3),
            _fmt(d.get('ci_lo'), 3)))
    rec = d.get('recent') or {}
    if rec.get('skill') is not None:
        lines.append('최근 %s일 개선율: %s' % (rec.get('days'), _fmt(rec['skill'], 3)))
    lines.append('관측: %s' % (d.get('obs') or '대지 기상원'))
    lines.append('※ 관측소는 한 점이고 예보는 격자 칸 평균이라 거리·고도·가림에 따른 대표성 차이가 있습니다. '
                 '보정 전 값은 원본으로 언제든 볼 수 있습니다.')
    return subject, '\n'.join(lines)


def _email_admins(subject, body):
    try:
        from aot.databases.models import SMTP, User
        smtp = SMTP.query.first()
        if smtp is None:
            return 0
        from aot.utils.send_data import send_email
        sent = 0
        for u in User.query.filter_by(role_id=1).all():
            if not u.email:
                continue
            if send_email(smtp.host, smtp.protocol, smtp.port, smtp.user, smtp.passw, smtp.email_from,
                          u.email, body, subject) == 0:
                sent += 1
        return sent
    except Exception:                                       # noqa: BLE001
        logger.warning('보정 알림 메일 실패 — 기록만 남김', exc_info=True)
        return 0


def add_events(site_id, site_name, rev, events: List[dict], now, email=True) -> int:
    """알림 기록 + 로그 + (SMTP 가 있으면) 메일. `events` 는 {event, kind, var, band, detail}."""
    from aot.aot_flask.extensions import db
    _Site, _Cal, Ev = _row_model()
    stamp = naive_utc(parse_utc(now))
    for ev in events:
        ev = dict(ev, rev=rev)
        db.session.add(Ev(site_id=site_id, rev=rev, event=ev['event'], kind=ev['kind'], var=ev['var'],
                          band=ev['band'], created_at=stamp,
                          detail=json.dumps(ev['detail'], ensure_ascii=False, default=_json_default)))
        subject, body = event_text(site_name or site_id, ev)
        logger.info('%s\n%s', subject, body)
        if email:
            _email_admins(subject, body)
    db.session.flush()
    return len(events)


def recent_events(site_id=None, limit=50, unacked_only=False):
    _Site, _Cal, Ev = _row_model()
    q = Ev.query
    if site_id:
        q = q.filter_by(site_id=site_id)
    if unacked_only:
        q = q.filter_by(acked=False)
    return q.order_by(Ev.id.desc()).limit(limit).all()
