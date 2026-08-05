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

from aot.ai.services import tool_registry as tr
from aot.ai.services.aot_data_tool_service import AoTDataToolService

_TOOLS = ('get_storage_tier_status', 'search_archives', 'get_archived_document')


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
    # 아카이브에 없는 tier 3 문서는 검색되지 않는다는 사실이 명시돼야 한다.
    assert 'not appear' in payloads['search_archives'].lower()


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

    with patch('aot.ai.services.aot_data_tool_service.db', db_mock), \
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
# search_archives / get_archived_document
# ---------------------------------------------------------------------------

def test_search_archives_empty_is_success_not_error():
    """빈 결과를 오류로 표현하면 AI 가 '검색 실패' 로 오해한다."""
    svc = MagicMock()
    svc.search_archives.return_value = {'archives': [], 'total': 0}
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        result = AoTDataToolService.search_archives(query='딸기')

    assert result['status'] == 'success'
    assert result['count'] == 0
    assert 'note' in result


def test_search_archives_clamps_limit():
    """limit 을 무한정 키우면 조회가 통째로 무거워진다."""
    svc = MagicMock()
    svc.search_archives.return_value = {'archives': [], 'total': 0}
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        AoTDataToolService.search_archives(limit=99999, offset=-5)

    kwargs = svc.search_archives.call_args[1]
    assert kwargs['limit'] == 200
    assert kwargs['offset'] == 0


def test_get_archived_document_requires_id():
    result = AoTDataToolService.get_archived_document(document_id=None)
    assert result['status'] == 'error'


def test_get_archived_document_not_found_explains_tier_flag():
    """아카이브에 없을 때, tier 값이 의도일 뿐이라는 설명이 함께 가야 한다."""
    svc = MagicMock()
    svc.restore_document.return_value = None
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        result = AoTDataToolService.get_archived_document(document_id='doc-1')

    assert result['status'] == 'not_found'
    assert 'intent' in result['message'].lower()


def test_get_archived_document_surfaces_missing_file():
    """DB 행은 있는데 파일이 없는 불일치를 삼키면 안 된다."""
    svc = MagicMock()
    svc.restore_document.side_effect = FileNotFoundError('/var/aot/archives/x.archive')
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        result = AoTDataToolService.get_archived_document(document_id='doc-1')

    assert result['status'] == 'error'
    assert 'missing' in result['message'].lower()


def test_get_archived_document_metadata_only_by_default():
    """기본은 메타데이터만 — 본문 해제는 명시적으로 요청할 때만."""
    svc = MagicMock()
    svc.restore_document.return_value = {'document_id': 'doc-1', 'metadata': {}}
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        AoTDataToolService.get_archived_document(document_id='doc-1')

    assert svc.restore_document.call_args[1]['decompress'] is False


# ---------------------------------------------------------------------------
# 쓰기 도구 — 승인 게이트 + "복사이지 이동이 아니다" 계약
# ---------------------------------------------------------------------------

_WRITE_TOOLS = ('archive_note', 'restore_note_from_archive',
                'set_document_tier', 'delete_archive')


def test_write_tools_require_approval():
    """데이터를 옮기거나 지우는 도구가 승인 없이 실행되면 안 된다."""
    approval = tr.approval_required_tools()
    for name in _WRITE_TOOLS:
        assert name in approval, f'{name} 이 승인 게이트를 타지 않는다'
        assert tr._BY_NAME[name].mutating is True


def test_write_tool_descriptions_state_original_is_kept():
    """아카이브가 원본을 지운다고 오해하면 AI 가 사용자에게 잘못 안내한다."""
    d = {v['tool_name']: v['description'] for v in tr.virtual_tools()}
    assert 'not deleted' in d['archive_note'].lower()
    assert 'moves no data' in d['set_document_tier'].lower()
    assert 'irreversible' in d['delete_archive'].lower()


def _note(tier=2, content='본문', unique_id='note-1'):
    return MagicMock(unique_id=unique_id, note=content, name='메모',
                     note_tags='', tier=tier)


