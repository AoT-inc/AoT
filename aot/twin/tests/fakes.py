# coding=utf-8
"""시험용 가짜 AoT 서버(진짜 HTTP) — 기존 읽기 API 와 제안한 수신 API 를 흉내 낸다."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


class FakeAoT:
    """저장소: {(id, unit, ch): {ts: value}}. 같은 (키, ts) 는 덮어쓴다(Influx 와 같다)."""

    def __init__(self, api_key="k-test", accept_ingest=True):
        self.store = {}
        self.tags = {}
        self.api_key = api_key
        self.accept_ingest = accept_ingest
        self.requests = []
        self.fail_next = 0           # 다음 N 개 요청을 503 으로
        self.max_ingest_batch = 0
        self.reasons = {}
        self.forecast = None          # /api/twin/forecast_series 가 돌려줄 응답(dict) — None 이면 404(게이트 닫힘)
        self.forecast_queries = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self):
                fake.requests.append((self.command, self.path))
                if fake.fail_next > 0:
                    fake.fail_next -= 1
                    self._send(503, {})
                    return False
                if self.headers.get("X-API-KEY") != fake.api_key:
                    self._send(403, {"message": "forbidden"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                p = self.path.split("?")[0]
                if p == "/api/settings/measurements":
                    return self._send(200, {"measurements": []})
                parts = p.strip("/").split("/")
                if p == "/api/twin/forecast_series":
                    from urllib.parse import parse_qs
                    fake.forecast_queries.append({k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").items()})
                    if fake.forecast is None:
                        return self._send(404, {})
                    return self._send(200, fake.forecast)
                if parts[:3] == ["api", "twin", "series"]:
                    from urllib.parse import parse_qs
                    qs = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                    uid, meas, ch = unquote(parts[3]), unquote(parts[4]), int(parts[5])
                    lo, hi = float(qs["start"][0]), float(qs["end"][0])
                    rows = [{"time": t, "value": v} for t, v in sorted(fake.store.get((uid, meas, ch), {}).items())
                            if lo <= t <= hi]
                    return self._send(200, {"measurements": rows})
                if parts[:3] == ["api", "measurements", "past"]:
                    uid, unit = unquote(parts[3]), unquote(parts[4])
                    if unit.startswith("env_twin"):                 # 진짜 서버: 단위표에 없다 → 422
                        return self._send(422, {"message": "Unit ID not found"})
                    ch, past = int(parts[5]), int(parts[6])
                    now = time.time()
                    rows = [{"time": t, "value": v} for t, v in sorted(fake.store.get((uid, unit, ch), {}).items())
                            if now - past <= t <= now + 0.5]
                    return self._send(200, {"measurements": rows})
                self._send(404, {})

            def do_POST(self):
                if not self._auth():
                    return
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/twin/ingest" and fake.accept_ingest:
                    pts = body.get("points", [])
                    fake.max_ingest_batch = max(fake.max_ingest_batch, len(pts))
                    # 계약 검사기(contract_check — 옛 서버 수신 검증)를 그대로 거친다 — 노드 출력이
                    # 서버 계약을 통과하는지가 왕복 시험의 일부다.
                    from aot.twin import contract_check
                    try:
                        res = contract_check.validate(body, time.time())
                    except contract_check.IngestError as e:
                        return self._send(e.status, {"message": str(e)})
                    for q in res.accepted:
                        fake.store.setdefault((q.device_id, q.measurement, q.channel), {})[q.timestamp] = q.value
                        fake.tags[(q.device_id, q.measurement, q.channel, q.timestamp)] = dict(q.tags)
                    fake.reasons.update(res.reasons)
                    return self._send(200, {"written": len(res.accepted), "rejected": res.rejected,
                                            "reasons": dict(res.reasons)})
                self._send(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    def seed(self, uid, unit, ch, t, v):
        self.store.setdefault((uid, unit, ch), {})[float(t)] = float(v)

    def seed_recent(self, uid, unit, ch, value, now=None, n=6, step=60.0):
        now = time.time() if now is None else now
        for i in range(n):
            self.seed(uid, unit, ch, now - (n - 1 - i) * step - 5, value)
