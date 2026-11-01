# coding=utf-8
"""트윈 출력 계약 검사기(`contract_check.validate`) — 계약 표 밖의 측정·채널·태그를 거르고, 발행 머리말
(`pubs`)로 유효기한을 본다(늦게 온 발행이 새 곡선을 덮어쓰지 않게, 원칙 1).

원래 서버 수신 API 의 검증 시험(aot/tests/test_twin_ingest.py)이었다. 수신 API 를 걷어 낸 뒤(계획서 §9.19)
검증 규칙은 노드 출력의 계약 시험으로 남는다.
"""
import time
import unittest

from aot.twin import output as O
from aot.twin import contract_check as TI
from aot.twin.types import Status, TargetKind, TwinOutput

PLOT = '53bdbec9-3507-4944-a7c2-778758196d8a'
COORD = 'c00rd000-0000-4000-8000-000000000001'


def _field_output(t0, status=Status.OK, n=8):
    days = [t0 + k * 86400.0 for k in range(n)]
    q = {'theta_root': {'p10': [20.0 + k for k in range(n)], 'p50': [22.0 + k for k in range(n)],
                        'p90': [24.0 + k for k in range(n)]},
         'Ks': {'p10': [0.8] * n, 'p50': [0.9] * n, 'p90': [1.0] * n}}
    out = TwinOutput(kind=TargetKind.FIELD, target_id=PLOT, t0=t0,
                     grids={'daily': days}, quantiles={'daily': q},
                     events={'daily': {'water_deficit': [0.1] * n}})
    out.meta = {'status': int(status), 'valid_until': t0 + (36 * 3600.0 if status < 2 else 0.0),
                'horizon_d': n - 1, 'ensemble_size': 64, 'stale_s': 0.0, 'model_rev': 1,
                'rain_src': 2}
    if status >= 2:
        out.grids, out.quantiles, out.events = {}, {}, {}
    return out


def _body(points, with_pubs=True):
    b = {'source': 'aot_twin', 'points': [
        {'m': p.measurement, 'id': p.device_id, 'ch': p.channel, 'ts': p.timestamp, 'v': p.value,
         'tags': dict(p.tags)} for p in points]}
    if with_pubs:
        b['pubs'] = O.publications(points)
    return b


