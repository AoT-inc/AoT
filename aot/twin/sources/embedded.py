# coding=utf-8
"""내장 통로 — AoT 서버 안에서 로컬 Influx·DB 를 직접 읽고 쓴다 (docker profile `twin` / `aottwin.service`).

flask·DB·Influx 모듈은 **호출 시점에** import 한다. 이 모듈을 import 하는 것만으로는 아무것도
끌어오지 않으므로 원격 노드(AoT 서버 없음)에서도 패키지는 import 된다.

Influx 읽기/쓰기는 `aot.utils.influx` 의 기존 함수를 그대로 부른다.

쓰기는 `write_influxdb_points`(한 연결·동기 일괄, 수신 API 와 같은 함수)를 쓴다 — 한 발행 약 4.6 천 점.
대상 목록은 배포형 서비스(`service.py`)에서 `discovery.build_plan` 이 DB 로 만든다(S2).
"""
from __future__ import annotations

import datetime
import logging
from typing import Sequence

from ..types import ForecastSeries, Point, Series, SeriesRef, TargetSpec, WriteResult

logger = logging.getLogger(__name__)


class EmbeddedSource:
    def __init__(self, server_id: str, targets: Sequence[TargetSpec], app=None):
        self.server_id = server_id
        self._targets = list(targets)
        # gate.LazyApp — 대지 예보 계열(DB 조회)에만 쓴다. 안 주면 프로세스 공유 앱을 처음 읽을 때 올린다
        # (서비스·노드가 앱 없이 만들어 노지 예보가 'no_app' 으로 비던 결함, 10-25).
        if app is None:
            from ..gate import LazyApp
            app = LazyApp()
        self._app = app

    def ping(self) -> bool:
        try:
            from aot.utils import influx  # noqa: F401
            return True
        except Exception:
            return False

    def list_targets(self) -> Sequence[TargetSpec]:
        return list(self._targets)

    def read_series(self, ref: SeriesRef, window_s: float, now: float) -> Series:
        from aot.functions.utils.twin_effects.state import DUTY_UNIT
        if ref.unit == DUTY_UNIT:                       # 가동 이력 → 켜짐/꺼짐 계단(설계서 §5.1 duty_log)
            from aot.utils.twin_device_state import read_duty
            times, values = read_duty(ref.unique_id, ref.channel, window_s, now)
            s = Series()
            s.times, s.values = list(times), list(values)
            return s
        from aot.utils.influx import read_influxdb_list
        rows = read_influxdb_list(ref.unique_id, ref.unit, ref.channel, duration_sec=int(max(1, window_s)))
        s = Series()
        for t, v in rows or []:
            if v is None:
                continue
            s.times.append(float(t))
            s.values.append(float(v))
        return s


    def read_forecast(self, site: str, t0: float, t1: float, variables=None) -> ForecastSeries:
        """대지 예보 계열 — 서버 함수 `geo.forecast_series.read` 를 앱 컨텍스트 안에서 부른다(지도 날씨·AI 와 같은 출처).
        읽기가 실패하면 쓸 수 없는 예보다(원칙 1)."""
        try:
            from aot.aot_flask.geo import forecast_series
            with self._app.get().app_context():
                data = forecast_series.read(site, t0, t1, list(variables) if variables else None)
        except Exception as e:                                          # noqa: BLE001
            logger.warning("트윈 예보 시계열 읽기 실패(내장): %s", e)
            return ForecastSeries(reason="error", reason_text=f"{type(e).__name__}: {e}")
        return ForecastSeries.from_response(data)


class EmbeddedSink:
    def __init__(self, server_id: str, app=None):
        self.server_id = server_id
        self._app = app                      # gate.LazyApp — 분석 실행 색인(`twin_run`)을 DB 에 적을 때만 쓴다. 없으면 적지 않는다

    def _record_runs(self, points) -> None:
        """쓴 점에 발행 머리말이 있으면 `twin_run` 에 한 줄 적는다(설계 §6.6). 실패해도 발행은 성공이다."""
        try:
            if self._app is None:
                return
            from aot.utils import twin_store
            if not twin_store.runs_from_points(points):
                return
            with self._app.get().app_context():
                twin_store.record_runs_from_points(points)
        except Exception:                                               # noqa: BLE001
            logger.warning("분석 실행 색인을 적지 못했다", exc_info=True)

    def write(self, points: Sequence[Point]) -> WriteResult:
        """`env_twin*` 만 쓴다(계약 §6). 일괄 쓰기(`write_influxdb_points`, 한 연결·동기)가
        있으면 그것으로, 없으면(옛 서버) 점마다 쓴다."""
        from aot.utils import influx
        res = WriteResult()
        good = [p for p in points if p.measurement.startswith("env_twin")]
        res.rejected = len(points) - len(good)
        if not good:
            return res
        batch = getattr(influx, "write_influxdb_points", None)
        if batch is not None:
            try:
                res.written = int(batch(good))
            except Exception as e:
                res.error = f"{type(e).__name__}: {e}"
            if res.error is None and res.written:
                self._record_runs(good)
            return res
        for p in good:
            ts = datetime.datetime.utcfromtimestamp(p.timestamp)
            try:
                err = influx.write_influxdb_value(p.device_id, p.measurement, p.value, channel=p.channel,
                                                  timestamp=ts, extra_tags=dict(p.tags) or None)
            except Exception as e:
                res.error = f"{type(e).__name__}: {e}"
                return res
            if err:
                res.rejected += 1
            else:
                res.written += 1
        return res
