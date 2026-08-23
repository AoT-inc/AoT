# coding=utf-8
"""그룹 스코프(권한의 목적어 축) 회귀 테스트 — A0.

정본 설계: `docs/design/access-scope-groups.md`

여기서 고정하는 계약은 여섯이다.

1. **미지정 = 전원 공개.** grant 가 0건이면 판정 자체가 건너뛰어지고, 그 설치의
   동작은 이 기능이 없던 때와 같다. 이것이 깨지면 업그레이드가 모든 사용자의
   조작을 빼앗는다.
2. **다중 소속은 합집합.** 그룹을 하나 더 받을수록 넓어진다. 교집합이 되면
   사람을 그룹에 넣는 행위가 권한을 줄이는 것이 되어 아무도 못 쓴다.
3. **모르는 level 은 좁은 쪽으로.** 오타 하나가 조용히 권한을 넓히면 안 된다.
4. **장치의 정본은 자기 탭 하나.** 컨테이너(위젯·마커·fitting)가 늘어난다고
   조작 권한이 넓어지지 않는다 — 합집합이면 감춘 장치의 위젯을 공개 대시보드에
   얹는 것만으로 샌다.
5. **탭 없는 장치는 전원 공개.** 규칙을 안 정하면 마이그레이션 직후 조용히
   사라지거나 반대로 새어 나간다.
6. **A0 은 아무것도 강제하지 않는다.** 리졸버가 존재하는 것만으로 동작이
   바뀌면 안 된다 — 아래 `A0IsInertTest` 가 소스로 고정한다.

DB 를 쓰는 검사는 conftest 가 만들어 둔 임시 sqlite 를 쓴다(레포 DB 를 열지
않는다).
"""
import ast
import contextlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.databases.models.user_group import (GroupGrant, LEVEL_OPERATE,
                                             LEVEL_VIEW, LEVELS,
                                             RESOURCE_DASHBOARD,
                                             RESOURCE_TAB, RESOURCE_TYPES,
                                             UserGroup, UserGroupMember,
                                             wider_level)

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# --------------------------------------------------------------- 어휘 · 순수 로직

class VocabularyTest(unittest.TestCase):

    def test_resource_types(self):
        self.assertEqual(
            set(RESOURCE_TYPES),
            {'tab', 'dashboard', 'geo_map', 'geo_facility'})

    def test_levels(self):
        self.assertEqual(set(LEVELS), {'view', 'operate'})

    def test_check_script_knows_every_resource_type(self):
        """검사 스크립트와 모델이 **같은 어휘**를 써야 한다.

        한쪽만 늘리면 새 종류의 고아 grant 를 영영 못 본다 — 그리고 고아는
        에러를 내지 않으므로 아무도 모른다.
        """
        from aot.scripts.check_scope_grants import RESOURCE_TABLES
        self.assertEqual(set(RESOURCE_TABLES), set(RESOURCE_TYPES))

    def test_wider_level_prefers_operate(self):
        self.assertEqual(wider_level(LEVEL_VIEW, LEVEL_OPERATE), LEVEL_OPERATE)
        self.assertEqual(wider_level(LEVEL_OPERATE, LEVEL_VIEW), LEVEL_OPERATE)
        self.assertEqual(wider_level(LEVEL_VIEW, LEVEL_VIEW), LEVEL_VIEW)

    def test_unknown_level_narrows(self):
        """모르는 값을 넓은 쪽으로 읽으면 오타가 권한을 넓힌다."""
        self.assertEqual(wider_level('oparate', LEVEL_VIEW), LEVEL_VIEW)
        self.assertEqual(wider_level('', ''), LEVEL_VIEW)
        self.assertEqual(wider_level('nonsense', LEVEL_OPERATE), LEVEL_OPERATE)


# --------------------------------------------------------------- DB 판정

class _ScopeFixture(object):
    """DB 를 쓰는 스코프 테스트의 공용 준비.

    `unittest.TestCase` 를 상속하지 않는다 — 상속하면 pytest 가 이 클래스도
    수집해 준비 코드만 있는 빈 테스트가 생긴다.
    """

    @classmethod
    def setUpClass(cls):
        """앱은 한 번만 만들되 **컨텍스트는 푸시하지 않는다.**

        클래스 내내 푸시해 두면 다른 테스트 파일이 같은 전역 `db` 를 자기 앱에
        다시 bind 하거나 세션을 실패 상태로 남겼을 때 그것을 그대로 물려받는다.
        실제로 겪었다 — 이 파일만 돌리면 통과하고 전체 스위트에서만
        `PendingRollbackError` 로 깨졌다.
        """
        from flask import Flask
        from flask_babel import Babel

        from aot.aot_flask.extensions import db
        from aot.config import AOT_DB_PATH
        import aot.databases.models  # noqa: F401

        cls.app = Flask(__name__)
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.db = db
        # `init_app` 은 앱당 한 번만 부를 수 있다(두 번째부터 RuntimeError).
        db.init_app(cls.app)
        # `utils_general` 은 import 시점에 `config_translations` 를 끌어오고,
        # 그 모듈이 `lazy_gettext` 를 즉시 평가한다 — Babel 이 없으면 import
        # 자체가 KeyError('babel') 로 죽는다. 게이트를 실제 호출 경로에서
        # 검사하려면 그 import 가 되어야 한다.
        cls.app.config.setdefault('SECRET_KEY', 'scope-test')
        Babel(cls.app)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        # 앞선 테스트가 남긴 실패 트랜잭션을 물려받지 않는다.
        self.db.session.rollback()
        self.db.session.remove()
        self.db.create_all()

        from aot.databases.models import Input, Role, User
        self.models = {'Input': Input, 'Role': Role, 'User': User}
        self._clear_scope_cache()
        self._wipe()

        # 면제 아닌 역할 하나, 면제 역할 하나.
        self.role = Role(name='ScopeTestEditor', edit_controllers=True,
                         edit_settings=False, bypass_group_scope=False)
        self.db.session.add(self.role)
        self.role_admin = Role(name='ScopeTestAdmin', edit_controllers=True,
                               edit_settings=True, edit_users=True,
                               bypass_group_scope=True)
        self.db.session.add(self.role_admin)
        self.db.session.commit()

        self.alice = self._user('alice', self.role.id)
        self.bob = self._user('bob', self.role.id)
        self.root = self._user('root', self.role_admin.id)
        self.db.session.commit()

    def tearDown(self):
        try:
            self._wipe()
        finally:
            self._clear_scope_cache()
            self.db.session.remove()
            self.ctx.pop()

    @staticmethod
    @contextlib.contextmanager
    def _logged_in(user):
        """이 사용자가 요청을 낸 것처럼 만든다.

        `scope` 는 `flask_login.current_user` 를 보고 신원을 정하므로, 게이트가
        **실제 호출 경로에서** 동작하는지 보려면 그 이름을 갈아끼워야 한다.
        `user=` 인자로 직접 넘기면 리졸버만 검사하는 것이지 게이트가 신원을
        올바로 집어오는지는 검사하지 못한다.
        """
        import flask_login

        class _Current(object):
            is_authenticated = True

            def __init__(self, name):
                self.name = name

        original = flask_login.current_user
        flask_login.current_user = _Current(user.name)
        try:
            yield
        finally:
            flask_login.current_user = original

    @staticmethod
    def _clear_scope_cache():
        """스코프 리졸버의 요청 캐시를 비운다.

        운영에서는 요청마다 `flask.g` 가 새로 생기므로 비울 일이 없다. 테스트
        에서는 다른 파일이 남긴 요청 컨텍스트가 살아 있을 수 있고, 그러면 `g`
        가 테스트 사이에 공유된다 — 매 테스트가 사용자를 지우고 다시 만들어
        **sqlite 가 같은 id 를 재사용**하므로 공유된 캐시는 옛 판정을 그대로
        돌려준다.
        """
        try:
            from flask import g, has_request_context
            if has_request_context() and hasattr(g, '_aot_scope_cache'):
                del g._aot_scope_cache
        except Exception:
            pass

    def _wipe(self):
        from aot.databases.models import Input, Role, User
        from aot.databases.models.scheduler import SchedulerJobMeta
        for model in (GroupGrant, UserGroupMember, UserGroup, Input,
                      SchedulerJobMeta):
            model.query.delete()
        User.query.filter(User.name.in_(['alice', 'bob', 'root'])).delete(
            synchronize_session=False)
        Role.query.filter(Role.name.in_(
            ['ScopeTestEditor', 'ScopeTestAdmin'])).delete(
            synchronize_session=False)
        self.db.session.commit()

    def _user(self, name, role_id):
        from aot.databases.models import User
        row = User(name=name, role_id=role_id, is_enabled=True)
        self.db.session.add(row)
        self.db.session.flush()
        return row

    def _group(self, name, members=()):
        group = UserGroup(name=name)
        self.db.session.add(group)
        self.db.session.flush()
        for user in members:
            self.db.session.add(UserGroupMember(group_uuid=group.unique_id,
                                                user_uuid=user.unique_id))
        self.db.session.commit()
        return group

    def _input(self, unique_id, tab_id):
        from aot.databases.models import Input
        row = Input(unique_id=unique_id, name=unique_id, tab_id=tab_id)
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def _grant(self, group, rtype, ruuid, level=LEVEL_OPERATE):
        row = GroupGrant(group_uuid=group.unique_id, resource_type=rtype,
                         resource_uuid=ruuid, level=level)
        self.db.session.add(row)
        self.db.session.commit()
        return row


