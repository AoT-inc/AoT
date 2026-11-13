# coding=utf-8
"""시나리오 실행 대기열 — 서비스(`aot_twin`)가 `twin_scenario` 의 `queued` 행을 차례로 꺼내 돌린다 (설계서 §5.3 ⑤, E2).

기존 트윈 큐(`queue.ServerQueues`)는 **대상 키만** 담는 서버별 FIFO 라 정의(가정)를 실어 나르지 못한다. 시나리오의 대기열은 DB 행의
`status` 가 맡는다 — 서비스가 재시작해도 남고(`running` 으로 남은 것은 시작 때 되돌린다), API 가 정의를 만들기만 하면 서비스가
집어 간다. 한 번에 하나, 오래 기다린 것부터. 실행기는 서비스 프로세스 하나뿐이다.

`ScenarioQueue` 는 서비스가 아는 면이고(시험은 가짜로 돈다), `DbScenarioQueue` 가 이 기기의 DB 를 쓴다(flask 는 호출 때 import).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from .scenario_run import ScenarioOutcome

logger = logging.getLogger(__name__)


class ScenarioQueue:
    """서비스가 쓰는 네 가지. 실제 구현은 `DbScenarioQueue`."""

    def recover(self) -> int:
        """시작 때: 도중에 멈춰 `running` 으로 남은 것을 되돌린다 → 되돌린 수."""
        raise NotImplementedError

    def claim(self) -> Optional[Dict[str, object]]:
        """가장 오래 기다린 정의를 실행 중으로 바꿔 `twin_store.scenario_dict` 모양으로 돌려준다. 없으면 None."""
        raise NotImplementedError

    def prepare(self, scn: Dict[str, object]) -> Dict[str, object]:
        """돌리기 전에 서버만 아는 것을 푼다. 틀린 가정은 `ScenarioError` — 호출자가 실패로 적는다."""
        return scn

    def done(self, scenario_id: str, outcome: ScenarioOutcome) -> None:
        raise NotImplementedError

    def failed(self, scenario_id: str, reason: str) -> None:
        raise NotImplementedError


class DbScenarioQueue(ScenarioQueue):
    def __init__(self, app=None):
        from .gate import LazyApp
        self._app = app or LazyApp()

    def _ctx(self):
        return self._app.get().app_context()

    def recover(self) -> int:
        from aot.utils import twin_store
        with self._ctx():
            n = twin_store.requeue_running()
        if n:
            logger.info("트윈 시나리오: 도중에 멈춘 %d 건을 다시 대기열에 올렸다", n)
        return n

    def claim(self) -> Optional[Dict[str, object]]:
        from aot.utils import twin_store
        with self._ctx():
            row = twin_store.claim_next_queued()
            return twin_store.scenario_dict(row) if row is not None else None

    def prepare(self, scn: Dict[str, object]) -> Dict[str, object]:
        """노지 밸브 가정을 구획 깊이로 — 물 회로는 서버에 있고 트윈은 깊이만 받는다. 정의(저장된 가정)는 그대로 둔다."""
        tgt = scn.get("target") or {}
        if tgt.get("kind") != "field":
            return scn
        with self._ctx():
            from aot.utils.twin_effects_link import field_scenario_depths
            return dict(scn, overrides=field_scenario_depths(str(tgt.get("id")), scn.get("overrides") or {}))

    def done(self, scenario_id: str, outcome: ScenarioOutcome) -> None:
        from aot.utils import twin_store
        with self._ctx():
            row = twin_store.get_scenario(scenario_id)
            if row is None:                                       # 도는 동안 지워졌다 — 쓴 곡선이 남지 않게 치운다
                twin_store.delete_curves(scenario_id)
                return
            lin = outcome.lineage or {}
            twin_store.mark_done(
                scenario_id, model_rev=lin.get("model_rev"), cal_rev=lin.get("cal_rev"),
                fc_issue_epoch=lin.get("fc_issue_epoch"), weather_src=lin.get("weather_src"),
                obs_origin=lin.get("obs_origin"), effects=outcome.effects,
                base_run=twin_store.run_id_of(row.target_id, outcome.t0) if outcome.t0 is not None else None)

    def failed(self, scenario_id: str, reason: str) -> None:
        from aot.utils import twin_store
        with self._ctx():
            if twin_store.get_scenario(scenario_id) is None:
                twin_store.delete_curves(scenario_id)
                return
            twin_store.mark_failed(scenario_id, reason)
