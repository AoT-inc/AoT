# coding=utf-8
"""프로그램의 단계 목표값과 구획의 현재 실측값을 나란히 놓는다.

"이 구획이 이 작물에 얼마나 적합한가" 는 실사용에서 반복해 나온 질문인데
(2026-08-26), 답이 늘 현재 센서값 나열이었다. 목표가 옆에 없으니 모델이
판단할 근거가 없어 값만 읽고 만 것이다. 필요한 것은 둘 다 이미 있었다 —
단계의 targets 가 숫자를, plot_context 가 그것을 측정 이름까지 붙여
정규화해 준다. 이어 붙이지 않았을 뿐이다.
"""
from aot.ai.services.aot_data_tool_service import AoTDataToolService as S


def _brief(targets, sensors=None, program=True, stage_name='정식기'):
    return {'unique_id': 'plot-1',
            'stage': {'name': stage_name, 'targets': targets},
            'program': {'name': '무'} if program else None,
            'sensors': sensors or {}}


def _reading(value, sensor='온습도_6', others=None):
    d = {'value': value, 'at': 't', 'sensor': sensor}
    if others:
        d['others'] = others
    return d


class TestItPairsTargetWithReading:
    def test_the_gap_is_computed(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement',
                            staticmethod(lambda a, b=None: {'temperature': _reading(25.2)}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'unit': '°C',
              'measurement': 'temperature', 'value': 26.0, 'observable': True}],
            sensors={'in_plot': ['dev-1']}))

        assert out['state'] == 'compared'
        row = out['rows'][0]
        assert row['target'] == 26.0 and row['current'] == 25.2
        assert row['delta'] == -0.8

    def test_no_tolerance_band_is_invented(self):
        """targets 는 단일 수치이고 허용폭이 데이터 어디에도 없다. '적정/높음'
        을 매기려면 폭을 발명해야 하고, 그러면 근거 없는 숫자가 조언이 된다."""
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 26.0, 'observable': True}]))
        assert 'do NOT' in out['note'] and 'invent' in out['note']
        for row in out.get('rows', []):
            assert 'verdict' not in row and 'status' not in row


class TestItDoesNotManufactureProblems:
    def test_a_non_observable_target_is_not_reported_as_a_missing_sensor(self, monkeypatch):
        """CO2·DLI 처럼 센서로 잴 수 없다고 선언된 항목을 '센서 없음' 으로
        보고하면 없는 문제를 만든다."""
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None: {}))
        out = S._stage_target_check(_brief(
            [{'key': 'co2', 'label': 'CO2', 'measurement': 'co2',
              'value': 1000.0, 'observable': False}],
            sensors={'in_plot': ['dev-1']}))

        assert out.get('not_measurable_here') == ['CO2']
        assert 'CO2' not in (out.get('no_reading_for') or [])

    def test_a_measurable_target_without_a_reading_is_reported(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None: {}))
        out = S._stage_target_check(_brief(
            [{'key': 'rh', 'label': 'Humidity', 'measurement': 'humidity',
              'value': 70.0, 'observable': True}],
            sensors={'in_plot': ['dev-1']}))
        assert out.get('no_reading_for') == ['Humidity']


class TestTheEmptyCaseIsActionable:
    def test_a_programme_without_targets_says_so(self):
        """조용히 비우면 모델이 또 센서값을 나열한다. 이건 내부 사정이 아니라
        그 사람의 프로그램에 아직 안 채워진 칸이다."""
        out = S._stage_target_check(_brief(None))
        assert out['state'] == 'no_targets'
        assert 'no target values' in out['note']

    def test_a_plot_without_a_programme_adds_nothing(self):
        assert S._stage_target_check(_brief(None, program=False)) is None


class TestTheRawDictShapeStillWorks:
    def test_a_dict_of_targets_is_accepted(self, monkeypatch):
        """정규화를 거치지 않은 payload 에서 조용히 비어 버리지 않게 한다."""
        monkeypatch.setattr(S, '_latest_by_measurement',
                            staticmethod(lambda a, b=None: {'temperature': _reading(24.0)}))
        brief = {'stage': {'name': '정식기', 'targets': {'temp_day': 26.0}},
                 'program': {'name': '무', 'target_defs': [
                     {'key': 'temp_day', 'label': 'Day temp', 'unit': '°C',
                      'measurement': 'temperature'}]},
                 'sensors': {'in_plot': ['dev-1']}}
        out = S._stage_target_check(brief)
        assert out['rows'][0]['delta'] == -2.0


class TestTheModelIsToldToUseIt:
    """실려 있다는 것과 닿는다는 것은 다르다 — stage.guidance 가 같은 이유로
    _reading 에 안내를 싣는다."""

    def test_a_compared_check_tells_it_to_answer_from_that(self):
        notes = ' '.join(S._plot_reading_notes(
            {'target_check': {'state': 'compared'}, 'stage': {}}))
        assert 'target_check' in notes
        assert 'do not list raw sensor values' in notes

    def test_an_empty_check_explains_why_it_cannot_judge(self):
        notes = ' '.join(S._plot_reading_notes(
            {'target_check': {'state': 'no_targets'}, 'stage': {}}))
        assert 'no target values' in notes