class ScopeResolutionTest(_ScopeFixture, unittest.TestCase):
    """리졸버의 판정. conftest 의 임시 DB 위에서 돈다."""

    # ------------------------------------------------ 1. 미지정 = 전원 공개

    def test_scoping_inactive_when_no_grants(self):
        """grant 가 0건이면 판정을 아예 건너뛴다.

        대부분의 설치는 그룹을 쓰지 않는다. 이 빠른 경로가 없으면 그 사람들이
        비용만 낸다(설계 §8-6).
        """
        from aot.aot_flask.access import scope
        self.assertFalse(scope.scoping_active())

    def test_everything_allowed_when_no_grants(self):
        from aot.aot_flask.access import scope
        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'any-tab',
                                          user=self.alice))
        self.assertEqual(
            scope.denied_resource_uuids(RESOURCE_TAB, user=self.alice),
            frozenset())

    def test_ungranted_resource_stays_open_after_scoping_starts(self):
        """다른 자원에 grant 가 생겨도, grant 없는 자원은 계속 전원 공개다.

        이것이 default-open 의 요지다 — 첫 grant 하나가 농장 전체를 잠그면
        아무도 이 기능을 켜지 않는다.
        """
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.bob])
        self._grant(group, RESOURCE_TAB, 'tab-locked')

        self.assertTrue(scope.scoping_active())
        self.assertFalse(scope.can_operate(RESOURCE_TAB, 'tab-locked',
                                           user=self.alice))
        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-open',
                                          user=self.alice))

    # ------------------------------------------------ 2. 합집합

    def test_member_can_operate_granted_resource(self):
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.alice])
        self._grant(group, RESOURCE_TAB, 'tab-1')
        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-1',
                                          user=self.alice))
        self.assertFalse(scope.can_operate(RESOURCE_TAB, 'tab-1',
                                           user=self.bob))

    def test_multiple_membership_is_a_union(self):
        """그룹을 하나 더 받으면 **넓어진다.** 교집합이면 반대가 된다."""
        from aot.aot_flask.access import scope
        g1 = self._group('1동반', members=[self.alice])
        g2 = self._group('2동반', members=[self.alice])
        self._grant(g1, RESOURCE_TAB, 'tab-1')
        self._grant(g2, RESOURCE_TAB, 'tab-2')

        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-1', user=self.alice))
        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-2', user=self.alice))
        self.assertEqual(
            scope.groups_for_user(self.alice),
            frozenset({g1.unique_id, g2.unique_id}))

    def test_view_grant_does_not_permit_operate(self):
        """A 단계에서 강제되는 것은 `operate` 뿐이다.

        `view` 만 가진 그룹이 조작까지 되면 level 을 둘로 나눈 의미가 없다.
        """
        from aot.aot_flask.access import scope
        group = self._group('참관', members=[self.alice])
        self._grant(group, RESOURCE_TAB, 'tab-1', level=LEVEL_VIEW)
        self.assertFalse(scope.can_operate(RESOURCE_TAB, 'tab-1',
                                           user=self.alice))

    # ------------------------------------------------ 면제

    def test_bypass_role_is_exempt(self):
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.bob])
        self._grant(group, RESOURCE_TAB, 'tab-1')
        self.assertTrue(scope.is_exempt(self.root))
        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-1', user=self.root))

    def test_exempt_is_not_role_id_one(self):
        """면제 판정이 `role_id == 1` 이면 두 번째 관리자 역할을 못 만든다."""
        from aot.aot_flask.access import scope
        self.assertNotEqual(self.role_admin.id, 1)
        self.assertTrue(scope.is_exempt(self.root))

    def test_system_caller_is_exempt(self):
        """요청 컨텍스트 밖(데몬·스크립트)은 스코프를 모른다 — 설계 §6-1.

        **주변에 요청 컨텍스트가 있는지에 기대지 않는다.** 전체 스위트에서는
        다른 테스트가 컨텍스트를 남겨 둘 수 있어, "지금 컨텍스트가 없다" 를
        전제로 쓰면 이 파일만 돌릴 때와 결과가 달라진다(실제로 겪었다).
        그래서 두 갈래를 각각 결정적으로 검증한다.
        """
        import flask

        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.bob])
        self._grant(group, RESOURCE_TAB, 'tab-1')

        # (1) SYSTEM 센티넬은 그대로 면제다.
        self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-1',
                                          user=scope.SYSTEM))

        # (2) "요청 컨텍스트 없음 → SYSTEM" 매핑 자체를 확인한다.
        original = flask.has_request_context
        flask.has_request_context = lambda: False
        try:
            self.assertIs(scope._resolve_user(None), scope.SYSTEM)
            self.assertTrue(scope.can_operate(RESOURCE_TAB, 'tab-1'))
        finally:
            flask.has_request_context = original

    def test_unauthenticated_request_is_denied_not_exempt(self):
        """요청 **안**에서 사용자가 없으면 시스템이 아니라 미인증이다.

        둘을 뭉치면 로그인하지 않은 요청이 데몬 권한을 얻는다.
        """
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.bob])
        self._grant(group, RESOURCE_TAB, 'tab-1')
        with self.app.test_request_context('/'):
            self.assertFalse(scope.can_operate(RESOURCE_TAB, 'tab-1'))

    # ------------------------------------------------ 4·5. 장치

    def test_device_scope_comes_from_its_tab(self):
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.alice])
        self._grant(group, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')

        self.assertEqual(scope.tab_of_device('dev-1'), 'tab-1')
        self.assertTrue(scope.can_operate_device('dev-1', user=self.alice))
        self.assertFalse(scope.can_operate_device('dev-1', user=self.bob))

    def test_device_without_tab_is_open(self):
        """탭 없는 장치는 정상이다(`tab_id` 는 nullable). 미지정 = 전원 공개."""
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.alice])
        self._grant(group, RESOURCE_TAB, 'tab-1')
        self._input('dev-orphan', None)
        self.assertTrue(scope.can_operate_device('dev-orphan', user=self.bob))

    def test_dashboard_grant_does_not_widen_device_scope(self):
        """컨테이너가 장치 권한을 넓히지 않는다(설계 §4-3).

        bob 이 대시보드를 부여받아도, 그 위 위젯이 가리키는 장치가 남의 탭에
        있으면 조작할 수 없다. 합집합으로 판정하면 감춘 장치의 위젯을 공개
        대시보드에 얹는 것만으로 스코프가 샌다.
        """
        from aot.aot_flask.access import scope
        theirs = self._group('1동반', members=[self.alice])
        bobs = self._group('대시보드반', members=[self.bob])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._grant(bobs, RESOURCE_DASHBOARD, 'dash-1')
        self._input('dev-1', 'tab-1')

        self.assertTrue(scope.can_operate(RESOURCE_DASHBOARD, 'dash-1',
                                          user=self.bob))
        self.assertFalse(scope.can_operate_device('dev-1', user=self.bob))

    # ------------------------------------------------ 거부 목록

    def test_denied_list_is_a_deny_list_not_an_allow_list(self):
        """빈 집합 = 아무것도 안 막는다. 새 자원은 자동으로 열린다."""
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.alice])
        self._grant(group, RESOURCE_TAB, 'tab-1')
        self._grant(group, RESOURCE_TAB, 'tab-2')

        self.assertEqual(scope.denied_resource_uuids(RESOURCE_TAB,
                                                     user=self.alice),
                         frozenset())
        self.assertEqual(scope.denied_resource_uuids(RESOURCE_TAB,
                                                     user=self.bob),
                         frozenset({'tab-1', 'tab-2'}))
        # 면제자에게는 거부가 없다.
        self.assertEqual(scope.denied_resource_uuids(RESOURCE_TAB,
                                                     user=self.root),
                         frozenset())

    # ------------------------------------------------ 부여 영향 미리보기

    def test_grant_impact_reports_who_loses(self):
        """무해함은 첫 grant 까지다 — 부여 화면이 미리 말해야 한다(원칙 2)."""
        from aot.aot_flask.access import scope
        group = self._group('1동반', members=[self.alice])

        impact = scope.grant_impact(RESOURCE_TAB, 'tab-1', [group.unique_id])
        # alice·bob·root 가 조작 가능했고(부여 전 = 전원 공개),
        # 부여 후에는 alice(멤버) + root(면제)만 남는다.
        self.assertEqual(impact['before'], 3)
        self.assertEqual(impact['after'], 2)
        self.assertEqual(impact['losing'], 1)
        self.assertEqual(impact['losing_names'], ['bob'])
        self.assertFalse(impact['locks_out_everyone'])

    def test_grant_impact_counts_pending_members(self):
        """아직 저장 안 된 멤버도 반영한다.

        멤버와 부여는 같은 폼으로 함께 저장된다. 저장된 멤버만 보면 방금
        체크한 사람이 계속 "잃는 사람" 으로 나와 미리보기가 늘 실제보다 많이
        세고, 그러면 관리자가 곧 무시한다 — 무시되는 경고는 없는 것과 같다.
        """
        from aot.aot_flask.access import scope
        group = self._group('1동반')            # 저장된 멤버 없음

        without = scope.grant_impact(RESOURCE_TAB, 'tab-1', [group.unique_id])
        self.assertIn('bob', without['losing_names'])

        with_pending = scope.grant_impact(
            RESOURCE_TAB, 'tab-1', [group.unique_id],
            pending_members={group.unique_id: [self.bob.unique_id]})
        self.assertNotIn('bob', with_pending['losing_names'])
        self.assertEqual(with_pending['losing_names'], ['alice'])

    def test_grant_impact_flags_total_lockout(self):
        """멤버 없는 그룹에 부여하면 면제자 말고는 아무도 조작할 수 없다."""
        from aot.aot_flask.access import scope
        empty = self._group('빈그룹')
        impact = scope.grant_impact(RESOURCE_TAB, 'tab-1', [empty.unique_id])
        self.assertEqual(impact['losing'], 2)          # alice, bob
        self.assertFalse(impact['locks_out_everyone'])  # root 는 면제라 남는다

    def test_grant_impact_ignores_service_accounts(self):
        """서비스 계정(`auth_provider='system'`)은 "잃는 사람" 이 아니다.

        사람이 아니라 로그인하지도 않고, 내부 AI 의 호출은 **사람이 없는
        호출**이라 애초에 면제다(설계 §6-2). 세면 그 목록을 보고 부여를
        망설이게 된다.
        """
        from aot.aot_flask.access import scope
        from aot.databases.models import User
        bot = User(name='scope-test-bot', full_name='AoT System',
                   role_id=self.role.id, is_enabled=True,
                   auth_provider='system')
        self.db.session.add(bot)
        self.db.session.commit()
        try:
            group = self._group('1동반', members=[self.alice])
            impact = scope.grant_impact(RESOURCE_TAB, 'tab-1',
                                        [group.unique_id])
            self.assertNotIn('AoT System', impact['losing_names'])
            self.assertEqual(impact['losing_names'], ['bob'])
        finally:
            User.query.filter(User.name == 'scope-test-bot').delete(
                synchronize_session=False)
            self.db.session.commit()

    def test_grant_impact_ignores_users_who_could_not_operate_anyway(self):
        """Monitor 는 애초에 조작할 수 없으므로 "잃는" 것이 없다.

        역할 축을 무시하고 세면 숫자가 실제보다 커지고, 그 숫자를 보고 부여를
        망설이게 된다.
        """
        from aot.aot_flask.access import scope
        from aot.databases.models import Role
        watcher_role = Role(name='ScopeTestWatcher', edit_controllers=False,
                            edit_settings=False, bypass_group_scope=False)
        self.db.session.add(watcher_role)
        self.db.session.commit()
        self._user('watcher', watcher_role.id)
        self.db.session.commit()
        try:
            group = self._group('1동반', members=[self.alice])
            impact = scope.grant_impact(RESOURCE_TAB, 'tab-1',
                                        [group.unique_id])
            self.assertNotIn('watcher', impact['losing_names'])
        finally:
            from aot.databases.models import User
            User.query.filter(User.name == 'watcher').delete(
                synchronize_session=False)
            Role.query.filter(Role.name == 'ScopeTestWatcher').delete(
                synchronize_session=False)
            self.db.session.commit()


