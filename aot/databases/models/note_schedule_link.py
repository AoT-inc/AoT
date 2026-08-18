# coding=utf-8
"""노트 본문의 한 조각 ↔ 그 조각으로 만든 예정.

**분류가 아니라 관계다.** 노트와 일정은 서로 다른 종류가 아니라, 사람이 쓴
문장과 그 문장의 한 조각이 시각을 얻은 것이다. 예전에는 쓰기 **전에** "이건
노트인가 일정인가" 를 고르게 했는데, 그 구분은 저장 테이블 이름이지 사람이
아는 구분이 아니었다 — 실제로 `action_type='note'` 인 일정과
`category='schedule'` 인 노트가 둘 다 실데이터에 있다.

이제 사용자는 노트만 쓴다. 쓴 뒤에 한 구간을 골라 시각을 주면 이 행이 생긴다.

**offset 은 흔들린다.** 노트를 나중에 고치면 구간 위치가 어긋나므로,
선택 당시의 텍스트(`text_snapshot`)를 함께 들고 있다가 재탐색한다. 그래도
못 찾으면 **하이라이트만 포기하고 링크는 유지한다** — 표시가 깨지는 것과
관계가 끊기는 것은 다른 일이다.

**FK 를 걸지 않는다.** 일정 삭제 경로가 한 곳이 아니고(이 레포는 장치 삭제
17경로로 이미 크게 데었다), 그중 하나만 링크 정리를 빠뜨려도 DB 제약이
그 삭제를 통째로 거부해 버린다. 대신 링크를 **읽을 때** 대상 일정이
사라졌으면 그 자리에서 걷어낸다(`prune_dangling`). 고아가 남더라도 화면과
집계에는 나타나지 않고, 다음 조회가 치운다.
"""
from aot.utils.time_utils import utc_now

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class NoteScheduleLink(CRUDMixin, db.Model):
    """노트 한 구간과 예정 하나를 잇는다.

    한 노트에 여러 구간이 붙을 수 있고(문단마다 다른 날), 한 구간은 예정
    하나만 갖는다.

    @phase active
    """
    __tablename__ = "note_schedule_link"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # Notes.unique_id — 정수 id 가 아니라 uuid 로 잡는다(이 레포의 모든
    # 교차 참조가 uuid 다).
    note_id = db.Column(db.String(36), nullable=False, index=True)
    # SchedulerJobMeta.unique_id — 정수 id 는 재사용될 수 있고, 감사 로그가
    # 정수 id 를 NOT NULL 로 물고 있어 삭제 순서에 얽힌다.
    job_uid = db.Column(db.String(36), nullable=False, index=True)

    # 선택 구간(문자 offset). 편집으로 어긋나면 스냅샷으로 재탐색해 갱신한다.
    start_offset = db.Column(db.Integer, nullable=False, default=0)
    end_offset = db.Column(db.Integer, nullable=False, default=0)
    # 선택 당시의 텍스트. **재탐색의 유일한 근거**라 비워 두지 말 것.
    text_snapshot = db.Column(db.Text, nullable=False, default='')

    created_at = db.Column(db.DateTime, default=utc_now)

    def __repr__(self):
        return "<{cls}(note={s.note_id}, job={s.job_uid})>".format(
            s=self, cls=self.__class__.__name__)
