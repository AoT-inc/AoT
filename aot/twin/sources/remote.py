# coding=utf-8
"""원격 통로 — 다른 AoT 서버를 REST 로 읽고, 결과를 `env_twin*` 측정으로 되돌려 쓴다.

읽기는 기존 API 를 그대로 쓴다: `GET /api/measurements/past/<id>/<unit>/<ch>/<past_seconds>`
(헤더 `X-API-KEY`, `Accept: application/vnd.aot.v1+json`).

쓰기는 일괄 수신 API 를 쓴다. 기존 `POST /api/measurements/create/...` 는 (1) 단위를
Unit 표에서 검증해 `env_twin*` 가 422 로 막히고 (2) 한 번에 한 점이라 한 발행 약 4.6 천 점에는 맞지
않는다. 그래서 일괄 수신 계약을 따로 둔다 (docs/design/digital-twin-node.md §5-1):

    POST {ingest_path}            (기본 /api/twin/ingest)
    {"source": "aot_twin",
     "pubs": [{"family": "facility", "id": "<device_id>", "t0": 1760000000.0, "status": 0,
               "valid_until": 1760007200.0}],
     "points": [{"m": "env_twin", "id": "<device_id>", "ch": 1,
                 "ts": 1760000600.0, "v": 21.3, "tags": {"facility": "a3d725da"}}]}
    → 200 {"written": N, "rejected": M, "reasons": {...}}

**원격 쓰기는 비활성이다(2026-10-24).** AoT 서버의 수신 API 를 걷어 냈다(계획서 §9.19 — 정식 경로는 서비스
`aot_twin` 이 Influx 에 직접 쓰는 내장 통로). 그래서 `RemoteSink` 는 기본으로 아무것도 보내지 않고
`REMOTE_WRITE_DISABLED` 를 오류로 돌려준다(설정 검증도 mode 'remote' 에 같은 이유를 알린다). 원격은 'AoT 쪽이
계산을 맡기는 방향'으로 다시 설계한다(배포 제안 §2, S6 원격 노드) — `RemoteSource`·`RemoteSink` 는 그때 정리한다.
위 계약의 직렬화는 그때까지 시험(가짜 서버)에서만 `write_enabled=True` 로 돈다. 계약 검사기는
`aot/twin/contract_check.py`.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Sequence

from ..output import publications
from ..types import ForecastSeries, Point, Series, SeriesRef, TargetSpec, WriteResult

logger = logging.getLogger(__name__)

ACCEPT = "application/vnd.aot.v1+json"


class RestError(Exception):
    def __init__(self, msg: str, status: Optional[int] = None):
        super().__init__(msg)
        self.status = status


class RestClient:
    """표준 라이브러리만 쓰는 얇은 클라이언트(트윈 노드에 requests 의존을 강요하지 않는다)."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float = 10.0, retries: int = 2,
                 backoff_s: float = 0.5, verify_tls: bool = True):
        self.base = base_url.rstrip("/")
        self._key = api_key
        self.timeout = timeout_s
        self.retries = retries
        self.backoff = backoff_s
        self._ctx = None
        if not verify_tls:
            import ssl
            self._ctx = ssl._create_unverified_context()

    def __repr__(self) -> str:                                  # 로그에 키가 새지 않게
        return f"RestClient({self.base!r}, key=***)"

    def _req(self, method: str, path: str, body=None):
        url = self.base + path
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "X-API-KEY": self._key, "Accept": ACCEPT, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code < 500:                                  # 4xx 는 다시 해도 같다
                    raise RestError(f"{method} {path} → HTTP {e.code}", e.code) from None
                last = RestError(f"{method} {path} → HTTP {e.code}", e.code)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = RestError(f"{method} {path} 연결 실패: {e}")
            if attempt < self.retries:
                time.sleep(self.backoff * (2 ** attempt))
        raise last  # type: ignore[misc]

    def get_json(self, path: str):
        return self._req("GET", path)

    def post_json(self, path: str, body):
        return self._req("POST", path, body)


