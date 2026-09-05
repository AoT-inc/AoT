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
                            staticmethod(lambda a, b=None, **_: {'temperature': _reading(25.2)}))
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
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None, **_: {}))
        out = S._stage_target_check(_brief(
            [{'key': 'co2', 'label': 'CO2', 'measurement': 'co2',
              'value': 1000.0, 'observable': False}],
            sensors={'in_plot': ['dev-1']}))

        assert out.get('not_measurable_here') == ['CO2']
        assert 'CO2' not in (out.get('no_reading_for') or [])

    def test_a_measurable_target_without_a_reading_is_reported(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None, **_: {}))
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
                            staticmethod(lambda a, b=None, **_: {'temperature': _reading(24.0)}))
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
            lambda a, b=None, **_: {'temperature': _reading(35.6, '온습도_6')}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 25.0, 'observable': True}], sensors={'in_plot': ['d1']}))
        assert out['rows'][0]['sensor'] == '온습도_6'

    def test_the_other_sensors_are_listed(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None, **_: {'temperature': _reading(
                35.6, '온습도_6', others=[{'sensor': '토양온습도_4', 'value': 36.25}])}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 25.0}], sensors={'in_plot': ['d1']}))
        assert out['rows'][0]['other_sensors'][0]['sensor'] == '토양온습도_4'

    def test_the_note_warns_about_same_measurement_sensors(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None, **_: {'temperature': _reading(35.6)}))
        out = S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 25.0}], sensors={'in_plot': ['d1']}))
        assert 'air vs soil' in out['note']


class TestDayAndNightTargetsDoNotCrossCompare:
    """야간 12도 목표를 한낮 35.6도와 견주어 '23.6도 차이' 라는 허위 경보가
    났다. `when` 이 정규화 과정에서 빠져 있어 읽는 쪽이 알 수 없었다."""

    def _run(self, monkeypatch, is_day):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None, **_: {'temperature': _reading(35.6)}))
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
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None, **_: {}))
        out = S._stage_target_check(_brief(
            [{'key': 'vpd', 'label': 'VPD', 'measurement': 'vapor_pressure_deficit',
              'value': None, 'source': 'method', 'method_name': 'vpd'}],
            sensors={'in_plot': ['d1']}))
        assert out['follows_curve'][0] == {'label': 'VPD', 'curve': 'vpd'}
        assert 'VPD' not in (out.get('no_reading_for') or [])

    def test_a_nameless_curve_still_says_it_follows_one(self, monkeypatch):
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(lambda a, b=None, **_: {}))
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


class TestFacilityPlotSensorsAreNotSkipped:
    """시설 구획은 `sensors['in_plot']` 이 항상 비어 있다(기하가 없어서 —
    plot_context.sensors_for_plot 참조). 호출부가 'in_plot' 만 보고 그걸
    'zone_ids' 로만 채우면, 그 구획이 속한 bay/시설 센서의 현재값이
    대조에서 통째로 빠지고 조용히 zone 대표값으로 뒤바뀐다."""

    def _captured(self, monkeypatch):
        calls = []
        monkeypatch.setattr(S, '_latest_by_measurement', staticmethod(
            lambda a, b=None, **_: calls.append((list(a or []), list(b or [])))
            or {'temperature': _reading(25.0)}))
        return calls

    def test_bay_sensors_are_passed_as_the_narrow_scope(self, monkeypatch):
        calls = self._captured(monkeypatch)
        S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 26.0, 'observable': True}],
            sensors={'in_plot': [], 'in_bay': ['bay-dev-1'], 'from_zone': ['zone-dev-1']}))
        assert calls[0][0] == ['bay-dev-1']

    def test_facility_sensors_are_passed_when_there_is_no_bay(self, monkeypatch):
        calls = self._captured(monkeypatch)
        S._stage_target_check(_brief(
            [{'key': 'temp_day', 'label': 'Day temp', 'measurement': 'temperature',
              'value': 26.0, 'observable': True}],
            sensors={'in_plot': [], 'in_bay': [], 'from_facility': ['fac-dev-1'],
                     'from_zone': ['zone-dev-1']}))
        assert calls[0][0] == ['fac-dev-1']


