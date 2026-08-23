# coding=utf-8
"""그룹 스코프 판정의 **정본**.

정본 설계: `docs/design/access-scope-groups.md` (원칙 3)

이 모듈 하나만 "이 사람이 이것을 조작할 수 있는가" 를 답한다. B 단계에서
"볼 수 있는가" 가 추가될 때도 **여기에 메서드가 하나 느는 것**이지 두 번째
판정자가 생기는 것이 아니다.

이 저장소가 가장 크게 데인 실패 모양이 "읽는 경로마다 기준이 다름" 이다
(GeoShape 의 `type` vs `aot_type`). 접근 제어에서 같은 일이 나면 증상은
"가끔 남의 것이 조작된다" 이고, 그건 보안 사고다.

## A0 단계 — 아무도 아직 이것을 부르지 않는다

모델과 이 모듈이 먼저 서고, 강제는 A1a 에서 켠다. 그래서 지금 이 파일이
있다는 사실만으로 동작이 바뀌면 안 된다(`test_scope_a0_inert.py` 가 고정한다).

## 세 가지 함정

1. **`operable_resource_uuids()` 는 "제한 없음" 을 `None` 으로 돌려준다.**
   빈 집합으로 돌려주면 호출자가 그것으로 필터링해 **전부 감춘다.** 없음과
   전부는 정반대인데 파이썬에서는 둘 다 falsy 다.
2. **캐시는 요청 단위(`flask.g`)까지만.** 세션이나 프로세스에 담으면 권한을
   회수해도 그 사람은 세션이 끝날 때까지 계속 쓴다.
3. **요청 컨텍스트 밖은 시스템 호출로 본다**(데몬·스크립트 — 설계 §6-1).
   요청 **안**에서 사용자가 없으면 그것은 시스템이 아니라 미인증이므로
   거부한다. 이 둘을 뭉치면 로그인 안 한 요청이 데몬 권한을 얻는다.
"""
import logging

logger = logging.getLogger(__name__)

#: 장치 종류 → 모델. 장치의 스코프 정본은 **그 장치의 탭 하나**다(설계 §4-3).
#: 대시보드 위젯·지도 마커·시설 fitting 은 장치를 참조할 뿐이고, 참조하는
#: 컨테이너가 늘어난다고 조작 권한이 넓어지지 않는다 — 합집합으로 판정하면
#: 감춘 장치의 위젯을 공개 대시보드에 얹는 것만으로 스코프가 샌다.
_DEVICE_MODEL_NAMES = ('Input', 'Output', 'Function', 'Conditional',
                       'Trigger', 'PID', 'CustomController')


def _models():
    """모델을 늦게 import 한다 — 이 모듈이 모델 패키지 import 사슬에 끼면
    순환이 생긴다(`extensions` → 모델 → 라우트 → 여기)."""
    from aot.databases.models import (Conditional, CustomController, Function,
                                      GroupGrant, Input, Output, PID, Role,
                                      Trigger, User, UserGroupMember)
    return {
        'GroupGrant': GroupGrant,
        'UserGroupMember': UserGroupMember,
        'Role': Role,
        'User': User,
        'devices': (Input, Output, Function, Conditional, Trigger, PID,
                    CustomController),
    }


# ---------------------------------------------------------------- 요청 캐시

def _cache():
    """요청 단위 캐시. 요청 컨텍스트가 없으면 매번 새 dict — 즉 캐시 없음.

    프로세스 캐시로 올리고 싶어지는 자리인데, 올리면 그룹 변경이 즉시 반영되지
    않는다. 권한 **회수**가 늦게 반영되는 것은 접근 제어에서 버그가 아니라
    사고다.
    """
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return {}
        if not hasattr(g, '_aot_scope_cache'):
            g._aot_scope_cache = {}
        return g._aot_scope_cache
    except Exception:
        return {}


# ---------------------------------------------------------------- 신원 해석

class _System(object):
    """요청 컨텍스트 밖의 호출자(데몬·스크립트·백그라운드 잡).

    설계 §6-1 — 제어 논리는 스코프를 모른다. 감춘 센서가 공유 난방기를 켜는
    함수의 입력일 수 있고 그 함수는 남의 장치를 움직인다. 그룹 스코프는
    "보기와 조작" 의 경계이지 "제어 논리" 의 경계가 아니다.
    """
    __slots__ = ()


SYSTEM = _System()


