# coding=utf-8
"""
group_expander.py 단위 테스트 — P2-4 복합 액추에이터 그룹.

대상:
  - symmetric: 팔로워 = 리더
  - windward_diff: symmetric 과 동일 (G4 게이트가 별도 처리)
  - stacked: threshold 기반 단계 개방
  - multi_stage: 이중 커튼 순서 개폐
  - 그룹 미적용 시 원본 유지
  - follower_ids() 헬퍼
"""

import pytest

from aot.functions.utils.env_control.coordinator import ActuatorCommand
from aot.functions.utils.env_control.group_expander import expand_group_commands
from aot.functions.utils.env_control.types import ActuatorGroup



# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _cmd(value, reason=1):
    return ActuatorCommand(value=value, reason=reason)


def _make_grp(mode, leader='A', members=('A', 'B'), threshold=50.0):
    return ActuatorGroup(
        group_id='g1', mode=mode,
        leader_id=leader, member_ids=list(members),
        threshold_pct=threshold,
    )


def _expand(commands, grp, prev=None):
    return expand_group_commands(commands, [grp], prev or {})


# ─────────────────────────────────────────────────────────────────────────────
# ActuatorGroup 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

class TestActuatorGroupHelper:
    def test_follower_ids_excludes_leader(self):
        grp = _make_grp('symmetric', leader='A', members=('A', 'B', 'C'))
        assert grp.follower_ids() == ['B', 'C']

    def test_follower_ids_empty_when_sole_member(self):
        grp = _make_grp('symmetric', leader='A', members=('A',))
        assert grp.follower_ids() == []


# ─────────────────────────────────────────────────────────────────────────────
# symmetric
# ─────────────────────────────────────────────────────────────────────────────

class TestSymmetric:
    def test_follower_equals_leader(self):
        grp = _make_grp('symmetric')
        result = _expand({'A': _cmd(60.0)}, grp)
        assert result['B'].value == pytest.approx(60.0)

    def test_leader_unchanged(self):
        grp = _make_grp('symmetric')
        result = _expand({'A': _cmd(40.0)}, grp)
        assert result['A'].value == pytest.approx(40.0)

    def test_reason_propagated(self):
        grp = _make_grp('symmetric')
        result = _expand({'A': _cmd(50.0, reason=2)}, grp)
        assert result['B'].reason == 2

    def test_zero_command_propagated(self):
        grp = _make_grp('symmetric')
        result = _expand({'A': _cmd(0.0)}, grp)
        assert result['B'].value == pytest.approx(0.0)

    def test_three_members(self):
        grp = _make_grp('symmetric', members=('A', 'B', 'C'))
        result = _expand({'A': _cmd(75.0)}, grp)
        assert result['B'].value == pytest.approx(75.0)
        assert result['C'].value == pytest.approx(75.0)


# ─────────────────────────────────────────────────────────────────────────────
# windward_diff
# ─────────────────────────────────────────────────────────────────────────────

class TestWindwardDiff:
    """windward_diff 은 coordinator 단계에서 symmetric, G4 가 개별 처리."""

    def test_follower_equals_leader_by_default(self):
        grp = _make_grp('windward_diff')
        result = _expand({'A': _cmd(55.0)}, grp)
        assert result['B'].value == pytest.approx(55.0)


# ─────────────────────────────────────────────────────────────────────────────
# stacked
# ─────────────────────────────────────────────────────────────────────────────

class TestStacked:
    """leader threshold=50 초과 시 팔로워 개방 시작."""

    def test_below_threshold_follower_zero(self):
        grp = _make_grp('stacked', threshold=50.0)
        result = _expand({'A': _cmd(30.0)}, grp)
        assert result['B'].value == pytest.approx(0.0)

    def test_at_threshold_follower_zero(self):
        grp = _make_grp('stacked', threshold=50.0)
        result = _expand({'A': _cmd(50.0)}, grp)
        assert result['B'].value == pytest.approx(0.0)

    def test_above_threshold_follower_opens(self):
        grp = _make_grp('stacked', threshold=50.0)
        result = _expand({'A': _cmd(70.0)}, grp)
        # follower = 70 - 50 = 20
        assert result['B'].value == pytest.approx(20.0)

    def test_full_open_leader_follower_half(self):
        grp = _make_grp('stacked', threshold=50.0)
        result = _expand({'A': _cmd(100.0)}, grp)
        assert result['B'].value == pytest.approx(50.0)

    def test_follower_clamped_to_100(self):
        # threshold=10, leader=100 → follower=90 (≤100)
        grp = _make_grp('stacked', threshold=10.0)
        result = _expand({'A': _cmd(100.0)}, grp)
        assert result['B'].value <= 100.0

    def test_different_thresholds(self):
        grp = _make_grp('stacked', threshold=30.0)
        result = _expand({'A': _cmd(80.0)}, grp)
        assert result['B'].value == pytest.approx(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# multi_stage
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiStage:
    """이중 커튼: 개방 시 내부(leader) 먼저, 폐쇄 시 외부(follower) 먼저."""

    # 개방 시나리오 (leader 올라가는 중)
    def test_opening_leader_gt0_follower_100(self):
        grp = _make_grp('multi_stage')
        prev = {'A': 0.0}
        result = _expand({'A': _cmd(50.0)}, grp, prev)
        assert result['B'].value == pytest.approx(100.0)

    def test_opening_leader_0_follower_0(self):
        grp = _make_grp('multi_stage')
        prev = {'A': 0.0}
        result = _expand({'A': _cmd(0.0)}, grp, prev)
        assert result['B'].value == pytest.approx(0.0)

    # 폐쇄 시나리오 (leader 내려가는 중)
    def test_closing_leader_gt0_follower_stays_100(self):
        """폐쇄 중: 외부(follower) leader=0 될 때까지 100% 유지."""
        grp = _make_grp('multi_stage')
        prev = {'A': 80.0}       # 이전 사이클 leader = 80
        result = _expand({'A': _cmd(40.0)}, grp, prev)   # 줄어드는 중
        assert result['B'].value == pytest.approx(100.0)

    def test_closing_leader_0_follower_closes(self):
        """리더가 완전히 닫히면 팔로워도 닫힘."""
        grp = _make_grp('multi_stage')
        prev = {'A': 20.0}
        result = _expand({'A': _cmd(0.0)}, grp, prev)
        assert result['B'].value == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 그룹 없을 때
# ─────────────────────────────────────────────────────────────────────────────

class TestNoGroups:
    def test_empty_groups_returns_original(self):
        commands = {'X': _cmd(42.0)}
        result = expand_group_commands(commands, [], {})
        assert result == commands

    def test_leader_not_in_commands_skipped(self):
        grp = _make_grp('symmetric', leader='missing')
        commands = {'other': _cmd(50.0)}
        result = expand_group_commands(commands, [grp], {})
        assert 'B' not in result
        assert result['other'].value == pytest.approx(50.0)
