# coding=utf-8
"""몇 시간 뒤 예보 입력의 오용 가드 (설계안 §4.3, PR 2 — 2026-10-13).

`OPEN_METEO_HOURLY_FORECAST` 는 "+1h/+3h/+6h" 와 "앞으로 N 시간 최대" 를 낸다.
이 채널을 실외 센서·외기 수집기 같은 **"지금 값" 자리**에 두면 "+6h 강수" 가
지금 오는 비로 읽혀 창이 닫힌다. 환경제어 결정(E4):

  ① 자동 해석(`auto_channels_for_device`)에서 이 드라이버 장치는 뺀다.
  ② 실내/실외 센서 설비와 외기 수집기 항목에 명시로 고르면 **저장을 거부**한다.
  ③ 예보 바인딩(weather_bindings)은 허용한다.
  ④ 기존 입력은 거부하지 않는다 — `data_time` 표식이 없으면 '현재'.
     예: 구마모토 일사 센서에 묶인 `OPEN_METEO_FORECAST` 는 계속 저장된다.

판정 근거는 드라이버의 `data_time='forecast'` 하나다(이름으로 어림하지 않는다).
"""
import unittest

import pytest
from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements, GeoFacility, Input

# 앱 컨텍스트 밖에서 먼저 import — 번역 문자열을 평가하는 모듈이 딸려 온다.
from aot.space import device_binding as _device_binding  # noqa: F401
from aot.space import facility_integration as FI
from aot.space.facility_io import FacilityManager
from aot.functions import ext_context_collector as ECC
from aot.inputs import open_meteo_hourly_forecast as HF
import aot.utils.inputs as UI

NEW = 'OPEN_METEO_HOURLY_FORECAST'
LIVE = 'OPEN_METEO_FORECAST'
KMA = 'KMA_weather_500'

FC_IN = '11111111-1111-4111-8111-111111111111'      # 새 예보 드라이버 장치
OM_IN = '22222222-2222-4222-8222-222222222222'      # 기존 Open-Meteo(지금 칸)
KMA_IN = '33333333-3333-4333-8333-333333333333'     # 기상청 관측


# ── 드라이버 표식 ──────────────────────────────────────────────────────────────

class TestDriverMarker:

    def test_새_드라이버만_예보_시각이다(self):
        drivers = UI.forecast_time_input_drivers()
        assert NEW in drivers
        assert LIVE not in drivers, '기존 실시간 입력이 예보로 잡히면 기존 설치가 거부된다'
        assert KMA not in drivers
        assert 'KMA_forecast' not in drivers, '표식이 없으면 현재로 본다'

    def test_드라이버_목록이_표식을_싣는다(self):
        info = UI.parse_input_information()
        assert info[NEW].get('data_time') == 'forecast'
        assert 'data_time' not in info[LIVE]

    def test_출처_표식은_그대로다(self):
        models = UI.model_input_drivers()
        assert NEW in models and LIVE in models
        assert KMA not in models

    def test_성공한_결과만_기억한다(self, monkeypatch):
        """파싱 실패를 빈 결과로 기억하면 그 프로세스 내내 가드가 꺼진다."""
        monkeypatch.setattr(UI, '_FORECAST_TIME_DRIVERS', None)

        def boom(*a, **k):
            raise RuntimeError('locale')
        monkeypatch.setattr(UI, 'parse_input_information', boom)
        assert UI.forecast_time_input_drivers() == frozenset()
        assert UI._FORECAST_TIME_DRIVERS is None
        monkeypatch.setattr(UI, 'parse_input_information',
                            lambda *a, **k: {NEW: {'data_time': 'forecast'}, LIVE: {}})
        assert UI.forecast_time_input_drivers() == frozenset({NEW})


def _fake_devices(monkeypatch, mapping):
    monkeypatch.setattr(UI, '_input_devices',
                        lambda ids: [(i, mapping[i]) for i in ids if i in mapping])


class TestDeviceJudgement:

    MAP = {FC_IN: NEW, OM_IN: LIVE, KMA_IN: KMA}

    def test_예보_장치만_골라낸다(self, monkeypatch):
        _fake_devices(monkeypatch, self.MAP)
        assert UI.forecast_time_device_ids([FC_IN, OM_IN, KMA_IN]) == {FC_IN}
        assert UI.forecast_time_device_ids([]) == set()

    def test_판정_실패는_현재로_본다(self, monkeypatch):
        monkeypatch.setattr(UI, '_input_devices', lambda ids: None)
        assert UI.forecast_time_device_ids([FC_IN]) == set()
        assert UI.forecast_time_selection_problem(FC_IN + ',m') is None

    def test_강우_출처(self, monkeypatch):
        """새 드라이버도 data_origin='model' — 게이트가 전면 폐쇄하지 않는다.
        기상청 관측은 'measured' 그대로."""
        _fake_devices(monkeypatch, self.MAP)
        assert UI.rain_origin_of([FC_IN]) == 'model'
        assert UI.rain_origin_of([KMA_IN]) == 'measured'
        assert UI.rain_origin_of([OM_IN]) == 'model'
        assert UI.rain_origin_of([FC_IN, KMA_IN]) == 'measured'