def _resolve_user(user):
    """판정 대상 사용자. `SYSTEM` 이면 면제, `None` 이면 거부.

    **요청 밖 = 시스템, 요청 안에서 미인증 = 거부.** 이 둘을 뭉치면 로그인하지
    않은 요청이 데몬 권한을 얻는다.
    """
    if user is not None:
        return user
    try:
        from flask import has_request_context
        if not has_request_context():
            return SYSTEM
    except Exception:
        return SYSTEM

    try:
        import flask_login
        current = flask_login.current_user
        if not current or not current.is_authenticated:
            return None
        models = _models()
        return models['User'].query.filter(
            models['User'].name == current.name).first()
    except Exception as exc:                     # pragma: no cover - 방어
        logger.warning("[scope] 사용자 해석 실패: %s", exc)
        return None


# ---------------------------------------------------------------- 전역 판정

def scoping_active():
    """이 설치가 그룹 스코프를 **쓰고 있는가**. grant 가 0건이면 False.

    대부분의 설치는 그룹이 없다(단일 팀). 원칙 2(미지정 = 전원 공개)가 이
    최적화를 가능하게 한다 — grant 테이블이 비어 있으면 아무 자원도 제한되지
    않으므로 **판정 자체를 건너뛸 수 있다.** 그러지 않으면 그룹을 쓰지 않는
    사람들이 비용만 낸다(설계 §8-6).
    """
    cache = _cache()
    if 'active' in cache:
        return cache['active']
    try:
        active = _models()['GroupGrant'].query.first() is not None
    except Exception as exc:
        # 테이블이 아직 없는 설치(마이그레이션 전)에서 판정이 앱을 막으면 안
        # 된다. 없으면 스코프를 쓰지 않는 것과 같다.
        logger.debug("[scope] grant 조회 실패, 스코프 비활성으로 본다: %s", exc)
        active = False
    cache['active'] = active
    return active


def is_exempt(user=None):
    """이 사람이 그룹 스코프 면제인가 (`roles.bypass_group_scope`).

    `role_id == 1` 로 판정하지 않는다 — 역할 id 라는 우연한 값에 보안 경계를
    걸면 "관리자와 동급인 두 번째 역할" 을 만들 수 없다.

    ⚠ **서비스 계정(`auth_provider='system'`)을 여기서 면제하지 말 것.**
    `grant_impact` 는 그 계정을 세지 않는데(사람이 아니라 "잃는 사람" 이 될 수
    없다) 여기서도 그럴 것 같지만, 근거가 다르다 — **외부 MCP 클라이언트가 그
    계정의 키로 붙는다.** 면제하면 외부에서 붙은 클라이언트가 스코프를 통째로
    벗어난다.

    내부 AI 의 호출이 면제되는 것은 계정 때문이 아니라 **요청 컨텍스트가 없기
    때문**이다(`SYSTEM`). A2 에서 이 경로를 배선할 때 서비스 계정 행을
    `user=` 로 넘기면 안 된다 — 넘기는 순간 판정 근거가 계정으로 바뀌고,
    그러면 내부 AI 는 아무것도 못 하게 되거나(지금 상태) 여기를 면제로 고쳐
    외부까지 함께 열게 된다. 둘 다 틀렸다.
    """
    subject = _resolve_user(user)
    if subject is SYSTEM:
        return True
    if subject is None:
        return False
    cache = _cache()
    key = ('exempt', getattr(subject, 'id', None))
    if key in cache:
        return cache[key]
    models = _models()
    role = models['Role'].query.filter(
        models['Role'].id == subject.role_id).first()
    result = bool(role is not None and getattr(role, 'bypass_group_scope', False))
    cache[key] = result
    return result


def groups_for_user(user=None):
    """이 사람이 속한 그룹 uuid 집합 (frozenset).

    다중 소속은 **합집합**이다 — 그룹을 하나 더 받을수록 권한이 넓어진다.
    교집합은 직관에 정면으로 반해서 아무도 못 쓴다(설계 §3-2).
    """
    subject = _resolve_user(user)
    if subject is SYSTEM or subject is None:
        return frozenset()
    cache = _cache()
    key = ('groups', getattr(subject, 'id', None))
    if key in cache:
        return cache[key]
    models = _models()
    rows = models['UserGroupMember'].query.filter(
        models['UserGroupMember'].user_uuid == subject.unique_id).all()
    result = frozenset(r.group_uuid for r in rows)
    cache[key] = result
    return result


