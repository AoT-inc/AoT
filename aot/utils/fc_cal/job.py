# coding=utf-8
"""데몬 예약 작업 `forecast_data.calibrate` — 매일 새벽(대지 현지 시각) 대지마다 한 번 보정을 점검한다 (설계 §4.5).

트윈 플래그와 무관하다(지도·AI 가 같은 예보를 쓰므로 `aot_twin` 서비스 안에 넣지 않는다). 데몬의 제어를 보호한다:

- **한 번에 한 대지씩**, 별도 스레드에서 돈다. 대지·변수마다 **시간 제한**(`Params.time_budget_s`, 기본 60 초 —
  넘기면 그 변수는 건너뛰고 이전 상태 유지).
- **낮은 우선순위**: 리눅스에서는 스레드의 nice 를 올리고, 시스템 부하가 높으면(1 분 평균 부하 > 코어 수 × 0.8)
  이번 점검을 건너뛰고 다음 시간에 다시 본다.
- `HARDWARE_PROFILE=LOW`(파이)는 **축소 동작**: 창 30 일, 부트스트랩 없이 표준오차 기준(더 엄격한 문턱), 검증 시점 이틀 간격,
  이틀에 한 번.

새 설정 칸은 없다. 대지별 방식(자동/항상 켬/끔)은 `fc_calibration_site.mode` 이고 대지 창의 '예보 보정' 줄이 고른다.
점검이 끝나면 같은 시간 틱에서 보정 곡선(L2, `l2.refresh_all`)도 새 발표본으로 갱신한다. 끄려면 환경변수 `AOT_FC_CAL=0`.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

from .common import Params

logger = logging.getLogger('aot.fc_cal')

DUE_HOUR = 3                    # 대지 현지 시각이 이 시 이후면 그날 점검 대상
NICE_INCREMENT = 10
LOAD_LIMIT_PER_CORE = 0.8
_run_lock = threading.Lock()


def enabled():
    return os.environ.get('AOT_FC_CAL', '1') != '0'


def is_low_profile():
    try:
        from aot.config.mcp_config import HARDWARE_PROFILE
        return str(HARDWARE_PROFILE or '').upper() == 'LOW'
    except Exception:                                       # noqa: BLE001
        return False


def params_for_profile(low=None):
    low = is_low_profile() if low is None else low
    return Params().reduced() if low else Params()


def lower_priority():
    """이 스레드를 낮은 우선순위로(리눅스). 안 되면 조용히 넘어간다."""
    try:
        if hasattr(os, 'setpriority') and hasattr(threading, 'get_native_id') and os.uname().sysname == 'Linux':
            tid = threading.get_native_id()
            cur = os.getpriority(os.PRIO_PROCESS, tid)
            os.setpriority(os.PRIO_PROCESS, tid, min(19, cur + NICE_INCREMENT))
            return True
    except Exception:                                       # noqa: BLE001
        logger.debug('[fc_cal] 스레드 우선순위를 낮추지 못함', exc_info=True)
    return False


def busy():
    """제어 루프가 바쁜가 — 1 분 평균 부하가 코어 수 × 0.8 을 넘으면 참."""
    try:
        return os.getloadavg()[0] > (os.cpu_count() or 1) * LOAD_LIMIT_PER_CORE
    except (OSError, AttributeError):
        return False


def site_due(now, tz_name, last_run_at, low=False):
    """이 대지를 지금 점검할 차례인가 — 대지 현지 시각이 `DUE_HOUR` 이후이고, 마지막 점검이 어제 이전(저사양은 이틀 이상)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name or 'UTC')
    except Exception:                                       # noqa: BLE001
        tz = timezone.utc
    local = datetime.fromtimestamp(now, timezone.utc).astimezone(tz)
    if local.hour < DUE_HOUR:
        return False
    if last_run_at is None:
        return True
    last = datetime.fromtimestamp(last_run_at, timezone.utc).astimezone(tz)
    return (local.date() - last.date()).days >= (2 if low else 1)


def run_due(io=None, now=None, params=None, force=False, sleep_between=1.0, skip_busy=True):
    """점검할 차례인 대지를 한 번에 하나씩 점검한다 → [요약 사전]. 앱 컨텍스트 안에서 부른다.

    이미 돌고 있으면(`_run_lock`) 곧바로 빈 목록. `force` 면 차례와 상관없이 모든 대지(부하 판정은 그대로)."""
    from . import store
    from .runner import calibrate_site
    from .sources import InfluxSources
    if not enabled() and not force:
        return []
    if not _run_lock.acquire(blocking=False):
        return []
    try:
        io = io or InfluxSources()
        now = time.time() if now is None else float(now)
        low = is_low_profile()
        p = params or params_for_profile(low)
        out = []
        for sid in io.sites():
            try:
                row = store.site_row(sid)
                if row is not None and row.mode == 'off' and not store.has_used(sid):
                    continue                            # 끈 대지는 쓰던 보정이 있을 때만 한 번 되돌려 알린다
                if not io.has_forecast(sid):
                    continue
                if not force and not site_due(now, io.site_tz(sid), row.last_run_at if row else None, low):
                    continue
                if skip_busy and busy():
                    logger.info('[fc_cal] 시스템 부하가 높아 보정 점검을 다음 시간으로 미룸')
                    break
                out.append(calibrate_site(sid, io, now=now, params=p))
            except Exception:                               # noqa: BLE001 — 한 대지의 오류가 다른 대지를 막지 않는다
                logger.exception('[fc_cal] 대지 점검 실패: %s', sid)
                try:
                    from aot.aot_flask.extensions import db
                    db.session.rollback()
                    store.save_run(sid, now, {'error': 'run_failed'})      # 같은 날 시간마다 되풀이하지 않는다
                except Exception:                           # noqa: BLE001
                    pass
            if sleep_between:
                time.sleep(sleep_between)
        return out
    finally:
        _run_lock.release()


def run_in_thread(app, **kw):
    """데몬이 부르는 진입 — 낮은 우선순위 스레드에서 `run_due` 를 돌린다(이미 돌고 있으면 새로 안 띄운다)."""
    if _run_lock.locked():
        return None

    def _target():
        lower_priority()
        try:
            with app.app_context():
                for s in run_due(**kw):
                    logger.info('[fc_cal] 점검 완료 %s 판 %s, 변경 %s', s.get('site') or '', s.get('rev'),
                                s.get('events'))
                if enabled():
                    from . import l2
                    for sid, n in l2.refresh_all().items():            # 새 발표본이 들어온 대지의 L2 곡선
                        logger.info('[fc_cal] L2 곡선 %s: %d점', sid, n)
        except Exception:                                   # noqa: BLE001
            logger.exception('[fc_cal] 예약 작업 실패')

    t = threading.Thread(target=_target, name='fc_calibration', daemon=True)
    t.start()
    return t
