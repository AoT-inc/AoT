# coding=utf-8
"""원격 AoT 서버 접속 공용 클라이언트.

다른 AoT 인스턴스를 "장치"로 다루는 세 모듈(원격 Input 1개, 원격 Output 2개)이
공유하는 HTTP/인증 계층. 접속정보 해석·TLS 검증·타임아웃·에러 정규화를 여기
한 곳에 모은다.

**한 곳에 모은 이유 — TLS 를 끄는 결정이 네 번 따로 내려져 있었다.**
`remote_output_on_off.py`(244·252·364·380)와 `remote_output_pwm.py`
(262·268·348·359)가 각자 HTTP 코드를 복붙해 갖고 있었다 — 두 파일 합쳐
`verify=False` 4곳과 `https://` 하드코딩 4곳이다. 원격 AoT 의 API 키는 그 서버의
**물리 장치 제어권**이므로(아래 참조) 중간자가 헤더를 읽으면 남의 밸브를 여닫을
수 있다. 게다가 scheme 이 박혀 있어 평문 HTTP 로만 열린 서버(로컬 docker 등)에는
아예 붙지 못했다. 드라이버가 하나 늘 때마다 이 결정이 한 번 더 복제되는 구조를
끊는 것이 이 파일의 첫 번째 목적이다.

**API 키 = 그 사용자의 전 권한.** `aot_flask/app.py` 의 `load_user_from_request`
는 키로 `User` 를 찾아 그대로 로그인시킨다(`User.find_by_api_key`). 키에 스코프가
없으므로 "수집만" 이라는 제한을 클라이언트 쪽에서 만들 방법은 없다. 수집 전용
연결이라면 **`view_settings` 만 가진 role 의 계정을 따로 만들어 그 키를 쓸 것.**
이 안내는 세 드라이버의 `custom_options_message` 에도 그대로 들어간다.

**키를 로그에 남기지 않는다.** 기존 드라이버 일부가 헤더 dict 를 통째로
`logger.debug` 로 찍었다(예: `ttn_data_storage_ttn_v3_jmespath.py`). 디버그 로그를
켜는 순간 크리덴셜이 파일로 떨어지므로, 이 파일은 헤더를 절대 로깅하지 않고
`_redacted_headers()` 로 마스킹한 사본만 남긴다.

**키는 base64 문자열 그대로 보낸다.** 사용자가 설정 화면에서 발급받아 보는 값이
이미 base64 다(`utils_settings.generate_api_key` → `base64_encode_bytes`). 서버의
`load_user_from_request` 가 `b64decode` 하므로, 여기서 다시 인코딩하면 안 된다.

@phase active
@stability experimental
@dependency requests
"""
import json
import logging

logger = logging.getLogger(__name__)

#: 연결 타임아웃(초). 호스트가 죽었을 때 빨리 포기하기 위한 값이라 짧게 둔다.
#: 읽기 타임아웃은 원격 명령이 실제로 장치를 건드리는 데 걸리는 시간에 좌우되므로
#: (예: 원격 핸들러의 time.sleep(15)) 호출자가 정한다.
DEFAULT_CONNECT_TIMEOUT = 5
DEFAULT_READ_TIMEOUT = 15

#: 원격 AoT REST API 의 버전 미디어타입. `aot_flask/api/__init__.py` 참조.
ACCEPT_MEDIATYPE = 'application/vnd.aot.v1+json'

#: `routes_general.data_batch` 의 항목 상한. 넘기면 서버가 조용히 잘라내므로
#: (`items = items[:_BATCH_MAX_ITEMS]`) 클라이언트가 미리 나눠 보낸다.
BATCH_MAX_ITEMS = 300

#: `async_data()` 가 받아들이는 device_type 어휘.
MEASURE_TYPES = ('input', 'function', 'output', 'pid')

