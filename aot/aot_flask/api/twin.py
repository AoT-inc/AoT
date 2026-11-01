# coding=utf-8
"""트윈 읽기·설정 API (실험, 비공개).

설계: docs/design/digital-twin-node.md · 계약: docs/design/digital-twin.md §6·§7·§10.4.
트윈 결과는 서비스 `aot_twin` 이 Influx 에 직접 쓴다(배포형, 계획서 §9.11). 옛 NAS→개발서버 경로의
수신 API(`POST /api/twin/ingest`)·키 범위 `twin_ingest` 는 2026-10-24 에 걷어 냈다(계획서 §9.19).

`GET /api/twin/series/<device_id>/<measurement>/<channel>?start=&end=[&lead=]` — 읽는 쪽(노드의
소비자 참조 구현·화면 시제품). 측정 API 는 `env_twin*` 를 단위표에 없다고 422 로 막고 "지금까지"
만 읽어 미래 시각인 예측 곡선이 빠진다. 권한은 `view_settings`(측정 읽기와 같다).
`GET /api/twin/series/...?scenario=<id|baseline>&post=1` — 시나리오 곡선(`env_twin_scn*`)·분석 이력(`env_twin_*_post`)을 같은 채널 번호로 읽는다
(설계 §6.8). 모든 응답에 `calibrated`·`cal_rev`·`fc_issue_epoch`·`origin`(최근 발행 머리말의 계보)을 싣는다.
`GET /api/twin/runs/<target_id>` 발행 색인 · `GET|POST /api/twin/scenarios` · `GET|DELETE /api/twin/scenarios/<id>` ·
`POST /api/twin/scenarios/<id>/pin|rerun` · `GET /api/twin/actuators?...` — 시나리오·작동 시계열(`utils/twin_store.py`).
`GET /api/twin/state/duty_log/<device_id>/<channel>?past=` — 출력 가동 이력을 켜짐/꺼짐 계단으로(원격 통로의 상태 계열 읽기).
`GET /api/twin/plots` — 지도 예측 제공자(twin.field)의 구획 묶음.
`GET /api/twin/chart/plot/<id>?back=&ahead=` — 지도 모달 '트윈' 탭 [그래프] 의 구획 묶음(예측·실측 점·비·기온·사건, `utils/twin_chart.py`).
`GET /api/twin/forecast_series?site=&start=&end=&variables=` — 대지에 지정한 예보 입력의 시간별 시계열(지도 슬라이더·AI
예보와 같은 출처, `geo/forecast_series.read`). 한 시간 칸 `[time, end)` 와 해상도·지평·수신 시각을 응답이 알린다. 권한은 `view_settings`.

**게이트는 설정 > 일반 '디지털트윈 (실험)' 플래그**(`twin_config.ui_enabled` — 플래그 AND 안 잠김). 꺼져 있으면 404.

`/api/twin/config/...` — 대지·구획 트윈 설정(S3·S4, 지도 모달 '트윈' 탭·설정 그룹의 제안 표):
읽기 `view_settings`, 쓰기 `edit_settings`. 제안은 저장하지 않는다 — 사용자가 적용한 것만 PUT 으로 온다.

이 모듈은 `controllers` 를 import 하지 않는다(ARCHITECTURE.md §4).
"""
import logging
import time

import flask_login
from flask import request
from flask_accept import accept
from flask_restx import Resource, abort

from aot.aot_flask.api import api, default_responses
from aot.aot_flask.utils import utils_general
from aot.twin import output as twin_output
from aot.utils import twin_config, twin_facility_config, twin_store

logger = logging.getLogger(__name__)

ns_twin = api.namespace('twin', description='Digital twin read and settings (experimental)')


def _misc():
    try:
        from aot.databases.models import Misc
        return Misc.query.first()
    except Exception:
        logger.exception("트윈 API: Misc 를 읽지 못했다 — 꺼진 것으로 본다")
        return None


#: 한 번에 읽는 구간 상한 — 노지 동화 이력(약 3 달)과 지평(+14 일)을 덮는다.
SERIES_MAX_SPAN_S = 120 * 86400.0


def _is_field(measurement):
    return 'field' in measurement


def _baseline(v):
    return v in (None, '', twin_output.BASELINE)


