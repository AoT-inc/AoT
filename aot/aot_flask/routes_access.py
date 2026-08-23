# coding=utf-8
"""그룹 부여를 **자원 쪽에서** 편집하는 엔드포인트.

정본 설계: `docs/design/access-scope-groups.md`

부여를 그룹 화면이 아니라 각 자원의 설정 창에서 하는 이유는 축이다 — **그룹은
적고(N) 자원은 많다(M).** 그룹 쪽에서 자원을 고르게 하면 목록이 자원 수만큼
길어져(실측 56줄) 자원이 늘수록 못 쓰게 된다. 자원에서 그룹을 고르면 목록은
항상 그룹 수만큼이고, 무엇에 영향을 주는지가 눈앞에 있다.

자원 종류마다 라우트를 만들지 않는다 — 대시보드를 붙일 때 탭 엔드포인트를
복사했다면 지도·시설에서 또 복사하게 되고, 그때 네 벌이 조용히 갈린다.
"""
import logging

import flask_login
from flask import Blueprint, jsonify, request

from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_general

logger = logging.getLogger('aot.aot_flask.routes_access')

blueprint = Blueprint('routes_access',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


def _resource_name(resource_type, resource_uuid):
    """그 자원이 실재하는가 — 실재하면 이름, 아니면 None.

    없는 자원에 부여하면 **아무도 부여한 적 없는 권한**이 생길 수 있다
    (uuid 재사용). `check_scope_grants.py` 의 `orphan-grant` 가 사후에 보지만,
    만들지 않는 편이 낫다.
    """
    from aot.databases.models import Dashboard, GeoFacility, GeoMap, Tab
    models = {'tab': Tab, 'dashboard': Dashboard,
              'geo_map': GeoMap, 'geo_facility': GeoFacility}
    model = models.get(resource_type)
    if model is None:
        return None
    row = model.query.filter(model.unique_id == resource_uuid).first()
    return (getattr(row, 'name', None) or resource_uuid) if row else None


def _admin_only():
    """부여는 **사용자 관리 권한**이다.

    자원을 고칠 수 있다고 해서 남의 접근 권한까지 정할 수 있으면 안 된다 —
    탭 이름을 바꾸는 사람과 누가 그 탭을 조작할지 정하는 사람은 다르다.
    """
    return utils_general.user_has_permission('edit_users', silent=True)


@blueprint.route('/api/scope/grants/<string:resource_type>/<string:resource_uuid>',
                 methods=['GET'])
@flask_login.login_required
def get_grants(resource_type, resource_uuid):
    """이 자원을 조작할 그룹 — 자원의 설정 창이 읽는다."""
    if not _admin_only():
        # 403 이면 화면이 섹션을 아예 그리지 않는다 — 관리자가 아닌 사람에게
        # "권한 설정" 이 보이되 막히는 것보다 낫다.
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    from aot.databases.models import GroupGrant, UserGroup
    from aot.databases.models.user_group import RESOURCE_TYPES

    if resource_type not in RESOURCE_TYPES:
        return jsonify({'success': False,
                        'message': 'Unknown resource type'}), 400
    if _resource_name(resource_type, resource_uuid) is None:
        return jsonify({'success': False, 'message': 'Not found'}), 404

    granted = {g.group_uuid for g in GroupGrant.query.filter(
        GroupGrant.resource_type == resource_type,
        GroupGrant.resource_uuid == resource_uuid).all()}
    groups = UserGroup.query.order_by(UserGroup.position_y, UserGroup.id).all()
    return jsonify({
        'success': True,
        'groups': [{'unique_id': g.unique_id, 'name': g.name,
                    'granted': g.unique_id in granted} for g in groups],
    })


def save_grants(resource_type, resource_uuid, group_uuids):
    """부여를 전량 교체한다. (실패 사유 문자열 또는 None)

    **부분 반영으로 두지 않는다.** "보낸 것만 추가" 로 만들면 체크를 푸는
    조작이 아무 일도 하지 않아, 권한을 회수했다고 믿는 상태가 만들어진다.

    ⚠ 호출자는 **"보내지 않음" 과 "전부 해제" 를 구분**해야 한다. 폼이 그
    섹션을 그리지 않았을 때(비관리자·로딩 실패) 빈 목록으로 이 함수를 부르면
    부여가 통째로 지워진다 — 그룹 저장 핸들러에서 이미 한 번 겪은 실패다.
    """
    from aot.aot_flask.extensions import db
    from aot.databases.models import GroupGrant, UserGroup
    from aot.databases.models.user_group import LEVEL_OPERATE, RESOURCE_TYPES
    from aot.utils import audit
    from aot.utils.audit import audit_log

    if resource_type not in RESOURCE_TYPES:
        return 'Unknown resource type'
    name = _resource_name(resource_type, resource_uuid)
    if name is None:
        return 'Not found'

    wanted = [g for g in (group_uuids or []) if g]
    known = {g.unique_id for g in UserGroup.query.all()}
    unknown = [g for g in wanted if g not in known]
    if unknown:
        # 모르는 그룹을 조용히 버리지 않는다 — 버리면 "부여했는데 안 먹는다"
        # 가 되고, 그 침묵이 접근 제어에서 가장 나쁘다.
        return 'Unknown group: %s' % unknown[0]

    before = sorted({g.group_uuid for g in GroupGrant.query.filter(
        GroupGrant.resource_type == resource_type,
        GroupGrant.resource_uuid == resource_uuid).all()})

    GroupGrant.query.filter(
        GroupGrant.resource_type == resource_type,
        GroupGrant.resource_uuid == resource_uuid).delete(
        synchronize_session=False)
    for group_uuid in dict.fromkeys(wanted):
        db.session.add(GroupGrant(group_uuid=group_uuid,
                                  resource_type=resource_type,
                                  resource_uuid=resource_uuid,
                                  level=LEVEL_OPERATE))
    db.session.commit()

    after = sorted(dict.fromkeys(wanted))
    if before != after:
        audit_log(audit.GROUP_GRANT_CHANGE, target_type=resource_type,
                  target_id=resource_uuid, target_name=name,
                  before={'groups': before}, after={'groups': after})
    return None


@blueprint.route('/api/scope/grants/<string:resource_type>/<string:resource_uuid>',
                 methods=['POST'])
@flask_login.login_required
def post_grants(resource_type, resource_uuid):
    if not _admin_only():
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    data = request.get_json(silent=True) or {}
    error = save_grants(resource_type, resource_uuid, data.get('groups'))
    if error:
        return jsonify({'success': False, 'message': error}), 400
    return jsonify({'success': True})


@blueprint.route('/api/scope/grant_impact/<string:resource_type>/<string:resource_uuid>',
                 methods=['POST'])
@flask_login.login_required
def grant_impact(resource_type, resource_uuid):
    """저장하면 누가 조작을 잃는가 — 저장 전에 보여준다(설계 원칙 2).

    무해함은 첫 부여까지다. 첫 부여 순간 그 자원을 조작하던 사람들이 조용히
    잃으므로 화면이 미리 말해야 한다. 읽기만 한다.
    """
    if not _admin_only():
        return jsonify({'success': False}), 403

    from aot.aot_flask.access import scope
    data = request.get_json(silent=True) or {}
    groups = [g for g in (data.get('groups') or []) if g]
    return jsonify({'success': True,
                    'impact': scope.grant_impact(resource_type, resource_uuid,
                                                 groups)})
