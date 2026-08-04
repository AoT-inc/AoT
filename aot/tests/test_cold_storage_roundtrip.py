# coding=utf-8
"""콜드 스토리지 왕복 통합 테스트 — 실제 DB·실제 파일로 태운다.

`test_cold_storage_service.py` 는 전 구간을 mock 한다. 그 방식은 호출 규약은
지켜주지만 **실제로 동작하는지는 전혀 보증하지 않는다.** 2026-08-04 에 mock
테스트 31건이 전부 통과하는 상태에서 다음 세 가지가 동시에 깨져 있었다.

  1. `ColdDocuments.query.join(ArchiveIndex)` — 두 테이블에 FK 가 없어
     조건 없는 join 은 InvalidRequestError 를 낸다. 즉 검색은 호출하면
     무조건 예외였다.
  2. `search_archives(query=...)` 의 query 인자가 본문 어디서도 쓰이지
     않았다. 키워드를 넘겨도 전체가 반환됐다.
  3. 메타데이터를 `json.dumps(...)` 기본값으로 저장해 한글이 \\uXXXX 로
     이스케이프됐다. 원문 '딸기' 로는 한 건도 매칭되지 않는다 — 한국어가
     기본인 시스템에서 태그·제목 검색이 통째로 무력했다.

셋 다 mock 을 지나쳤고, 임시 DB 에 실제로 태워보자마자 드러났다. 그래서 이
파일은 mock 을 쓰지 않는다. 임시 sqlite + 임시 디렉터리에만 쓰므로 어떤
운영 데이터도 건드리지 않는다.
"""
import json
import os

import pytest

from aot.aot_flask.extensions import db
import aot.databases.models  # noqa: F401  — 모델 등록(테이블 생성에 필요)
from aot.databases.models.cold_storage import ArchiveAuditLog, ArchiveIndex, ColdDocuments
from aot.services.cold_storage_service import ColdStorageService

CONTENT = "딸기 정식 3일차. 야간 최저 12.4도, 결로 없음.\n" * 40
META = {"title": "정식 기록", "tags": ["딸기", "정식"], "zone": "1-1"}


@pytest.fixture()
def svc(tmp_path):
    """임시 sqlite + 임시 아카이브 경로에 묶인 서비스."""
    from flask import Flask

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{tmp_path / 'roundtrip.db'}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield ColdStorageService(archive_base_path=str(tmp_path / 'archives'))
        db.session.remove()


def _archive(svc, doc_id='note-001', content=CONTENT, metadata=META, **kw):
    return svc.archive_document(document_id=doc_id, content=content,
                                metadata=metadata, archived_by='ai', **kw)


# ---------------------------------------------------------------------------
# 아카이브 → 조회 → 복원
# ---------------------------------------------------------------------------

def test_archive_writes_compressed_file_and_rows(svc):
    result = _archive(svc)

    assert os.path.exists(result['archive_path']), '압축 파일이 생성되지 않았다'
    row = ColdDocuments.query.filter_by(document_id='note-001').first()
    assert row is not None
    assert row.compressed_size < row.original_size, '압축이 되지 않았다'
    assert ArchiveIndex.query.filter_by(document_id='note-001').count() == 1


def test_restore_returns_byte_identical_content(svc):
    """압축·해제를 거쳐도 본문이 한 글자도 달라지면 안 된다."""
    _archive(svc)
    restored = svc.restore_document('note-001', decompress=True)
    assert restored['content'] == CONTENT


def test_restore_metadata_only_does_not_read_file(svc):
    """decompress=False 는 메타데이터만 — 파일이 없어도 성공해야 한다."""
    result = _archive(svc)
    os.remove(result['archive_path'])

    meta_only = svc.restore_document('note-001', decompress=False)
    assert meta_only['metadata'] == META


def test_restore_missing_file_raises(svc):
    """DB 행은 있는데 파일이 사라진 불일치는 조용히 넘어가면 안 된다."""
    result = _archive(svc)
    os.remove(result['archive_path'])

    with pytest.raises(FileNotFoundError):
        svc.restore_document('note-001', decompress=True)


def test_archive_twice_is_rejected(svc):
    """같은 문서가 두 벌 보관되면 어느 쪽이 정본인지 알 수 없게 된다."""
    _archive(svc)
    with pytest.raises(ValueError, match='already archived'):
        _archive(svc)