@ns_twin.route('/series/<string:device_id>/<string:measurement>/<int:channel>')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'start': 'epoch seconds (default now - 3 days)',
                     'end': 'epoch seconds (default now + 16 days)',
                     'lead': 'lead_h / lead_d tag value for *_lead measurements',
                     'scenario': 'scenario id (default baseline) — reads env_twin_scn* with that tag',
                     'post': '1 = read the analysis history env_twin_*_post (the fitted past)'})
class TwinSeries(Resource):
    """트윈 계열 하나를 시각 구간으로 읽는다(미래 시각 포함)."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, device_id, measurement, channel):
        """Read one env_twin* series in a time window (experimental)."""
        if not twin_config.ui_enabled(_misc()):
            abort(404)
        if not utils_general.user_has_permission('view_settings', silent=True):
            abort(403)
        if measurement not in twin_output.MEASUREMENTS:
            abort(422, 'not a twin measurement')
        now = time.time()
        try:
            start = float(request.args.get('start', now - 3 * 86400.0))
            end = float(request.args.get('end', now + 16 * 86400.0))
        except ValueError:
            abort(422, 'start/end must be epoch seconds')
        if end < start or end - start > SERIES_MAX_SPAN_S:
            abort(422, 'window must be 0..{} s'.format(int(SERIES_MAX_SPAN_S)))
        lead = request.args.get('lead')
        scenario = request.args.get('scenario')
        post = request.args.get('post') in ('1', 'true', 'yes')
        tags = None
        if post or not _baseline(scenario):
            if lead is not None:
                abort(422, 'lead cannot be combined with scenario or post')
            if post and not _baseline(scenario):
                abort(422, 'post (the fitted past) has no scenario')
            if post:
                measurement = twin_output.POST_OF.get(measurement, measurement)
                if measurement not in twin_output.POST_MEASUREMENTS:
                    abort(422, 'no analysis history for this measurement')
            else:
                measurement = twin_output.SCENARIO_OF.get(measurement, measurement)
                if measurement not in twin_output.SCENARIO_MEASUREMENTS:
                    abort(422, 'no scenario curves for this measurement')
                row = twin_store.get_scenario(scenario)
                if row is None or row.target_id != device_id:
                    abort(404, 'scenario not found for this target')
                tags = {'scenario': scenario}
        elif measurement in twin_output.SCENARIO_MEASUREMENTS:
            abort(422, 'scenario is required for scenario curves')
        from aot.utils.influx import read_twin_series
        try:
            rows = read_twin_series(device_id, measurement, channel, start, end, lead=lead,
                                    **({'tag_filters': tags} if tags else {}))
        except Exception as e:
            logger.exception("트윈 읽기 실패")
            abort(503, 'measurement DB read failed: {}'.format(type(e).__name__))
        out = {'measurements': [{'time': t, 'value': v} for t, v in rows],
               'measurement': measurement, 'scenario': scenario or twin_output.BASELINE, 'post': post}
        out.update(_lineage_fields(device_id, 'field' if _is_field(measurement) else 'facility', now))
        return out, 200


def _lineage_fields(device_id, kind, now):
    """모든 읽기 응답이 싣는 계보 — 그래프의 '보정됨/원본' 표시 재료(설계 §6.8)."""
    lin = twin_store.lineage(kind, device_id, now)
    return {'calibrated': lin['calibrated'], 'cal_rev': lin['cal_rev'], 'fc_issue_epoch': lin['fc_issue_epoch'],
            'origin': lin['origin'], 't0': lin['run_t0']}


@ns_twin.route('/state/duty_log/<string:device_id>/<int:channel>')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'past': 'seconds back from now (default 48 h)'})
class TwinDutyLog(Resource):
    """출력의 가동 이력(`duration_time`)을 켜짐/꺼짐 계단(0/100 %)으로 — 원격 트윈 통로의 상태 계열 읽기."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, device_id, channel):
        """Duty-log step series of an output for the twin (experimental)."""
        if not twin_config.ui_enabled(_misc()):
            abort(404)
        if not utils_general.user_has_permission('view_settings', silent=True):
            abort(403)
        try:
            past = float(request.args.get('past', 48 * 3600.0))
        except ValueError:
            abort(422, 'past must be seconds')
        from aot.utils import twin_device_state
        times, values = twin_device_state.read_duty(device_id, channel, past)
        return {'measurements': [{'time': t, 'value': v} for t, v in zip(times, values)]}, 200


