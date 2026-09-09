# -*- coding: utf-8 -*-
#
# system_environment.py - Detect the runtime environment (Raspberry Pi,
# Debian/generic Linux, Docker) and derive environment-appropriate values
# such as the recommended gunicorn thread count.
#
# Standard library only: this module is imported by install/gunicorn_conf.py
# before the application (and its dependencies) are loaded, and by the aot
# daemon at startup.
#
import os
import shutil

THREADS_MIN = 4
THREADS_MAX = 16
THREADS_MAX_LOW_RESOURCE = 6
LOW_MEMORY_GB = 2

PLATFORM_RASPBERRY_PI = 'raspberry_pi'
PLATFORM_DOCKER = 'docker'
PLATFORM_DEBIAN = 'debian'


def _read_file(path):
    try:
        with open(path, 'r', errors='ignore') as f:
            return f.read()
    except OSError:
        return None


def is_docker():
    if os.environ.get('DOCKER_CONTAINER', '') == 'TRUE':
        return True
    return os.path.exists('/.dockerenv')


def pi_model():
    """Return the Raspberry Pi model string, or None if not a Pi."""
    model = _read_file('/proc/device-tree/model')
    if model and 'raspberry pi' in model.lower():
        return model.strip('\x00').strip()
    return None


def os_release_name():
    data = _read_file('/etc/os-release') or ''
    for line in data.splitlines():
        if line.startswith('PRETTY_NAME='):
            return line.split('=', 1)[1].strip().strip('"')
    return None


