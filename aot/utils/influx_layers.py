# coding=utf-8
"""데이터 계층별 Influx 버킷 해석기 (예보·트윈 데이터 관리 D1).

설계: AoT_dev/plans/2026-10-25_twin_data_management_design.md §1·§2·§5.

센서 측정(L0 관측)은 지금처럼 `aot_db` 한 곳에 둔다. 예보 발표본·트윈 산출은 **보존 기간이 다른**
버킷으로 나눈다 — Influx v2 의 보존은 버킷 단위라, 계층마다 기간을 다르게 주려면 나누는 길뿐이다.

| 계층 키 | 버킷(기본 이름) | 담는 것 | 기본 보존 |
|---|---|---|---|
| obs  | `aot_db`   (기존, 안 건드림) | L0 센서 관측, 예보 입력의 옛 채널 | 무기한 |
| fc   | `aot_fc`   | L0 예보 발표본 `fc_hourly`·`fc_daily` | 730일 |
| calc | `aot_calc` | L2 보정 예보, L3 최신 곡선·시나리오·작동 시계열 | 60일 |
| hist | `aot_hist` | L3 검증 보관·머리말·분석 이력, 보정 성적 | 730일 |

## 하위 호환 모드 (`legacy`)

다음 중 하나면 **모든 계층이 `aot_db` 한 곳**에 쓴다(지금과 같다). 호출하는 쪽은 모드를 몰라도 된다.

- Influx v1 이다 / 사용자가 끔(`misc.data_layers.enabled == false`).
- 버킷이 없고 만들 수 없다(토큰 권한 없음 등).

읽기는 `[계층 버킷, aot_db]` 순으로 합친다(`read_buckets`). 같은 시각·같은 계열이 두 곳에 있으면 앞 버킷이
이긴다 — 옛 `aot_db` 의 덮어쓴 최신 곡선보다 새 버킷의 값이 최신이다.

## 비용

해석 결과는 프로세스 안에서 캐시한다(성공 10분, 실패 5분). 쓰기마다 Influx 에 묻지 않는다. 버킷은 처음
필요할 때 한 번 만든다(멱등).
"""
import logging
import threading
import time
from collections import namedtuple

logger = logging.getLogger("aot.influx_layers")

LAYER_OBS = 'obs'
LAYER_FC = 'fc'
LAYER_CALC = 'calc'
LAYER_HIST = 'hist'
LAYERS = (LAYER_OBS, LAYER_FC, LAYER_CALC, LAYER_HIST)
STORED_LAYERS = (LAYER_FC, LAYER_CALC, LAYER_HIST)        # aot_db 밖에 따로 두는 계층

DEFAULT_RETENTION_DAYS = {LAYER_FC: 730, LAYER_CALC: 60, LAYER_HIST: 730}
# 설정에서 고를 수 있는 범위(일). 너무 짧으면 보정·평가 재료가 사라지고 너무 길면 용량이 문제다.
RETENTION_BOUNDS = {LAYER_FC: (30, 3650), LAYER_CALC: (7, 365), LAYER_HIST: (30, 3650)}

# 측정 이름 → 계층. 설계 §1·§3·§6. 여기에 없는 이름은 센서 측정(obs)이다.
_MEASUREMENT_LAYER = {
    # L0 예보 발표본
    'fc_hourly': LAYER_FC, 'fc_daily': LAYER_FC,
    'fc_hourly_meta': LAYER_FC, 'fc_daily_meta': LAYER_FC,
    # L2 보정 예보(최신)
    'fc_hourly_cal': LAYER_CALC, 'fc_daily_cal': LAYER_CALC,
    # L3 최신 곡선 · 시나리오 · 작동 시계열
    'env_twin': LAYER_CALC, 'env_twin_field': LAYER_CALC, 'env_twin_field_h': LAYER_CALC,
    'env_twin_scn': LAYER_CALC, 'env_twin_scn_field': LAYER_CALC, 'env_twin_scn_field_h': LAYER_CALC,
    'env_twin_act': LAYER_CALC,
    # 물 회로 결과 — 실행별(60일)과 닫힌 날의 합계(730일). 모양은 `water_net.result`
    'water_run': LAYER_CALC, 'water_day': LAYER_HIST,
    # L3 검증 보관 · 머리말 · 분석 이력, 보정 성적
    'env_twin_lead': LAYER_HIST, 'env_twin_meta': LAYER_HIST,
    'env_twin_field_lead': LAYER_HIST, 'env_twin_field_meta': LAYER_HIST,
    'env_twin_post': LAYER_HIST, 'env_twin_field_post': LAYER_HIST, 'env_twin_field_post_h': LAYER_HIST,
    'fc_cal_score': LAYER_HIST,
}

