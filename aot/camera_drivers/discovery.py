# coding=utf-8
"""네트워크 검색 (설계 §8 1차안). 데몬에서 돈다. 사용자가 "카메라 찾기"를 눌렀을 때만.

- 대상은 RFC1918 의 /24 이하(좁거나 같은 대역)만. 넓은 대역은 줄이지 않고 거절한다.
- 동시에 한 건, 같은 서브넷은 끝난 뒤 60초 지나야 다시. 동시 연결 16, 전체 30초 상한.
"""
import ipaddress
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

from aot.camera_drivers.vigi import probe as P

CONCURRENCY = 16
TOTAL_LIMIT_S = 30.0
RESCAN_S = 60.0
_KEEP = 5

_ALLOWED = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]


class ScanError(Exception):
    """code: invalid | not_private | too_wide | busy | cooldown. retry_after 는 cooldown 일 때만."""

    def __init__(self, code, retry_after=None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def parse_subnet(text):
    """사용자 입력 → ip_network. 규칙 위반이면 ScanError. 대역을 몰래 바꾸지 않는다.
    CIDR 의 호스트 비트만 정리한다(192.168.1.5/24 → 192.168.1.0/24, 같은 범위). 접두사 없는 IP 는 /32."""
    try:
        net = ipaddress.ip_network((text or '').strip(), strict=False)
    except ValueError:
        raise ScanError('invalid')
    if net.version != 4:
        raise ScanError('invalid')
    if not any(net.subnet_of(a) for a in _ALLOWED):
        raise ScanError('not_private')      # 공인·루프백·링크 로컬·CGNAT 모두 여기서 걸린다
    if net.prefixlen < 24:
        raise ScanError('too_wide')
    return net


def hosts_of(net):
    if net.prefixlen >= 31:
        return [str(h) for h in net]
    return [str(h) for h in net.hosts()]


def default_subnet(is_docker=None):
    """네이티브 설치: 서버 IP 를 포함한 /24. Docker·알 수 없음·사설망이 아님이면 None(사용자가 입력)."""
    if is_docker is None:
        try:
            from aot.utils import system_environment as se
            is_docker = se.detect().get('platform_type') == se.PLATFORM_DOCKER
        except Exception:
            is_docker = True
    if is_docker:
        return None
    try:   # UDP connect 는 패킷을 보내지 않고 경로의 출발 주소만 고른다
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            ip = s.getsockname()[0]
        net = ipaddress.ip_network('%s/24' % ip, strict=False)
        return str(net) if any(net.subnet_of(a) for a in _ALLOWED) else None
    except OSError:
        return None


class ScanManager:
    def __init__(self, probe=P.probe_host, clock=time.monotonic, total_limit=TOTAL_LIMIT_S,
                 rescan_s=RESCAN_S, concurrency=CONCURRENCY, registered=None):
        self._probe = probe
        self._clock = clock
        self.total_limit = total_limit
        self.rescan_s = rescan_s
        self.concurrency = concurrency
        self._registered = registered or registered_hosts
        self._lock = threading.Lock()
        self._running = None
        self._done_at = {}        # subnet -> 끝난 시각
        self._scans = {}          # id -> dict
        self._order = []
        self.max_inflight = 0     # 시험용 관측
        self._inflight = 0

    # -- 시작 ----------------------------------------------------------------
    def start(self, subnet_text, background=True):
        net = parse_subnet(subnet_text)
        key = str(net)
        with self._lock:
            if self._running is not None:
                raise ScanError('busy')
            last = self._done_at.get(key)
            if last is not None and self._clock() - last < self.rescan_s:
                raise ScanError('cooldown', retry_after=int(self.rescan_s - (self._clock() - last)) + 1)
            sid = uuid.uuid4().hex[:12]
            scan = {'id': sid, 'subnet': key, 'state': 'running', 'results': [], 'scanned': 0,
                    'total': len(hosts_of(net)), 'truncated': False}
            self._scans[sid] = scan
            self._order.append(sid)
            for old in self._order[:-_KEEP]:
                self._scans.pop(old, None)
            self._order = self._order[-_KEEP:]
            self._running = sid
        if background:
            threading.Thread(target=self._run, args=(scan, net), daemon=True,
                             name='camera-scan').start()
        else:
            self._run(scan, net)
        return sid

    def _one(self, host):
        with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            return self._probe(host)
        except Exception:
            return None
        finally:
            with self._lock:
                self._inflight -= 1

    def _run(self, scan, net):
        deadline = self._clock() + self.total_limit
        hosts = hosts_of(net)
        ex = ThreadPoolExecutor(max_workers=self.concurrency)
        try:
            pending = set()
            it = iter(hosts)
            exhausted = False
            while True:
                while not exhausted and len(pending) < self.concurrency and self._clock() < deadline:
                    h = next(it, None)
                    if h is None:
                        exhausted = True
                    else:
                        pending.add(ex.submit(self._one, h))
                if not pending:
                    break
                done, pending = wait(pending, timeout=0.05)
                for f in done:
                    scan['scanned'] += 1
                    r = f.result()
                    if r:
                        scan['results'].append(r)
                if self._clock() >= deadline and not exhausted:
                    scan['truncated'] = True
                    exhausted = True
                if self._clock() >= deadline and pending:
                    scan['truncated'] = True
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
            scan['results'].sort(key=lambda r: ipaddress.ip_address(r['host']))
            scan['state'] = 'done'
            with self._lock:
                self._done_at[scan['subnet']] = self._clock()
                self._running = None

    # -- 결과 ----------------------------------------------------------------
    def result(self, scan_id):
        with self._lock:
            scan = self._scans.get(scan_id)
            if scan is None:
                return None
            out = dict(scan, results=[dict(r) for r in scan['results']])
        reg = self._registered()
        for r in out['results']:
            r['registered'] = r['host'] in reg
        out['suggestions'] = suggest_ip_changes(out, reg)
        return out


def registered_hosts():
    """등록된 VIGI 카메라 주소 {host: camera_id}. DB 는 db_store 만 만진다."""
    from aot.camera_drivers.db_store import registered_hosts as _hosts
    return _hosts()


def suggest_ip_changes(scan, reg=None):
    """IP 바뀜 제안 (설계 §11 P5, Q8). 보수적 판정 — 제안만 하고 바꾸지 않는다.

    인증 전에는 같은 카메라라는 증거가 없다(모델·MAC 을 모른다). 그래서 다음을 **모두** 만족할 때만 짝을 낸다:
      · 등록된 카메라의 주소가 이번 검색 대역 안에 있는데 VIGI 로 응답하지 않았다(사라짐)
      · 등록되지 않은 VIGI 후보가 정확히 하나, 사라진 등록 카메라도 정확히 하나
    그 밖(여럿)은 짝짓지 않는다. 사용자는 후보를 직접 골라 쓸 수 있다.
    """
    reg = registered_hosts() if reg is None else reg
    try:
        net = ipaddress.ip_network(scan['subnet'])
    except ValueError:
        return []
    answered = {r['host'] for r in scan['results'] if r['kind'] == 'vigi'}
    missing = []
    for host, cid in reg.items():
        try:
            inside = ipaddress.ip_address(host) in net
        except ValueError:
            continue
        if inside and host not in answered and not scan.get('truncated'):
            missing.append((host, cid))
    cands = [r['host'] for r in scan['results'] if r['kind'] == 'vigi' and r['host'] not in reg]
    if len(missing) == 1 and len(cands) == 1 and scan.get('state') == 'done':
        return [{'camera_id': missing[0][1], 'old_host': missing[0][0], 'new_host': cands[0]}]
    return []


_mgr = None


def get_manager():
    global _mgr
    if _mgr is None:
        _mgr = ScanManager()
    return _mgr
