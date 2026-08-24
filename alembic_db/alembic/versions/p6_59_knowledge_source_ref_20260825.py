# coding=utf-8
"""P6-59: 지식 항목이 어느 등록 소스에서 나왔는지 — `AIKnowledgeChunk.source_ref`.

## 왜 필요한가

AI 가 비치하는 항목은 전부 `ai_curated`/미확인으로 들어간다(설계 §4). 그건 옳다 —
쓰는 쪽의 자기 신고를 믿으면 오염 방지가 무너진다.

그런데 실제로는 성격이 다른 둘이 같은 칸에 쌓인다:

  (가) AI 가 **등록된 소스를 조회해 그대로 옮긴 것**
       예: query_reference_table 로 FAO ECOCROP(CC BY 4.0)에서 읽은 수치
  (나) AI 가 **추론해 만든 것**
       예: 대화 중 관찰을 정리한 메모

(가)는 확인이 기계적이다 — 어느 소스에서 나왔는지 알면 리뷰어가 그 소스의
주소로 바로 가서 대조하면 된다. (나)는 사람이 판단해야 한다. 둘을 구분하지
못하면 리뷰 부담만 쌓이고, 결국 아무도 안 본다.

## attribution·source_url 이 이미 있는데 왜 또

둘 다 **자유 텍스트**다. AI 가 그럴듯한 문자열을 적어 넣어도 서버는 모른다.
이 컬럼은 `ai_context_source.source_id` 를 가리키고, 쓰기 시점에 **그런 소스가
실제로 등록돼 있는지 서버가 확인한다.** "AI 가 ECOCROP 이라고 말했다" 와 "이
시스템에 실제로 있는 ECOCROP 소스를 가리킨다" 의 차이다.

## 신뢰를 올리지는 않는다

여전히 `ai_curated` 이고 진입 상태도 그대로다. 바뀌는 것은 **인용 태그와 리뷰
화면**뿐이다 — "[AI 정리 — 미확인]" 대신 "[AI 정리 — 출처: FAO ECOCROP]" 으로
인용되어, 읽는 사람과 모델이 확인 가능한 것과 아닌 것을 가릴 수 있다.

FK 를 걸지 않는다: 소스가 지워져도 지식은 남아야 하고(그 소스가 무엇이었는지는
attribution 에 글로 남는다), 지워진 소스를 가리키는 값은 화면에서 "확인 불가"로
보이면 충분하다.

기존 행은 전부 NULL 이며 검색·주입 경로는 이 값을 읽지 않는 한 종전과 같다.

Revision ID: p6_59_knowledge_source_ref_20260825
Revises: p6_58_knowledge_source_url_20260824
Create Date: 2026-08-25
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_59_knowledge_source_ref_20260825'
down_revision = 'p6_58_knowledge_source_url_20260824'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if 'source_ref' in _columns(bind, 'ai_knowledge_chunk'):
        return                      # 재실행 안전
    with op.batch_alter_table('ai_knowledge_chunk', schema=None) as batch:
        batch.add_column(sa.Column('source_ref', sa.String(length=36), nullable=True))


def downgrade():
    bind = op.get_bind()
    if 'source_ref' not in _columns(bind, 'ai_knowledge_chunk'):
        return
    with op.batch_alter_table('ai_knowledge_chunk', schema=None) as batch:
        batch.drop_column('source_ref')
