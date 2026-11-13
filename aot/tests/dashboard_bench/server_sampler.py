# coding=utf-8
"""서버 쪽 표본 수집기 — 측정 실행기와 **다른 기기**에서 돌릴 수 있게 따로 둔다.

두 방식:

  docker  이 기기에서 `docker stats` 로 컨테이너 CPU·메모리를 고르게 뽑는다(로컬 스택용).
  ssh     원격 서버에 ssh 로 들어가 `pidstat -u -r`(gunicorn)·`iostat -dx`·
          `vcgencmd measure_temp / get_throttled`(파이)·`/proc/stat` 를 고르게 뽑는다.
          원격에는 아무것도 설치·저장하지 않는다(쉘 반복문 한 줄을 흘려 보낼 뿐).

출력은 CSV 한 파일(표본 한 줄 = 한 시각의 한 대상). 집계기가 이 파일을 읽는다.

    python -m aot.tests.dashboard_bench.server_sampler docker --containers aot-e2e-aot-app-1 \
        --duration 120 --interval 2 --out .local/bench/server/pc_P2.csv
    python -m aot.tests.dashboard_bench.server_sampler ssh --host aot@PC_또는_파이 \
        --duration 120 --interval 5 --out .local/bench/server/pi_P2.csv

⚠ ssh 방식은 **그 서버를 건드린다**(읽기 전용 명령뿐이지만 접속은 접속이다). 운영 서버와
라즈베리 파이에는 사용자의 승인을 받은 뒤에만 쓴다.
"""
import argparse
import csv
import re
import subprocess
import sys
import threading
import time

COLUMNS = ['ts', 'name', 'cpu_pct', 'mem_mb', 'sys_cpu_pct', 'load1',
           'temp_c', 'throttled', 'disk_util_pct', 'disk_await_ms']

_MEM = re.compile(r'([\d.]+)\s*([KMG]i?B)', re.I)
_UNIT_MB = {'kib': 1 / 1024, 'kb': 1 / 1000, 'mib': 1, 'mb': 1, 'gib': 1024, 'gb': 1000}


def parse_mem_mb(text):
    """'491.2MiB / 3GiB' → 491.2 (앞 값만, MB)."""
    m = _MEM.search(text or '')
    if not m:
        return None
    return float(m.group(1)) * _UNIT_MB.get(m.group(2).lower(), 1)


def parse_docker_stats(output, ts):
    """`docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}'` 출력 → 행 목록."""
    rows = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(',', 2)]
        if len(parts) < 3:
            continue
        try:
            cpu = float(parts[1].rstrip('%'))
        except ValueError:
            continue
        rows.append(dict(ts=ts, name=parts[0], cpu_pct=cpu, mem_mb=parse_mem_mb(parts[2])))
    return rows


# --- ssh ---------------------------------------------------------------------
#: 원격에서 도는 반복문. 한 번 도는 데 interval 초가 걸린다(pidstat 이 그 시간을 잰다).
#: 표식 줄(@@…)로 구획하고 파서가 나눠 읽는다. 없는 도구는 건너뛴다.
REMOTE_LOOP = r'''
END=$((SECONDS+{duration})); PATTERN='{pattern}'
while [ $SECONDS -lt $END ]; do
  echo "@@TS $(date +%s)"
  head -1 /proc/stat 2>/dev/null | sed 's/^/@@STAT /'
  echo "@@LOAD $(cut -d' ' -f1 /proc/loadavg 2>/dev/null)"
  if command -v vcgencmd >/dev/null 2>&1; then
    echo "@@TEMP $(vcgencmd measure_temp 2>/dev/null)"
    echo "@@THR $(vcgencmd get_throttled 2>/dev/null)"
  fi
  PIDS=$(pgrep -d, -f "$PATTERN" 2>/dev/null)
  if command -v pidstat >/dev/null 2>&1 && [ -n "$PIDS" ]; then
    if command -v iostat >/dev/null 2>&1; then
      iostat -dx -y {interval} 1 2>/dev/null | sed 's/^/@@IO /' &
    fi
    echo "@@PIDSTAT"
    pidstat -h -u -r -p "$PIDS" {interval} 1 2>/dev/null
    echo "@@END"
    wait
  else
    [ -n "$PIDS" ] && ps -o rss= -p "$PIDS" 2>/dev/null | awk '{{s+=$1}} END {{print "@@RSS " s}}'
    sleep {interval}
  fi
done
'''