class TestItLooksBackNotJustAtNow:
    """한 시점만 보면 "이 목표가 이 현장에서 계속 안 맞는다" 를 말할 수 없다.

    실측(김제 3-1): 야간온도가 잰 날 전부 목표를 넘겼는데, 낮에 물으면 그
    항목이 `not_this_period` 로 빠져 목록에서 **사라지기까지 했다.**
    """

    @staticmethod
    def _drift(latest=None):
        return {'days': 14, 'from': '2026-08-21', 'to': '2026-09-03',
                'drift': [{'label': 'Night temp', 'when': 'night',
                           'phase_label': None, 'unit': 'C',
                           'unit_label': '°C', 'sensor_count': 2,
                           'agree': 'above', 'sensors': [],
                           'days': 12, 'days_hi': 14,
                           'above': 12, 'above_hi': 14,
                           'below': 0, 'below_hi': 0,
                           'on_target': 0, 'on_target_hi': 0,
                           'mean': 5.5, 'mean_hi': 5.9,
                           'min': 1.66, 'max': 9.31, 'one_way': 'above'}],
                'latest': latest or {}}

    def _out(self, monkeypatch, is_day=True, latest=None, recent_days=None):
        import aot.aot_flask.geo.plot_journal as PJ
        monkeypatch.setattr(S, '_latest_by_measurement',
                            staticmethod(lambda a, b=None, **_: {}))
        monkeypatch.setattr('aot.utils.solar.is_daytime',
                            lambda **k: is_day)
        monkeypatch.setattr(PJ, 'recent_target_drift',
                            lambda *a, **k: self._drift(latest))
        return S._stage_target_check(
            _brief([{'key': 'temp_night', 'label': 'Night temp', 'unit': '°C',
                     'measurement': 'temperature', 'when': 'night',
                     'value': 18.0, 'observable': True}],
                   sensors={'in_plot': ['dev-1']}),
            plot_row=object(), recent_days=recent_days)

    def test_the_period_summary_rides_along(self, monkeypatch):
        out = self._out(monkeypatch)
        assert out['recent']['days'] == 14
        assert out['recent']['drift'][0]['one_way'] == 'above'

    def test_a_night_target_asked_by_day_keeps_its_evidence(self, monkeypatch):
        """예전에는 목표만 적힌 한 줄로 빠져 "모른다" 로 읽혔다."""
        out = self._out(monkeypatch, latest={
            'temperature|night': {'value': 23.5, 'on': '2026-09-03',
                                  'sensor': '온습도_5'}})
        item = out['not_this_period'][0]
        assert item['last_seen']['value'] == 23.5
        assert item['last_seen']['delta'] == 5.5
        assert item['last_seen']['on'] == '2026-09-03'

    def test_no_reading_no_invented_one(self, monkeypatch):
        out = self._out(monkeypatch, latest={})
        assert 'last_seen' not in out['not_this_period'][0]

    def test_it_can_be_turned_off(self, monkeypatch):
        """되돌아보기는 InfluxDB 를 그 기간만큼 읽는다 — 끌 수 있어야 한다."""
        out = self._out(monkeypatch, recent_days=0)
        assert 'recent' not in out

    def test_the_note_tells_the_model_what_one_way_means(self, monkeypatch):
        out = self._out(monkeypatch)
        assert "'one_way'" in out['note']
        assert 'tolerance' in out['note']

    def test_the_reading_notes_point_at_it(self, monkeypatch):
        """실려 있다는 것과 닿는다는 것은 다르다 — `_reading` 이 그 다리다."""
        out = self._out(monkeypatch)
        brief = _brief([], sensors={})
        brief['target_check'] = out
        notes = ' '.join(S._plot_reading_notes(brief))
        assert 'target_check.recent' in notes
        assert 'one_way' in notes


