# coding=utf-8
"""적응형 문서 스토리지 조회 도구(읽기 전용) 테스트.

이 도구들의 존재 이유는 "AI 가 스토리지 계층을 이해할 수 있어야 한다" 인데,
지금 그 계층은 **판정과 실물이 어긋나 있는** 상태다 — 티어 값은 갱신되지만
실제 이동(TierMigrationService._migrate_to_*)은 placeholder 라 문서 본문은
원래 자리에 남는다. 그래서 이 테스트들이 실제로 지키는 것은 반환값 형태가
아니라 **AI 가 그 어긋남을 보고받는가** 이다. 경고가 사라지면 AI 는
tier=3 을 "아카이브 완료" 로 읽고 사용자에게 그대로 전달하게 된다.

DB 는 건드리지 않는다 — 모델 쿼리는 스텁으로 대체한다.
"""
from unittest.mock import MagicMock, patch

from aot.tools import tool_registry as tr
from aot.tools.aot_data_tool_service import AoTDataToolService
# get_storage_tier_status lives in the 'system' drawer mixin -- `db` is looked
# up in that module's globals at call time, so the patches below target it.

_TOOLS = ('get_storage_tier_status',)


# ---------------------------------------------------------------------------
# 등록 규약 — 선언 한 번으로 MCP 노출·승인분류·매니페스트가 따라온다
# ---------------------------------------------------------------------------

def test_tools_are_declared_and_dispatchable():
    """virtual_tools() 는 핸들러 없는 도구를 만나면 raise 한다 — 통과 자체가 검증."""
    catalog = {v['tool_name'] for v in tr.virtual_tools()}
    for name in _TOOLS:
        assert name in catalog, f'{name} 이 MCP 카탈로그에 없다'
        tool = tr._BY_NAME[name]
        assert callable(getattr(AoTDataToolService, tool.handler, None))


def test_read_tools_need_no_approval():
    """조회 도구가 승인 게이트에 걸리면 AI 가 상태 파악조차 못 한다."""
    approval = tr.approval_required_tools()
    for name in _TOOLS:
        assert name not in approval, f'{name} 이 승인 대상으로 잡혔다'


def test_tool_descriptions_separate_intent_from_reality():
    """설명문이 '티어 값 = 의도, 아카이브 행 = 실물' 구분을 담고 있어야 한다."""
    payloads = {v['tool_name']: v['description'] for v in tr.virtual_tools()}
    status_desc = payloads['get_storage_tier_status'].lower()
    assert 'intent' in status_desc and 'archive' in status_desc


# ---------------------------------------------------------------------------
# get_storage_tier_status
# ---------------------------------------------------------------------------

def _run_status(tier_counts, archived_rows, enabled, decisions=0):
    """티어 분포·아카이브 실물·설정 활성 여부를 지정해 도구를 돌린다.

    enabled=None 은 AdaptiveStorageSettings 행 자체가 없는 상태(현 운영 상태).
    """
    db_mock = MagicMock()
    db_mock.session.query.return_value.group_by.return_value.all.return_value = tier_counts

    settings_cls = MagicMock()
    settings_cls.query.first.return_value = (
        MagicMock(enabled=enabled) if enabled is not None else None)
    decision_cls = MagicMock()
    decision_cls.query.count.return_value = decisions
    cold_cls = MagicMock()
    cold_cls.query.count.return_value = archived_rows

    with patch('aot.tools.data_tools.system.db', db_mock), \
         patch.dict('sys.modules', {
             'aot.databases.models.tier_adaptive_storage': MagicMock(
                 AdaptiveStorageSettings=settings_cls, TierDecision=decision_cls),
             'aot.databases.models.cold_storage': MagicMock(ColdDocuments=cold_cls),
         }):
        return AoTDataToolService.get_storage_tier_status()


def test_status_warns_when_tier3_exists_but_archive_is_empty():
    """가장 중요한 케이스 — 의도만 있고 실물이 없을 때 반드시 경고한다."""
    result = _run_status([(3, 12), (2, 40)], archived_rows=0, enabled=True)

    assert result['status'] == 'success'
    assert result['document_tier_counts']['3'] == 12
    assert result['archived_document_rows'] == 0
    assert 'warning' in result, '의도/실물 불일치인데 경고가 없다'
    assert 'placeholder' in result['warning'].lower()


def test_status_reports_disabled_state():
    """설정 행이 없으면(현 운영 상태) 재분류가 아예 돌지 않는다는 사실을 알린다."""
    result = _run_status([(2, 40)], archived_rows=0, enabled=None)

    assert result['adaptive_storage_enabled'] is False
    assert 'note' in result and 'disabled' in result['note'].lower()


def test_status_has_no_warning_when_consistent():
    """tier 3 문서가 없으면 경고할 불일치도 없다 — 무조건 겁주지 않는다."""
    result = _run_status([(1, 5), (2, 40)], archived_rows=0, enabled=True)
    assert 'warning' not in result


# ---------------------------------------------------------------------------
# 자동 티어 이동 — "옮겼다" 고 거짓 보고하지 않는가
# ---------------------------------------------------------------------------

def test_tier_migration_reports_content_not_moved():
    """tier 값만 바뀌고 본문은 그대로인 상태를 결과가 정직하게 담아야 한다.

    예전에는 _migrate_to_cold() 가 로그만 찍고 조용히 돌아와서, 호출자가
    success=True 를 반환하고 TierDecision 에 전환까지 기록했다 — 아무것도
    옮기지 않았는데 감사 기록만 남는 셈이었다.
    """
    from aot.ai.services.tier_decision_engine import TierMigrationService as TMS

    doc = MagicMock(unique_id='note-1', tier=2, note='본문')
    with patch('aot.aot_flask.extensions.db'), \
         patch.object(TMS, '_is_transition_rate_limited', return_value=False), \
         patch.object(TMS, '_log_transition'):
        result = TMS.migrate_document(doc, target_tier=3)

    assert result['success'] is True          # tier 갱신 자체는 유효하다
    assert result['content_moved'] is False   # 그러나 본문은 옮겨지지 않았다
    assert doc.note == '본문'


def test_tier_migration_to_warm_needs_no_move():
    """warm 은 원래 자리다 — 옮길 것이 없으므로 moved=True 가 맞다."""
    from aot.ai.services.tier_decision_engine import TierMigrationService as TMS

    doc = MagicMock(unique_id='note-1', tier=3, note='본문')
    with patch('aot.aot_flask.extensions.db'), \
         patch.object(TMS, '_is_transition_rate_limited', return_value=False), \
         patch.object(TMS, '_log_transition'):
        result = TMS.migrate_document(doc, target_tier=2)

    assert result['success'] is True
    assert result['content_moved'] is True
