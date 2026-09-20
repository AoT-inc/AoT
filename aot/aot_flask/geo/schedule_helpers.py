# coding=utf-8
"""장치의 대기 중 예약 조회 — routes_geo_summary·routes_geo_device·routes_geo_schedule 공용 헬퍼.

원래 routes_geo.py 안에 있었으나 여러 라우트 모듈이 함께 쓰므로 이 모듈로 승격했다.
"""
from flask import current_app




def _schedule_display_tz(target_id):
    """예약 시각을 보여줄 시간대 — 장치 로컬(timezone-management.md §6)."""
    try:
        from aot.utils.device_tz import resolve_location_tz
        return resolve_location_tz(target_id)
    except Exception:
        return None


def _fmt_schedule_when(when_utc, tzinfo, now_local):
    """UTC datetime → 표시 문자열. 오늘 'HH:MM' · 내일 'HH:MM(+1)' · 그 외 'M/D HH:MM'."""
    from datetime import timedelta, timezone as _tz
    when = when_utc.replace(tzinfo=_tz.utc)
    if tzinfo is not None:
        when = when.astimezone(tzinfo)
    if when.date() == now_local.date():
        return when.strftime('%H:%M')
    if when.date() == (now_local + timedelta(days=1)).date():
        return when.strftime('%H:%M') + '(+1)'
    return when.strftime('%-m/%-d %H:%M')


def pending_schedules(target_id, limit=20):
    """이 장치에 걸린 예약 — 설정 모달의 '예약 상황' 블록용.

    라벨(_next_schedule_label)은 다음 하나를 문자열로만 준다. 모달은 시작·종료·
    작동 시간을 각각 보여주고 취소까지 해야 하므로 job_id 와 초 단위 값이 필요하다.

    **정본은 서버다.** 예약을 브라우저에 저장하면 같은 예약이 다른 사람에게도,
    같은 사람의 다른 기기에도 보이지 않는다 — 예약은 브라우저를 닫아도 실행되는
    것이므로 화면만 모르는 상태가 된다.
    """
    from datetime import timedelta, timezone as _tz

    from aot.databases.models.scheduler import SchedulerJobMeta
    from aot.utils.time_utils import utc_now

    try:
        now = utc_now().replace(tzinfo=None)
        q = (SchedulerJobMeta.query
             .filter(SchedulerJobMeta.target_id == target_id,
                     SchedulerJobMeta.state.in_(('DRAFT', 'PENDING', 'RUNNING')),
                     SchedulerJobMeta.schedule_time.isnot(None),
                     SchedulerJobMeta.schedule_time >= now)
             .order_by(SchedulerJobMeta.schedule_time.asc()))
        cap = max(1, int(limit))
        rows = q.limit(cap + 1).all()
        # 상한을 넘겼다는 사실을 숨기지 않는다 — 조용히 자르면 화면은 "이게
        # 전부" 라고 말하게 되고, 안 보이는 예약이 시간에 맞춰 장치를 움직인다.
        # 한 건 더 읽어 초과 여부만 보고, 목록 자체는 상한까지만 돌려준다.
        overflow = len(rows) > cap
        rows = rows[:cap]
        if not rows:
            return []

        tzinfo = _schedule_display_tz(target_id)
        now_local = utc_now().astimezone(tzinfo) if tzinfo is not None else utc_now()

        out = []
        for row in rows:
            dur = int(row.duration_sec or 0) or None
            end_utc = row.end_time
            if end_utc is None and dur:
                end_utc = row.schedule_time + timedelta(seconds=dur)
            out.append({
                'job_id': row.id,
                'state': row.state,
                'start': _fmt_schedule_when(row.schedule_time, tzinfo, now_local),
                'start_epoch': int(row.schedule_time.replace(
                    tzinfo=_tz.utc).timestamp()),
                'duration_sec': dur,
                'end': (_fmt_schedule_when(end_utc, tzinfo, now_local)
                        if end_utc is not None else None),
            })
        if overflow:
            out[-1]['more'] = True
        return out
    except Exception:
        current_app.logger.debug('pending schedule lookup failed for %s', target_id)
        return []


def _next_schedule_label(target_id):
    """이 장치의 다음 예약 — 장치 현지 시각 'HH:MM'(오늘이 아니면 'M/D HH:MM').

    pending_schedules 의 첫 줄을 그대로 쓴다 — 라벨과 모달이 같은 조회에서
    나오지 않으면 한쪽만 갱신되는 순간이 생긴다.
    """
    rows = pending_schedules(target_id, limit=1)
    return rows[0]['start'] if rows else None