class TestTheLookBackIsCountedLikeTheJournal:
    def test_it_reuses_the_journals_counter(self):
        """여기서 따로 세면 같은 구획을 두고 화면과 AI 가 다른 숫자를 말한다."""
        import inspect
        from aot.aot_flask.geo import plot_journal as PJ
        src = inspect.getsource(PJ.recent_target_drift)
        assert 'target_drift(buckets)' in src
        assert 'attach_targets(' in src
        assert 'env_channel_series(' in src

    def test_the_cache_key_carries_the_window_end(self):
        """`on` 이 없으면 창은 "오늘" 인데, 그것을 키에 안 담으면 23:55 에
        담긴 어제 창이 00:01 에도 TTL(10분) 안이라 그대로 나온다 — 응답의
        from/to 가 어제로 찍히고 오늘치가 빠진다."""
        import inspect
        from aot.aot_flask.geo import plot_journal as PJ
        src = inspect.getsource(PJ.recent_target_drift)
        assert 'cache_key = (plot.unique_id, int(days),' in src
        assert 'end_date.isoformat())' in src
        # 키를 만들기 전에 창의 끝날이 정해져 있어야 한다.
        assert src.index('end_date = on or') < src.index('cache_key =')

    def test_it_only_asks_for_measurements_it_can_compare(self):
        """안 볼 채널을 InfluxDB 에 묻는 비용이 사람이 기다리는 시간이 된다."""
        import inspect
        from aot.aot_flask.geo import plot_journal as PJ
        src = inspect.getsource(PJ.recent_target_drift)
        assert "t.get('observable') is False" in src
        assert "want_stats=('mean',)" in src


class TestTargetsCanBeFedBackFromMeasurements:
    """단계 일수는 실측으로 갱신되는데 **목표값은 갱신할 길이 없었다.**

    문헌 기준이 이 현장에서 성립하지 않게 되는 상황이 정확히 거기서 막혔다 —
    실측(김제 3-1): 야간온도 목표 22.0 인 단계의 실측 중앙값이 25.58 이었고,
    작기 내내 모든 단계가 그랬다.
    """

    def test_the_review_never_averages_across_sensors(self):
        """캐노피 안팎이 다른 값을 내는 것이 정상이라, 하나로 접으면 어느
        센서도 말하지 않은 숫자가 목표가 된다(§C-0 과 같은 규칙)."""
        import inspect
        from aot.aot_flask.geo import plot_journal as PJ
        src = inspect.getsource(PJ.measured_stage_targets)
        assert "'sensors-differ'" in src
        assert "len(sensors) > 1" in src

    def test_the_quantile_is_an_observed_value_not_an_interpolation(self):
        """보간하면 그 자리에 **실제로 잰 적 없는 숫자**가 생긴다."""
        from aot.aot_flask.geo import plot_journal as PJ
        import inspect
        src = inspect.getsource(PJ.measured_stage_targets)
        assert 'int(round((len(values) - 1) * q))' in src

    def test_adopting_keeps_the_source_where_it_is_ambiguous(self):
        """지어낸 숫자가 다음 작기의 목표가 되는 일이 이 게이트의 반대편이다."""
        import inspect
        from aot.aot_flask.geo import plot_io
        src = inspect.getsource(plot_io._target_review)
        for why in ("'follows-curve'", "'out-of-range'"):
            assert why in src
        # 사유가 있으면 제안값을 지운다 — 둘이 서로를 부정하면 안 된다.
        assert "item['suggest'] = None" in src

    def test_it_does_not_write_into_the_source_programmes_dict(self):
        """구획에 목표 오버라이드가 없는 단계에서는 `effective_stages` 가
        **원본 프로그램의 stages JSON 에 든 dict 를 그대로** 넘긴다(로컬 실측:
        69개 단계가 객체를 공유했다). 얕은 복사로 떼어졌다고 믿고 그 위에 쓰면
        사용자가 고르지도 않은 원본 프로그램의 목표가 실측값으로 덮인다."""
        import inspect
        from aot.aot_flask.geo import plot_io
        src = inspect.getsource(plot_io.save_as_program)
        assert "item['targets'] = dict(item['targets'])" in src

    def test_showing_is_the_default_and_writing_is_opt_in(self):
        import inspect
        from aot.aot_flask.geo import plot_io
        sig = inspect.signature(plot_io.save_as_program)
        assert sig.parameters['adopt_targets'].default is False

    def test_a_failure_to_read_measurements_does_not_block_registering(self):
        """되먹임을 붙이려다 원래 되던 일을 깨뜨리면 안 된다."""
        import inspect
        from aot.aot_flask.geo import plot_io
        src = inspect.getsource(plot_io._target_review)
        assert 'except Exception' in src
        assert 'return None, [], []' in src

    def test_the_tool_tells_the_model_not_to_fill_the_gaps_itself(self):
        import inspect
        src = inspect.getsource(S.save_plot_schedule_as_program)
        assert 'targets_kept' in src
        assert 'do not fill those in' in src