def _field_plot_ids(requested):
    """노지 구획(시설 밖, 끝나지 않은 작기). requested 가 있으면 그 가운데서만."""
    from aot.databases.models import GeoPlot
    q = GeoPlot.query.filter(GeoPlot.facility_uuid.is_(None))
    if requested:
        q = q.filter(GeoPlot.unique_id.in_(requested))
    else:
        q = q.filter(GeoPlot.ended_on.is_(None))
    return [p.unique_id for p in q.all()]


@ns_twin.route('/plots')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'start': 'epoch seconds (default now - 1 day)', 'end': 'epoch seconds (default now + 8 days)',
                     'measure': "'field' (노지 일 격자) — 지금은 이것 하나",
                     'plots': 'comma separated plot unique_ids (default: all open field plots)'})
class TwinPlots(Resource):
    """구획 묶음 — 지도 예측 제공자(twin.field)가 한 번에 읽는다. 읽는 쪽 규칙을 서버에서 적용."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self):
        """Latest usable twin forecast per field plot (experimental)."""
        if not twin_config.ui_enabled(_misc()):
            abort(404)
        if not utils_general.user_has_permission('view_settings', silent=True):
            abort(403)
        if request.args.get('measure', 'field') != 'field':
            abort(422, "measure must be 'field'")
        now = time.time()
        try:
            start = float(request.args.get('start', now - 86400.0))     # 오늘 00 시(k=0)가 들어오게
            end = float(request.args.get('end', now + 8 * 86400.0))
        except ValueError:
            abort(422, 'start/end must be epoch seconds')
        if end < start or end - start > SERIES_MAX_SPAN_S:
            abort(422, 'window must be 0..{} s'.format(int(SERIES_MAX_SPAN_S)))
        requested = [p for p in (request.args.get('plots') or '').split(',') if p][:200]
        ids = _field_plot_ids(requested)
        from aot.twin import output as O
        from aot.utils import twin_read
        from aot.utils.influx import read_twin_many
        try:
            meta_rows = read_twin_many(O.M_FLD_META, ids, twin_read.META_CHANNELS,
                                       now - 3 * 86400.0, now + 600.0)
            live = [i for i in ids if twin_read.usable(twin_read.latest_meta(meta_rows, i), now)[0]]
            curve_rows = read_twin_many(O.M_FLD, live, sorted(set(twin_read.CURVE_CHANNELS.values())),
                                        now - 2 * 86400.0, end) if live else {}
        except Exception as e:
            logger.exception("트윈 구획 묶음 읽기 실패")
            abort(503, 'measurement DB read failed: {}'.format(type(e).__name__))
        bundle = twin_read.plots_bundle(ids, meta_rows, curve_rows, now, start, end)
        # 곡선이 없는 이유가 설정(계산 불가·동기화 안 됨)이면 무엇이 비었는지 한 단어를 더한다 — 지도가 할 일을 적는다
        blocked = [r['plot_uuid'] for r in bundle if r['reason'] in ('status_2', 'status_3')]
        if blocked:
            try:
                setup = twin_config.plot_diagnoses(blocked)
                for r in bundle:
                    if r['plot_uuid'] in setup:
                        r['setup'] = setup[r['plot_uuid']]
            except Exception:
                logger.exception('트윈 구획 설정 진단 실패')
        return {'now': now, 'measure': 'field', 'plots': bundle}, 200


@ns_twin.route('/chart/plot/<string:plot_id>')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'back': 'days before today (default 14, max 60)', 'ahead': 'days after today (default 7, max 14)',
                     'scenario': 'scenario id — adds that scenario curves as `scenario`',
                     'post': '1 = adds the fitted past (analysis history) as `post`'})
class TwinChartPlot(Resource):
    """구획 그래프 한 장 — 예측 곡선·센서 실측 점·비·기온·사건 확률을 날짜 키로 묶어 준다."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, plot_id):
        """Everything the twin chart of one field plot needs (experimental)."""
        if not twin_config.ui_enabled(_misc()):
            abort(404)
        if not utils_general.user_has_permission('view_settings', silent=True):
            abort(403)
        try:
            back = int(request.args.get('back', 14))
            ahead = int(request.args.get('ahead', 7))
        except ValueError:
            abort(422, 'back/ahead must be integers')
        from aot.utils import twin_chart
        try:
            data = twin_chart.plot_chart(plot_id, time.time(), back, ahead,
                                         scenario=request.args.get('scenario') or None,
                                         post=request.args.get('post') in ('1', 'true', 'yes'))
        except twin_store.StoreError as e:
            _store_error(e)
        except Exception as e:
            logger.exception("트윈 구획 그래프 읽기 실패")
            abort(503, 'chart read failed: {}'.format(type(e).__name__))
        if data is None:
            abort(404, 'not a twin plot')
        data['can_edit'] = _can_edit()                 # 화면이 [만약에] 만들기를 보일지(쓰기는 시나리오 API 가 다시 막는다)
        return data, 200


