# coding=utf-8
"""P6-00: 알렘빅 체인 리베이스라인 — 2026-07-20.

이 시점(115개 리비전, 718f314963bc~p5_53_drop_ai_task_history)까지의 스텝별
마이그레이션 파일들을 대체하는 단일 베이스라인. 신규 설치는 alembic 체인을
전혀 타지 않고 db.create_all() + 자체 스탬프로 스키마를 만들기 때문에(
aot/aot_flask/app.py, aot/databases/models/__init__.py) 이 파일의
upgrade()/downgrade()는 실질적으로 실행될 일이 없다 — 존재 이유는 두 가지뿐:
  1) alembic이 "head"를 계산하려면 최소 하나의 리비전 파일이 있어야 함
  2) 앞으로 추가될 새 마이그레이션이 down_revision으로 연결할 지점 제공

리베이스라인 시점에 실제로 운영 중이던 4개 설치(로컬 Docker, aot-004, aot-005,
koat-macmini)는 전부 이 리비전으로 직접 재스탬프됨(옛 체인을 다시 걷지 않음).
과거 체인 전체는 git 히스토리(로컬 Gitea)에 남아있어 필요하면 조회 가능.

Revision ID: p6_00_rebaseline_20260720
Revises:
Create Date: 2026-07-20
"""

revision = 'p6_00_rebaseline_20260720'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 리베이스라인 시점 스키마는 db.create_all()이 담당(위 docstring 참고).
    # 이 리비전을 직접 밟는 경로는 없다 — 그래도 alembic upgrade가 우연히
    # 이 지점부터 시작되는 경우를 위해 명시적으로 아무 것도 하지 않는다.
    pass


def downgrade():
    pass