class TestTheReviewReachesTheScreen:
    """되먹임은 **보여야** 열린다. API 응답에만 실리면 화면 사용자에게는
    여전히 "목표는 원본 그대로" 다 — AI 를 안 쓰는 사용자가 이 저장소의
    기준이다(`docs` 의 화면 우선 원칙)."""

    import os as _os
    _ROOT = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')

    def _read(self, *parts):
        import io
        import os
        with io.open(os.path.join(self._ROOT, *parts), encoding='utf-8') as fh:
            return fh.read()

    def test_the_renderer_is_shared_not_written_twice(self):
        """지도 위젯과 구획 페이지가 각자 짜면 한쪽만 고쳐진다."""
        src = self._read('aot_flask', 'static', 'js', 'common',
                         'aot-target-review.js')
        assert 'AoTTargetReview' in src
        for path in (('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                      'aot-map-plot.js'),
                     ('aot_flask', 'static', 'js', 'geo', 'plots-page.js')):
            assert 'AoTTargetReview' in self._read(*path)

    def test_it_makes_no_new_css(self):
        """공용 클래스를 쓴다 — 같은 성격의 글이 화면마다 다른 모양으로 서면
        사용자는 둘이 다른 것인 줄 안다."""
        src = self._read('aot_flask', 'static', 'js', 'common',
                         'aot-target-review.js')
        assert 'aot-modal-option-row' in src
        assert 'aot-modal-subgroup-title' in src
        assert 'style=' not in src

    def test_it_uses_classes_that_every_page_loads(self):
        """처음엔 지도 개요 카드의 `.aot-ov-*` 로 짰는데, 그 규칙이 든
        `aot-sensor-label.css` 는 **구획 페이지에 안 실린다** — 브라우저로
        보니 두 칸이 접혀 한 줄씩 흘렀다(2026-09-04 실측). 공용 조각은
        layout 이 늘 싣는 것만 써야 한다."""
        src = self._read('aot_flask', 'static', 'js', 'common',
                         'aot-target-review.js')
        assert 'aot-ov-row' not in src
        layout = self._read('aot_flask', 'templates', 'layout.html')
        assert 'aot-modal-modern.css' in layout
        assert 'aot-target-review.js' in layout

    def test_the_sentence_is_not_squeezed_into_a_value_cell(self):
        """두 칸짜리 행의 오른쪽에 긴 문장을 넣으면 우측 정렬로 찢어진다
        (개요 카드가 적어 둔 2026-08-26 지적)."""
        src = self._read('aot_flask', 'static', 'js', 'common',
                         'aot-target-review.js')
        assert 'aot-modal-body-text' in src

    def test_sensors_that_differ_get_a_line_each(self):
        src = self._read('aot_flask', 'static', 'js', 'common',
                         'aot-target-review.js')
        assert 'sensors.length === 1' in src
        assert "' · ' + s.sensor" in src

    def test_a_stage_with_no_readings_makes_no_empty_line(self):
        src = self._read('aot_flask', 'static', 'js', 'common',
                         'aot-target-review.js')
        assert 'if (!sensors.length) return;' in src

    def test_the_bundle_was_rebuilt(self):
        """소스만 고치면 지도 위젯에는 반영되지 않는다(번들 필수)."""
        assert 'aot-ov-sched-reg-review' in self._read(
            'aot_flask', 'static', 'js', 'dist', 'aot-map-widget.bundle.js')

    def test_the_new_strings_are_translated(self):
        ko = self._read('aot_flask', 'translations', 'ko', 'LC_MESSAGES',
                        'messages.po')
        assert 'msgid "Target vs what this plot measured"' in ko
        assert '이 구획이 실제로 잰 값과 목표' in ko