# --------------------------------------------------------------- A0 무해성

class EntityMutationTest(_ScopeFixture, unittest.TestCase):
    """엔티티 CRUD 스코프 (A1b).

    역할 게이트는 submit 핸들러 맨 위에 있어 **어떤 장치인지 모른 채** 통과한다
    (설계 §1-A 표: routes_input :106 게이트 → :129 대상 확정). 그래서 대상이
    정해진 뒤에 한 번 더 묻는다.

    삭제는 `delete_entry_with_id()` 라는 **한 곳**을 지나므로 거기서 막는다 —
    삭제 경로마다 다는 것보다 낫고, 새 경로가 생겨도 자동으로 같은 경계를
    지난다.
    """

    def test_delete_chokepoint_refuses_out_of_scope_device(self):
        from aot.aot_flask.utils.utils_general import delete_entry_with_id
        from aot.databases.models import Input

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')

        with self.app.test_request_context('/'):
            with self._logged_in(self.bob):
                self.assertEqual(
                    delete_entry_with_id(Input, 'dev-1', flash_message=False), 0)
        # 행이 남아 있어야 한다 — 0 을 돌려주면서 지우면 최악이다.
        self.assertIsNotNone(
            Input.query.filter(Input.unique_id == 'dev-1').first())

    def test_delete_chokepoint_allows_member(self):
        from aot.aot_flask.utils.utils_general import delete_entry_with_id
        from aot.databases.models import Input

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')

        with self.app.test_request_context('/'):
            with self._logged_in(self.alice):
                delete_entry_with_id(Input, 'dev-1', flash_message=False)
        self.assertIsNone(
            Input.query.filter(Input.unique_id == 'dev-1').first())

    def test_refusal_happens_before_side_effects(self):
        """**거부는 부수 효과보다 먼저 일어나야 한다.**

        처음에는 삭제를 `delete_entry_with_id()` 초크포인트 한 곳에서만
        막았다. 그것으로 충분해 보였지만 실측에서 무너졌다(2026-08-22):

          `output_del` 은 초크포인트를 부르기 **전에** 측정값을 지우고
          바인딩을 끊는다. 그리고 초크포인트의 반환값 0(거부)을 **보지 않고**
          "삭제 성공" 을 보고했다. 결과는 출력은 남았는데 그 측정값·채널은
          사라진 **부분 변경**이고, 사용자는 성공 메시지를 봤다.

        그래서 이 검사는 "거부됐는가" 만 보지 않는다 — **아무것도 지워지지
        않았는가**를 함께 본다. 앞의 것만 보면 그때도 통과했을 것이다.
        """
        from aot.aot_flask.utils import utils_output
        from aot.databases.models import DeviceMeasurements, Output

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')

        out = Output(unique_id='out-1', name='out-1', tab_id='tab-1')
        meas = DeviceMeasurements(unique_id='meas-1', device_id='out-1')
        self.db.session.add_all([out, meas])
        self.db.session.commit()

        class _Field(object):
            def __init__(self, data):
                self.data = data

        class _Form(object):
            output_id = _Field('out-1')

        try:
            with self.app.test_request_context('/'):
                with self._logged_in(self.bob):
                    messages = utils_output.output_del(_Form())

            self.assertTrue(messages["error"], '거부되지 않았다')
            self.assertFalse(messages["success"],
                             '거부인데 성공으로 보고했다')
            # 여기가 핵심 — 부수 효과가 먼저 돌지 않았는가.
            self.assertIsNotNone(
                Output.query.filter(Output.unique_id == 'out-1').first())
            self.assertIsNotNone(
                DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == 'meas-1').first(),
                '출력은 남았는데 측정값이 지워졌다 — 부분 변경이다')
        finally:
            for model, uid in ((DeviceMeasurements, 'meas-1'), (Output, 'out-1')):
                model.query.filter(model.unique_id == uid).delete(
                    synchronize_session=False)
            self.db.session.commit()

    def test_child_rows_pass_through(self):
        """자식 행(채널·조건 등)은 스코프 대상이 아니다.

        부모를 지울 권한이 있으면 자식도 함께 지워진다. 자식마다 따로 물으면
        같은 질문을 두 번 하는 것이고, 게다가 자식은 탭을 갖지 않아 물어도
        늘 통과한다 — 그 무의미한 통과가 "검사했다" 로 읽히면 안 된다.
        """
        from aot.aot_flask.access import scope
        from aot.databases.models import InputChannel

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self.assertTrue(
            scope.can_operate_record(InputChannel, 'anything', user=self.bob))

    def test_tab_itself_is_the_grant_unit(self):
        """탭 삭제/이름변경이 막히지 않으면 **삭제로 부여를 해제**할 수 있다."""
        from aot.aot_flask.access import scope
        from aot.databases.models import Tab

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self.assertFalse(
            scope.can_operate_record(Tab, 'tab-1', user=self.bob))
        self.assertTrue(
            scope.can_operate_record(Tab, 'tab-1', user=self.alice))

    def test_widget_is_scoped_by_its_dashboard(self):
        from aot.aot_flask.access import scope
        from aot.databases.models import Widget

        bobs = self._group('대시보드반', members=[self.bob])
        self._grant(bobs, RESOURCE_DASHBOARD, 'dash-1')
        w = Widget(unique_id='w-1', tab_id='dash-1')
        self.db.session.add(w)
        self.db.session.commit()
        try:
            self.assertTrue(
                scope.can_operate_record(Widget, 'w-1', user=self.bob))
            self.assertFalse(
                scope.can_operate_record(Widget, 'w-1', user=self.alice))
        finally:
            Widget.query.filter(Widget.unique_id == 'w-1').delete(
                synchronize_session=False)
            self.db.session.commit()

    def test_unknown_model_is_not_scoped(self):
        """명부에 없는 모델은 통과시킨다.

        기본 거부로 두면 스코프와 무관한 모델(측정값·노트·설정 …)의 삭제가
        전부 막혀, 그룹을 켜는 순간 시스템이 통째로 멈춘다.
        """
        from aot.aot_flask.access import scope
        from aot.databases.models import Misc

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self.assertTrue(
            scope.can_operate_record(Misc, 'whatever', user=self.bob))


