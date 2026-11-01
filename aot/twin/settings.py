# coding=utf-8
"""'트윈: 이 서버에서 / 다른 서버' 설정 (설계 문서 §4). 개발 설정 뒤에 숨긴다.

노드는 이 구조 하나만 읽는다. 어디에서 오는지는 두 경로다:
  - 내장(이 서버): 서버의 Misc 설정 → `from_misc()` 가 만든다 (DB 열 추가는 후속, 설계 §4).
  - 독립 노드(NAS·미니PC): JSON 파일 `AOT_TWIN_CONFIG` → `load()`.
비밀(API 키)은 파일에 적지 않고 `api_key_env` 가 가리키는 환경변수에서 읽는다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from .types import Provenance, SeriesRef, TargetKind, TargetSpec

logger = logging.getLogger("aot.twin.settings")

MODES = ("off", "embedded", "remote")


class SettingsError(ValueError):
    pass


@dataclass
class ServerSettings:
    server_id: str
    mode: str = "off"                       # off | embedded | remote
    url: str = ""                           # remote: https://host:port
    api_key_env: str = ""                   # remote: 키를 담은 환경변수 이름
    ingest_path: str = "/api/twin/ingest"
    ping_path: str = "/api/settings/measurements"
    verify_tls: bool = True
    timeout_s: float = 10.0
    targets: List[TargetSpec] = field(default_factory=list)

    def api_key(self, env: Optional[Mapping[str, str]] = None) -> str:
        env = os.environ if env is None else env
        k = env.get(self.api_key_env, "") if self.api_key_env else ""
        if not k:
            raise SettingsError(f"[{self.server_id}] API 키 환경변수 '{self.api_key_env}' 가 비어 있다")
        return k

    def validate(self) -> None:
        if self.mode not in MODES:
            raise SettingsError(f"[{self.server_id}] mode '{self.mode}' ∉ {MODES}")
        if self.mode == "remote":
            if not self.url.startswith(("http://", "https://")):
                raise SettingsError(f"[{self.server_id}] remote 는 url(http/https)이 필요하다")
            if not self.api_key_env:
                raise SettingsError(f"[{self.server_id}] remote 는 api_key_env 가 필요하다")
        for n in self.notices():
            logger.warning(n)

    def notices(self) -> List[str]:
        """설정은 맞지만 기대대로 돌지 않는 것 — 지금은 원격 쓰기 비활성 하나(계획서 §9.19).

        읽기(RemoteSource)는 되지만 결과를 되돌려 쓰지 못한다. 거부하지 않고 알린다: 배포 제안 §2 의 '다른 서버 지정'
        방식은 계속 지원하되 원격 노드를 다시 설계하는 중이라, 설정을 막으면 그 작업의 시험 길까지 닫힌다.
        """
        if self.mode != "remote":
            return []
        from .sources.remote import REMOTE_WRITE_DISABLED
        return [f"[{self.server_id}] mode 'remote': {REMOTE_WRITE_DISABLED}"]


@dataclass
class Schedule:
    """정기 실행(벽시계). `run_at` 이 비면 예전처럼 `period_s` 간격으로 돈다."""
    run_at: List[str] = field(default_factory=list)   # ["06:10", "18:10"] — 하루 1~2회 권장
    timezone: str = "UTC"                   # run_at 을 읽는 시간대(IANA)
    run_on_start: bool = True               # 기동 직후 한 번 (재기동·NAS 재부팅 뒤 따라잡기)
    retry_s: float = 900.0                  # 서버가 안 닿거나 쓰기가 거부됐을 때 다시 해 보는 간격
    max_retries: int = 4                    # 그래도 안 되면 다음 예약 시각까지 쉰다

    def validate(self) -> None:
        from . import schedule as sch
        try:
            sch.parse_run_at(self.run_at)
            sch.check_timezone(self.timezone)
        except ValueError as e:
            raise SettingsError(f"schedule: {e}")
        if len(self.run_at) > 6:
            raise SettingsError("schedule.run_at 은 하루 6 회까지")
        if self.retry_s < 60 or self.max_retries < 0:
            raise SettingsError("schedule.retry_s 는 60 초 이상, max_retries 는 0 이상")


@dataclass
class NodeSettings:
    enabled: bool = False                   # 개발 설정에서 켜야 한다 (공개 기능 아님)
    period_s: float = 3600.0                # 발행 주기
    schedule: Schedule = field(default_factory=Schedule)
    force_tier: Optional[str] = None        # full|deterministic|light — 벤치 대신 못박기
    workers: int = 2
    servers: List[ServerSettings] = field(default_factory=list)

    def validate(self) -> None:
        if self.period_s < 60:
            raise SettingsError("period_s 는 60 초 이상")
        self.schedule.validate()
        ids = [s.server_id for s in self.servers]
        if len(ids) != len(set(ids)):
            raise SettingsError("server_id 중복")
        for s in self.servers:
            s.validate()

    def notices(self) -> List[str]:
        return [n for s in self.servers for n in s.notices()]


def _series(d: Mapping) -> SeriesRef:
    sc = d.get("scale")
    scale = None
    if sc:
        scale = (float(sc["from_min"]), float(sc["from_max"]))
        if not scale[1] > scale[0]:
            raise ValueError("scale: from_max 는 from_min 보다 커야 한다")
    return SeriesRef(unique_id=str(d["unique_id"]), unit=str(d["unit"]), channel=int(d["channel"]),
                     provenance=Provenance(d.get("provenance", "unknown")), scale=scale)


def _target(server_id: str, d: Mapping) -> TargetSpec:
    return TargetSpec(
        server_id=server_id, kind=TargetKind(d["kind"]), target_id=str(d["target_id"]),
        facility=str(d.get("facility", "")),
        inputs={k: _series(v) for k, v in d.get("inputs", {}).items()},
        controls={k: _series(v) for k, v in d.get("controls", {}).items()},
        options=dict(d.get("options", {})))


def from_dict(d: Mapping) -> NodeSettings:
    servers = []
    for sd in d.get("servers", []):
        sid = str(sd["server_id"])
        servers.append(ServerSettings(
            server_id=sid, mode=sd.get("mode", "off"), url=os.path.expandvars(sd.get("url", "")),
            api_key_env=sd.get("api_key_env", ""),
            ingest_path=sd.get("ingest_path", "/api/twin/ingest"),
            ping_path=sd.get("ping_path", "/api/settings/measurements"),
            verify_tls=bool(sd.get("verify_tls", True)), timeout_s=float(sd.get("timeout_s", 10.0)),
            targets=[_target(sid, t) for t in sd.get("targets", [])]))
    sd = d.get("schedule") or {}
    sched = Schedule(run_at=[str(x) for x in sd.get("run_at", [])], timezone=str(sd.get("timezone", "UTC")),
                     run_on_start=bool(sd.get("run_on_start", True)), retry_s=float(sd.get("retry_s", 900.0)),
                     max_retries=int(sd.get("max_retries", 4)))
    ns = NodeSettings(enabled=bool(d.get("enabled", False)), period_s=float(d.get("period_s", 3600.0)),
                      schedule=sched, force_tier=d.get("force_tier"), workers=int(d.get("workers", 2)),
                      servers=servers)
    ns.validate()
    return ns


def load(path: Optional[str] = None) -> NodeSettings:
    path = path or os.environ.get("AOT_TWIN_CONFIG", "")
    if not path:
        raise SettingsError("설정 파일 경로가 없다 (AOT_TWIN_CONFIG)")
    with open(path, encoding="utf-8") as f:
        return from_dict(json.load(f))


def from_misc(misc) -> NodeSettings:
    """이 서버의 '트윈: 이 서버에서 / 다른 서버' 설정(Misc 행) → 이 서버 안에서 돌 노드의 설정.

    - off      : 꺼짐.
    - embedded : 이 서버 안에 노드를 띄운다(서버 하나, 내장 통로). 대상·배선은 아직 JSON 설정이 정한다.
    - remote   : 트윈 노드는 **다른 서버**에 있다. 그 노드가 이 서버를 읽으러 오므로 이 서버 안에서는
                 노드를 띄우지 않는다(꺼진 설정). `twin_node_url` 은 화면 표시·점검용이다.
    열(`twin_mode` …)은 아직 없다(후속 마이그레이션, 설계 §4) — 없으면 꺼짐이라 서버는 지금처럼 돈다.
    """
    mode = getattr(misc, "twin_mode", None) or "off"
    if mode != "embedded":
        return NodeSettings(enabled=False)
    ns = NodeSettings(enabled=True, servers=[ServerSettings(server_id="local", mode="embedded")])
    ns.validate()
    return ns