def test_restore_updates_access_tracking(svc):
    """읽기가 last_accessed/restore_count 에 반영돼야 티어 판정이 의미를 갖는다."""
    _archive(svc)
    before = ColdDocuments.query.filter_by(document_id='note-001').first()
    prev_count = before.restore_count or 0

    svc.restore_document('note-001', decompress=True)

    after = ColdDocuments.query.filter_by(document_id='note-001').first()
    assert (after.restore_count or 0) == prev_count + 1


# ---------------------------------------------------------------------------
# 검색 — 위 3개 회귀가 여기서 잡힌다
# ---------------------------------------------------------------------------

def test_search_runs_at_all(svc):
    """회귀 1: 조인 조건이 빠지면 호출 자체가 InvalidRequestError 로 죽는다."""
    _archive(svc)
    result = svc.search_archives()
    assert result['total'] == 1


def test_search_actually_filters_by_query(svc):
    """회귀 2: query 인자가 무시되면 무엇을 넣든 전체가 돌아온다."""
    _archive(svc, doc_id='note-strawberry', metadata={"tags": ["딸기"]})
    _archive(svc, doc_id='note-tomato', metadata={"tags": ["토마토"]})

    assert svc.search_archives()['total'] == 2
    hit = svc.search_archives(query='토마토')
    assert hit['total'] == 1
    assert hit['results'][0]['document_id'] == 'note-tomato'


def test_search_matches_korean_metadata(svc):
    """회귀 3: ensure_ascii 기본값이면 한글이 이스케이프돼 영원히 안 맞는다."""
    _archive(svc)

    row = ColdDocuments.query.filter_by(document_id='note-001').first()
    assert '딸기' in row.meta_json, 'meta_json 에 한글이 원문으로 저장돼야 한다'
    assert '\\u' not in row.meta_json

    assert svc.search_archives(query='딸기')['total'] == 1


def test_search_metadata_filters_match_korean_values(svc):
    """키=값 필터도 같은 인코딩 규칙을 따라야 한다."""
    _archive(svc)
    result = svc.search_archives(metadata_filters={'zone': '1-1'})
    assert result['total'] == 1


def test_search_returns_metadata_as_dict(svc):
    """결과의 metadata 가 문자열로 새어 나가면 호출자가 매번 파싱해야 한다."""
    _archive(svc)
    archives = svc.search_archives()['results']
    assert isinstance(archives[0]['metadata'], dict)
    assert archives[0]['metadata']['title'] == '정식 기록'


# ---------------------------------------------------------------------------
# 삭제 · 감사 로그
# ---------------------------------------------------------------------------

def test_delete_removes_file_and_row(svc):
    result = _archive(svc)
    path = result['archive_path']

    assert svc.delete_archive('note-001', deletion_reason='테스트 정리') is True
    assert not os.path.exists(path), '파일이 남아 있다'
    assert ColdDocuments.query.filter_by(document_id='note-001').first() is None


def test_delete_unknown_document_returns_false(svc):
    assert svc.delete_archive('nope') is False


def test_operations_are_audited(svc):
    """무엇이 언제 보관·복원·삭제됐는지 남지 않으면 사후 추적이 불가능하다."""
    _archive(svc)
    svc.restore_document('note-001', decompress=True)
    svc.delete_archive('note-001', deletion_reason='정리')

    ops = [a.operation for a in ArchiveAuditLog.query.order_by(ArchiveAuditLog.id).all()]
    assert 'archive' in ops and 'restore' in ops and 'delete' in ops


def test_audit_records_sizes_on_archive(svc):
    _archive(svc)
    entry = ArchiveAuditLog.query.filter_by(operation='archive').first()
    assert entry.original_size > entry.compressed_size > 0


# ---------------------------------------------------------------------------
# 통계
# ---------------------------------------------------------------------------

def test_archive_stats_reflect_reality(svc):
    """도구가 그대로 노출하는 값이라, 실물과 어긋나면 AI 가 잘못 보고한다."""
    _archive(svc, doc_id='a')
    _archive(svc, doc_id='b')

    stats = svc.get_archive_stats()
    assert stats['total_archived'] == 2
    assert stats['active_archives'] == 2
    assert stats['total_original_size_bytes'] > stats['total_compressed_size_bytes'] > 0
