# coding=utf-8
"""시나리오·분석 이력·작동 시계열 저장 계약 (예보·트윈 데이터 관리 D7, 설계 §6).

지키는 계약:
1. 측정 모양 — 시나리오 곡선은 기본 예측과 채널·분위수가 같고 태그 `scenario` 만 더한다(`device_id` = 대상 id, 머리말·`_lead` 없음).
   분석 이력은 발행 시각 `t0` 앞만 쓴다. 작동 시계열은 `channel` 태그가 없고 `device_id` = 대상 id.
2. 머리말 채널은 추가만 한다(기존 번호 불변, 15~17·30~32 신설).
3. 새 측정은 계층 표(`influx_layers`)에 있고 구획 삭제 훅(`_CURVES`/`_HISTORY`)이 따른다.
4. 시나리오: 대상당 20건, 고정은 곡선 복사가 성공해야 서고, 곡선이 만료된 것은 고정할 수 없다, `expires_at` 은 곡선 만료.
5. 발행 색인은 머리말에서 채운다. 읽기 API 는 `scenario`·`post` 로 측정을 바꾸고 계보를 싣는다.

Influx 는 이 테스트에 없다 — 읽기·쓰기 함수 대역이 받은 인자를 본다.
"""
import time
from unittest import mock

import pytest

from aot.tests.test_settings_matter_routes import _MatterAppFixture
from aot.twin import output as O
from aot.twin.types import Point, Status, TargetKind, TwinOutput
from aot.utils import data_retention as R
from aot.utils import influx_layers as L
from aot.utils import twin_store as S

PLOT = '53bdbec9-3507-4944-a7c2-778758196d8a'
T0 = 1792641600.0          # 2026-10-27 04:00 UTC (정시)


def _field(t0=T0, n=4, hourly=True):
    days = [t0 - 2 * 86400.0 + k * 86400.0 for k in range(n)]      # 앞 둘은 t0 이전
    q = {'theta_root': {'p10': [20.0] * n, 'p50': [22.0] * n, 'p90': [24.0] * n},
         'GDD': {'p50': [5.0] * n}}
    out = TwinOutput(kind=TargetKind.FIELD, target_id=PLOT, t0=t0, grids={'daily': days},
                     quantiles={'daily': q}, events={'daily': {'frost': [0.1] * n}})
    if hourly:
        hrs = [t0 - 3600.0, t0, t0 + 3600.0]
        out.grids['hourly'] = hrs
        out.quantiles['hourly'] = {'T': {'p10': [1.0] * 3, 'p50': [2.0] * 3, 'p90': [3.0] * 3}}
    out.meta = {'status': int(Status.OK), 'valid_until': t0 + 36 * 3600.0, 'model_rev': 3, 'fc_issue_epoch': t0 - 600.0,
                'fc_cal_rev': 2, 'obs_origin': 2, 'weather_src': 5, 'plan_src': 1, 'effects_modeled': 2,
                'effects_unmodeled': 1, 'sync_rmse_theta_1d': 1.5, 'coverage_80': 0.8}
    return out


def _facility(t0=T0):
    g = [t0 - 600.0, t0, t0 + 600.0]
    q = {'T': {'p10': [18.0] * 3, 'p50': [20.0] * 3, 'p90': [22.0] * 3}}
    out = TwinOutput(kind=TargetKind.FACILITY, target_id='fac1', facility='abcd1234', t0=t0, grids={'fast': g},
                     quantiles={'fast': q}, events={'fast': {'frost': [0.2] * 3}})
    out.meta = {'status': 0, 'valid_until': t0 + 3600.0, 'plan_src': 2}
    return out


class TestMeasurementShape:
    def test_scenario_curves_mirror_the_baseline_with_a_scenario_tag(self):
        base = [p for p in O.flatten(_field()) if p.measurement in (O.M_FLD, O.M_FLD_H)]
        scn = O.flatten_scenario(_field(), 'ab12cd34')
        assert {(p.channel, p.timestamp, p.value) for p in scn if p.measurement == O.M_FLD_SCN} == \
            {(p.channel, p.timestamp, p.value) for p in base if p.measurement == O.M_FLD}
        assert {(p.channel, p.timestamp, p.value) for p in scn if p.measurement == O.M_FLD_SCN_H} == \
            {(p.channel, p.timestamp, p.value) for p in base if p.measurement == O.M_FLD_H}
        assert all(p.tags['scenario'] == 'ab12cd34' and p.device_id == PLOT for p in scn)
        assert not any(p.measurement.endswith(('_lead', '_meta')) for p in scn)

    def test_facility_scenario_curves_keep_the_facility_tag(self):
        scn = O.flatten_scenario(_facility(), 'ab12cd34')
        assert scn and {p.measurement for p in scn} == {O.M_FAC_SCN}
        assert all(p.tags == {'facility': 'abcd1234', 'scenario': 'ab12cd34'} and p.device_id == 'fac1' for p in scn)

    def test_baseline_is_a_reserved_scenario_id(self):
        for bad in ('baseline', ''):
            with pytest.raises(ValueError):
                O.flatten_scenario(_field(), bad)

    def test_post_writes_only_the_past_and_no_events_or_gdd(self):
        pts = O.flatten_post(_field())
        assert pts
        daily = [p for p in pts if p.measurement == O.M_FLD_POST]
        assert daily and all(p.timestamp < T0 for p in pts)
        assert {p.channel for p in daily} == {0, 1, 2}                 # 이 입력에는 θ_root 만 있다
        assert not any(p.channel in O.FIELD_DAILY_Q.values() and p.channel >= 50 and p.channel < 90 for p in pts)
        assert {p.measurement for p in pts} == {O.M_FLD_POST, O.M_FLD_POST_H}

    def test_facility_post_uses_the_fast_grid_before_t0(self):
        pts = O.flatten_post(_facility())
        assert {p.measurement for p in pts} == {O.M_FAC_POST}
        assert [p.timestamp for p in pts if p.channel == 1] == [T0 - 600.0]

    def test_act_series_have_no_channel_tag_and_the_target_as_device_id(self):
        pts = O.act_points(TargetKind.FIELD, PLOT, 'irrigation_mm', 'duty_log', [T0, T0 + 3600.0], [1.5, float('nan')])
        assert len(pts) == 1
        p = pts[0]
        assert (p.measurement, p.device_id, p.channel) == (O.M_ACT, PLOT, None)
        assert p.tags == {'target': PLOT, 'effect': 'irrigation_mm', 'basis': 'duty_log', 'scenario': 'baseline',
                          'dev': 'all'}

    def test_act_rejects_unknown_effect_and_basis(self):
        with pytest.raises(ValueError):
            O.act_points(TargetKind.FIELD, PLOT, 'vent', 'actual', [T0], [1.0])
        with pytest.raises(ValueError):
            O.act_points(TargetKind.FACILITY, 'fac1', 'vent', 'guess', [T0], [1.0])


