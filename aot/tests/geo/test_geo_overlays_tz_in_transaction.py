# coding=utf-8
"""geo_overlays 의 tz 물질화·부모 변경이 아직 커밋되지 않은 구간에서 timekit 이 새 값을 보는가.

배경: `timekit.tz_of(id)` → `_place_tz` → `_db_first`/`_db_row` 는 별도 DB 세션
(`session_scope(AOT_DB_PATH)`)으로 읽는다. Flask 요청 안의 `db.session` 이 flush 만 한
변경은 그 세션에서 보이지 않는다. 반면 행을 직접 넘기는 `tz_of(row)` 는 그 행(세션 객체)의
속성을 읽는다. 이 파일은 그 경계를 시험으로 고정한다.

`materialize_timezones` 는 커밋 직후 별도 트랜잭션으로 돌고 그 안에서 timekit 을 부르지
않는다(`GeoShape.resolve_timezone` 의 세션 경로를 쓴다). 따라서 실제 호출 경로에서 커밋 전에
`tz_of(id)` 를 부르는 곳은 없다 — 아래 `Uncommitted*` 시험은 그 한계를 문서화한다.
"""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoBinding, GeoMap, GeoShape, Input
from aot.utils import timekit

MAP = 'gtz-map-1'
SITE = 'gtz-site-1'
ZONE = 'gtz-zone-1'
DEV = 'gtz-input-1'
DEV_SHAPE = 'gtz-devshape-1'


def _make_app():
    from aot.config import AOT_DB_PATH
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 't'
    db.init_app(app)
    return app


def _poly():
    return {'type': 'Feature', 'properties': {},
            'geometry': {'type': 'Polygon',
                         'coordinates': [[[127.0, 37.0], [127.0, 37.1], [127.1, 37.1],
                                          [127.0, 37.0]]]}}


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self._clean()
        db.session.add(GeoMap(unique_id=MAP, name='M', category='design'))
        site = GeoShape(unique_id=SITE, geo_id=MAP, type='site', feature=_poly(),
                        timezone='Asia/Seoul', tz_source='explicit')
        db.session.add(site)
        db.session.flush()
        zone = GeoShape(unique_id=ZONE, geo_id=MAP, type='zone', feature=_poly(),
                        parent_id=site.id)
        db.session.add(zone)
        db.session.flush()
        dev_shape = GeoShape(unique_id=DEV_SHAPE, geo_id=MAP, type='device',
                             feature=_poly(), parent_id=zone.id, )
        db.session.add(dev_shape)
        db.session.add(Input(unique_id=DEV, name='S1'))
        db.session.add(GeoBinding(
            spatial_kind='shape', spatial_id=DEV_SHAPE, role='area',
            device_kind='input', device_id=DEV, channel_id='0'))
        db.session.commit()
        self.site_id, self.zone_id = site.id, zone.id

    def tearDown(self):
        db.session.rollback()
        self._clean()
        self.ctx.pop()

    def _clean(self):
        GeoBinding.query.filter(GeoBinding.device_id == DEV).delete(synchronize_session=False)
        GeoShape.query.filter(GeoShape.geo_id == MAP).delete(synchronize_session=False)
        Input.query.filter(Input.unique_id == DEV).delete(synchronize_session=False)
        GeoMap.query.filter(GeoMap.unique_id == MAP).delete(synchronize_session=False)
        db.session.commit()

    def _site(self):
        return GeoShape.query.filter_by(unique_id=SITE).first()