def build_remote_script(duration, interval, pattern='gunicorn'):
    return REMOTE_LOOP.format(duration=int(duration), interval=int(interval), pattern=pattern)


def _stat_busy_pct(prev, cur):
    """/proc/stat 첫 줄 두 번의 차이로 전체 CPU 사용률(%)."""
    if prev is None or cur is None:
        return None
    dt = [b - a for a, b in zip(prev, cur)]
    total = sum(dt)
    if total <= 0:
        return None
    idle = dt[3] + (dt[4] if len(dt) > 4 else 0)
    return (total - idle) / total * 100.0


def parse_remote_output(text):
    """원격 반복문의 출력 → 행 목록(대상 이름 'gunicorn' 하나 + 시스템 값)."""
    rows, cur = [], None
    prev_stat = None
    mode = None
    pid_cpu, pid_mem = [], []
    io_util, io_await = [], []
    io_header = None

    def flush():
        nonlocal cur, pid_cpu, pid_mem, io_util, io_await
        if cur is not None:
            if pid_cpu:
                cur['cpu_pct'] = sum(pid_cpu)
            if pid_mem:
                cur['mem_mb'] = sum(pid_mem)
            if io_util:
                cur['disk_util_pct'] = max(io_util)
                cur['disk_await_ms'] = max(io_await) if io_await else None
            rows.append(cur)
        cur, pid_cpu, pid_mem, io_util, io_await = None, [], [], [], []

    for line in text.splitlines():
        if line.startswith('@@TS '):
            flush()
            cur = dict(ts=int(line.split()[1]), name='gunicorn')
            mode = None
        elif cur is None:
            continue
        elif line.startswith('@@STAT '):
            try:
                vals = [int(x) for x in line.split()[2:]]
            except ValueError:
                vals = None
            cur['sys_cpu_pct'] = _stat_busy_pct(prev_stat, vals)
            prev_stat = vals
        elif line.startswith('@@LOAD '):
            try:
                cur['load1'] = float(line.split()[1])
            except (IndexError, ValueError):
                pass
        elif line.startswith('@@TEMP '):
            m = re.search(r'temp=([\d.]+)', line)
            if m:
                cur['temp_c'] = float(m.group(1))
        elif line.startswith('@@THR '):
            m = re.search(r'throttled=(0x[0-9a-fA-F]+)', line)
            if m:
                cur['throttled'] = m.group(1)
        elif line.startswith('@@RSS '):
            try:
                cur['mem_mb'] = float(line.split()[1]) / 1024
            except (IndexError, ValueError):
                pass
        elif line.startswith('@@PIDSTAT'):
            mode = 'pidstat'
        elif line.startswith('@@END'):
            mode = None
        elif line.startswith('@@IO '):
            f = line[5:].split()
            if not f:
                continue
            if f[0] == 'Device':
                io_header = f              # 열 이름 — 버전마다 열 수가 달라 이름으로 찾는다
            elif io_header and len(f) == len(io_header):
                row = dict(zip(io_header, f))
                try:
                    io_util.append(float(row['%util']))
                    wait = row.get('r_await') or row.get('await')
                    if wait is not None:
                        io_await.append(float(wait))
                except (KeyError, ValueError):
                    pass
        elif mode == 'pidstat':
            # pidstat -h 의 줄: Time UID PID %usr %system %guest %wait %CPU CPU minflt/s majflt/s VSZ RSS %MEM Command
            f = line.split()
            if len(f) >= 14 and f[0].isdigit():
                try:
                    pid_cpu.append(float(f[7]))
                    pid_mem.append(float(f[12]) / 1024)
                except ValueError:
                    pass
    flush()
    return rows