# ── 외기 수집기 — "지금 값" 칸 ──────────────────────────────────────────────────

class TestExtContextCollector:

    MAP = {FC_IN: NEW, OM_IN: LIVE, KMA_IN: KMA}

    def test_모든_측정_칸에_제약이_걸려_있다(self):
        opts = [o for o in ECC.FUNCTION_INFORMATION['custom_options']
                if o.get('type') == 'select_measurement']
        assert {o['id'] for o in opts} >= {'sensor_rain', 'sensor_temperature',
                                           'sensor_humidity', 'sensor_wind',
                                           'sensor_solar'}
        for o in opts:
            assert o.get('constraints_pass') is ECC.constraints_pass_current_value, o['id']

    def test_예보_입력은_거부(self, monkeypatch):
        _fake_devices(monkeypatch, self.MAP)
        ok, errors, _ = ECC.constraints_pass_current_value(None, FC_IN + ',meas-1')
        assert ok is False
        assert errors and '예보' in errors[0]

    @pytest.mark.parametrize('sel', [OM_IN + ',m', KMA_IN + ',m', '', None,
                                     'func-uuid,m'])
    def test_기존_입력은_그대로(self, monkeypatch, sel):
        _fake_devices(monkeypatch, self.MAP)
        ok, errors, _ = ECC.constraints_pass_current_value(None, sel)
        assert ok is True and errors == []

    def test_웹_폼_저장이_거부된다(self, monkeypatch):
        """실제 저장 경로(`custom_options_return_json`)가 오류를 내고 값을 바꾸지 않는다."""
        from werkzeug.datastructures import MultiDict
        from aot.aot_flask.utils.utils_general import custom_options_return_json
        _fake_devices(monkeypatch, self.MAP)
        info = {'ext_context_collector': ECC.FUNCTION_INFORMATION}
        presave = {'sensor_rain': KMA_IN + ',m6'}

        class _Dev:
            device = 'ext_context_collector'
        err, out = custom_options_return_json(
            [], info, request_form=MultiDict({'sensor_rain': FC_IN + ',m4'}),
            mod_dev=_Dev(), custom_options=dict(presave))
        assert err, '거부 오류가 없다'
        import json
        assert json.loads(out)['sensor_rain'] == KMA_IN + ',m6'

        err, out = custom_options_return_json(
            [], info, request_form=MultiDict({'sensor_rain': OM_IN + ',m5'}),
            mod_dev=_Dev(), custom_options=dict(presave))
        assert err == []
        assert json.loads(out)['sensor_rain'] == OM_IN + ',m5'

    def test_AI_도구_값_검사도_같은_제약(self, monkeypatch):
        from aot.tools.data_tools.function import FunctionToolsMixin as FunctionTools
        _fake_devices(monkeypatch, self.MAP)
        opt = next(o for o in ECC.FUNCTION_INFORMATION['custom_options']
                   if o['id'] == 'sensor_rain')
        assert '예보' in FunctionTools._option_value_problem(opt, FC_IN + ',m')
        assert FunctionTools._option_value_problem(opt, OM_IN + ',m') is None
        assert FunctionTools._option_value_problem(opt, '') is None

    def test_AI_도구로_만들_때도_거부_빈_함수를_남기지_않는다(self, monkeypatch):
        from aot.aot_flask.utils import utils_function
        from aot.tools.data_tools.function import FunctionToolsMixin
        _fake_devices(monkeypatch, self.MAP)
        import aot.config as cfg
        import aot.utils.functions as uf
        monkeypatch.setitem(cfg.FUNCTION_INFO, 'ext_context_collector',
                            {'name': 'Ext Context'})
        monkeypatch.setattr(uf, 'parse_function_information', lambda *a, **k: {
            'ext_context_collector': ECC.FUNCTION_INFORMATION})
        called = []
        monkeypatch.setattr(utils_function, 'function_add',
                            lambda *a, **k: called.append(1))
        out = FunctionToolsMixin.create_function_tool(
            function_type='ext_context_collector',
            params={'sensor_rain': FC_IN + ',m'})
        assert 'sensor_rain' in out.get('invalid', {}), out
        assert called == [], '거부할 값인데 함수 행을 먼저 만들었다'


# ── 시설 — 자동 해석 제외와 저장 거부 (실제 DB, 인메모리) ───────────────────────

def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    # 드라이버 목록은 lazy 문구를 풀어야 파싱된다. Babel 이 없으면 파싱이 실패해 가드가 꺼지고,
    # 앞선 시험이 캐시를 채운 작업자에서만 통과한다.
    Babel(app)
    return app