# 고정(pin)한 시나리오의 점을 `aot_hist` 로 복사해 두는 측정(설계 §5·§6.3·§6.5). 읽기는 `aot_calc` 뒤에 `aot_hist` 도 잇는다.
PINNABLE_MEASUREMENTS = frozenset(('env_twin_scn', 'env_twin_scn_field', 'env_twin_scn_field_h', 'env_twin_act'))

# mode: 'layered' | 'legacy'.  buckets: 계층 키 → 쓸 버킷 이름(legacy 면 전부 같은 이름).
Layout = namedtuple('Layout', 'mode buckets legacy reason')

_OK_TTL = 600.0
_FAIL_TTL = 300.0
_lock = threading.Lock()
_cache = {'layout': None, 'until': 0.0}


def layer_of_measurement(measurement):
    """측정 이름 → 계층 키. 모르는 이름은 센서 측정(`obs`)이다."""
    return _MEASUREMENT_LAYER.get(str(measurement), LAYER_OBS)


def bucket_name(legacy_bucket, layer):
    """기본 버킷 `aot_db` → 계층 버킷 `aot_fc` 등. `_db` 로 안 끝나면 이름 뒤에 붙인다."""
    if layer == LAYER_OBS:
        return legacy_bucket
    base = legacy_bucket[:-3] if legacy_bucket.endswith('_db') else legacy_bucket
    return '{}_{}'.format(base, layer)


def _legacy_layout(legacy, reason):
    return Layout('legacy', {layer: legacy for layer in LAYERS}, legacy, reason)


def _settings_config():
    """`misc.data_layers` JSON → dict. 읽지 못하면 빈 dict(= 기본값)."""
    try:
        from aot.databases.models import Misc
        from aot.utils.database import db_retrieve_table_daemon
        cfg = getattr(db_retrieve_table_daemon(Misc, entry='first'), 'data_layers', None)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:                                           # noqa: BLE001
        logger.debug('misc.data_layers 를 읽지 못했다 — 기본값', exc_info=True)
        return {}


def desired_retention_days(config=None):
    """계층별 보존 일수 = 설정값(범위 안) 또는 기본값."""
    cfg = _settings_config() if config is None else config
    saved = cfg.get('retention_days') if isinstance(cfg.get('retention_days'), dict) else {}
    out = {}
    for layer, default in DEFAULT_RETENTION_DAYS.items():
        lo, hi = RETENTION_BOUNDS[layer]
        try:
            days = int(saved.get(layer, default))
        except (TypeError, ValueError):
            days = default
        out[layer] = min(hi, max(lo, days))
    return out


def validate_retention(layer, days):
    """설정 저장 전 검사 → 정수 일수. 범위를 벗어나면 ValueError."""
    if layer not in RETENTION_BOUNDS:
        raise ValueError('알 수 없는 계층: {}'.format(layer))
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError('보존 일수는 정수여야 한다')
    lo, hi = RETENTION_BOUNDS[layer]
    if not lo <= days <= hi:
        raise ValueError('{} 보존은 {}~{}일'.format(layer, lo, hi))
    return days


def _retention_rules(days):
    from influxdb_client.domain.bucket_retention_rules import BucketRetentionRules
    return [BucketRetentionRules(type='expire', every_seconds=int(days) * 86400)]


def _client_for_admin():
    """(client, legacy_bucket) 또는 (None, 사유). v2 만 본다."""
    from influxdb_client import InfluxDBClient
    from aot.utils.influx import _influx_connection_params
    params = _influx_connection_params()
    if params is None:
        return None, '측정 DB 설정을 읽지 못했다'
    url, token, legacy, version = params
    if str(version) != '2':
        return None, 'Influx v{} — 버킷 분리는 v2 만'.format(version)
    return InfluxDBClient(url=url, token=token, org='aot', timeout=10000), legacy


