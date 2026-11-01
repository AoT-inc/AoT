# coding=utf-8
"""모델은 끼우는 부품이다 (원칙 6). 이름 → 공장 함수. 실제 모델(그레이박스 v3, 노지 물 수지)은
각자의 모듈에서 `register()` 로 자기를 등록한다 — 뼈대는 그 파일을 import 하지도, 고치지도 않는다."""
from __future__ import annotations

from typing import Callable, Dict, Optional

from ..interfaces import TwinModel

_FACTORIES: Dict[str, Callable[[], TwinModel]] = {}
_DEFAULT: Dict[str, str] = {}      # kind → 모델 이름


def register(name: str, kind: str, factory: Callable[[], TwinModel], default: bool = False) -> None:
    _FACTORIES[name] = factory
    if default or kind not in _DEFAULT:
        _DEFAULT[kind] = name


def get(kind: str, name: Optional[str] = None) -> TwinModel:
    """`name` 이 있으면 그 모델, 없으면 그 종류의 기본 모델. 없으면 KeyError."""
    key = name or _DEFAULT[kind]
    return _FACTORIES[key]()


def names() -> Dict[str, str]:
    return dict(_DEFAULT)
