# coding=utf-8
"""트윈 시나리오·분석 실행 저장소 (예보·트윈 데이터 관리 D7, 설계 §6).

SQLite `twin_scenario`(정의·계보)·`twin_run`(발행 색인)과, 그 짝인 Influx 곡선(`env_twin_scn*`·`env_twin_act`)의 수명을
함께 다룬다. 쓰는 쪽(장치 효과 세션의 시나리오 실행기, 트윈 서비스)과 읽는 쪽(그래프, 읽기 API)이 쓰는 면은 이 모듈이다.

## 수명 규칙 (D6 `data_retention` 이 기대는 것)

- `expires_at` = **곡선 만료 시각**(만든 때 + 30일). 고정하면 NULL. 하루 점검이 지난 미고정 시나리오의 곡선을 `scenario` 태그
  조건 삭제로 지우고 상태를 `curve_expired` 로 바꾼다. 정의는 `created_at + 365일` 까지 남는다.
- 고정(`pin_scenario`): 곡선을 `aot_hist` 로 **복사한 뒤에** 고정으로 표시한다(복사에 실패하면 고정하지 않는다).
  아직 도는 중이면 표시만 하고, 끝날 때(`mark_done`) 복사한다. 곡선이 이미 만료된 시나리오는 고정할 수 없다.
- 대상당 20건(`SCENARIO_LIMIT`)을 넘기면 만들지 않고 오래된 미고정 시나리오를 지우자고 제안한다(계열 수를 묶는다).
- 분석 실행 색인 `twin_run` 은 발행 머리말에서 쓰는 쪽이 채우고(`record_run_from_points`), 분석 이력(`aot_hist`)과 같은 기간
  (설정의 '데이터 보관', 기본 730일)이 지나면 하루 점검이 지운다(`expire_runs`).

Influx 를 못 쓰는 환경(꺼짐·v1)에서도 정의 쪽(SQLite)은 동작한다 — 곡선 복사·삭제만 건너뛴다.
"""
import json
import logging
import secrets
import time
from typing import Dict, List, Mapping, Optional, Sequence

from aot.twin import output as O
from aot.twin.types import Point, TargetKind
from aot.utils import influx_layers as L

logger = logging.getLogger('aot.twin_store')

SCENARIO_LIMIT = 20                    # 대상당
CURVE_DAYS = 30                        # 고정하지 않은 시나리오 곡선
DEF_DAYS = 365                         # 곡선이 만료된 뒤에도 정의를 두는 기간(생성 시각 기준)
LABEL_MAX = 120
OVERRIDES_MAX_BYTES = 64 * 1024
OVERRIDE_KEYS = ('actuators', 'weather', 'supply')
EFFECT_STATUSES = ('modeled', 'partial', 'unmodeled', 'unknown', 'supply')
EFFECT_SOURCES = ('measured', 'estimated', 'unknown')
SCENARIO_MEASUREMENTS = tuple(sorted(L.PINNABLE_MEASUREMENTS))
RUN_FIT_KEYS = ('sync_rmse_T', 'sync_rmse_RH', 'sync_rmse_T_1h', 'sync_rmse_theta_1d', 'sync_rmse_Ts_1d',
                'coverage_80', 'ensemble_size', 'stale_s', 'horizon_h', 'horizon_d', 'obs_n', 'valid_until')