class TestContractNumbers:
    def test_header_channels_only_grow(self):
        fac, fld = O.FACILITY_META, O.FIELD_META
        assert (fac['weather_src'], fac['fc_issue_epoch'], fac['obs_origin']) == (11, 12, 14)
        assert (fac['plan_src'], fac['effects_modeled'], fac['effects_unmodeled']) == (15, 16, 17)
        assert (fld['rain_fc_days'], fld['fc_issue_epoch'], fld['obs_origin']) == (26, 27, 29)
        assert (fld['plan_src'], fld['effects_modeled'], fld['effects_unmodeled']) == (30, 31, 32)
        assert (fld['theta_fc'], fld['theta_thr'], fld['obs_a'], fld['obs_b']) == (33, 35, 36, 37)
        for table in (fac, fld):
            assert len(set(table.values())) == len(table)               # 번호가 겹치지 않는다

    def test_headers_carry_the_new_lineage_columns(self):
        meta = {p.channel: p.value for p in O.flatten(_field()) if p.measurement == O.M_FLD_META}
        assert meta[30] == 1.0 and meta[31] == 2.0 and meta[32] == 1.0
        fac = {p.channel: p.value for p in O.flatten(_facility()) if p.measurement == O.M_FAC_META}
        assert fac[15] == 2.0

    def test_every_new_measurement_has_a_layer(self):
        want = {O.M_FAC_SCN: L.LAYER_CALC, O.M_FLD_SCN: L.LAYER_CALC, O.M_FLD_SCN_H: L.LAYER_CALC, O.M_ACT: L.LAYER_CALC,
                O.M_FAC_POST: L.LAYER_HIST, O.M_FLD_POST: L.LAYER_HIST, O.M_FLD_POST_H: L.LAYER_HIST}
        for m, layer in want.items():
            assert L.layer_of_measurement(m) == layer, m
        # 구획 삭제 훅이 따른다: 최신 곡선 묶음에 시나리오·작동 시계열, 이력 묶음에 분석 이력
        assert {O.M_FLD_SCN, O.M_FAC_SCN, O.M_ACT} <= set(R._CURVES)
        assert {O.M_FLD_POST, O.M_FAC_POST, O.M_FLD_POST_H} <= set(R._HISTORY)

    def test_pinnable_measurements_read_the_history_bucket_too(self):
        lay = L.Layout('layered', {L.LAYER_OBS: 'aot_db', L.LAYER_FC: 'aot_fc', L.LAYER_CALC: 'aot_calc',
                                   L.LAYER_HIST: 'aot_hist'}, 'aot_db', '')
        with mock.patch.object(L, 'layout', return_value=lay):
            assert L.read_buckets(O.M_FLD_SCN) == ['aot_calc', 'aot_hist', 'aot_db']
            assert L.read_buckets(O.M_ACT) == ['aot_calc', 'aot_hist', 'aot_db']
            assert L.read_buckets(O.M_FLD) == ['aot_calc', 'aot_db']          # 기본 예측은 사본이 없다
            assert L.pinned_copy_bucket() == 'aot_hist'
        legacy = L.Layout('legacy', {k: 'aot_db' for k in L.LAYERS}, 'aot_db', '')
        with mock.patch.object(L, 'layout', return_value=legacy):
            assert L.read_buckets(O.M_FLD_SCN) == ['aot_db']
            assert L.pinned_copy_bucket() is None

    def test_scenario_and_post_names_pair_up(self):
        assert O.SCENARIO_OF == {O.M_FAC: O.M_FAC_SCN, O.M_FLD: O.M_FLD_SCN, O.M_FLD_H: O.M_FLD_SCN_H}
        assert O.POST_OF == {O.M_FAC: O.M_FAC_POST, O.M_FLD: O.M_FLD_POST, O.M_FLD_H: O.M_FLD_POST_H}
        assert (O.SCENARIO_MEASUREMENTS | O.POST_MEASUREMENTS) <= O.MEASUREMENTS


