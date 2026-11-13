# coding=utf-8
"""데이터 보관 — 하루 한 번 점검과 구획 삭제 규칙 (예보·트윈 데이터 관리 D6).

설계: AoT_dev/plans/2026-10-25_twin_data_management_design.md §5.

## 하루 한 번 점검 (`run_daily`)

데몬이 매시간 불러 주고, 시스템 시간대로 03시 이후이며 마지막 점검이 어제 이전일 때만 돈다.

1. **보존 동기화**: 설정의 보관 일수를 Influx 버킷 보존에 맞춘다(`influx_layers.apply_retention`, 다른 점만 갱신).
2. **만료 시나리오 삭제**: 고정하지 않은 시나리오의 곡선을 `scenario` 태그 조건 삭제로 지우고(`expires_at` = 곡선 만료,
   UTC epoch), 정의는 곡선보다 오래 남긴다(`created_at + 365일`). 시나리오 표가 없으면 아무 일도 하지 않는다.
   분석 실행 색인(`twin_run`)도 분석 이력과 같은 기간이 지난 것을 지운다.
3. **용량 점검**: 계층 버킷의 하루 쌓이는 양으로 보존 기간 동안의 점 수를 어림하고, 저장 공간이 모자라면 경고를 남긴다.
4. **고아 점검**: 지워진 예보 입력의 L0 발표본(`fc_*`)은 **지우지 않고** 개수만 센다. 보존 기간이 지나면 저절로 사라진다.

결과는 `misc.data_layers['check']` 에 남기고 설정 > 일반 '데이터 보관' 칸이 한 줄로 보인다. 새 테이블·설정 칸은 없다.

## 구획 끄기·삭제·모델 판 변경 (설계 §5)

- **끄기**: 새 발행만 멈춘다. 곡선은 보존 기간까지 남는다 — 이 모듈은 아무것도 지우지 않는다.
- **삭제** (`on_target_deleted`): 최신 곡선(`aot_calc`)은 `device_id` 조건 삭제로 바로 지운다. 검증 이력·머리말·분석 이력
  (`aot_hist`)은 사용자가 '이력도 지우기' 를 고를 때만 지운다(`purge_target(history=True)`).
- **물 결과**(`water_run`·`water_day`): 구획을 지우면 실행별 `water_run`(`aot_calc`)은 트윈 설정과 무관하게 지운다(`purge_water`).
  일 합계 `water_day`(`aot_hist`)는 이력이라 '이력도 지우기' 를 고를 때만 지운다.
- **모델 판 변경**: 옛 판 곡선은 지우지 않는다. 지우는 길은 대상 id 로만 나 있고 `model_rev` 로는 없다.
"""
import logging
import shutil
import threading
import time

from aot.utils import influx_layers as L
from aot.utils.timekit import utc_now

logger = logging.getLogger('aot.data_retention')

CHECK_KEY = 'check'
#: 바빠서 연속으로 미룰 수 있는 최대 시간(초).
MAX_DEFER_S = 12 * 3600
USER_LAYERS = (L.LAYER_FC, L.LAYER_HIST)      # 사용자가 바꾸는 '데이터 보관' 한 칸이 정하는 계층
USER_BOUNDS = (30, 3650)                       # 일
WARN_POINTS = 100_000_000                      # 보존 기간 동안 쌓일 점 수가 이를 넘으면 '많이 쌓임'
WARN_FREE_BYTES = 1 << 30                      # 남은 공간 1 GiB 미만이면 경고
WARN_FREE_RATIO = 0.10
SCENARIO_CURVE_MEASUREMENTS = tuple(sorted(L.PINNABLE_MEASUREMENTS))   # 시나리오 곡선 + 작동 시계열(`scenario` 태그)
SCENARIO_DEF_DAYS = 365
_run_lock = threading.Lock()

# 구획(대상)을 지울 때의 두 묶음 — 측정 이름의 계층(influx_layers)이 정한다.
_CURVES = tuple(sorted(m for m, ly in L._MEASUREMENT_LAYER.items()
                       if ly == L.LAYER_CALC and not m.startswith('fc_')))
