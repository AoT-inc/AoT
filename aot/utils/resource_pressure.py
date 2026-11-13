# -*- coding: utf-8 -*-
"""자원 압박 단계 — "지금 이 기기가 얼마나 바쁜가" 를 한 곳에서 판정한다.

시스템이 상황에 따라 스스로 비용을 줄일 때(배경 작업 미루기, 폴링 늦추기, 무거운 조회
제한) 각 손잡이가 저마다 문턱을 두지 않고 **이 판정 하나만** 보게 하려는 것이다.
설계: `.local/reports/resource-adaptive-proposal-20261108.md` (R1).

**R1 은 관찰만 한다.** 이 모듈은 아무것도 줄이지 않는다. 입력 드라이버
(`inputs/aot_resource_pressure.py`)가 단계와 신호를 Influx 에 남기고, 실측(특히 파이)과
맞춰 본 뒤에 문턱을 확정하고 손잡이를 연결한다. 그래서 문턱(`THRESHOLDS`)은 초안이다.

신호 (없으면 None — 기기마다 있는 것이 다르다):
  - PSI some avg10 — 사용률이 아니라 "일이 막혀 기다린 시간 비율". 자기 cgroup 의
    `*.pressure` 와 기기 전체 `/proc/pressure/*` 중 **나쁜 쪽**(도커에서 데몬 쪽 판정이
    웹 컨테이너의 부하를 못 보던 것을 막는다. 베어메탈에서는 둘이 같다).
  - CPU 한도 대비 사용률·스로틀 비율 — cgroup `cpu.stat` 의 증가분. 할당량(cpu.max)에
    막힌 컨테이너는 대기(PSI)보다 스로틀로 나타나, 포화를 가장 곧게 보여 준다(S2 실측:
    무난 45~73%, 포화 86~95%, 그때 CPU PSI 는 최대 39).
  - 1분 부하 ÷ cgroup 인지 코어 수 — PSI 가 없을 때만 판정에 쓴다.
  - 메모리 가용 비율 — 컨테이너 한도와 기기 전체 중 낮은 쪽.
  - 웹 p95(`web_latency`) — 폴링·API 만(페이지·로그인 제외). 웹 컨테이너가 공유 폴더에
    쓰므로 데몬에서도 보인다. **혼자서는 단계를 올리지 않는다** — 자원 신호가 받쳐 줄
    때만 판정에 들어간다(`_web_corroborated`).
  - 파이 `vcgencmd get_throttled` 현재 비트(0~3)·CPU 온도 — **부하가 아니라 하드웨어 상태**.
    현재 비트가 서 있으면 "이 기기는 지금 느리다" 로 보고 최소 '주의' 로 둔다.

단계: 0 정상 · 1 주의 · 2 과부하. 올라갈 때는 `UP_HOLD_S` 동안 이어져야(한 번 튄 값으로
오르지 않게), 내려갈 때는 `DOWN_HOLD_S` 동안 낮아야 바뀐다.
"""
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from aot.utils import system_environment

logger = logging.getLogger(__name__)

STAGE_NORMAL = 0
STAGE_WATCH = 1
STAGE_OVERLOAD = 2
STAGE_NAMES = {STAGE_NORMAL: 'normal', STAGE_WATCH: 'watch', STAGE_OVERLOAD: 'overload'}

#: 신호별 (주의, 과부하) 문턱. 일반 PC(S2, 26-11-08)로 1차 조정, 파이(S3)로 확정한다.
#: 방향: mem_available_pct 만 "낮을수록 나쁨", 나머지는 "높을수록 나쁨".
THRESHOLDS = {
    # 주의 20 은 S2 의 경고 시작점(P2 160·P3 120명)과 맞았다. 과부하는 50 에 한 번도
    # 안 닿아(포화에서 최대 39) 30 으로 — P3 120명(경고 구간) 중앙값 33.
    'cpu_psi': (20.0, 30.0),
    'memory_psi': (10.0, 30.0),     # 메모리 정체는 CPU 보다 치명적이라 낮게 (S2 미도달)
    'io_psi': (30.0, 60.0),         # SD 카드 지터를 감안해 높게 (S2 최대 3.6 — 파이에서 확정)
    'cpu_used_pct': (70.0, 85.0),   # S2: 무난 ≤73%, 경고 74~91%, 포화 86~95%
    'load_per_core': (0.8, 1.5),    # PSI 가 없을 때만 — 예전 fc_cal.busy() 의 0.8 과 같은 출발점
    'mem_available_pct': (15.0, 7.0),
    'web_p95_ms': (250.0, 1000.0),  # 폴링·API 만. 페이지 제외 후 값은 S3 로 다시 본다
}
_LOWER_IS_WORSE = {'mem_available_pct'}