class ScheduledActionRecheckTest(_ScopeFixture, unittest.TestCase):
    """예약 발화 시 재검사 (A1a · 설계 §6-3·§8-7).

    **생성 시 한 번 검사하는 것으로는 부족하다.** 잡스토어는 영구이고 발화는
    신원 없이 일어나므로, 재검사가 없으면 둘이 무너진다:

    1. 그룹에서 뺀 사람이 어제 걸어 둔 예약이 계속 발화한다 — 권한 회수의
       의미가 "지금부터 못 한다" 가 아니라 "지금부터 새로 만들지 못한다" 로
       조용히 바뀐다.
    2. **"지금 못 켜니 1분 뒤로 예약" 이 제어 게이트의 우회로가 된다.** 게이트를
       켠 뒤 남는 구멍 중 사람이 의도적으로 쓸 수 있는 유일한 것이다.

    판정 신원은 `SchedulerJobMeta.user_id` 다 — 새 컬럼을 만들지 않았으므로
    **이 변경 이전에 만들어진 예약도 같은 경로로 검사된다**(kwargs 에 실었다면
    잡스토어에 이미 직렬화된 예약은 영영 검사 밖에 남았을 것이다).
    """

    def _meta(self, target_id, user_id):
        from aot.databases.models.scheduler import SchedulerJobMeta
        row = SchedulerJobMeta(action_type='output', target_id=target_id,
                               params_json='{}', user_id=user_id)
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def _denies(self, meta_id, target_id, params=None, action_type='output'):
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        return AISchedulerService._scope_denies(meta_id, action_type,
                                                target_id, params)

    def test_owner_outside_scope_is_refused_at_fire_time(self):
        """우회로를 닫는다 — 만든 사람이 지금 조작할 수 없으면 발화하지 않는다."""
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')
        meta = self._meta('dev-1', self.bob.id)

        reason = self._denies(meta.id, 'dev-1')
        self.assertIsNotNone(reason)
        self.assertIn('bob', reason)

    def test_owner_inside_scope_still_fires(self):
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')
        meta = self._meta('dev-1', self.alice.id)
        self.assertIsNone(self._denies(meta.id, 'dev-1'))

    def test_legacy_schedule_without_owner_is_exempt(self):
        """기존 예약(user_id NULL)은 **한시 면제**다.

        거부로 두면 업그레이드 순간 돌던 예약이 전부 멈춘다 — 원칙 2
        (default-open)와 같은 이유로 면제가 맞다. 그 건수는
        `check_scope_grants.py` 의 `legacy-schedule` 이 계속 보여준다.
        """
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')
        meta = self._meta('dev-1', None)
        self.assertIsNone(self._denies(meta.id, 'dev-1'))

    def test_deleted_owner_is_exempt_not_refused(self):
        """만든 사람이 지워졌으면 면제한다.

        거부하면 **사람을 지우는 것만으로 남의 예약이 멈춘다** — 이 함수가
        막으려는 것과 다른 종류의 사고다.
        """
        from aot.databases.models import User
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')
        meta = self._meta('dev-1', self.bob.id)
        User.query.filter(User.id == self.bob.id).delete(
            synchronize_session=False)
        self.db.session.commit()
        self.assertIsNone(self._denies(meta.id, 'dev-1'))

    def test_mcp_tool_call_target_comes_from_arguments(self):
        """MCP 도구 호출은 대상이 인자 안에 있다.

        겉의 `target_id` 는 도구 이름이라 그것으로 물으면 **늘 통과한다**
        (존재하지 않는 장치 = 탭 없음 = 전원 공개). 조용히 새는 모양이다.
        """
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')
        meta = self._meta('operate_device', self.bob.id)

        # 인자를 안 보면 통과해 버린다는 것부터 고정한다.
        self.assertIsNone(self._denies(meta.id, 'operate_device',
                                       params={}, action_type='mcp_tool_call'))
        reason = self._denies(meta.id, 'operate_device',
                              params={'arguments': {'device_id': 'dev-1'}},
                              action_type='mcp_tool_call')
        self.assertIsNotNone(reason)

    def test_check_failure_does_not_block_execution(self):
        """재검사가 깨져도 예약은 돈다.

        막으면 스코프를 쓰지 않는 설치에서 이 코드의 버그 하나가 모든 예약을
        멈춘다. 대신 로그로 시끄럽게 남긴다.
        """
        from unittest.mock import patch

        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input('dev-1', 'tab-1')
        meta = self._meta('dev-1', self.bob.id)

        with patch('aot.aot_flask.access.scope.can_operate_device',
                   side_effect=RuntimeError('boom')):
            self.assertIsNone(self._denies(meta.id, 'dev-1'))


