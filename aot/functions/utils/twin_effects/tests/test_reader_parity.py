# coding=utf-8
"""장치 읽기 모듈(`twin_effects.reader`)과 코디네이터 로더(`_reload_profiles`)의 정격 일치 시험 (설계 결정 2 = B).

같은 통합 payload(고정 자료)를 두 길에 넣어 장치마다 면적·풍량·열 정격·분무 유량이 같은지 본다. 로더 코드는 건드리지 않는다 —
로더의 규칙이 바뀌면 이 시험이 깨져 읽기 모듈을 같이 고치게 한다.
"""
import logging
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
# 앱 컨텍스트 밖에서 먼저 import — 번역 문자열을 평가하는 모듈이 딸려 온다.
from aot.space import device_binding as _device_binding  # noqa: F401
from aot.space import facility_integration as FI
from aot.functions.custom_functions.env_coordinator_impl import _profile_loader_mixin as _loader
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import ProfileLoaderMixin
from aot.functions.utils.twin_effects import reader as R

from aot.functions.utils.twin_effects.tests.fixture_integ import FAC, _act, _integ


class _Base(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def loader_profiles(self, integ):
        class Stub(ProfileLoaderMixin):
            def _attach_electric_kw(self): pass
            def _warn_shared_actuators(self, f): pass
            def _apply_pending_commissioning_anchors(self, f): pass

        s = Stub()
        s.logger = logging.getLogger("test_reader_parity")
        s.unique_id = "coord-parity"
        s.geo_facility_id_device_id = FAC
        s.disabled_actuators = ""
        s.bay_scope = ""

        def _no_rows(model, *a, **k):
            q = mock.MagicMock()
            q.all.return_value = []
            q.filter.return_value = q
            return q

        with mock.patch.object(FI, "get_facility_integration", lambda *a, **k: (integ, None)), \
                mock.patch.object(_loader, "db_retrieve_table_daemon", _no_rows):
            s._reload_profiles()
        return {p.actuator_id: p for p in s._profiles}


class TestParity(_Base):
    def _compare(self, integ):
        prof = self.loader_profiles(integ)
        got = R.devices_from_integration(integ)
        by_id = {d.actuator_id: d for d in got.devices}
        self.assertEqual(set(by_id), set(prof))                       # 같은 장치를 본다
        for uid, p in prof.items():
            d = by_id[uid]
            self.assertEqual(d.kind, p.kind, uid)
            self.assertEqual(d.vent_form, p.vent_form, uid)
            self.assertEqual(d.ratings.get("area_m2") or 0.0, p.area_m2 or 0.0, uid)
            cm = p.capacity_meta
            self.assertEqual(d.ratings.get("rated_m3h") or 0.0, cm.get("rated_m3h") or 0.0, uid)
            self.assertEqual(d.ratings.get("rated_kW_thermal") or 0.0, cm.get("rated_kW_thermal") or 0.0, uid)
            self.assertAlmostEqual(d.ratings.get("fog_flow_lpm") or 0.0, cm.get("fog_flow_lpm") or 0.0, places=9,
                                   msg=uid)

    def test_envelope_모드_슬롯_분할(self):
        self._compare(_integ("envelope"))

    def test_fittings_권위_모드는_균등_분할을_하지_않는다(self):
        integ = _integ("fittings")
        self._compare(integ)
        got = {d.actuator_id: d for d in R.devices_from_integration(integ).devices}
        self.assertNotIn("area_m2", got["win-s1"].ratings)            # 모르는 면적을 지어내지 않는다

    def test_정격_출처가_적힌다(self):
        got = R.devices_from_integration(_integ())
        self.assertEqual(got.sources["fan-r"]["rated_m3h"], "device")
        self.assertEqual(got.sources["fan-d"]["rated_m3h"], "default")      # 추정 표시 대상
        self.assertEqual(got.sources["fog"]["fog_flow_lpm"], "geometry")
        self.assertEqual(got.sources["win-g1"]["area_m2"], "geometry")
        self.assertNotIn("rated_kW_thermal", got.sources["heat0"])           # 모름 — 전기 소비량으로 지어내지 않는다


class TestUnreadable(unittest.TestCase):
    def test_종류를_모르는_설비는_미반영_목록으로_남는다(self):
        integ = _integ()
        integ["actuators_resolved"].append(_act("x1", None, None, fitting_kind="mystery"))
        got = R.devices_from_integration(integ)
        self.assertEqual([u["actuator_id"] for u in got.unknown], ["x1"])
        self.assertNotIn("x1", {d.actuator_id for d in got.devices})
        self.assertEqual(got.unknown[0]["fitting_kind"], "mystery")

    def test_rating_view_모름과_추정을_구분한다(self):
        got = R.devices_from_integration(_integ())
        by = {d.actuator_id: d for d in got.devices}
        h0 = {r["key"]: r for r in R.rating_view(by["heat0"], got.sources["heat0"])}
        self.assertEqual(h0["rated_kW_thermal"]["source"], "unknown")
        self.assertIsNone(h0["rated_kW_thermal"]["value"])
        fan = {r["key"]: r for r in R.rating_view(by["fan-d"], got.sources["fan-d"])}
        self.assertEqual((fan["rated_m3h"]["value"], fan["rated_m3h"]["source"]), (3000.0, "default"))


if __name__ == "__main__":
    unittest.main()