#: 이만큼 높은 상태가 이어져야 단계가 올라간다(초). S2 에서 첫 로드 한 번의 튐이
#: 단계를 올리고 내림 60초에 묶여 오래 남았다 — 표본 두세 개는 이어져야 오른다.
UP_HOLD_S = 10.0
#: 이만큼 낮은 상태가 이어져야 단계가 내려간다(초).
DOWN_HOLD_S = 60.0
#: 한 프로세스 안에서 같은 판정을 다시 계산하지 않는 시간(초).
CACHE_TTL_S = 5.0
#: `vcgencmd` 는 하위 프로세스라 자주 부르지 않는다(초).
THROTTLE_TTL_S = 30.0

_PSI_RE = re.compile(r'^(some|full)\s+avg10=([\d.]+)\s+avg60=([\d.]+)\s+avg300=([\d.]+)')


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


# ── 신호 ─────────────────────────────────────────────────────────────

def parse_psi(text):
    """PSI 파일 내용 → {'some': {'avg10',...}, 'full': {...}}. 형식이 아니면 None."""
    if not text:
        return None
    out = {}
    for line in text.splitlines():
        m = _PSI_RE.match(line.strip())
        if m:
            out[m.group(1)] = {'avg10': float(m.group(2)), 'avg60': float(m.group(3)),
                               'avg300': float(m.group(4))}
    return out or None


def read_psi(resource, cgroup_root='/sys/fs/cgroup', proc_root='/proc/pressure'):
    """`resource`(cpu|memory|io) 의 PSI some avg10(%) — 자기 cgroup 과 기기 전체 중 나쁜 쪽.

    컨테이너 안이면 cgroup 의 `<resource>.pressure`(이 서비스가 기다린 시간)와
    `/proc/pressure`(기기 전체)가 둘 다 있다. 둘 중 하나만 보면 도커에서 데몬 쪽 판정이
    웹 컨테이너의 정체를 놓치거나, 그 반대가 된다. 베어메탈은 cgroup 루트에 파일이
    없어 기기 전체 하나뿐이다.
    Returns: (avg10 또는 None, 그 값을 낸 쪽 'cgroup'|'proc'|None)
    """
    best = (None, None)
    for source, path in (('cgroup', os.path.join(cgroup_root, resource + '.pressure')),
                         ('proc', os.path.join(proc_root, resource))):
        parsed = parse_psi(_read(path))
        if parsed and 'some' in parsed:
            value = parsed['some']['avg10']
            if best[0] is None or value > best[0]:
                best = (value, source)
    return best


_cpu_prev = {}   # cgroup_root -> (monotonic_t, usage_usec, throttled_usec, 직전 결과)
_cpu_lock = threading.Lock()


def parse_cpu_stat(text):
    """cgroup v2 `cpu.stat` → {'usage_usec', 'throttled_usec'} (없는 키는 빠짐)."""
    out = {}
    for line in (text or '').splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ('usage_usec', 'throttled_usec'):
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return out


def _online_cpus():
    """이 프로세스가 돌 수 있는 CPU 수(cpuset 반영)."""
    try:
        return len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def cpu_allowance(cgroup_root='/sys/fs/cgroup'):
    """쓸 수 있는 CPU 양(코어, 소수 허용) — cgroup v2 `cpu.max` 할당량과 cpuset 중 작은 쪽.

    `system_environment.cpu_cores()` 는 워커 수 산정용이라 정수로 내린다(1.5코어 → 1).
    사용률 분모로 쓰면 1.5코어 한도에서 포화가 150% 로 잘못 나오므로 따로 계산한다.
    """
    cpus = float(_online_cpus())
    parts = (_read(os.path.join(cgroup_root, 'cpu.max')) or '').split()
    if len(parts) == 2 and parts[0] != 'max':
        try:
            quota = int(parts[0]) / float(int(parts[1]))
            if quota > 0:
                return min(cpus, quota)
        except (ValueError, ZeroDivisionError):
            pass
    return cpus


