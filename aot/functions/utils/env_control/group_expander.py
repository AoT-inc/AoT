# coding=utf-8
"""
group_expander.py — 복합 액추에이터 그룹 명령 확장 (P2-4).

coordinator.py 가 리더에만 명령을 내린 후, 이 모듈이 팔로워들에게
그룹 모드별 규칙으로 명령을 복사/변환한다.

모드별 규칙:
  symmetric     : follower.value = leader.value
  windward_diff : 기본 symmetric. 풍향 보정은 safety_gates.G4 가 별도 처리.
  stacked       : leader > threshold_pct → follower = leader - threshold_pct
                  (남은 여분을 팔로워에 할당, [0, 100] 클램프)
  multi_stage   : 개방 방향(leader ↑):
                    leader ≤ 100% 동안 follower = 100%  (내부 커튼 먼저)
                    leader = 0% 이면 follower = 0%       (닫기 시작)
                  폐쇄 방향(leader ↓):
                    leader > 0% → follower = 100%        (내부 유지)
                    leader = 0% → follower = 0%          (외부 폐쇄 완료 후)

참조: docs/dev/integrated_env_control_design.md §P2-4
"""

from typing import Dict, List

from aot.functions.utils.env_control.coordinator import ActuatorCommand
from aot.functions.utils.env_control.types import ActuatorGroup


def expand_group_commands(
    commands: Dict[str, ActuatorCommand],
    groups: List[ActuatorGroup],
    prev_commands: Dict[str, float],
) -> Dict[str, ActuatorCommand]:
    """
    그룹 팔로워 액추에이터에 리더 명령을 모드별로 확장한다.

    Args:
        commands:     coordinator 출력 (리더 포함 전 액추에이터 명령)
        groups:       활성 ActuatorGroup 목록
        prev_commands: 이전 사이클 명령 (stacked/multi_stage 방향 판단용)

    Returns:
        팔로워 명령이 추가된 commands dict (원본 수정 없이 새 dict 반환)
    """
    result = dict(commands)

    for grp in groups:
        leader_cmd = result.get(grp.leader_id)
        if leader_cmd is None:
            continue

        lv = leader_cmd.value
        reason = leader_cmd.reason

        for fid in grp.follower_ids():
            follower_val = _compute_follower(grp, lv, fid, prev_commands)
            result[fid] = ActuatorCommand(
                value=follower_val,
                reason=reason,
                var_source=leader_cmd.var_source,
            )

    return result


def _compute_follower(
    grp: ActuatorGroup,
    leader_val: float,
    follower_id: str,
    prev_commands: Dict[str, float],
) -> float:
    mode = grp.mode

    if mode in ('symmetric', 'windward_diff'):
        return leader_val

    if mode == 'stacked':
        thr = grp.threshold_pct
        if leader_val <= thr:
            return 0.0
        return _clamp(leader_val - thr, 0.0, 100.0)

    if mode == 'multi_stage':
        # multi_stage: 내부(leader)→외부(follower) 순서
        # 폐쇄(leader 내려가는 중): follower는 leader가 0이 됐을 때만 닫음
        # 개방(leader 올라가는 중): follower는 leader가 0보다 크면 100
        prev_leader = prev_commands.get(grp.leader_id, 0.0)
        closing = leader_val < prev_leader

        if closing:
            # 외부(follower) 먼저 폐쇄: leader가 0일 때만 follower 닫음
            return 0.0 if leader_val == 0.0 else 100.0
        else:
            # 내부(leader) 먼저 개방: leader > 0이면 follower도 100%
            return 100.0 if leader_val > 0.0 else 0.0

    return leader_val  # 알 수 없는 모드 → pass-through


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