@ns_twin.route('/forecast_series')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'site': 'site (대지) unique_id — required',
                     'start': 'epoch seconds (default: the current hour)',
                     'end': 'epoch seconds (default: end of the source file)',
                     'variables': 'comma separated subset of temp_c, rh_pct, wind_ms, wind_dir_deg, '
                                  'precip_mm_h, solar_w_m2, cloud_pct, pop_pct (default: all)'})
class TwinForecastSeries(Resource):
    """대지에 지정한 예보 입력의 시간별 시계열 — 지도 슬라이더·AI 예보와 같은 출처(geo/forecast_series.py)."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self):
        """Hourly forecast series of the site's designated forecast input (experimental)."""
        if not twin_config.ui_enabled(_misc()):
            abort(404)
        if not utils_general.user_has_permission('view_settings', silent=True):
            abort(403)
        site = (request.args.get('site') or '').strip()
        if not site:
            abort(422, 'site is required')
        from aot.databases.models import GeoShape
        shape = GeoShape.query.filter_by(unique_id=site).first()
        if shape is None or shape.type != 'site':
            abort(404, 'no such site')
        try:
            t0 = float(request.args['start']) if request.args.get('start') else None
            t1 = float(request.args['end']) if request.args.get('end') else None
        except ValueError:
            abort(422, 'start/end must be epoch seconds')
        if t0 is not None and t1 is not None and (t1 < t0 or t1 - t0 > SERIES_MAX_SPAN_S):
            abort(422, 'window must be 0..{} s'.format(int(SERIES_MAX_SPAN_S)))
        names = [v for v in (request.args.get('variables') or '').split(',') if v] or None
        from aot.aot_flask.geo import forecast_series
        try:
            return forecast_series.read(site, t0, t1, names), 200
        except ValueError as e:
            abort(422, str(e))


# ── 대지·구획 트윈 설정 (S3·S4) ────────────────────────────────────────────────

def _cfg_gate(write=False):
    if not twin_config.ui_enabled(_misc()):
        abort(404)
    if not utils_general.user_has_permission('edit_settings' if write else 'view_settings', silent=True):
        abort(403)


def _auto_forecast() -> bool:
    """설정 > 디지털트윈의 '예보 입력 자동 만들기' — 기본 켜짐."""
    from aot.utils import twin_gate
    return twin_gate.auto_forecast_enabled()


def _can_edit():
    return bool(utils_general.user_has_permission('edit_settings', silent=True))


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(422, 'JSON object body required')
    return body


def _save(scope, target_id, body):
    """body {enabled?: bool|null, config?: {...}} — 준 것만 바꾼다. config 는 통째로 바꾼다."""
    try:
        twin_config.save(scope, target_id, body.get('enabled'), body.get('config') if 'config' in body else None,
                         set_enabled='enabled' in body)
    except twin_config.TwinConfigError as e:
        abort(422, str(e))