def cpu_usage(cgroup_root='/sys/fs/cgroup', now=None, cores=None):
    """직전 기준점 이후 CPU 사용률(쓸 수 있는 CPU 대비 %)과 스로틀 비율(%).

    cgroup v2 `cpu.stat` 의 누적값 증가분으로 낸다. 컨테이너면 그 컨테이너 몫·한도
    기준이고, 베어메탈은 루트 cgroup(기기 전체, 루트에는 throttled_usec 가 없다)이다.
    첫 호출(기준점 없음)·카운터 리셋·v1 은 None. 1초 안에 다시 부르면 기준점을 두고
    직전 결과를 돌려준다(동시에 부른 스레드가 기준점을 망가뜨리지 않게).
    `throttled_usec` 는 CPU 마다의 스로틀 시간을 더한 값이라 CPU 수로도 나눈다 [커널 동작,
    판정에는 쓰지 않고 기록만].
    Returns: (cpu_used_pct, cpu_throttled_pct)
    """
    stat = parse_cpu_stat(_read(os.path.join(cgroup_root, 'cpu.stat')))
    if 'usage_usec' not in stat:
        return None, None
    t = time.monotonic() if now is None else now
    usage, throttled = stat['usage_usec'], stat.get('throttled_usec')
    prev = _cpu_prev.get(cgroup_root)
    if prev and t - prev[0] < 1.0:
        return prev[3]
    if not prev or usage < prev[1]:
        _cpu_prev[cgroup_root] = (t, usage, throttled, (None, None))
        return None, None
    elapsed_us = (t - prev[0]) * 1e6
    n = cores or cpu_allowance(cgroup_root) or 1.0
    used = max(0.0, min(100.0, (usage - prev[1]) * 100.0 / (elapsed_us * n)))
    thr = None
    if throttled is not None and prev[2] is not None and throttled >= prev[2]:
        thr = max(0.0, min(100.0, (throttled - prev[2]) * 100.0
                           / (elapsed_us * _online_cpus())))
    result = (used, thr)
    _cpu_prev[cgroup_root] = (t, usage, throttled, result)
    return result


def load_per_core():
    try:
        return os.getloadavg()[0] / float(system_environment.cpu_cores() or 1)
    except (OSError, AttributeError):
        return None


def mem_available_pct(cgroup_root='/sys/fs/cgroup', meminfo_path='/proc/meminfo'):
    """쓸 수 있는 메모리 비율(%). 컨테이너 한도(cgroup v2 memory.max)가 있으면 그 기준.

    cgroup 의 `memory.current` 에는 회수 가능한 페이지 캐시가 섞여 있어, `memory.stat` 의
    `inactive_file` 을 빼서 "실제로 쓰는 양" 에 가깝게 본다.
    """
    candidates = [_container_mem_available_pct(cgroup_root), _host_mem_available_pct(meminfo_path)]
    candidates = [c for c in candidates if c is not None]
    # 컨테이너 한도와 기기 전체 중 낮은 쪽 — 어느 쪽이 모자라도 모자란 것이다.
    return min(candidates) if candidates else None


def _container_mem_available_pct(cgroup_root):
    # (한도, 사용량, stat, 페이지 캐시 키) — cgroup v2, 그다음 v1
    layouts = (
        ('memory.max', 'memory.current', 'memory.stat', 'inactive_file '),
        ('memory/memory.limit_in_bytes', 'memory/memory.usage_in_bytes',
         'memory/memory.stat', 'total_inactive_file '),
    )
    for f_max, f_cur, f_stat, cache_key in layouts:
        raw_max = (_read(os.path.join(cgroup_root, f_max)) or '').strip()
        raw_cur = (_read(os.path.join(cgroup_root, f_cur)) or '').strip()
        if not raw_max or raw_max == 'max' or not raw_cur:
            continue
        try:
            limit = int(raw_max)
            used = int(raw_cur)
            for line in (_read(os.path.join(cgroup_root, f_stat)) or '').splitlines():
                if line.startswith(cache_key):
                    used -= int(line.split()[1])
                    break
            # v1 의 "한도 없음" 은 아주 큰 수다
            if 0 < limit < (1 << 50):
                return max(0.0, min(100.0, (limit - max(used, 0)) * 100.0 / limit))
        except ValueError:
            pass
    return None


