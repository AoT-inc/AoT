# coding=utf-8
"""대상 별칭 — 사용자가 대상(장소·장치·함수·위젯 …)을 부르는 다른 이름.

사용자는 '3포장' 을 "산포장"(음성 인식이 바꾼 표기)으로, 위젯 '육묘장' 을 "육묘장 그래프"
로 부른다. 별칭은 사용자가 정하는 **데이터**다 — 코드에 그런 값을 넣지 않고, 설정 화면
칸도 두지 않는다. AI 가 사용자 말을 듣고 등록한다(record.alias_add).

- 서버(농장) 단위로 저장해 어떤 AI·계정이 붙어도 같은 별칭을 쓴다. `created_by` 는 누가
  등록했는지 남기는 칸일 뿐 찾는 범위를 가르지 않는다.
- `alias_key` 는 `aot.tools.name_key.name_key(alias)` — 띄어쓰기·전각·대소문자만 다른
  표기를 한 값으로 모은다. 대상 해석(`aot.tools.domain.targets`)은 이 열쇠로 맞춘다.
- 대상은 종류와 id 로 가리킨다(`target_kind`·`target_id`). 대상이 지워지면 별칭은 남지만
  해석에서 건너뛴다 — 지울 때 알리는 것은 목록(`find.aliases`)의 몫이다.

@phase active
@stability experimental
"""
import time

from aot.aot_flask.extensions import db
from aot.databases import CRUDMixin


class TargetAlias(CRUDMixin, db.Model):
    __tablename__ = 'target_alias'
    __table_args__ = (db.Index('ix_target_alias_key', 'alias_key'),
                      db.Index('ix_target_alias_target', 'target_kind', 'target_id'),
                      {'extend_existing': True})

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    alias = db.Column(db.String(80), nullable=False)               # 사용자가 말한 표기 그대로
    alias_key = db.Column(db.String(80), nullable=False)           # name_key(alias)
    target_kind = db.Column(db.String(16), nullable=False)         # targets 의 kind
    target_id = db.Column(db.String(80), nullable=False)
    created_by = db.Column(db.String(64), nullable=True)           # 등록한 사용자 uuid
    created_at = db.Column(db.Float, nullable=False, default=time.time)
