# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoJournal(CRUDMixin, db.Model):
    """구획·구역 **일지** — 그때 그 자리의 사실을 떠 둔 스냅샷.

    설계 정본: 일지 기능 계획서 §1

    ## 왜 스냅샷인가 (열람할 때 다시 계산하지 않는다)

    일지는 "작기가 끝난 뒤 무엇을 어떻게 키웠나" 를 한 문서로 남기고 제3자
    (인증기관·다음 담당자)에게 넘기기 위한 것이다. 그런데 장치 배선·프로그램·
    구역 경계는 **그 뒤에도 계속 바뀐다.** 열 때마다 다시 계산하면 작년 일지의
    내용이 올해 배선에 맞춰 조용히 달라지고, 그러면 그것은 기록이 아니다.

    그래서 생성 시점에 §6 계약대로 한 번 뜨고(`data`), 이후 열람(HTML/MD/JSON/
    MCP 어느 경로든)은 이 행을 읽기만 한다. 부수 효과로 성능도 따라온다 —
    InfluxDB 를 다시 두드리지 않는다.

    ## `status` 가 왜 필요한가

    집계는 채널마다 InfluxDB 쿼리가 나가는 작업이라 요청 스레드에서 돌리면
    저사양 기기(라즈베리파이)에서 웹이 멎는다. 그래서 `pending` 행을 먼저
    만들고 백그라운드에서 채운다(§13b). 화면은 이 값으로 "생성 중" 을 말한다.

    `started_at` 은 그 백그라운드가 **중간에 죽었을 때** 회수하기 위한 것이다
    (프로세스 재시작 등). 없으면 그 행이 영원히 'running' 으로 남아 사용자에게
    "잠시 후 새로고침" 을 영원히 말하게 된다(§13d).

    ## 삭제해도 원본은 다치지 않는다

    이 표는 **파생 기록**이다. 지워도 구획·노트·측정값 어느 것도 사라지지
    않는다 — 되만들면 (그 사이 배선이 안 바뀌었다면) 같은 문서가 나온다.
    """
    __tablename__ = 'geo_journal'

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # 'plot' | 'zone' | 'site'. GeoPlot 과 GeoShape 를 함께 가리키므로 FK 를
    # 걸지 않는다 — 대상 표가 둘이고, 원본이 지워져도 **일지는 남아야 한다**
    # (지워진 구획의 작기 기록이 그 삭제로 함께 사라지면 기록의 뜻이 없다).
    target_type = db.Column(db.String(16), nullable=False)
    target_id = db.Column(db.String(36), nullable=False, index=True)

    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)

    # 일 경계를 가른 시간대(§4-1). 저장해 두지 않으면 나중에 같은 문서를
    # 다시 해석할 근거가 없다 — "이 하루가 어디부터 어디까지였나" 는 tz 가
    # 정한다.
    tz_name = db.Column(db.String(64), nullable=True)

    title = db.Column(db.String(160), nullable=False, default='')
    summary = db.Column(db.Text, nullable=True)

    # pending | running | done | error
    status = db.Column(db.String(16), nullable=False, default='pending')
    started_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # §6 계약의 jsonable 스냅샷. status='done' 일 때만 채워진다.
    data = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def is_ready(self):
        return self.status == 'done' and self.data is not None