def _host_mem_available_pct(meminfo_path):
    total = avail = None
    for line in (_read(meminfo_path) or '').splitlines():
        if line.startswith('MemTotal:'):
            total = float(line.split()[1])
        elif line.startswith('MemAvailable:'):
            avail = float(line.split()[1])
    if total and avail is not None:
        return avail * 100.0 / total
    return None


def cpu_temperature_c(path='/sys/class/thermal/thermal_zone0/temp'):
    raw = (_read(path) or '').strip()
    try:
        return int(raw) / 1000.0 if raw else None
    except ValueError:
        return None


_throttle_cache = {'t': -1e9, 'value': None}


def parse_throttled(text):
    """`throttled=0x50005` → 정수. 형식이 아니면 None."""
    m = re.search(r'throttled=(0x[0-9a-fA-F]+)', text or '')
    return int(m.group(1), 16) if m else None


def throttled_bits(now=None):
    """파이 `vcgencmd get_throttled` 의 비트. vcgencmd 가 없으면(파이 아님) None.

    비트 0 저전압 · 1 주파수 제한 · 2 스로틀 · 3 소프트 온도 제한 (현재),
    16~19 는 같은 항목의 "부팅 이후 있었음". 펌웨어마다 해석이 다를 수 있다.
    파이 위 도커 컨테이너에는 보통 vcgencmd 가 없어 None 이다(베어메탈 설치에서만 보인다).
    """
    t = time.monotonic() if now is None else now
    if t - _throttle_cache['t'] < THROTTLE_TTL_S:
        return _throttle_cache['value']
    value = None
    exe = shutil.which('vcgencmd') or ('/usr/bin/vcgencmd' if os.path.exists('/usr/bin/vcgencmd') else None)
    if exe:
        try:
            out = subprocess.run([exe, 'get_throttled'], capture_output=True, text=True, timeout=2)
            value = parse_throttled(out.stdout)
        except (OSError, subprocess.SubprocessError):
            value = None
    _throttle_cache.update(t=t, value=value)
    return value


def web_p95_ms():
    try:
        from aot.utils import web_latency
        agg = web_latency.aggregate()
    except Exception:
        return None
    return agg.get('p95_ms') if agg else None


def read_signals():
    """지금의 신호를 모두 읽는다. 없는 것은 None."""
    cpu_psi, psi_source = read_psi('cpu')
    memory_psi, _ = read_psi('memory')
    io_psi, _ = read_psi('io')
    with _cpu_lock:
        cpu_used_pct, cpu_throttled_pct = cpu_usage()
    bits = throttled_bits()
    return {
        'cpu_psi': cpu_psi,
        'memory_psi': memory_psi,
        'io_psi': io_psi,
        'psi_source': psi_source,
        'cpu_used_pct': cpu_used_pct,
        'cpu_throttled_pct': cpu_throttled_pct,
        'load_per_core': load_per_core(),
        'mem_available_pct': mem_available_pct(),
        'web_p95_ms': web_p95_ms(),
        'throttled_bits': bits,
        'temperature_c': cpu_temperature_c(),
    }


# ── 판정 ─────────────────────────────────────────────────────────────

def _level(name, value):
    if value is None:
        return STAGE_NORMAL
    watch, overload = THRESHOLDS[name]
    if name in _LOWER_IS_WORSE:
        if value < overload:
            return STAGE_OVERLOAD
        return STAGE_WATCH if value < watch else STAGE_NORMAL
    if value >= overload:
        return STAGE_OVERLOAD
    return STAGE_WATCH if value >= watch else STAGE_NORMAL


