# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoPlotStageEvent(CRUDMixin, db.Model):
    """확인된 단계 전환 하나 (추가 전용 원장).

    설계 정본: docs/design/program-layer.md §P5

    ## 승인은 기록이 아니라 **보정**이다

    현재 단계는 파생값이다(시작일 + 프로그램). 승인이 그 파생을 바꾸지 않으면
    "확인했음" 체크박스일 뿐이라 만들 이유가 없다.

    그래서 승인은 **기준점을 옮긴다** — "정식기가 8/17 에 시작됐다" 가 확인되면
    그 뒤의 단계는 심은 날이 아니라 8/17 부터 계산한다. 프로그램은 표준이고
    현실은 표준대로 가지 않으므로, 확인된 사실이 들어올 때마다 남은 계산이
    거기에 맞춰 다시 정렬되는 것이 맞다.

    ## 대기 중 전환은 이 표에 없다

    "승인 대기" 는 파생값이다 — 기준점 이후로 계산한 단계가 기준점의 단계보다
    앞서면 그것이 제안이다. 대기 행을 만들면 프로그램을 고치거나 GDD 가 밀릴 때
    그 행이 조용히 낡고, 아무도 보지 않는 구획을 위해 배경 잡이 필요해지며,
    같은 사실이 두 곳에 있게 된다. **그래서 배경 잡이 없다.**

    ## 되돌리기는 행을 지우지 않는다

    지우면 "누가 언제 확인했다가 물렀다" 가 사라지고 같은 판단을 다시 하게 된다
    (`device_binding.unbind` 가 행을 지우지 않는 것과 같은 규율).

    @phase active
    @stability experimental
    @dependency GeoPlot, GeoProgram
    """
    __tablename__ = "geo_plot_stage_event"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # GeoPlot.unique_id. 문자열 참조 — 이 도메인의 다른 표와 같은 규약이다.
    plot_uuid = db.Column(db.String(36), nullable=False, index=True)

    # 어느 단계로 들어갔나. 프로그램의 `stages[].key` 와 같은 어휘.
    stage_key = db.Column(db.String(64), nullable=False)
    # 1-based. 프로그램을 고쳐 키가 바뀌어도 순서로는 읽을 수 있게 함께 둔다.
    stage_index = db.Column(db.Integer, nullable=False)

    # **그 단계가 시작된 날.** `decided_at`(확인한 시각)과 다르다 — 사흘 뒤에
    # 확인해도 단계는 사흘 전에 시작됐다. 이후 계산의 기준점이 되는 것은 이쪽이다.
    started_on = db.Column(db.Date, nullable=False)

    # 무엇을 근거로 제안됐나 — 'days' | 'gdd' | 'manual'.
    # 사람이 날짜를 직접 고쳐 넣으면 'manual' 이다.
    source = db.Column(db.String(16), nullable=False, default='manual')

    decided_at = db.Column(db.DateTime, default=utc_now)
    decided_by = db.Column(db.String(64), nullable=True)

    # 되돌림 표시. NULL 이 아니면 이 행은 기준점 계산에서 빠지지만 기록으로는
    # 남는다.
    undone_at = db.Column(db.DateTime, nullable=True)
    undone_by = db.Column(db.String(64), nullable=True)

    # 자동으로 남은 줄인가(P7). `decided_by` 가 비었다는 것만으로는 "로그인
    # 정보가 없는 사람이 눌렀다" 와 구분되지 않는다 — 사람이 이력을 볼 때
    # 그 둘은 완전히 다른 사실이다.
    auto = db.Column(db.Boolean, nullable=False, default=False)

    note = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return ("<GeoPlotStageEvent(plot={s.plot_uuid!r}, stage={s.stage_key!r},"
                " started_on={s.started_on})>".format(s=self))