class TabVisibilityTest(_ScopeFixture, unittest.TestCase):
    """조작할 수 없는 탭은 목록에서 뺀다 (부여 UI 재설계, 2026-08-22).

    ⚠ **정보 격리가 아니다.** 감추는 것은 장치 **관리 화면**뿐이고, 그
    장치들의 값은 대시보드·지도·`/data_batch` 로 여전히 보인다. 감추는 대상을
    넓히는 것은 B 단계의 결정이다 — 여기서 조용히 넓히면 사용자는 격리됐다고
    믿게 되고, 설계가 "깨지는 자리가 고객 신뢰다" 라고 적어 둔 그 일이 난다.

    감추는 이유는 UX 다: 조작할 수 없는 탭을 목록에 두면 눌러 보고 거부당하는
    일이 반복되고, 자원이 늘수록 그 잡음이 커진다.
    """

    def _tab(self, uid, name, page_type='input', position=0):
        from aot.databases.models import Tab
        row = Tab(unique_id=uid, name=name, page_type=page_type,
                  position=position)
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def _wipe_tabs(self):
        from aot.databases.models import Tab
        Tab.query.filter(Tab.unique_id.in_(['t-mine', 't-theirs', 't-open'])).delete(
            synchronize_session=False)
        self.db.session.commit()

    def test_only_operable_tabs_are_listed(self):
        from aot.services.tab_service import TabService
        self._wipe_tabs()
        try:
            self._tab('t-theirs', '1동', position=0)
            self._tab('t-open', '공용', position=1)
            theirs = self._group('1동반', members=[self.alice])
            self._grant(theirs, RESOURCE_TAB, 't-theirs')

            # **신원을 명시한다.** 주변에 요청 컨텍스트가 있는지에 기대면 이
            # 파일만 돌릴 때와 전체 스위트에서 결과가 달라진다(실제로 겪었다 —
            # 남의 테스트가 남긴 요청 컨텍스트 안에서는 미인증으로 읽혀 전부
            # 거부됐다).
            with self.app.test_request_context('/'):
                with self._logged_in(self.alice):
                    mine = [t.unique_id for t in
                            TabService.visible_tabs_for_page('input')]
            self.assertIn('t-theirs', mine)      # alice 는 멤버
            self.assertIn('t-open', mine)        # 미지정 = 전원 공개

            with self.app.test_request_context('/'):
                with self._logged_in(self.bob):
                    theirs_view = [t.unique_id for t in
                                   TabService.visible_tabs_for_page('input')]
            self.assertNotIn('t-theirs', theirs_view)
            self.assertIn('t-open', theirs_view)
        finally:
            self._wipe_tabs()

    def test_raw_listing_stays_unfiltered(self):
        """**`get_tabs_for_page` 를 대신 고치면 안 된다.**

        그 함수는 삭제 시 "마지막 탭인가" 판정처럼 서버가 전체를 알아야 하는
        자리에서도 쓰인다. 거기서 걸러진 목록을 쓰면, 남의 탭이 안 보이는
        사람에게는 자기 탭이 늘 "마지막 탭" 이 되어 삭제가 막힌다.
        """
        from aot.services.tab_service import TabService
        self._wipe_tabs()
        try:
            self._tab('t-theirs', '1동', position=0)
            self._tab('t-open', '공용', position=1)
            theirs = self._group('1동반', members=[self.alice])
            self._grant(theirs, RESOURCE_TAB, 't-theirs')

            with self.app.test_request_context('/'):
                with self._logged_in(self.bob):
                    raw = [t.unique_id for t in
                           TabService.get_tabs_for_page('input')]
            self.assertIn('t-theirs', raw)
        finally:
            self._wipe_tabs()

    def test_default_tab_is_one_the_user_can_see(self):
        """position 0 탭이 스코프 밖이면 그것으로 보내면 안 된다 —
        목록에 없는 탭이 열려 있는 모순된 화면이 된다."""
        from aot.services.tab_service import TabService
        self._wipe_tabs()
        try:
            self._tab('t-theirs', '1동', position=0)
            self._tab('t-open', '공용', position=1)
            theirs = self._group('1동반', members=[self.alice])
            self._grant(theirs, RESOURCE_TAB, 't-theirs')

            with self.app.test_request_context('/'):
                with self._logged_in(self.bob):
                    tab = TabService.default_visible_tab('input')
            self.assertIsNotNone(tab)
            self.assertEqual(tab.unique_id, 't-open')
        finally:
            self._wipe_tabs()

    def test_no_visible_tab_returns_none_instead_of_leaking(self):
        from aot.services.tab_service import TabService
        self._wipe_tabs()
        try:
            self._tab('t-theirs', '1동', position=0)
            theirs = self._group('1동반', members=[self.alice])
            self._grant(theirs, RESOURCE_TAB, 't-theirs')
            with self.app.test_request_context('/'):
                with self._logged_in(self.bob):
                    self.assertIsNone(TabService.default_visible_tab('input'))
        finally:
            self._wipe_tabs()


class DashboardVisibilityTest(_ScopeFixture, unittest.TestCase):
    """부여된 대시보드는 **목록에서 사라지고 진입도 막힌다** (2026-08-22).

    처음에는 "대시보드는 감시 화면이니 감추지 않는다" 로 정했는데, 그것이
    요구와 어긋났다 — 원문 요구가 "나머지는 부여받은 그룹만 **접근**" 이었다.
    부여를 해 두고도 비멤버가 그대로 보고 들어갈 수 있으면 부여가 무슨 뜻인지
    사용자가 알 수 없다.

    ⚠ 값 자체는 여전히 `/data_batch` 등으로 닿는다(A 범위는 조작만 막는다).
    이것은 화면을 치우는 것이지 데이터 격리가 아니다.
    """

    def _dash(self, uid, name, sort_order=0):
        from aot.databases.models import Dashboard
        row = Dashboard(unique_id=uid, name=name, sort_order=sort_order)
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def _wipe_dash(self):
        from aot.databases.models import Dashboard
        Dashboard.query.filter(
            Dashboard.unique_id.in_(['d-theirs', 'd-open'])).delete(
            synchronize_session=False)
        self.db.session.commit()

    def test_granted_dashboard_disappears_for_non_members(self):
        from aot.aot_flask.routes_static import visible_dashboards
        self._wipe_dash()
        try:
            theirs = self._dash('d-theirs', '대시보드6', sort_order=0)
            openish = self._dash('d-open', '공용', sort_order=1)
            group = self._group('1동반', members=[self.alice])
            self._grant(group, RESOURCE_DASHBOARD, 'd-theirs')
            rows = [theirs, openish]

            with self.app.test_request_context('/'):
                with self._logged_in(self.alice):
                    mine = [d.unique_id for d in visible_dashboards(rows)]
            self.assertEqual(mine, ['d-theirs', 'd-open'])

            with self.app.test_request_context('/'):
                with self._logged_in(self.bob):
                    other = [d.unique_id for d in visible_dashboards(rows)]
            self.assertEqual(other, ['d-open'], '비멤버에게 부여된 것이 보인다')
        finally:
            self._wipe_dash()

    def test_filtering_happens_outside_the_shared_cache(self):
        """**`_cached_dashboards()` 안에서 거르면 안 된다.**

        그것은 프로세스 공유 캐시(TTL)라, 거기서 거르면 한 사람의 목록이 그 뒤
        모든 사람에게 나간다 — 이 저장소가 캐시로 신원이 섞이는 사고를 이미
        겪은 그 모양이다(2026-08-12).
        """
        import inspect

        from aot.aot_flask import routes_static
        src = inspect.getsource(routes_static._cached_dashboards)
        for name in ('can_operate', 'denied_resource_uuids', 'scope'):
            self.assertNotIn(name, src,
                             '공유 캐시 안에서 스코프를 판정하고 있다')

    def test_entry_is_blocked_not_just_hidden(self):
        """목록에서 빼는 것만으로는 부족하다 — URL·북마크로 들어오는 길이
        남으면 "감췄다" 가 아니라 "메뉴에서만 없앴다" 다."""
        from aot.aot_flask.access import scope
        self._wipe_dash()
        try:
            self._dash('d-theirs', '대시보드6')
            group = self._group('1동반', members=[self.alice])
            self._grant(group, RESOURCE_DASHBOARD, 'd-theirs')
            self.assertFalse(
                scope.can_operate('dashboard', 'd-theirs', user=self.bob))
            self.assertTrue(
                scope.can_operate('dashboard', 'd-theirs', user=self.alice))
        finally:
            self._wipe_dash()

    def test_default_dashboard_does_not_bounce_to_home(self):
        """보이는 대시보드가 0개인 사용자가 **무한 리다이렉트에 빠지면 안 된다.**

        `landing_page='dashboard'` 인 사용자의 home 은 다시
        `page_dashboard_default` 로 온다. 거기서 home 으로 되돌리면 고리가 된다 —
        대시보드가 없던 시절에는 만들기 어려운 조합이었지만, 그룹 스코프가
        생기면서 그런 사용자가 정상적으로 존재하게 됐다.
        """
        import inspect

        from aot.aot_flask import routes_dashboard
        src = inspect.getsource(routes_dashboard.page_dashboard_default)
        # 주석은 뺀다 — 왜 그러면 안 되는지 설명하는 문장이 거기 있다.
        code = '\n'.join(line for line in src.splitlines()
                         if not line.lstrip().startswith('#'))
        self.assertNotIn("url_for('routes_general.home')", code,
                         'home 으로 되돌리면 무한 리다이렉트가 된다')