def _patch_notes(note):
    """Notes.query.filter_by(...).first() 가 note 를 돌려주도록."""
    notes_cls = MagicMock()
    notes_cls.query.filter_by.return_value.first.return_value = note
    return patch('aot.ai.services.aot_data_tool_service.Notes', notes_cls)


def test_archive_note_copies_and_marks_tier3():
    note = _note()
    svc = MagicMock()
    svc.archive_document.return_value = {
        'archive_path': '/var/aot/archives/2026/08/note-1.archive',
        'compression_ratio': 88.0,
    }
    with _patch_notes(note), \
         patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc), \
         patch('aot.ai.services.aot_data_tool_service.db'):
        result = AoTDataToolService.archive_note(note_id='note-1')

    assert result['status'] == 'success'
    assert note.tier == 3
    # 본문은 그대로 남아야 한다 — 아카이브는 복사다.
    assert note.note == '본문'
    assert 'not deleted' in result['note'].lower()


def test_archive_note_rejects_empty_content():
    with _patch_notes(_note(content='   ')):
        result = AoTDataToolService.archive_note(note_id='note-1')
    assert result['status'] == 'error'


def test_archive_note_surfaces_duplicate():
    """이미 아카이브된 문서를 다시 넣으면 사본이 둘 생긴다 — 서비스가 막고, 도구가 전달."""
    svc = MagicMock()
    svc.archive_document.side_effect = ValueError('Document note-1 is already archived')
    with _patch_notes(_note()), \
         patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc), \
         patch('aot.ai.services.aot_data_tool_service.db'):
        result = AoTDataToolService.archive_note(note_id='note-1')

    assert result['status'] == 'error'
    assert 'already archived' in result['message']


def test_restore_reports_orphan_archive():
    """원본이 사라진 아카이브를 조용히 되살리면 안 된다 — 상태를 밝힌다."""
    svc = MagicMock()
    svc.restore_document.return_value = {'content': '보관된 본문'}
    with _patch_notes(None), \
         patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc), \
         patch('aot.ai.services.aot_data_tool_service.db'):
        result = AoTDataToolService.restore_note_from_archive(note_id='note-1')

    assert result['status'] == 'orphan_archive'
    assert result['content'] == '보관된 본문'


def test_restore_moves_tier_back():
    note = _note(tier=3)
    svc = MagicMock()
    svc.restore_document.return_value = {'content': '본문'}
    with _patch_notes(note), \
         patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc), \
         patch('aot.ai.services.aot_data_tool_service.db'):
        result = AoTDataToolService.restore_note_from_archive(note_id='note-1')

    assert result['status'] == 'success'
    assert note.tier == 2
    assert result['content_matches_original'] is True


def test_set_document_tier_warns_that_nothing_moved():
    """tier=3 만 찍고 끝나는데 '아카이브했다'로 읽히면 안 된다."""
    note = _note(tier=2)
    with _patch_notes(note), patch('aot.ai.services.aot_data_tool_service.db'):
        result = AoTDataToolService.set_document_tier(note_id='note-1', tier=3)

    assert result['status'] == 'success'
    assert result['previous_tier'] == 2 and result['tier'] == 3
    assert 'nothing was moved' in result['note'].lower()


def test_set_document_tier_rejects_bad_value():
    for bad in (0, 4, 'cold', None):
        result = AoTDataToolService.set_document_tier(note_id='note-1', tier=bad)
        assert result['status'] == 'error', bad


def test_delete_archive_says_original_untouched():
    svc = MagicMock()
    svc.delete_archive.return_value = True
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        result = AoTDataToolService.delete_archive(document_id='note-1', reason='정리')

    assert result['status'] == 'success'
    assert 'not touched' in result['note'].lower()


def test_delete_archive_not_found():
    svc = MagicMock()
    svc.delete_archive.return_value = False
    with patch.object(AoTDataToolService, '_cold_storage_service', return_value=svc):
        result = AoTDataToolService.delete_archive(document_id='missing')
    assert result['status'] == 'not_found'


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