class CommittedVisibility(_Base):
    """커밋 뒤에는 id 로 풀어도 새 값이다(materialize_timezones 이후의 실제 경로)."""

    def test_site_change_visible_to_children_after_commit(self):
        self._site().timezone = 'America/New_York'
        db.session.commit()
        self.assertEqual(str(timekit.tz_of(SITE)), 'America/New_York')
        self.assertEqual(str(timekit.tz_of(ZONE)), 'America/New_York')
        self.assertEqual(str(timekit.tz_of(DEV_SHAPE)), 'America/New_York')
        self.assertEqual(str(timekit.tz_of(DEV)), 'America/New_York')

    def test_reparent_visible_after_commit(self):
        other = GeoShape(unique_id='gtz-site-2', geo_id=MAP, type='site', feature=_poly(),
                         timezone='Europe/London', tz_source='explicit')
        db.session.add(other)
        db.session.flush()
        zone = GeoShape.query.filter_by(unique_id=ZONE).first()
        zone.parent_id = other.id
        db.session.commit()
        self.assertEqual(str(timekit.tz_of(ZONE)), 'Europe/London')
        self.assertEqual(str(timekit.tz_of(DEV)), 'Europe/London')


class UncommittedByRow(_Base):
    """커밋 전: 행 객체를 넘기면 세션의 새 값을 읽는다(자식 체인은 별도 세션이라 옛 값)."""

    def test_row_itself_sees_uncommitted_value(self):
        site = self._site()
        site.timezone = 'America/New_York'
        db.session.flush()
        self.assertEqual(str(timekit.tz_of(site)), 'America/New_York')
        self.assertEqual(str(site.resolve_timezone()), 'America/New_York')

    def test_session_path_sees_uncommitted_parent_for_children(self):
        """Flask 안의 resolve_timezone(세션 경로)은 미커밋 부모 변경을 본다."""
        site = self._site()
        site.timezone = 'America/New_York'
        db.session.flush()
        zone = GeoShape.query.filter_by(unique_id=ZONE).first()
        zone.timezone = None
        self.assertEqual(str(zone.resolve_timezone()), 'America/New_York')


class UncommittedById(_Base):
    """커밋 전 `tz_of(id)` — **알려진 한계**: 별도 세션이라 flush 만 한 변경을 못 본다.

    실제 geo_overlays 흐름에는 이 호출이 없다(물질화는 커밋 뒤 별도 트랜잭션이고 안에서
    timekit 을 부르지 않는다). 새 코드가 같은 트랜잭션에서 id 로 풀려면 먼저 커밋하거나 행을
    넘겨야 한다. 고치면(Flask 컨텍스트에서 세션 경로로 읽기) 아래 시험이 XPASS 로 바뀐다.
    문서: ARCHITECTURE.md §6 Time, docs/design/timezone-management.md §9(같은 트랜잭션의 미커밋 변경).
    """

    @unittest.expectedFailure
    def test_id_lookup_sees_flushed_site_change(self):
        site = self._site()
        site.timezone = 'America/New_York'
        db.session.flush()
        self.assertEqual(str(timekit.tz_of(SITE)), 'America/New_York')

    @unittest.expectedFailure
    def test_id_lookup_sees_flushed_descendants(self):
        site = self._site()
        site.timezone = 'America/New_York'
        db.session.flush()
        for target in (ZONE, DEV_SHAPE, DEV):
            with self.subTest(target=target):
                self.assertEqual(str(timekit.tz_of(target)), 'America/New_York')

    @unittest.expectedFailure
    def test_id_lookup_sees_flushed_reparent(self):
        other = GeoShape(unique_id='gtz-site-2', geo_id=MAP, type='site', feature=_poly(),
                         timezone='Europe/London', tz_source='explicit')
        db.session.add(other)
        db.session.flush()
        zone = GeoShape.query.filter_by(unique_id=ZONE).first()
        zone.parent_id = other.id
        db.session.flush()
        self.assertEqual(str(timekit.tz_of(ZONE)), 'Europe/London')


class DaemonPath(_Base):
    """앱 컨텍스트 없는 경로: 커밋된 값만 본다(별도 세션이므로 정상)."""

    def test_daemon_sees_committed_value(self):
        self._site().timezone = 'America/New_York'
        db.session.commit()
        self.ctx.pop()
        try:
            self.assertEqual(str(timekit.tz_of(DEV)), 'America/New_York')
        finally:
            self.ctx.push()


if __name__ == '__main__':
    unittest.main()
