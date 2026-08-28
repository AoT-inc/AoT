# coding=utf-8
"""
_runtime_state_mixin.py — RuntimeStateMixin: PI state persistence (P2-5).

P0 강화 (2026-05-16):
- 저장 실패 시 짧은 재시도 (transient SQLite lock 대응)
- 최종 실패 시 CRITICAL 로그 + decision_log 채널 기록
  → 사용자가 "왜 재시작 후 PI 적분이 사라졌나" 추적 가능
"""

import json
import time

from aot.config import AOT_DB_PATH
from aot.databases.models import FunctionRuntimeState
from aot.databases.utils import session_scope
from aot.functions.utils.env_control import (
    CH_RUNTIME_STATE_FAIL,
    write_decision_log,
)


class RuntimeStateMixin:
    """Mixin: load/save CoordinatorState to FunctionRuntimeState DB table."""

    _SAVE_RETRY_COUNT = 3
    _SAVE_RETRY_BACKOFF_SEC = 0.3

    def _load_runtime_state(self) -> None:
        """DB에서 PI 상태를 읽어 CoordinatorState 를 복원한다."""
        try:
            with session_scope(AOT_DB_PATH) as sess:
                row = sess.query(FunctionRuntimeState).filter(
                    FunctionRuntimeState.function_id == self.unique_id
                ).first()
                if row is None:
                    return
                integral      = json.loads(row.integral_json    or '{}')
                prev_commands = json.loads(row.prev_cmds_json   or '{}')
                active_vars   = json.loads(row.active_vars_json or '{}')
                last_ts       = row.last_cycle_ts or 0.0
                cal_raw       = row.calibration_state_json or None
                trend_raw     = row.trend_state_json or None
                sess.expunge_all()

            self._coord_state.integral      = integral
            self._coord_state.prev_commands = prev_commands
            self._coord_state.active_vars   = active_vars
            self._last_cycle_ts             = last_ts

            # 추세 히스토리 — 이게 없으면 이 코디네이터는 매 사이클 새로
            # 만들어지므로(재생성 패턴, 아래 calibration 복원과 같은 이유)
            # `self._trend_state` 가 매번 빈 채로 시작해 회귀에 필요한 점
            # 2개를 영원히 못 모은다(추세가 항상 0 → 화면에서 안 보임).
            if trend_raw:
                try:
                    from aot.functions.utils.env_control.situation import TrendState
                    hist = json.loads(trend_raw)
                    # JSON 은 튜플을 배열로 낸다 — `_slope_per_min` 이 `for t, v
                    # in points` 로 그대로 풀어 쓰므로 튜플로 되돌릴 필요는 없다.
                    self._trend_state = TrendState(history=hist)
                except Exception as trend_exc:
                    self.logger.warning(
                        'EnvCoordinator: trend state restore failed: %s', trend_exc)

            if cal_raw:
                try:
                    from aot.functions.utils.env_control.calibration import CalibrationRegistry
                    cal_state = json.loads(cal_raw)
                    self._cal_registry_inst = CalibrationRegistry.from_state(cal_state)
                    self.logger.info(
                        'EnvCoordinator: calibration state restored — '
                        '%d actuator(s)', len(cal_state.get('cals', {})))
                except Exception as cal_exc:
                    self.logger.warning(
                        'EnvCoordinator: calibration state restore failed: %s', cal_exc)

            self.logger.info(
                'EnvCoordinator: PI state restored — integral=%s prev_cmds=%s',
                integral, prev_commands)
        except Exception:
            self.logger.exception(
                'EnvCoordinator: runtime state load failed — starting with clean state')

    def _save_runtime_state(self) -> None:
        """CoordinatorState 를 DB에 upsert 한다.

        Transient 실패(SQLite busy 등)에 짧은 재시도. 최종 실패 시
        CRITICAL 로그 + decision_log 기록 — 사용자가 재시작 후 PI 불연속
        원인을 추적할 수 있게 한다.
        """
        last_exc = None
        for attempt in range(self._SAVE_RETRY_COUNT):
            try:
                now = time.time()
                with session_scope(AOT_DB_PATH) as sess:
                    row = sess.query(FunctionRuntimeState).filter(
                        FunctionRuntimeState.function_id == self.unique_id
                    ).first()
                    if row is None:
                        row = FunctionRuntimeState(function_id=self.unique_id)
                        sess.add(row)
                    row.integral_json    = json.dumps(self._coord_state.integral)
                    row.prev_cmds_json   = json.dumps(self._coord_state.prev_commands)
                    row.active_vars_json = json.dumps(
                        {k: bool(v) for k, v in self._coord_state.active_vars.items()})
                    row.last_cycle_ts    = self._last_cycle_ts
                    row.updated_at       = now

                    # 추세 히스토리 — `_load_runtime_state` 와 같은 이유(이
                    # 코디네이터는 사이클마다 재생성된다). `window_sec` 은
                    # 저장하지 않는다 — assess() 가 매 호출마다 그 사이클의
                    # cycle_sec 기준으로 다시 정하므로 저장해 봐야 곧바로
                    # 덮어써진다(situation.py 주석 참조).
                    _trend = getattr(self, '_trend_state', None)
                    if _trend is not None:
                        try:
                            row.trend_state_json = json.dumps(_trend.history)
                        except (TypeError, ValueError):
                            pass

                    # 맵 팝업 [현황] 요약 — 사이클이 산출한 경우에만 갱신
                    _summary = getattr(self, '_last_cycle_summary', None)
                    if _summary is not None:
                        try:
                            row.summary_json = json.dumps(
                                _summary, ensure_ascii=False)
                        except (TypeError, ValueError):
                            pass

                    # 맵 위젯 /runtime 용 센서 스냅샷 — 사이클이 산출한 경우에만 갱신
                    _runtime = getattr(self, '_last_cycle_runtime_snapshot', None)
                    if _runtime is not None:
                        try:
                            row.runtime_json = json.dumps(
                                _runtime, ensure_ascii=False)
                        except (TypeError, ValueError):
                            pass

                    # Persist CalibrationRegistry if it exists and is enabled.
                    # Merge state_dict() output INTO the existing JSON rather
                    # than replacing it, so out-of-band flags written by other
                    # paths (e.g. greybox_kpi_passed from _handle_greybox_kpi_passed)
                    # survive each save cycle.
                    if hasattr(self, '_cal_registry_inst'):
                        try:
                            try:
                                existing = json.loads(
                                    row.calibration_state_json or '{}')
                            except Exception:
                                existing = {}
                            new_state = self._cal_registry_inst.state_dict()
                            # Preserve any extra top-level keys (KPI flags, etc.)
                            # while overwriting the registry-owned 'enabled'/'cals'.
                            existing.update(new_state)
                            row.calibration_state_json = json.dumps(existing)
                        except Exception:
                            pass

                    sess.commit()
                # 성공 시 누적 실패 카운터는 다음 실패까지 보존(외부 관찰자가
                # rate를 계산할 수 있도록 누적값만 갱신)
                return
            except Exception as exc:
                last_exc = exc
                self.logger.warning(
                    'EnvCoordinator: runtime state save failed (attempt %d/%d): %s',
                    attempt + 1, self._SAVE_RETRY_COUNT, exc)
                if attempt < self._SAVE_RETRY_COUNT - 1:
                    time.sleep(self._SAVE_RETRY_BACKOFF_SEC * (attempt + 1))

        # 최종 실패: CRITICAL + decision_log
        self._runtime_state_fail_count = (
            getattr(self, '_runtime_state_fail_count', 0) + 1)
        self.logger.critical(
            'EnvCoordinator: runtime state save final failure (%d total) — '
            'PI integral/previous commands will be lost on restart. Last error: %s',
            self._runtime_state_fail_count, last_exc)
        try:
            write_decision_log(
                self.unique_id, 'runtime_state_save_fail',
                CH_RUNTIME_STATE_FAIL, float(self._runtime_state_fail_count))
        except Exception:
            # 로그 채널 자체 실패는 무시 — 본 사이클 진행을 막지 않는다.
            pass
