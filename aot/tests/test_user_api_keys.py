# coding=utf-8
"""사용자별 API 키(1인 다중 키 + 스코프)의 회귀 테스트.

예전에는 키가 `users.api_key_hash` 컬럼 **하나**였다. 그래서:

  - 한 사람이 ChatGPT 와 Claude 에 동시에 붙을 수 없었다. 두 번째를 발급하면
    첫 번째가 아무 에러 없이 죽는다(재발급 = 덮어쓰기).
  - 유출이 의심돼도 그 키만 끊을 수 없어, 끊으면 그 사람의 모든 연동이 끊긴다.
  - 키 하나가 곧 **그 계정의 전 권한**이었다. 데이터를 받아가기만 하는 상대에게도
    장치 제어권을 함께 넘겨야 했다.

`user_api_key` 테이블(p6_32)과 `scope` 컬럼(p6_33)이 그 셋을 각각 푼다.
여기서 지키는 계약은 다섯이다.

1. 폐기된 키로는 아무도 인증되지 않는다.
2. 꺼진 계정의 키로는 아무도 인증되지 않는다(키가 살아 있어도).
3. 레거시 컬럼 폴백은 아직 살아 있다 — 백필이 돌지 않은 서버가 있기 때문이고,
   이 폴백을 지우는 것은 배포 후 확인을 거친 뒤의 일이다.
4. 레거시 키의 스코프는 'full' 이다. 업그레이드가 돌던 연동을 조용히 읽기
   전용으로 바꾸면 안 된다.
5. **모르는 스코프 값은 'full' 이 아니라 'readonly' 로 좁힌다.** 오타 하나가
   조용히 전 권한 키를 만드는 쪽이 훨씬 위험하다.

스코프 가드(HTTP 메서드 차단) 자체는 app.py 에 있고 브라우저로 실증했다.
여기서는 그 가드가 의존하는 판정(`is_readonly`)과 발급 규칙을 고정한다.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.databases.models.user_api_key import (SCOPE_FULL, SCOPE_READONLY,
                                               SCOPES, UserAPIKey)


class ScopeVocabularyTest(unittest.TestCase):

    def test_scope_values(self):
        self.assertEqual(SCOPE_FULL, 'full')
        self.assertEqual(SCOPE_READONLY, 'readonly')
        self.assertIn(SCOPE_FULL, SCOPES)
        self.assertIn(SCOPE_READONLY, SCOPES)

    def test_is_readonly_only_for_readonly(self):
        row = UserAPIKey()
        row.scope = SCOPE_FULL
        self.assertFalse(row.is_readonly)
        row.scope = SCOPE_READONLY
        self.assertTrue(row.is_readonly)

    def test_unknown_scope_is_not_treated_as_readonly(self):
        """모르는 값을 readonly 로 읽으면 안 된다 — 그건 발급 단계에서 막는다.

        읽는 쪽이 관대하면(모르는 값 = readonly) 스코프 컬럼이 손상됐을 때
        멀쩡한 연동이 조용히 읽기 전용이 된다. 좁히는 판단은 발급 한 곳에서만
        한다(아래 IssueScopeTest).
        """
        row = UserAPIKey()
        row.scope = 'nonsense'
        self.assertFalse(row.is_readonly)


class IssueScopeTest(unittest.TestCase):
    """User.issue_api_key 의 스코프 결정 규칙."""

    def _issue(self, scope_arg):
        from aot.databases.models.user import User

        created = {}

        class _Row(object):
            def __setattr__(self, key, value):
                created[key] = value

        with patch.dict(sys.modules, {
                'aot.databases.models.user_api_key': MagicMock(
                    SCOPE_FULL=SCOPE_FULL, SCOPE_READONLY=SCOPE_READONLY,
                    SCOPES=SCOPES, UserAPIKey=_Row)}), \
                patch('aot.databases.models.user.db') as db:
            user = User()
            user.id = 1
            user.issue_api_key('테스트', scope_arg)
            db.session.add.assert_called_once()
        return created

    def test_default_is_full(self):
        """스코프를 안 주면 예전과 같이 전 권한이다."""
        self.assertEqual(self._issue(None)['scope'], SCOPE_FULL)

    def test_explicit_values_are_kept(self):
        self.assertEqual(self._issue(SCOPE_FULL)['scope'], SCOPE_FULL)
        self.assertEqual(self._issue(SCOPE_READONLY)['scope'], SCOPE_READONLY)

    def test_unknown_value_narrows_to_readonly(self):
        """오타가 전 권한 키를 만들면 안 된다 — 좁은 쪽으로 떨어뜨린다."""
        self.assertEqual(self._issue('readonyl')['scope'], SCOPE_READONLY)
        self.assertEqual(self._issue('admin')['scope'], SCOPE_READONLY)


@pytest.fixture()
def app_db(tmp_path):
    """임시 sqlite 에 현재 모델 스키마를 세운 앱 컨텍스트.

    리졸버는 두 테이블을 실제로 질의하므로(새 키 테이블 → 레거시 컬럼) 목으로
    흉내 내면 정작 지켜야 할 질의 자체가 검증되지 않는다.
    """
    from flask import Flask

    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401  — 모델 등록

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///{}".format(tmp_path / 'keys.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()


def _make_user(db, name='tester', enabled=True):
    from aot.databases.models import User

    user = User()
    user.name = name
    user.is_enabled = enabled
    db.session.add(user)
    db.session.commit()
    return user


def test_one_user_can_hold_several_working_keys(app_db):
    """예전 구조에서 불가능했던 것 — 두 번째 발급이 첫 번째를 죽이지 않는다."""
    from aot.databases.models import User

    user = _make_user(app_db)
    first = user.issue_api_key('ChatGPT')
    second = user.issue_api_key('Claude Desktop')
    app_db.session.commit()

    self_first, row_first = User.resolve_api_key(first)
    self_second, row_second = User.resolve_api_key(second)
    assert self_first is user and self_second is user
    assert row_first.name == 'ChatGPT'
    assert row_second.name == 'Claude Desktop'
    assert len(user.active_api_keys()) == 2


def test_revoking_one_key_leaves_the_others_working(app_db):
    """유출이 의심되는 연동 하나만 끊을 수 있어야 한다."""
    from aot.databases.models import User, UserAPIKey

    user = _make_user(app_db)
    doomed = user.issue_api_key('leaked')
    kept = user.issue_api_key('fine')
    app_db.session.commit()

    UserAPIKey.query.filter_by(
        key_hash=User.hash_api_key(doomed)).first().revoke()
    app_db.session.commit()

    assert User.resolve_api_key(doomed) == (None, None)
    assert User.resolve_api_key(kept)[0] is user
    assert len(user.active_api_keys()) == 1


def test_disabled_account_keys_stop_working(app_db):
    """계정을 끄면 그 사람의 키도 함께 죽어야 한다."""
    from aot.databases.models import User

    user = _make_user(app_db)
    key = user.issue_api_key('any')
    app_db.session.commit()
    assert User.resolve_api_key(key)[0] is user

    user.is_enabled = False
    app_db.session.commit()
    assert User.resolve_api_key(key) == (None, None)


def test_legacy_column_is_still_honoured(app_db):
    """백필이 돌지 않은 서버를 위한 폴백.

    이 폴백을 지우는 것은 배포한 서버에서 폴백이 0 인 것을 확인한 뒤의 일이다.
    지금 지우면 그런 서버의 모든 API 연동이 즉시 끊긴다.
    """
    from aot.databases.models import User

    user = _make_user(app_db)
    raw = b'legacy-raw-key'
    user.api_key_hash = User.hash_api_key(raw)
    app_db.session.commit()

    found, row = User.resolve_api_key(raw)
    assert found is user
    assert row is None, "레거시 키는 키 행이 없다 — 스코프는 full 로 취급된다"


def test_issued_keys_default_to_full_scope(app_db):
    """업그레이드가 돌던 연동을 조용히 읽기 전용으로 바꾸면 안 된다."""
    from aot.databases.models import User

    user = _make_user(app_db)
    raw = user.issue_api_key('no scope given')
    app_db.session.commit()
    assert User.resolve_api_key(raw)[1].scope == SCOPE_FULL


def test_readonly_key_is_marked_readonly(app_db):
    from aot.databases.models import User

    user = _make_user(app_db)
    raw = user.issue_api_key('collector', SCOPE_READONLY)
    app_db.session.commit()
    row = User.resolve_api_key(raw)[1]
    assert row.scope == SCOPE_READONLY
    assert row.is_readonly is True


def test_find_active_matches_the_resolver(app_db):
    """가드가 쓰는 조회와 로그인이 쓰는 조회가 어긋나면 스코프가 새어 나간다."""
    from aot.databases.models import User, UserAPIKey

    user = _make_user(app_db)
    raw = user.issue_api_key('probe', SCOPE_READONLY)
    app_db.session.commit()

    assert UserAPIKey.find_active(raw).is_readonly is True
    UserAPIKey.find_active(raw).revoke()
    app_db.session.commit()
    assert UserAPIKey.find_active(raw) is None
    assert User.resolve_api_key(raw) == (None, None)


def test_empty_key_resolves_to_nothing(app_db):
    from aot.databases.models import User, UserAPIKey

    assert User.resolve_api_key(b'') == (None, None)
    assert User.resolve_api_key(None) == (None, None)
    assert UserAPIKey.find_active(b'') is None


# ---------------------------------------------------------------------------
# 스코프가 MCP 판정까지 도달하는가
#
# 메인 앱은 HTTP 메서드로 거르는 가드(app.py)가 있지만, MCP 는 도구 호출이 전부
# `POST /mcp` 한 경로라 메서드로 구분되지 않는다. 그래서 스코프는 역할 판정
# (`_role_for`)에 얹혀야 하고, 그게 끊기면 읽기 전용 키로 쓰기 도구가 전부
# 열린다 — 실제로 그랬다(2026-08-11 실측: readonly 키인데 can_write=True).
# ---------------------------------------------------------------------------

def _write_capable_role(db, name='Editor'):
    from aot.databases.models import Role

    role = Role()
    role.name = name
    role.edit_controllers = True     # 쓰기 도구를 쓸 수 있는 역할
    role.edit_users = False
    db.session.add(role)
    db.session.commit()
    return role


def test_readonly_key_turns_off_write_even_for_a_write_capable_role(app_db):
    """스코프는 역할 **위에** 얹히는 제한이다 — 좁은 쪽이 이겨야 한다."""
    from aot.ai.services import mcp_auth
    from aot.databases.models import User

    role = _write_capable_role(app_db)
    user = _make_user(app_db)
    user.role_id = role.id
    app_db.session.commit()

    readonly = user.issue_api_key('collector', SCOPE_READONLY)
    full = user.issue_api_key('operator', SCOPE_FULL)
    app_db.session.commit()

    _u, ro_row = User.resolve_api_key(readonly)
    _u, full_row = User.resolve_api_key(full)

    assert mcp_auth.role_can_write(mcp_auth._role_for(user, ro_row)) is False
    assert mcp_auth.role_can_write(mcp_auth._role_for(user, full_row)) is True
    # 역할 자체는 그대로다 — 끄는 것은 이 연결의 쓰기 권한뿐이다.
    assert mcp_auth._role_for(user, ro_row).name == 'Editor'


def test_legacy_key_keeps_write_access(app_db):
    """키 행이 없는(레거시) 키는 예전처럼 역할 그대로 동작해야 한다."""
    from aot.ai.services import mcp_auth
    from aot.databases.models import User

    role = _write_capable_role(app_db)
    user = _make_user(app_db)
    user.role_id = role.id
    user.api_key_hash = User.hash_api_key(b'legacy-raw')
    app_db.session.commit()

    _u, row = User.resolve_api_key(b'legacy-raw')
    assert row is None
    assert mcp_auth.role_can_write(mcp_auth._role_for(user, row)) is True


def test_readonly_cannot_be_widened_by_a_read_only_role(app_db):
    """읽기 전용 역할 + 전체 권한 키 = 여전히 쓰기 불가(역할이 좁은 쪽)."""
    from aot.ai.services import mcp_auth
    from aot.databases.models import Role, User

    role = Role()
    role.name = 'Monitor'
    role.edit_controllers = False
    role.edit_users = False
    app_db.session.add(role)
    app_db.session.commit()

    user = _make_user(app_db)
    user.role_id = role.id
    app_db.session.commit()
    full = user.issue_api_key('operator', SCOPE_FULL)
    app_db.session.commit()

    _u, row = User.resolve_api_key(full)
    assert mcp_auth.role_can_write(mcp_auth._role_for(user, row)) is False
