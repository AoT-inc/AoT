# coding=utf-8
"""사용자 그룹과 자원 부여 — 권한의 **목적어** 축.

정본 설계: `docs/design/access-scope-groups.md`

`Role` 의 불리언 9개는 전부 **동사**다("무엇을 할 수 있는가"). 그래서 Editor 를
받은 사람은 농장 **전체**의 출력을 켤 수 있었고, 임차 구획·작업반·고객사를 한
시스템에 담으려면 시스템 자체를 분리하는 수밖에 없었다.

이 세 테이블이 **목적어**("무엇에 대해")를 담는다. 실효 권한은 곱이다:

    실효 권한 = 역할(동사) ∧ 그룹(목적어) ∧ 키 스코프(자격증명 상한)

역할에 그룹을 합치지 않는다 — "A그룹 관리자 역할" 을 만들면 역할 5개 × 그룹 N개가
역할 5N개가 되고, 그게 지금 모두에게 Editor 를 주고 있는 이유와 같은 원인이다.

## 지금 강제되는 것은 조작뿐이다 (A 단계)

`level` 어휘는 `view`/`operate` 둘이지만 **A 단계에서 강제되는 것은 `operate`
뿐이고 `view` 는 UI 에 노출하지 않는다.** 강제되지 않는 값을 고르게 하면
"설정했는데 안 먹는다" 가 되는데, 그 침묵은 접근 제어에서 가장 나쁜 종류다
(권한이 있다고 믿는 상태). `view` 는 정보 격리(B 단계)에서 연다.

원문 요구는 읽기를 포함한 "접근" 이었다. A 는 요구를 쪼갠 것이지 다시 읽은 것이
아니다 — 자세한 것은 설계 문서 §1-A.

## 미지정 = 전원 공개 (default-open)

grant 가 **하나도 없는** 자원은 지금과 똑같이 누구나 조작한다. default-deny 로
만들면 마이그레이션 직후 모든 사용자가 모든 조작을 잃는다(`user_api_key.scope`
기본값이 `full` 인 것과 같은 판단).

⚠ **무해함은 첫 grant 까지다.** 관리자가 탭 하나에 그룹을 처음 붙이는 순간 그
탭을 조작하던 사람들이 조용히 잃는다 — 부여 화면이 그 사실을 미리 말해야 한다
(`scope.grant_impact()`).
"""
from datetime import datetime

from aot.aot_flask.extensions import db
from aot.databases import CRUDMixin
from aot.databases import set_uuid

#: 부여 대상 종류.
#:
#: **`tab` 하나로 단순화하면 안 된다.** 대시보드 행은 `tab` 이 아니라 `dashboard`
#: 테이블에 있고(`Widget.tab_id` 의 FK 선언이 `tab.unique_id` 를 가리키지만 실제
#: 값은 dashboard 의 uuid 다 — FK 강제가 꺼져 있어 이 어긋남은 에러를 내지
#: 않는다), 지도·시설도 탭이 아니다. 그래서 다형 키 `(종류, uuid)` 다.
#:
#: 나중에 `'site'` 나 `'geo_shape'`(구역)를 넣는 데 스키마 변경이 필요 없다 —
#: 지도 단위로 시작하는 결정이 되돌릴 수 없는 결정이 아닌 근거가 이것이다.
RESOURCE_TAB = 'tab'
RESOURCE_DASHBOARD = 'dashboard'
RESOURCE_GEO_MAP = 'geo_map'
RESOURCE_GEO_FACILITY = 'geo_facility'
RESOURCE_TYPES = (RESOURCE_TAB, RESOURCE_DASHBOARD,
                  RESOURCE_GEO_MAP, RESOURCE_GEO_FACILITY)

#: 부여 수준. `operate` 가 `view` 를 함의한다(넓은 쪽이 좁은 쪽을 포함).
LEVEL_VIEW = 'view'
LEVEL_OPERATE = 'operate'
LEVELS = (LEVEL_VIEW, LEVEL_OPERATE)

#: 넓은 쪽이 이긴다 — 한 사람이 여러 그룹에 들고 같은 자원에 level 이 갈릴 때
#: 쓰는 순서. 합집합 규칙(`UserGroupMember` 참조)의 일부다.
_LEVEL_RANK = {LEVEL_VIEW: 1, LEVEL_OPERATE: 2}


def wider_level(a, b):
    """두 level 중 넓은 쪽. 모르는 값은 좁은 쪽으로 취급한다.

    모르는 값을 넓은 쪽으로 취급하면 **오타 하나가 조용히 권한을 넓힌다**
    (`user_api_key.scope` 가 모르는 값을 `readonly` 로 좁히는 것과 같은 판단).
    """
    if _LEVEL_RANK.get(a, 0) >= _LEVEL_RANK.get(b, 0):
        return a if a in _LEVEL_RANK else LEVEL_VIEW
    return b if b in _LEVEL_RANK else LEVEL_VIEW