def write_csv(path, rows):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in COLUMNS})


def sample_docker(containers, duration, interval):
    rows = []
    end = time.time() + duration
    while time.time() < end:
        t = time.time()
        out = subprocess.run(
            ['docker', 'stats', '--no-stream', '--format', '{{.Name}},{{.CPUPerc}},{{.MemUsage}}'] + containers,
            capture_output=True, text=True, timeout=60).stdout
        rows.extend(parse_docker_stats(out, int(t)))
        time.sleep(max(0.0, interval - (time.time() - t)))
    return rows


class DockerSampler:
    """백그라운드 스레드로 docker stats 를 계속 뽑는다 — runner 가 한 번 측정하는 동안만 켠다.

    같은 기기에서 서버와 클라이언트를 같이 돌리는 **연기 측정**용이다. 실제 실험(S2~S5)은
    서버 기기에서 이 모듈을 따로 돌려 부하가 섞이지 않게 한다.
    """

    def __init__(self, containers, interval=2.0):
        self.containers, self.interval = containers, interval
        self.rows = []
        self._stop = threading.Event()
        self._th = None

    def _loop(self):
        while not self._stop.is_set():
            t = time.time()
            try:
                out = subprocess.run(
                    ['docker', 'stats', '--no-stream', '--format',
                     '{{.Name}},{{.CPUPerc}},{{.MemUsage}}'] + self.containers,
                    capture_output=True, text=True, timeout=60).stdout
                self.rows.extend(parse_docker_stats(out, int(t)))
            except (OSError, subprocess.SubprocessError):
                pass
            self._stop.wait(max(0.0, self.interval - (time.time() - t)))

    def start(self):
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=70)
        return self.rows


def sample_ssh(host, duration, interval, pattern, ssh_opts=None, shell=False):
    script = build_remote_script(duration, interval, pattern)
    cmd = (['bash', '-c', script] if shell else
           ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10'] + (ssh_opts or []) + [host, script])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 120)
    if out.returncode not in (0, 255) and not out.stdout:
        raise SystemExit(f'수집 실패: {out.stderr[:300]}')
    if out.returncode == 255:
        raise SystemExit(f'ssh 접속 실패: {out.stderr[:300]}')
    return parse_remote_output(out.stdout)


def main(argv=None):
    ap = argparse.ArgumentParser(description='서버 표본 수집기')
    sub = ap.add_subparsers(dest='mode', required=True)
    d = sub.add_parser('docker', help='로컬 docker stats')
    d.add_argument('--containers', required=True, help='컨테이너 이름(쉼표)')
    s = sub.add_parser('ssh', help='원격 pidstat/iostat/vcgencmd (읽기 전용 명령)')
    s.add_argument('--host', required=True, help='user@host')
    s.add_argument('--pattern', default='gunicorn', help='pgrep -f 패턴(대상 프로세스)')
    s.add_argument('--ssh-opt', action='append', default=[], help='ssh 추가 옵션(예: -i key)')
    s.add_argument('--local-shell', action='store_true', help='ssh 없이 이 기기의 쉘에서 같은 반복문을 돌린다(시험용)')
    for p in (d, s):
        p.add_argument('--duration', type=float, required=True, help='수집 시간(초)')
        p.add_argument('--interval', type=float, default=2.0 if p is d else 5.0)
        p.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    import os
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    if args.mode == 'docker':
        rows = sample_docker(args.containers.split(','), args.duration, args.interval)
    else:
        rows = sample_ssh(args.host, args.duration, args.interval, args.pattern,
                          args.ssh_opt, shell=args.local_shell)
    write_csv(args.out, rows)
    print(f'{len(rows)}행 저장: {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
