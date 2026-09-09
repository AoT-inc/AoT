# -*- coding: utf-8 -*-
#
# gunicorn_conf.py - Environment-adaptive gunicorn settings for aotflask.
#
# Thread count priority:
#   1. GUNICORN_THREADS environment variable
#   2. Manual setting in the settings DB (misc.gunicorn_threads, NULL = auto)
#   3. Automatic recommendation from the detected environment
#      (cores, memory, Raspberry Pi / Docker limits)
#
# Resolution never raises — any failure falls back to the automatic value,
# so service startup cannot be blocked here.
#
# ─────────────────────────────────────────────────────────────────────────────
# workers 를 1 로 묶어 두던 제약이 풀렸다(2026-09-09).
#
# 예전 이유는 스케줄러였다: `create_app()` 이 `AISchedulerService.init_app()` 을
# 부르고 그것이 영구 잡스토어를 물린 BackgroundScheduler 를 띄우는데, 스케줄러
# 인스턴스는 모듈 전역(프로세스당 하나)이고 프로세스 사이를 조율하는 장치가
# 없었다. `max_instances: 1` 은 한 스케줄러 안에서만 유효하다. 그래서 workers=N
# 이면 예약이 최대 N 번 발화하고, 그 예약에는 **장치 제어가 포함된다.**
#
# 이제 예약을 **실행하는 프로세스는 데몬 하나뿐**이다 — `create_app()` 의
# `run_scheduler` 기본값이 False 이고 `aot_daemon.py` 만 True 로 부른다. 웹
# 워커는 스케줄러를 멈춘 채(paused) 붙여 등록·해제만 하고 실행하지 않는다.
# 근거와 함정은 docs/design/scheduler-process-separation.md 7절.
#
# ⚠ `preload_app = True` 는 여전히 답이 아니다. 앱 팩토리가 fork 전 마스터에서
# 한 번 돌지만 **스케줄러 스레드는 fork 된 자식에게 상속되지 않는다.** 지금은
# 데몬이 실행자라 웹에서는 무해해 보이지만, 켜 두면 다음 사람이 같은 함정을
# 다시 밟는다.
#
# 남는 성능은 실재한다 — 라즈베리파이 4B 실측(2026-08-24): 동시 요청을 1→12 로
# 올려도 처리량이 3.8→3.5 req/s 로 그대로이고(GIL 에 묶인 Python 구간), 그때
# 시스템은 4코어 중 34~52% 만 쓴다. 로컬 도커 실측(2026-09-08)도 같다: 대시보드
# 를 열 때 워커가 코어 4개 중 1.7개까지만 올라갔다.
#
# ⚠ **늘리고 나서 다시 재라.** SQLite 쓰기 경합이 다음 병목 후보다 — WAL 이라
# 읽기는 괜찮지만, SD 카드 위에서 N 개 프로세스가 쓰기를 다투는 것은 재보기
# 전에는 모른다. 워커 수는 추측이 아니라 그 측정으로 정한다.
#
# 프로세스 메모리에 남아 워커를 늘리면 갈라지는 것들(전부 경미, 안전 문제 아님):
#   - routes_geo._openmeteo_fail_until — 상류 장애 시 60초 창에서 호출이 N 배
#   - site_summary._CACHE(30초) — 적중률이 떨어져 재계산이 는다
#   - flask-caching 은 해당 없음 — 최초 커밋부터 FileSystemCache 라 공유된다
# ─────────────────────────────────────────────────────────────────────────────
#
import os
import sys

_INSTALL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _INSTALL_DIR not in sys.path:
    sys.path.insert(0, _INSTALL_DIR)

from aot.utils.system_environment import (detect, resolve_gunicorn_threads,
                                          resolve_gunicorn_workers)

# Mirrors aot.config DB path resolution without importing the full config
# (which pulls flask_babel and the rest of the app at master startup).
# Must NOT require 'databases' to already exist under AOT_LOCAL_DIR -- see
# the matching comment in aot/config/__init__.py.
_local_dir = os.environ.get('AOT_LOCAL_DIR')
if _local_dir:
    _db_path = os.path.join(_local_dir, 'databases', 'aot.db')
else:
    _db_path = os.path.join(_INSTALL_DIR, 'aot', 'databases', 'aot.db')

_env = detect()
_threads, _source = resolve_gunicorn_threads(database_path=_db_path)
_workers, _worker_source = resolve_gunicorn_workers()

workers = _workers
worker_class = 'gthread'
threads = _threads
timeout = 300

print(
    f"[gunicorn_conf] platform={_env['platform_type']} "
    f"cores={_env['cpu_cores']} mem={_env['mem_total_gb']}GB "
    f"-> workers={workers} (source={_worker_source}) "
    f"threads={threads} (source={_source})",
    flush=True)