class GroupSaveKeepsGrantsTest(_ScopeFixture, unittest.TestCase):
    """**그룹을 저장해도 부여가 지워지면 안 된다.**

    부여 편집이 자원 쪽으로 옮겨간 뒤에도 그룹 저장 핸들러에 "부여 전량 교체"
    코드가 남아 있으면, 폼이 부여를 보내지 않으므로 **그룹 이름만 고쳐도 부여가
    전부 지워진다** — 아무 에러 없이, 그리고 그 사실은 누군가 조작을 잃은
    뒤에야 드러난다.
    """

    def test_saving_a_group_does_not_clear_its_grants(self):
        from aot.aot_flask.utils import utils_settings
        from aot.databases.models import GroupGrant

        group = self._group('1동반', members=[self.alice])
        self._grant(group, RESOURCE_TAB, 'tab-1')

        class _Field(object):
            def __init__(self, data):
                self.data = data

        class _Form(object):
            user_group_add = _Field(False)
            user_group_save = _Field(True)
            user_group_delete = _Field(False)
            group_id = _Field(group.unique_id)
            name = _Field('1동반(수정)')
            description = _Field('')

        class _Req(dict):
            def getlist(self, key):
                return [self.alice_uuid] if key == 'group_members' else []

        req = _Req()
        req.alice_uuid = self.alice.unique_id

        with self.app.test_request_context('/'):
            with self._logged_in(self.root):
                utils_settings.user_groups(_Form(), req)

        self.assertEqual(
            GroupGrant.query.filter(
                GroupGrant.group_uuid == group.unique_id).count(), 1,
            '그룹을 저장했더니 부여가 지워졌다')


class DashboardGrantFormTest(_ScopeFixture, unittest.TestCase):
    """대시보드 부여는 이름과 **같은 [저장]** 으로 함께 나간다.

    ⚠ 핵심은 **"보내지 않음" 과 "전부 해제" 의 구분**이다. 폼이 그룹 섹션을
    그리지 않았을 때(비관리자·로딩 실패) 빈 목록을 전량 교체로 넘기면
    대시보드 이름만 고쳐도 부여가 통째로 지워진다 — 그룹 저장 핸들러에서 이미
    한 번 겪은 실패이고, 같은 모양이 자원마다 되풀이될 수 있다.
    """

    def _dash(self, uid='dash-1', name='대시보드'):
        from aot.databases.models import Dashboard
        row = Dashboard(unique_id=uid, name=name)
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def _wipe_dash(self):
        from aot.databases.models import Dashboard
        Dashboard.query.filter(Dashboard.unique_id == 'dash-1').delete(
            synchronize_session=False)
        self.db.session.commit()

    def test_absent_section_leaves_grants_alone(self):
        from aot.aot_flask.utils.utils_dashboard import _apply_dashboard_groups
        from aot.databases.models import GroupGrant

        self._wipe_dash()
        try:
            self._dash()
            group = self._group('1동반', members=[self.alice])
            self._grant(group, RESOURCE_DASHBOARD, 'dash-1')

            # 표식 없는 폼 = 섹션이 없었다
            with self.app.test_request_context('/', method='POST', data={}):
                with self._logged_in(self.root):
                    self.assertEqual(_apply_dashboard_groups('dash-1'), [])

            self.assertEqual(GroupGrant.query.filter(
                GroupGrant.resource_uuid == 'dash-1').count(), 1,
                '섹션을 안 보냈는데 부여가 지워졌다')
        finally:
            self._wipe_dash()

    def test_marker_is_not_rendered_statically(self):
        """표식은 **조회에 성공했을 때만** 들어가야 한다.

        `display:none` 안의 hidden input 도 그대로 제출된다. 표식을 템플릿에
        정적으로 두면 조회가 실패해 목록이 빈 상태에서도 표식만 나가
        "전부 해제" 로 읽히고, 대시보드 이름만 고쳐도 부여가 통째로 지워진다
        (무에러). "보내지 않음" 과 "전부 해제" 를 구분하는 것이 이 표식의
        전부이므로, 표식 자체가 그 구분을 지켜야 한다.

        레이아웃은 기동 시 `layout_default.html` 로 덮어써지므로 그 파일을 본다.
        """
        import os
        import re
        path = os.path.join(_REPO, 'aot/aot_flask/templates/layout_default.html')
        html = open(path, encoding='utf-8').read()

        # `<script>` 안은 JS 가 만들어 넣는 것이라 정적 렌더가 아니다.
        markup = re.sub(r'(?s)<script\b.*?</script>', '', html)
        static = re.findall(
            r'<input[^>]*name="dashboard_groups_present"[^>]*>', markup)
        self.assertEqual(
            static, [],
            '표식이 템플릿에 정적으로 렌더된다 — 조회 실패 시 부여가 지워진다')
        self.assertIn('dashboard_groups_present', html,
                      'JS 가 표식을 넣는 코드조차 없다')

    def test_present_section_replaces_grants(self):
        from aot.aot_flask.utils.utils_dashboard import _apply_dashboard_groups
        from aot.databases.models import GroupGrant

        self._wipe_dash()
        try:
            self._dash()
            group = self._group('1동반', members=[self.alice])
            self._grant(group, RESOURCE_DASHBOARD, 'dash-1')

            with self.app.test_request_context(
                    '/', method='POST',
                    data={'dashboard_groups_present': '1'}):
                with self._logged_in(self.root):
                    self.assertEqual(_apply_dashboard_groups('dash-1'), [])

            self.assertEqual(GroupGrant.query.filter(
                GroupGrant.resource_uuid == 'dash-1').count(), 0,
                '전부 해제를 보냈는데 반영되지 않았다')
        finally:
            self._wipe_dash()

    def test_non_admin_cannot_change_grants(self):
        """표식만 흉내내 보내도 통과하면 안 된다 — 부여는 사용자 관리 권한이다."""
        from aot.aot_flask.utils.utils_dashboard import _apply_dashboard_groups
        from aot.databases.models import GroupGrant

        self._wipe_dash()
        try:
            self._dash()
            group = self._group('1동반', members=[self.alice])
            self._grant(group, RESOURCE_DASHBOARD, 'dash-1')

            with self.app.test_request_context(
                    '/', method='POST',
                    data={'dashboard_groups_present': '1'}):
                with self._logged_in(self.alice):   # edit_users 없음
                    _apply_dashboard_groups('dash-1')

            self.assertEqual(GroupGrant.query.filter(
                GroupGrant.resource_uuid == 'dash-1').count(), 1,
                '비관리자가 부여를 바꿨다')
        finally:
            self._wipe_dash()