@ns_twin.route('/config/site/<string:site_id>')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinConfigSite(Resource):
    """대지 트윈 설정 — 켜기·출처(구획이 물려받음)·구획 목록·제안·판정·일치도."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, site_id):
        """Site twin settings with plots, suggestions and verdict (experimental)."""
        _cfg_gate()
        v = twin_config.with_names(twin_config.site_view(site_id))
        v['can_edit'] = _can_edit()
        return v, 200

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def put(self, site_id):
        """Save site twin settings (experimental)."""
        _cfg_gate(write=True)
        body = _body()
        was_on = bool(twin_config.read('site', site_id)[0])
        _save('site', site_id, body)
        created = None
        # 꺼져 있던 대지를 켤 때만 — 예보를 일부러 '없음' 으로 두고 저장할 때마다 만들지 않도록
        if body.get('enabled') is True and not was_on and _auto_forecast():
            try:
                created = twin_config.ensure_site_forecast(site_id)
            except twin_config.TwinConfigError as e:
                logger.warning('트윈: 대지 %s 예보 입력을 만들지 못했다: %s', site_id, e)
            except Exception:
                logger.exception('트윈: 대지 %s 예보 입력 만들기 실패', site_id)
        return dict(twin_config.with_names(twin_config.site_view(site_id)), can_edit=True,
                    forecast_created=created), 200


@ns_twin.route('/config/site/<string:site_id>/forecast_input')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinConfigSiteForecastInput(Resource):
    """대지 위치에 예보 입력을 만들고 대지의 예보 칸을 그것으로 채운다(가까운 켜진 예보 입력이 없을 때만)."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def post(self, site_id):
        """Create a forecast input at the site and select it (experimental)."""
        _cfg_gate(write=True)
        try:
            created = twin_config.ensure_site_forecast(site_id)
        except twin_config.TwinConfigError as e:
            abort(422, str(e))
        if not created:
            abort(422, 'A forecast input is already chosen or near this site')
        return dict(twin_config.with_names(twin_config.site_view(site_id)), can_edit=True,
                    forecast_created=created), 200


@ns_twin.route('/config/plot/<string:plot_id>')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinConfigPlot(Resource):
    """구획 트윈 설정 — 포함·제외·출처 덮어쓰기·관측 센서 제안·일치도."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, plot_id):
        """Plot twin settings with inherited values and sensor suggestions (experimental)."""
        _cfg_gate()
        return dict(twin_config.with_names(twin_config.plot_view(plot_id)), can_edit=_can_edit()), 200

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def put(self, plot_id):
        """Save plot twin settings (experimental)."""
        _cfg_gate(write=True)
        from aot.databases.models import GeoPlot
        if GeoPlot.query.filter_by(unique_id=plot_id).first() is None:
            abort(404, 'plot not found')
        _save('plot', plot_id, _body())
        return dict(twin_config.with_names(twin_config.plot_view(plot_id)), can_edit=True), 200


@ns_twin.route('/config/facility/<string:facility_id>')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinConfigFacility(Resource):
    """시설 트윈 설정 — 입력·장치 실제 상태·출처·켜기(시설 행만)·판정·제안."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, facility_id):
        """Facility twin settings with verdict and suggestions (experimental)."""
        _cfg_gate()
        v = twin_config.with_names(twin_facility_config.facility_view(facility_id))
        v['can_edit'] = _can_edit()
        return v, 200

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def put(self, facility_id):
        """Save facility twin settings; `notices` carries one-time warnings (experimental)."""
        _cfg_gate(write=True)
        body = _body()
        try:
            notices = twin_facility_config.save(facility_id, body.get('enabled'),
                                                body.get('config') if 'config' in body else None,
                                                set_enabled='enabled' in body)
        except twin_config.TwinConfigError as e:
            abort(422, str(e))
        return dict(twin_config.with_names(twin_facility_config.facility_view(facility_id)),
                    can_edit=True, notices=notices), 200


# ── 시나리오·발행 색인·작동 시계열 (D7, 설계 §6) ─────────────────────────────────

def _store_error(e):
    abort(e.status, str(e), **e.extra) if e.extra else abort(e.status, str(e))


def _kind_arg(required=False):
    kind = request.args.get('target_kind')
    if kind is not None and kind not in ('field', 'facility'):
        abort(422, 'target_kind must be field or facility')
    if required and kind is None:
        abort(422, 'target_kind is required')
    return kind