class TestScenarioStore(_MatterAppFixture):
    def test_create_defaults_and_expiry_is_the_curve_expiry(self):
        with self.app.app_context():
            row = S.create_scenario('field', PLOT, label='  비 없음  ', overrides={'weather': [{'var': 'precip_mm', 'op': 'set', 'value': 0, 't0': T0}]}, now=T0)
            assert len(row.id) == 8 and row.id != 'baseline'
            assert (row.status, row.pinned, row.label) == ('queued', False, '비 없음')
            assert row.expires_at == T0 + 30 * 86400.0                  # 곡선 30일
            d = S.scenario_dict(row)
            assert d['def_expires_at'] == T0 + 365 * 86400.0 and d['layer'] == 'L3' and d['schema_version'] == 1
            assert d['target'] == {'kind': 'field', 'id': PLOT}

    def test_base_run_defaults_to_the_latest_ok_run_and_base_t0_follows(self):
        with self.app.app_context():
            S.record_run('field', PLOT, T0 - 7200, {'status': 0})
            S.record_run('field', PLOT, T0, {'status': 0})
            S.record_run('field', PLOT, T0 + 3600, {'status': 9})        # 실패한 발행은 바탕이 못 된다
            row = S.create_scenario('field', PLOT, now=T0)
            assert row.base_run == S.run_id_of(PLOT, T0)
            assert S.base_t0_map([row]) == {row.base_run: T0}
            # 색인이 지워져도 run_id 앞 숫자로 t0 를 푼다
            S.expire_runs(T0 + 9999 * 86400.0, 1)
            assert S.base_t0_map([row]) == {row.base_run: float(int(T0))}

    def test_overrides_are_opaque_but_shape_checked(self):
        with self.app.app_context():
            for bad in ({'nope': []}, {'weather': {}}, 'x', ['a']):
                with pytest.raises(S.StoreError):
                    S.create_scenario('field', PLOT, overrides=bad)
            with pytest.raises(S.StoreError):
                S.create_scenario('field', PLOT, overrides={'supply': ['x' * (70 * 1024)]})
            with pytest.raises(S.StoreError):
                S.create_scenario('plot', PLOT)
            with pytest.raises(S.StoreError):
                S.create_scenario('field', PLOT, future_input_mode='dream')
            with pytest.raises(S.StoreError):
                S.create_scenario('field', '')

    def test_meaning_of_the_assumptions_is_checked_at_create(self):
        """E2: 실행기가 못 돌릴 정의는 만들 때 422 — 나중에 실패로 남기지 않는다."""
        with self.app.app_context():
            bad = [dict(kind='facility', overrides={'actuators': [{'channel': 'heat', 't0': 1, 'value': 300}]}),
                   dict(kind='facility', overrides={'weather': [{'var': 'zz', 'op': 'add', 'value': 1, 't0': 1}]}),
                   dict(kind='field', overrides={'actuators': [{'channel': 'irrigation_mm', 't0': 1, 'value': 3}]}),
                   dict(kind='facility', overrides={}, base_mode='schedule'),
                   dict(kind='facility', overrides={}, future_input_mode='policy')]
            for kw in bad:
                kind = kw.pop('kind')
                with pytest.raises(S.StoreError) as e:
                    S.create_scenario(kind, 'fac1', **kw)
                assert e.value.status == 422
            ok = S.create_scenario('field', PLOT, future_input_mode='whatif', overrides={
                'actuators': [{'channel': 'irrigation_mm', 't0': T0, 't1': T0 + 7200, 'value': 5, 'unit': 'mm'}]})
            assert ok.status == 'queued'

    def test_summaries_are_computed_not_stored(self):
        with self.app.app_context():
            row = S.create_scenario('facility', 'fac1', overrides={
                'weather': [{'var': 'temp_c', 'op': 'add', 'value': 2, 't0': 1, 't1': 9}],
                'actuators': [{'channel_or_device_uid': 'vent', 't0': 1, 't1': 5, 'value': 30, 'unit': '%'}]})
            d = S.scenario_dict(row)
            assert d['weather_assumption'] == [{'var': 'temp_c', 'op': 'add', 'value': 2, 'from': 1, 'to': 9}]
            assert d['actuator_plan'] == [{'channel': 'vent', 'from': 1, 'to': 5, 'value': 30, 'unit': '%'}]
            assert 'weather_assumption' not in row.__table__.columns and 'actuator_plan' not in row.__table__.columns

    def test_twenty_per_target_then_a_delete_suggestion(self):
        with self.app.app_context():
            ids = [S.create_scenario('field', PLOT, now=T0 + i).id for i in range(S.SCENARIO_LIMIT)]
            other = S.create_scenario('field', 'another', now=T0)       # 다른 대상은 따로 센다
            assert other.id
            S.get_scenario(ids[0]).pinned = True
            from aot.aot_flask.extensions import db
            db.session.commit()
            with pytest.raises(S.StoreError) as e:
                S.create_scenario('field', PLOT, now=T0 + 99)
            assert e.value.status == 409
            assert e.value.extra == {'limit': 20, 'suggest_delete': [ids[1]]}   # 고정은 제안하지 않는다, 오래된 미고정부터

    def test_status_transitions_and_lineage(self):
        with self.app.app_context():
            row = S.create_scenario('field', PLOT, now=T0)
            S.mark_running(row.id)
            assert S.get_scenario(row.id).status == 'running'
            S.mark_failed(row.id, 'x' * 500)
            assert len(S.get_scenario(row.id).fail_reason) == 200
            S.mark_running(row.id)                                     # 실패한 것은 다시 돌릴 수 있다
            S.mark_done(row.id, model_rev=3, cal_rev=0, fc_issue_epoch=T0 - 60, weather_src=5, obs_origin=1,
                        effects=[{'kind': 'vent', 'channel': 'vent', 'status': 'partial', 'source': 'estimated'},
                                 {'kind': 'mystery', 'channel': None, 'status': 'unknown', 'source': 'unknown'}],
                        now=T0 + 10)
            d = S.scenario_dict(S.get_scenario(row.id))
            assert (d['status'], d['model_rev'], d['cal_rev'], d['obs_origin'], d['fail_reason']) == ('done', 3, 0, 1, None)
            assert d['effects_unmodeled'] == 2 and d['finished_at'] == T0 + 10
            with pytest.raises(S.StoreError):
                S.mark_done(row.id, effects=[{'kind': 'x', 'status': 'weird'}])
            with pytest.raises(S.StoreError):
                S.mark_done('nope')

    def test_executor_claims_oldest_queued_and_recovers_after_a_crash(self):
        with self.app.app_context():
            a = S.create_scenario('field', PLOT, now=T0)
            b = S.create_scenario('field', PLOT, now=T0 + 5)
            assert S.claim_next_queued().id == a.id and S.get_scenario(a.id).status == 'running'
            assert S.claim_next_queued().id == b.id and S.claim_next_queued() is None
            assert S.requeue_running() == 2                            # 실행기가 다시 떴다 — 도중에 멈춘 것은 모두 낡은 것
            assert S.claim_next_queued().id == a.id                    # 먼저 요청한 것부터 다시

    def test_done_moves_base_run_to_the_published_run_that_was_used(self):
        with self.app.app_context():
            S.record_run('field', PLOT, T0, {'status': 0})
            row = S.create_scenario('field', PLOT, now=T0)
            assert row.base_run == S.run_id_of(PLOT, T0)
            S.mark_done(row.id, base_run=S.run_id_of(PLOT, T0 + 3600))
            d = S.scenario_dict(S.get_scenario(row.id), S.base_t0_map([S.get_scenario(row.id)]).get(S.get_scenario(row.id).base_run))
            assert d['base_run'] == S.run_id_of(PLOT, T0 + 3600) and d['base_t0'] == T0 + 3600

    def test_requeue_refreshes_base_and_clears_old_curves_but_not_records(self):
        with self.app.app_context():
            S.record_run('field', PLOT, T0, {'status': 0})
            row = S.create_scenario('field', PLOT, now=T0)
            with pytest.raises(S.StoreError) as e:
                S.requeue(row.id)                                      # 아직 대기 중
            assert e.value.status == 409
            S.mark_running(row.id)
            S.mark_done(row.id, now=T0 + 60)
            S.record_run('field', PLOT, T0 + 7200, {'status': 0})
            with mock.patch.object(S, 'delete_curves', return_value=2) as dc:
                r = S.requeue(row.id, now=T0 + 8000)
            dc.assert_called_once_with(row.id, include_hist=False)
            assert (r.status, r.finished_at, r.base_run) == ('queued', None, S.run_id_of(PLOT, T0 + 7200))
            assert r.expires_at == T0 + 8000 + 30 * 86400.0
            S.mark_running(row.id)
            S.mark_done(row.id)
            with mock.patch.object(S, 'copy_to_hist', return_value=0):
                S.pin_scenario(row.id)
            with pytest.raises(S.StoreError) as e:
                S.requeue(row.id)
            assert e.value.status == 409                               # 고정은 기록이다
            with pytest.raises(S.StoreError):
                S.requeue('nope')

    def test_listing_filters_by_target(self):
        with self.app.app_context():
            a = S.create_scenario('field', PLOT, now=T0)
            S.create_scenario('facility', 'fac1', now=T0 + 1)
            assert [r.id for r in S.list_scenarios('field', PLOT)] == [a.id]
            assert len(S.list_scenarios()) == 2


