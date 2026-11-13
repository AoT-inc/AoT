# coding=utf-8
"""호환용 별칭 — 정본은 `aot.space.coordinator_plot` (아키텍처 7b).

같은 모듈 객체를 돌려주므로 monkeypatch 도 정본에 닿는다.
"""
import sys

from aot.space import coordinator_plot as _canonical

sys.modules[__name__] = _canonical