# ---------------------------------------------------------------- 자원 판정

def _grants_for(resource_type, resource_uuid):
    """그 자원에 붙은 (group_uuid, level) 목록. 캐시된다."""
    cache = _cache()
    key = ('grants', resource_type, resource_uuid)
    if key in cache:
        return cache[key]
    GroupGrant = _models()['GroupGrant']
    rows = GroupGrant.query.filter(
        GroupGrant.resource_type == resource_type,
        GroupGrant.resource_uuid == resource_uuid).all()
    result = [(r.group_uuid, r.level) for r in rows]
    cache[key] = result
    return result


def can_operate(resource_type, resource_uuid, user=None):
    """이 사람이 이 자원을 **조작**할 수 있는가.

    역할(동사)은 보지 않는다 — 이것은 목적어 축이고, 호출자가 이미 자기
    역할 검사를 통과한 뒤에 부른다. 실효 권한은 둘의 곱이다.

    grant 가 없는 자원은 **누구나** 조작한다(원칙 2, default-open).
    """
    if not resource_uuid:
        # 대상을 모르면 스코프가 판정할 것이 없다. 여기서 False 를 돌려주면
        # 대상이 없는 정상 작업(전역 설정 등)까지 막힌다 — 그런 작업은 애초에
        # 이 함수를 부르지 않아야 한다.
        return True
    if not scoping_active():
        return True
    if is_exempt(user):
        return True

    grants = _grants_for(resource_type, resource_uuid)
    if not grants:
        return True                      # 미지정 = 전원 공개

    from aot.databases.models.user_group import LEVEL_OPERATE
    mine = groups_for_user(user)
    return any(g in mine and level == LEVEL_OPERATE for g, level in grants)


def denied_resource_uuids(resource_type, user=None):
    """조작이 **거부되는** 자원 uuid 집합. 제한이 없으면 빈 집합.

    ⚠ **허용 목록이 아니라 거부 목록을 돌려주는 것이 의도다.**

    허용 목록은 default-open 과 모양이 맞지 않는다. grant 가 붙지 않은 자원은
    여전히 전원 공개이므로 허용 목록에는 그것들까지 전부 들어가야 하고, 그러면
    "제한 없음" 을 빈 집합으로 표현할 수 없어 `None` 같은 특별값이 필요해진다 —
    그리고 파이썬에서 `None` 과 `set()` 은 **둘 다 falsy** 라, 호출자가
    `if not allowed:` 로 뭉뚱그리는 순간 "제한 없음" 이 "전부 금지" 로 조용히
    뒤집힌다.

    거부 목록에는 그 뒤집힘이 없다. 빈 집합 = 아무것도 안 막는다 = default-open
    이고, 새로 생긴 자원은 목록에 없으므로 자동으로 열린다.
    """
    if not scoping_active() or is_exempt(user):
        return frozenset()

    from aot.databases.models.user_group import LEVEL_OPERATE
    GroupGrant = _models()['GroupGrant']
    mine = groups_for_user(user)

    restricted = {}
    for row in GroupGrant.query.filter(
            GroupGrant.resource_type == resource_type).all():
        restricted.setdefault(row.resource_uuid, []).append(
            (row.group_uuid, row.level))

    return frozenset(
        uid for uid, grants in restricted.items()
        if not any(g in mine and lv == LEVEL_OPERATE for g, lv in grants))


# ---------------------------------------------------------------- 장치 판정

def tab_of_device(device_uuid):
    """장치가 속한 탭 uuid. 없으면 None.

    **탭 없는 장치는 정상이다**(`tab_id` 는 nullable). 원칙 2 를 따라 탭 없음 =
    미지정 = 전원 공개로 본다. 그것이 스코프의 구멍이므로
    `check_scope_grants.py` 의 `unscoped-device` 가 건수를 계속 보인다.
    """
    if not device_uuid:
        return None
    cache = _cache()
    key = ('tab_of', device_uuid)
    if key in cache:
        return cache[key]
    result = None
    for model in _models()['devices']:
        row = model.query.filter(model.unique_id == device_uuid).first()
        if row is not None:
            result = row.tab_id
            break
    cache[key] = result
    return result


