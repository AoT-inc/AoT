# coding=utf-8
"""대지 기상대 지정 — `set_site_weather` + 후보 목록 + 화면 배선.

일사·강우는 대지에 하나 있는 기상대가 재고 구획마다 따로 재지 않는다. 그래서
구획 화면이 그 값을 보려면 대지의 기상대를 알아야 하는데, 지금까지는 **측정값
이름으로 추론**했다(`WEATHER_MARKER_MEASUREMENTS`). 추론은 아무도 설정을
만지지 않은 설치에서도 값이 보이게 하는 안전망이지 정답이 아니다 — 대지에
일사계가 둘이거나 실험용 센서가 섞이면 사람이 바로잡을 수단이 없었다.

여기서 지키는 것은 넷이다.

1. **지정이 추론을 이긴다.** 그리고 지정을 지우면 **추론으로 되돌아간다** —
   비활성이 아니다. 되돌아가지 않으면 "해제했더니 값이 통째로 사라졌다" 가
   되고, 사람은 그 화면을 다시는 만지지 않는다.
2. **`rebind()` 를 쓰지 않는다.** `weather` 는 다중 점유라 rebind 는 같은
   role 의 다른 장치까지 함께 종료시킨다 — 기상대 둘을 등록한 설치에서 한
   대를 더하는 것만으로 다른 한 대가 조용히 사라진다.
3. **이력을 지우지 않는다.** 해제는 행 삭제가 아니라 `valid_to` 다(B3).
4. **출력은 후보가 아니다.** 밸브·난방기도 가동시간을 측정값으로 갖고 있어,
   거르지 않으면 목록을 통째로 덮는다(실측: 19대 중 18대가 밸브).
"""
import ast
import io
import os
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding as B
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import GeoBinding, Input, Output

SITE = 'site-uuid-0001'
STATION = 'dev-station-01'
OTHER = 'dev-other-002'

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..', '..'))
_WIDGET_JS = os.path.join(
    _ROOT, 'aot', 'aot_flask', 'static', 'js', 'widgets', 'AoT_map',
    'aot-map-widget-vector.js')
_MEMBERSHIP_PY = os.path.join(
    _ROOT, 'aot', 'aot_flask', 'geo', 'device_membership.py')
_ROUTES_PY = os.path.join(_ROOT, 'aot', 'aot_flask', 'routes_geo.py')


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


class _Base(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        B.reset_fallback_log()
        Input(unique_id=STATION, name='기상대').save()
        Input(unique_id=OTHER, name='온습도').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _current(self):
        return sorted(b.device_id for b in
                      B.current('weather', SITE, role=B.SITE_WEATHER_ROLE))


class TestSetSiteWeather(_Base):

    def test_designation_creates_current_bindings(self):
        created, ended = B.set_site_weather(SITE, [STATION], commit=True)
        self.assertEqual((created, ended), (1, 0))
        self.assertEqual(self._current(), [STATION])

    def test_repeating_the_same_list_changes_nothing(self):
        """멱등이 아니면 저장을 두 번 누르는 것만으로 이력이 부풀고,
        나중에 "언제 바꿨나" 를 읽을 수 없게 된다."""
        B.set_site_weather(SITE, [STATION], commit=True)
        self.assertEqual(B.set_site_weather(SITE, [STATION], commit=True),
                         (0, 0))
        self.assertEqual(self._current(), [STATION])

    def test_adding_one_does_not_drop_the_other(self):
        """`weather` 는 다중 점유다. rebind 로 구현하면 여기서 깨진다 —
        한 대를 더했을 뿐인데 먼저 있던 기상대가 함께 종료된다."""
        B.set_site_weather(SITE, [STATION], commit=True)
        B.set_site_weather(SITE, [STATION, OTHER], commit=True)
        self.assertEqual(self._current(), sorted([STATION, OTHER]))

    def test_clearing_ends_everything(self):
        B.set_site_weather(SITE, [STATION], commit=True)
        created, ended = B.set_site_weather(SITE, [], commit=True)
        self.assertEqual((created, ended), (0, 1))
        self.assertEqual(self._current(), [])

    def test_history_survives_a_clear(self):
        """행을 지우면 시계열 접합의 근거가 사라진다(B3)."""
        B.set_site_weather(SITE, [STATION], commit=True)
        B.set_site_weather(SITE, [], commit=True)
        rows = GeoBinding.query.filter_by(
            spatial_kind='weather', spatial_id=SITE).all()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0].valid_to)
        self.assertEqual(rows[0].ended_reason, 'unbound')

    def test_nonexistent_device_is_not_promoted(self):
        """죽은 참조를 승격시키면 고아가 정본이 된다(백필과 같은 규칙)."""
        created, _ = B.set_site_weather(SITE, ['ghost-0000'], commit=True)
        self.assertEqual(created, 0)
        self.assertEqual(self._current(), [])

    def test_missing_shape_uuid_is_refused(self):
        with self.assertRaises(B.BindingError):
            B.set_site_weather('', [STATION])


