# coding=utf-8
"""P6-56: 지식 항목의 출처 URL — `AIKnowledgeChunk.source_url`.

## 왜 필요한가

설계(§3.2)는 AI 가 비친 미확인 지식이 **사람이 확인하면 승격된다**는 경로를
전제한다. 그런데 확인할 방법이 없었다. 출처를 담는 자리가 `attribution`
자유 텍스트뿐이라, 리뷰어가 "이게 맞는 말인가" 를 물어도 **원문으로 돌아갈
길이 없었다.** 그래서 미확인 항목은 실질적으로 영원히 미확인으로 남는다.

MCP 로 연결된 외부 LLM 이 웹에서 조사한 요약을 비치하게 되면서 이 구멍이
결정적이 됐다. 그런 항목은 정의상 **바깥에 원문이 있고**, 그 원문 주소가
승격 판단의 전부다.

## 왜 attribution 을 파싱하지 않는가

자유 텍스트에서 URL 을 긁어내는 것은 쓰는 쪽이 어떤 형식으로 적을지에
기대는 일이다. 화면이 링크를 걸려면 "여기에 주소가 있다" 가 스키마여야 한다.
`attribution` 은 사람이 읽는 출처 표기로 그대로 두고(예: "농사로 무 재배
정보"), 주소만 따로 받는다.

## 신뢰를 올리지 않는다

이 컬럼이 있다고 해서 항목이 더 신뢰받지는 않는다. 쓰는 쪽이 "이건 권위
출처야" 라고 자기 신고하는 것을 믿으면 §3.3 오염 방지가 무너진다. 진입은
여전히 `ai_curated`/미확인이고, 이 값은 **사람이 확인할 수 있게** 할 뿐이다.

기존 행은 전부 NULL 이며 검색·주입 어디도 이 값을 읽지 않는다 —
업그레이드 직후 동작은 이전과 같다.

Revision ID: p6_58_knowledge_source_url_20260824
Revises: p6_57_plot_stage_overrides_20260824
Create Date: 2026-08-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_58_knowledge_source_url_20260824'
down_revision = 'p6_57_plot_stage_overrides_20260824'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if 'source_url' in _columns(bind, 'ai_knowledge_chunk'):
        return                      # 재실행 안전
    with op.batch_alter_table('ai_knowledge_chunk', schema=None) as batch:
        batch.add_column(sa.Column('source_url', sa.String(length=500), nullable=True))


def downgrade():
    bind = op.get_bind()
    if 'source_url' not in _columns(bind, 'ai_knowledge_chunk'):
        return
    with op.batch_alter_table('ai_knowledge_chunk', schema=None) as batch:
        batch.drop_column('source_url')
