# coding=utf-8
"""AI 사용 프로필(ai_user_profile)이 있는 사용자 삭제 회귀 테스트.

## 재현했던 사고 (2026-09-23, NAS 데모 v26.09.06)

설정 › 사용자에서 AI를 한 번이라도 쓴 사용자(예: Kiosk 역할의 `방문객`)를
지우면 `POST /settings/users_submit`(user_delete)이 500으로 죽었다.

    sqlite3.IntegrityError: NOT NULL constraint failed: ai_user_profile.user_id
    [SQL: UPDATE ai_user_profile SET user_id=?, last_active=? WHERE ai_user_profile.id = ?]

`AIUserProfile.user_id`는 `nullable=False`인데, `User` ↔ `AIUserProfile` 사이에
(cascade 없는) `db.relationship(..., backref=...)`가 걸려 있었다. User를 지우면
SQLAlchemy 기본 동작(부모가 사라지면 자식의 FK를 NULL로 떼어내는 것)이 발동해
NOT NULL 제약에 걸려 IntegrityError가 났다. 그리고 그 실패한 세션을
`user_del`(aot/aot_flask/utils/utils_settings.py)이 rollback하지 않고 그대로
반환해, 같은 요청 뒤에 이어지는 `user_has_permission` 조회까지
PendingRollbackError로 연쇄 실패했다.

고친 것:

`aot/databases/models/ai_user_profile.py` — backref에
`cascade='all, delete-orphan'`을 걸어, User가 지워지면 AI 프로필도
같이 지워지게 한다(감사 대상이 아니라 개인화 상태이므로 안전).

`user_del`의 롤백은 이 수정과 별개로 이미 들어 있다(예약 책임자 풀기와 삭제를 한
커밋으로 묶으면서 실패 시 rollback 후 다시 던진다). 아래 세 번째 테스트가 그
안전장치가 계속 지켜지는지 고정한다.
"""
import os
import sys
import unittest.mock as mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


@pytest.fixture()
def app_db(tmp_path):
    """임시 sqlite에 현재 모델 스키마를 세운 앱 컨텍스트."""
    from flask import Flask
    from flask_babel import Babel

    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401 — 모델 등록

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///{}".format(tmp_path / 'del.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Babel(app)  # utils_settings가 import 시 TRANSLATIONS(lazy_gettext)를 평가한다
    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()


def _make_user_with_ai_profile(db, name='visitor', role_id=None):
    from aot.databases.models import User
    from aot.databases.models.ai_user_profile import AIUserProfile

    user = User()
    user.name = name
    user.role_id = role_id
    db.session.add(user)
    db.session.commit()

    profile = AIUserProfile()
    profile.user_id = user.id
    profile.proficiency_level = 'beginner'
    db.session.add(profile)
    db.session.commit()

    return user, profile


def test_deleting_user_cascades_ai_profile(app_db):
    """AI 프로필이 있어도 User.delete()가 IntegrityError 없이 끝나야 한다."""
    from aot.databases.models import User
    from aot.databases.models.ai_user_profile import AIUserProfile

    user, profile = _make_user_with_ai_profile(app_db)
    user_id = user.id
    profile_id = profile.id

    user.delete()  # utils_settings.user_del이 부르는 것과 같은 CRUDMixin.delete()

    assert User.query.get(user_id) is None
    assert AIUserProfile.query.get(profile_id) is None


def test_user_del_succeeds_and_cleans_up_profile(app_db):
    """utils_settings.user_del 경로 전체 — 성공하고 관련 행이 정리된다."""
    from aot.aot_flask.utils import utils_settings
    from aot.databases.models import User
    from aot.databases.models.ai_user_profile import AIUserProfile

    user, profile = _make_user_with_ai_profile(app_db, name='방문객')
    target_unique_id = user.unique_id

    class _Field(object):
        def __init__(self, data):
            self.data = data

    class _Form(object):
        def __init__(self, user_id):
            self.user_id = _Field(user_id)

    fake_current_user = mock.MagicMock()
    fake_current_user.id = -1  # 지우려는 사용자와 절대 같을 수 없는 값

    with mock.patch('aot.aot_flask.utils.utils_settings.flask_login.current_user',
                     fake_current_user):
        messages = utils_settings.user_del(_Form(target_unique_id))

    assert messages["error"] == [], messages["error"]
    assert messages["success"], "성공 메시지가 있어야 한다"

    assert User.query.filter_by(unique_id=target_unique_id).first() is None
    assert AIUserProfile.query.get(profile.id) is None

    # 같은 요청 뒷단(예: user_has_permission)이 죽은 세션 때문에
    # PendingRollbackError로 연쇄 실패하지 않는지 — 정상 쿼리가 그대로 돼야 한다.
    assert User.query.count() == 0


def test_user_del_rolls_back_session_on_failure(app_db):
    """삭제가 실패해도 세션이 rollback돼, 뒤이은 쿼리가 PendingRollbackError로 죽지 않는다.

    cascade 수정이 근본 원인을 없앴더라도, 다른 이유로 삭제가 또 실패할 수
    있으니 이 안전장치는 별도로 지켜야 한다. 삭제는 `db.session.delete` 로 이뤄지므로
    그 호출을 실패시킨다.
    """
    from aot.aot_flask.utils import utils_settings
    from aot.databases.models import User

    user, _profile = _make_user_with_ai_profile(app_db, name='실패유발')
    target_unique_id = user.unique_id

    class _Field(object):
        def __init__(self, data):
            self.data = data

    class _Form(object):
        def __init__(self, user_id):
            self.user_id = _Field(user_id)

    fake_current_user = mock.MagicMock()
    fake_current_user.id = -1

    with mock.patch('aot.aot_flask.utils.utils_settings.flask_login.current_user',
                     fake_current_user), \
         mock.patch.object(app_db.session, 'delete',
                            side_effect=RuntimeError('삭제 실패 시뮬레이션')):
        messages = utils_settings.user_del(_Form(target_unique_id))

    assert messages["error"], "실패는 error 메시지로 드러나야 한다"

    # 세션이 rollback됐으므로 이어지는 조회가 PendingRollbackError 없이 돈다.
    assert User.query.filter_by(unique_id=target_unique_id).first() is not None
