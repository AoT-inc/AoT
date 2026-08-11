# coding=utf-8
"""내부 AI 가 사람 계정을 빌려 쓰지 않는다는 계약의 회귀 테스트.

예전에는 앱 기동 시 "API 키가 없는 첫 번째 Admin/Editor" 를 골라 **그 사람
명의로** 키를 발급하고, 그것을 AoT System Expert Server 의 AOT_MCP_API_KEY 로
넣었다. 두 가지가 무너졌다.

1. 감사 로그의 agent_id 가 'user:<그 사람>' 이 되어, 내부 AI 가 한 일과 그
   사람이 한 일을 구분할 수 없었다. mcp_auth 가 애초에 없애려던 문제(신원
   자기신고)가 형태만 바꿔 되살아난 셈이다. 로컬 DB 에서 실제로 내부 AI 가
   사람 계정 'koat' 명의로 돌고 있었다(2026-08-11 확인).
2. User.api_key_hash 는 컬럼 하나뿐이라 1인 1키다. 그 사람이 나중에 설정
   화면에서 자기 키를 재발급하면 덮어써지고, 내부 AI 는 아무 에러 없이 도구를
   전부 잃었다.

지키는 계약은 넷이다.
  - 서비스 계정은 auth_provider 로 식별한다(이름이 아니다 — 사람이 같은 이름을
    먼저 차지했을 수 있고, 그 계정을 서비스 계정으로 오인하면 남의 계정에 키를
    발급하게 된다).
  - 이미 있으면 다시 만들지 않는다(멱등).
  - 만들 때 로그인 수단을 하나도 주지 않는다(password_hash/code/email 이 전부
    None 이어야 세 로그인 경로가 모두 막힌다).
  - 최소 권한 — 쓰기 도구에 필요한 edit_controllers 만 받고 edit_users 는 받지
    않는다.

마지막으로 app.py 가 옛 방식(사람 고르기)으로 되돌아가지 않았는지 소스에서
확인한다. 이 되돌림은 실행해 보기 전에는 티가 나지 않는다 — 사람 계정으로도
인증은 멀쩡히 되기 때문이다.
"""
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.ai.services import mcp_auth


def _role(name='Editor', role_id=2, edit_controllers=True, edit_users=False):
    role = MagicMock()
    role.id = role_id
    role.name = name
    role.edit_controllers = edit_controllers
    role.edit_users = edit_users
    return role


class ServiceAccountTest(unittest.TestCase):

    def _run(self, existing_system=None, name_taken=False, role=None):
        """ensure_service_account() 를 DB 없이 돌리고 (결과, db) 를 돌려준다."""
        user_cls = MagicMock()
        role_cls = MagicMock()
        db = MagicMock()

        # 첫 filter().first() 는 서비스 계정 조회, 두 번째는 이름 충돌 확인.
        user_cls.query.filter.return_value.first.side_effect = [
            existing_system, MagicMock() if name_taken else None]
        # User() 로 새로 만드는 인스턴스는 속성 대입을 그대로 기억한다.
        created = MagicMock()
        user_cls.return_value = created

        chain = role_cls.query.filter.return_value
        chain.filter.return_value.order_by.return_value.first.return_value = role
        chain.order_by.return_value.first.return_value = role

        models = MagicMock(User=user_cls, Role=role_cls)
        with patch.dict(sys.modules, {
                'aot.databases.models': models,
                'aot.aot_flask.extensions': MagicMock(db=db)}):
            result = mcp_auth.ensure_service_account()
        return result, created, db

    def test_identified_by_provider_not_name(self):
        """식별 기준은 auth_provider 여야 한다 — 이름이 아니다."""
        self.assertEqual(mcp_auth.SERVICE_ACCOUNT_PROVIDER, 'system')

    def test_existing_account_is_reused(self):
        """이미 있으면 다시 만들지 않는다(기동마다 계정이 늘면 안 된다)."""
        existing = MagicMock()
        result, _created, db = self._run(existing_system=existing)
        self.assertIs(result, existing)
        db.session.add.assert_not_called()
        db.session.commit.assert_not_called()

    def test_created_account_cannot_log_in(self):
        """로그인 수단을 하나도 주지 않는다.

        password_hash 가 있으면 비밀번호 로그인이, code 가 있으면 키패드
        로그인이, email 이 있으면 Google 로그인이 열린다.
        """
        _result, created, db = self._run(role=_role())
        db.session.add.assert_called_once()
        self.assertIsNone(created.password_hash)
        self.assertIsNone(created.code)
        self.assertIsNone(created.email)
        self.assertEqual(created.auth_provider, 'system')
        # find_by_api_key 가 꺼진 계정의 키를 거부하므로 켜져 있어야 한다.
        self.assertTrue(created.is_enabled)

    def test_least_privilege_role(self):
        """쓰기에 필요한 권한만 받는다 — 사용자 관리 권한은 받지 않는다."""
        editor = _role(name='Editor', role_id=2)
        _result, created, _db = self._run(role=editor)
        self.assertEqual(created.role_id, editor.id)
        self.assertTrue(editor.edit_controllers)
        self.assertFalse(editor.edit_users)

    def test_no_role_means_no_account(self):
        """붙일 역할이 없으면 계정을 만들지 않고 None 을 돌려준다."""
        result, _created, db = self._run(role=None)
        self.assertIsNone(result)
        db.session.add.assert_not_called()

    def test_name_collision_is_avoided(self):
        """사람이 같은 이름을 쓰고 있으면 비켜 간다(User.name 은 unique)."""
        _result, created, _db = self._run(role=_role(), name_taken=True)
        self.assertNotEqual(created.name, mcp_auth.SERVICE_ACCOUNT_NAME)
        self.assertTrue(created.name.startswith(mcp_auth.SERVICE_ACCOUNT_NAME))


class StartupWiringTest(unittest.TestCase):
    """app.py 가 옛 '사람 빌려 쓰기' 방식으로 되돌아가지 않았는지 본다."""

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), '..',
                            'aot_flask', 'app.py')
        with open(path, encoding='utf-8') as handle:
            self.source = handle.read()

    def test_uses_service_account(self):
        self.assertIn('ensure_service_account', self.source)

    def test_does_not_pick_a_human_user(self):
        """옛 선택자가 남아 있으면 실패한다.

        'API 키가 없는 사용자를 고른다' 는 이 필터가 사람 계정을 집어오던
        장본인이다. 되살아나도 인증은 멀쩡히 되므로 실행 중에는 티가 나지 않는다.
        """
        self.assertNotRegex(
            self.source,
            re.compile(r'filter\(\s*User\.api_key_hash\.is_\(None\)\s*\)'))


if __name__ == '__main__':
    unittest.main()