def can_operate_device(device_uuid, user=None):
    """이 사람이 이 장치를 조작할 수 있는가. 판정 근거는 **그 장치의 탭**이다."""
    if not scoping_active():
        return True
    if is_exempt(user):
        return True
    from aot.databases.models.user_group import RESOURCE_TAB
    tab_uuid = tab_of_device(device_uuid)
    if not tab_uuid:
        return True                      # 탭 없음 = 미지정 = 전원 공개
    return can_operate(RESOURCE_TAB, tab_uuid, user=user)


def can_operate_widget(widget_uuid, user=None):
    """위젯 실행 판정. 근거는 **그 위젯이 놓인 대시보드**다.

    위젯은 장치가 아니라 화면 요소라 탭(장치 탭)으로 판정할 수 없다. 그리고
    `Widget.tab_id` 는 FK 선언이 `tab.unique_id` 를 가리키지만 실제로 담기는
    값은 **dashboard 의 uuid** 다 — FK 강제가 꺼져 있어 이 어긋남은 에러를
    내지 않는다(CLAUDE.md 에 적힌 그 함정).
    """
    if not scoping_active():
        return True
    if is_exempt(user):
        return True
    from aot.databases.models import Widget
    from aot.databases.models.user_group import RESOURCE_DASHBOARD
    row = Widget.query.filter(Widget.unique_id == widget_uuid).first()
    if row is None or not row.tab_id:
        return True                      # 미지정 = 전원 공개
    return can_operate(RESOURCE_DASHBOARD, row.tab_id, user=user)


#: 모델 이름 → 그 행의 스코프를 무엇으로 판정하는가 (A1b).
#:
#: 여기 **없는 모델은 스코프 대상이 아니다**(True). 채널·조건·액션 같은 자식
#: 행들이 그렇다 — 부모를 지울 권한이 있으면 자식도 함께 지워지고, 자식마다
#: 따로 물으면 같은 질문을 두 번 하는 것이 된다.
_SCOPED_BY_OWN_TAB = ('Input', 'Output', 'Function', 'Conditional',
                      'Trigger', 'PID', 'CustomController')
_SCOPED_BY_SELF = {
    'Tab': 'tab',
    'Dashboard': 'dashboard',
    'GeoMap': 'geo_map',
    'GeoFacility': 'geo_facility',
}


def can_operate_record(table, record_uuid, user=None):
    """모델 클래스(또는 이름)와 uuid 로 판정한다 — 엔티티 CRUD 용 (A1b).

    삭제는 `delete_entry_with_id()` 라는 한 곳을 지나므로 여기서 한 번 물으면
    모든 삭제 경로가 같은 경계를 지난다. **호출자마다 규칙을 두면 갈라지고,
    갈라지면 느슨한 쪽이 실질 권한이 된다.**

    ⚠ **`Tab` 은 자기 자신이 부여 단위다.** 탭을 지우거나 이름을 바꾸는 것은
    그 탭에 걸린 부여의 대상을 바꾸는 일이라, 안에 든 장치를 조작할 수 있는
    사람만 할 수 있어야 한다. 여기를 빼면 스코프 밖 사람이 **탭을 지워서**
    안의 장치를 미지정(=전원 공개)으로 만들 수 있다.
    """
    if not scoping_active():
        return True
    if is_exempt(user):
        return True
    if not record_uuid:
        return True

    name = table if isinstance(table, str) else getattr(table, '__name__', '')
    if name in _SCOPED_BY_OWN_TAB:
        return can_operate_device(record_uuid, user=user)
    if name == 'Widget':
        return can_operate_widget(record_uuid, user=user)
    resource_type = _SCOPED_BY_SELF.get(name)
    if resource_type:
        return can_operate(resource_type, record_uuid, user=user)
    return True                          # 스코프 대상이 아닌 모델


_UUID_RE = None


