# coding=utf-8
"""예보 파일 오프셋은 **파일을 쓴 시각** 기준이다(2026-09-22 수정).

`forecast.json` 의 키 "0", "1", ... 은 파일의 `now`(벽시계, `tz`)부터 몇 시간 뒤인지다.
예전에는 feedforward·기상 위험·AI 예보 도구가 키를 그대로 "지금부터 몇 시간 뒤" 로 읽어,
파일이 늦게 갱신되면 이미 지난 시간대를 앞날로 봤다(발표 215일 지난 파일도 판정이 돌았다).
"""

from datetime import datetime, timedelta

import pytz

from aot.functions.utils.env_control.forecast_feedforward import (
    build_feedforward_signal, forecast_epoch, forecast_rows_ahead,
)

KST = pytz.timezone('Asia/Seoul')


def _stamp(dt):
    return dt.strftime('%Y%m%d%H%M')


def _file(written, rows, pub=None, tz='Asia/Seoul'):
    return {'tz': tz, 'now': _stamp(written), 'pub_dt': _stamp(pub or written),
            'forecasts': {str(k): v for k, v in rows.items()}}


WRITTEN = datetime(2026, 9, 22, 12, 0)
AT_WRITE = KST.localize(WRITTEN).timestamp()


class TestRowsAhead:
    def test_갓_쓴_파일은_예전과_같다(self):
        d = _file(WRITTEN, {0: {'TMP': 1}, 1: {'TMP': 2}, 5: {'TMP': 3}})
        rows = forecast_rows_ahead(d, 3, now_epoch=AT_WRITE)
        assert [r[0] for r in rows] == [0.0, 1.0]

    def test_늦게_갱신된_파일은_지난_시간대를_버린다(self):
        d = _file(WRITTEN, {k: {'TMP': k} for k in range(8)})
        rows = forecast_rows_ahead(d, 3, now_epoch=AT_WRITE + 4 * 3600)
        # 지금 = 오프셋 4. 0~3 은 지난 시간, 4~7 이 0~3시간 뒤.
        assert [r[1]['TMP'] for r in rows] == [4, 5, 6, 7]
        assert [r[0] for r in rows] == [0.0, 1.0, 2.0, 3.0]

    def test_지금이_든_시간_칸은_포함(self):
        d = _file(WRITTEN, {0: {'TMP': 1}, 1: {'TMP': 2}})
        rows = forecast_rows_ahead(d, 3, now_epoch=AT_WRITE + 40 * 60)
        assert rows[0][1]['TMP'] == 1 and rows[0][0] < 0

    def test_아주_낡은_파일은_아무것도_없다(self):
        d = _file(WRITTEN, {k: {'TMP': k} for k in range(72)})
        assert forecast_rows_ahead(d, 3, now_epoch=AT_WRITE + 215 * 86400) == []

    def test_쓴_시각이_없으면_모른다(self):
        d = _file(WRITTEN, {0: {'TMP': 1}})
        d.pop('now')
        assert forecast_rows_ahead(d, 3, now_epoch=AT_WRITE) == []

    def test_파일의_시간대로_읽는다(self):
        tokyo = pytz.timezone('Asia/Tokyo')
        d = _file(WRITTEN, {0: {'TMP': 1}}, tz='Asia/Tokyo')
        assert forecast_epoch(d['now'], d['tz']) == tokyo.localize(WRITTEN).timestamp()
        assert forecast_epoch('202609221200', None) == AT_WRITE   # 없으면 KST


class TestFeedforward:
    def test_지난_시간대의_고온으로_목표를_옮기지_않는다(self, tmp_path):
        """파일은 4시간 전에 썼고, 고온(35°C)은 오프셋 1~2 = 이미 지난 시간이다."""
        import json
        rows = {k: {'TMP': 35.0 if k in (1, 2) else 22.0, 'REH': 60.0} for k in range(10)}
        p = tmp_path / 'forecast.json'
        p.write_text(json.dumps(_file(WRITTEN, rows)), encoding='utf-8')
        from aot.functions.utils.env_control import forecast_feedforward as ff
        ff._clear_cache()
        sig = build_feedforward_signal(T_int=22.0, RH_int=60.0, lookahead_h=3.0,
                                       forecast_path=str(p),
                                       now_epoch=AT_WRITE + 4 * 3600)
        ff._clear_cache()
        assert sig.valid
        assert sig.T_bias == 0.0, sig.reason

    def test_앞으로_올_고온에는_반응한다(self, tmp_path):
        import json
        rows = {k: {'TMP': 35.0 if k in (5, 6) else 22.0, 'REH': 60.0} for k in range(10)}
        p = tmp_path / 'forecast.json'
        p.write_text(json.dumps(_file(WRITTEN, rows)), encoding='utf-8')
        from aot.functions.utils.env_control import forecast_feedforward as ff
        ff._clear_cache()
        sig = build_feedforward_signal(T_int=22.0, RH_int=60.0, lookahead_h=3.0,
                                       forecast_path=str(p),
                                       now_epoch=AT_WRITE + 4 * 3600)
        ff._clear_cache()
        assert sig.T_bias < 0.0


class TestAiTool:
    def test_hour_offset_는_지금부터(self, monkeypatch):
        from aot.tools.aot_data_tool_service import AoTDataToolService as MeasurementTools
        from aot.functions.utils.env_control import forecast_feedforward as ff
        wall = datetime.now(KST).replace(tzinfo=None, second=0, microsecond=0)
        written = wall - timedelta(hours=3)
        rows = {k: {'TMP': float(k)} for k in range(10)}
        monkeypatch.setattr(ff, '_load_forecast',
                            lambda *a, **k: _file(written, rows, pub=written))
        out = MeasurementTools.get_weather_forecast(hours=2)
        assert out['status'] == 'success', out
        assert [r['TMP'] for r in out['forecasts']] == [3.0, 4.0, 5.0]
        assert [r['hour_offset'] for r in out['forecasts']] == [0, 1, 2]
