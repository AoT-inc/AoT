# coding=utf-8
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class DeviceMember(CRUDMixin, db.Model):
    """복합장치(Device)의 부가(secondary) 소속 — 다대다 + 장치 간 계층.

    Phase 1~6의 parent_device_id(Input/Output/Function/CustomController에 존재)는
    "이 항목을 자동 생성·소유하고 활성화를 cascade하는 단 하나의 상위 장치"를
    가리키는 **1급(primary) 소유 관계**다 — 그 의미는 이 테이블 도입 후에도
    바뀌지 않는다.

    이 테이블은 그와 별개로, 이미 다른 장치에 소속된 항목(또는 장치 자신)을
    "추가로" 다른 장치의 구성에 참조 전용으로 끼워 넣기 위한 것이다(설계 근거:
    .local/plans/device_group_console_plan.md Phase 8/9). 예: 온실 A의 외기온
    센서가 "온실 A 제어" 장치의 주 소유물이면서, 동시에 "전체 기상 모니터링"
    장치의 참조 목록에도 보이고 싶을 때. 장치가 장치를 참조하면(member_type=
    'device') 그것이 곧 장치 간 계층이다 — 별도 메커니즘을 만들지 않고 같은
    테이블·같은 의미(참조 전용, 소유권 없음)를 재사용한다.

    참조 관계는 활성화 cascade(Phase 4)에 관여하지 않는다 — 소유자가 둘 이상일
    수 있는 관계에서 한쪽이 비활성화한다고 다른 쪽이 의존하는 멤버를 꺼버리면
    안 되기 때문이다. cascade는 parent_device_id 단일 소유 관계만 본다.

    @phase active
    @stability experimental
    @dependency CustomController, Input, Output
    """
    __tablename__ = "device_member"
    __table_args__ = (
        db.UniqueConstraint('device_id', 'member_type', 'member_id', name='uq_device_member'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    # 참조하는 쪽 장치의 CustomController.unique_id.
    device_id = db.Column(db.String(36), nullable=False, index=True)
    # 'input' | 'output' | 'device' — member_id 가 어느 테이블 소속인지.
    member_type = db.Column(db.String(16), nullable=False)
    # 참조되는 Input/Output/CustomController 의 unique_id.
    member_id = db.Column(db.String(36), nullable=False, index=True)