def _sensor(fid, iid, role='outdoor', channels=None, name=None):
    d = {'id': fid, 'kind': 'sensor', 'sensor_role': role, 'input_id': iid,
         'name': name or fid}
    if channels is not None:
        d['channel_measurements'] = channels
    return d


class _DB(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        Input(unique_id=FC_IN, name='김제 예보', device=NEW).save()
        Input(unique_id=OM_IN, name='Kumamoto Solar', device=LIVE).save()
        Input(unique_id=KMA_IN, name='김제 기상청', device=KMA).save()
        # 새 드라이버 — 실제 채널 정의 그대로
        for ch, m in HF.measurements_dict.items():
            DeviceMeasurements(unique_id='fc-m%d' % ch, device_id=FC_IN,
                               measurement=m['measurement'], unit=m['unit'],
                               channel=ch).save()
        for ch, meas in enumerate(('temperature', 'humidity', 'light', 'speed',
                                   'direction', 'precipitation', 'vapor_pressure_deficit',
                                   'dewpoint')):
            DeviceMeasurements(unique_id='om-m%d' % ch, device_id=OM_IN,
                               measurement=meas, unit='x', channel=ch).save()

    def tearDown(self):
        FI.invalidate_facility_integration_cache()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _integ(self, fittings, fac='fac-guard'):
        GeoFacility(unique_id=fac, shape_uuid='s-' + fac, geo_id='map-1',
                    name='가드 시설', fittings=fittings, actuators=[]).save()
        integ, err = FI.get_facility_integration(fac, bypass_cache=True)
        self.assertIsNone(err)
        return integ


class TestAutoResolutionExcluded(_DB):

    def test_실외_설비에_넣어도_자동_해석_0개(self):
        integ = self._integ([_sensor('S1', FC_IN)])
        self.assertEqual(integ['sensors_outdoor'], [])

    def test_종류가_하나뿐이어도_끌려오지_않는다(self):
        """일반 규칙으로는 모호하지 않은 종류(채널 하나)는 끌려온다 — 가드가 막는다."""
        rows = [r for r in DeviceMeasurements.query.filter_by(device_id=FC_IN)
                if r.channel in (2, 21)]            # +1h 강수, 창 최고 기온
        assert FI.auto_channels_for_device(rows, set()), '전제: 일반 규칙은 끌어온다'
        self.assertEqual(FI.auto_channels_for_input(NEW, rows, set()), [])

    def test_기존_입력은_자동_해석_그대로(self):
        integ = self._integ([_sensor('S2', OM_IN,
                                     channels=[{'measurement_id': 'om-m2'}])])
        types = {s['measurement_type'] for s in integ['sensors_outdoor']}
        self.assertIn('light', types)
        self.assertIn('temperature', types, '기존 Open-Meteo 자동 해석이 사라졌다')


class TestSaveRejected(_DB):

    def _save(self, fittings, weather_bindings=None):
        data = {'facility_uuid': 'fac-x', 'geo_id': 'map-1', 'fittings': fittings}
        if weather_bindings is not None:
            data['weather_bindings'] = weather_bindings
        return FacilityManager.save_facility(data)

    def test_실외_센서_명시_선택은_거부(self):
        res, err = self._save([_sensor('S1', FC_IN, name='気象台',
                                       channels=[{'measurement_id': 'fc-m2'}])])
        self.assertIsNone(res)
        self.assertIn('예보', err)
        self.assertIn('김제 예보', err)
        self.assertIn('저장하지 않았습니다', err)

    def test_실내_센서도_거부(self):
        res, err = self._save([_sensor('S1', FC_IN, role='indoor')])
        self.assertIsNone(res)
        self.assertIn('실내', err)

    def test_역할_미설정은_실내로_보고_거부(self):
        f = _sensor('S1', FC_IN)
        f.pop('sensor_role')
        _res, err = self._save([f])
        self.assertIn('실내', err)

    def test_기존_입력_구마모토_일사는_통과(self):
        """`OPEN_METEO_FORECAST` 일사 센서 — 가드 검사를 지나 다음 단계로 간다."""
        from aot.space import facility_io as FIO
        self.assertIsNone(FIO._forecast_inputs_in_sensor_fittings(
            [_sensor('S2', OM_IN, channels=[{'measurement_id': 'om-m2'}]),
             _sensor('S3', KMA_IN)]))

    def test_예보_바인딩은_막지_않는다(self):
        from aot.space import facility_io as FIO
        self.assertIsNone(FIO._forecast_inputs_in_sensor_fittings(
            [{'id': 'A1', 'kind': 'opening', 'input_id': FC_IN}]))
        # weather_bindings 는 설비가 아니다 — 같은 장치를 예보 칸에 묶는 것은 허용.
        _res, err = self._save([], weather_bindings=[{
            'measurement_type': 'forecast_precipitation', 'input_uuid': FC_IN,
            'measurement_id': 'fc-m25', 'name': '창 시간당 강수 최대'}])
        self.assertNotIn('예보 입력', err or '')


if __name__ == '__main__':
    unittest.main()