#: 웹 p95 를 판정에 넣으려면 자원 신호 중 하나가 이만큼(주의 문턱 대비) 올라 있어야 한다.
WEB_CORROBORATION = 0.5


def _web_corroborated(signals, resource_names):
    """웹 p95 가 "대기" 를 뜻한다고 볼 근거가 자원 신호에 있는가.

    웹 p95 만으로는 대기와 원래 무거운 요청(구획 환경 시계열 5~7초·대지 요약·래스터 타일)을
    가르지 못한다. 맥미니 8084(26-11-10)는 CPU 0.9%·PSI 0.18 로 한가했는데 p95 758ms 하나로
    주의~과부하에 올라 화면 폴링을 ×4 늦췄다. S2 원자료(26-11-08)로 보면 사용자 1~20명에서도
    표본의 17~45% 가 p95 하나로 '주의' 였고, 이 조건을 걸면 그 구간은 0%, 실제 포화(P3 120명
    이상)는 70% 안팎을 그대로 잡는다.

    근거: 높을수록 나쁜 신호는 주의 문턱의 `WEB_CORROBORATION` 배 이상, 메모리 가용 비율은
    주의 문턱 미만(가용 메모리 20% 대는 맥·도커에서 평소 값이라 반으로 늦추지 않는다).
    """
    for name in resource_names:
        value = signals.get(name)
        if value is None:
            continue
        watch = THRESHOLDS[name][0]
        if name in _LOWER_IS_WORSE:
            if value < watch:
                return True
        elif value >= watch * WEB_CORROBORATION:
            return True
    return False


def raw_stage(signals):
    """히스테리시스 없이 지금 신호만으로 본 단계와 그 이유(신호 이름 목록).

    부하 평균은 PSI 가 하나도 없을 때만 본다 — PSI 가 있으면 그쪽이 더 정확하고,
    부하 평균은 I/O 대기와 CPU 대기를 가르지 못한다.

    웹 p95 는 자원 신호가 받쳐 줄 때만 본다(`_web_corroborated`).
    """
    names = ['cpu_psi', 'memory_psi', 'io_psi', 'cpu_used_pct', 'mem_available_pct']
    if all(signals.get(k) is None for k in ('cpu_psi', 'memory_psi', 'io_psi')):
        names.append('load_per_core')
    if _web_corroborated(signals, names):
        names.append('web_p95_ms')
    stage, reasons = STAGE_NORMAL, []
    for name in names:
        level = _level(name, signals.get(name))
        if level > stage:
            stage, reasons = level, [name]
        elif level == stage and level > STAGE_NORMAL:
            reasons.append(name)
    bits = signals.get('throttled_bits')
    if bits is not None and bits & 0xF:
        reasons.append('throttled')
        if stage < STAGE_WATCH:
            stage, reasons = STAGE_WATCH, ['throttled']
    return stage, reasons


class StageTracker:
    """올라갈 때는 `up_hold_s`, 내려갈 때는 `hold_s` 동안 그 상태가 이어져야 바뀐다.

    올라갈 때는 그 사이 본 값 중 **가장 낮은 것**까지만 — 한 번 튄 과부하 사이에 주의가
    섞였으면 주의로 오른다. 내려갈 때는 그 사이 본 값 중 **가장 높은 것**까지만 — 과부하
    에서 60초 동안 주의·정상이 섞였으면 주의로 간다.
    표본 간격이 유지 시간보다 길면 표본 두 번으로 바뀐다(표본으로 본 것이 전부다).
    """

    def __init__(self, hold_s=DOWN_HOLD_S, up_hold_s=UP_HOLD_S):
        self.hold_s = hold_s
        self.up_hold_s = up_hold_s
        self.stage = STAGE_NORMAL
        self._lower_since = None
        self._lower_max = STAGE_NORMAL
        self._higher_since = None
        self._higher_min = STAGE_NORMAL

    def update(self, raw, now):
        if raw > self.stage:
            self._lower_since = None
            if self._higher_since is None:
                self._higher_since, self._higher_min = now, raw
            else:
                self._higher_min = min(self._higher_min, raw)
            if now - self._higher_since >= self.up_hold_s:
                self.stage = self._higher_min
                # 더 오를지는 지금부터 다시 센다
                self._higher_since = now if raw > self.stage else None
                self._higher_min = raw
        elif raw == self.stage:
            self._higher_since = None
            self._lower_since = None
        elif self._lower_since is None:
            self._higher_since = None
            self._lower_since = now
            self._lower_max = raw
        else:
            self._lower_max = max(self._lower_max, raw)
            if now - self._lower_since >= self.hold_s:
                self.stage = self._lower_max
                # 더 내려갈지는 지금부터 다시 센다
                self._lower_since = now if raw < self.stage else None
                self._lower_max = raw
        return self.stage