class TestPin(_MatterAppFixture):
    def _done(self, **kw):
        row = S.create_scenario('field', PLOT, now=T0)
        S.mark_done(row.id, now=T0 + 5)
        return row

    def test_pin_copies_to_history_then_keeps_forever(self):
        with self.app.app_context():
            row = self._done()
            with mock.patch.object(S, 'copy_to_hist', return_value=42) as cp:
                out = S.pin_scenario(row.id)
            cp.assert_called_once()
            assert out.pinned is True and out.expires_at is None and out.copied_points == 42
            assert S.scenario_dict(out)['def_expires_at'] is None

    def test_copy_failure_does_not_pin(self):
        with self.app.app_context():
            row = self._done()
            with mock.patch.object(S, 'copy_to_hist', side_effect=RuntimeError('influx down')):
                with pytest.raises(S.StoreError) as e:
                    S.pin_scenario(row.id)
            assert e.value.status == 503
            assert S.get_scenario(row.id).pinned is False and S.get_scenario(row.id).expires_at is not None

    def test_expired_curves_cannot_be_pinned(self):
        with self.app.app_context():
            row = self._done()
            row.status = 'curve_expired'
            with pytest.raises(S.StoreError) as e:
                S.pin_scenario(row.id)
            assert e.value.status == 409

    def test_pinning_a_running_scenario_copies_when_it_finishes(self):
        with self.app.app_context():
            row = S.create_scenario('field', PLOT, now=T0)
            with mock.patch.object(S, 'copy_to_hist') as cp:
                S.pin_scenario(row.id)
                cp.assert_not_called()                                  # 아직 곡선이 없다
                S.mark_done(row.id, now=T0 + 5)
                cp.assert_called_once()

    def test_copy_reads_by_scenario_tag_and_writes_to_the_history_layer(self):
        with self.app.app_context():
            row = self._done()
            rd = mock.Mock(side_effect=lambda m, dev, tags, lo, hi: (
                [(T0, 22.0, {'channel': '1', 'scenario': row.id, 'target': 'field'})] if m == O.M_FLD_SCN else
                [(T0, 50.0, {'target': PLOT, 'effect': 'irrigation_mm', 'basis': 'plan', 'scenario': row.id,
                             'dev': 'all'})] if m == O.M_ACT else []))
            wr = mock.Mock(return_value=2)
            with mock.patch.object(L, 'pinned_copy_bucket', return_value='aot_hist'), \
                    mock.patch('aot.utils.influx.read_layer_points', rd), \
                    mock.patch('aot.utils.influx.write_influxdb_points', wr):
                assert S.copy_to_hist(row, T0) == 2 * 2             # 측정마다 한 번씩 쓴다(대역이 2 를 돌려준다)
            assert all(c.args[2] == {'scenario': row.id} for c in rd.call_args_list)
            assert all(c.kwargs == {'layer': L.LAYER_HIST} for c in wr.call_args_list)
            written = [p for c in wr.call_args_list for p in c.args[0]]
            by_m = {p.measurement: p for p in written}
            assert by_m[O.M_FLD_SCN].channel == 1 and by_m[O.M_FLD_SCN].tags == {'scenario': row.id, 'target': 'field'}
            assert by_m[O.M_ACT].channel is None and by_m[O.M_ACT].device_id == PLOT

    def test_one_bucket_mode_has_nothing_to_copy(self):
        with self.app.app_context():
            row = self._done()
            with mock.patch.object(L, 'pinned_copy_bucket', return_value=None), \
                    mock.patch('aot.utils.influx.read_layer_points') as rd:
                assert S.copy_to_hist(row) == 0
            rd.assert_not_called()