#: 디스커버리 전체에 허용하는 시간(초)과 그 안에서 요청 하나에 허용하는 읽기 시간.
#:
#: 디스커버리는 **웹 요청 처리 중에**(설정 저장 훅) 원격 서버로 5번 연속 호출한다.
#: 그런데 이 앱의 gunicorn 은 `workers=1, threads=8, timeout=300`
#: (`install/gunicorn_conf.py`)이다 — 워커가 하나뿐이라 블로킹 I/O 가 스레드를
#: 잡아먹고, 타임아웃이 300초라 워커가 죽지도 않는다. 사용자의 `request_timeout`
#: (기본 30초)을 그대로 쓰면 응답하지 않는 원격 하나가 5×30=150초 동안 스레드를
#: 점유하고, 그런 저장이 8번이면 앱 전체가 멈춘 것처럼 보인다.
#:
#: 그래서 디스커버리만은 사용자 설정과 무관하게 짧게 자른다. 수집(주기 폴링)은
#: 백그라운드 컨트롤러에서 돌므로 이 제한을 받지 않는다 — 거기서는 사용자가 정한
#: `request_timeout` 이 그대로 유효하다.
DISCOVERY_BUDGET_S = 10.0
DISCOVERY_READ_TIMEOUT_S = 5

_LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1', '[::1]')


class RemoteAoTError(Exception):
    """원격 AoT 호출 실패의 공통 조상."""


class RemoteAoTUnreachable(RemoteAoTError):
    """네트워크 계층에서 실패 — 연결 불가, 타임아웃, TLS 검증 실패."""


class RemoteAoTAuthError(RemoteAoTError):
    """401/403 — API 키가 틀렸거나 그 계정에 권한이 없다."""


class RemoteAoTResponseError(RemoteAoTError):
    """연결은 됐으나 응답이 200 이 아니거나 해석할 수 없다."""


def normalize_host(host):
    """사용자가 입력한 호스트 문자열을 (host, scheme) 로 정리한다.

    사람은 `192.168.0.9`, `192.168.0.9:8084`, `https://farm.example.com/` 를
    가리지 않고 넣는다. scheme 을 붙여 넣었다면 그것이 명시적 의사표시이므로
    옵션의 scheme 보다 우선한다(안 그러면 `http://…` 를 넣은 사람이 왜 https 로
    나가는지 알 수 없다).

    :return: (host[:port] 문자열, 'http'/'https'/None)
    """
    if not host:
        return '', None

    value = str(host).strip()
    scheme = None

    for prefix in ('https://', 'http://'):
        if value.lower().startswith(prefix):
            scheme = prefix[:-3]
            value = value[len(prefix):]
            break

    # 경로·쿼리는 버린다. base_url 이 `/api/...` 를 붙이므로 남아 있으면 URL 이
    # 깨진다.
    for sep in ('/', '?', '#'):
        if sep in value:
            value = value.split(sep, 1)[0]

    # `user:pass@host` 형태로 크리덴셜을 끼워 넣는 것은 지원하지 않는다 —
    # 인증은 X-API-KEY 하나뿐이고, URL 에 든 비밀은 로그로 샌다.
    if '@' in value:
        value = value.rsplit('@', 1)[1]

    return value.strip().rstrip('.'), scheme


def _host_is_local(host):
    bare = (host or '').split(':', 1)[0].strip().lower()
    return bare in _LOCAL_HOSTS


def _redacted_headers(headers):
    """로그용 헤더 사본 — 크리덴셜을 마스킹한다."""
    safe = dict(headers or {})
    if 'X-API-KEY' in safe:
        safe['X-API-KEY'] = '<redacted>'
    return safe