def ensure_buckets(client=None, legacy=None, retention=None):
    """계층 버킷이 없으면 만든다(멱등). → {계층: 버킷 이름}. 실패하면 예외를 올린다.

    이미 있는 버킷의 보존은 건드리지 않는다(바꾸는 일은 `apply_retention`).
    """
    own = client is None
    if own:
        client, legacy = _client_for_admin()
        if client is None:
            raise RuntimeError(legacy)
    retention = retention or desired_retention_days()
    try:
        api = client.buckets_api()
        org_id = None
        out = {LAYER_OBS: legacy}
        for layer in STORED_LAYERS:
            name = bucket_name(legacy, layer)
            if api.find_bucket_by_name(name) is None:
                if org_id is None:
                    orgs = client.organizations_api().find_organizations(org='aot')
                    if not orgs:
                        raise RuntimeError("Influx 조직 'aot' 를 찾지 못했다")
                    org_id = orgs[0].id
                api.create_bucket(bucket_name=name, org_id=org_id,
                                  retention_rules=_retention_rules(retention[layer]),
                                  description='AoT data layer {}'.format(layer))
                logger.info('Influx 버킷 %s 를 만들었다(보존 %s일)', name, retention[layer])
            out[layer] = name
        return out
    finally:
        if own:
            client.close()


def apply_retention(retention=None):
    """설정의 보존 일수를 Influx 버킷에 반영한다 → {계층: 일수}. 다른 점만 갱신한다."""
    client, legacy = _client_for_admin()
    if client is None:
        raise RuntimeError(legacy)
    retention = retention or desired_retention_days()
    changed = {}
    try:
        api = client.buckets_api()
        for layer in STORED_LAYERS:
            bucket = api.find_bucket_by_name(bucket_name(legacy, layer))
            if bucket is None:
                continue
            want = int(retention[layer]) * 86400
            have = next((r.every_seconds for r in (bucket.retention_rules or [])), 0)
            if have != want:
                bucket.retention_rules = _retention_rules(retention[layer])
                api.update_bucket(bucket=bucket)
                changed[layer] = retention[layer]
        return changed
    finally:
        client.close()


def _resolve():
    """캐시 없이 한 번 판정한다."""
    cfg = _settings_config()
    try:
        client, legacy = _client_for_admin()
    except Exception as exc:                                    # noqa: BLE001
        from aot.utils.influx import _influx_connection_params
        params = _influx_connection_params()
        return _legacy_layout(params[2] if params else 'aot_db', '연결 실패: {}'.format(exc))
    if client is None:
        from aot.utils.influx import _influx_connection_params
        params = _influx_connection_params()
        return _legacy_layout(params[2] if params else 'aot_db', legacy)
    if cfg.get('enabled') is False:
        client.close()
        return _legacy_layout(legacy, '사용자가 껐다')
    try:
        names = ensure_buckets(client, legacy, desired_retention_days(cfg))
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('계층 버킷을 준비하지 못해 한 버킷 모드로 동작한다: %s', exc)
        return _legacy_layout(legacy, '버킷 준비 실패: {}'.format(exc))
    finally:
        client.close()
    return Layout('layered', names, legacy, '')


def layout(force=False):
    """현재 배치. 캐시 안이면 Influx 에 묻지 않는다."""
    now = time.time()
    with _lock:
        if not force and _cache['layout'] is not None and now < _cache['until']:
            return _cache['layout']
    lay = _resolve()
    with _lock:
        _cache['layout'] = lay
        _cache['until'] = now + (_OK_TTL if lay.mode == 'layered' else _FAIL_TTL)
    return lay


def invalidate():
    """캐시를 비운다(쓰기 실패 뒤, 설정 변경 뒤)."""
    with _lock:
        _cache['layout'] = None
        _cache['until'] = 0.0


def write_bucket(measurement):
    """이 측정을 쓸 버킷 이름."""
    lay = layout()
    return lay.buckets[layer_of_measurement(measurement)]


def read_buckets(measurement):
    """이 측정을 읽을 버킷 이름들 — 우선순위 순. 앞이 이긴다. 고정 시나리오 사본이 있는 측정은 `aot_hist` 도 잇는다."""
    lay = layout()
    primary = lay.buckets[layer_of_measurement(measurement)]
    if primary == lay.legacy:
        return [primary]
    out = [primary]
    if str(measurement) in PINNABLE_MEASUREMENTS and lay.buckets[LAYER_HIST] not in out:
        out.append(lay.buckets[LAYER_HIST])
    return out + [lay.legacy]


def pinned_copy_bucket():
    """고정한 시나리오의 점을 복사해 둘 버킷 이름. 한 버킷 모드면 None(복사할 필요가 없다 — 한 곳에 있다)."""
    lay = layout()
    target = lay.buckets[LAYER_HIST]
    return None if target == lay.legacy else target