class ResourceScopeUIGuardTest(unittest.TestCase):
    """부여 UI 넷이 **같은 안전장치**를 갖는가 (소스 검사).

    자원마다 저장 방식이 다르다 — 탭·지도는 모달 [저장], 대시보드는 폼 POST,
    시설은 자기 [적용]. 방식이 갈리면 **같은 실수를 자리마다 다시 하게 된다.**
    실제로 대시보드에서 한 번 냈다: 섹션이 로드되지 않은 상태에서 "체크 없음"
    을 전량 교체로 보내면 이름만 고쳐도 부여가 통째로 지워진다(무에러).

    그래서 "섹션이 실제로 로드됐을 때만 보낸다" 는 규칙을 넷 모두에서 본다.
    """

    FILES = {
        'map': 'aot/aot_flask/static/js/geo/aot-map-settings-modal.js',
        'facility': 'aot/aot_flask/static/js/geo/aot-facility-scope.js',
    }

    def test_map_and_facility_guard_on_a_loaded_section(self):
        import os
        for kind, rel in self.FILES.items():
            src = open(os.path.join(_REPO, rel), encoding='utf-8').read()
            post = src.index("method: 'POST'", src.index('/api/scope/grants/'))
            head = src[max(0, post - 700):post]
            self.assertIn('length', head,
                          '%s: 섹션 로드 여부를 확인하지 않고 부여를 보낸다' % kind)

    def test_every_surface_uses_the_generic_endpoint(self):
        """자원마다 라우트를 복사하면 네 벌이 조용히 갈린다."""
        import os
        surfaces = dict(self.FILES)
        surfaces['tab'] = 'aot/aot_flask/templates/modals/tab_settings.html'
        surfaces['dashboard'] = 'aot/aot_flask/templates/layout_default.html'
        for kind, rel in surfaces.items():
            src = open(os.path.join(_REPO, rel), encoding='utf-8').read()
            self.assertIn('/api/scope/grants/', src, kind)

    def test_resource_types_cover_all_four_surfaces(self):
        from aot.databases.models.user_group import RESOURCE_TYPES
        self.assertEqual(
            set(RESOURCE_TYPES),
            {'tab', 'dashboard', 'geo_map', 'geo_facility'})


class DuplicateRouteTrapTest(unittest.TestCase):
    """**같은 URL 을 두 곳이 등록하면 느슨한 쪽이 실질 권한이 된다.**

    2026-08-22 에 실제로 그랬다. 지도 쓰기를 `routes_geo.py` 에서 막았는데
    실측에서 그대로 통과했다 — `/api/geo/designs` POST 가 **두 곳**에
    등록돼 있었고(`api.geo_geo_designs` 와 `routes_geo.api_geo_design_save`)
    Flask 는 먼저 등록된 쪽을 매칭한다. 막은 것은 안 쓰이는 쪽이었다.

    증상이 고약하다: 게이트는 코드에 멀쩡히 있고, 리졸버는 단독으로 물으면
    올바로 `False` 를 돌려주며, 검사기도 "강제 지점이 있다" 고 답한다. 오직
    HTTP 로 실제로 눌러 봐야 드러난다.

    그래서 두 구현 **모두** 막혀 있는지 본다 — 어느 쪽이 이기든 결과가 같아야
    한다. 등록 순서에 기대는 것은 그 자체로 취약하다.
    """

    #: (파일, 그 파일이 반드시 막아야 하는 자원 종류)
    GEO_WRITE_FILES = (
        'aot/aot_flask/api/geo.py',
        'aot/aot_flask/routes_geo.py',
    )

    def test_both_geo_design_implementations_are_gated(self):
        import os
        for rel in self.GEO_WRITE_FILES:
            src = open(os.path.join(_REPO, rel), encoding='utf-8').read()
            self.assertIn(
                "can_operate('geo_map'", src,
                '%s 에 지도 스코프 게이트가 없다 — 같은 URL 의 다른 구현이 '
                '막혀 있어도 이쪽이 매칭되면 그대로 통과한다.' % rel)

    def test_no_scoped_url_is_registered_twice_for_the_same_method(self):
        """같은 (URL, 메서드)를 두 엔드포인트가 등록하지 않는가.

        앱을 띄워야 알 수 있으므로 소스가 아니라 `url_map` 을 본다. 여기서
        걸리는 것이 곧 "어느 쪽이 이기는지 모르는 상태" 다.
        """
        from collections import defaultdict

        from flask import Flask

        from aot.aot_flask import routes_geo
        app = Flask(__name__)
        app.register_blueprint(routes_geo.blueprint)

        by = defaultdict(set)
        for rule in app.url_map.iter_rules():
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                by[(str(rule), method)].add(rule.endpoint)
        dupes = {k: sorted(v) for k, v in by.items() if len(v) > 1}
        self.assertEqual(
            dupes, {},
            '같은 URL·메서드를 두 곳이 등록한다 — 어느 쪽이 매칭될지 '
            '등록 순서에 달렸고, 한쪽만 막으면 조용히 뚫린다.')


class ToolCallScopeTest(_ScopeFixture, unittest.TestCase):
    """AI·MCP 쓰기 도구 스코프 (A2 · 설계 §6-2).

    신원 축이 셋이다 — 외부 MCP 는 **키 소유자**, 인앱 채팅은 **부른 사람**,
    사람이 없는 호출(백그라운드 AI 잡·주기 요약)은 **면제**다.

    **인자 이름이 아니라 값으로 대상을 찾는다.** 쓰기 도구 59개의 인자 이름은
    제각각이고 대부분 기계 판독 가능한 스키마조차 없다(매니페스트가 산문이다).
    이름 목록으로 찾으면 새 도구가 다른 이름을 쓰는 순간 조용히 새고, 그 사실은
    남의 장치가 움직인 뒤에야 드러난다.
    """

    WRITE = frozenset({'operate_device', 'delete_input'})

    #: 실제 장치 id 와 같은 모양(uuid4)이어야 한다 — 값으로 대상을 찾으므로
    #: 모양이 다르면 그 인자는 아예 후보에서 빠진다.
    DEV = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'

    def _judge(self, tool, args, user):
        from aot.aot_flask.access import scope
        return scope.can_operate_tool_call(tool, args, user=user,
                                           write_tools=self.WRITE)

    def test_write_tool_on_out_of_scope_device_is_refused(self):
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input(self.DEV, 'tab-1')

        allowed, denied = self._judge(
            'operate_device', {'device_id': self.DEV}, self.bob)
        self.assertFalse(allowed)
        self.assertEqual(denied, self.DEV)

        allowed, _ = self._judge(
            'operate_device', {'device_id': self.DEV}, self.alice)
        self.assertTrue(allowed)

    def test_real_ids_match_the_uuid_shape_filter(self):
        """**값으로 찾는 방식은 "id 는 uuid4 다" 라는 전제 위에 있다.**

        모양이 다른 id 가 생기면 그 인자는 후보에서 조용히 빠지고, 그 도구만
        스코프 밖이 된다 — 에러는 나지 않는다. 그래서 전제를 고정한다.
        """
        from aot.aot_flask.access.scope import _looks_like_uuid
        from aot.databases import set_uuid
        for _ in range(5):
            self.assertTrue(_looks_like_uuid(set_uuid()))

    def test_read_tools_are_not_scoped(self):
        """A 범위에서 보기는 전원 공개다 — 조회 도구를 막으면 범위를 넘는다."""
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input(self.DEV, 'tab-1')
        allowed, _ = self._judge(
            'get_sensor_reading', {'device_id': self.DEV}, self.bob)
        self.assertTrue(allowed)

    def test_target_is_found_by_value_not_by_key_name(self):
        """인자 이름이 무엇이든 값이 스코프 대상이면 잡힌다.

        이것이 이름 기반 추출과 갈리는 지점이다 — 새 도구가 `widget_target`
        이든 `payload.uuid` 든 자동으로 덮인다.
        """
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input(self.DEV, 'tab-1')

        for args in ({'some_unusual_name': self.DEV},
                     {'payload': {'nested': {'x': self.DEV}}},
                     {'targets': ['other', self.DEV]}):
            allowed, denied = self._judge('operate_device', args, self.bob)
            self.assertFalse(allowed, args)
            self.assertEqual(denied, self.DEV)

    def test_unrelated_uuids_are_ignored(self):
        """스코프 대상이 아닌 uuid 는 통과시킨다.

        기본 거부로 두면 노트 id·측정 id 를 인자로 받는 쓰기 도구가 전부
        막혀, 그룹을 켜는 순간 AI 가 아무것도 못 하게 된다.
        """
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        allowed, _ = self._judge(
            'operate_device',
            {'note_id': '11111111-2222-3333-4444-555555555555'}, self.bob)
        self.assertTrue(allowed)

    def test_no_human_caller_is_exempt(self):
        """사람이 없는 호출(백그라운드 AI 잡)은 면제다 — §6-1 과 같은 근거."""
        from aot.ai.services.tool_execution import _scope_refusal
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input(self.DEV, 'tab-1')
        self.assertIsNone(
            _scope_refusal('operate_device', {'device_id': self.DEV}, None))

    def test_unknown_user_uuid_does_not_refuse(self):
        """신원은 왔는데 그 사용자가 없으면 판정 근거가 없다 — 거부하지 않는다."""
        from aot.ai.services.tool_execution import _scope_refusal
        theirs = self._group('1동반', members=[self.alice])
        self._grant(theirs, RESOURCE_TAB, 'tab-1')
        self._input(self.DEV, 'tab-1')
        self.assertIsNone(_scope_refusal(
            'operate_device', {'device_id': self.DEV},
            '99999999-9999-9999-9999-999999999999'))

    def test_use_tool_forwards_the_identity(self):
        """**`use_tool` 로 감싸면 스코프를 벗어난다** 를 막는다.

        서랍 안 도구는 전부 `use_tool` 을 지나고, 그 위임에서
        `scope_user_uuid` 를 안 넘기면 감싸 부르는 것만으로 판정이 사라진다.
        소스로 고정한다 — 실행 경로로는 승인 게이트까지 함께 태워야 해서
        이 계약만 따로 보기 어렵다.
        """
        import inspect

        from aot.ai.services import tool_execution
        src = inspect.getsource(tool_execution._execute_tool)
        head = src[:src.index('permission = gate.classify_permission')]
        self.assertIn('scope_user_uuid=scope_user_uuid', head,
                      'use_tool 위임이 신원을 넘기지 않는다')

    def test_scope_is_checked_before_the_approval_gate(self):
        """스코프 거부는 **승인 큐보다 먼저**여야 한다.

        뒤에 두면 어차피 거부될 호출이 승인 큐에 들어가고, 사람이 승인한
        뒤에야 거부된다 — 승인한 사람에게는 "승인했는데 안 됐다" 로 보이고
        큐에는 답할 수 없는 항목이 쌓인다.
        """
        import inspect

        from aot.ai.services import tool_execution
        src = inspect.getsource(tool_execution._execute_tool)
        self.assertLess(src.index('_scope_refusal('), src.index('gate.gate('),
                        '스코프 판정이 승인 게이트보다 뒤에 있다')