class RemoteAoTClient:
    """원격 AoT 인스턴스 하나에 대한 얇은 REST 클라이언트.

    스레드 안전하지 않다 — 드라이버마다 자기 인스턴스를 갖는다(원격 Output 의
    상태 폴링 스레드처럼 별도 스레드에서 쓰는 경우 `requests` 호출 자체는
    독립적이라 문제 없으나, 인스턴스를 여러 컨트롤러가 공유하지는 말 것).
    """

    def __init__(self, host, api_key,
                 scheme='https',
                 verify_tls=True,
                 request_timeout=DEFAULT_READ_TIMEOUT,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 logger_=None):
        self.logger = logger_ or logger

        self.host, scheme_from_host = normalize_host(host)
        self.scheme = (scheme_from_host or scheme or 'https').lower()
        if self.scheme not in ('http', 'https'):
            self.logger.error(
                "Unknown scheme '%s' for remote AoT host; falling back to https",
                self.scheme)
            self.scheme = 'https'

        self.api_key = api_key or ''
        self.verify_tls = bool(verify_tls)

        try:
            self.request_timeout = max(1, int(request_timeout or DEFAULT_READ_TIMEOUT))
        except (TypeError, ValueError):
            self.request_timeout = DEFAULT_READ_TIMEOUT
        try:
            self.connect_timeout = max(1, int(connect_timeout or DEFAULT_CONNECT_TIMEOUT))
        except (TypeError, ValueError):
            self.connect_timeout = DEFAULT_CONNECT_TIMEOUT

        self._warned_insecure = False
        self._warn_if_insecure()

    # ── 구성 ──────────────────────────────────────────────────────────────
    @classmethod
    def from_options(cls, options, logger_=None, request_timeout=None):
        """드라이버의 custom_options dict 에서 클라이언트를 만든다.

        세 드라이버가 같은 옵션 id(`host`/`api_key`/`scheme`/`verify_tls`/
        `request_timeout`)를 쓰기로 한 계약이 여기 박혀 있다. 복합장치
        (`device_remote_aot.py`)의 `inherit_options` 도 이 이름들을 그대로
        전파하므로 이름을 바꾸면 세 곳이 함께 어긋난다.
        """
        get = options.get if hasattr(options, 'get') else (lambda k, d=None: d)
        timeout = request_timeout if request_timeout is not None else get('request_timeout')
        return cls(
            host=get('host'),
            api_key=get('api_key'),
            scheme=get('scheme') or 'https',
            # 미설정(None)은 "검증 켬" 으로 읽는다 — 옵션이 없는 구버전 설정에서
            # 조용히 검증이 꺼지면 안 된다.
            verify_tls=True if get('verify_tls') is None else bool(get('verify_tls')),
            request_timeout=timeout or DEFAULT_READ_TIMEOUT,
            logger_=logger_)

    def _warn_if_insecure(self):
        """안전하지 않은 구성일 때 한 번만 경고한다.

        경고를 남기는 이유: 검증을 끄는 것 자체는 자체서명 인증서를 쓰는 현장
        때문에 막지 않지만, 끈 사실이 어디에도 안 남으면 몇 달 뒤 아무도 모른다.
        """
        if self._warned_insecure:
            return
        if self.scheme == 'https' and not self.verify_tls:
            self.logger.warning(
                "Remote AoT %s: TLS certificate verification is DISABLED. The API "
                "key (which grants control of that server's devices) is exposed to "
                "anyone able to intercept this connection. Use a trusted certificate "
                "and re-enable verification.", self.host)
            self._warned_insecure = True
        elif self.scheme == 'http' and not _host_is_local(self.host):
            self.logger.warning(
                "Remote AoT %s: plain HTTP to a non-local host. The API key is sent "
                "in cleartext on every request.", self.host)
            self._warned_insecure = True

    @property
    def base_url(self):
        return '{s}://{h}'.format(s=self.scheme, h=self.host)

    @property
    def configured(self):
        return bool(self.host and self.api_key)

    def _headers(self):
        return {
            'Accept': ACCEPT_MEDIATYPE,
            'X-API-KEY': self.api_key,
        }

    # ── 저수준 ────────────────────────────────────────────────────────────
    def _request(self, method, path, json_body=None, read_timeout=None):
        """한 번의 HTTP 왕복. 성공하면 파싱된 JSON(dict/list)을 돌려준다.

        실패는 전부 RemoteAoTError 하위 예외로 정규화한다 — 호출자가
        `requests` 의 예외 계층을 알 필요가 없게 하고, "None 을 돌려주는 실패"
        가 조용히 성공으로 읽히는 일을 막기 위해서다.
        """
        import requests

        if not self.configured:
            raise RemoteAoTError("Remote AoT host or API key is not configured")

        url = '{base}{path}'.format(
            base=self.base_url,
            path=path if path.startswith('/') else '/' + path)
        headers = self._headers()
        timeout = (self.connect_timeout,
                   int(read_timeout) if read_timeout else self.request_timeout)

        self.logger.debug("%s %s (headers=%s, verify=%s)",
                          method, url, _redacted_headers(headers), self.verify_tls)

        try:
            response = requests.request(
                method, url,
                headers=headers,
                json=json_body,
                verify=self.verify_tls,
                timeout=timeout)
        except requests.exceptions.SSLError as err:
            # 검증 실패를 일반 연결 오류와 섞지 않는다 — 사용자가 취할 조치가
            # 다르다(인증서를 고치거나, 알고서 검증을 끄거나).
            raise RemoteAoTUnreachable(
                "TLS verification failed for {url}: {err}. Fix the certificate, or "
                "disable 'Verify TLS Certificate' if you accept the risk.".format(
                    url=self.base_url, err=err))
        except requests.exceptions.RequestException as err:
            raise RemoteAoTUnreachable(
                "Request to {url} failed: {err}".format(url=url, err=err))

        self.logger.debug("Response status: %s", response.status_code)

        if response.status_code in (401, 403):
            raise RemoteAoTAuthError(
                "Remote AoT rejected the API key (HTTP {code}). Check the key and "
                "that its user has the required permission.".format(
                    code=response.status_code))

        if response.status_code == 204:
            return None

        if response.status_code != 200:
            raise RemoteAoTResponseError(
                "Remote AoT returned HTTP {code}: {body}".format(
                    code=response.status_code, body=response.text[:200]))

        if not response.text:
            return None

        try:
            return json.loads(response.text)
        except ValueError:
            raise RemoteAoTResponseError(
                "Remote AoT returned a non-JSON body: {body}".format(
                    body=response.text[:200]))

    def get(self, path, read_timeout=None):
        return self._request('GET', path, read_timeout=read_timeout)

    def post(self, path, json_body=None, read_timeout=None):
        return self._request('POST', path, json_body=json_body,
                             read_timeout=read_timeout)

    # ── 연결 확인 ─────────────────────────────────────────────────────────
    def ping(self):
        """접속·인증이 되는지 확인한다. 실패는 예외로 올라간다."""
        self.get('/api/inputs/')
        return True

    # ── 조회 ──────────────────────────────────────────────────────────────
    def inputs(self, read_timeout=None):
        return self.get('/api/inputs/', read_timeout=read_timeout) or {}

    def functions(self, read_timeout=None):
        return self.get('/api/functions/', read_timeout=read_timeout) or {}

    def outputs(self, read_timeout=None):
        return self.get('/api/outputs/', read_timeout=read_timeout) or {}

    def pids(self, read_timeout=None):
        return self.get('/api/settings/pids', read_timeout=read_timeout) or {}

    def device_measurements(self, read_timeout=None):
        """원격의 DeviceMeasurements 전체를 1회 호출로 가져온다.

        채널마다 `/api/inputs/<id>` 를 부르는 N+1 을 피하는 자리다.
        """
        data = self.get('/api/settings/device_measurements',
                        read_timeout=read_timeout) or {}
        return data.get('device measurement settings') or []

    # ── 측정값 수집 ───────────────────────────────────────────────────────
    def data_batch(self, items):
        """`POST /data_batch` — 여러 채널을 한 번에 조회한다.

        `/api/` 네임스페이스 **밖**의 내부 엔드포인트다(버전 미디어타입 계약이
        없다). 그래서 호출자는 반드시 `past_data()` 폴백을 갖춰야 한다 — 이
        엔드포인트가 없는 구버전 원격 서버에서도 붙을 수 있어야 하기 때문.

        `kind='past'` 결과는 항목당 `[[ts, value], ...]` 이고, 원격 서버가
        **변환(Conversion)을 적용한 뒤**의 값이다(`async_data()` 경유). 그래서
        단위 어휘를 로컬에서 다시 해석할 필요가 없다.

        :param items: data_batch 항목 리스트
        :return: items 와 같은 길이의 결과 리스트 (실패 항목은 None)
        """
        if not items:
            return []

        results = []
        # 상한을 넘기면 서버가 말없이 잘라낸다 — 잘린 항목이 "데이터 없음" 으로
        # 보이지 않도록 클라이언트가 나눠 보낸다.
        for start in range(0, len(items), BATCH_MAX_ITEMS):
            chunk = items[start:start + BATCH_MAX_ITEMS]
            payload = self.post('/data_batch', json_body={'items': chunk}) or {}
            chunk_results = payload.get('results')
            if not isinstance(chunk_results, list):
                raise RemoteAoTResponseError(
                    "data_batch returned an unexpected body")
            # 서버는 items 와 정렬을 맞춰 돌려주지만, 짧게 오면 뒤를 None 으로
            # 채워 인덱스가 밀리지 않게 한다.
            if len(chunk_results) < len(chunk):
                chunk_results = chunk_results + [None] * (len(chunk) - len(chunk_results))
            results.extend(chunk_results[:len(chunk)])
        return results

    def past_data(self, device_id, measure_type, measurement_id, past_seconds):
        """`GET /past/...` — 채널 하나의 과거 구간. data_batch 폴백용.

        `data_batch` 와 같은 `async_data()` 를 타므로 변환 적용 결과도 동일하다.
        """
        if measure_type not in MEASURE_TYPES:
            raise RemoteAoTError(
                "Unsupported measure_type '{t}'".format(t=measure_type))
        path = '/past/{dev}/{typ}/{meas}/{sec}'.format(
            dev=device_id, typ=measure_type,
            meas=measurement_id, sec=int(past_seconds))
        data = self.get(path)
        # 204(데이터 없음)는 None 으로 온다 — 빈 구간이지 오류가 아니다.
        return data if isinstance(data, list) else []

    # ── 제어 ──────────────────────────────────────────────────────────────
    def set_output_state(self, output_id, channel, state, read_timeout=None):
        """원격 On/Off 출력을 전환한다. 실패는 예외."""
        return self._expect_success(self.post(
            '/api/outputs/{oid}'.format(oid=output_id),
            json_body={'channel': channel, 'state': state},
            read_timeout=read_timeout))

    def set_output_duty_cycle(self, output_id, channel, duty_cycle, read_timeout=None):
        """원격 PWM 출력의 듀티사이클을 설정한다. 실패는 예외."""
        return self._expect_success(self.post(
            '/api/outputs/{oid}'.format(oid=output_id),
            json_body={'channel': channel, 'duty_cycle': duty_cycle},
            read_timeout=read_timeout))

    @staticmethod
    def _expect_success(response_dict):
        """AoT 출력 API 의 성공 규약(`message` 에 'Success')을 확인한다.

        HTTP 200 만 보고 성공으로 처리하면 안 된다 — 이 API 는 도구 자체가
        실패해도 200 에 오류 메시지를 담아 돌려주는 경우가 있다.
        """
        message = ''
        if isinstance(response_dict, dict):
            message = str(response_dict.get('message') or '')
        if 'Success' not in message:
            raise RemoteAoTResponseError(
                "Remote AoT did not report success: {msg}".format(
                    msg=message or '(no message)'))
        return True