_tracker = StageTracker()
_cache = {'t': -1e9, 'snapshot': None}
_cache_lock = threading.Lock()


def current(now=None):
    """이 프로세스가 보는 지금의 압박 상태(`CACHE_TTL_S` 동안 재사용).

    Returns: dict — 신호 전부 + 'raw_stage', 'stage', 'stage_name', 'reasons'.
    판정 중 예외가 나면 직전 단계를 그대로 둔다 — 판정 실패가 시스템을 멈추게 하지도,
    단계를 엉뚱하게 바꾸지도 않는다. 돌려준 dict 는 공유되므로 고치지 말 것.
    """
    t = time.monotonic() if now is None else now
    with _cache_lock:
        if _cache['snapshot'] is not None and t - _cache['t'] < CACHE_TTL_S:
            return _cache['snapshot']
    # 파일 읽기·vcgencmd(최대 2초)는 잠금 밖에서 — 동시에 부른 쪽이 기다리지 않게.
    try:
        signals = read_signals()
        raw, reasons = raw_stage(signals)
        failed = False
    except Exception:
        logger.warning('resource pressure 판정 실패', exc_info=True)
        signals, raw, reasons, failed = {}, None, ['error'], True
    with _cache_lock:
        stage = _tracker.stage if failed else _tracker.update(raw, t)
        snapshot = dict(signals, raw_stage=raw, stage=stage,
                        stage_name=STAGE_NAMES[stage], reasons=reasons)
        _cache.update(t=t, snapshot=snapshot)
        return snapshot


# ── 손잡이: 배경 작업 미루기 (R3) ────────────────────────────────────

DEFER_ENV = 'AOT_RESOURCE_DEFER'
#: 작업 이름 → 이번 연속 미룸이 시작된 monotonic 시각
_deferred = {}
_deferred_lock = threading.Lock()


def should_defer(job, max_defer_s, min_stage=STAGE_WATCH, now=None):
    """배경 작업 `job` 을 이번 차례에 미룰까.

    압박 단계가 `min_stage`(기본 '주의') 이상이면 미룬다. 다만 연속으로 미룬 지
    `max_defer_s` 가 지나면 더는 미루지 않고 돌린다 — 바쁜 상태가 길게 이어지는 기기
    (작은 파이)에서 보존 점검·보정이 영영 안 도는 것을 막는다. 단계가 내려가 한 번
    돌면 연속 미룸 기록을 지운다.

    판정 자체가 실패하면 미루지 않는다(기존 동작 = 늘 돌림).
    환경변수 `AOT_RESOURCE_DEFER=0` 이면 미루지 않는다(운영자 끄기, 시험 기본값).
    """
    if os.environ.get(DEFER_ENV, '1') == '0':
        return False
    t = time.monotonic() if now is None else now
    try:
        snap = current(now=now)
        stage = snap.get('stage', STAGE_NORMAL)
    except Exception:
        return False
    with _deferred_lock:
        if stage < min_stage:
            _deferred.pop(job, None)
            return False
        first = _deferred.setdefault(job, t)
        waited = t - first
        if waited >= max_defer_s:
            _deferred.pop(job, None)
            logger.warning('[%s] 압박 단계 %s(%s) 지만 %.1f시간 미뤄 와서 이번에는 돌린다',
                           job, STAGE_NAMES.get(stage), ','.join(snap.get('reasons') or []),
                           waited / 3600.0)
            return False
    logger.info('[%s] 압박 단계 %s(%s) — 다음 차례로 미룸(연속 %.0f분째)',
                job, STAGE_NAMES.get(stage), ','.join(snap.get('reasons') or []), waited / 60.0)
    return True