_HISTORY = tuple(sorted(m for m, ly in L._MEASUREMENT_LAYER.items()
                        if ly == L.LAYER_HIST and not m.startswith('fc_')))


# ── 설정: '데이터 보관' 한 칸 ─────────────────────────────────────────────────

def user_days(config=None):
    """화면에 보이는 보관 일수 = 예보 발표본·분석 이력의 보존(둘은 같은 값). 기본 730."""
    return L.desired_retention_days(config)[L.LAYER_FC]


def validate_days(days):
    """저장 전 검사 → 정수. 범위를 벗어나면 ValueError."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError('days must be an integer')
    lo, hi = USER_BOUNDS
    if not lo <= days <= hi:
        raise ValueError('days must be {}~{}'.format(lo, hi))
    return days


def merged_config(cfg, days):
    """`misc.data_layers` 에 보관 일수를 합친 새 사전. 다른 키(`enabled`·`check`)와 최신 곡선 보존은 그대로 둔다."""
    out = dict(cfg or {})
    saved = dict(out.get('retention_days') or {})
    for layer in USER_LAYERS:
        saved[layer] = int(days)
    out['retention_days'] = saved
    return out


# ── Influx 도우미 ─────────────────────────────────────────────────────────────

def _flux(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def _admin():
    client, legacy = L._client_for_admin()
    if client is None:
        raise RuntimeError(legacy)
    return client, legacy


def _buckets_of(layer_or_measurement, legacy, measurement=False, hist=False):
    """이 측정(또는 계층)을 둔 버킷들 — 새 버킷과 옛 `aot_db` 둘 다. `hist=True` 면 고정 시나리오 사본이 있는
    측정(`influx_layers.PINNABLE_MEASUREMENTS`)의 `aot_hist` 도 넣는다."""
    layer = L.layer_of_measurement(layer_or_measurement) if measurement else layer_or_measurement
    primary = L.bucket_name(legacy, layer)
    out = [primary] if primary == legacy else [primary, legacy]
    if hist and measurement and str(layer_or_measurement) in L.PINNABLE_MEASUREMENTS:
        copy = L.bucket_name(legacy, L.LAYER_HIST)
        if copy not in out:
            out.insert(1, copy)
    return out


def delete_points(client, legacy, measurement, tags, start='1970-01-01T00:00:00Z', stop=None, hist=False):
    """측정 하나를 태그 조건으로 지운다(Influx 조건 삭제는 `_measurement` 와 태그만 받는다) → 시도한 버킷 수.

    `hist=True` 면 고정 시나리오의 `aot_hist` 사본도 지운다(시나리오를 지우거나 이력까지 지울 때만)."""
    import datetime
    stop = stop or (utc_now() + datetime.timedelta(days=3650)).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    pred = ' AND '.join(['_measurement="{}"'.format(_flux(measurement))]
                        + ['{}="{}"'.format(k, _flux(v)) for k, v in sorted(tags.items())])
    n = 0
    for bucket in _buckets_of(measurement, legacy, measurement=True, hist=hist):
        try:
            client.delete_api().delete(start, stop, pred, bucket=bucket, org='aot')
            n += 1
        except Exception:                                       # noqa: BLE001 — 없는 버킷·권한은 다음 버킷으로
            logger.warning('조건 삭제 실패: %s %s', bucket, pred, exc_info=True)
    return n


def _count_last_day(client, bucket):
    q = ('from(bucket: "{}") |> range(start: -1d) |> filter(fn: (r) => r["_field"] == "value") '
         '|> group() |> count()').format(_flux(bucket))
    total = 0
    for tb in client.query_api().query(q):
        for r in tb.records:
            total += int(r.get_value() or 0)
    return total


def _tag_values(client, bucket, measurement, tag, days):
    q = ('import "influxdata/influxdb/schema"\n'
         'schema.measurementTagValues(bucket: "{}", measurement: "{}", tag: "{}", start: -{}d)').format(
        _flux(bucket), _flux(measurement), _flux(tag), int(days))
    out = set()
    for tb in client.query_api().query(q):
        for r in tb.records:
            out.add(str(r.get_value()))
    return out


# ── 구획(대상) 삭제 ───────────────────────────────────────────────────────────

def purge_target(target_id, history=False):
    """대상(구획·시설) 하나의 트윈 점을 지운다 → 지우려 한 (측정, 버킷) 수.

    최신 곡선은 늘 지운다. 검증 이력·머리말·분석 이력은 `history=True` 일 때만 — 고정한 시나리오의 `aot_hist` 사본,
    시나리오 정의(고정분)와 발행 색인도 이때 지운다. 센서 측정과 예보는 건드리지 않는다.
    """
    client, legacy = _admin()
    try:
        n = sum(delete_points(client, legacy, m, {'device_id': str(target_id)}, hist=history) for m in _CURVES)
        if history:
            n += sum(delete_points(client, legacy, m, {'device_id': str(target_id)}) for m in _HISTORY)
    finally:
        client.close()
    try:
        from aot.utils import twin_store
        twin_store.drop_for_target(target_id, pinned=history, runs=history)
    except Exception:                                           # noqa: BLE001 — 표가 없는 환경
        logger.warning('%s 의 시나리오 행을 정리하지 못했다', target_id, exc_info=True)
    return n


def purge_water(target_id):
    """구획의 실행별 물 결과(`water_run`)를 지운다 → 지우려 한 버킷 수. 일 합계(`water_day`)는 이력이라 남긴다.

    트윈 설정이 없는 구획도 물 결과는 쌓이므로 `on_target_deleted` 가 설정 행과 무관하게 부른다."""
    client, legacy = _admin()
    try:
        return delete_points(client, legacy, 'water_run', {'device_id': str(target_id)})
    finally:
        client.close()


def has_history(target_id, days=None):
    """이 대상에 남은 트윈 이력(`aot_hist`)이 있나 — 삭제 확인 창이 '이력도 지우기' 를 보일지 정한다."""
    try:
        client, legacy = _admin()
    except Exception:                                           # noqa: BLE001
        return False
    try:
        days = days or user_days()
        hist_bucket = L.bucket_name(legacy, L.LAYER_HIST)
        # 고정한 시나리오의 사본은 `aot_hist` 에만 이력으로 센다(`aot_calc` 의 곡선은 구획 삭제가 지운다)
        probes = [(m, b) for m in _HISTORY for b in _buckets_of(m, legacy, measurement=True)]
        probes += [(m, hist_bucket) for m in sorted(L.PINNABLE_MEASUREMENTS) if hist_bucket != legacy]
        for m, bucket in probes:
            try:
                if str(target_id) in _tag_values(client, bucket, m, 'device_id', days):
                    return True
            except Exception:                                   # noqa: BLE001 — 버킷이 없으면 없는 것
                continue
        return False
    finally:
        client.close()


def on_target_deleted(scope, target_id):
    """구획('plot')·시설('facility')을 지운 직후 부른다 — 최신 곡선을 치우고 트윈 설정 행을 정리하고, 이력이 남았는지 알려 준다.

    → {'curves': n, 'history_kept': bool}. 트윈 설정을 한 적 없는 대상은 Influx 에 묻지 않는다. 실패해도 삭제 자체를
    막지 않는다(Influx 가 꺼져 있어도 구획은 지워진다).
    """
    out = {'curves': 0, 'history_kept': False}
    if scope == 'plot':
        try:
            purge_water(target_id)
        except Exception:                                       # noqa: BLE001 — Influx 가 꺼져 있어도 삭제는 된다
            logger.warning('%s 의 물 결과를 치우지 못했다', target_id, exc_info=True)
    try:
        from aot.aot_flask.extensions import db
        from aot.utils import twin_config
        row = twin_config.get_row(scope, target_id)
        if row is None:
            return out
        out['history_kept'] = has_history(target_id)
        out['curves'] = purge_target(target_id, history=False)
        db.session.delete(row)
        db.session.commit()
    except Exception:                                           # noqa: BLE001
        logger.warning('%s %s 의 트윈 곡선을 치우지 못했다', scope, target_id, exc_info=True)
    return out


# ── 만료 시나리오 ─────────────────────────────────────────────────────────────

def expire_scenarios(client, legacy, now):
    """고정하지 않은 시나리오의 곡선을 만료 시각이 지나면 지우고, 정의는 곡선보다 오래(365일) 둔다.

    시나리오 표(`twin_scenario`, 설계 §6.2)가 없으면 0 이다. 시각은 UTC epoch 초(Float)다 — `expires_at` 은 곡선 만료,
    정의는 `created_at + 365일` 에 지운다. → {'curves': 곡선을 지운 시나리오 수, 'defs': 정의를 지운 수, 'runs': 색인}
    """
    from sqlalchemy import inspect, text
    from aot.aot_flask.extensions import db
    out = {'curves': 0, 'defs': 0, 'runs': 0}
    if not inspect(db.engine).has_table('twin_scenario'):
        return out
    rows = db.session.execute(text(
        "SELECT id, status FROM twin_scenario WHERE COALESCE(pinned, 0) = 0 "
        "AND expires_at IS NOT NULL AND expires_at < :now AND COALESCE(status, '') != 'curve_expired'"),
        {'now': float(now)}).fetchall()
    for sid, _status in rows:
        for m in SCENARIO_CURVE_MEASUREMENTS:
            delete_points(client, legacy, m, {'scenario': sid})
        db.session.execute(text("UPDATE twin_scenario SET status = 'curve_expired' WHERE id = :i"), {'i': sid})
        out['curves'] += 1
    out['defs'] = db.session.execute(text(
        "DELETE FROM twin_scenario WHERE COALESCE(pinned, 0) = 0 AND status = 'curve_expired' "
        "AND created_at < :old"), {'old': float(now) - SCENARIO_DEF_DAYS * 86400.0}).rowcount or 0
    db.session.commit()
    return out


def expire_runs(now, days):
    """분석 실행 색인(`twin_run`)에서 분석 이력과 같은 기간(`days`일)이 지난 행을 지운다 → 지운 수. 표가 없으면 0."""
    from sqlalchemy import inspect
    from aot.aot_flask.extensions import db
    if not inspect(db.engine).has_table('twin_run'):
        return 0
    from aot.utils import twin_store
    return twin_store.expire_runs(now, days)


# ── 용량·고아 ─────────────────────────────────────────────────────────────────

def free_space(path=None):
    """(남은 바이트, 전체 바이트). 못 재면 (None, None) — 경고하지 않는다."""
    try:
        if path is None:
            from aot.config import DATABASE_PATH
            path = DATABASE_PATH
        u = shutil.disk_usage(path)
        return u.free, u.total
    except Exception:                                           # noqa: BLE001
        return None, None


def capacity(client, legacy, retention):
    """계층 버킷별 하루 쌓이는 점 수와 보존 기간 동안의 어림 → {계층: {per_day, days, est_points}}."""
    out = {}
    for layer in L.STORED_LAYERS:
        try:
            per_day = _count_last_day(client, L.bucket_name(legacy, layer))
        except Exception:                                       # noqa: BLE001 — 버킷이 아직 없으면 0
            per_day = 0
        out[layer] = {'per_day': per_day, 'days': int(retention[layer]),
                      'est_points': per_day * int(retention[layer])}
    return out


def warnings_for(cap, free, total):
    """용량 어림과 디스크로 경고 코드를 낸다(`disk_low`·`many_points`)."""
    out = []
    if free is not None and total and (free < WARN_FREE_BYTES or free / total < WARN_FREE_RATIO):
        out.append('disk_low')
    if any(v['est_points'] > WARN_POINTS for v in cap.values()):
        out.append('many_points')
    return out


def orphan_inputs(client, legacy, days, live_ids):
    """예보 발표본(`fc_*`)에 남은 입력 id 중 지금 없는 것 → 정렬된 목록. 지우지 않는다."""
    seen = set()
    for m in ('fc_hourly', 'fc_daily'):
        try:
            seen |= _tag_values(client, L.bucket_name(legacy, L.LAYER_FC), m, 'device_id', days)
        except Exception:                                       # noqa: BLE001
            continue
    return sorted(seen - set(live_ids))


# ── 하루 한 번 ────────────────────────────────────────────────────────────────

def due(now, tz_name, last_at):
    """03시(시스템 시간대) 이후이고 마지막 점검이 어제 이전이면 참."""
    from aot.utils.fc_cal.job import site_due
    return site_due(now, tz_name, last_at)


def _live_input_ids():
    from aot.databases.models import Input
    return {r.unique_id for r in Input.query.all()}


def _save_check(result):
    from aot.aot_flask.extensions import db
    from aot.databases.models import Misc
    misc = Misc.query.first()
    cfg = dict(misc.data_layers or {})
    cfg[CHECK_KEY] = result
    misc.data_layers = cfg
    db.session.commit()


# @manual geo/map-widget#twin-data-retention
def run_daily(now=None, force=False):
    """하루 한 번 점검을 한다 → 결과 사전(점검 안 할 차례면 None). 앱 컨텍스트 안에서 부른다."""
    from aot.databases.models import Misc
    if not _run_lock.acquire(blocking=False):
        return None
    try:
        now = time.time() if now is None else float(now)
        misc = Misc.query.first()
        cfg = (misc.data_layers if misc is not None else None) or {}
        last = (cfg.get(CHECK_KEY) or {}).get('at')
        if not force and not due(now, getattr(misc, 'timezone', None), last):
            return None
        # 차례가 됐어도 시스템이 바쁘면 다음 시간으로(하루 한 번이라 1시간 늦어도 무해).
        # 연속 12시간 미뤘으면 바빠도 한 번은 돈다 — 디스크 용량 경고가 이 점검에서 나온다.
        from aot.utils import resource_pressure
        if force:
            resource_pressure.clear_deferral('data_retention')    # 손으로 돌렸으면 연속 미룸도 끝
        elif resource_pressure.should_defer('data_retention', MAX_DEFER_S):
            return None
        if cfg.get('enabled') is False or L.layout().mode != 'layered':
            result = {'at': now, 'mode': 'legacy', 'warnings': [], 'orphans': 0}
            _save_check(result)
            return result
        retention = L.desired_retention_days(cfg)
        client, legacy = _admin()
        result = {'at': now, 'mode': 'layered', 'warnings': [], 'orphans': 0}
        try:
            result['retention_changed'] = L.apply_retention(retention)
            result['expired'] = expire_scenarios(client, legacy, now)
            result['expired']['runs'] = expire_runs(now, retention[L.LAYER_HIST])
            cap = capacity(client, legacy, retention)
            free, total = free_space()
            result['capacity'] = cap
            result['free_bytes'] = free
            result['warnings'] = warnings_for(cap, free, total)
            result['orphans'] = len(orphan_inputs(client, legacy, retention[L.LAYER_FC], _live_input_ids()))
        finally:
            client.close()
        _save_check(result)
        if result['warnings']:
            logger.warning('[data_retention] 경고 %s', result['warnings'])
        return result
    finally:
        _run_lock.release()


def run_in_thread(app):
    """데몬이 부르는 진입 — 낮은 우선순위 스레드에서 `run_daily` 를 돌린다."""
    if _run_lock.locked():
        return None

    def _target():
        try:
            from aot.utils.fc_cal.job import lower_priority
            lower_priority()
            with app.app_context():
                run_daily()
        except Exception:                                       # noqa: BLE001 — 데몬은 계속 돈다
            logger.exception('[data_retention] 점검 실패')

    t = threading.Thread(target=_target, name='data_retention', daemon=True)
    t.start()
    return t
