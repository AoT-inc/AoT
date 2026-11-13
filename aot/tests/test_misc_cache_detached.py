"""get_misc_cached 가 돌려주는 Misc 는 요청 간 캐시다 — 뒤 commit·세션 종료 뒤에도 읽혀야 한다.

main 회귀(#555 뒤): GeoSetting 기본 좌표가 None 이면 지도 위젯이 misc.map_latitude 를 읽는데,
캐시된 인스턴스가 세션에 붙어 있어 commit 으로 만료된 뒤 DetachedInstanceError 가 났다
(전체 스위트에서만 test_screen_follow_v2·test_web_presence 가 실패)."""
import unittest


class MiscCacheDetachedTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        from aot.aot_flask.app import create_app
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def test_cached_misc_survives_commit_and_session_close(self):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.utils import utils_geo
        from aot.databases.models import Misc
        if Misc.query.first() is None:          # 시험 DB 에는 행이 없을 수 있다
            db.session.add(Misc())
            db.session.commit()
        utils_geo.invalidate_misc_cache()
        misc = utils_geo.get_misc_cached()
        self.assertIsNotNone(misc)
        db.session.commit()      # 같은 요청의 뒤 commit — 붙어 있었다면 속성이 만료된다
        db.session.remove()      # 요청 종료
        again = utils_geo.get_misc_cached()
        self.assertIs(misc, again)
        _ = (again.map_latitude, again.map_longitude, again.custom_theme_json)  # 예외 없어야 한다
        utils_geo.invalidate_misc_cache()
