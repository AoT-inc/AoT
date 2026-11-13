# coding=utf-8
"""장치 → 효과 채널 **자동 연결** (설계서 §3, 2026-10-26 개정).

연결은 위치로 정해진다 — 시설 피팅에 묶인 장치(`GeoBinding` → 통합 payload)의 **종류**를 효과 목록표에 대어 채널을 정하고,
정격은 `reader` 가, 상태 계열은 `state` 의 우선순위가 정한다. 사람이 다시 고르게 하지 않는다. 사람이 하는 일은 덮어쓰기
예외 둘뿐이다:

- `kind`  종류를 모르는 설비(노지의 범용 출력 포함)에 **역할/종류**를 준다. 알아본 종류는 덮어쓰지 않는다.
- `exclude` 이 장치를 효과에서 뺀다(수리 중 등).

이 모듈은 순수하다(DB·Flask 를 모른다). 읽기 결과(`reader.ReadResult`)와 상태 출처(`state_info`)를 받아 화면 줄과
트윈 부품 옵션(`options.effects`)을 만든다. 서버 쪽 글루는 `aot.utils.twin_effects_link`.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from . import catalog as C
from . import state as S
from .aggregate import Device
from .reader import ReadResult, rating_view

STATUS_UNKNOWN = "unknown"          # 종류를 모른다(목록표에 없는 종류와 구분해 화면이 '종류를 정해 주세요'를 낸다)


class OverrideError(ValueError):
    pass


def validate_overrides(obj, domain: str = C.FACILITY) -> Dict[str, Dict[str, object]]:
    """`{"<장치 id>": {"kind": 종류}` 또는 `{"exclude": true}}` → 정리한 사본. 모르는 키·종류는 거부한다(조용히 사라지면 모른다)."""
    if obj is None:
        return {}
    if not isinstance(obj, Mapping):
        raise OverrideError("effects 는 객체여야 한다")
    unknown = set(obj) - {"devices"}
    if unknown:
        raise OverrideError("모르는 항목: %s" % ", ".join(sorted(unknown)))
    devs = obj.get("devices") or {}
    if not isinstance(devs, Mapping):
        raise OverrideError("effects.devices 는 객체여야 한다")
    kinds = C.all_kinds(domain)
    out: Dict[str, Dict[str, object]] = {}
    for uid, v in devs.items():
        if not isinstance(v, Mapping) or not str(uid).strip():
            raise OverrideError("장치 덮어쓰기는 {kind|exclude} 객체")
        bad = set(v) - {"kind", "exclude"}
        if bad:
            raise OverrideError("모르는 덮어쓰기: %s" % ", ".join(sorted(bad)))
        rec: Dict[str, object] = {}
        if v.get("exclude"):
            rec["exclude"] = True
        if v.get("kind") not in (None, ""):
            if str(v["kind"]) not in kinds:
                raise OverrideError("모르는 종류: %s" % v["kind"])
            rec["kind"] = str(v["kind"])
        if rec:
            out[str(uid)] = rec
    return out


def selectable_kinds(domain: str = C.FACILITY) -> List[str]:
    """종류를 모르는 설비에 줄 수 있는 종류 — 표의 행마다 대표 종류(창 행의 별칭 `vent`·`side_vent` 등은 `opening` 하나로)."""
    out: List[str] = []
    for r in C.rows(domain):
        for k in (("opening",) if r.name == "window" else r.kinds):
            if k not in out:
                out.append(k)
    return out


def _row_status(kind: Optional[str], domain: str) -> str:
    return STATUS_UNKNOWN if not kind else C.row_for(kind, domain).status


def build_rows(read: ReadResult, state_info: Optional[Mapping[str, Mapping]] = None,
               overrides: Optional[Mapping[str, Mapping]] = None, domain: str = C.FACILITY) -> List[Dict[str, object]]:
    """장치마다 한 줄: 종류 → 효과 채널, 반영 상태, 정격(값·출처), 상태 출처.

    `state_info[장치 id]` = {basis, ref?, candidates?} (서버 글루가 채운다). 없으면 `none`.
    """
    state_info = state_info or {}
    ov = overrides or {}                                     # `validate_overrides` 가 정리한 {장치 id: 덮어쓰기}
    rows: List[Dict[str, object]] = []

    def add(dev: Optional[Device], uid: str, name: str, kind: Optional[str], kind_from: str, sources, fitting_kind=None):
        o = ov.get(uid) or {}
        st = state_info.get(uid) or {}
        row = C.row_for(kind, domain) if kind else C.UNKNOWN_KIND
        rec = {
            "id": uid, "name": name, "kind": kind, "kind_from": kind_from,
            "effect": row.name if kind else None, "channel": row.channel if kind else None,
            "status": _row_status(kind, domain), "unmodeled_effects": list(row.unmodeled_effects),
            "ratings": rating_view(dev, sources, domain) if dev is not None else [],
            "basis": st.get("basis") or S.NONE, "estimated": S.estimated(st.get("basis") or S.NONE),
            "excluded": bool(o.get("exclude")), "needs_kind": not kind,
        }
        if fitting_kind:
            rec["fitting_kind"] = fitting_kind
        rows.append(rec)

    for d in read.devices:
        add(d, d.actuator_id, read.names.get(d.actuator_id, d.actuator_id[:8]), d.kind, "location",
            read.sources.get(d.actuator_id))
    for u in read.unknown:                                   # 종류를 못 알아본 설비 — 역할을 준 것만 장치가 된다
        uid = u["actuator_id"]
        k = (ov.get(uid) or {}).get("kind")
        if k:
            dev = Device(uid, k, {}, None)
            add(dev, uid, u.get("name") or uid[:8], k, "override", {}, u.get("fitting_kind"))
        else:
            add(None, uid, u.get("name") or uid[:8], None, "", {}, u.get("fitting_kind"))
    return rows


def effective_devices(read: ReadResult, overrides: Optional[Mapping[str, Mapping]] = None) -> List[Device]:
    """효과에 쓰는 장치 — 뺀 것은 제외하고 역할을 준 설비는 넣는다."""
    ov = overrides or {}
    out = [d for d in read.devices if not (ov.get(d.actuator_id) or {}).get("exclude")]
    for u in read.unknown:
        o = ov.get(u["actuator_id"]) or {}
        if o.get("kind") and not o.get("exclude"):
            out.append(Device(u["actuator_id"], o["kind"], {}, None))
    return out


def effects_options(devices: List[Device], basis_by_id: Mapping[str, str]) -> Dict[str, object]:
    """트윈 시설 부품의 `options.effects` — 장치별 종류·정격·형태와 상태 출처."""
    return {"devices": [
        {"id": d.actuator_id, "kind": d.kind, "ratings": {k: v for k, v in d.ratings.items() if v},
         "vent_form": d.vent_form, "basis": basis_by_id.get(d.actuator_id) or S.NONE}
        for d in devices]}


def summarize(rows: List[Dict[str, object]]) -> Dict[str, int]:
    """화면 요약 — 뺀 장치는 세지 않고 따로 센다. 반영 상태 개수와, 채널에 들어가는데 상태 계열이 없는 장치 수."""
    live = [r for r in rows if not r["excluded"]]
    out = {"total": len(live), "modeled": 0, "partial": 0, "unmodeled": 0, "supply": 0, "unknown": 0, "no_state": 0,
           "estimated": 0, "excluded": len(rows) - len(live)}
    for r in live:
        out[r["status"]] += 1
        if r["channel"] and r["basis"] == S.NONE:
            out["no_state"] += 1
        if r["estimated"]:
            out["estimated"] += 1
    return out
