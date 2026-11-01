# coding=utf-8
"""뼈대가 아는 인터페이스 셋. 내장·원격은 TwinSource/TwinSink 구현만 다르고 나머지 코드는 같다.

- TwinSource : 자료를 읽는 통로
- TwinSink   : 결과를 되돌려 쓰는 통로
- TwinModel  : 끼우는 부품 (계약 §10.7, 계획서 원칙 6). 모델은 확률을 모른다 — 앙상블은 뼈대가 만든다.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Protocol, Sequence, runtime_checkable

from .types import Point, Series, SeriesRef, TargetSpec, WriteResult


@runtime_checkable
class TwinSource(Protocol):
    server_id: str

    def ping(self) -> bool:
        """서버에 닿는가. 거짓이면 그 서버의 작업은 건너뛴다(원칙 1: 트윈은 없어도 된다)."""

    def list_targets(self) -> Sequence[TargetSpec]:
        """이 서버에서 트윈이 맡을 대상과 배선."""

    def read_series(self, ref: SeriesRef, window_s: float, now: float) -> Series:
        """`now - window_s` ~ `now` 구간의 측정. 없으면 빈 계열."""


@runtime_checkable
class TwinSink(Protocol):
    server_id: str

    def write(self, points: Sequence[Point]) -> WriteResult:
        """점들을 `env_twin*` 측정으로 쓴다. 같은 측정·태그·시각이면 덮어쓴다(계약 §6.1)."""


@runtime_checkable
class TwinModel(Protocol):
    kind: str                        # 'facility' | 'field'
    model_rev: int                   # env_twin_meta.model_rev
    state_names: Sequence[str]
    param_names: Sequence[str]
    dt_nominal_s: float

    def init_state(self, target: TargetSpec, t0: float, obs: Mapping[str, float]) -> Dict[str, float]: ...

    def step(self, x: Mapping[str, float], u: Mapping[str, float], w: Mapping[str, float],
             dt_s: float) -> Dict[str, float]:
        """결정론 한 스텝. 모르는 입력은 NaN 으로 오며 모델은 그 항을 뺀다."""

    def observe(self, x: Mapping[str, float], name: str) -> float: ...

    def derived(self, x: Mapping[str, float]) -> Dict[str, float]: ...

    def risks(self, traj: Sequence[Mapping[str, float]], target: TargetSpec) -> Dict[str, Sequence[float]]:
        """궤적 하나에서 격자 지점별 사건 발생 여부(0/1). 확률은 뼈대가 앙상블에서 평균낸다."""