class UserGroup(CRUDMixin, db.Model):
    """이름 있는 사용자 묶음.

    @phase active
    @stability experimental
    """
    __tablename__ = "user_group"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # 사람이 부르는 이름("1동 작업반", "OO농산"). 유일해야 한다 — 같은 이름이
    # 둘이면 권한을 부여할 때 어느 쪽인지 화면으로 구분할 수 없다.
    name = db.Column(db.String(64), nullable=False, unique=True)

    # 이 그룹이 무엇인지. 나중에 "이 그룹은 왜 있는가" 를 묻게 되는데, 그 답이
    # 없으면 지워도 되는지 판단할 수 없어 아무도 못 지운다.
    description = db.Column(db.Text, default=None)

    # 설정 화면 카드 순서 (users.position_y·roles.position_y 와 같은 방식).
    position_y = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return "<UserGroup(id={s.id}, name='{s.name}')>".format(s=self)


class UserGroupMember(CRUDMixin, db.Model):
    """사용자 ↔ 그룹 (N:M).

    ## 합집합. 가장 넓은 권한이 이긴다

        실효 대상 = ⋃(내가 속한 모든 그룹의 grant)
        같은 자원에 level 이 갈리면 → 넓은 쪽(operate > view)

    교집합은 직관에 정면으로 반한다 — 그룹을 하나 더 받을수록 권한이 **줄어든다.**
    사람을 그룹에 넣는 동기가 "이 영역도 맡긴다" 인데 결과가 반대면 아무도 못 쓴다.

    **그래서 "제외 그룹"(deny 규칙)을 만들지 말 것.** 합집합에 deny 를 섞으면
    순서에 따라 결과가 달라지고, "왜 이 사람이 이걸 못 하는가" 에 답하려면 모든
    소속을 다 훑어야 한다. 접근을 좁히는 수단은 **그룹에서 빼는 것** 하나다.

    ## 역할은 아직 사용자에 둔다

    "김제에서는 관리자, 나주에서는 모니터" 는 지금 표현되지 않는다. 그 요구가
    실제로 나오면 이 테이블에 `role_id` 를 추가한다(NULL = 사용자 기본 역할) —
    **스키마 재설계가 아니라 컬럼 하나**다. 미리 만들지 않는 이유는 쓰는 사람이
    없는 축이 관리 UI 를 복잡하게 만들고, 그 복잡함이 권한 체계가 안 쓰이게
    되는 가장 흔한 원인이기 때문이다.

    @phase active
    @stability experimental
    @dependency UserGroup, User
    """
    __tablename__ = "user_group_member"
    __table_args__ = (
        db.UniqueConstraint('group_uuid', 'user_uuid',
                            name='uq_user_group_member'),
        {'extend_existing': True}
    )

    id = db.Column(db.Integer, primary_key=True)
    group_uuid = db.Column(db.String(36), nullable=False, index=True)
    user_uuid = db.Column(db.String(36), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return "<UserGroupMember(group={s.group_uuid}, user={s.user_uuid})>".format(s=self)


class GroupGrant(CRUDMixin, db.Model):
    """그룹 → 자원 부여 (다형).

    ## 고아 grant 는 조용히 위험하다

    지도·시설·대시보드·탭이 삭제되면 이 행은 죽은 uuid 를 가리킨 채 남는다.
    접근 제어에서는 한 겹 더 고약하다 — **삭제된 자원의 uuid 가 재사용되면
    아무도 부여한 적 없는 권한이 생긴다.**

    행을 삭제 시점에 함께 지우는 것(FK CASCADE)으로 풀지 않는다. 대상이 네 테이블
    이라 FK 를 걸 수 없고, 이 저장소는 FK 강제가 꺼져 있다. 대신
    `aot/scripts/check_scope_grants.py` 의 `orphan-grant` 가 배포 전후로 본다.

    @phase active
    @stability experimental
    @dependency UserGroup
    """
    __tablename__ = "group_grant"
    __table_args__ = (
        db.UniqueConstraint('group_uuid', 'resource_type', 'resource_uuid',
                            name='uq_group_grant'),
        {'extend_existing': True}
    )

    id = db.Column(db.Integer, primary_key=True)
    group_uuid = db.Column(db.String(36), nullable=False, index=True)

    # RESOURCE_TYPES 중 하나. 문자열인 이유는 위 상수 주석 참조 — 종류를 늘리는
    # 데 스키마 변경이 필요 없어야 한다.
    resource_type = db.Column(db.String(32), nullable=False, index=True)
    resource_uuid = db.Column(db.String(36), nullable=False, index=True)

    # 'view' | 'operate'. A 단계에서 강제되는 것은 operate 뿐이다(모듈 docstring).
    level = db.Column(db.String(16), nullable=False, default=LEVEL_OPERATE,
                      server_default=LEVEL_OPERATE)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return ("<GroupGrant(group={s.group_uuid}, {s.resource_type}="
                "{s.resource_uuid}, {s.level})>".format(s=self))