class _Fake:
    def __init__(self):
        self.deletes = []
        self.closed = False

    def delete_api(self):
        outer = self

        class D:
            def delete(self, start, stop, pred, bucket=None, org=None):
                outer.deletes.append((bucket, pred))
        return D()

    def close(self):
        self.closed = True


class TestDeleteAndTargetLifecycle(_MatterAppFixture):
    def test_delete_scenario_removes_pinned_copies_too(self):
        f = _Fake()
        with self.app.app_context(), mock.patch.object(R, '_admin', return_value=(f, 'aot_db')):
            row = S.create_scenario('field', PLOT, now=T0)
            out = S.delete_scenario(row.id)
            assert S.get_scenario(row.id) is None and out['curves'] > 0
        hist = {p for b, p in f.deletes if b == 'aot_hist'}
        assert '_measurement="env_twin_scn_field" AND scenario="{}"'.format(row.id) in hist
        assert '_measurement="env_twin_act" AND scenario="{}"'.format(row.id) in hist
        assert {b for b, _ in f.deletes} == {'aot_calc', 'aot_hist', 'aot_db'}

    def test_expiry_leaves_pinned_copies_alone(self):
        f = _Fake()
        with self.app.app_context():
            row = S.create_scenario('field', PLOT, now=T0 - 40 * 86400.0)
            R.expire_scenarios(f, 'aot_db', T0)
        assert f.deletes and all(b != 'aot_hist' for b, _ in f.deletes)   # 만료는 미고정 곡선만, 사본 버킷은 건드리지 않는다

    def test_target_delete_keeps_pinned_scenarios_until_history_is_purged(self):
        f = _Fake()
        with self.app.app_context(), mock.patch.object(R, '_admin', return_value=(f, 'aot_db')):
            plain = S.create_scenario('field', PLOT, now=T0).id
            pinned = S.create_scenario('field', PLOT, now=T0 + 1).id
            S.record_run('field', PLOT, T0, {'status': 0})
            S.get_scenario(pinned).pinned = True
            R.purge_target(PLOT, history=False)
            assert S.get_scenario(plain) is None and S.get_scenario(pinned) is not None
            assert not any(b == 'aot_hist' for b, _ in f.deletes)        # 곡선만 지우고 고정 사본·이력은 남긴다
            f.deletes.clear()
            R.purge_target(PLOT, history=True)
            assert S.get_scenario(pinned) is None and S.list_runs(PLOT) == []
            assert any(b == 'aot_hist' and 'env_twin_act' in p for b, p in f.deletes)