def _looks_like_uuid(value):
    global _UUID_RE
    if not isinstance(value, str) or len(value) != 36:
        return False
    if _UUID_RE is None:
        import re
        _UUID_RE = re.compile(
            r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
            r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    return bool(_UUID_RE.match(value))


def _uuid_values(payload, depth=0):
    """인자 안에 있는 uuid 모양 문자열 전부 (중첩 포함)."""
    if depth > 6:                        # 순환·과도한 중첩 방어
        return
    if isinstance(payload, str):
        if _looks_like_uuid(payload):
            yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            for found in _uuid_values(value, depth + 1):
                yield found
    elif isinstance(payload, (list, tuple, set)):
        for value in payload:
            for found in _uuid_values(value, depth + 1):
                yield found


def _resource_of_uuid(record_uuid):
    """이 uuid 가 어떤 스코프 대상인가. 아니면 None.

    ⚠ **인자 이름이 아니라 값으로 찾는다.** 도구 59개의 인자 이름은 제각각이고
    (`device_id`·`unique_id`·`output_id`·`function_id`…), 대부분은 기계 판독
    가능한 스키마조차 없다(매니페스트가 산문이다). 이름 목록으로 찾으면 **새
    도구가 다른 이름을 쓰는 순간 조용히 새고**, 그 사실은 남의 장치가 움직인
    뒤에야 드러난다. 값으로 찾으면 새 도구도 자동으로 덮인다.
    """
    cache = _cache()
    key = ('res_of', record_uuid)
    if key in cache:
        return cache[key]

    from aot.databases.models import (Dashboard, GeoFacility, GeoMap, Tab,
                                      Widget)
    result = None
    if tab_of_device(record_uuid) is not None:
        result = ('device', record_uuid)
    else:
        for model, kind in ((Widget, 'widget'), (Tab, 'tab'),
                            (Dashboard, 'dashboard'), (GeoMap, 'geo_map'),
                            (GeoFacility, 'geo_facility')):
            if model.query.filter(model.unique_id == record_uuid).first():
                result = (kind, record_uuid)
                break
    cache[key] = result
    return result


def can_operate_tool_call(tool_name, arguments, user=None, write_tools=None):
    """AI·MCP 도구 호출 하나를 판정한다 (A2).

    정본 설계: `docs/design/access-scope-groups.md` §6-2

    **읽기 도구는 보지 않는다** — A 범위에서 보기는 전원 공개다(§1-A).
    쓰기 도구만 대상이고, 인자 안의 uuid 를 전부 훑어 그중 스코프 대상이
    하나라도 거부되면 거부한다.

    `user` 가 `None` 이고 요청 컨텍스트도 없으면 **사람이 없는 호출**이라
    면제다(§6-1·§6-2 — 백그라운드 AI 잡·주기 요약). 그 면제는 A1 이 막은 것을
    여는 구멍이므로 설계 문서와 매뉴얼에 적혀 있다.

    ⚠ **서비스 계정을 `user=` 로 넘기지 말 것.** 내부 AI 의 면제 근거는 계정이
    아니라 **사람이 없다는 것**이다(`is_exempt` 주석 참조). 넘기면 판정 근거가
    계정으로 바뀌어, 내부 AI 가 아무것도 못 하게 되거나 그것을 고치려다 외부
    클라이언트까지 함께 열게 된다.
    """
    if not scoping_active():
        return True, None
    if write_tools is None:
        try:
            from aot.ai.services.mcp_safety_gate import write_tools as _wt
            write_tools = _wt()
        except Exception:
            return True, None
    if tool_name not in write_tools:
        return True, None
    if is_exempt(user):
        return True, None

    from aot.databases.models.user_group import (RESOURCE_DASHBOARD,
                                                 RESOURCE_GEO_FACILITY,
                                                 RESOURCE_GEO_MAP,
                                                 RESOURCE_TAB)
    by_kind = {'tab': RESOURCE_TAB, 'dashboard': RESOURCE_DASHBOARD,
               'geo_map': RESOURCE_GEO_MAP, 'geo_facility': RESOURCE_GEO_FACILITY}

    for value in dict.fromkeys(_uuid_values(arguments)):
        found = _resource_of_uuid(value)
        if found is None:
            continue                     # 스코프 대상이 아닌 uuid
        kind, record_uuid = found
        if kind == 'device':
            allowed = can_operate_device(record_uuid, user=user)
        elif kind == 'widget':
            allowed = can_operate_widget(record_uuid, user=user)
        else:
            allowed = can_operate(by_kind[kind], record_uuid, user=user)
        if not allowed:
            return False, record_uuid
    return True, None


#: 거부 문구. **모든 거부가 같은 말을 해야 한다** — 자리마다 다르게 쓰면
#: 사용자는 "권한이 없다" 와 "고장났다" 를 구분하지 못하고, 지원 요청이
#: 들어와도 어느 게이트가 막았는지 알 수 없다.
def deny_message():
    try:
        from flask_babel import gettext
        return gettext(
            "This resource is assigned to another group. "
            "Ask an administrator for access.")
    except Exception:                    # pragma: no cover - 번역 없는 환경
        return "This resource is assigned to another group."


# ---------------------------------------------------- 부여 영향 미리보기

def grant_impact(resource_type, resource_uuid, group_uuids,
                 pending_members=None):
    """이 자원을 `group_uuids` 에만 부여하면 **누가 조작을 잃는가**.

    default-open 이 업그레이드를 무해하게 만드는 것은 grant 가 0건인 동안뿐이다.
    관리자가 탭 하나에 그룹을 처음 붙이는 순간 그 탭을 조작하던 사람들이
    **조용히** 잃는다 — 부여 화면이 그 사실을 미리 말해야 한다(원칙 2).

    §8-5 의 감사 로그가 사후 추적이라면 이것은 사전 고지다.

    Args:
        pending_members: {group_uuid: [user_uuid, ...]} — **아직 저장되지 않은**
            멤버 구성. 화면에서 멤버와 부여는 같은 폼으로 함께 저장되므로,
            저장된 멤버만 보면 방금 추가한 사람이 계속 "잃는 사람" 으로 나온다.
            그러면 미리보기가 늘 실제보다 많이 세고, 관리자는 곧 그것을 무시하게
            된다 — 무시되는 경고는 없는 것과 같다.

    Returns:
        dict: before/after/losing 인원과 잃는 사람 이름 목록.
    """
    models = _models()
    User = models['User']
    Role = models['Role']
    Member = models['UserGroupMember']

    roles = {r.id: r for r in Role.query.all()}

    def _can_control(role):
        # 애초에 조작할 수 없던 사람은 "잃는" 것이 없다. 역할 축을 무시하고
        # 세면 Monitor 까지 포함돼 숫자가 실제보다 커지고, 그 숫자를 보고
        # 부여를 망설이게 된다.
        if role is None:
            return False
        return bool(role.edit_controllers or role.edit_settings)

    # 서비스 계정은 사람이 아니다. 세면 "누가 잃는가" 에 로그인할 수도 없는
    # 이름이 섞여, 그 목록을 보고 부여를 망설이게 된다. 그리고 내부 AI 의
    # 호출은 어차피 **사람이 없는 호출**이라 면제다(설계 §6-2).
    #
    # 이름이 아니라 `auth_provider` 로 가른다 — 사람이 같은 이름을 먼저
    # 차지했을 수 있고, 그 판별 기준은 `mcp_auth.ensure_service_account()` 와
    # 같아야 한다.
    candidates = [u for u in User.query.filter(User.is_enabled.is_(True)).all()
                  if getattr(u, 'auth_provider', None) != 'system'
                  and _can_control(roles.get(u.role_id))]

    exempt = {u.unique_id for u in candidates
              if getattr(roles.get(u.role_id), 'bypass_group_scope', False)}

    # 지금 조작 가능한 사람
    current_grants = _grants_for(resource_type, resource_uuid)
    if not current_grants:
        before = {u.unique_id for u in candidates}
    else:
        from aot.databases.models.user_group import LEVEL_OPERATE
        granted_groups = {g for g, lv in current_grants if lv == LEVEL_OPERATE}
        members = {m.user_uuid for m in Member.query.filter(
            Member.group_uuid.in_(granted_groups)).all()} if granted_groups else set()
        before = (members & {u.unique_id for u in candidates}) | exempt

    # 부여 후
    target = set(group_uuids or ())
    if not target:
        after = {u.unique_id for u in candidates}       # 부여를 비우면 전원 공개로 돌아간다
    else:
        overrides = pending_members or {}
        stored = {g for g in target if g not in overrides}
        members = set()
        if stored:
            members |= {m.user_uuid for m in Member.query.filter(
                Member.group_uuid.in_(stored)).all()}
        for group_uuid in target:
            if group_uuid in overrides:
                members |= set(overrides[group_uuid] or ())
        after = (members & {u.unique_id for u in candidates}) | exempt

    losing = before - after
    by_uuid = {u.unique_id: u for u in candidates}
    return {
        'before': len(before),
        'after': len(after),
        'losing': len(losing),
        'losing_names': sorted(
            (by_uuid[x].full_name or by_uuid[x].name) for x in losing
            if x in by_uuid),
        # 부여를 켜는 순간 아무도 조작할 수 없게 되는 경우. 관리자가 자기
        # 자신까지 잠그는 실수는 화면이 막아야 한다.
        'locks_out_everyone': len(after) == 0,
    }
