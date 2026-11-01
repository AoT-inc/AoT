# coding=utf-8
"""what-if 시나리오 한 건의 실행 (설계서 §5.2 ④·§5.3, 데이터 관리 설계 §6.2~§6.5, E2).

    시나리오 정의(twin_scenario) ─▶ 대상 설정(TargetSpec)에 `options.scenario` 를 얹어 **기본 예측과 같은 경로**(`engine.run_target`)
        ─▶ 같은 동기화·같은 시드, 예측 구간의 장치 명령·기상 가정만 다르다(모델은 가정을 모르고 입력만 받는다 — 원칙 3)
        ─▶ `flatten_scenario`(env_twin_scn*, 태그 scenario) + 작동 시계열(env_twin_act, 앞날 `plan`)을 쓴다

DB 를 모른다 — 정의는 사전으로 받고, 결과는 `ScenarioOutcome` 으로 돌려준다(상태 전이·계보 기록은 호출자: `scenario_queue`).
같은 정의 + 같은 입력이면 같은 결과다(시드가 대상·t0 로 정해진다 — 기본 예측과 같은 난수라 차이가 가정에서만 온다).
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from . import engine, models, output as O
from .bench import Capability
from .interfaces import TwinSink, TwinSource
from .types import Status, TargetSpec

logger = logging.getLogger(__name__)


@dataclass
class ScenarioOutcome:
    ok: bool
    reason: str = ""
    t0: Optional[float] = None
    written: int = 0
    points: int = 0
    effects: List[Dict[str, object]] = field(default_factory=list)
    lineage: Dict[str, object] = field(default_factory=dict)     # model_rev·cal_rev·fc_issue_epoch·weather_src·obs_origin
    status: Optional[Status] = None
    info: Dict[str, object] = field(default_factory=dict)


def _lineage(meta: Mapping[str, float]) -> Dict[str, object]:
    def i(k):
        v = meta.get(k)
        return int(v) if v is not None and v == v else None

    ep = meta.get("fc_issue_epoch")
    return {"model_rev": i("model_rev"), "cal_rev": i("fc_cal_rev"),
            "fc_issue_epoch": float(ep) if ep is not None and ep == ep else None,
            "weather_src": i("weather_src"), "obs_origin": i("obs_origin")}


def run_scenario(spec: TargetSpec, source: TwinSource, sink: TwinSink, cap: Capability, now: float,
                 scn: Mapping, period_s: Optional[float] = None) -> ScenarioOutcome:
    """`scn` = `twin_store.scenario_dict` 모양(id·base_mode·future_input_mode·overrides). 실패는 예외가 아니라 `ok=False`."""
    from aot.functions.utils.twin_effects import scenario as SC
    sid = str(scn.get("id") or "")
    overrides = scn.get("overrides") or {}
    try:
        if not sid or sid == O.BASELINE:
            raise SC.ScenarioError("시나리오 id 가 없다")
        SC.check_modes(str(scn.get("base_mode") or "hold"), str(scn.get("future_input_mode") or "hold"))
        SC.validate(overrides, spec.kind.value)
    except SC.ScenarioError as e:
        return ScenarioOutcome(False, str(e))
    spec2 = dataclasses.replace(spec, options={**spec.options, "scenario": {"id": sid, "overrides": overrides}})
    try:
        model = models.get(spec.kind.value, spec.options.get("model"))
        res = engine.run_target(spec2, source, model, cap, now, period_s=period_s)
    except Exception as e:                                         # noqa: BLE001 — 한 시나리오의 실패가 서비스로 번지지 않는다
        logger.exception("트윈 시나리오 %s 계산 실패", sid)
        return ScenarioOutcome(False, "계산 실패: %s: %s" % (type(e).__name__, e))
    out = res.output
    if out is None or not out.grids:                               # 곡선 없는 머리말만의 결과 = 쓸 수 없음
        why = res.reason or (res.status.name if res.status is not None else "no_output")
        return ScenarioOutcome(False, "기본 예측과 같은 조건에서 계산할 수 없다: %s" % why, status=res.status)
    pts = O.flatten_scenario(out, sid) + O.run_act_points(out, res.act, scenario=sid, plan_only=True)
    wr = sink.write(pts)
    if not wr.ok:
        return ScenarioOutcome(False, "쓰기 실패: %s (거부 %d)" % (wr.error or "-", wr.rejected), t0=out.t0,
                               written=wr.written, points=len(pts), status=res.status)
    info = {k: v for k, v in dict(res.info).items() if k in ("effects", "forecast")}
    if res.reason:
        info["notes"] = res.reason
    return ScenarioOutcome(True, res.reason, t0=out.t0, written=wr.written, points=len(pts),
                           effects=list(res.effects), lineage=_lineage(out.meta), status=res.status, info=info)