# ── 손잡이: 폴링 배율 (R4a) ──────────────────────────────────────────

#: 단계 → 화면 폴링 간격 배율. 서버가 응답 머리 `X-AoT-Poll-Scale` 로 알리고, 화면의
#: 전역 폴링 관리자(aot-poll-visibility.js)가 모든 반복 타이머에 곱한다(상한 ×4).
#: 일반 PC 실측(S2)에서 서버는 실패보다 대기열로 버텼다 — 요청 수를 줄이는 것이 직접 처방이다.
POLL_SCALE = {STAGE_NORMAL: 1, STAGE_WATCH: 2, STAGE_OVERLOAD: 4}
POLL_SCALE_HEADER = 'X-AoT-Poll-Scale'
#: 마지막 판정이 이보다 오래됐으면 배율을 내지 않는다(표본 스레드가 멈춘 경우 등).
PEEK_MAX_AGE_S = 30.0


def peek(max_age_s=PEEK_MAX_AGE_S, now=None):
    """마지막 판정을 **계산하지 않고** 돌려준다(없거나 낡았으면 None).

    웹 요청 경로에서 쓴다 — `current()` 는 파이에서 vcgencmd(최대 2초)를 부를 수 있어
    요청 스레드에서 돌리면 안 된다. 판정은 `start_sampler()` 의 스레드가 이어 간다.
    """
    t = time.monotonic() if now is None else now
    with _cache_lock:
        snap, at = _cache['snapshot'], _cache['t']
    if snap is None or t - at > max_age_s:
        return None
    return snap


def poll_scale(snapshot):
    """판정 → 폴링 배율(1·2·4). 판정이 없으면 1."""
    if not snapshot:
        return 1
    return POLL_SCALE.get(snapshot.get('stage'), 1)


def clear_deferral(job):
    """`job` 의 연속 미룸 기록을 지운다(손으로 돌렸을 때 등)."""
    with _deferred_lock:
        _deferred.pop(job, None)


# ── 표본 스레드 ───────────────────────────────────────────────────────

#: 표본 간격(초). 올림 지속(UP_HOLD_S 10초)을 판정하려면 그보다 촘촘해야 한다.
SAMPLE_INTERVAL_S = 5.0
_sampler = {'pid': None}


def start_sampler(interval_s=SAMPLE_INTERVAL_S):
    """이 프로세스에서 `current()` 를 주기적으로 불러 단계 추적을 이어 가는 배경 스레드.

    단계는 `current()` 를 부를 때만 갱신된다. 데몬에서 그것을 부르는 곳이 정시마다 도는
    배경 작업뿐이면 표본이 한 시간에 하나라, 10초 지속 조건이 성립하지 않고(바빠도 안
    미룸) CPU 사용률도 한 시간 평균이 된다. 측정값 입력을 켜지 않아도 판정이 살아 있게
    데몬이 이것을 띄운다. 같은 프로세스에서 두 번 불러도 하나만 돈다. 표본 하나의 비용은
    작은 파일 몇 개 읽기와 30초마다 vcgencmd 한 번이다(스레드라 메인 루프를 막지 않는다).
    """
    # 미루기를 끈 곳(시험 기본값·운영자 끄기)에서는 띄우지 않는다 — 시험이 가짜 시각으로
    # 넣은 판정을 실제 시각의 표본이 덮어써 간헐적으로 깨지지 않게.
    if os.environ.get(DEFER_ENV, '1') == '0':
        return False
    pid = os.getpid()
    with _deferred_lock:
        if _sampler['pid'] == pid:
            return False
        _sampler['pid'] = pid

    def _loop():
        while True:
            try:
                current()
            except Exception:
                logger.debug('resource pressure sample failed', exc_info=True)
            time.sleep(interval_s)

    threading.Thread(target=_loop, name='aot-resource-pressure', daemon=True).start()
    return True


def _reset_for_tests():
    _deferred.clear()
    global _tracker
    _tracker = StageTracker()
    _cache.update(t=-1e9, snapshot=None)
    _throttle_cache.update(t=-1e9, value=None)
    _cpu_prev.clear()