@ns_twin.route('/runs/<string:target_id>')
@ns_twin.doc(security='apikey', responses=default_responses, params={'limit': 'rows (default 50, max 500)'})
class TwinRuns(Resource):
    """대상의 발행 색인(최근 순) — 어느 모델 판·보정 판·예보 발표 위에서 돌았나."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, target_id):
        """List the twin publication index of a target (experimental)."""
        _cfg_gate()
        try:
            limit = int(request.args.get('limit', 50))
        except ValueError:
            abort(422, 'limit must be an integer')
        return {'runs': [twin_store.run_dict(r) for r in twin_store.list_runs(target_id, limit)]}, 200


@ns_twin.route('/scenarios')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'target_kind': 'field | facility', 'target_id': 'target id'})
class TwinScenarios(Resource):
    """시나리오 머리 목록(읽기)과 만들기(쓰기)."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self):
        """List scenario headers of a target, with base_t0 for the staleness check (experimental)."""
        _cfg_gate()
        rows = twin_store.list_scenarios(_kind_arg(), request.args.get('target_id'))
        t0s = twin_store.base_t0_map(rows)
        return {'scenarios': [twin_store.scenario_dict(r, t0s.get(r.base_run)) for r in rows],
                'limit': twin_store.SCENARIO_LIMIT}, 200

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def post(self):
        """Create a scenario definition (queued). Body: {target:{kind,id}, label?, base_mode?, future_input_mode?, overrides?}."""
        _cfg_gate(write=True)
        body = _body()
        target = body.get('target') if isinstance(body.get('target'), dict) else {}
        try:
            row = twin_store.create_scenario(
                target.get('kind'), target.get('id'), label=body.get('label'),
                base_mode=body.get('base_mode', 'hold'), future_input_mode=body.get('future_input_mode', 'hold'),
                overrides=body.get('overrides'))
        except twin_store.StoreError as e:
            _store_error(e)
        return twin_store.scenario_dict(row, twin_store.base_t0_map([row]).get(row.base_run)), 201


@ns_twin.route('/scenarios/<string:scenario_id>')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinScenario(Resource):
    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, scenario_id):
        """Read one scenario header (experimental)."""
        _cfg_gate()
        row = twin_store.get_scenario(scenario_id)
        if row is None:
            abort(404, 'scenario not found')
        return twin_store.scenario_dict(row, twin_store.base_t0_map([row]).get(row.base_run)), 200

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def delete(self, scenario_id):
        """Delete a scenario with its curves (including the pinned copy) (experimental)."""
        _cfg_gate(write=True)
        try:
            return dict(ok=True, **twin_store.delete_scenario(scenario_id)), 200
        except twin_store.StoreError as e:
            _store_error(e)


@ns_twin.route('/scenarios/<string:scenario_id>/rerun')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinScenarioRerun(Resource):
    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def post(self, scenario_id):
        """Queue a finished/failed scenario again on the current baseline (experimental). Pinned ones are records (409)."""
        _cfg_gate(write=True)
        try:
            row = twin_store.requeue(scenario_id)
        except twin_store.StoreError as e:
            _store_error(e)
        return twin_store.scenario_dict(row, twin_store.base_t0_map([row]).get(row.base_run)), 200


@ns_twin.route('/scenarios/<string:scenario_id>/pin')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinScenarioPin(Resource):
    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def post(self, scenario_id):
        """Pin a scenario: copy its curves to the history bucket and keep it (experimental)."""
        _cfg_gate(write=True)
        try:
            row = twin_store.pin_scenario(scenario_id)
        except twin_store.StoreError as e:
            _store_error(e)
        out = twin_store.scenario_dict(row, twin_store.base_t0_map([row]).get(row.base_run))
        out['copied_points'] = getattr(row, 'copied_points', 0)
        return out, 200


@ns_twin.route('/actuators')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'target_kind': 'field | facility', 'target_id': 'target id', 'start': 'epoch seconds',
                     'end': 'epoch seconds', 'scenario': 'scenario id (default baseline)',
                     'effect': 'effect channel name', 'basis': 'actual|duty_log|command|assumed|plan',
                     'dev': 'all (default) or a device uuid'})
