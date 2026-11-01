# coding=utf-8
"""같은 효과 채널의 여러 장치를 하나의 채널 값으로 합친다 (설계서 §4).

- `vent`: env_control 의 `vent_capacities`·`vent_channel_value` 를 **그대로 부른다**(창/팬 압력 효율 포함, 모델 두 벌 금지).
- `shade`·`curtain`: 개도 평균(env_control `aggregate_cmds_by_kind` 와 같다).
- `heat`·`cool`·`fog`·`co2_inj`: **정격 가중 평균** `Σ(정격·가동률) / Σ정격`. env_control 은 최댓값을 쓰는데, 난방기 둘 중
  하나만 100 % 여도 채널이 100 % 가 되어 트윈에는 과대다(env_control 쪽은 운영 제어라 고치지 않는다).
  ⚠ 이 값이 맞으려면 그레이박스의 `Q_heat`(W) 등이 **설치 정격 합**이어야 한다. `GreyboxParams.from_capacity_meta` 는
  `Q_heat`·`Q_cool`·`m_fog_evap`·`K_CO2_inj` 를 채우지 않아 기본값이 그대로다(E1 에서 정격 합으로 채운다).
- 정격을 모르는 장치: 알려진 정격의 평균을 대신 쓰고(전부 모르면 같은 몫), `assumed` 에 적는다 — 조용히 가정하지 않는다.
- 표에 없거나 모델이 못 받는 종류는 채널에 넣지 않고 `unmodeled` 에 남긴다.

env_control 은 `__init__` 이 DB·Influx 를 끌어오므로 **실행할 때** 가져온다(노드 import 가드).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Dict, List, Mapping, Optional, Sequence

from . import catalog as C


@dataclass
class Device:
    """합치기에 필요한 장치 정보. DB 를 모른다 — 읽기 쪽(E1)이 채운다."""
    actuator_id: str
    kind: str
    ratings: Mapping[str, Optional[float]] = field(default_factory=dict)
    vent_form: Optional[str] = None            # 'ridge' | 'side' | None


@dataclass
class ChannelResult:
    values: Dict[str, float] = field(default_factory=dict)      # 채널 → 값(%, 노지 관수는 mm)
    unmodeled: List[Dict[str, object]] = field(default_factory=list)   # {actuator_id, kind, effects}
    assumed: List[str] = field(default_factory=list)             # 정격을 가정한 장치
    members: Dict[str, List[str]] = field(default_factory=dict)  # 채널 → 장치 id


def _weights(devs: Sequence[Device], key: str, assumed: List[str]) -> Dict[str, float]:
    known = {d.actuator_id: float(d.ratings[key]) for d in devs
             if d.ratings.get(key) not in (None, 0) and float(d.ratings[key]) > 0}
    fill = (sum(known.values()) / len(known)) if known else 1.0
    out = {}
    for d in devs:
        w = known.get(d.actuator_id)
        if w is None:
            assumed.append(d.actuator_id)
            w = fill
        out[d.actuator_id] = w
    return out


def merge(devices: Sequence[Device], cmds_pct: Mapping[str, float], domain: str = C.FACILITY) -> ChannelResult:
    """장치별 가동·개도(%) → 효과 채널 값. `cmds_pct` 에 없는 장치는 0 으로 본다."""
    res = ChannelResult()
    by_channel: Dict[str, List[Device]] = {}
    for d in devices:
        row = C.row_for(d.kind, domain)
        if row.status == C.UNMODELED or row.channel is None:
            res.unmodeled.append({"actuator_id": d.actuator_id, "kind": d.kind,
                                  "effects": list(row.unmodeled_effects)})
            continue
        by_channel.setdefault(row.channel, []).append(d)
    for ch, devs in by_channel.items():
        res.members[ch] = [d.actuator_id for d in devs]
        merge_kind = C.row_for(devs[0].kind, domain).merge
        pct = {d.actuator_id: float(cmds_pct.get(d.actuator_id, 0.0) or 0.0) for d in devs}
        if merge_kind == C.MERGE_VENT_FLOW:
            from aot.functions.utils.env_control.greybox.channels import vent_capacities, vent_channel_value
            profiles = [SimpleNamespace(
                actuator_id=d.actuator_id, kind=d.kind, vent_form=d.vent_form,
                area_m2=d.ratings.get("area_m2"), capacity_meta={"rated_m3h": d.ratings.get("rated_m3h") or 0.0})
                for d in devs]
            caps = vent_capacities(profiles)
            for d in devs:                          # 면적·풍량을 몰라 env_control 기본값이 쓰인 장치는 가정으로 적는다
                key = "rated_m3h" if d.kind in ("exhaust_fan", "intake_fan") else "area_m2"
                if not d.ratings.get(key):
                    res.assumed.append(d.actuator_id)
            res.values[ch] = vent_channel_value(pct, caps)
        elif merge_kind == C.MERGE_MEAN_OPEN:
            res.values[ch] = sum(pct.values()) / len(pct)
        elif merge_kind == C.MERGE_SUM_MM:           # 값이 이미 장치별 물 깊이(mm)다
            res.values[ch] = sum(pct.values())
        elif merge_kind == C.MERGE_CAPACITY:
            key = C.row_for(devs[0].kind, domain).ratings[0].key
            w = _weights(devs, key, res.assumed)
            tot = sum(w.values())
            res.values[ch] = sum(w[a] * pct[a] for a in w) / tot if tot > 0 else 0.0
        else:
            res.unmodeled.append({"actuator_id": ",".join(d.actuator_id for d in devs), "kind": devs[0].kind,
                                  "effects": ["no_merge_rule"]})
    return res