class TestDesignationBeatsInference(_Base):

    def test_source_flips_to_bound_and_back(self):
        from aot.aot_flask.geo import device_membership as DM
        self.assertEqual(DM.weather_device_ids(SITE)[1], 'none')
        B.set_site_weather(SITE, [STATION], commit=True)
        ids, src = DM.weather_device_ids(SITE)
        self.assertEqual((ids, src), ([STATION], 'bound'))
        # ⚠ 해제는 비활성이 아니라 **지정 전** 이다. 'none' 으로 굳으면
        #   실외 값이 통째로 사라지고, 그 화면은 아무도 다시 안 만진다.
        B.set_site_weather(SITE, [], commit=True)
        self.assertEqual(DM.weather_device_ids(SITE)[1], 'none')


class TestSourceIsSpelledOut(unittest.TestCase):
    """소스로 고정하는 것들 — 실행 중에는 조용히 어긋난다."""

    def _src(self, path):
        return io.open(path, encoding='utf-8').read()

    def test_gateway_never_rebinds_weather(self):
        """`rebind` 는 단일 점유 전용이다. 여기 들어오면 기상대 둘 중
        하나가 저장 한 번에 사라지는데 **에러가 안 난다**."""
        src = self._src(os.path.join(
            _ROOT, 'aot', 'aot_flask', 'geo', 'device_binding.py'))
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == 'set_site_weather')
        calls = {n.func.id for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn('bind', calls)
        self.assertIn('unbind', calls)
        self.assertNotIn('rebind', calls)

    def test_candidates_exclude_outputs(self):
        """출력을 안 거르면 고를 것 하나가 밸브 18대에 파묻힌다."""
        self.assertIn("if kind == 'output':", self._src(_MEMBERSHIP_PY))

    def test_candidate_labels_prefer_the_channel_name(self):
        """측정 어휘의 이름은 물리량이라 `length` 가 '길이' 로 나온다 —
        그 채널이 재는 것은 강우다. 일지에서 같은 지적을 받아 고쳤다."""
        src = self._src(_MEMBERSHIP_PY)
        self.assertIn("(r.name or '').strip() or _measurement_display_name(",
                      src)

    def test_save_route_requires_the_key_not_just_a_value(self):
        """키가 없는 요청을 '해제' 로 읽으면, 조회 실패로 목록을 못 채운
        상태에서 저장하는 것만으로 지정이 통째로 지워진다(스코프 부여
        화면이 같은 함정을 겪었다)."""
        self.assertIn("if 'device_ids' not in data:", self._src(_ROUTES_PY))

    def test_save_route_is_scope_gated(self):
        src = self._src(_ROUTES_PY)
        i = src.index('def api_geo_site_weather')
        body = src[i:i + 3500]
        self.assertIn("scope.can_operate('geo_map'", body)

    def test_about_pane_is_not_redrawn_by_the_poll(self):
        """30초 폴링이 [정보] 탭을 다시 그리면, 기상대를 고르는 중에
        체크가 통째로 날아간다 — 저장을 누르기 전에 화면이 스스로
        되돌아간다."""
        self.assertIn('if (aboutPane && !aboutPane.firstChild) {',
                      self._src(_WIDGET_JS))

    def test_saved_message_is_written_after_the_redraw(self):
        """앞에 적으면 `innerHTML` 교체가 지운다. 이미 지정돼 있던 대지에
        한 대를 더할 때는 안내문도 안 바뀌므로, 화면이 아무 반응도 하지
        않는 것처럼 보인다(실측)."""
        src = self._src(_WIDGET_JS)
        i = src.index('function _wireSiteWeather')
        body = src[i:i + 4000]
        self.assertLess(body.index('_renderSiteWeather(box, d2)'),
                        body.index("m2.textContent = _tr('Saved')"))