class StoreError(Exception):
    """호출한 쪽이 고쳐야 하는 잘못(검사 실패·없음·충돌). `status` 는 API 가 그대로 쓰는 HTTP 코드."""

    def __init__(self, message, status=422, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


# ── 검사 ─────────────────────────────────────────────────────────────────────

def validate_target(kind, target_id):
    if kind not in ('field', 'facility'):
        raise StoreError('target kind must be field or facility')
    target_id = str(target_id or '').strip()
    if not target_id or len(target_id) > 80:
        raise StoreError('target id is required')
    return kind, target_id


def validate_overrides(overrides):
    """`overrides` 는 불투명 JSON 이다 — 모양(사전 + 세 목록)과 크기만 본다. 뜻은 장치 효과 세션 소유."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise StoreError('overrides must be an object')
    bad = [k for k in overrides if k not in OVERRIDE_KEYS]
    if bad:
        raise StoreError('unknown overrides key: {}'.format(', '.join(sorted(map(str, bad)))))
    for k in OVERRIDE_KEYS:
        if k in overrides and not isinstance(overrides[k], list):
            raise StoreError('overrides.{} must be a list'.format(k))
    if len(json.dumps(overrides, ensure_ascii=False)) > OVERRIDES_MAX_BYTES:
        raise StoreError('overrides is too large')
    return overrides


def validate_effects(effects):
    """`effects` = [{kind, channel, status, source, caveats?}] — 목록표에 없는 종류는 status=unknown, channel=null."""
    if effects is None:
        return []
    if not isinstance(effects, list):
        raise StoreError('effects must be a list')
    out = []
    for e in effects:
        if not isinstance(e, dict):
            raise StoreError('effects items must be objects')
        status = e.get('status', 'unknown')
        source = e.get('source', 'unknown')
        if status not in EFFECT_STATUSES or source not in EFFECT_SOURCES:
            raise StoreError('invalid effects status/source')
        row = {'kind': e.get('kind'), 'channel': e.get('channel'), 'status': status, 'source': source}
        if e.get('caveats'):                                # 밸브 가정의 공급 주의 — 메모는 저장되지 않으니 여기에 남긴다
            row['caveats'] = [str(c) for c in e['caveats']]
        out.append(row)
    return out


# ── 시나리오 ─────────────────────────────────────────────────────────────────

def check_runnable(kind, base_mode, future_input_mode, overrides):
    """실행기가 받을 수 있는 정의인가(E2) — 가정의 뜻(채널·기상 변수·연산·값 범위)과 미래 입력 방식. 틀리면 `StoreError(422)`.
    이 시설·구획에 그 장치가 있는지는 여기서 알 수 없어 실행 때 확인한다(없으면 `failed` + 이유)."""
    from aot.functions.utils.twin_effects import scenario as SC
    try:
        SC.check_modes(base_mode, future_input_mode)
        SC.validate(overrides, kind)
    except SC.ScenarioError as e:
        raise StoreError(str(e))


def _models():
    from aot.databases.models import TwinRun, TwinScenario
    return TwinScenario, TwinRun


def _db():
    from aot.aot_flask.extensions import db
    return db


def new_scenario_id():
    TwinScenario, _ = _models()
    for _i in range(20):
        sid = secrets.token_hex(4)
        if sid != O.BASELINE and TwinScenario.query.filter_by(id=sid).first() is None:
            return sid
    raise StoreError('could not allocate a scenario id', 500)


def run_id_of(target_id, t0):
    return '{}:{}'.format(int(float(t0)), target_id)


def latest_run(kind, target_id, ok_only=True):
    """대상의 가장 최근 발행 색인(정상 `status < 2` 만). 없으면 None."""
    _, TwinRun = _models()
    q = TwinRun.query.filter_by(target_kind=kind, target_id=str(target_id))
    if ok_only:
        q = q.filter(TwinRun.status < 2)
    return q.order_by(TwinRun.t0.desc()).first()


def suggest_oldest_unpinned(kind, target_id, count=1):
    TwinScenario, _ = _models()
    rows = (TwinScenario.query.filter_by(target_kind=kind, target_id=str(target_id), pinned=False)
            .order_by(TwinScenario.created_at.asc()).limit(max(1, count)).all())
    return [r.id for r in rows]


def create_scenario(kind, target_id, label=None, base_mode='hold', future_input_mode='hold', overrides=None,
                    effects=None, base_run=None, now=None):
    """시나리오 정의를 만든다(`queued`). 실행은 시나리오 실행기가 한다 → TwinScenario 행.

    대상당 20건이 차 있으면 `StoreError(409, suggest_delete=[…])`. `base_run` 을 안 주면 대상의 가장 최근 정상 발행.
    """
    TwinScenario, _ = _models()
    kind, target_id = validate_target(kind, target_id)
    if base_mode not in ('hold', 'schedule', 'policy'):
        raise StoreError('base_mode must be hold, schedule or policy')
    if future_input_mode not in ('hold', 'schedule', 'policy', 'whatif'):
        raise StoreError('future_input_mode must be hold, schedule, policy or whatif')
    overrides = validate_overrides(overrides)
    check_runnable(kind, base_mode, future_input_mode, overrides)
    effects = validate_effects(effects)
    label = (str(label).strip() if label is not None else '')[:LABEL_MAX] or None
    now = time.time() if now is None else float(now)
    have = TwinScenario.query.filter_by(target_kind=kind, target_id=target_id).count()
    if have >= SCENARIO_LIMIT:
        raise StoreError('scenario limit reached for this target', 409, limit=SCENARIO_LIMIT,
                         suggest_delete=suggest_oldest_unpinned(kind, target_id, have - SCENARIO_LIMIT + 1))
    if base_run is None:
        run = latest_run(kind, target_id)
        base_run = run.run_id if run is not None else None
    row = TwinScenario(id=new_scenario_id(), target_kind=kind, target_id=target_id, label=label, created_at=now,
                       requested_at=now, status='queued', pinned=False, expires_at=now + CURVE_DAYS * 86400.0,
                       base_run=base_run, base_mode=base_mode, future_input_mode=future_input_mode,
                       overrides=json.dumps(overrides, ensure_ascii=False),
                       effects=json.dumps(effects, ensure_ascii=False), schema_version=1)
    db = _db()
    db.session.add(row)
    db.session.commit()
    return row


def get_scenario(scenario_id):
    TwinScenario, _ = _models()
    return TwinScenario.query.filter_by(id=str(scenario_id)).first()


def list_scenarios(kind=None, target_id=None):
    TwinScenario, _ = _models()
    q = TwinScenario.query
    if kind:
        q = q.filter_by(target_kind=kind)
    if target_id:
        q = q.filter_by(target_id=str(target_id))
    return q.order_by(TwinScenario.created_at.desc()).all()


def _summaries(overrides):
    """`overrides` 에서 계산해 응답에 싣는 요약 — 두 번 저장하지 않는다(설계 §6.2)."""
    weather = [{'var': w.get('var'), 'op': w.get('op'), 'value': w.get('value'), 'from': w.get('t0'),
                'to': w.get('t1')} for w in overrides.get('weather') or [] if isinstance(w, dict)]
    plan = [{'channel': a.get('channel_or_device_uid', a.get('channel')), 'from': a.get('t0'), 'to': a.get('t1'),
             'value': a.get('value'), 'unit': a.get('unit')}
            for a in overrides.get('actuators') or [] if isinstance(a, dict)]
    return weather, plan


def scenario_dict(row, base_t0=None):
    """API 응답용 사전. `base_t0` = base_run 을 푼 발행의 t0 epoch(그래프의 '낡음' 판정: ≠ 현재 t0)."""
    overrides = row.overrides_dict()
    weather, plan = _summaries(overrides)
    effects = row.effects_list()
    return {
        'id': row.id, 'target': {'kind': row.target_kind, 'id': row.target_id}, 'label': row.label,
        'created_at': row.created_at, 'requested_at': row.requested_at, 'finished_at': row.finished_at,
        'status': row.status, 'pinned': bool(row.pinned), 'expires_at': row.expires_at,
        'def_expires_at': None if row.pinned else row.created_at + DEF_DAYS * 86400.0,
        'base_run': row.base_run, 'base_t0': base_t0,
        'base_mode': row.base_mode, 'future_input_mode': row.future_input_mode,
        'overrides': overrides, 'weather_assumption': weather, 'actuator_plan': plan, 'effects': effects,
        'effects_unmodeled': sum(1 for e in effects if e.get('status') not in ('modeled', 'supply')),
        'model_rev': row.model_rev, 'cal_rev': row.cal_rev, 'fc_issue_epoch': row.fc_issue_epoch,
        'weather_src': row.weather_src, 'obs_origin': row.obs_origin, 'fail_reason': row.fail_reason,
        'layer': 'L3', 'schema_version': row.schema_version or 1,
    }


def base_t0_map(rows):
    """시나리오 행들의 {base_run: t0}. 색인이 이미 지워졌으면 run_id 앞 숫자(= t0 epoch)로 푼다."""
    _, TwinRun = _models()
    ids = {r.base_run for r in rows if r.base_run}
    found = {r.run_id: r.t0 for r in TwinRun.query.filter(TwinRun.run_id.in_(ids)).all()} if ids else {}
    for rid in ids - set(found):
        try:
            found[rid] = float(rid.split(':', 1)[0])
        except ValueError:
            pass
    return found


def mark_running(scenario_id):
    row = get_scenario(scenario_id)
    if row is not None and row.status in ('queued', 'failed'):
        row.status, row.fail_reason = 'running', None
        _db().session.commit()
    return row


def claim_next_queued(now=None):
    """가장 오래 기다린 `queued` 시나리오를 `running` 으로 바꿔 돌려준다(실행기 하나가 차례로 처리한다). 없으면 None."""
    TwinScenario, _ = _models()
    row = (TwinScenario.query.filter_by(status='queued')
           .order_by(TwinScenario.requested_at.asc(), TwinScenario.created_at.asc()).first())
    if row is None:
        return None
    row.status, row.fail_reason = 'running', None
    _db().session.commit()
    return row


def requeue_running():
    """실행기가 다시 떴을 때 `running` 으로 남은 것(이전 프로세스가 도중에 멈춤)을 `queued` 로 되돌린다 → 되돌린 수.
    실행기는 한 프로세스뿐이라 시작 때의 `running` 은 모두 낡은 것이다."""
    TwinScenario, _ = _models()
    rows = TwinScenario.query.filter_by(status='running').all()
    for r in rows:
        r.status = 'queued'
    if rows:
        _db().session.commit()
    return len(rows)


def requeue(scenario_id, now=None):
    """끝났거나 실패한(또는 곡선이 만료된) 시나리오를 다시 실행 대기로 — 새 기본 예측 위에서 다시 돌린다 → 행.
    실행 중·대기 중이거나 고정된 시나리오는 409(고정은 기록이라 덮어쓰지 않는다). 옛 곡선은 지우고(격자가 달라 섞이지 않게)
    기준 발행(`base_run`)은 대상의 최근 정상 발행으로 갱신한다."""
    row = get_scenario(scenario_id)
    if row is None:
        raise StoreError('scenario not found', 404)
    if row.status in ('queued', 'running'):
        raise StoreError('scenario is already %s' % row.status, 409)
    if row.pinned:
        raise StoreError('a pinned scenario is a record and is not re-run', 409)
    now = time.time() if now is None else float(now)
    run = latest_run(row.target_kind, row.target_id)
    delete_curves(scenario_id, include_hist=False)
    row.status, row.fail_reason, row.finished_at, row.requested_at = 'queued', None, None, now
    row.expires_at = now + CURVE_DAYS * 86400.0
    if run is not None:
        row.base_run = run.run_id
    _db().session.commit()
    return row


def mark_done(scenario_id, model_rev=None, cal_rev=None, fc_issue_epoch=None, weather_src=None, obs_origin=None,
              effects=None, now=None, base_run=None):
    """실행기가 곡선을 다 쓴 뒤 부른다 — 계보를 적고 `done`. 고정돼 있으면 곡선을 `aot_hist` 로 복사한다."""
    row = get_scenario(scenario_id)
    if row is None:
        raise StoreError('scenario not found', 404)
    now = time.time() if now is None else float(now)
    row.status, row.finished_at, row.fail_reason = 'done', now, None
    for k, v in (('model_rev', model_rev), ('cal_rev', cal_rev), ('fc_issue_epoch', fc_issue_epoch),
                 ('weather_src', weather_src), ('obs_origin', obs_origin)):
        if v is not None:
            setattr(row, k, v)
    if effects is not None:
        row.effects = json.dumps(validate_effects(effects), ensure_ascii=False)
    if base_run:                                            # 실제로 돌린 발행(t0)에 맞춘다 — '낡음' 판정이 이 값을 본다
        row.base_run = str(base_run)
    _db().session.commit()
    if row.pinned:
        copy_to_hist(row, now)
    return row


def mark_failed(scenario_id, reason='', now=None):
    row = get_scenario(scenario_id)
    if row is None:
        raise StoreError('scenario not found', 404)
    row.status, row.finished_at = 'failed', time.time() if now is None else float(now)
    row.fail_reason = str(reason or '')[:200] or None
    _db().session.commit()
    return row


# ── Influx 곡선 수명 ─────────────────────────────────────────────────────────

def copy_to_hist(row, now=None):
    """시나리오 곡선(`env_twin_scn*`·`env_twin_act`)을 `aot_hist` 로 복사한다 → 복사한 점 수. 실패하면 예외.

    한 버킷 모드(복사할 곳이 같은 버킷)면 0 이다. 같은 점을 되풀이해 써도 같은 키라 덮어쓸 뿐이다."""
    if L.pinned_copy_bucket() is None:
        return 0
    from aot.utils import influx
    now = time.time() if now is None else float(now)
    lo, hi = float(row.created_at) - 30 * 86400.0, now + 40 * 86400.0
    total = 0
    for m in SCENARIO_MEASUREMENTS:
        pts = []
        for ts, value, tags in influx.read_layer_points(m, row.target_id, {'scenario': row.id}, lo, hi):
            tags = dict(tags)
            ch = tags.pop('channel', None)
            pts.append(Point(m, row.target_id, int(ch) if ch is not None else None, ts, float(value), tags))
        if pts:
            total += int(influx.write_influxdb_points(pts, layer=L.LAYER_HIST))
    return total


def pin_scenario(scenario_id, now=None):
    """고정 — 곡선을 `aot_hist` 로 복사한 뒤 `pinned`·`expires_at=NULL`. 복사가 실패하면 예외(고정하지 않는다)."""
    row = get_scenario(scenario_id)
    if row is None:
        raise StoreError('scenario not found', 404)
    if row.status == 'curve_expired':
        raise StoreError('the curves have expired; run the scenario again', 409)
    if row.pinned:
        return row
    copied = 0
    if row.status == 'done':
        try:
            copied = copy_to_hist(row, now)
        except Exception as exc:                                # noqa: BLE001
            logger.warning('시나리오 %s 곡선을 aot_hist 로 복사하지 못했다', row.id, exc_info=True)
            raise StoreError('could not copy the curves to history storage: {}'.format(type(exc).__name__), 503)
    row.pinned, row.expires_at = True, None
    _db().session.commit()
    row.copied_points = copied                                  # 응답용 일회성 값(저장 안 함)
    return row


def delete_curves(scenario_id, include_hist=True):
    """시나리오 곡선을 태그 조건으로 지운다 → 시도한 (측정, 버킷) 수. Influx 를 못 쓰면 0."""
    from aot.utils import data_retention as R
    try:
        client, legacy = R._admin()
    except Exception:                                           # noqa: BLE001 — v1·꺼짐: 지울 계층 버킷이 없다
        return 0
    try:
        return sum(R.delete_points(client, legacy, m, {'scenario': str(scenario_id)}, hist=include_hist)
                   for m in SCENARIO_MEASUREMENTS)
    finally:
        client.close()


def delete_scenario(scenario_id):
    """정의와 곡선(고정 사본 포함)을 지운다. 없으면 StoreError(404)."""
    row = get_scenario(scenario_id)
    if row is None:
        raise StoreError('scenario not found', 404)
    curves = delete_curves(row.id)
    db = _db()
    db.session.delete(row)
    db.session.commit()
    return {'curves': curves}


def drop_for_target(target_id, pinned=False, runs=False):
    """대상(구획·시설)을 지울 때 시나리오 행을 정리한다. 고정하지 않은 것만(곡선이 같이 치워졌다). `pinned=True` 면 전부,
    `runs=True` 면 발행 색인도(이력까지 지울 때). → 지운 행 수."""
    TwinScenario, TwinRun = _models()
    q = TwinScenario.query.filter_by(target_id=str(target_id))
    if not pinned:
        q = q.filter_by(pinned=False)
    n = q.delete(synchronize_session=False)
    if runs:
        n += TwinRun.query.filter_by(target_id=str(target_id)).delete(synchronize_session=False)
    _db().session.commit()
    return n


# ── 분석 실행 색인 ───────────────────────────────────────────────────────────

def record_run(kind, target_id, t0, meta: Mapping[str, float]):
    """발행 한 건의 색인을 쓴다(같은 대상·`t0` 는 덮어쓴다). `meta` 는 머리말 이름 → 값."""
    _, TwinRun = _models()
    target_id = str(target_id)
    rid = run_id_of(target_id, t0)
    row = TwinRun.query.filter_by(run_id=rid).first()
    if row is None:
        row = TwinRun(run_id=rid, target_kind=kind, target_id=target_id, t0=float(t0))
        _db().session.add(row)

    def num(name, cast=int):
        v = meta.get(name)
        return None if v is None else cast(v)

    row.status = num('status')
    row.model_rev = num('model_rev')
    row.cal_rev = num('fc_cal_rev')
    row.fc_issue_epoch = num('fc_issue_epoch', float)
    row.weather_src = num('weather_src')
    row.obs_origin = num('obs_origin')
    row.policy = num('policy')
    row.plan_src = num('plan_src')
    row.fit = json.dumps({k: float(meta[k]) for k in RUN_FIT_KEYS if meta.get(k) is not None})
    _db().session.commit()
    return row


def runs_from_points(points: Sequence[Point]) -> List[Dict[str, object]]:
    """한 번 쓴 점 목록에서 발행 머리말을 모은다 → [{kind, id, t0, meta{이름: 값}}]. 머리말이 없으면 빈 목록."""
    spec = {O.M_FAC_META: (TargetKind.FACILITY.value, O.FACILITY_META),
            O.M_FLD_META: (TargetKind.FIELD.value, O.FIELD_META)}
    acc: Dict[tuple, Dict[str, object]] = {}
    for p in points:
        if p.measurement not in spec:
            continue
        kind, table = spec[p.measurement]
        names = {ch: name for name, ch in table.items()}
        if p.channel not in names:
            continue
        rec = acc.setdefault((kind, p.device_id, float(p.timestamp)),
                             {'kind': kind, 'id': p.device_id, 't0': float(p.timestamp), 'meta': {}})
        rec['meta'][names[p.channel]] = float(p.value)
    return list(acc.values())


def record_runs_from_points(points: Sequence[Point]) -> int:
    """쓴 점에서 머리말을 찾아 `twin_run` 에 적는다(앱 컨텍스트 안에서). 실패해도 발행을 막지 않는다 → 적은 건수."""
    n = 0
    for rec in runs_from_points(points):
        try:
            record_run(rec['kind'], rec['id'], rec['t0'], rec['meta'])
            n += 1
        except Exception:                                       # noqa: BLE001
            logger.warning('분석 실행 색인을 적지 못했다: %s', rec.get('id'), exc_info=True)
            try:
                _db().session.rollback()
            except Exception:                                   # noqa: BLE001
                pass
    return n


def run_dict(row):
    return {'run_id': row.run_id, 'target': {'kind': row.target_kind, 'id': row.target_id}, 't0': row.t0,
            'status': row.status, 'model_rev': row.model_rev, 'cal_rev': row.cal_rev,
            'fc_issue_epoch': row.fc_issue_epoch, 'weather_src': row.weather_src, 'obs_origin': row.obs_origin,
            'policy': row.policy, 'plan_src': row.plan_src, 'fit': row.fit_dict(), 'layer': 'L3'}


def list_runs(target_id, limit=50):
    _, TwinRun = _models()
    return (TwinRun.query.filter_by(target_id=str(target_id)).order_by(TwinRun.t0.desc())
            .limit(max(1, min(int(limit), 500))).all())


def expire_runs(now, days):
    """`t0` 가 `days` 일보다 오래된 발행 색인을 지운다 → 지운 수. 하루 점검이 부른다."""
    _, TwinRun = _models()
    n = TwinRun.query.filter(TwinRun.t0 < float(now) - int(days) * 86400.0).delete(synchronize_session=False)
    _db().session.commit()
    return n


# ── 읽기 응답의 계보 ─────────────────────────────────────────────────────────

LINEAGE_KEYS = ('fc_issue_epoch', 'fc_cal_rev', 'obs_origin')


def lineage(kind, target_id, now=None, meta_rows=None):
    """읽기 응답마다 싣는 계보 `{calibrated, cal_rev, fc_issue_epoch, origin, run_t0}` — 가장 최근 발행 머리말에서.

    머리말이 없거나 못 읽으면 값은 모두 None(`calibrated` 도 None: 모름). 보정됨 = `cal_rev > 0`.
    `origin` = 1 실측 · 2 미러 · 3 가상 · 0 미확인(표시용 — 보정이나 동기화를 거르는 데 쓰지 않는다)."""
    out = {'calibrated': None, 'cal_rev': None, 'fc_issue_epoch': None, 'origin': None, 'run_t0': None}
    if kind == 'field':
        measurement, table = O.M_FLD_META, O.FIELD_META
    else:
        measurement, table = O.M_FAC_META, O.FACILITY_META
    chans = [table['status'], table['fc_issue_epoch'], table['fc_cal_rev'], table['obs_origin']]
    now = time.time() if now is None else float(now)
    if meta_rows is None:
        try:
            from aot.utils.influx import read_twin_many
            meta_rows = read_twin_many(measurement, [str(target_id)], chans, now - 3 * 86400.0, now + 600.0)
        except Exception:                                       # noqa: BLE001 — 계보를 못 읽어도 곡선은 준다
            logger.warning('트윈 계보를 읽지 못했다: %s', target_id, exc_info=True)
            return out
    st = meta_rows.get((str(target_id), table['status'])) or []
    if not st:
        return out
    t0 = st[-1][0]
    out['run_t0'] = float(t0)

    def at(name):
        for t, v in meta_rows.get((str(target_id), table[name])) or []:
            if abs(t - t0) < 1.0:
                return float(v)
        return None

    out['fc_issue_epoch'] = at('fc_issue_epoch')
    rev, org = at('fc_cal_rev'), at('obs_origin')
    out['cal_rev'] = None if rev is None else int(rev)
    out['calibrated'] = None if rev is None else int(rev) > 0
    out['origin'] = None if org is None else int(org)
    return out