class TestRunIndex(_MatterAppFixture):
    def test_headers_in_written_points_become_run_rows(self):
        pts = O.flatten(_field()) + O.flatten(_facility())
        found = {(r['kind'], r['id']): r for r in S.runs_from_points(pts)}
        assert set(found) == {('field', PLOT), ('facility', 'fac1')}
        assert found[('field', PLOT)]['t0'] == T0 and found[('field', PLOT)]['meta']['fc_cal_rev'] == 2.0
        assert S.runs_from_points([p for p in pts if not p.measurement.endswith('_meta')]) == []

    def test_record_run_is_idempotent_and_keeps_lineage(self):
        with self.app.app_context():
            for _ in range(2):
                S.record_runs_from_points(O.flatten(_field()))
            runs = S.list_runs(PLOT)
            assert len(runs) == 1
            d = S.run_dict(runs[0])
            assert d['run_id'] == '{}:{}'.format(int(T0), PLOT)
            assert (d['status'], d['model_rev'], d['cal_rev'], d['weather_src'], d['obs_origin'], d['plan_src']) == \
                (0, 3, 2, None, 2, 1)         # 노지 머리말에는 weather_src 칸이 없다(시설 11 만)
            assert d['fit'] == {'sync_rmse_theta_1d': 1.5, 'coverage_80': 0.8, 'valid_until': T0 + 36 * 3600.0}
            assert d['fc_issue_epoch'] == T0 - 600.0

    def test_sink_records_runs_only_when_given_an_app(self):
        from aot.twin.sources.embedded import EmbeddedSink
        pts = O.flatten(_field())
        with mock.patch('aot.utils.influx.write_influxdb_points', return_value=len(pts)), \
                mock.patch.object(S, 'record_runs_from_points') as rec:
            res = EmbeddedSink('s').write(pts)
            assert res.ok and res.written == len(pts)
            rec.assert_not_called()                                    # 앱이 없으면 적지 않는다(시험·원격 경로)
            app = mock.MagicMock()
            EmbeddedSink('s', app=app).write(pts)
            app.get.return_value.app_context.assert_called_once()
            rec.assert_called_once()

    def test_a_failed_write_records_nothing(self):
        from aot.twin.sources.embedded import EmbeddedSink
        with mock.patch('aot.utils.influx.write_influxdb_points', side_effect=RuntimeError('down')), \
                mock.patch.object(S, 'record_runs_from_points') as rec:
            res = EmbeddedSink('s', app=mock.Mock()).write(O.flatten(_field()))
        assert res.error and not res.ok
        rec.assert_not_called()

    def test_old_runs_are_dropped_after_the_history_retention(self):
        with self.app.app_context():
            S.record_run('field', PLOT, T0 - 800 * 86400.0, {'status': 0})
            S.record_run('field', PLOT, T0 - 10 * 86400.0, {'status': 0})
            assert S.expire_runs(T0, 730) == 1
            assert len(S.list_runs(PLOT)) == 1


class TestLineage:
    def _rows(self, rev=2.0, origin=2.0):
        t = T0
        return {('fld', 0): [(t - 3600.0, 0.0), (t, 0.0)], ('fld', 27): [(t, t - 600.0)], ('fld', 28): [(t, rev)],
                ('fld', 29): [(t, origin)]}

    def test_calibrated_comes_from_the_latest_header(self):
        rows = {(PLOT, ch): v for (_d, ch), v in self._rows().items()}
        lin = S.lineage('field', PLOT, T0, meta_rows=rows)
        assert lin == {'calibrated': True, 'cal_rev': 2, 'fc_issue_epoch': T0 - 600.0, 'origin': 2, 'run_t0': T0}

    def test_original_forecast_is_not_calibrated(self):
        rows = {(PLOT, ch): v for (_d, ch), v in self._rows(rev=0.0).items()}
        assert S.lineage('field', PLOT, T0, meta_rows=rows)['calibrated'] is False

    def test_no_header_means_unknown(self):
        lin = S.lineage('field', PLOT, T0, meta_rows={})
        assert lin['calibrated'] is None and lin['cal_rev'] is None and lin['origin'] is None

    def test_unreadable_influx_still_answers(self):
        with mock.patch('aot.utils.influx.read_twin_many', side_effect=RuntimeError('down')):
            assert S.lineage('field', PLOT, T0)['calibrated'] is None


class TestExecutorQueue(_MatterAppFixture):
    """서비스가 쓰는 DB 대기열(`aot.twin.scenario_queue`) — 꺼내기·완료·실패·도는 동안 지워진 경우."""

    def _queue(self):
        from types import SimpleNamespace
        from aot.twin.scenario_queue import DbScenarioQueue
        return DbScenarioQueue(SimpleNamespace(get=lambda: self.app))

    def test_claim_done_failed_roundtrip(self):
        from aot.twin.scenario_run import ScenarioOutcome
        q = self._queue()
        with self.app.app_context():
            a = S.create_scenario('facility', 'fac1', now=T0)
            b = S.create_scenario('facility', 'fac1', now=T0 + 1)
            got = q.claim()
            assert got['id'] == a.id and got['status'] == 'running' and got['target'] == {'kind': 'facility', 'id': 'fac1'}
            out = ScenarioOutcome(True, t0=T0 + 3600, lineage={'model_rev': 1, 'cal_rev': 2, 'fc_issue_epoch': T0 - 5.0,
                                                              'weather_src': 4, 'obs_origin': 1},
                                  effects=[{'kind': 'heater', 'channel': 'heat', 'status': 'modeled', 'source': 'measured'}])
            q.done(a.id, out)
            from aot.aot_flask.extensions import db
            db.session.expire_all()                                    # 대기열은 자기 앱 문맥에서 썼다 — 바깥 세션의 낡은 사본을 버린다
            row = S.get_scenario(a.id)
            assert (row.status, row.model_rev, row.cal_rev, row.weather_src) == ('done', 1, 2, 4)
            assert row.base_run == S.run_id_of('fac1', T0 + 3600) and row.effects_list()[0]['channel'] == 'heat'
            assert q.claim()['id'] == b.id
            q.failed(b.id, '계산할 수 없다')
            db.session.expire_all()
            assert S.get_scenario(b.id).status == 'failed' and S.get_scenario(b.id).fail_reason == '계산할 수 없다'
            assert q.claim() is None

    def test_deleted_while_running_leaves_no_curves(self):
        from aot.twin.scenario_run import ScenarioOutcome
        q = self._queue()
        with self.app.app_context():
            a = S.create_scenario('facility', 'fac1', now=T0)
            q.claim()
            from aot.aot_flask.extensions import db
            db.session.delete(S.get_scenario(a.id))
            db.session.commit()
            with mock.patch.object(S, 'delete_curves', return_value=1) as dc:
                q.done(a.id, ScenarioOutcome(True, t0=T0))
                q.failed(a.id, 'x')
            assert dc.call_count == 2 and S.get_scenario(a.id) is None