class TestItSaysWhichSensorTheReadingCameFrom:
    """실측(2026-08-26): 공기 온도 목표가 **토양 센서** 값과 비교됐다. 측정
    이름이 둘 다 'temperature' 라 이름만으로는 갈리지 않는다. 어느 센서인지
    보이지 않으면 그것을 알 길이 없다."""

    def test_the_sensor_name_travels_with_the_reading(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None: {'temperature': _reading(35.6, '온습도_6')}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 25.0, 'observable': True}], sensors={'in_plot': ['d1']}))
        assert out['rows'][0]['sensor'] == '온습도_6'

    def test_the_other_sensors_are_listed(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None: {'temperature': _reading(
                35.6, '온습도_6', others=[{'sensor': '토양온습도_4', 'value': 36.25}])}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 25.0}], sensors={'in_plot': ['d1']}))
        assert out['rows'][0]['other_sensors'][0]['sensor'] == '토양온습도_4'

    def test_the_note_warns_about_same_measurement_sensors(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None: {'temperature': _reading(35.6)}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 25.0}], sensors={'in_plot': ['d1']}))
        assert 'air vs soil' in out['note']


class TestDayAndNightTargetsDoNotCrossCompare:
    """야간 12도 목표를 한낮 35.6도와 견주어 '23.6도 차이' 라는 허위 경보가
    났다. `when` 이 정규화 과정에서 빠져 있어 읽는 쪽이 알 수 없었다."""

    def _run(self, monkeypatch, is_day):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None: {'temperature': _reading(35.6)}))
        import aot.utils.solar as solar
        monkeypatch.setattr(solar, 'is_daytime', lambda **kw: is_day)
        return S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'when': 'day', 'value': 25.0},
             {'key': 'temp_night', 'label': 'Night temp', 'measurement': 'temperature',
              'when': 'night', 'value': 12.0}], sensors={'in_plot': ['d1']}))

    def test_the_night_target_is_not_compared_during_the_day(self, monkeypatch):
        out = self._run(monkeypatch, True)
        assert [r['label'] for r in out['rows']] == ['Day temp']
        assert out['not_this_period'][0]['label'] == 'Night temp'
        assert out['now'] == 'day'

    def test_the_day_target_is_not_compared_at_night(self, monkeypatch):
        out = self._run(monkeypatch, False)
        assert [r['label'] for r in out['rows']] == ['Night temp']
        assert out['not_this_period'][0]['label'] == 'Day temp'

    def test_unknown_daylight_compares_both_rather_than_dropping_them(self, monkeypatch):
        """판정할 수 없으면 조용히 버리지 않는다 — 버리면 목표가 없는 것처럼
        보인다. 대신 둘 다 내고 사람이 본다."""
        out = self._run(monkeypatch, None)
        assert len(out['rows']) == 2
        assert 'not_this_period' not in out

    def test_the_flag_survives_normalisation(self):
        """`when` 이 plot_context 의 정규화 결과에 실려야 여기까지 온다."""
        import inspect

        from aot.aot_flask.geo import plot_context

        body = inspect.getsource(plot_context)
        assert "'when': spec.get('when')" in body


class TestCurveDrivenTargetsAreNotDroppedSilently:
    """곡선을 따르는 항목은 값이 비어 온다(곡선의 '지금 값' 은 메서드마다
    계산이 달라 plot_context 가 채우지 못한다). 조용히 빠뜨리면 목표가 아예
    없는 것처럼 보인다 — 실측에서 VPD 가 그랬다."""

    def test_a_curve_target_is_reported_as_following_a_curve(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None: {}))
        out = S._stage_target_check(_brief(
            [{'key': 'vpd', 'label': 'VPD', 'measurement': 'vapor_pressure_deficit',
              'value': None, 'source': 'method', 'method_name': 'vpd'}],
            sensors={'in_plot': ['d1']}))
        assert out['follows_curve'][0] == {'label': 'VPD', 'curve': 'vpd'}
        assert 'VPD' not in (out.get('no_reading_for') or [])

    def test_a_nameless_curve_still_says_it_follows_one(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None: {}))
        out = S._stage_target_check(_brief(
            [{'key': 'vpd', 'label': 'VPD', 'value': None,
              'source': 'method', 'method_uuid': 'm-1'}], sensors={'in_plot': ['d1']}))
        assert out['follows_curve'][0]['label'] == 'VPD'


class TestInPlotSensorsWinOverZoneFallback:
    def test_the_plot_sensor_is_preferred(self):
        """구획 안 센서를 구역 대표값보다 먼저 본다(sensors_for_plot 과 같은
        우선순위). 인자 순서가 그것을 표현한다."""
        import inspect

        body = inspect.getsource(S._latest_by_measurement)
        assert 'in_plot_ids' in body and 'zone_ids' in body
        assert 'rank' in body