def cpu_cores():
    """CPU cores available to this process. In a container with a CPU
    quota (cgroup v2 cpu.max or v1 cfs quota), the quota wins over the
    host core count."""
    host_cores = os.cpu_count() or 2

    # cgroup v2
    cpu_max = _read_file('/sys/fs/cgroup/cpu.max')
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2 and parts[0] != 'max':
            try:
                quota = int(parts[0]) / int(parts[1])
                if quota > 0:
                    return max(1, min(host_cores, int(quota)))
            except (ValueError, ZeroDivisionError):
                pass

    # cgroup v1
    quota_s = _read_file('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
    period_s = _read_file('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
    if quota_s and period_s:
        try:
            quota_v = int(quota_s)
            period_v = int(period_s)
            if quota_v > 0 and period_v > 0:
                return max(1, min(host_cores, quota_v // period_v))
        except ValueError:
            pass

    return host_cores


def mem_total_gb():
    """Memory available to this process in GB. A container memory limit
    (cgroup v2 memory.max or v1 limit_in_bytes) wins over host MemTotal."""
    host_gb = None
    meminfo = _read_file('/proc/meminfo') or ''
    for line in meminfo.splitlines():
        if line.startswith('MemTotal:'):
            try:
                host_gb = int(line.split()[1]) / 1024.0 / 1024.0
            except (ValueError, IndexError):
                pass
            break

    for path in ('/sys/fs/cgroup/memory.max',
                 '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        raw = _read_file(path)
        if raw and raw.strip() != 'max':
            try:
                limit_gb = int(raw) / (1024.0 ** 3)
                # Absurdly large values mean "no limit" (cgroup v1 default)
                if limit_gb < 1024:
                    if host_gb is None:
                        return round(limit_gb, 2)
                    return round(min(limit_gb, host_gb), 2)
            except ValueError:
                pass

    return round(host_gb, 2) if host_gb is not None else None


def detect():
    """Return a snapshot dict describing the runtime environment."""
    model = pi_model()
    if is_docker():
        platform_type = PLATFORM_DOCKER
    elif model:
        platform_type = PLATFORM_RASPBERRY_PI
    else:
        platform_type = PLATFORM_DEBIAN

    uname = os.uname()

    return {
        'platform_type': platform_type,
        'pi_model': model,
        'os_release': os_release_name(),
        'kernel': f'{uname.sysname} {uname.release} {uname.machine}',
        'hostname': uname.nodename,
        'cpu_cores': cpu_cores(),
        'mem_total_gb': mem_total_gb(),
        'capabilities': {
            'gpio': shutil.which('gpio') is not None,
            'i2c': bool(_glob_i2c()),
            'vcgencmd': shutil.which('vcgencmd') is not None,
            'journalctl': shutil.which('journalctl') is not None,
            'ifconfig': shutil.which('ifconfig') is not None,
            'ip': shutil.which('ip') is not None,
            'dmesg': shutil.which('dmesg') is not None,
        },
    }


def _glob_i2c():
    import glob
    return glob.glob('/dev/i2c-*')


def recommended_threads(env=None):
    """Recommended gunicorn thread count for this environment.
    Heuristic: 2 threads per core (I/O-bound app), capped lower on
    Raspberry Pi / low-memory hosts, clamped to [THREADS_MIN, THREADS_MAX].
    """
    if env is None:
        env = detect()
    threads = (env.get('cpu_cores') or 2) * 2
    mem_gb = env.get('mem_total_gb')
    low_resource = (env.get('platform_type') == PLATFORM_RASPBERRY_PI
                    or (mem_gb is not None and mem_gb < LOW_MEMORY_GB))
    if low_resource:
        threads = min(threads, THREADS_MAX_LOW_RESOURCE)
    return max(THREADS_MIN, min(threads, THREADS_MAX))


WORKERS_MAX = 4
# 워커 하나가 앱을 통째로 적재한다(실측 2026-09-09 로컬 도커: RSS 404MB,
# 마스터는 23MB). 여유를 얹어 0.7GB 로 잡는다 — 캐시가 붙으면서 자란다.
WORKER_MEM_GB = 0.7
# 데몬·DB·OS 몫으로 남겨 두는 양. 이걸 안 빼면 메모리가 빠듯한 기기에서
# 워커끼리 서로를 굶긴다.
RESERVED_MEM_GB = 1.0


def recommended_workers(env=None):
    """이 환경에 맞는 gunicorn 워커 수.

    스레드(gthread)는 I/O 대기에만 겹쳐 돌 뿐, 파이썬 코드는 GIL 때문에 프로세스
    하나 안에서 줄을 선다. 실측(라즈베리파이 4B 2026-08-24): 동시 요청을 1→12 로
    올려도 처리량이 3.8→3.5 req/s 로 그대로이고, 그때 시스템은 4코어 중 34~52%
    만 쓴다. 로컬 도커에서도 워커 1개가 코어 1.7개까지만 올라갔다. 프로세스를
    늘리는 것만이 파이썬 구간을 실제로 병렬화한다.

    다만 **메모리가 먼저 걸린다.** 워커마다 앱을 통째로 올리므로 코어 수와
    "쓸 수 있는 메모리 ÷ 워커 한 개 몫" 중 작은 쪽을 택한다. 라즈베리파이와
    저메모리 기기는 1개로 둔다 — 늘려서 얻는 것보다 스왑으로 잃는 것이 크다.

    ⚠ 늘린 뒤에는 **SQLite 쓰기 경합**이 다음 병목 후보다. WAL 이라 읽기는
    괜찮지만 SD 카드 위에서 N 개 프로세스가 쓰기를 다투는 것은 재보기 전에는
    모른다(docs/design/scheduler-process-separation.md 5절).
    """
    if env is None:
        env = detect()
    cores = env.get('cpu_cores') or 1
    mem_gb = env.get('mem_total_gb')

    if (env.get('platform_type') == PLATFORM_RASPBERRY_PI
            or (mem_gb is not None and mem_gb < LOW_MEMORY_GB)):
        return 1

    by_mem = WORKERS_MAX
    if mem_gb:
        by_mem = int((mem_gb - RESERVED_MEM_GB) / WORKER_MEM_GB)
    return max(1, min(cores, by_mem, WORKERS_MAX))


def resolve_gunicorn_workers():
    """(workers, source) — 'env' 면 GUNICORN_WORKERS 로 지정된 값이다.

    스레드와 달리 DB 설정을 두지 않는다. 워커 수는 메모리를 직접 먹는 값이라
    화면에서 바꾸다 기기를 재우기 쉽고, 바꾸려면 어차피 재시작이 필요하다.
    """
    env_value = os.environ.get('GUNICORN_WORKERS')
    if env_value:
        try:
            return max(1, min(int(env_value), WORKERS_MAX * 2)), 'env'
        except ValueError:
            pass
    return recommended_workers(), 'auto'


def resolve_gunicorn_threads(database_path=None):
    """Resolve the effective gunicorn thread count and its source.

    Priority: GUNICORN_THREADS env var > manual setting in the settings DB
    (misc.gunicorn_threads, NULL = auto) > automatic recommendation.

    Returns (threads, source) where source is 'env' | 'manual' | 'auto'.
    Never raises: any failure falls back to the automatic recommendation
    so service startup cannot be blocked by this resolution.
    """
    env_value = os.environ.get('GUNICORN_THREADS')
    if env_value:
        try:
            return _clamp(int(env_value)), 'env'
        except ValueError:
            pass

    if database_path and os.path.exists(database_path):
        try:
            import sqlite3
            con = sqlite3.connect(database_path, timeout=3)
            try:
                row = con.execute(
                    'SELECT gunicorn_threads FROM misc LIMIT 1').fetchone()
            finally:
                con.close()
            if row and row[0]:
                return _clamp(int(row[0])), 'manual'
        except Exception:
            # Missing column (pre-migration DB), locked/corrupt DB, etc.
            pass

    return recommended_threads(), 'auto'


def _clamp(value):
    return max(THREADS_MIN, min(value, THREADS_MAX * 2))