class TestApi(_MatterAppFixture):
    """라우트는 게이트·권한을 대역으로 두고 본문 처리만 본다(권한 자체는 `_cfg_gate` 가 `test_twin_read_api` 에서 눌린다)."""

    def _call(self, cls, method, *args, query='', json=None):
        from aot.aot_flask.api import twin as api
        with self.app.test_request_context('/?' + query, json=json, method='POST' if json is not None else 'GET',
                                           headers={'Accept': 'application/vnd.aot.v1+json'}), \
                mock.patch.object(api, '_cfg_gate'), mock.patch.object(api, '_misc'), \
                mock.patch.object(api.twin_config, 'ui_enabled', return_value=True), \
                mock.patch.object(api.utils_general, 'user_has_permission', return_value=True), \
                mock.patch('flask_login.utils._get_user', return_value=mock.Mock(is_authenticated=True)):
            return getattr(cls(), method)(*args)

    def _abort_code(self, *a, **kw):
        from werkzeug.exceptions import HTTPException
        try:
            self._call(*a, **kw)
        except HTTPException as e:
            return e.code, getattr(e, 'data', {})
        raise AssertionError('should abort')

    def test_create_list_get_pin_delete(self):
        from aot.aot_flask.api import twin as api
        with self.app.app_context():
            body, status = self._call(api.TwinScenarios, 'post', json={
                'target': {'kind': 'field', 'id': PLOT}, 'label': '가정', 'overrides': {'weather': []}})
            assert status == 201 and body['status'] == 'queued' and body['target']['id'] == PLOT
            sid = body['id']
            listing, status = self._call(api.TwinScenarios, 'get', query='target_kind=field&target_id=' + PLOT)
            assert status == 200 and [s['id'] for s in listing['scenarios']] == [sid] and listing['limit'] == 20
            one, _ = self._call(api.TwinScenario, 'get', sid)
            assert one['id'] == sid and one['base_t0'] is None
            with mock.patch.object(S, 'copy_to_hist', return_value=0):
                S.mark_done(sid)
                pinned, status = self._call(api.TwinScenarioPin, 'post', sid)
            assert status == 200 and pinned['pinned'] is True and pinned['expires_at'] is None
            with mock.patch.object(S, 'delete_curves', return_value=3):
                gone, status = self._call(api.TwinScenario, 'delete', sid)
            assert (gone, status) == ({'ok': True, 'curves': 3}, 200)
            assert self._abort_code(api.TwinScenario, 'get', sid)[0] == 404

    def test_rerun_route_and_unrunnable_bodies(self):
        from aot.aot_flask.api import twin as api
        with self.app.app_context():
            body, _ = self._call(api.TwinScenarios, 'post', json={'target': {'kind': 'facility', 'id': 'fac1'}})
            sid = body['id']
            assert self._abort_code(api.TwinScenarioRerun, 'post', sid, json={})[0] == 409     # 아직 대기 중
            S.mark_running(sid)
            S.mark_failed(sid, 'x')
            with mock.patch.object(S, 'delete_curves', return_value=0):
                again, status = self._call(api.TwinScenarioRerun, 'post', sid, json={})
            assert status == 200 and again['status'] == 'queued' and again['fail_reason'] is None
            assert self._abort_code(api.TwinScenarioRerun, 'post', 'nope', json={})[0] == 404
            assert self._abort_code(api.TwinScenarios, 'post', json={
                'target': {'kind': 'facility', 'id': 'fac1'}, 'base_mode': 'schedule'})[0] == 422
            assert self._abort_code(api.TwinScenarios, 'post', json={
                'target': {'kind': 'facility', 'id': 'fac1'},
                'overrides': {'actuators': [{'channel': 'vent', 't0': 1, 'value': -5}]}})[0] == 422

    def test_bad_bodies_and_filters_are_422(self):
        from aot.aot_flask.api import twin as api
        with self.app.app_context():
            assert self._abort_code(api.TwinScenarios, 'post', json={'target': {'kind': 'x', 'id': 'y'}})[0] == 422
            assert self._abort_code(api.TwinScenarios, 'post', json={})[0] == 422
            assert self._abort_code(api.TwinScenarios, 'get', query='target_kind=plot')[0] == 422
            assert self._abort_code(api.TwinActuators, 'get', query='target_id=x')[0] == 422

    def test_limit_overflow_returns_409_with_suggestions(self):
        from aot.aot_flask.api import twin as api
        with self.app.app_context():
            for i in range(S.SCENARIO_LIMIT):
                S.create_scenario('field', PLOT, now=T0 + i)
            code, data = self._abort_code(api.TwinScenarios, 'post', json={'target': {'kind': 'field', 'id': PLOT}})
            assert code == 409 and data.get('limit') == 20 and len(data.get('suggest_delete')) == 1

    def test_runs_route(self):
        from aot.aot_flask.api import twin as api
        with self.app.app_context():
            S.record_run('field', PLOT, T0, {'status': 0, 'model_rev': 3})
            body, status = self._call(api.TwinRuns, 'get', PLOT, query='limit=5')
            assert status == 200 and body['runs'][0]['run_id'] == S.run_id_of(PLOT, T0)

    def _series(self, measurement, query='', device=PLOT):
        from aot.aot_flask.api import twin as api
        with mock.patch('aot.utils.influx.read_twin_series', return_value=[(1.0, 2.0)]) as rd, \
                mock.patch.object(S, 'lineage', return_value={'calibrated': True, 'cal_rev': 2, 'fc_issue_epoch': 5.0,
                                                              'origin': 2, 'run_t0': 9.0}):
            body, status = self._call(api.TwinSeries, 'get', device, measurement, 1, query='start=0&end=100&' + query)
        return body, status, rd

    def test_series_baseline_post_and_scenario_pick_the_measurement(self):
        with self.app.app_context():
            body, status, rd = self._series('env_twin_field')
            assert status == 200 and rd.call_args.args[1] == 'env_twin_field' and 'tag_filters' not in rd.call_args.kwargs
            assert (body['calibrated'], body['cal_rev'], body['fc_issue_epoch'], body['origin'], body['t0']) == \
                (True, 2, 5.0, 2, 9.0)
            body, _, rd = self._series('env_twin_field', 'post=1')
            assert rd.call_args.args[1] == 'env_twin_field_post' and body['post'] is True
            body, _, rd = self._series('env_twin_field_h', 'post=1')
            assert rd.call_args.args[1] == 'env_twin_field_post_h'
            row = S.create_scenario('field', PLOT, now=T0)
            body, _, rd = self._series('env_twin_field', 'scenario=' + row.id)
            assert rd.call_args.args[1] == 'env_twin_scn_field' and rd.call_args.kwargs['tag_filters'] == {'scenario': row.id}
            assert body['scenario'] == row.id
            body, _, rd = self._series('env_twin', 'scenario=' + row.id, device=PLOT)
            assert rd.call_args.args[1] == 'env_twin_scn'

    def test_series_refuses_unknown_or_foreign_scenarios_and_mixed_modes(self):
        from werkzeug.exceptions import HTTPException
        with self.app.app_context():
            row = S.create_scenario('field', PLOT, now=T0)
            for query, code, dev in (('scenario=nope', 404, PLOT), ('scenario=' + row.id, 404, 'someone-else'),
                                     ('post=1&scenario=' + row.id, 422, PLOT), ('post=1&lead=1', 422, PLOT),
                                     ('scenario=' + row.id + '&lead=1', 422, PLOT)):
                try:
                    self._series('env_twin_field', query, device=dev)
                except HTTPException as e:
                    assert e.code == code, query
                else:
                    raise AssertionError(query)
            try:
                self._series('env_twin_lead', 'post=1')
            except HTTPException as e:
                assert e.code == 422
            else:
                raise AssertionError('no post of a lead measurement')
            try:
                self._series('env_twin_scn_field')                     # 시나리오 측정을 직접 부르면 시나리오가 필요하다
            except HTTPException as e:
                assert e.code == 422
            else:
                raise AssertionError('scenario required')

    def test_actuators_group_series_and_filter_by_tags(self):
        from aot.aot_flask.api import twin as api
        rows = [(10.0, 50.0, {'effect': 'irrigation_mm', 'basis': 'duty_log', 'dev': 'all', 'scenario': 'baseline'}),
                (20.0, 60.0, {'effect': 'irrigation_mm', 'basis': 'duty_log', 'dev': 'all', 'scenario': 'baseline'}),
                (10.0, 5.0, {'effect': 'irrigation_mm', 'basis': 'plan', 'dev': 'all', 'scenario': 'baseline'})]
        with self.app.app_context(), \
                mock.patch('aot.utils.influx.read_layer_points', return_value=rows) as rd, \
                mock.patch.object(S, 'lineage', return_value={'calibrated': None, 'cal_rev': None,
                                                              'fc_issue_epoch': None, 'origin': None, 'run_t0': None}):
            body, status = self._call(api.TwinActuators, 'get',
                                      query='target_kind=field&target_id={}&start=0&end=100&effect=irrigation_mm'.format(PLOT))
        assert status == 200
        assert rd.call_args.args[:2] == (O.M_ACT, PLOT)
        assert rd.call_args.args[2] == {'scenario': 'baseline', 'dev': 'all', 'effect': 'irrigation_mm'}
        assert [(s['effect'], s['basis'], len(s['measurements'])) for s in body['series']] == \
            [('irrigation_mm', 'duty_log', 2), ('irrigation_mm', 'plan', 1)]
        assert body['scenario'] == 'baseline'

    def test_chart_route_passes_scenario_and_post(self):
        from aot.aot_flask.api import twin as api
        with self.app.app_context(), mock.patch('aot.utils.twin_chart.plot_chart', return_value={'ok': 1}) as pc:
            body, status = self._call(api.TwinChartPlot, 'get', PLOT, query='scenario=ab&post=1')
        assert status == 200
        assert pc.call_args.kwargs == {'scenario': 'ab', 'post': True}

    def test_chart_route_unknown_scenario_is_404(self):
        from aot.aot_flask.api import twin as api
        err = S.StoreError('scenario not found for this plot', 404)
        with self.app.app_context(), mock.patch('aot.utils.twin_chart.plot_chart', side_effect=err):
            assert self._abort_code(api.TwinChartPlot, 'get', PLOT, query='scenario=zz')[0] == 404


def test_supply_status_and_water_caveats_survive_the_effects_check():
    from aot.utils import twin_store
    rows = twin_store.validate_effects([{'kind': 'pump', 'channel': None, 'status': 'supply', 'source': 'measured'},
                                        {'kind': 'irrigation_drip', 'channel': 'irrigation_mm', 'status': 'partial',
                                         'source': 'estimated', 'caveats': ['pump-over-demand']}])
    assert rows[0]['status'] == 'supply' and 'caveats' not in rows[0]
    assert rows[1]['caveats'] == ['pump-over-demand']