class TwinActuators(Resource):
    """작동 시계열(`env_twin_act`) — 그래프의 '원인' 레인. 효과 채널·근거·장치별로 계열을 나눠 준다."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self):
        """Read the actuator-effect time series of a target (experimental)."""
        _cfg_gate()
        kind = _kind_arg(required=True)
        target_id = request.args.get('target_id')
        if not target_id:
            abort(422, 'target_id is required')
        now = time.time()
        try:
            start = float(request.args.get('start', now - 2 * 86400.0))
            end = float(request.args.get('end', now + 3 * 86400.0))
        except ValueError:
            abort(422, 'start/end must be epoch seconds')
        if end < start or end - start > SERIES_MAX_SPAN_S:
            abort(422, 'window must be 0..{} s'.format(int(SERIES_MAX_SPAN_S)))
        scenario = request.args.get('scenario') or twin_output.BASELINE
        tags = {'scenario': scenario, 'dev': request.args.get('dev') or twin_output.ACT_ALL_DEVICES}
        for key in ('effect', 'basis'):
            if request.args.get(key):
                tags[key] = request.args[key]
        if not _baseline(scenario):
            row = twin_store.get_scenario(scenario)
            if row is None or row.target_id != target_id:
                abort(404, 'scenario not found for this target')
        from aot.utils.influx import read_layer_points
        try:
            rows = read_layer_points(twin_output.M_ACT, target_id, tags, start, end)
        except Exception as e:
            logger.exception("작동 시계열 읽기 실패")
            abort(503, 'measurement DB read failed: {}'.format(type(e).__name__))
        series = {}
        for t, v, tg in rows:
            key = (tg.get('effect'), tg.get('basis'), tg.get('dev'))
            series.setdefault(key, []).append({'time': t, 'value': v})
        out = {'scenario': scenario, 'target': {'kind': kind, 'id': target_id},
               'series': [{'effect': k[0], 'basis': k[1], 'dev': k[2], 'measurements': pts}
                          for k, pts in sorted(series.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]}
        out.update(_lineage_fields(target_id, kind, now))
        return out, 200


@ns_twin.route('/history/<string:scope>/<string:target_id>')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinHistory(Resource):
    """지운 구획·시설의 트윈 이력 지우기 — 삭제 확인 창에서 '이력도 지우기' 를 고른 뒤에만 온다(설계 §5)."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def delete(self, scope, target_id):
        """Erase the twin history (validation and publish headers) of a deleted plot or facility (experimental)."""
        _cfg_gate(write=True)
        if scope not in ('plot', 'facility'):
            abort(422, 'scope must be plot or facility')
        from aot.databases.models import GeoFacility, GeoPlot
        model = GeoPlot if scope == 'plot' else GeoFacility
        if model.query.filter_by(unique_id=target_id).first() is not None:
            abort(409, 'the target still exists; delete it first')   # 살아 있는 대상의 이력은 이 길로 지우지 않는다
        from aot.utils import data_retention
        return {'ok': True, 'deleted': data_retention.purge_target(target_id, history=True)}, 200


@ns_twin.route('/config/channels')
@ns_twin.doc(security='apikey', responses=default_responses,
             params={'kind': 'rain|t_air|et0|theta|soil_t — 이 입력이 될 수 있는 채널만(생략하면 전부)',
                     'all': '1 이면 kind 와 무관하게 전부(사용자가 직접 고를 때)'})
class TwinConfigChannels(Resource):
    """고를 수 있는 채널 목록 — 후보 종류(kinds)와 입력 모듈이 밝힌 출처 표시 제안을 붙여서."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self):
        """Channels that can feed a twin input (experimental)."""
        _cfg_gate()
        kind = request.args.get('kind') or ''
        if kind and kind not in twin_config.INPUT_KEYS:
            abort(422, 'unknown kind')
        rows = twin_config.channels()
        if kind and request.args.get('all') not in ('1', 'true'):
            rows = [r for r in rows if kind in r['kinds']]
        return {'channels': rows, 'forecast_inputs': twin_config.forecast_inputs()}, 200


@ns_twin.route('/config/overview')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinConfigOverview(Resource):
    """설정 그룹의 제안 결과 표 — 대지마다 켜짐·출처(설정/제안)·센서 제안·판정."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self):
        """Per-site twin overview (experimental)."""
        _cfg_gate()
        return {'sites': twin_config.overview(), 'facilities': twin_facility_config.overview(),
                'can_edit': _can_edit()}, 200


@ns_twin.route('/config/enable_all')
@ns_twin.doc(security='apikey', responses=default_responses)
class TwinConfigEnableAll(Resource):
    """모든 대지에 켜기. apply_suggestions 면 비어 있는 출처 칸만 첫 제안으로 채운다."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def post(self):
        """Turn the twin on for every site (experimental)."""
        _cfg_gate(write=True)
        body = request.get_json(silent=True) or {}
        try:
            res = twin_config.enable_all(apply_suggestions=bool(body.get('apply_suggestions')),
                                         auto_forecast=_auto_forecast())
        except twin_config.TwinConfigError as e:
            abort(422, str(e))
        return dict(res, sites_table=twin_config.overview()), 200