class EnforcementBoundaryTest(unittest.TestCase):
    """강제는 **정해진 자리에서만** 일어난다 (A1a).

    A0 에서는 이 명부가 비어 있었고, 그 비어 있음이 곧 "아직 아무것도 막지
    않는다" 의 증명이었다. A1a 가 제어 경로를 열었으므로 이제 명부는 **강제해도
    되는 곳의 목록**이다.

    명부 밖에서 강제하면 실패한다. 그 이유는 "그 코드가 틀렸다" 가 아니라
    **강제를 늘리는 것이 조용히 일어나면 안 되기 때문**이다 — 어디가 막히는지가
    코드 전체에 흩어지면, 사용자가 "왜 안 되지" 라고 물을 때 답할 수 있는
    사람이 없어진다. A1b·A2 에서 늘릴 때도 여기에 근거와 함께 적는다.

    **어디에 게이트가 서 있어야 하는가** 는 이 테스트가 아니라
    `aot/scripts/check_scope_gates.py` 가 본다(데몬 제어 호출 기준). 둘은 방향이
    반대다 — 저기는 "빠진 곳", 여기는 "넘친 곳".
    """

    ENFORCING = ('can_operate', 'can_operate_device', 'can_operate_widget',
                 'can_operate_record', 'can_operate_tool_call',
                 'denied_resource_uuids')

    #: 강제가 허용된 모듈(레포 상대경로 접두사).
    ALLOWED_CALLERS = (
        'aot/aot_flask/access/',
        'aot/tests/',
        # --- A1a: 제어 경로 ---
        'aot/aot_flask/routes_general.py',      # output_mod · widget_execute
        'aot/aot_flask/routes_geo.py',          # 지도 출력 제어 · 시설 적용
        'aot/aot_flask/routes_geo_iec.py',      # 시설 직접 제어 · 함수 상태
        'aot/aot_flask/api/output.py',          # REST 출력 제어
        'aot/aot_flask/api/controller.py',      # REST 컨트롤러 활성/비활성
        'aot/aot_flask/utils/utils_general.py',  # controller_activate_deactivate 초크포인트
        'aot/widgets/',                         # 위젯 제어(타이머·PID·시퀀스 등)
        # --- A1a: 예약 발화 재검사(§8-7) ---
        'aot/ai/services/ai_scheduler_service.py',
        # --- A2: AI·MCP 쓰기 도구 ---
        'aot/ai/services/tool_execution.py',
        # --- 지도 쓰기 (2026-08-22) ---
        # ⚠ 두 곳이 같은 URL 을 등록한다 — 한쪽만 막으면 조용히 뚫린다
        #   (`DuplicateRouteTrapTest` 참조).
        'aot/aot_flask/api/geo.py',
        # --- 자원 목록 필터 (2026-08-22) ---
        # 조작할 수 없는 탭·대시보드는 목록에서 빼고 진입도 막는다.
        # ⚠ 정보 격리가 아니다 — 값은 대시보드 위젯·지도로 여전히 닿는다.
        'aot/aot_flask/routes_static.py',     # 대시보드 목록(공유 캐시 **밖**)
        'aot/aot_flask/routes_dashboard.py',  # 기본 대시보드 선택 · 진입 차단
        # --- A1b: 엔티티 CRUD ---
        # 삭제는 `utils_general.delete_entry_with_id` 한 곳이 막는다(초크포인트).
        # 나머지는 대상이 정해진 뒤 각 변경 함수에서 묻는다.
        'aot/aot_flask/utils/',
        'aot/services/tab_service.py',    # 탭은 자기 자신이 부여 단위다
    )

    def _python_files(self):
        for root, dirs, files in os.walk(os.path.join(_REPO, 'aot')):
            dirs[:] = [d for d in dirs
                       if d not in ('__pycache__', 'node_modules')]
            for name in files:
                if name.endswith('.py'):
                    yield os.path.join(root, name)

    def _offenders(self, predicate):
        out = []
        for path in self._python_files():
            rel = os.path.relpath(path, _REPO).replace(os.sep, '/')
            if rel.startswith(self.ALLOWED_CALLERS):
                continue
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except SyntaxError:
                continue
            out.extend(predicate(rel, tree))
        return sorted(out)

    def test_enforcement_stays_inside_the_inventory(self):
        def check(rel, tree):
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Attribute) and
                        func.attr in self.ENFORCING and
                        isinstance(func.value, ast.Name) and
                        func.value.id == 'scope'):
                    yield '{}:{} {}'.format(rel, node.lineno, func.attr)

        self.assertEqual(
            self._offenders(check), [],
            "강제를 늘리는 것은 조용히 일어나면 안 된다. A1b·A2 에서 늘릴 때는 "
            "ALLOWED_CALLERS 에 근거와 함께 적을 것.")

    def test_enforcing_names_are_not_imported_bare(self):
        """`from ...scope import can_operate` 로 이름만 가져오면 위 검사가
        모듈 접두사를 못 본다. 그 우회 경로를 따로 막는다."""
        def check(rel, tree):
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and \
                        node.module.endswith('access.scope'):
                    for alias in node.names:
                        if alias.name in self.ENFORCING:
                            yield '{}:{} {}'.format(rel, node.lineno, alias.name)

        self.assertEqual(self._offenders(check), [])

    def test_gate_checker_reports_clean(self):
        """제어 경로에 **빠진** 게이트가 없어야 한다.

        위 두 검사가 "넘친 곳" 을 보는 것과 반대 방향이다. 둘 다 있어야
        "제어는 전부 막혔고, 그 밖은 안 막혔다" 를 말할 수 있다.
        """
        from aot.scripts.check_scope_gates import inspect
        result, code = inspect()
        self.assertEqual(
            code, 0,
            "스코프를 지나지 않는 제어 경로: {}".format(
                result.get('findings', {}).get('missing-gate')))


if __name__ == '__main__':
    unittest.main()