class RemoteSource:
    def __init__(self, server_id: str, client: RestClient, targets: Sequence[TargetSpec],
                 ping_path: str = "/api/settings/measurements"):
        self.server_id = server_id
        self._c = client
        self._targets = list(targets)
        self._ping = ping_path

    def ping(self) -> bool:
        try:
            self._c.get_json(self._ping)
            return True
        except RestError:
            return False

    def list_targets(self) -> Sequence[TargetSpec]:
        # 대상 목록은 설정이 정한다. 서버가 대상을 알려 주는 API 는 후속(설계 §5).
        return list(self._targets)

    def read_series(self, ref: SeriesRef, window_s: float, now: float) -> Series:
        from aot.functions.utils.twin_effects.state import DUTY_UNIT
        past = max(1, int(window_s))
        if ref.unit == DUTY_UNIT:
            # 가동 이력은 서버가 계단으로 바꿔 준다(측정 API 는 이 표식을 모른다)
            path = "/api/twin/state/duty_log/{}/{}?past={}".format(
                urllib.parse.quote(ref.unique_id, safe=""), int(ref.channel), past)
        elif ref.unit.startswith("env_twin"):
            # 트윈 결과는 트윈 읽기 API 로(측정 API 는 env_twin* 를 422 로 막고 미래 시각을 못 읽는다).
            # 끝은 지평(+14 일)까지 — 곡선은 미래 시각에 있다.
            path = "/api/twin/series/{}/{}/{}?start={:.0f}&end={:.0f}".format(
                urllib.parse.quote(ref.unique_id, safe=""), urllib.parse.quote(ref.unit, safe=""),
                int(ref.channel), now - past, now + 16 * 86400.0)
        else:
            path = "/api/measurements/past/{}/{}/{}/{}".format(
                urllib.parse.quote(ref.unique_id, safe=""), urllib.parse.quote(ref.unit, safe=""),
                int(ref.channel), past)
        data = self._c.get_json(path)
        rows = data.get("measurements") if isinstance(data, dict) else None
        s = Series()
        for r in rows or []:
            t, v = r.get("time"), r.get("value")
            if t is None or v is None:
                continue
            s.times.append(float(t))
            s.values.append(float(v))
        order = sorted(range(len(s.times)), key=s.times.__getitem__)
        s.times = [s.times[i] for i in order]
        s.values = [s.values[i] for i in order]
        return s


    def read_forecast(self, site: str, t0: float, t1: float, variables: Optional[Sequence[str]] = None) -> ForecastSeries:
        """대지의 지정 예보 입력 시계열. 서버가 못 주거나(게이트 404·권한·연결) 응답이 이상하면 **쓸 수 없는 예보**로
        돌려준다 — 예보가 없어도 트윈은 돈다(원칙 1). 지정이 없거나 낡았으면 서버가 200 + available:false 로 답한다."""
        q = "site={}&start={:.0f}&end={:.0f}".format(urllib.parse.quote(str(site), safe=""), t0, t1)
        if variables:
            q += "&variables=" + ",".join(urllib.parse.quote(v, safe="") for v in variables)
        try:
            data = self._c.get_json("/api/twin/forecast_series?" + q)
        except RestError as e:
            logger.warning("트윈 예보 시계열 읽기 실패 %s: %s", self.server_id, e)
            return ForecastSeries(reason="error", reason_text=str(e))
        return ForecastSeries.from_response(data)


#: 원격 쓰기를 막은 이유 — 설정 검증(`settings.ServerSettings.notices`)과 싱크가 같은 문구를 쓴다.
REMOTE_WRITE_DISABLED = ("서버 수신 API 없음 — 원격 쓰기는 비활성 (/api/twin/ingest 는 2026-10-24 에 걷어 냈다. "
                         "원격 노드는 'AoT 쪽이 계산을 맡기는 방향'으로 다시 설계한다)")


class RemoteSink:
    def __init__(self, server_id: str, client: RestClient, ingest_path: str = "/api/twin/ingest",
                 max_batch: int = 2000, write_enabled: bool = False):
        self.server_id = server_id
        self._c = client
        self._path = ingest_path
        self._max = max_batch
        # 설정으로는 켤 수 없다(JSON·DB 에 칸이 없다) — 계약을 받는 가짜 서버로 직렬화를 시험할 때만 True.
        self._enabled = write_enabled

    def write(self, points: Sequence[Point]) -> WriteResult:
        res = WriteResult()
        if not self._enabled:
            res.error = REMOTE_WRITE_DISABLED                 # 보내지 않는다 — 받을 서버가 없다
            return res
        pubs = publications(points)        # 조각마다 실어 보낸다 — 서버가 유효기한을 검사한다
        for i in range(0, len(points), self._max):
            chunk = points[i:i + self._max]
            body = {"source": "aot_twin", "pubs": pubs, "points": [
                {"m": p.measurement, "id": p.device_id, "ch": p.channel, "ts": p.timestamp,
                 "v": p.value, "tags": dict(p.tags)} for p in chunk]}
            try:
                r = self._c.post_json(self._path, body)
            except RestError as e:
                res.error = str(e)
                return res
            res.written += int(r.get("written", 0))
            res.rejected += int(r.get("rejected", 0))
        return res
