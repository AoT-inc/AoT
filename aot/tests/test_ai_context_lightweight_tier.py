# coding=utf-8
"""`AIContextService.get_master_context(tier='lightweight')` 회귀 고정.

무엇이 문제였나 (2026-09-18 발견). `get_master_context` 는 함수 상단(모듈
레벨, 15행)에서 이미 `from flask_login import current_user` 를 해 뒀는데,
`tier != 'lightweight'` 로 가드된 "Phase 2: Inject Context Metadata" 블록
안에서 **같은 이름을 다시 import** 하고 있었다. 파이썬은 함수 안 어딘가에
대입(import 포함)이 있으면 그 이름을 함수 **전체**에서 지역변수로 취급한다
— 그 블록이 실행되든 말든 상관없다. lightweight 티어는 정확히 그 블록을
건너뛰므로, 뒤쪽 "User Profile Injection" 의 `if current_user and ...` 에서
`UnboundLocalError: local variable 'current_user' referenced before
assignment` 로 죽었다. `get_master_context` 는 모든 예외를 삼켜
`{"error": str(e)}` 한 줄만 돌려주므로, lightweight 로 요청하는 모든 AI
호출이 컨텍스트 없이 돌고 있었다.

같은 자리에서 두 번째 문제도 나왔다: lightweight 는 `exclude_for_slim`
목록에 `available_api_keys` 를 강제 제외로 올려뒀는데, 그 키를 실제로 채우는
블록이 `should_include()` 를 거치지 않고 무조건 넣고 있어 제외가 먹지 않았다.

DB 는 임시 sqlite(모델에서 직접 스키마 생성)만 쓰고 라이브를 건드리지 않는다.
"""
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ.setdefault("ALEMBIC_RUNNING", "1")


class TestLightweightTierDoesNotCrash(unittest.TestCase):
    """임시 sqlite DB 만 쓰고 라이브를 건드리지 않는다."""

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from aot.aot_flask.extensions import db, cache
        import aot.databases.models  # noqa: F401 — 모델 등록

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'ai_context_lightweight.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        # get_master_context 가 CacheManager(flask_caching) 를 거친다 — 앱
        # 확장이 없으면 KeyError('cache') 로 죽는다. 파일 캐시는 임시 디렉터리로.
        app.config['CACHE_TYPE'] = 'SimpleCache'
        cache.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _assert_not_error_payload(self, ctx, tier):
        self.assertIsInstance(ctx, dict, '%s 티어 결과가 dict 가 아니다' % tier)
        is_swallowed_error = set(ctx.keys()) == {'error'}
        self.assertFalse(
            is_swallowed_error,
            '%s 티어가 예외를 삼키고 에러 페이로드만 반환했다: %s' % (tier, ctx)
        )

    def test_lightweight_tier_returns_real_context_not_swallowed_error(self):
        """회귀의 핵심: lightweight 가 UnboundLocalError 를 삼켜
        `{"error": "local variable 'current_user' referenced before
        assignment"}` 한 줄만 돌려주던 상태로 되돌아가지 않는다."""
        from aot.ai.services.ai_context_service import AIContextService
        ctx = AIContextService.get_master_context(tier='lightweight')
        self._assert_not_error_payload(ctx, 'lightweight')

    def test_standard_and_heavy_tiers_also_survive_the_current_user_block(self):
        """중복 import 를 지우면서 Phase 2 블록(정상 경로)이 깨지지 않았는지
        함께 고정한다 — 이 블록은 lightweight 가 건너뛰던 바로 그 코드다."""
        from aot.ai.services.ai_context_service import AIContextService
        for tier in ('standard', 'heavy'):
            ctx = AIContextService.get_master_context(tier=tier)
            self._assert_not_error_payload(ctx, tier)

    def test_lightweight_excludes_available_api_keys_even_when_present(self):
        """`exclude_for_slim` 에 이미 올라 있던 `available_api_keys` 가 실제로도
        빠지는지 고정한다 — 채우는 블록이 `should_include()` 를 거치지 않아
        제외가 안 먹던 두 번째 버그."""
        from aot.databases.models import APIKey
        from aot.ai.services.ai_context_service import AIContextService

        APIKey(name='테스트 키', provider='test_provider', tag='weather').save()
        try:
            lightweight_ctx = AIContextService.get_master_context(tier='lightweight')
            standard_ctx = AIContextService.get_master_context(tier='standard')
        finally:
            APIKey.query.delete()
            from aot.aot_flask.extensions import db
            db.session.commit()

        self.assertNotIn('available_api_keys', lightweight_ctx)
        self.assertIn('available_api_keys', standard_ctx)


if __name__ == '__main__':
    unittest.main()