# ──────────────────────────────────────────────────────────────────────────
# 디스커버리
# ──────────────────────────────────────────────────────────────────────────
def discover_measurements(client, budget_s=DISCOVERY_BUDGET_S):
    """원격의 측정 채널 목록을 (value, label) 튜플 리스트로 만든다.

    **웹 요청 안에서 도는 코드다.** 그래서 전체 소요를 `budget_s` 로 자른다 —
    예산을 넘기면 부분 결과를 돌려주지 않고 `RemoteAoTError` 를 올린다. 부분
    결과를 돌려주면 호출자가 그것을 정상 목록으로 저장해, 원격에 멀쩡히 있는
    채널이 화면에서 사라진 채 굳는다(호출자는 실패 시 기존 목록을 보존한다).

    value 형식은 `"<device_id>,<measurement_id>,<measure_type>"`.
    셋을 다 넣는 이유는 수집할 때 `data_batch` 가 이 셋을 모두 요구하는데,
    나중에 다시 조회하면 원격이 그 사이 바뀌었을 때 채널이 조용히 딴 곳을
    가리키기 때문이다.

    **`DeviceMeasurements.device_type` 을 믿지 않는다.** 컬럼은 있지만 이
    코드베이스 어디에서도 값을 넣지 않아 항상 NULL 이다(로컬 라이브 DB 184행
    전수 확인, 2026-08-10). 그래서 종류는 device_id 를 실제 장치 목록에 대조해 판정한다.

    :param client: RemoteAoTClient
    :return: [(value, label), ...] — 이름순 정렬
    """
    import time as _time
    deadline = _time.monotonic() + float(budget_s)

    def _left():
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            raise RemoteAoTUnreachable(
                "Discovery exceeded its {b:.0f}s budget — the remote server is "
                "reachable but too slow to list its measurements.".format(b=budget_s))
        return min(DISCOVERY_READ_TIMEOUT_S, max(1, int(remaining)))

    measurements = client.device_measurements(read_timeout=_left())
    if not measurements:
        return []

    # device_id → (measure_type, 표시이름). 한 종류라도 조회에 실패하면 그
    # 종류의 채널만 빠지고 나머지는 살린다 — 원격의 권한이 부분적으로만
    # 열려 있을 수 있다(예: 수집 전용 계정).
    owners = {}

    def _collect(measure_type, fetch, key):
        # 예산 초과는 여기서 잡지 않고 위로 올린다 — 남은 종류를 조용히 건너뛰면
        # 그 종류의 채널이 통째로 사라진 목록이 정상인 것처럼 저장된다.
        timeout = _left()
        try:
            payload = fetch(read_timeout=timeout) or {}
        except RemoteAoTError as err:
            client.logger.debug(
                "discover: skipping %s (%s)", measure_type, err)
            return
        for row in payload.get(key) or []:
            if isinstance(row, dict) and row.get('unique_id'):
                owners[row['unique_id']] = (
                    measure_type, row.get('name') or measure_type)

    _collect('input', client.inputs, 'input settings')
    _collect('function', client.functions, 'function settings')
    _collect('output', client.outputs, 'output devices')
    _collect('pid', client.pids, 'pid settings')

    choices = []
    for row in measurements:
        if not isinstance(row, dict):
            continue
        device_id = row.get('device_id')
        measurement_id = row.get('unique_id')
        if not device_id or not measurement_id:
            continue
        # 꺼 둔 채널은 더 이상 기록되지 않으므로 고를 수 있게 두지 않는다.
        # (is_enabled 가 None 인 옛 행은 모델 기본값대로 '켜짐'으로 본다 —
        # utils_general.form_input_choices 와 같은 규칙.)
        if row.get('is_enabled') is False:
            continue

        owner = owners.get(device_id)
        if not owner:
            # 소유 장치를 못 찾은 채널. 권한 부족이거나 원격에 고아 행이 있다는
            # 뜻이므로 목록에 올리지 않는다 — 올려 봐야 수집이 실패한다.
            continue
        measure_type, owner_name = owner

        label = '{owner}: {meas} ({unit})'.format(
            owner=owner_name,
            meas=row.get('measurement') or '?',
            unit=row.get('unit') or '?')
        if row.get('channel') is not None:
            label += ' CH{ch}'.format(ch=row['channel'])
        if row.get('name'):
            label += ' [{n}]'.format(n=row['name'])

        choices.append((
            '{dev},{meas},{typ}'.format(
                dev=device_id, meas=measurement_id, typ=measure_type),
            label))

    choices.sort(key=lambda pair: pair[1])
    return choices


def parse_channel_value(value):
    """`discover_measurements()` 가 만든 값을 되돌린다.

    :return: (device_id, measurement_id, measure_type) 또는 None
    """
    if not value or not isinstance(value, str):
        return None
    parts = value.split(',')
    if len(parts) < 2:
        return None
    device_id = parts[0].strip()
    measurement_id = parts[1].strip()
    measure_type = parts[2].strip() if len(parts) > 2 else 'input'
    if not device_id or not measurement_id:
        return None
    if measure_type not in MEASURE_TYPES:
        measure_type = 'input'
    return device_id, measurement_id, measure_type