def _now_t0():
    now = time.time()
    return now, float(int(now) // 3600 * 3600)


class ValidateTest(unittest.TestCase):

    def test_real_field_publication_passes_whole(self):
        now, t0 = _now_t0()
        pts = O.flatten(_field_output(t0))
        res = TI.validate(_body(pts), now)
        self.assertEqual((len(res.accepted), res.rejected), (len(pts), 0), dict(res.reasons))
        self.assertTrue({p.measurement for p in res.accepted} >=
                        {'env_twin_field', 'env_twin_field_lead', 'env_twin_field_meta'})

    def test_pubs_let_curve_only_chunk_through(self):
        """원격 쓰기는 조각으로 나뉘어 머리말이 마지막 조각에만 있다 — pubs 가 그 빈자리를 메운다."""
        now, t0 = _now_t0()
        pts = O.flatten(_field_output(t0))
        curve = [p for p in pts if not p.measurement.endswith('_meta')]
        body = _body(curve, with_pubs=False)
        self.assertEqual(TI.validate(body, now).reasons, {'no_publication': len(curve)})
        body['pubs'] = O.publications(pts)
        self.assertEqual(TI.validate(body, now).rejected, 0)

    def test_non_twin_measurement_and_unknown_channel_and_tag(self):
        now, t0 = _now_t0()
        pts = O.flatten(_field_output(t0))
        body = _body(pts)
        body['points'] += [
            {'m': 'temperature', 'id': PLOT, 'ch': 0, 'ts': t0, 'v': 1.0},
            {'m': 'env_twin_field', 'id': PLOT, 'ch': 99, 'ts': t0, 'v': 1.0, 'tags': {'target': 'field'}},
            {'m': 'env_twin_field', 'id': PLOT, 'ch': 1, 'ts': t0, 'v': 1.0, 'tags': {'run': 'abc'}},
            {'m': 'env_twin_field_lead', 'id': PLOT, 'ch': 1, 'ts': t0, 'v': 1.0, 'tags': {'target': 'field'}},
            {'m': 'env_twin_field', 'id': PLOT, 'ch': 70, 'ts': t0, 'v': 1.5, 'tags': {'target': 'field'}},
            {'m': 'env_twin_field', 'id': 'bad id!', 'ch': 1, 'ts': t0, 'v': 1.0},
            {'m': 'env_twin_field', 'id': PLOT, 'ch': True, 'ts': t0, 'v': 1.0},
            {'m': 'env_twin_field', 'id': PLOT, 'ch': 1, 'ts': t0, 'v': float('nan')},
        ]
        res = TI.validate(body, now)
        self.assertEqual(len(res.accepted), len(pts))
        self.assertEqual(dict(res.reasons), {'measurement': 1, 'channel': 2, 'tags': 2, 'value': 2,
                                             'device_id': 1})

    def test_late_publication_refused_whole(self):
        now, _ = _now_t0()
        t0 = float(int(now - 40 * 3600) // 3600 * 3600)        # 36 h 유효기한이 이미 지났다
        pts = O.flatten(_field_output(t0))
        res = TI.validate(_body(pts), now)
        self.assertEqual((len(res.accepted), dict(res.reasons)), (0, {'expired': len(pts)}))

    def test_unsynced_publication_meta_only(self):
        """status ≥ 2 는 즉시 만료(valid_until = t0)가 정상 — 머리말은 받고 곡선은 거부."""
        now, t0 = _now_t0()
        meta = O.flatten(_field_output(t0, Status.UNSYNCED))
        self.assertTrue(meta and all(p.measurement == 'env_twin_field_meta' for p in meta))
        body = _body(meta)
        body['points'].append({'m': 'env_twin_field', 'id': PLOT, 'ch': 1, 'ts': t0 + 86400,
                               'v': 20.0, 'tags': {'target': 'field'}})
        res = TI.validate(body, now)
        self.assertEqual(len(res.accepted), len(meta))
        self.assertEqual(dict(res.reasons), {'curve_on_unusable_status': 1})

    def test_bad_validity_and_windows(self):
        now, t0 = _now_t0()
        for pub, reason in (
                ({'t0': t0, 'status': 0, 'valid_until': t0 - 1}, 'bad_valid_until'),
                ({'t0': t0, 'status': 0, 'valid_until': t0 + 30 * 86400}, 'bad_valid_until'),
                ({'t0': t0 + 86400, 'status': 0, 'valid_until': t0 + 2 * 86400}, 't0_out_of_window'),
                ({'t0': t0, 'status': 7, 'valid_until': t0 + 3600}, 'bad_publication'),
                ({'t0': t0, 'status': 0}, 'bad_publication')):
            body = {'pubs': [dict(pub, family='field', id=PLOT)], 'points': [
                {'m': 'env_twin_field', 'id': PLOT, 'ch': 1, 'ts': t0 + 86400, 'v': 20.0,
                 'tags': {'target': 'field'}}]}
            self.assertEqual(dict(TI.validate(body, now).reasons), {reason: 1}, pub)

    def test_horizon_and_meta_timestamp(self):
        now, t0 = _now_t0()
        pts = O.flatten(_field_output(t0))
        body = _body(pts)
        body['points'] += [
            {'m': 'env_twin_field', 'id': PLOT, 'ch': 1, 'ts': t0 + 20 * 86400, 'v': 20.0,
             'tags': {'target': 'field'}},
            {'m': 'env_twin_field', 'id': PLOT, 'ch': 1, 'ts': t0 - 86400, 'v': 20.0,
             'tags': {'target': 'field'}},
            {'m': 'env_twin_field_meta', 'id': PLOT, 'ch': 4, 'ts': t0 + 60, 'v': 2.5,
             'tags': {'target': 'field'}}]
        self.assertEqual(dict(TI.validate(body, now).reasons),
                         {'ts_out_of_horizon': 2, 'meta_ts': 1})

    def test_unknown_target(self):
        now, t0 = _now_t0()
        pts = O.flatten(_field_output(t0))
        res = TI.validate(_body(pts), now, known_target=lambda fam, dev: False)
        self.assertEqual(dict(res.reasons), {'unknown_target': len(pts)})

    def test_shape_errors(self):
        with self.assertRaises(TI.IngestError) as e:
            TI.validate([], 0)
        self.assertEqual(e.exception.status, 400)
        with self.assertRaises(TI.IngestError) as e:
            TI.validate({'points': [{}] * (TI.MAX_POINTS_PER_REQUEST + 1)}, 0)
        self.assertEqual(e.exception.status, 413)


if __name__ == '__main__':
    unittest.main()
